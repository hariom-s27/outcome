"""HTTP role: POST /jobs, GET /jobs/{job_id}, GET /health (contract/openapi.yaml)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app import db, filetypes, lab
from app.config import Settings

log = logging.getLogger("app.api")

TERMINAL_WITH_RESULT = {"SUCCESS", "PARTIAL"}
RETRY_AFTER_S = 30
MAX_ORG_ID_LEN = 256
MAX_WEBHOOK_LEN = 2048


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers


def _error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        {"code": exc.code, "message": exc.message}, status_code=exc.status, headers=exc.headers
    )


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _org(request: Request) -> str | None:
    org = (request.headers.get("x-organization-id") or "").strip()
    return org or None


def job_view(row: dict[str, Any]) -> dict[str, Any]:
    """JobStatus body. Optional keys are omitted rather than null (OpenAPI 3.1, see CLAUDE.md)."""
    body: dict[str, Any] = {
        "job_id": str(row["id"]),
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }
    if row.get("stage") and row["status"] == "RUNNING":
        body["stage"] = row["stage"]
    if row["status"] in TERMINAL_WITH_RESULT and row.get("result") is not None:
        body["result"] = row["result"]
    if row.get("error") is not None:
        body["error"] = row["error"]
    return body


# --- request validation --------------------------------------------------------------------------


def parse_field_list(raw: str) -> dict[str, Any]:
    """Loose rule (approved): object with a non-empty `fields` object of objects whose
    `name` / `description`, when present, are strings."""
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        raise ApiError(400, "invalid_schema", "schema is not valid JSON") from None
    if not isinstance(doc, dict):
        raise ApiError(400, "invalid_schema", "schema must be a JSON object")
    fields = doc.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ApiError(400, "invalid_schema", "schema needs a non-empty `fields` object")
    for key, spec in fields.items():
        if not key or not isinstance(spec, dict):
            raise ApiError(400, "invalid_schema", "each field must be an object with a key")
        for attr in ("name", "description"):
            if attr in spec and not isinstance(spec[attr], str):
                raise ApiError(400, "invalid_schema", f"field `{attr}` must be a string")
    return doc


def parse_webhook(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    url = raw.strip()
    parts = urlsplit(url)
    if len(url) > MAX_WEBHOOK_LEN or parts.scheme not in ("http", "https") or not parts.hostname:
        raise ApiError(400, "invalid_webhook_url", "webhook_url must be an http(s) URL")
    return url


# --- app ---------------------------------------------------------------------------------------


def create_app(settings: Settings | None = None, *, migrate_on_start: bool = False) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if migrate_on_start:
            # uvicorn accepts connections only after this, so /health never answers early
            await run_in_threadpool(db.migrate_with_retry, settings.database_url)
        yield

    app = FastAPI(title="Outcome DocExtract", version=settings.version, lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc)

    @app.get("/health")
    async def health() -> JSONResponse:
        def ping() -> None:
            with db.connect(settings.database_url, connect_timeout=2) as conn:
                conn.execute("SELECT 1")

        try:
            await asyncio.wait_for(run_in_threadpool(ping), timeout=1.0)
        except (TimeoutError, psycopg.Error) as exc:
            log.warning("health: db check failed (%s)", type(exc).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok", "version": settings.version})

    @app.post("/jobs", status_code=202)
    async def create_job(request: Request) -> JSONResponse:
        # 413 early when the declared body is clearly over the limit (1 MB slack for form parts)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 2**20:
            raise ApiError(413, "file_too_large", "file is larger than the upload limit")

        try:
            form = await request.form(max_files=1, max_fields=10)
        except (MultiPartException, StarletteHTTPException, ValueError):
            raise ApiError(
                400, "malformed_request", "body must be valid multipart/form-data"
            ) from None
        try:
            upload = form.get("file")
            schema_raw = form.get("schema")
            webhook_raw = form.get("webhook_url")
            # P9b: read only in LAB_MODE; the shipped service never looks at this part
            debug_raw = form.get("debug_model") if settings.lab_mode else None
            if not isinstance(upload, UploadFile):
                raise ApiError(400, "missing_file", "multipart part `file` is required")
            if not isinstance(schema_raw, str) or not schema_raw.strip():
                raise ApiError(400, "missing_schema", "multipart part `schema` is required")
            if webhook_raw is not None and not isinstance(webhook_raw, str):
                raise ApiError(400, "invalid_webhook_url", "webhook_url must be a string")

            content = await upload.read(settings.max_upload_bytes + 1)
            if len(content) > settings.max_upload_bytes:
                raise ApiError(413, "file_too_large", "file is larger than the upload limit")
            if not content:
                raise ApiError(400, "missing_file", "uploaded file is empty")
            filename = upload.filename
        finally:
            await form.close()

        org = _org(request)
        if org and len(org) > MAX_ORG_ID_LEN:
            raise ApiError(400, "invalid_org", "X-Organization-Id is too long")
        field_list = parse_field_list(schema_raw)
        try:
            field_list = lab.attach_debug_model(settings, field_list, debug_raw)
        except lab.BadDebugModel as exc:
            raise ApiError(400, "invalid_debug_model", str(exc)) from None
        webhook_url = parse_webhook(webhook_raw)
        file_type = filetypes.detect(filename, content)
        if file_type is None:
            raise ApiError(400, "unsupported_file_type", "file must be PDF, DOCX, XLSX or CSV")

        row = await run_in_threadpool(
            _insert_job, settings, org, field_list, file_type, content, webhook_url
        )
        log.info(
            "job %s created status=%s type=%s bytes=%d",
            row["id"],
            row["status"],
            file_type,
            len(content),
        )
        return JSONResponse(job_view(row), status_code=202)

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request) -> JSONResponse:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            raise ApiError(404, "not_found", "job not found") from None
        row = await run_in_threadpool(_fetch_job, settings, jid, _org(request))
        if row is None:
            raise ApiError(404, "not_found", "job not found")
        return JSONResponse(job_view(row))

    return app


# --- db operations (run in the threadpool) --------------------------------------------------------

_JOB_COLUMNS = "id, status, stage, result, error, created_at, updated_at"


def _insert_job(settings, org, field_list, file_type, content, webhook_url) -> dict[str, Any]:
    from psycopg.rows import dict_row

    job_id = uuid.uuid4()
    with db.connect(settings.database_url, row_factory=dict_row) as conn, conn.transaction():
        pending = conn.execute("SELECT count(*) AS n FROM jobs WHERE status = 'PENDING'").fetchone()
        if pending["n"] >= settings.max_pending:
            raise ApiError(
                429,
                "too_many_jobs",
                "queue is full; retry later",
                headers={"Retry-After": str(RETRY_AFTER_S)},
            )
        row = conn.execute(
            f"""INSERT INTO jobs (id, org_id, status, field_list, file_type, file_size,
                                 webhook_url, deadline_at)
                VALUES (%s, %s, 'PENDING', %s, %s, %s, %s, now() + make_interval(secs => %s))
                RETURNING {_JOB_COLUMNS}""",
            (
                job_id,
                org,
                Jsonb(field_list),
                file_type,
                len(content),
                webhook_url,
                settings.job_deadline_s,
            ),
        ).fetchone()
        conn.execute("INSERT INTO job_files (job_id, content) VALUES (%s, %s)", (job_id, content))
        conn.execute("INSERT INTO job_events (job_id, event) VALUES (%s, 'CREATED')", (job_id,))
    return row


def _fetch_job(settings, job_id: uuid.UUID, org: str | None) -> dict[str, Any] | None:
    from psycopg.rows import dict_row

    with db.connect(settings.database_url, row_factory=dict_row) as conn:
        # IS NOT DISTINCT FROM: org job needs the same header; org-less job needs no header (P1-13)
        return conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = %s AND org_id IS NOT DISTINCT FROM %s",
            (job_id, org),
        ).fetchone()


def main() -> None:  # pragma: no cover - container entry point
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(migrate_on_start=True), host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()
