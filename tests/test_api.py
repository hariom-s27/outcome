"""HTTP behaviour of POST /jobs, GET /jobs/{id}, GET /health (P1-09..P1-14)."""

from __future__ import annotations

import json
import uuid

import pytest
from conftest import (
    CSV_BYTES,
    DOCX_BYTES,
    FIELD_LIST,
    FIELD_LIST_JSON,
    PDF_BYTES,
    XLSX_BYTES,
    validator,
)

from app import worker
from app.config import Settings


def post(client, *, file=("doc.pdf", PDF_BYTES), schema=FIELD_LIST_JSON, org=None, **extra):
    files = {"file": file} if file is not None else {}
    data = {"schema": schema} if schema is not None else {}
    data.update(extra)
    headers = {"X-Organization-Id": org} if org is not None else {}
    return client.post("/jobs", files=files or None, data=data, headers=headers)


# --- POST /jobs: accepted ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,content",
    [
        ("a.pdf", PDF_BYTES),
        ("a.docx", DOCX_BYTES),
        ("a.xlsx", XLSX_BYTES),
        ("a.csv", CSV_BYTES),
        # P1-11: magic bytes alone are enough (wrong or missing extension)
        ("noext", PDF_BYTES),
        ("upload.bin", DOCX_BYTES),
        ("upload.dat", XLSX_BYTES),
        ("upload.txt", CSV_BYTES),
        # P1-11: extension alone is enough (content not recognised)
        ("odd.pdf", b"not really a pdf"),
    ],
)
def test_post_accepts_supported_types(client, name, content):
    r = post(client, file=(name, content))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    assert uuid.UUID(body["job_id"])
    assert body["created_at"] and body["updated_at"]
    for absent in ("result", "error", "stage"):
        assert absent not in body


def test_post_accepts_unfamiliar_field_list(client):
    loose = {"fields": {"anything": {}, "other": {"name": "Other"}}}
    assert post(client, schema=json.dumps(loose)).status_code == 202


# --- POST /jobs: 400 -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"file": None},
        {"schema": None},
        {"schema": "{not json"},
        {"schema": "[]"},
        {"schema": json.dumps({"name": "x"})},
        {"schema": json.dumps({"fields": {}})},
        {"schema": json.dumps({"fields": {"a": "not an object"}})},
        {"schema": json.dumps({"fields": {"a": {"name": 5}}})},
        {"file": ("a.exe", b"MZ\x90\x00binary")},
        {"file": ("a.pdf", b"")},
        {"webhook_url": "ftp://example.invalid/hook"},
        {"webhook_url": "not a url"},
    ],
)
def test_post_rejects_malformed(client, kwargs):
    r = post(client, **kwargs)
    assert r.status_code == 400, r.text
    err = r.json()
    assert set(err) >= {"code", "message"}


def test_post_rejects_non_multipart(client):
    r = client.post("/jobs", json={"schema": FIELD_LIST_JSON})
    assert r.status_code == 400


def test_post_accepts_valid_webhook(client):
    r = post(client, webhook_url="https://example.invalid/hook")
    assert r.status_code == 202


# --- POST /jobs: 413, 429 ------------------------------------------------------------------------


def test_post_too_large(database_url, clean_db):
    from fastapi.testclient import TestClient

    from app.api import create_app

    small = Settings(database_url=database_url, max_pending=3, max_upload_bytes=1024)
    with TestClient(create_app(small)) as c:
        r = post(c, file=("big.pdf", PDF_BYTES + b"0" * 2048))
        assert r.status_code == 413
        assert post(c, file=("ok.pdf", PDF_BYTES)).status_code == 202


def test_post_429_when_queue_full(client):
    for _ in range(3):  # settings fixture: MAX_PENDING=3
        assert post(client).status_code == 202
    r = post(client)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "30"


def test_max_pending_from_env(monkeypatch):
    monkeypatch.setenv("MAX_PENDING", "7")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/x")
    assert Settings.from_env().max_pending == 7


def test_lease_heartbeat_sweep_from_env(monkeypatch):
    for var in ("LEASE_S", "HEARTBEAT_S", "SWEEP_EVERY_S"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert (s.lease_s, s.heartbeat_s, s.sweep_every_s) == (60, 15.0, 5.0)  # P1-06 defaults
    monkeypatch.setenv("LEASE_S", "30")
    monkeypatch.setenv("HEARTBEAT_S", "7.5")
    monkeypatch.setenv("SWEEP_EVERY_S", "2")
    s = Settings.from_env()
    assert (s.lease_s, s.heartbeat_s, s.sweep_every_s) == (30, 7.5, 2.0)
    monkeypatch.setenv("HEARTBEAT_S", "30")  # heartbeat must be shorter than the lease
    with pytest.raises(ValueError):
        Settings.from_env()


# --- GET /jobs/{id} and tenants (P1-13) ----------------------------------------------------------


def test_get_unknown_and_malformed_ids(client):
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404
    assert client.get("/jobs/not-a-uuid").status_code == 404


def test_get_roundtrip(client):
    job_id = post(client).json()["job_id"]
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["job_id"] == job_id
    assert r.json()["status"] == "PENDING"


@pytest.mark.parametrize(
    "created_org,read_org,visible",
    [
        ("org-a", "org-a", True),
        ("org-a", "org-b", False),
        ("org-a", None, False),  # no header vs org job -> 404
        (None, None, True),  # job without org: visible without header
        (None, "org-a", False),  # ... and 404 with any header (confirmed gap a)
    ],
)
def test_tenant_isolation(client, created_org, read_org, visible):
    job_id = post(client, org=created_org).json()["job_id"]
    headers = {"X-Organization-Id": read_org} if read_org else {}
    r = client.get(f"/jobs/{job_id}", headers=headers)
    assert r.status_code == (200 if visible else 404)


# --- worker stub (P1-09) -------------------------------------------------------------------------


def test_worker_writes_valid_stub_and_deletes_file(client, settings):
    job_id = post(client, org="org-a").json()["job_id"]
    assert worker.process_one(settings) is True
    assert worker.process_one(settings) is False  # queue empty

    body = client.get(f"/jobs/{job_id}", headers={"X-Organization-Id": "org-a"}).json()
    assert body["status"] == "PARTIAL"
    assert "error" not in body
    result = body["result"]
    assert validator.validate_contract(result, FIELD_LIST) == []
    assert len(result["entries"]) == 1
    for fr in result["entries"][0].values():
        assert fr == {"value": None, "citation": "", "confidence": 0.0}

    import psycopg

    with psycopg.connect(settings.database_url) as conn:
        files = conn.execute("SELECT count(*) FROM job_files WHERE job_id = %s", (job_id,))
        assert files.fetchone()[0] == 0
        events = conn.execute(
            "SELECT event FROM job_events WHERE job_id = %s ORDER BY id", (job_id,)
        ).fetchall()
        assert [e[0] for e in events] == ["CREATED", "CLAIMED", "PARTIAL"]


# --- /health (P1-12) -----------------------------------------------------------------------------


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_503_when_db_unreachable():
    from fastapi.testclient import TestClient

    from app.api import create_app

    # port 1 on loopback: connection refused, never leaves the machine
    dead = Settings(database_url="postgresql://u:p@127.0.0.1:1/x?connect_timeout=1")
    with TestClient(create_app(dead)) as c:
        r = c.get("/health")
    assert r.status_code == 503
