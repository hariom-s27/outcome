"""DEV eval loop (P2-18, P2-19, P2-30, P2-32): run DEV documents through the RUNNING service
over HTTP, score them with tools/validate.py's score(), record the numbers.

    uv run python scripts/eval_dev.py                      # all 6 DEV docs, --max-usd 0.15
    uv run python scripts/eval_dev.py --docs boxscore_001 --max-usd 0.03 --no-record \\
        --label reasoning=none                             # pilot
    uv run python scripts/eval_dev.py --reuse <run_id>     # re-score a saved run, no HTTP
    uv run python scripts/eval_dev.py --docs lease_002 --expect-live --run-index 1  # P5 live

--expect-live (P5 D-1): every job's calls must be live; one dev-cache replay -> exit 3,
nothing scored or recorded. History lines carry path, cache_mode, run_index, prompt_version,
all_live (P5 D-2).

HTTP only (localhost:8080): submit, poll every 2 s, read result.metadata.cost_usd for the
--max-usd stop. No key, no DB. Documents run one at a time; the run aborts when the spend
reaches --max-usd or when 2 documents in a row end with an LLM failure reason.
Held-out documents are refused unless --final-sealed (P8 only).

Prints/writes: doc ids, field names, scores, counts, $ and latency. Never row labels, primary
keys or any cell value (D04, R31): the row labels validate.py builds are used in memory only.
Raw job results go to cache/eval_runs/<run_id>/run<run_index>/ (git-ignored; P5b F-8).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dry_run
import run_gates
from make_outputs import DOCS, OUT, ROOT, SCHEMAS, TERMINAL, TIMEOUT_S, call, manifest, multipart

from app.contract_check import validator

TRUTH = ROOT / "sample" / "sample-data-output-validated"
RUNS = ROOT / "cache" / "eval_runs"
HISTORY = ROOT / "eval" / "history.jsonl"
REPORT = ROOT / "logs" / "eval_latest.md"  # --report: never overwrite an older phase's report
HELD_OUT = frozenset({"lease_003", "budget_001"})  # D03: sealed until the P8 run
LLM_FAILURE_REASONS = frozenset(
    {"llm_failed", "circuit_open", "llm_not_configured", "dev_budget_reached", "deadline"}
)


# --- scoring + error taxonomy -------------------------------------------------------------------


def value_type(v: Any) -> str:
    if isinstance(v, list):
        return "list"
    kind = validator().norm(v)[0]
    return {"num": "number", "date": "date", "bool": "bool", "str": "text"}.get(kind, "null")


def taxonomy(result: dict, truth: dict, schema: dict) -> dict[str, Any]:
    """wrong / missed (wrongly null) / hallucinated per field and per truth value type.
    Cells in extra or missing rows are counted under rows, not per field."""
    v = validator()
    fields, primary = v.schema_fields(schema)
    truth_entries = truth.get("entries", truth if isinstance(truth, list) else [truth])
    pairs = v.align_rows(result.get("entries", []), truth_entries, primary)
    per_field: dict[str, Counter] = {k: Counter() for k in fields}
    per_type: dict[str, Counter] = {}
    extra = missing = 0
    for pe, te, _label in pairs:  # _label is a row key: never printed or stored
        if te is None:
            extra += 1
            continue
        if pe is None:
            missing += 1
            continue
        for k in fields:
            tv, pv = v.value_of(te, k), v.value_of(pe, k)
            t_type = value_type(tv)
            if v.cell_match(pv, tv) == 1.0:
                outcome = "right"
            elif t_type == "null":
                outcome = "hallucinated"
            elif (not pv) if isinstance(pv, list) else v.norm(pv)[0] == "null":
                outcome = "missed"
            else:
                outcome = "wrong"
            per_field[k][outcome] += 1
            per_type.setdefault(t_type, Counter())[outcome] += 1
    totals = Counter()
    for c in per_field.values():
        totals.update(c)
    return {
        "per_field_counts": {k: dict(c) for k, c in per_field.items()},
        "per_type": {k: dict(c) for k, c in sorted(per_type.items())},
        "totals": {k: totals.get(k, 0) for k in ("right", "wrong", "missed", "hallucinated")},
        "extra_rows": extra,
        "missing_rows": missing,
    }


def score_doc(doc_id: str, schema_name: str, job: dict) -> dict[str, Any]:
    v = validator()
    schema = json.loads((SCHEMAS / f"{schema_name}.json").read_text(encoding="utf-8"))
    rec: dict[str, Any] = {"doc": doc_id, "status": job.get("status")}
    if "result" not in job:
        rec.update(valid=False, score=0.0)
        return rec
    result = job["result"]
    meta = result.get("metadata", {})
    shaped = {"schema": schema_name, "document": doc_id, **result}
    rec["valid"] = v.validate_contract(shaped, schema) == []
    truth = json.loads((TRUTH / f"{doc_id}.json").read_text(encoding="utf-8"))
    rep = v.score(result, truth, schema)
    tax = taxonomy(result, truth, schema)
    rec.update(
        score=rep["score"],
        per_field=rep["per_field"],
        rows_predicted=rep["rows"]["predicted"],
        rows_truth=rep["rows"]["truth"],
        **tax,
        terminal_reason=meta.get("terminal_reason"),
        cost_usd=float(meta.get("cost_usd", 0.0)),
        cost_computed_usd=float(meta.get("cost_computed_usd", 0.0)),
        # graders have no dev cache: a cache hit is priced at the call that filled it
        cost_uncached_usd=float(meta.get("cost_uncached_usd", meta.get("cost_usd", 0.0))),
        model_calls=meta.get("model_calls", 0),
        tokens_in=meta.get("tokens_in", 0),
        tokens_out=meta.get("tokens_out", 0),
        tokens_reasoning=meta.get("tokens_reasoning", 0),
        latency_ms=meta.get("latency_ms", 0),
        models_returned=meta.get("models_returned", []),
        reasoning_effort=meta.get("reasoning_effort"),
        cache_hits=meta.get("cache_hits", 0),
        truncated=bool(meta.get("truncated", False)),
        path=doc_path(job),
        cache_mode=meta.get("cache_mode", "unknown"),
        replays=replays(job),
        # P8b: baseline cut-off / loop flags (P6b B-6) and the scan page choice (Z-13)
        output_flags=list(meta.get("output_flags") or []),
        scan_pages=scan_pages(meta),
    )
    return rec


def scan_pages(meta: dict) -> str:
    """'first' (default path), or 'locate:<result>' when the Z-13 page choice ran."""
    sp = meta.get("scan_pages")
    return f"locate:{sp.get('result', '?')}" if isinstance(sp, dict) else "first"


# --- P5 D-1 / D-2: live runs and what a history line records ------------------------------------


def _meta(job: dict) -> dict:
    return ((job.get("result") or {}).get("metadata")) or {}


def replays(job: dict) -> int:
    """Calls of this job answered from the dev cache (ledger cache_hit rows)."""
    meta = _meta(job)
    ext = meta.get("extraction") if isinstance(meta.get("extraction"), dict) else {}
    return max(int(meta.get("cache_hits", 0) or 0), int(ext.get("cache_replays", 0) or 0))


def doc_path(job: dict) -> str:
    """'smart' when the single-value smart path ran (even if it fell back); P6: 'table:<ai|
    heuristic|fallback>' when the long-table spec path ran; else 'baseline'."""
    ext = _meta(job).get("extraction")
    if isinstance(ext, dict) and ext.get("path") == "smart":
        return "smart"
    if isinstance(ext, dict) and ext.get("path") == "table":
        return f"table:{(ext.get('table') or {}).get('chosen', '?')}"
    return "baseline"


# --- running ------------------------------------------------------------------------------------


def run_id() -> str:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout

    sha = git("rev-parse", "--short", "HEAD").strip() or "nogit"
    dirty = "-dirty" if git("status", "--porcelain", "--untracked-files=no").strip() else ""
    return f"{sha}{dirty}"


def run_folder(rid: str, run_index: int) -> Path:
    """P5b F-8: one raw folder per run, <RUNS>/<sha>[-dirty]/run<index>/, so runs of the same
    commit never overwrite each other. --reuse / --reuse-from take '<sha>[-dirty]/run<n>'
    (or an older flat '<sha>' folder)."""
    return RUNS / rid / f"run{int(run_index)}"


def submit_and_wait(base: str, doc_id: str, row: dict[str, str]) -> dict:
    schema_text = (SCHEMAS / f"{row['schema_name']}.json").read_text(encoding="utf-8")
    body, ctype = multipart(DOCS / row["file"], schema_text)
    t0 = time.monotonic()
    status, job = call(base, "POST", "/jobs", body, {"Content-Type": ctype})
    while status == 429:
        time.sleep(30)
        status, job = call(base, "POST", "/jobs", body, {"Content-Type": ctype})
    if status != 202:
        return {"status": f"POST_{status}"}
    job_id = job["job_id"]
    while time.monotonic() - t0 < TIMEOUT_S:
        status, job = call(base, "GET", f"/jobs/{job_id}")
        if status == 200 and job.get("status") in TERMINAL:
            return job
        time.sleep(2)
    return {"status": "TIMEOUT", "job_id": job_id}


def fmt_doc(r: dict) -> str:
    t = r.get("totals", {})
    return (
        f"{r['doc']:14s} {r.get('status', '?'):8s} valid={r.get('valid')} "
        f"score={r.get('score', 0):.3f} rows={r.get('rows_predicted', '-')}/"
        f"{r.get('rows_truth', '-')} wrong={t.get('wrong', 0)} missed={t.get('missed', 0)} "
        f"halluc={t.get('hallucinated', 0)} reason={r.get('terminal_reason')} "
        f"calls={r.get('model_calls', 0)} in={r.get('tokens_in', 0)} out={r.get('tokens_out', 0)} "
        f"reasoning={r.get('tokens_reasoning', 0)} cost=${r.get('cost_usd', 0):.5f} "
        f"(computed ${r.get('cost_computed_usd', 0):.5f}, "
        f"uncached ${r.get('cost_uncached_usd', 0):.5f}) latency={r.get('latency_ms', 0)}ms "
        f"model={','.join(r.get('models_returned') or []) or '-'} "
        f"flags={','.join(r.get('output_flags') or []) or '-'} "
        f"scan_pages={r.get('scan_pages', 'first')}"
    )


def default_docs(rows: dict[str, dict], final_sealed: bool) -> list[str]:
    """Every DEV doc; with --final-sealed (P8b Z-7) every manifest doc, held-out included, so
    the held-out ids never have to be typed on a command line."""
    return [d for d in rows if final_sealed or d not in HELD_OUT]


def paid_run_gates(
    live_docs: list[str], allow_dirty: bool, skip_dry_run: bool, git=None
) -> tuple[bool, dict[str, Any]]:
    """PR-09 + R-A before any paid run. Returns (may run, what the report records)."""
    ok, msg = run_gates.clean_tree_gate(allow_dirty, **({"git": git} if git else {}))
    print(msg)
    gates: dict[str, Any] = {"allow_dirty_used": allow_dirty and msg.startswith("DIRTY")}
    if not ok:
        return False, gates
    if skip_dry_run:
        print("dry run SKIPPED by --skip-dry-run")
        gates["dry_run"] = "skipped"
        return True, gates
    # P8b Z-7: the dry run never opens a held-out document (dry_run refuses them); held-out
    # documents are opened once, by the sealed run itself.
    passed, recs = dry_run.run([d for d in live_docs if d not in HELD_OUT])
    for r in recs:
        if not r.get("ok"):
            print(dry_run.fmt(r))
    print(f"dry run {'passed' if passed else 'FAILED'} ({len(recs)} docs)")
    gates["dry_run"] = "passed" if passed else "failed"
    if not passed:
        print("refused: fix the dry-run failure first, or --skip-dry-run with Hariom's yes")
    return passed, gates


def summarise(
    records: list[dict],
    rid: str,
    label: str,
    aborted: str | None,
    gates: dict[str, Any] | None = None,
    run_index: int = 1,
    final: bool = False,
) -> dict:
    from app.pipeline.single_value import PROMPT_VERSION

    scored = [r for r in records if "score" in r]
    paths = sorted({r.get("path") or "baseline" for r in scored})
    modes = sorted({r.get("cache_mode") or "unknown" for r in scored})
    lat = [r["latency_ms"] for r in scored if r.get("latency_ms")]
    totals = Counter()
    for r in scored:
        totals.update(r.get("totals", {}))
    cost = sum(r.get("cost_usd", 0.0) for r in scored)
    uncached = sum(r.get("cost_uncached_usd", r.get("cost_usd", 0.0)) for r in scored)
    models = sorted({m for r in scored for m in r.get("models_returned") or []})
    pipelines = sorted({r.get("pipeline") or "" for r in scored} - {""})
    dev = [r for r in scored if r["doc"] not in HELD_OUT]
    held = [r for r in scored if r["doc"] in HELD_OUT]
    return {
        "run_id": rid,
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # P8b Z-7/Z-8: the sealed final run; DEV and held-out reported apart
        "final": bool(final),
        "n_dev": len(dev),
        "dev_mean_score": round(statistics.fmean(r["score"] for r in dev), 4) if dev else 0.0,
        "held_out_per_doc": {r["doc"]: r["score"] for r in held},
        "pipeline": ",".join(pipelines) or "unknown",
        "model": ",".join(models) or "-",
        "label": label,
        "reasoning_effort_sent": sorted({r.get("reasoning_effort") or "default" for r in scored}),
        "n_docs": len(scored),
        "mean_score": round(statistics.fmean(r["score"] for r in scored), 4) if scored else 0.0,
        "per_doc": {r["doc"]: r["score"] for r in scored},
        "all_valid": all(r.get("valid") for r in scored),
        "wrong": totals.get("wrong", 0),
        "missed": totals.get("missed", 0),
        "hallucinated": totals.get("hallucinated", 0),
        "extra_rows": sum(r.get("extra_rows", 0) for r in scored),
        "missing_rows": sum(r.get("missing_rows", 0) for r in scored),
        "cost_usd": round(cost, 6),
        "cost_computed_usd": round(sum(r.get("cost_computed_usd", 0.0) for r in scored), 6),
        "cost_uncached_usd": round(uncached, 6),
        "usd_per_doc": round(uncached / len(scored), 6) if scored else 0.0,  # uncached
        "usd_per_doc_paid": round(cost / len(scored), 6) if scored else 0.0,
        "tokens_reasoning": sum(r.get("tokens_reasoning", 0) for r in scored),
        "cache_hits": sum(r.get("cache_hits", 0) for r in scored),
        "p50_latency_ms": int(statistics.median(lat)) if lat else 0,
        "aborted": aborted,
        # P4-05/06: a report must say when a gate was bypassed
        "dry_run": (gates or {}).get("dry_run", "not_run"),
        "allow_dirty_used": bool((gates or {}).get("allow_dirty_used", False)),
        # P5 D-2
        "path": "+".join(paths) or "unknown",
        "path_per_doc": {r["doc"]: r.get("path") or "baseline" for r in scored},
        "cache_mode": "+".join(modes) or "unknown",
        "run_index": int(run_index),
        "prompt_version": PROMPT_VERSION,
        "all_live": bool(scored) and all(r.get("replays", 0) == 0 for r in scored),
        # P8b: metadata only (flag names, page-choice result)
        "output_flags_per_doc": {r["doc"]: r.get("output_flags") or [] for r in scored},
        "scan_pages_per_doc": {r["doc"]: r.get("scan_pages", "first") for r in scored},
    }


def reason_extras(r: dict) -> str:
    """P8b: output flags and a non-default page choice, appended to the reason column."""
    out = ""
    if r.get("output_flags"):
        out += " flags=" + ",".join(r["output_flags"])
    if r.get("scan_pages", "first") != "first":
        out += " scan_pages=" + r["scan_pages"]
    return out


def write_report(records: list[dict], summary: dict, report: Path = REPORT) -> None:
    if summary.get("final"):  # P8b Z-8: DEV mean and held-out count stated apart
        head = (
            f"**DEV mean {summary['dev_mean_score']:.3f} over n = {summary['n_dev']} DEV docs; "
            f"held-out (scored once): {len(summary['held_out_per_doc'])} docs** · "
        )
    else:
        head = (
            f"**Mean score {summary['mean_score']:.3f} over n = {summary['n_docs']} DEV docs** · "
        )
    lines = [
        "# DEV eval (baseline)",
        "",
        f"Run `{summary['run_id']}` · {summary['date']} · pipeline `{summary['pipeline']}` · "
        f"model `{summary['model']}` · {summary['label']}",
        "",
        "Score = mean of per-field means (tools/validate.py `score()`), per document. "
        "Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is "
        "null). Extra/missing rows score 0 on every field and are counted separately. "
        "$ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document "
        "costs with no cache (a hit is priced at the ledger cost of the call that filled it), "
        "the figure a grader pays and the one used for $/doc.",
        "",
        "| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | "
        "extra/missing rows | $ paid | $ uncached | latency s | reason |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        t = r.get("totals", {})
        lines.append(
            f"| {r['doc']} | {r.get('status')} | {r.get('valid')} | {r.get('score', 0):.3f} | "
            f"{r.get('rows_predicted', '-')}/{r.get('rows_truth', '-')} | {t.get('wrong', 0)} | "
            f"{t.get('missed', 0)} | {t.get('hallucinated', 0)} | "
            f"{r.get('extra_rows', 0)}/{r.get('missing_rows', 0)} | "
            f"{r.get('cost_usd', 0):.5f} | {r.get('cost_uncached_usd', 0):.5f} | "
            f"{r.get('latency_ms', 0) / 1000:.1f} | "
            f"{r.get('terminal_reason') or ''}{reason_extras(r)} |"
        )
    lines += [
        "",
        head + f"paid ${summary['cost_usd']:.5f} (computed ${summary['cost_computed_usd']:.5f}) · "
        f"uncached ${summary['cost_uncached_usd']:.5f} · "
        f"**${summary['usd_per_doc']:.5f}/doc uncached** · p50 latency "
        f"{summary['p50_latency_ms'] / 1000:.1f} s · reasoning tokens "
        f"{summary['tokens_reasoning']}"
        + (f" · ABORTED: {summary['aborted']}" if summary["aborted"] else ""),
        "",
        f"Gates: dry run `{summary.get('dry_run', 'not_run')}` · --allow-dirty used: "
        f"`{summary.get('allow_dirty_used', False)}`",
        "",
        "## Errors by truth value type (cells in matched rows)",
        "",
        "| doc | type | right | wrong | missed | halluc. |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        for typ, c in (r.get("per_type") or {}).items():
            lines.append(
                f"| {r['doc']} | {typ} | {c.get('right', 0)} | {c.get('wrong', 0)} | "
                f"{c.get('missed', 0)} | {c.get('hallucinated', 0)} |"
            )
    lines += ["", "## Per-field scores (field names only)", ""]
    for r in records:
        if not r.get("per_field"):
            continue
        lines.append(f"### {r['doc']} ({r.get('score', 0):.3f})")
        lines.append("")
        lines.append("| field | score | wrong | missed | halluc. |")
        lines.append("|---|---|---|---|---|")
        for k, s in sorted(r["per_field"].items(), key=lambda kv: kv[1]):
            c = (r.get("per_field_counts") or {}).get(k, {})
            lines.append(
                f"| {k} | {s:.2f} | {c.get('wrong', 0)} | {c.get('missed', 0)} | "
                f"{c.get('hallucinated', 0)} |"
            )
        lines.append("")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--docs", nargs="+", help="DEV doc ids (default: every DEV doc)")
    ap.add_argument("--max-usd", type=float, default=0.15)
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--label", default="", help="free text recorded with the run")
    ap.add_argument("--no-record", action="store_true", help="pilot: no history/report")
    ap.add_argument("--write-outputs", action="store_true", help="refresh outputs/<doc>.json")
    ap.add_argument("--reuse", metavar="RUN_ID", help="re-score a saved run, no HTTP")
    ap.add_argument("--final-sealed", action="store_true", help="P8 sealed run only")
    ap.add_argument(
        "--report",
        type=Path,
        default=REPORT,
        help="markdown report path (default logs/eval_latest.md)",
    )
    ap.add_argument(
        "--reuse-from",
        metavar="RUN_ID",
        help="run only --docs live; re-score every other DEV doc from this saved run",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="run on an uncommitted tree (Hariom's yes only; recorded)",
    )
    ap.add_argument(
        "--skip-dry-run",
        action="store_true",
        help="skip the dry-run gate (Hariom's yes only; recorded)",
    )
    ap.add_argument(
        "--expect-live",
        action="store_true",
        help="P5: refuse to score if any job replayed a call from the dev cache",
    )
    ap.add_argument(
        "--run-index", type=int, default=1, help="P5: run number (1..n) recorded in history"
    )
    args = ap.parse_args()
    if args.reuse_from and (args.reuse or not args.docs):
        ap.error("--reuse-from needs --docs and cannot be combined with --reuse")
    report = args.report if args.report.is_absolute() else ROOT / args.report

    rows = manifest()
    docs = args.docs or default_docs(rows, args.final_sealed)
    sealed = [d for d in docs if d in HELD_OUT]
    if sealed and not args.final_sealed:
        print(f"refused: held-out documents are sealed until P8 ({len(sealed)} requested)")
        return 2
    unknown = [d for d in docs if d not in rows]
    if unknown:
        print(f"unknown doc ids: {', '.join(unknown)}")
        return 2
    gates: dict[str, Any] = {}
    if not args.reuse:  # a paid run: clean tree (PR-09) and dry run (R-A) first
        ok, gates = paid_run_gates(docs, args.allow_dirty, args.skip_dry_run)
        if not ok:
            return 2

    rid = args.reuse or run_id()
    run_dir = RUNS / rid if args.reuse else run_folder(rid, args.run_index)
    run_dir.mkdir(parents=True, exist_ok=True)
    if not args.reuse and call(args.base_url, "GET", "/health")[0] != 200:
        print("service not healthy; start the dev stack first")
        return 2

    records: list[dict] = []
    jobs: list[tuple[str, dict]] = []
    spent = 0.0
    fail_streak = 0
    aborted = None
    live = set(docs)
    if args.reuse_from:  # docs in --docs run live; every other DEV doc is re-scored from it
        docs = [d for d in rows if d not in HELD_OUT]
    for doc_id in docs:
        if not args.reuse and doc_id in live and spent >= args.max_usd:
            aborted = f"max_usd {args.max_usd} reached before {doc_id}"
            break
        raw_path = run_dir / f"{doc_id}.json"
        if args.reuse:
            job = json.loads(raw_path.read_text(encoding="utf-8"))
        elif doc_id not in live:
            src = RUNS / args.reuse_from / f"{doc_id}.json"
            job = json.loads(src.read_text(encoding="utf-8"))
            raw_path.write_text(json.dumps(job, indent=1), encoding="utf-8", newline="\n")
        else:
            job = submit_and_wait(args.base_url, doc_id, rows[doc_id])
            raw_path.write_text(json.dumps(job, indent=1), encoding="utf-8", newline="\n")
        meta = _meta(job)
        spent += float(meta.get("cost_usd", 0.0) or 0.0)
        if args.expect_live:  # P5 D-1: no score is computed until every job is known live
            print(
                f"{doc_id:14s} {job.get('status', '?'):8s} calls={meta.get('model_calls', 0)} "
                f"replays={replays(job)} cache_mode={meta.get('cache_mode', 'unknown')}",
                flush=True,
            )
            if replays(job):
                print(f"refused: {doc_id} replayed {replays(job)} call(s) from the dev cache; "
                      "no scores computed or recorded (--expect-live)")  # fmt: skip
                return 3
        jobs.append((doc_id, job))
        reason = meta.get("terminal_reason")
        fail_streak = fail_streak + 1 if reason in LLM_FAILURE_REASONS else 0
        if fail_streak >= 2:
            aborted = "2 documents in a row ended with an LLM failure reason"
            break

    for doc_id, job in jobs:
        rec = score_doc(doc_id, rows[doc_id]["schema_name"], job)
        rec["pipeline"] = _meta(job).get("pipeline")
        records.append(rec)
        print(fmt_doc(rec), flush=True)
        if args.write_outputs and rec.get("valid") and "result" in job:
            OUT.mkdir(exist_ok=True)
            out = {"schema": rows[doc_id]["schema_name"], "document": doc_id, **job["result"]}
            (OUT / f"{doc_id}.json").write_text(
                json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n"
            )

    summary = summarise(
        records, rid, args.label, aborted, gates, args.run_index, final=args.final_sealed
    )
    summary["raw_dir"] = run_dir.relative_to(RUNS).as_posix()
    print(
        f"\nMEAN {summary['mean_score']:.3f} n={summary['n_docs']} "
        f"all_valid={summary['all_valid']} "
        f"wrong={summary['wrong']} missed={summary['missed']} halluc={summary['hallucinated']} "
        f"cost=${summary['cost_usd']:.5f} (computed ${summary['cost_computed_usd']:.5f}) "
        f"uncached=${summary['cost_uncached_usd']:.5f} "
        f"$/doc(uncached)={summary['usd_per_doc']:.5f} p50={summary['p50_latency_ms']}ms "
        f"reasoning_tokens={summary['tokens_reasoning']}"
        + (f" ABORTED: {aborted}" if aborted else "")
    )
    if not args.no_record:
        HISTORY.parent.mkdir(exist_ok=True)
        with HISTORY.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(summary) + "\n")
        write_report(records, summary, report)
        print(f"recorded: {HISTORY.relative_to(ROOT)}, {report}")
    return 1 if aborted else 0


if __name__ == "__main__":
    sys.exit(main())
