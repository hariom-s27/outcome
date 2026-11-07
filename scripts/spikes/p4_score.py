"""Host-side scorer for P4 spike runs (P4-07, P4-15): grades cache/spikes/<run_id>/<doc>__<variant>
.json with tools/validate.py's score() (via scripts/eval_dev.score_doc) against the DEV
answers, read inside this script only. Answers are never mounted into a container.

    uv run python scripts/spikes/p4_score.py --run <run_id> [<run_id> ...]

Prints per prediction one line (score, error counts, $, calls, latency) and, for repeated
variants (b3-r1..rN), mean / min / max / spread per doc. Appends one line per prediction to
eval/spikes.jsonl (per-field scores and counts, byproducts; field names and numbers only,
D04/R31). Never prints or stores a value, a row label or a citation.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import eval_dev  # noqa: E402
from make_outputs import manifest  # noqa: E402

ROOT = HERE.parents[1]
SPIKES = ROOT / "cache" / "spikes"
LEDGER = ROOT / "eval" / "spikes.jsonl"
HELD_OUT = frozenset({"lease_003", "budget_001"})
REPEAT = re.compile(r"-r\d+$")
META_KEYS = (
    "model_calls", "tokens_in", "tokens_out", "tokens_reasoning", "cost_usd",
    "cost_computed_usd", "latency_ms", "models_returned", "images_sent", "repair_calls",
    "conflicts", "conflict_fields", "batches", "batches_ok", "pages_sent", "pages_chosen",
    "locate_calls", "ocr_cpu_seconds", "groups", "groups_ok", "truncated", "cost_fuse",
    "reason",
)  # fmt: skip


def score_file(path: Path, rows: dict[str, dict[str, str]]) -> dict[str, Any]:
    doc, variant = path.stem.split("__", 1)
    if doc in HELD_OUT:
        raise SystemExit("refused: held-out document in a spike run (P4-16)")
    job = json.loads(path.read_text(encoding="utf-8"))
    rec = eval_dev.score_doc(doc, rows[doc]["schema_name"], job)
    meta = (job.get("result") or {}).get("metadata") or job.get("metadata") or {}
    keep = ("score", "valid", "per_field", "per_field_counts", "totals", "extra_rows",
            "missing_rows", "rows_predicted", "rows_truth")  # fmt: skip
    return {"doc": doc, "variant": variant, "status": job.get("status"),
            **{k: rec[k] for k in keep if k in rec},
            **{k: meta[k] for k in META_KEYS if k in meta}}  # fmt: skip


def call_stats(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Per (doc, variant) byproducts from calls.jsonl (P4-12): metadata only, no content.
    json_mode_ok = JSON mode was sent and no call of the variant failed with an error."""
    path = run_dir / "calls.jsonl"
    if not path.exists():
        return {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            x = json.loads(raw)
            groups.setdefault((x.get("doc", ""), x.get("variant", "")), []).append(x)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, ls in groups.items():
        ok = [x for x in ls if x.get("status") == "ok"]
        errors: dict[str, int] = {}
        for x in ls:
            st = x.get("status") or ""
            if st != "ok" and not st.startswith("skipped"):
                errors[st] = errors.get(st, 0) + 1
        per_img = [x["image_tokens_per_image_est"] for x in ok
                   if isinstance(x.get("image_tokens_per_image_est"), int | float)]  # fmt: skip
        reported = [x["cost_reported_usd"] for x in ok
                    if isinstance(x.get("cost_reported_usd"), int | float)]  # fmt: skip
        sent = any(x.get("json_mode_sent") for x in ls)
        out[key] = {
            "calls_ok": len(ok),
            "calls_logged": len(ls),
            "models_requested": sorted(
                {x["model_requested"] for x in ls if x.get("model_requested")}
            ),  # fmt: skip
            "models_returned": sorted(
                {x["model_returned"] for x in ok if x.get("model_returned")}
            ),  # fmt: skip
            "json_mode_sent": sent,
            "json_mode_ok": sent and not errors,
            "repair_calls": sum(1 for x in ok if x.get("purpose") == "repair"),
            "finish_length": sum(1 for x in ok if x.get("finish_reason") == "length"),
            "tokens_reasoning": sum(x.get("tokens_reasoning") or 0 for x in ok),
            "cost_reported_usd": round(sum(reported), 6) if reported else None,
            "cost_computed_usd": round(sum(x.get("cost_computed_usd") or 0.0 for x in ok), 6),
            "image_tokens_per_image": round(statistics.fmean(per_img)) if per_img else None,
            "cap_hit": any(str(x.get("status", "")).startswith("skipped_max") for x in ls),
            "errors": errors,
        }
    return out


def fmt_calls(doc: str, variant: str, c: dict[str, Any]) -> str:
    return (
        f"  calls {doc} {variant}: ok={c['calls_ok']}/{c['calls_logged']} "
        f"returned={','.join(c['models_returned']) or '-'} json_ok={c['json_mode_ok']} "
        f"repair={c['repair_calls']} reasoning={c['tokens_reasoning']} "
        f"img_tok/page={c['image_tokens_per_image']} $rep={c['cost_reported_usd']} "
        f"$comp={c['cost_computed_usd']} cap_hit={c['cap_hit']} errors={c['errors'] or '-'}"
    )


def spread(recs: list[dict[str, Any]]) -> list[str]:
    groups: dict[tuple[str, str], list[float]] = {}
    for r in recs:
        groups.setdefault((r["doc"], REPEAT.sub("", r["variant"])), []).append(r["score"])
    return [
        f"  {doc} {base}: n={len(v)} mean={statistics.fmean(v):.3f} min={min(v):.3f} "
        f"max={max(v):.3f} spread={max(v) - min(v):.3f}"
        for (doc, base), v in groups.items()
        if len(v) > 1
    ]


def fmt(r: dict[str, Any]) -> str:
    t = r.get("totals") or {}
    return (
        f"{r['doc']} {r['variant']}: score={r.get('score', 0):.3f} valid={r.get('valid')} "
        f"wrong={t.get('wrong', 0)} missed={t.get('missed', 0)} "
        f"halluc={t.get('hallucinated', 0)} $={r.get('cost_usd', 0):.5f} "
        f"calls={r.get('model_calls', 0)} latency={r.get('latency_ms', 0)}ms"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", nargs="+", required=True, help="run ids under cache/spikes/")
    ap.add_argument("--no-record", action="store_true", help="do not append eval/spikes.jsonl")
    args = ap.parse_args(argv)
    rows = manifest()
    out: list[dict[str, Any]] = []
    for run_id in args.run:
        run_dir = SPIKES / run_id
        summary_path = run_dir / "summary.json"
        summary = json.loads(summary_path.read_text("utf-8")) if summary_path.exists() else {}
        launch_path = run_dir / "launch.json"
        launch = json.loads(launch_path.read_text("utf-8")) if launch_path.exists() else {}
        recs = [score_file(p, rows) for p in sorted(run_dir.glob("*__*.json"))]
        stats = call_stats(run_dir)
        print(
            f"run {run_id}: predictions={len(recs)} spent=${summary.get('spent_usd', 0):.4f} "
            f"stop={summary.get('stop')} dry_run_gate={launch.get('dry_run')} "
            f"allow_dirty={launch.get('allow_dirty_used')}"
        )
        for r in recs:
            print(fmt(r))
            if (r["doc"], r["variant"]) in stats:
                print(fmt_calls(r["doc"], r["variant"], stats[(r["doc"], r["variant"])]))
        for line in spread(recs):
            print(line)
        for r in recs:
            out.append({"run_id": run_id, "spike": summary.get("spike"),
                        "git_sha": run_id.split("-", 1)[0],
                        "tree_clean": launch.get("allow_dirty_used") is False,
                        "gates": {k: launch.get(k) for k in ("dry_run", "allow_dirty_used")},
                        "calls": stats.get((r["doc"], r["variant"]), {}),
                        **r})  # fmt: skip
    if not args.no_record and out:
        LEDGER.parent.mkdir(exist_ok=True)
        with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
            for r in out:
                fh.write(json.dumps(r) + "\n")
        print(f"recorded {len(out)} lines: {LEDGER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
