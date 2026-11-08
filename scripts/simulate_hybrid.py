"""Offline hybrid simulation (P5c Part A, H-3): no LLM calls, $0.

For each DEV single-value doc and each saved smart run, merge the smart job's result with the
shipped baseline output (outputs/<doc>.json) field by field with the pre-registered merge
rule (H-2), then score the merged result exactly as eval_dev.py scores a job.

    uv run python scripts/simulate_hybrid.py \\
        --runs 6db0488/run1 6db0488-dirty/run2 6db0488-dirty/run3 \\
        --docs lease_001 lease_002 om_001 --report logs/P5c_hybrid_sim.md

Prints/writes doc ids, scores, source counts, reason codes and hallucination counts only;
never a value, a citation or a row label (D04, R31). Held-out documents are refused.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_dev import HELD_OUT, RUNS, score_doc  # noqa: E402
from make_outputs import OUT, ROOT, manifest  # noqa: E402

# P5-22 bar, unchanged
BAR_MEAN = 0.8385
FLOORS = {"lease_001": 0.675, "lease_002": 0.750, "om_001": 0.9405}
P5B_SMART_MEAN = {"lease_001": 0.5925, "lease_002": 0.7083, "om_001": 0.9195}  # P5b report

# H-2 merge rule (exact reason names in app/pipeline/single_value.py)
SMART_OK = frozenset({"ok", "ok_partial", "computed_ok", "computed_fixed"})
BASELINE_CONF = 0.5


def merge_entry(
    smart: dict[str, Any], base: dict[str, Any], reasons: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """H-2, per field: the smart cell if non-null and its reason is checked; else the baseline
    cell (citation and page_numbers kept; confidence 0.5 if non-null, else its own)."""
    out: dict[str, Any] = {}
    source: dict[str, str] = {}
    for k in base.keys() | smart.keys():
        s, b = smart.get(k) or {}, base.get(k) or {}
        if s.get("value") is not None and reasons.get(k) in SMART_OK:
            out[k] = dict(s)
            source[k] = "smart"
            continue
        cell = dict(b) if b else {"value": None, "citation": "", "confidence": 0.0}
        if cell.get("value") is not None:
            cell["confidence"] = BASELINE_CONF
        out[k] = cell
        source[k] = "baseline"
    return out, source


def smart_reasons(job: dict[str, Any]) -> dict[str, str]:
    ext = ((job.get("result") or {}).get("metadata") or {}).get("extraction") or {}
    fields = ext.get("fields") if isinstance(ext, dict) else None
    return {k: str(v.get("reason")) for k, v in (fields or {}).items() if isinstance(v, dict)}


def baseline_rec(doc: str, schema: str, base_out: dict) -> dict[str, Any]:
    """The shipped baseline output scored as a job (the 'old' numbers)."""
    job = {"status": "SUCCESS", "result": {k: base_out[k] for k in ("entries", "metadata")}}
    return score_doc(doc, schema, job)


def simulate(doc: str, schema: str, smart_job: dict, base_out: dict) -> dict[str, Any]:
    reasons = smart_reasons(smart_job)
    s_entries = (smart_job.get("result") or {}).get("entries") or [{}]
    b_entries = base_out.get("entries") or [{}]
    merged, source = merge_entry(s_entries[0], b_entries[0], reasons)
    meta = dict(base_out.get("metadata") or {})
    meta["extraction"] = {
        "path": "hybrid-sim",
        "source_counts": dict(Counter(source.values())),
    }
    job = {"status": "SUCCESS", "result": {"entries": [merged], "metadata": meta}}
    rec = score_doc(doc, schema, job)
    smart_rec = score_doc(doc, schema, smart_job)
    return {
        "doc": doc,
        "score": rec["score"],
        "valid": rec["valid"],
        "smart_score": smart_rec["score"],
        "source": dict(Counter(source.values())),
        "halluc": rec["totals"]["hallucinated"],
        "halluc_smart": smart_rec["totals"]["hallucinated"],
        "baseline_fields_nonnull": sum(
            1 for k, v in source.items() if v == "baseline" and merged[k].get("value") is not None
        ),
        "reason_to_baseline": dict(
            Counter(reasons.get(k, "absent") for k, v in source.items() if v == "baseline")
        ),
        "per_field": rec["per_field"],
        "source_per_field": source,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", nargs="+", required=True, help="raw run folders: <run_id>/run<n>")
    ap.add_argument("--docs", nargs="+", default=["lease_001", "lease_002", "om_001"])
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()
    rows = manifest()
    if any(d in HELD_OUT for d in args.docs):
        print("refused: held-out documents are sealed")
        return 2

    results: dict[str, list[dict]] = {d: [] for d in args.docs}
    old: dict[str, float] = {}
    for doc in args.docs:
        schema = rows[doc]["schema_name"]
        base_out = json.loads((OUT / f"{doc}.json").read_text(encoding="utf-8"))
        old[doc] = baseline_rec(doc, schema, base_out)["score"]
        for run in args.runs:
            job = json.loads((RUNS / run / f"{doc}.json").read_text(encoding="utf-8"))
            results[doc].append(simulate(doc, schema, job, base_out))

    lines = [
        "# P5c Part A: offline hybrid simulation ($0, no LLM calls)",
        "",
        "Merge rule H-2: smart cell if non-null and reason in "
        f"{{{', '.join(sorted(SMART_OK))}}}; else the baseline cell (confidence "
        f"{BASELINE_CONF} if non-null). Smart = P5b runs `{'`, `'.join(args.runs)}`; "
        "baseline = shipped `outputs/<doc>.json` (P2, n = 1). Score = `tools/validate.py "
        "score()` via `eval_dev.score_doc` (mean of per-field means).",
        "",
        "## Scores",
        "",
        "| Doc | "
        + " | ".join(f"Hybrid r{i + 1}" for i in range(len(args.runs)))
        + " | **Hybrid mean** | Old (baseline) | Smart (re-scored) mean | P5b smart mean | Floor |",
        "|---|" + "---|" * (len(args.runs) + 5),
    ]
    means: dict[str, float] = {}
    for doc in args.docs:
        sc = [r["score"] for r in results[doc]]
        means[doc] = statistics.fmean(sc)
        sm = statistics.fmean(r["smart_score"] for r in results[doc])
        lines.append(
            f"| {doc} | "
            + " | ".join(f"{s:.4f}" for s in sc)
            + f" | **{means[doc]:.4f}** | {old[doc]:.4f} | {sm:.4f} | "
            f"{P5B_SMART_MEAN.get(doc, float('nan')):.4f} | {FLOORS.get(doc, 0):.4f} |"
        )
    lines += [
        "",
        "## Sources, hallucinations, validity (per run)",
        "",
        "| Doc | Run | from smart | from baseline | baseline non-null | halluc. hybrid | "
        "halluc. smart | valid | smart reasons sent to baseline |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for doc in args.docs:
        for i, r in enumerate(results[doc]):
            why = ", ".join(f"{k} {v}" for k, v in sorted(r["reason_to_baseline"].items()))
            lines.append(
                f"| {doc} | {i + 1} | {r['source'].get('smart', 0)} | "
                f"{r['source'].get('baseline', 0)} | {r['baseline_fields_nonnull']} | "
                f"{r['halluc']} | {r['halluc_smart']} | {r['valid']} | {why} |"
            )
    overall = statistics.fmean(means.values())
    mean_ok = overall >= BAR_MEAN
    floor_ok = {d: means[d] >= FLOORS[d] for d in args.docs if d in FLOORS}
    verdict = "PASS" if mean_ok and all(floor_ok.values()) else "FAIL"
    lines += [
        "",
        "## Bar (P5-22, unchanged)",
        "",
        "- Means: "
        + "; ".join(
            f"{d} = ({' + '.join(f'{r["score"]:.4f}' for r in results[d])}) / "
            f"{len(results[d])} = {means[d]:.5f}"
            for d in args.docs
        ),
        f"- Mean test: ({' + '.join(f'{means[d]:.5f}' for d in args.docs)}) / {len(args.docs)}"
        f" = **{overall:.5f}** vs bar {BAR_MEAN} -> {'pass' if mean_ok else 'FAIL'}",
        "- Floor test: "
        + "; ".join(
            f"{d} {means[d]:.4f} {'>=' if ok else '<'} {FLOORS[d]} ({'pass' if ok else 'FAIL'})"
            for d, ok in floor_ok.items()
        ),
        f"- **Verdict: {verdict}**",
        "",
        "## Per-field change vs old (field names only; mean over runs)",
        "",
        "| Doc | field | old | hybrid mean | from smart (runs) |",
        "|---|---|---|---|---|",
    ]
    for doc in args.docs:
        schema = rows[doc]["schema_name"]
        base_out = json.loads((OUT / f"{doc}.json").read_text(encoding="utf-8"))
        old_pf = baseline_rec(doc, schema, base_out)["per_field"]
        for k in sorted(old_pf):
            hm = statistics.fmean(r["per_field"].get(k, 0.0) for r in results[doc])
            if abs(hm - old_pf[k]) > 1e-9:
                n_smart = sum(1 for r in results[doc] if r["source_per_field"].get(k) == "smart")
                lines.append(f"| {doc} | {k} | {old_pf[k]:.2f} | {hm:.2f} | {n_smart} |")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.report:
        report = args.report if args.report.is_absolute() else ROOT / args.report
        report.write_text(text, encoding="utf-8", newline="\n")
        print(f"written: {report.relative_to(ROOT).as_posix()}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
