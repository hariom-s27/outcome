"""Dry run (R-A, P4-05): every DEV doc through the reader + baseline prompt builder, no LLM.

    uv run python scripts/dry_run.py                    # all DEV docs
    uv run python scripts/dry_run.py --docs om_001      # a given list
    uv run python scripts/dry_run.py --path smart       # P5: plan the smart single-value path
    uv run python scripts/dry_run.py --table-path spec  # P6: plan the long-table spec path
    uv run python scripts/dry_run.py --scan-pages locate  # P8b: plan locate page choice

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
from app.pipeline import baseline, baseline_located, single_value, table_spec
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


def dry_run_table(doc_id: str, row: dict[str, str], catalog: ModelCatalog) -> dict[str, Any]:
    """P6: EXTRACT_TABLE_PATH=spec. Table field lists -> table_spec.plan (path chosen, preview
    tokens, calls, est. $, the heuristic spec's checks); a doc that keeps the baseline also
    gets the baseline record. Single-value lists -> the baseline record (path unchanged)."""
    rec = dry_run_doc(doc_id, row, catalog)
    try:
        path = DOCS / row["file"]
        file_type = path.suffix.lower().lstrip(".")
        field_list = json.loads((SCHEMAS / f"{row['schema_name']}.json").read_text("utf-8"))
        if is_single_value(field_list):
            rec["table"] = {"path": "baseline", "why": "single_value"}
            return rec
        dm = read_document(file_type, path.read_bytes())
        plan = table_spec.plan(field_list, dm.blocks, file_type, catalog)
        rec["table"] = plan
        if plan["path"] == "table_spec":
            rec["ok"] = plan["est_tokens_in"] < TOKEN_LIMIT
            if not rec["ok"]:
                rec["error"] = f"estimate {plan['est_tokens_in']} >= {TOKEN_LIMIT}"
    except Exception as exc:  # recorded and fails the gate; the type only (no content, R23)
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}"
        rec["detail"] = str(exc)[:300]  # cache file only, never printed
    return rec


def dry_run_scan(doc_id: str, row: dict[str, str], catalog: ModelCatalog) -> dict[str, Any]:
    """P8b Z-13: SCAN_PAGE_METHOD=locate. The baseline record, plus, for a single-value list on
    a scan with more than 8 page images, the planned locate calls (real builders, no LLM). The
    baseline call is planned on the first 8 pages (the locate answer is unknown)."""
    rec = dry_run_doc(doc_id, row, catalog)
    try:
        path = DOCS / row["file"]
        file_type = path.suffix.lower().lstrip(".")
        field_list = json.loads((SCHEMAS / f"{row['schema_name']}.json").read_text("utf-8"))
        if not is_single_value(field_list):
            rec["scan"] = {"locate": False, "why": "table_list"}
            return rec
        dm = read_document(file_type, path.read_bytes())
        info = baseline_located.plan_pages(dm.blocks)
        calls = []
        if info["locate"]:
            images = [b for b in dm.blocks if b.kind == "image"]
            thumbs = [single_value.thumbnail(b) for b in images]
            n = len(field_list.get("fields", {}))
            for i in range(0, len(thumbs), single_value.MAX_IMAGES):
                group = thumbs[i : i + single_value.MAX_IMAGES]
                msgs = single_value.locate_messages(field_list, group)
                calls.append(single_value._call_line("locate", msgs, None, group, n, catalog))
        rec["scan"] = {**info, "locate_calls": calls}
        worst = max((c["est_tokens_in"] for c in calls), default=0)
        if worst >= TOKEN_LIMIT:
            rec["ok"] = False
            rec["error"] = f"locate estimate {worst} >= {TOKEN_LIMIT}"
    except Exception as exc:  # recorded and fails the gate; the type only (no content, R23)
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}"
        rec["detail"] = str(exc)[:300]  # cache file only, never printed
    return rec


def fmt_scan(r: dict[str, Any]) -> str:
    s = r.get("scan") or {}
    calls = s.get("locate_calls") or []
    usd = sum(c.get("est_usd_realistic", 0.0) for c in calls)
    return (
        f"{fmt(r)} scan_locate={s.get('locate', False)} image_pages={s.get('image_pages', '-')} "
        f"locate_calls={len(calls)} locate_est$={usd:.4f}"
    )


def fmt_table(r: dict[str, Any]) -> str:
    t = r.get("table") or {}
    if not t:
        return f"{r['doc']:14s} FAIL {r.get('error')}"
    head = f"{r['doc']:14s} {'ok  ' if r['ok'] else 'FAIL'} path={t.get('path')} why={t.get('why')}"
    if t.get("path") != "table_spec":
        return (
            f"{head} data_lines={t.get('data_lines', '-')} baseline_est_tokens="
            f"{r.get('fuse_tokens_est', '-')}" + (f" error={r['error']}" if r.get("error") else "")
        )
    h = t.get("heuristic") or {}
    return (
        f"{head} data_lines={t['data_lines']} preview_tokens={t['est_tokens_in']} "
        f"calls={t['calls_planned']} (max {t['calls_max']}) est$={t['est_usd_realistic']:.4f} "
        f"(fuse {t['est_usd_fuse']:.4f}) heuristic_score={h.get('score', '-')} "
        f"heuristic_hard_fail={h.get('hard_fail', '-')} rows={h.get('rows', '-')} "
        f"heuristic_doc_filled={h.get('doc_filled', '-')}"
        + (f" error={r['error']}" if r.get("error") else "")
    )


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


def run(
    docs: list[str] | None = None,
    path: str = "baseline",
    table_path: str = "baseline",
    scan_pages: str = "first",
) -> tuple[bool, list[dict[str, Any]]]:
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
    if table_path == "spec":
        one = dry_run_table
    if scan_pages == "locate":
        one = dry_run_scan
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
    ap.add_argument(
        "--table-path",
        choices=["baseline", "spec"],
        default="baseline",
        help="EXTRACT_TABLE_PATH to plan for (P6)",
    )
    ap.add_argument(
        "--scan-pages",
        choices=["first", "locate"],
        default="first",
        help="SCAN_PAGE_METHOD to plan for (P8b)",
    )
    args = ap.parse_args(argv)
    switches = [args.path == "smart", args.table_path == "spec", args.scan_pages == "locate"]
    if sum(switches) > 1:
        ap.error("plan one switch at a time: --path smart, --table-path spec or --scan-pages")
    ok, records = run(args.docs, args.path, args.table_path, args.scan_pages)
    for r in records:
        if args.scan_pages == "locate":
            print(fmt_scan(r))
        elif args.table_path == "spec":
            print(fmt_table(r))
        else:
            print(fmt_smart(r) if args.path == "smart" else fmt(r))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    (OUT_DIR / f"{stamp}.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"dry run {'PASSED' if ok else 'FAILED'} ({len(records)} docs)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
