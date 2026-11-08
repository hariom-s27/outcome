"""Dry run (R-A, P4-05): every DEV doc through the reader + baseline prompt builder, no LLM.

    uv run python scripts/dry_run.py                    # all DEV docs
    uv run python scripts/dry_run.py --docs om_001      # a given list
    uv run python scripts/dry_run.py --path smart       # P5: plan the smart single-value path

Same steps as the worker before its call: read_document(file_type, bytes) ->
baseline.build_messages(field_list, blocks, file_type, est=catalog.estimate) -> the fuse's
high-side token estimate (catalog.estimate.tokens with the builder's kind_chars). No DB, no
key, no network. Prints one line per doc (blocks, images, estimated tokens, any exception
type) and exits 1 on any exception or any estimate >= 90k tokens (R22: Haiku's 100k cliff).
Full records go to cache/dry_run/<utc>.json (git-ignored). No document text is printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from make_outputs import DOCS, ROOT, SCHEMAS, manifest

from app.extract.compile_fields import is_single_value
from app.llm.models import ModelCatalog
from app.pipeline import baseline, single_value
from app.readers import read_document

HELD_OUT = frozenset({"lease_003", "budget_001"})  # D03
TOKEN_LIMIT = 90_000  # R22: every call stays clearly under the 100k price cliff
OUT_DIR = ROOT / "cache" / "dry_run"


def dry_run_doc(doc_id: str, row: dict[str, str], catalog: ModelCatalog) -> dict[str, Any]:
    """One document, as the worker would prepare it. Never raises: errors are recorded."""
    rec: dict[str, Any] = {"doc": doc_id, "ok": False}
    t0 = time.monotonic()
    try:
        path = DOCS / row["file"]
        file_type = path.suffix.lower().lstrip(".")
        field_list = json.loads((SCHEMAS / f"{row['schema_name']}.json").read_text("utf-8"))
        dm = read_document(file_type, path.read_bytes())
        messages, notes = baseline.build_messages(
            field_list, dm.blocks, file_type, est=catalog.estimate
        )
        kind_chars = notes.pop(baseline.KIND_CHARS, None)
        est = catalog.estimate.tokens(messages, kind_chars)
        rec.update(
            file_type=file_type,
            blocks=len(dm.blocks),
            kinds=dict(Counter(b.kind for b in dm.blocks)),
            pages=len({b.page for b in dm.blocks if b.page is not None}),
            images_total=sum(1 for b in dm.blocks if b.kind == "image"),
            images_sent=notes.get("images_sent", 0),
            blocks_sent=notes.get("blocks_sent", 0),
            truncated=notes.get("truncated", False),
            blocks_dropped=notes.get("blocks_dropped", 0),
            builder_tokens_est=notes.get("input_tokens_est", 0),
            fuse_tokens_est=est,
            n_fields=len(field_list.get("fields", {})),
        )
        rec["ok"] = est < TOKEN_LIMIT
        if not rec["ok"]:
            rec["error"] = f"estimate {est} >= {TOKEN_LIMIT}"
    except Exception as exc:  # recorded and fails the gate; the type only (no content, R23)
        rec["error"] = f"{type(exc).__name__}"
        rec["detail"] = str(exc)[:300]  # cache file only, never printed
    rec["seconds"] = round(time.monotonic() - t0, 2)
    return rec


def dry_run_smart(doc_id: str, row: dict[str, str], catalog: ModelCatalog) -> dict[str, Any]:
    """P5 smart path: single-value field lists -> every planned call (locate + read) built with
    the real builders; table field lists -> the baseline record above, unchanged (P5-03)."""
    path = DOCS / row["file"]
    field_list = json.loads((SCHEMAS / f"{row['schema_name']}.json").read_text("utf-8"))
    if not is_single_value(field_list):
        rec = dry_run_doc(doc_id, row, catalog)
        spec = catalog.get(catalog.baseline)
        est = rec.get("fuse_tokens_est", 0)
        rec.update(
            path="baseline(table)",
            calls=[{"purpose": "baseline", "images": rec.get("images_sent", 0),
                    "est_tokens_in": est,
                    "est_usd_fuse": round(spec.cost(est, baseline.MAX_TOKENS), 6)}],
        )  # fmt: skip
        return rec
    rec: dict[str, Any] = {"doc": doc_id, "ok": False, "path": "smart"}
    t0 = time.monotonic()
    try:
        file_type = path.suffix.lower().lstrip(".")
        dm = read_document(file_type, path.read_bytes())
        calls, info = single_value.planned_calls(field_list, dm.blocks, file_type, catalog)
        rec.update(
            file_type=file_type,
            blocks=len(dm.blocks),
            n_fields=len(field_list.get("fields", {})),
            calls=calls,
            **info,
        )
        worst = max((c["est_tokens_in"] for c in calls), default=0)
        rec["ok"] = bool(calls) and worst < TOKEN_LIMIT
        if worst >= TOKEN_LIMIT:
            rec["error"] = f"estimate {worst} >= {TOKEN_LIMIT}"
    except Exception as exc:  # recorded and fails the gate; the type only (no content, R23)
        rec["error"] = f"{type(exc).__name__}"
        rec["detail"] = str(exc)[:300]  # cache file only, never printed
    rec["seconds"] = round(time.monotonic() - t0, 2)
    return rec


def fmt_smart(r: dict[str, Any]) -> str:
    calls = r.get("calls") or []
    if not calls:
        return f"{r['doc']:14s} FAIL {r.get('error')}"
    toks = "/".join(str(c["est_tokens_in"]) for c in calls)
    usd = sum(c.get("est_usd_fuse", 0.0) for c in calls)
    real = sum(c.get("est_usd_realistic", c.get("est_usd_fuse", 0.0)) for c in calls)
    imgs = sum(c.get("images", 0) for c in calls)
    sent = r.get("blocks_sent", 0)
    return (
        f"{r['doc']:14s} {'ok  ' if r['ok'] else 'FAIL'} path={r['path']} "
        f"mode={r.get('mode', '-')} blocks={sent}/{r.get('blocks', 0)} images={imgs} "
        f"calls={len(calls)} est_tokens={toks} est$={usd:.4f} (real {real:.4f})"
        + (f" error={r['error']}" if r.get("error") else "")
    )


def run(docs: list[str] | None = None, path: str = "baseline") -> tuple[bool, list[dict[str, Any]]]:
    rows = manifest()
    docs = docs or [d for d in rows if d not in HELD_OUT]
    sealed = [d for d in docs if d in HELD_OUT]
    if sealed:
        return False, [{"doc": "-", "ok": False, "error": f"{len(sealed)} held-out ids refused"}]
    unknown = [d for d in docs if d not in rows]
    if unknown:
        return False, [{"doc": d, "ok": False, "error": "unknown doc id"} for d in unknown]
    catalog = ModelCatalog.load()
    one = dry_run_smart if path == "smart" else dry_run_doc
    records = [one(d, rows[d], catalog) for d in docs]
    return all(r["ok"] for r in records), records


def fmt(r: dict[str, Any]) -> str:
    if "fuse_tokens_est" not in r:
        return f"{r['doc']:14s} FAIL {r.get('error')}"
    return (
        f"{r['doc']:14s} {'ok  ' if r['ok'] else 'FAIL'} type={r['file_type']} "
        f"blocks={r['blocks']} sent={r['blocks_sent']} images={r['images_sent']}/"
        f"{r['images_total']} truncated={r['truncated']} est_tokens={r['fuse_tokens_est']} "
        f"{r['seconds']}s" + (f" error={r['error']}" if r.get("error") else "")
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--docs", nargs="+", help="DEV doc ids (default: every DEV doc)")
    ap.add_argument(
        "--path",
        choices=["baseline", "smart"],
        default="baseline",
        help="EXTRACT_SINGLE_VALUE_PATH to plan for (P5)",
    )
    args = ap.parse_args(argv)
    ok, records = run(args.docs, args.path)
    for r in records:
        print(fmt_smart(r) if args.path == "smart" else fmt(r))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    (OUT_DIR / f"{stamp}.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"dry run {'PASSED' if ok else 'FAILED'} ({len(records)} docs)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
