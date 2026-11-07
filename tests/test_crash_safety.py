"""Claim/lease/fence, terminal-once, deadline, sweeper and poison jobs (P1-06, P1-07, P1-08)."""

from __future__ import annotations

import dataclasses
import threading
import time

import psycopg
import pytest
from conftest import FIELD_LIST, FIELD_LIST_JSON, PDF_BYTES, validator

from app import db, queue, worker


def new_job(client) -> str:
    r = client.post("/jobs", files={"file": ("a.pdf", PDF_BYTES)}, data={"schema": FIELD_LIST_JSON})
    assert r.status_code == 202
    return r.json()["job_id"]


def sql(settings, query, params=()):
    with psycopg.connect(settings.database_url) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def events(settings, job_id) -> list[str]:
    return [
        r[0]
        for r in sql(
            settings, "SELECT event FROM job_events WHERE job_id = %s ORDER BY id", (job_id,)
        )
    ]


def job(settings, job_id) -> dict:
    with psycopg.connect(settings.database_url, row_factory=psycopg.rows.dict_row) as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()


def file_count(settings, job_id) -> int:
    return sql(settings, "SELECT count(*) FROM job_files WHERE job_id = %s", (job_id,))[0][0]


# --- schema / P1-07 -----------------------------------------------------------------------------


def test_migration_is_idempotent(settings, clean_db):
    db.migrate(settings.database_url)
    db.migrate(settings.database_url)


def test_deadline_set_from_submission(client, settings):
    row = job(settings, new_job(client))
    assert (row["deadline_at"] - row["created_at"]).total_seconds() == pytest.approx(1500, abs=2)


def test_trigger_blocks_any_change_to_terminal_job(client, settings):
    jid = new_job(client)
    assert worker.process_one(settings, "w1")
    for stmt in (
        "UPDATE jobs SET status = 'RUNNING' WHERE id = %s",
        "UPDATE jobs SET result = '{}'::jsonb WHERE id = %s",
        "UPDATE jobs SET status = 'FAILED' WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            sql(settings, stmt, (jid,))
    assert job(settings, jid)["status"] == "PARTIAL"


def test_only_one_terminal_event_per_job(client, settings):
    jid = new_job(client)
    assert worker.process_one(settings, "w1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql(settings, "INSERT INTO job_events (job_id, event) VALUES (%s, 'FAILED')", (jid,))


# --- claim / P1-06 ------------------------------------------------------------------------------


def test_claim_skips_locked_rows(client, settings):
    first, second = new_job(client), new_job(client)
    with psycopg.connect(settings.database_url) as holder, holder.transaction():
        holder.execute("SELECT 1 FROM jobs WHERE id = %s FOR UPDATE", (first,))
        with db.connect(settings.database_url) as conn:
            got = queue.claim(conn, "w2", settings.lease_s)
            assert str(got.id) == second
            assert queue.claim(conn, "w2", settings.lease_s) is None  # first is locked


def test_claim_sets_lease_fence_and_attempts(client, settings):
    jid = new_job(client)
    with db.connect(settings.database_url) as conn:
        c = queue.claim(conn, "w1", 60)
    row = job(settings, jid)
    assert (row["status"], row["fence"], row["attempts"], row["lease_owner"]) == (
        "RUNNING",
        1,
        1,
        "w1",
    )
    assert c.fence == 1
    remaining = sql(settings, "SELECT extract(epoch FROM lease_until - now()) FROM jobs")[0][0]
    assert 55 < float(remaining) <= 60


def test_expired_lease_requeued_and_stale_fence_loses(client, settings):
    jid = new_job(client)
    with db.connect(settings.database_url) as conn:
        old = queue.claim(conn, "dead-worker", 60)
        sql(settings, "UPDATE jobs SET lease_until = now() - interval '1 s' WHERE id = %s", (jid,))
        assert queue.sweep(conn, "sweeper") == {"deadline": 0, "requeued": 1}
        assert job(settings, jid)["status"] == "PENDING"

        new = queue.claim(conn, "w2", 60)
        assert new.fence == old.fence + 1
        # the old worker wakes up and tries to write: compare-and-set rejects it
        assert not queue.finish(conn, jid, "PARTIAL", fence=old.fence, result={"x": 1})
        assert not queue.heartbeat(conn, jid, old.fence, 60)
        assert queue.finish(conn, jid, "PARTIAL", fence=new.fence, result={"ok": 1})

    assert events(settings, jid) == ["CREATED", "CLAIMED", "REQUEUED", "CLAIMED", "PARTIAL"]
    assert job(settings, jid)["result"] == {"ok": 1}
    assert file_count(settings, jid) == 0


def test_live_lease_is_not_requeued(client, settings):
    new_job(client)
    with db.connect(settings.database_url) as conn:
        queue.claim(conn, "w1", 60)
        assert queue.sweep(conn, "sweeper") == {"deadline": 0, "requeued": 0}


# --- heartbeat ----------------------------------------------------------------------------------


def test_heartbeat_extends_lease_then_detects_loss(client, settings):
    fast = dataclasses.replace(settings, heartbeat_s=0.2)
    jid = new_job(client)
    with db.connect(settings.database_url) as conn:
        c = queue.claim(conn, "w1", 60)
    sql(settings, "UPDATE jobs SET lease_until = now() + interval '5 s' WHERE id = %s", (jid,))
    with worker.Heartbeat(fast, c.id, c.fence) as hb:
        time.sleep(0.6)
        left = sql(settings, "SELECT extract(epoch FROM lease_until - now()) FROM jobs")[0][0]
        assert float(left) > 50  # extended back to ~60 s
        assert not hb.lost.is_set()
        sql(settings, "UPDATE jobs SET fence = fence + 1 WHERE id = %s", (jid,))  # re-claimed
        assert hb.lost.wait(2.0)


def test_worker_abandons_job_when_lease_lost(client, settings):
    slow = dataclasses.replace(settings, heartbeat_s=0.2, fake_work_s=3.0)
    jid = new_job(client)
    t = threading.Thread(target=worker.process_one, args=(slow, "w1"))
    t.start()
    deadline = time.monotonic() + 5
    while job(settings, jid)["status"] != "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.05)
    sql(settings, "UPDATE jobs SET fence = fence + 1 WHERE id = %s", (jid,))  # someone else owns it
    t.join(timeout=10)
    assert not t.is_alive()
    assert job(settings, jid)["status"] == "RUNNING"  # w1 did not write
    assert "PARTIAL" not in events(settings, jid)


# --- deadline / P1-08 ---------------------------------------------------------------------------


@pytest.mark.parametrize("claimed", [False, True])
def test_deadline_gives_partial_skeleton(client, settings, claimed):
    jid = new_job(client)
    old = None
    with db.connect(settings.database_url) as conn:
        if claimed:
            old = queue.claim(conn, "slow-worker", 60)
        sql(settings, "UPDATE jobs SET deadline_at = now() - interval '1 s' WHERE id = %s", (jid,))
        assert queue.sweep(conn, "sweeper")["deadline"] == 1
        if old:  # the slow worker finishes later: rejected, no trigger error
            assert not queue.finish(conn, jid, "PARTIAL", fence=old.fence, result={"late": 1})

    body = client.get(f"/jobs/{jid}").json()
    assert body["status"] == "PARTIAL"
    assert "error" not in body  # error is for FAILED only
    assert body["result"]["metadata"]["terminal_reason"] == "deadline_exceeded"
    assert validator.validate_contract(body["result"], FIELD_LIST) == []
    assert file_count(settings, jid) == 0
    assert events(settings, jid)[-1] == "PARTIAL"


# --- poison job ---------------------------------------------------------------------------------


def test_poison_job_capped_at_max_attempts(client, settings, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(worker, "process", boom)
    jid = new_job(client)
    for attempt in range(1, settings.max_attempts + 1):
        assert worker.process_one(settings, "w1")
        row = job(settings, jid)
        assert (row["status"], row["attempts"]) == ("PENDING", attempt)

    assert worker.process_one(settings, "w1")  # claim #4 -> poison skeleton, no 4th try
    body = client.get(f"/jobs/{jid}").json()
    assert body["status"] == "PARTIAL"
    assert "error" not in body  # error is for FAILED only
    assert body["result"]["metadata"]["terminal_reason"] == "too_many_attempts"
    assert validator.validate_contract(body["result"], FIELD_LIST) == []
    assert events(settings, jid) == (
        ["CREATED"] + ["CLAIMED", "RELEASED"] * settings.max_attempts + ["CLAIMED", "PARTIAL"]
    )


def test_crash_loop_poison_via_lease_expiry(client, settings):
    """Worker process dies every time (no release): leases expire, attempts still cap it."""
    jid = new_job(client)
    with db.connect(settings.database_url) as conn:
        for _ in range(settings.max_attempts):
            assert queue.claim(conn, "crashy", 60)
            sql(
                settings,
                "UPDATE jobs SET lease_until = now() - interval '1 s' WHERE id = %s",
                (jid,),
            )
            queue.sweep(conn, "sweeper")
    assert worker.process_one(settings, "w1")
    row = job(settings, jid)
    assert row["status"] == "PARTIAL"
    assert row["error"] is None
    assert row["result"]["metadata"]["terminal_reason"] == "too_many_attempts"
