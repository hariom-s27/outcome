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
        print(
            f"run {run_id}: predictions={len(recs)} spent=${summary.get('spent_usd', 0):.4f} "
            f"stop={summary.get('stop')} dry_run_gate={launch.get('dry_run')} "
            f"allow_dirty={launch.get('allow_dirty_used')}"
        )
        for r in recs:
            print(fmt(r))
        for line in spread(recs):
            print(line)
        for r in recs:
            out.append({"run_id": run_id, "spike": summary.get("spike"),
                        "gates": {k: launch.get(k) for k in ("dry_run", "allow_dirty_used")},
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
