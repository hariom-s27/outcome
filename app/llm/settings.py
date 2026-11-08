"""LLM wrapper settings, read from the environment (names in .env.example / compose)."""

from __future__ import annotations

import os
from dataclasses import dataclass

CACHE_MODES = ("readwrite", "off")


def _float_or_none(raw: str | None) -> float | None:
    return float(raw) if raw not in (None, "") else None


@dataclass(frozen=True)
class LLMSettings:
    base_url: str = ""
    api_key: str = ""
    max_concurrency: int = 4  # P2-07 LLM_MAX_CONCURRENCY
    max_calls_per_doc: int = 8  # P2-28 LLM_MAX_CALLS_PER_DOC (retries + repair included)
    max_usd_per_doc: float = 0.05  # P2-28 LLM_MAX_USD_PER_DOC (computed cost)
    dev_budget_usd: float | None = None  # P2-10 DEV_BUDGET_USD; set by compose.dev.yaml only
    cache_dir: str | None = None  # P2-11 LLM_CACHE_DIR; set by compose.dev.yaml only
    # P5 D-1 LLM_CACHE_MODE: readwrite (read + write the dev cache, when cache_dir is set) |
    # off (no cache read, no cache write, whatever cache_dir says). An explicit value, never an
    # empty LLM_CACHE_DIR: PowerShell drops empty env vars, which would leave the cache on.
    cache_mode: str = "readwrite"
    request_timeout_s: float = 120.0  # LLM_REQUEST_TIMEOUT_S, per HTTP attempt
    max_attempts: int = 4  # P2-06
    backoff_s: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)  # P2-06, + jitter
    default_cooldown_s: float = 5.0  # shared pause after a 429 without Retry-After
    breaker_threshold: int = 5  # P2-29: failures in a row (any model, any worker)
    breaker_pause_s: float = 60.0  # P2-29
    breaker_abort: bool = False  # LLM_BREAKER_ABORT=1 in dev scripts: tripped -> abort run
    slot_poll_s: float = 0.25
    probe_poll_s: float = 1.0  # P2-33: how often a caller re-checks a half-open breaker
    reasoning_override: str | None = None  # P2-31 dev only (compose.dev.yaml): default|none

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError(f"LLM_MAX_CONCURRENCY must be >= 1, got {self.max_concurrency}")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.reasoning_override not in (None, "default", "none"):
            raise ValueError("LLM_REASONING_OVERRIDE must be default or none")
        if self.cache_mode not in CACHE_MODES:
            raise ValueError(
                f"LLM_CACHE_MODE must be one of {CACHE_MODES}, got {self.cache_mode!r}"
            )

    @property
    def slot_lease_s(self) -> float:
        # longer than one HTTP attempt, so a live holder never loses its slot mid-call
        return self.request_timeout_s + 30.0

    @classmethod
    def from_env(cls) -> LLMSettings:
        env = os.environ
        return cls(
            base_url=(env.get("LLM_BASE_URL") or "").rstrip("/"),
            api_key=env.get("LLM_API_KEY") or "",
            max_concurrency=int(env.get("LLM_MAX_CONCURRENCY") or 4),
            max_calls_per_doc=int(env.get("LLM_MAX_CALLS_PER_DOC") or 8),
            max_usd_per_doc=float(env.get("LLM_MAX_USD_PER_DOC") or 0.05),
            dev_budget_usd=_float_or_none(env.get("DEV_BUDGET_USD")),
            cache_dir=env.get("LLM_CACHE_DIR") or None,
            cache_mode=(env.get("LLM_CACHE_MODE") or "readwrite").strip().lower(),
            request_timeout_s=float(env.get("LLM_REQUEST_TIMEOUT_S") or 120.0),
            breaker_abort=(env.get("LLM_BREAKER_ABORT") or "") in ("1", "true", "yes"),
            reasoning_override=env.get("LLM_REASONING_OVERRIDE") or None,
        )
