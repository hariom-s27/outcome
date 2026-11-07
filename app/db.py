"""Postgres access: connections and the idempotent start-up migration."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
_MIGRATE_LOCK = 0x0D0CE7  # pg_advisory_xact_lock key; serialises api + worker start-up


def connect(database_url: str, **kwargs) -> psycopg.Connection:
    kwargs.setdefault("connect_timeout", 5)
    return psycopg.connect(database_url, **kwargs)


def migrate(database_url: str) -> None:
    with connect(database_url) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATE_LOCK,))
        conn.execute(SCHEMA_SQL)


def migrate_with_retry(database_url: str, give_up_after_s: float = 120.0) -> None:
    """Retry until the DB answers; raise after give_up_after_s so the container restarts."""
    start = time.monotonic()
    while True:
        try:
            migrate(database_url)
            log.info("migration applied")
            return
        except psycopg.OperationalError as exc:
            if time.monotonic() - start > give_up_after_s:
                raise
            log.warning("db not ready (%s); retrying", type(exc).__name__)
            time.sleep(1.0)
