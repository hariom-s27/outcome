"""Runtime settings, read from the environment once per process."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql://docextract:docextract@db:5432/docextract"


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    max_pending: int = 500  # P1-10: 429 when PENDING >= this
    max_upload_bytes: int = 50 * 1024 * 1024  # P1-10: 413 above 50 MB
    job_deadline_s: int = 1500  # P1-08 (used from Part C)
    worker_poll_s: float = 1.0
    version: str = "dev"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
            max_pending=int(env.get("MAX_PENDING") or 500),
            job_deadline_s=int(env.get("JOB_DEADLINE_S") or 1500),
            worker_poll_s=float(env.get("WORKER_POLL_S") or 1.0),
            version=env.get("APP_VERSION") or "dev",
        )
