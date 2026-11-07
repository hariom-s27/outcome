"""P1-20: make outputs/<doc>.json by sending sample documents through the RUNNING service.

    uv run python scripts/make_outputs.py <doc_id> [<doc_id> ...]

Doc ids are given explicitly (no "all" switch): the agent runs the DEV ids; Hariom runs the
held-out ids (D03). For each id the script looks up the file and field list in
sample/manifest.csv, POSTs both to /jobs, polls GET /jobs/{id} every 2 s (the harness rhythm)
and writes {"schema", "document", "entries", "metadata"} to outputs/<doc>.json, the shape
tools/validate.py batch mode expects.

Prints doc id, job id, status and timings only; never document content or field values.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample"
DOCS = SAMPLE / "sample-data-documents"
SCHEMAS = SAMPLE / "schemas"
OUT = ROOT / "outputs"
TERMINAL = {"SUCCESS", "PARTIAL", "FAILED"}
TIMEOUT_S = 1800  # contract: 30 minutes per document, counted from submission


def manifest() -> dict[str, dict[str, str]]:
    with (SAMPLE / "manifest.csv").open(newline="", encoding="utf-8") as f:
        return {row["document_id"]: row for row in csv.DictReader(f)}


def multipart(file_path: Path, schema_text: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b"".join(
        [
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{file_path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f'--{boundary}\r\nContent-Disposition: form-data; name="schema"\r\n\r\n'.encode(),
            schema_text.encode("utf-8"),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def call(base: str, method: str, path: str, body=None, headers=None) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def run_doc(base: str, doc_id: str, row: dict[str, str]) -> bool:
    schema_text = (SCHEMAS / f"{row['schema_name']}.json").read_text(encoding="utf-8")
    body, ctype = multipart(DOCS / row["file"], schema_text)

    t0 = time.monotonic()
    status, job = call(base, "POST", "/jobs", body, {"Content-Type": ctype})
    while status == 429:  # back off like the harness
        time.sleep(30)
        status, job = call(base, "POST", "/jobs", body, {"Content-Type": ctype})
    if status != 202:
        print(f"{doc_id}: POST /jobs -> {status}")
        return False
    post_ms = (time.monotonic() - t0) * 1000
    job_id = job["job_id"]

    while time.monotonic() - t0 < TIMEOUT_S:
        status, job = call(base, "GET", f"/jobs/{job_id}")
        if status == 200 and job.get("status") in TERMINAL:
            break
        time.sleep(2)
    else:
        print(f"{doc_id}: job {job_id} not terminal after {TIMEOUT_S}s")
        return False

    took = time.monotonic() - t0
    if "result" not in job:
        print(f"{doc_id}: job {job_id} {job['status']} without result ({took:.1f}s)")
        return False
    out = {"schema": row["schema_name"], "document": doc_id, **job["result"]}
    OUT.mkdir(exist_ok=True)
    (OUT / f"{doc_id}.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"{doc_id}: job {job_id} {job['status']} entries={len(out['entries'])} "
        f"post_ms={post_ms:.0f} total_s={took:.1f}"
    )
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("doc_ids", nargs="+", help="document ids from sample/manifest.csv")
    ap.add_argument("--base-url", default="http://localhost:8080")
    args = ap.parse_args()

    rows = manifest()
    unknown = [d for d in args.doc_ids if d not in rows]
    if unknown:
        print(f"unknown doc ids: {', '.join(unknown)}")
        return 2
    if call(args.base_url, "GET", "/health")[0] != 200:
        print("service not healthy; run `docker compose up -d` first")
        return 2
    ok = [run_doc(args.base_url, d, rows[d]) for d in args.doc_ids]
    print(f"{sum(ok)}/{len(ok)} outputs written")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
