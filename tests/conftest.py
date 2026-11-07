"""Shared fixtures. Default test run: no outside network, no LLM key (R32, P1-15).

Postgres comes from a testcontainer (Docker must be running). The socket guard allows
loopback only, which is where the container's mapped port lives.
"""

from __future__ import annotations

import importlib.util
import io
import ipaddress
import json
import os
import socket
import zipfile
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
PG_IMAGE = (
    "postgres:17-alpine@sha256:3540c0362c809df084ffac0ae69fe794515f9de92692f02178bcdce0ef0302ac"
)

# --- no key, no outside network -------------------------------------------------------------

os.environ.pop("LLM_API_KEY", None)
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple):  # AF_UNIX path
        return True
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guarded_connect(self, address):
    if not _is_loopback(address):
        raise RuntimeError(f"network blocked in tests: {address!r}")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if not _is_loopback(address):
        raise RuntimeError(f"network blocked in tests: {address!r}")
    return _real_connect_ex(self, address)


socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]


# --- the frozen validator, imported as a module ----------------------------------------------


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "contract_validate", ROOT / "tools" / "validate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


validator = _load_validator()


# --- Postgres ---------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(PG_IMAGE, driver=None) as pg:
        yield pg.get_connection_url()


@pytest.fixture
def settings(database_url):
    from app.config import Settings

    return Settings(database_url=database_url, max_pending=3, job_deadline_s=1500)


@pytest.fixture
def clean_db(settings) -> None:
    from app import db

    db.migrate(settings.database_url)
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("TRUNCATE jobs CASCADE")


@pytest.fixture
def client(settings, clean_db):
    from fastapi.testclient import TestClient

    from app.api import create_app

    with TestClient(create_app(settings)) as c:
        yield c


# --- invented test data (never sample values) -------------------------------------------------

FIELD_LIST = {
    "name": "widget_sheet",
    "fields": {
        "widget_name": {"name": "Widget Name", "description": "Name of the widget."},
        "widget_count": {
            "name": "Widget Count",
            "description": "How many widgets.",
            "primary": True,
        },
    },
}
FIELD_LIST_JSON = json.dumps(FIELD_LIST)

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
CSV_BYTES = b"widget_name,widget_count\nalpha,1\nbeta,2\n"


def _zip(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for n in names:
            z.writestr(n, "<x/>")
    return buf.getvalue()


DOCX_BYTES = _zip(["word/document.xml"])
XLSX_BYTES = _zip(["xl/workbook.xml"])
