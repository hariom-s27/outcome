"""Worker role: claim -> heartbeat -> process -> compare-and-set finish; sweep on a timer.

Crash safety (P1-06/07/08): a worker that dies stops heart-beating, its lease expires, the
sweeper requeues the job and the next claim gets a new fence, so a late write from the old
worker matches nothing. A job claimed more than max_attempts times is a poison job and gets
the P1-09 skeleton instead of another try.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from typing import Any

import psycopg

from app import db, queue
from app.config import Settings
from app.results import stub_result

log = logging.getLogger("app.worker")

_stop = threading.Event()


class LeaseLost(Exception):
    """The job was taken from us (lease expired + re-claimed, or deadline sweep)."""


def worker_id() -> str:
    # host:pid:random -- in a container pid is always 1, so a restarted worker needs the suffix
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class Heartbeat:
    """Background thread extending the lease every heartbeat_s on its own connection."""

    def __init__(self, settings: Settings, job_id, fence: int):
        self.settings, self.job_id, self.fence = settings, job_id, fence
        self.lost = threading.Event()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)

    def __enter__(self) -> Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._done.set()
        self._thread.join(timeout=self.settings.heartbeat_s + 5)

    def _run(self) -> None:
        while not self._done.wait(self.settings.heartbeat_s):
            try:
                with db.connect(self.settings.database_url) as conn:
                    ok = queue.heartbeat(conn, self.job_id, self.fence, self.settings.lease_s)
            except psycopg.OperationalError as exc:
                # keep trying; if the DB stays away the lease lapses and the job is requeued
                log.warning("job %s heartbeat failed (%s)", self.job_id, type(exc).__name__)
                continue
            if not ok:
                log.warning("job %s lease lost (fence=%d)", self.job_id, self.fence)
                self.lost.set()
                return

    def check(self) -> None:
        if self.lost.is_set():
            raise LeaseLost(str(self.job_id))


def process(job: queue.Claim, settings: Settings, hb: Heartbeat) -> dict[str, Any]:
    """Produce the result. Part C: the P1-09 skeleton (real extraction arrives in P2+)."""
    if settings.fake_work_s > 0:  # dev/chaos only
        end = time.monotonic() + settings.fake_work_s
        while time.monotonic() < end:
            hb.check()
            time.sleep(min(0.5, end - time.monotonic()))
    hb.check()
    return stub_result(job.field_list, queue.latency_ms(job.created_at))


def process_one(settings: Settings, wid: str | None = None) -> bool:
    """Claim and process at most one job. Returns False when the queue was empty."""
    wid = wid or worker_id()
    with db.connect(settings.database_url) as conn:
        job = queue.claim(conn, wid, settings.lease_s)
        if job is None:
            return False
        log.info("job %s claimed fence=%d attempt=%d", job.id, job.fence, job.attempts)

        if job.attempts > settings.max_attempts:
            queue.finish(
                conn,
                job.id,
                "PARTIAL",
                fence=job.fence,
                result=stub_result(
                    job.field_list, queue.latency_ms(job.created_at), "too_many_attempts"
                ),
                worker=wid,
                reason="poison",
            )
            log.error("job %s status=PARTIAL reason=poison attempts=%d", job.id, job.attempts)
            return True

        started = time.monotonic()
        try:
            with Heartbeat(settings, job.id, job.fence) as hb:
                queue.set_stage(conn, job.id, job.fence, "EXTRACTING")
                result = process(job, settings, hb)
        except LeaseLost:
            log.warning("job %s abandoned: lease lost", job.id)
            return True
        except Exception as exc:
            # surface (type + code location only: messages may quote document text, R23),
            # then hand the job back; attempts+1 on the next claim caps retries
            tb = exc.__traceback__
            while tb and tb.tb_next:
                tb = tb.tb_next
            where = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb else "?"
            log.error("job %s processing error %s at %s", job.id, type(exc).__name__, where)
            queue.release(conn, job.id, job.fence, wid, reason=type(exc).__name__)
            return True

        if queue.finish(conn, job.id, "PARTIAL", fence=job.fence, result=result, worker=wid):
            log.info(
                "job %s status=PARTIAL took_ms=%d", job.id, (time.monotonic() - started) * 1000
            )
        else:
            log.warning("job %s finish rejected: fence %d is stale", job.id, job.fence)
        return True


def sweep_once(settings: Settings, wid: str | None = None) -> dict[str, int]:
    with db.connect(settings.database_url) as conn:
        return queue.sweep(conn, wid or worker_id())


def _sweep_loop(settings: Settings, wid: str) -> None:
    """Runs beside job processing so deadlines and dead leases are handled during long jobs."""
    while not _stop.wait(settings.sweep_every_s):
        try:
            sweep_once(settings, wid)
        except psycopg.OperationalError as exc:
            log.warning(
                "sweep failed (%s); next try in %.0fs", type(exc).__name__, settings.sweep_every_s
            )


def _request_stop(signum, _frame) -> None:
    _stop.set()
    log.info("signal %s: stopping after the current job", signum)


def main() -> None:  # pragma: no cover - container entry point
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    db.migrate_with_retry(settings.database_url)
    wid = worker_id()
    log.info("worker %s started", wid)
    threading.Thread(target=_sweep_loop, args=(settings, wid), name="sweeper", daemon=True).start()
    backoff = settings.worker_poll_s
    while not _stop.is_set():
        try:
            if not process_one(settings, wid):
                _stop.wait(settings.worker_poll_s)
            backoff = settings.worker_poll_s
        except psycopg.OperationalError as exc:
            log.warning("db error (%s); retrying in %.1fs", type(exc).__name__, backoff)
            _stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)
    log.info("worker %s stopped", wid)


if __name__ == "__main__":  # pragma: no cover
    main()
