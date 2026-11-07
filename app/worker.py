"""Worker role. Part B: claim one PENDING job (SKIP LOCKED), write the P1-09 stub, delete the file.

Part C adds the lease, heartbeat, fence token, sweeper, terminal trigger and deadline.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import db
from app.config import Settings
from app.results import stub_result

log = logging.getLogger("app.worker")

_stop = False


def _claim(conn: psycopg.Connection) -> dict[str, Any] | None:
    with conn.transaction():
        row = conn.execute(
            """SELECT id, field_list, created_at FROM jobs
               WHERE status = 'PENDING' ORDER BY created_at
               FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'RUNNING', stage = 'EXTRACTING', updated_at = now() "
            "WHERE id = %s",
            (row["id"],),
        )
        conn.execute("INSERT INTO job_events (job_id, event) VALUES (%s, 'CLAIMED')", (row["id"],))
    return row


def _finish(conn: psycopg.Connection, job_id, status: str, result=None, error=None) -> None:
    with conn.transaction():
        conn.execute(
            """UPDATE jobs SET status = %s, stage = NULL, result = %s, error = %s,
                              updated_at = now()
               WHERE id = %s AND status = 'RUNNING'""",
            (
                status,
                Jsonb(result) if result is not None else None,
                Jsonb(error) if error is not None else None,
                job_id,
            ),
        )
        conn.execute("DELETE FROM job_files WHERE job_id = %s", (job_id,))  # P1-05
        conn.execute("INSERT INTO job_events (job_id, event) VALUES (%s, %s)", (job_id, status))


def process_one(settings: Settings) -> bool:
    """Process at most one job. Returns False when the queue was empty."""
    with db.connect(settings.database_url, row_factory=dict_row) as conn:
        job = _claim(conn)
        if job is None:
            return False
        started = time.monotonic()
        latency_ms = (datetime.now(UTC) - job["created_at"]).total_seconds() * 1000
        try:
            result = stub_result(job["field_list"], latency_ms)
        except (KeyError, TypeError, AttributeError) as exc:
            _finish(
                conn,
                job["id"],
                "FAILED",
                error={"code": "internal_error", "message": f"stub failed: {type(exc).__name__}"},
            )
            log.error("job %s status=FAILED (%s)", job["id"], type(exc).__name__)
            return True
        _finish(conn, job["id"], "PARTIAL", result=result)
        log.info("job %s status=PARTIAL took_ms=%d", job["id"], (time.monotonic() - started) * 1000)
        return True


def _request_stop(signum, _frame) -> None:
    global _stop
    _stop = True
    log.info("signal %s: stopping after the current job", signum)


def main() -> None:  # pragma: no cover - container entry point
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    db.migrate_with_retry(settings.database_url)
    log.info("worker started")
    backoff = settings.worker_poll_s
    while not _stop:
        try:
            if not process_one(settings):
                time.sleep(settings.worker_poll_s)
            backoff = settings.worker_poll_s
        except psycopg.OperationalError as exc:
            log.warning("db error (%s); retrying in %.1fs", type(exc).__name__, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    log.info("worker stopped")


if __name__ == "__main__":  # pragma: no cover
    main()
