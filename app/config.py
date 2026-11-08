"""Runtime settings, read from the environment once per process."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql://docextract:docextract@db:5432/docextract"
SINGLE_VALUE_PATHS = ("baseline", "smart")
TABLE_PATHS = ("baseline", "spec")


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    max_pending: int = 500  # P1-10: 429 when PENDING >= this
    max_upload_bytes: int = 50 * 1024 * 1024  # P1-10: 413 above 50 MB
    job_deadline_s: int = 1500  # P1-08: PARTIAL skeleton this long after submission
    lease_s: int = 60  # P1-06; env LEASE_S
    heartbeat_s: float = 15.0  # P1-06; env HEARTBEAT_S (must be < lease)
    max_attempts: int = 3  # poison job: claimed this many times without finishing
    sweep_every_s: float = 5.0  # env SWEEP_EVERY_S
    worker_poll_s: float = 1.0
    fake_work_s: float = 0.0  # dev/chaos only: simulated processing time; never set in compose
    version: str = "dev"
    # P5-03/P5-04: single-value field lists go to the smart path only when "smart";
    # table field lists always keep the baseline. env EXTRACT_SINGLE_VALUE_PATH.
    single_value_path: str = "baseline"
    # P6 T-15: table field lists go to the spec path (long XLSX/CSV tables) only when "spec";
    # default baseline until P6 ships. env EXTRACT_TABLE_PATH.
    table_path: str = "baseline"

    def __post_init__(self) -> None:
        if self.single_value_path not in SINGLE_VALUE_PATHS:
            raise ValueError(
                f"EXTRACT_SINGLE_VALUE_PATH must be one of {SINGLE_VALUE_PATHS}, "
                f"got {self.single_value_path!r}"
            )
        if self.table_path not in TABLE_PATHS:
            raise ValueError(
                f"EXTRACT_TABLE_PATH must be one of {TABLE_PATHS}, got {self.table_path!r}"
            )
        if not 0 < self.heartbeat_s < self.lease_s:
            raise ValueError(
                f"need 0 < HEARTBEAT_S < LEASE_S, got {self.heartbeat_s} and {self.lease_s}"
            )
        if self.sweep_every_s <= 0:
            raise ValueError(f"SWEEP_EVERY_S must be > 0, got {self.sweep_every_s}")

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
            max_pending=int(env.get("MAX_PENDING") or 500),
            job_deadline_s=int(env.get("JOB_DEADLINE_S") or 1500),
            lease_s=int(env.get("LEASE_S") or 60),
            heartbeat_s=float(env.get("HEARTBEAT_S") or 15.0),
            sweep_every_s=float(env.get("SWEEP_EVERY_S") or 5.0),
            fake_work_s=float(env.get("WORKER_FAKE_WORK_S") or 0.0),
            worker_poll_s=float(env.get("WORKER_POLL_S") or 1.0),
            version=env.get("APP_VERSION") or "dev",
            single_value_path=(env.get("EXTRACT_SINGLE_VALUE_PATH") or "baseline").strip().lower(),
            table_path=(env.get("EXTRACT_TABLE_PATH") or "baseline").strip().lower(),
        )
