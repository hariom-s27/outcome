"""Shared LLM state in Postgres: cost ledger (P2-09), in-flight slots + 429 cool-down (P2-07),
circuit breaker (P2-29). Every worker sees the same rows, so the caps are global.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from app import db


@dataclass
class LedgerRow:
    job_id: str | None
    purpose: str
    attempt: int
    model_requested: str
    status: str
    model_returned: str | None = None
    model_mismatch: bool = False
    http_status: int | None = None
    finish_reason: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_reasoning: int | None = None
    tokens_cached: int | None = None
    cost_reported: float | None = None
    cost_computed: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    reasoning_effort: str | None = None  # P2-31: effort value sent, None = no parameter
    reasoning_param_dropped: bool = False  # P2-31: gateway refused it, retried without
    tokens_estimated: int | None = None  # P2-36: pre-call high-side estimate of tokens_in
    cost_original: float | None = None  # cache-hit rows: cost of the call that filled it


_COLUMNS = list(LedgerRow.__dataclass_fields__)

# PR-74: the cost every fuse, total and job metadata counts is max(reported, computed). The
# gateway once reported $0 for a paid model; the computed figure then still counts. Both raw
# numbers stay in their own ledger columns.
COUNTED_COST_SQL = "greatest(coalesce(cost_reported, 0), cost_computed)"


def counted_cost(reported: float | None, computed: float) -> float:
    """PR-74 in Python (same rule as COUNTED_COST_SQL)."""
    return max(reported or 0.0, computed)


@dataclass(frozen=True)
class SharedState:
    """llm_state as one caller sees it (P2-07 cool-down, P2-29/P2-33 breaker)."""

    cooldown_s: float = 0.0  # seconds left on the shared 429 cool-down
    open_until: datetime | None = None  # breaker pause end; None = breaker closed
    breaker_s: float = 0.0  # seconds left on the pause; 0 = pause over (half-open)
    probe_held: bool = False  # half-open: a live caller holds the single probe


@dataclass
class DocUsage:
    calls: int = 0  # paid attempts (cache hits excluded)
    cost_counted: float = 0.0  # PR-74: sum of max(reported, computed)
    extra: dict[str, Any] = field(default_factory=dict)


class LLMStore:
    def __init__(self, database_url: str):
        self._url = database_url
        self._conn: psycopg.Connection | None = None

    def _c(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = db.connect(self._url, autocommit=True)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    # --- ledger -------------------------------------------------------------------------

    def record(self, row: LedgerRow) -> None:
        cols = ", ".join(_COLUMNS)
        marks = ", ".join(["%s"] * len(_COLUMNS))
        self._c().execute(
            f"INSERT INTO llm_calls ({cols}) VALUES ({marks})",
            [getattr(row, c) for c in _COLUMNS],
        )

    def doc_usage(self, job_id: str) -> DocUsage:
        calls, cost = (
            self._c()
            .execute(
                f"SELECT count(*), coalesce(sum({COUNTED_COST_SQL}), 0) FROM llm_calls "
                "WHERE job_id = %s AND NOT cache_hit",
                (job_id,),
            )
            .fetchone()
        )
        return DocUsage(calls=int(calls), cost_counted=float(cost))

    def total_spend(self) -> float:
        (total,) = (
            self._c()
            .execute(f"SELECT coalesce(sum({COUNTED_COST_SQL}), 0) FROM llm_calls")
            .fetchone()
        )
        return float(total)

    def job_metadata(self, job_id: str, latency_ms: int) -> dict[str, Any]:
        """Contract metadata block for one job, built from its ledger rows (R21)."""
        rows = (
            self._c()
            .execute(
                "SELECT model_requested, count(*), sum(tokens_in), sum(tokens_out), "
                f"sum({COUNTED_COST_SQL}), sum(cost_computed), "
                "bool_or(model_mismatch), coalesce(sum(tokens_reasoning), 0), "
                "bool_or(reasoning_param_dropped), max(reasoning_effort), "
                "coalesce(sum(cost_reported), 0) "
                "FROM llm_calls WHERE job_id = %s AND NOT cache_hit GROUP BY model_requested "
                "ORDER BY model_requested",
                (job_id,),
            )
            .fetchall()
        )
        cache_hits, cache_cost = (
            self._c()
            .execute(
                "SELECT count(*), coalesce(sum(cost_original), 0) FROM llm_calls "
                "WHERE job_id = %s AND cache_hit",
                (job_id,),
            )
            .fetchone()
        )
        models: dict[str, Any] = {}
        meta: dict[str, Any] = {
            "model_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "latency_ms": max(0, int(latency_ms)),
        }
        computed = reported = 0.0
        reasoning = 0
        mismatch = dropped = False
        efforts: set[str] = set()
        for model, calls, t_in, t_out, cost, cost_c, mm, r_tok, r_drop, r_eff, cost_r in rows:
            models[model] = {
                "calls": int(calls),
                "tokens_in": int(t_in or 0),
                "tokens_out": int(t_out or 0),
                "cost_usd": round(float(cost or 0.0), 6),
            }
            meta["model_calls"] += int(calls)
            meta["tokens_in"] += int(t_in or 0)
            meta["tokens_out"] += int(t_out or 0)
            meta["cost_usd"] += float(cost or 0.0)
            computed += float(cost_c or 0.0)
            reported += float(cost_r or 0.0)
            reasoning += int(r_tok)
            mismatch = mismatch or bool(mm)
            dropped = dropped or bool(r_drop)
            if r_eff:
                efforts.add(r_eff)
        meta["cost_usd"] = round(meta["cost_usd"], 6)
        if models:
            meta["models"] = models
            meta["cost_computed_usd"] = round(computed, 6)
            meta["cost_reported_usd"] = round(reported, 6)
            meta["tokens_reasoning"] = reasoning
        returned = [
            r[0]
            for r in self._c()
            .execute(
                "SELECT DISTINCT model_returned FROM llm_calls WHERE job_id = %s "
                "AND model_returned IS NOT NULL ORDER BY 1",
                (job_id,),
            )
            .fetchall()
        ]
        if returned:
            meta["models_returned"] = returned  # R28: the id strings the gateway reported
        if efforts:
            meta["reasoning_effort"] = ",".join(sorted(efforts))
        if dropped:
            meta["reasoning_param_dropped"] = True
        if mismatch:
            meta["model_mismatch"] = True
        if cache_hits:
            meta["cache_hits"] = int(cache_hits)
            # what this job would have cost without the dev cache (graders have none)
            meta["cost_uncached_usd"] = round(meta["cost_usd"] + float(cache_cost), 6)
        return meta

    # --- in-flight slots (P2-07) --------------------------------------------------------

    def ensure_slots(self, cap: int) -> None:
        self._c().execute(
            "INSERT INTO llm_slots (slot) SELECT generate_series(0, %s - 1) ON CONFLICT DO NOTHING",
            (cap,),
        )

    def try_acquire_slot(self, holder: str, cap: int, lease_s: float) -> int | None:
        row = (
            self._c()
            .execute(
                "UPDATE llm_slots SET holder = %(h)s, "
                "lease_until = now() + make_interval(secs => %(lease)s) "
                "WHERE slot = (SELECT slot FROM llm_slots WHERE slot < %(cap)s "
                "AND (lease_until IS NULL OR lease_until < now()) "
                "ORDER BY slot LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING slot",
                {"h": holder, "cap": cap, "lease": lease_s},
            )
            .fetchone()
        )
        return None if row is None else int(row[0])

    def release_slot(self, slot: int, holder: str) -> None:
        self._c().execute(
            "UPDATE llm_slots SET holder = NULL, lease_until = NULL "
            "WHERE slot = %s AND holder = %s",
            (slot, holder),
        )

    # --- cool-down + breaker (P2-07, P2-29) ---------------------------------------------

    def shared_state(self) -> SharedState:
        cool, open_until, brk, probe = (
            self._c()
            .execute(
                "SELECT greatest(0, extract(epoch FROM cooldown_until - now())), "
                "breaker_open_until, "
                "greatest(0, extract(epoch FROM breaker_open_until - now())), "
                "coalesce(probe_until > now(), false) "
                "FROM llm_state WHERE id = 1"
            )
            .fetchone()
        )
        return SharedState(float(cool or 0.0), open_until, float(brk or 0.0), bool(probe))

    def waits(self) -> tuple[float, float]:
        """Seconds left on (429 cool-down, open breaker); 0 when not active."""
        st = self.shared_state()
        return st.cooldown_s, st.breaker_s

    def set_cooldown(self, seconds: float) -> None:
        self._c().execute(
            "UPDATE llm_state SET cooldown_until = greatest(coalesce(cooldown_until, now()), "
            "now() + make_interval(secs => %s)) WHERE id = 1",
            (seconds,),
        )

    def try_claim_probe(self, open_until: datetime, lease_s: float) -> bool:
        """P2-33 half-open: the one caller that waited out pause `open_until` gets the probe.

        Keyed on the pause it waited out (not on the DB clock), so a caller whose pause ended
        claims at once; a caller holding a stale pause value, or arriving while a live probe
        holds the lease, gets False and waits.
        """
        row = (
            self._c()
            .execute(
                "UPDATE llm_state SET probe_until = now() + make_interval(secs => %s) "
                "WHERE id = 1 AND breaker_open_until = %s "
                "AND (probe_until IS NULL OR probe_until < now()) RETURNING 1",
                (lease_s, open_until),
            )
            .fetchone()
        )
        return row is not None

    def release_probe(self) -> None:
        """Give the probe back without a verdict (the call said nothing about the gateway)."""
        self._c().execute("UPDATE llm_state SET probe_until = NULL WHERE id = 1")

    def note_failure(self, threshold: int, pause_s: float, *, probe: bool = False) -> bool:
        """Count one failed call; open the breaker at `threshold`, or at once when the failed
        call was the half-open probe (P2-33). True if this call (re)opened the breaker."""
        (n,) = (
            self._c()
            .execute(
                "UPDATE llm_state SET consecutive_failures = consecutive_failures + 1 "
                "WHERE id = 1 RETURNING consecutive_failures"
            )
            .fetchone()
        )
        if probe or n >= threshold:
            self._c().execute(
                "UPDATE llm_state SET breaker_open_until = now() + make_interval(secs => %s), "
                "consecutive_failures = 0, probe_until = NULL WHERE id = 1",
                (pause_s,),
            )
            return True
        return False

    def note_success(self) -> None:
        """Any success closes the breaker (a successful probe = closed, P2-33)."""
        self._c().execute(
            "UPDATE llm_state SET consecutive_failures = 0, breaker_open_until = NULL, "
            "probe_until = NULL WHERE id = 1 AND (consecutive_failures <> 0 "
            "OR breaker_open_until IS NOT NULL OR probe_until IS NOT NULL)"
        )
