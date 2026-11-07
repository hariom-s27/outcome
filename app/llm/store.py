"""Shared LLM state in Postgres: cost ledger (P2-09), in-flight slots + 429 cool-down (P2-07),
circuit breaker (P2-29). Every worker sees the same rows, so the caps are global.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


_COLUMNS = list(LedgerRow.__dataclass_fields__)


@dataclass
class DocUsage:
    calls: int = 0  # paid attempts (cache hits excluded)
    cost_computed: float = 0.0
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
                "SELECT count(*), coalesce(sum(cost_computed), 0) FROM llm_calls "
                "WHERE job_id = %s AND NOT cache_hit",
                (job_id,),
            )
            .fetchone()
        )
        return DocUsage(calls=int(calls), cost_computed=float(cost))

    def total_spend(self) -> float:
        (total,) = (
            self._c()
            .execute(
                "SELECT coalesce(sum(coalesce(cost_reported, cost_computed)), 0) FROM llm_calls"
            )
            .fetchone()
        )
        return float(total)

    def job_metadata(self, job_id: str, latency_ms: int) -> dict[str, Any]:
        """Contract metadata block for one job, built from its ledger rows (R21)."""
        rows = (
            self._c()
            .execute(
                "SELECT model_requested, count(*), sum(tokens_in), sum(tokens_out), "
                "sum(coalesce(cost_reported, cost_computed)), sum(cost_computed), "
                "bool_or(model_mismatch), coalesce(sum(tokens_reasoning), 0) "
                "FROM llm_calls WHERE job_id = %s AND NOT cache_hit GROUP BY model_requested "
                "ORDER BY model_requested",
                (job_id,),
            )
            .fetchall()
        )
        (cache_hits,) = (
            self._c()
            .execute("SELECT count(*) FROM llm_calls WHERE job_id = %s AND cache_hit", (job_id,))
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
        computed = 0.0
        reasoning = 0
        mismatch = False
        for model, calls, t_in, t_out, cost, cost_c, mm, r_tok in rows:
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
            reasoning += int(r_tok)
            mismatch = mismatch or bool(mm)
        meta["cost_usd"] = round(meta["cost_usd"], 6)
        if models:
            meta["models"] = models
            meta["cost_computed_usd"] = round(computed, 6)
            meta["tokens_reasoning"] = reasoning
        if mismatch:
            meta["model_mismatch"] = True
        if cache_hits:
            meta["cache_hits"] = int(cache_hits)
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

    def waits(self) -> tuple[float, float]:
        """Seconds left on (429 cool-down, open breaker); 0 when not active."""
        cool, brk = (
            self._c()
            .execute(
                "SELECT greatest(0, extract(epoch FROM cooldown_until - now())), "
                "greatest(0, extract(epoch FROM breaker_open_until - now())) "
                "FROM llm_state WHERE id = 1"
            )
            .fetchone()
        )
        return float(cool or 0.0), float(brk or 0.0)

    def set_cooldown(self, seconds: float) -> None:
        self._c().execute(
            "UPDATE llm_state SET cooldown_until = greatest(coalesce(cooldown_until, now()), "
            "now() + make_interval(secs => %s)) WHERE id = 1",
            (seconds,),
        )

    def note_failure(self, threshold: int, pause_s: float) -> bool:
        """Count one failed call; open the breaker at `threshold`. True if it is now open."""
        (n,) = (
            self._c()
            .execute(
                "UPDATE llm_state SET consecutive_failures = consecutive_failures + 1 "
                "WHERE id = 1 RETURNING consecutive_failures"
            )
            .fetchone()
        )
        if n >= threshold:
            self._c().execute(
                "UPDATE llm_state SET breaker_open_until = now() + make_interval(secs => %s), "
                "consecutive_failures = 0 WHERE id = 1",
                (pause_s,),
            )
            return True
        return False

    def note_success(self) -> None:
        self._c().execute(
            "UPDATE llm_state SET consecutive_failures = 0, breaker_open_until = NULL "
            "WHERE id = 1 AND (consecutive_failures <> 0 OR breaker_open_until IS NOT NULL)"
        )
