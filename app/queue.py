"""Job state machine in Postgres (P1-06, P1-07, P1-08).

PENDING -> RUNNING (claim: SKIP LOCKED, fence+1, attempts+1, 60 s lease)
RUNNING -> RUNNING (heartbeat every 15 s extends the lease, only while the fence matches)
RUNNING -> PENDING (sweeper: lease expired; the next claim gets a new fence)
RUNNING -> terminal (worker: compare-and-set on fence + status)
PENDING/RUNNING -> PARTIAL (sweeper: deadline passed; skeleton result)

Terminal rows never change: every write is conditional, and the jobs_terminal_once trigger
rejects anything that slips through. job_events keeps one row per transition, at most one
terminal row per job (unique index).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.results import stub_result

log = logging.getLogger("app.queue")

TERMINAL = ("SUCCESS", "PARTIAL", "FAILED")


@dataclass(frozen=True)
class Claim:
    id: Any
    fence: int
    attempts: int
    field_list: dict[str, Any]
    created_at: datetime
    deadline_at: datetime


def _event(conn, job_id, event: str, *, fence=None, worker=None, reason=None) -> None:
    conn.execute(
        "INSERT INTO job_events (job_id, event, fence, worker, reason) VALUES (%s, %s, %s, %s, %s)",
        (job_id, event, fence, worker, reason),
    )


def latency_ms(created_at: datetime) -> int:
    return max(0, int((datetime.now(UTC) - created_at).total_seconds() * 1000))


def claim(conn: psycopg.Connection, worker_id: str, lease_s: int) -> Claim | None:
    with conn.transaction():
        row = conn.execute(
            """WITH next AS (
                   SELECT id FROM jobs WHERE status = 'PENDING'
                   ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE jobs j
                  SET status = 'RUNNING', stage = 'PARSING', fence = j.fence + 1,
                      attempts = j.attempts + 1, lease_owner = %s,
                      lease_until = now() + make_interval(secs => %s), updated_at = now()
                 FROM next WHERE j.id = next.id
               RETURNING j.id, j.fence, j.attempts, j.field_list, j.created_at, j.deadline_at""",
            (worker_id, lease_s),
        ).fetchone()
        if row is None:
            return None
        claim_ = Claim(*row)
        _event(conn, claim_.id, "CLAIMED", fence=claim_.fence, worker=worker_id)
    return claim_


def heartbeat(conn: psycopg.Connection, job_id, fence: int, lease_s: int) -> bool:
    """Extend the lease. False = we no longer own the job (fence moved or job terminal)."""
    with conn.transaction():
        row = conn.execute(
            """UPDATE jobs SET lease_until = now() + make_interval(secs => %s)
               WHERE id = %s AND fence = %s AND status = 'RUNNING' RETURNING id""",
            (lease_s, job_id, fence),
        ).fetchone()
    return row is not None


def set_stage(conn: psycopg.Connection, job_id, fence: int, stage: str) -> bool:
    with conn.transaction():
        row = conn.execute(
            """UPDATE jobs SET stage = %s, updated_at = now()
               WHERE id = %s AND fence = %s AND status = 'RUNNING' RETURNING id""",
            (stage, job_id, fence),
        ).fetchone()
    return row is not None


def load_file(conn: psycopg.Connection, job_id) -> tuple[str, bytes] | None:
    """(file_type, bytes) of a job's upload; None once the job is terminal (file deleted)."""
    row = conn.execute(
        """SELECT j.file_type, f.content FROM jobs j JOIN job_files f ON f.job_id = j.id
           WHERE j.id = %s""",
        (job_id,),
    ).fetchone()
    return None if row is None else (row[0], bytes(row[1]))


def finish(
    conn: psycopg.Connection,
    job_id,
    status: str,
    *,
    fence: int | None,
    result: dict | None = None,
    error: dict | None = None,
    worker: str | None = None,
    reason: str | None = None,
) -> bool:
    """Compare-and-set to a terminal status. With a fence: only the current lease holder wins.
    Without (sweeper): any non-terminal job. False = someone else got there first."""
    assert status in TERMINAL
    if fence is None:
        guard, params = "status IN ('PENDING', 'RUNNING')", ()
    else:
        guard, params = "fence = %s AND status = 'RUNNING'", (fence,)
    with conn.transaction():
        row = conn.execute(
            f"""UPDATE jobs SET status = %s, stage = NULL, result = %s, error = %s,
                               lease_owner = NULL, lease_until = NULL, updated_at = now()
                WHERE id = %s AND {guard} RETURNING fence""",
            (
                status,
                Jsonb(result) if result is not None else None,
                Jsonb(error) if error is not None else None,
                job_id,
                *params,
            ),
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM job_files WHERE job_id = %s", (job_id,))  # P1-05
        _event(conn, job_id, status, fence=row[0], worker=worker, reason=reason)
    return True


def release(conn: psycopg.Connection, job_id, fence: int, worker: str, reason: str) -> bool:
    """Give a job back to the queue after a processing error (counts as an attempt)."""
    with conn.transaction():
        row = conn.execute(
            """UPDATE jobs SET status = 'PENDING', stage = NULL, lease_owner = NULL,
                              lease_until = NULL, updated_at = now()
               WHERE id = %s AND fence = %s AND status = 'RUNNING' RETURNING id""",
            (job_id, fence),
        ).fetchone()
        if row is None:
            return False
        _event(conn, job_id, "RELEASED", fence=fence, worker=worker, reason=reason)
    return True


# --- sweeper -------------------------------------------------------------------------------------


def sweep(conn: psycopg.Connection, worker_id: str, batch: int = 50) -> dict[str, int]:
    """Deadline first (P1-08), then expired leases. Safe to run from every worker at once."""
    counts = {"deadline": 0, "requeued": 0}

    rows = conn.execute(
        """SELECT id, field_list, created_at FROM jobs
           WHERE status IN ('PENDING', 'RUNNING') AND deadline_at <= now()
           ORDER BY deadline_at LIMIT %s""",
        (batch,),
    ).fetchall()
    conn.commit()
    for job_id, field_list, created_at in rows:
        if finish(
            conn,
            job_id,
            "PARTIAL",
            fence=None,
            result=stub_result(field_list, latency_ms(created_at), "deadline_exceeded"),
            worker=worker_id,
            reason="deadline",
        ):
            counts["deadline"] += 1
            log.warning("job %s status=PARTIAL reason=deadline", job_id)

    with conn.transaction():
        expired = conn.execute(
            """SELECT id, fence FROM jobs
               WHERE status = 'RUNNING' AND lease_until < now()
               ORDER BY lease_until FOR UPDATE SKIP LOCKED LIMIT %s""",
            (batch,),
        ).fetchall()
        for job_id, fence in expired:
            conn.execute(
                """UPDATE jobs SET status = 'PENDING', stage = NULL, lease_owner = NULL,
                                  lease_until = NULL, updated_at = now() WHERE id = %s""",
                (job_id,),
            )
            _event(conn, job_id, "REQUEUED", fence=fence, worker=worker_id, reason="lease_expired")
            counts["requeued"] += 1
            log.warning("job %s lease expired (fence=%d); requeued", job_id, fence)
    return counts
