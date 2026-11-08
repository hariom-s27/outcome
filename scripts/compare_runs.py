"""P9a D49: compare a candidate setting against a base, per document, and apply the gate.

    uv run python scripts/compare_runs.py --base 90 103 101 102 --cand 111 112 113 114
    uv run python scripts/compare_runs.py --base 90 103 101 102            # base table only

A selector is a history run_index (e.g. 101) or a raw_dir ('<sha>[-dirty]/run<n>') from
eval/history.jsonl. When several history lines share a run_index, the last one is used and a
note is printed. Each run's saved raw jobs are re-scored with eval_dev.score_doc (the
tools/validate.py score), so DEV and SYN runs are scored the same way. Held-out documents are
skipped before anything is opened.

Per doc and side: mean score over that side's runs, delta, hallucinated and missed cells
(mean per run), rows predicted/truth (mean per run), $/doc (uncached, mean per run), valid.

Gate (D49, fixed before any experiment). The candidate passes only if ALL hold:
  1. mean score over DEV+SYN docs (per-doc mean over the runs given, then mean over docs)
     >= base mean + 0.025
  2. no DEV doc's mean score drops by more than 0.05
  3. total hallucinations (sum over docs of mean hallucinated cells per run) <= base total
  4. candidate mean $/doc (uncached, over every candidate run x doc) <= $0.01
  5. every candidate output VALID
  plus: both sides cover the same documents (else the verdict is FAIL: incomplete).

Prints doc ids, field-free counts, scores and $ only (D04, R31). Exit 0 = PASS (or base-only
table), 1 = FAIL, 2 = bad selector or missing raw run.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import doc_sets
import eval_dev

GATE_MIN_GAIN = 0.025
GATE_MAX_DEV_DROP = 0.05
GATE_MAX_USD_PER_DOC = 0.01


class SelectorError(Exception):
    pass


def load_history(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def resolve(selectors: list[str], history: list[dict]) -> tuple[list[dict], list[str]]:
    """Selectors -> history lines (last match wins), plus notes about ambiguous matches."""
    out, notes = [], []
    for sel in selectors:
        if sel.isdigit():
            hits = [h for h in history if int(h.get("run_index", -1)) == int(sel)]
        else:
            hits = [h for h in history if h.get("raw_dir") == sel]
        if not hits:
            raise SelectorError(f"no history line for selector {sel!r}")
        if len(hits) > 1:
            notes.append(f"selector {sel}: {len(hits)} history lines, using the last")
        out.append(hits[-1])
    return out, notes


def run_records(entry: dict, rows: dict[str, dict], runs_dir: Path) -> list[dict]:
    """Re-score one recorded run from its raw jobs. Held-out docs are never opened."""
    raw_dir = entry.get("raw_dir")
    if not raw_dir:
        raise SelectorError(f"history line run_index={entry.get('run_index')} has no raw_dir")
    recs = []
    for doc_id in entry.get("per_doc", {}):
        if doc_id in eval_dev.HELD_OUT:
            continue
        if doc_id not in rows:
            raise SelectorError(f"{doc_id}: not in any manifest")
        raw = runs_dir / raw_dir / f"{doc_id}.json"
        if not raw.exists():
            raise SelectorError(f"{doc_id}: raw job missing for run {raw_dir}")
        job = json.loads(raw.read_text(encoding="utf-8"))
        row = rows[doc_id]
        own = {"row": row} if "truth_path" in row else {}
        rec = eval_dev.score_doc(doc_id, row["schema_name"], job, **own)
        rec["set"] = doc_sets.set_of(doc_id)
        recs.append(rec)
    return recs


def aggregate(records: list[dict]) -> dict[str, dict[str, Any]]:
    """Per doc: means over that doc's runs."""
    by_doc: dict[str, list[dict]] = {}
    for r in records:
        by_doc.setdefault(r["doc"], []).append(r)
    out = {}
    for doc, rs in by_doc.items():
        tot = [r.get("totals", {}) for r in rs]
        out[doc] = {
            "set": doc_sets.set_of(doc),
            "n": len(rs),
            "score": statistics.fmean(r.get("score", 0.0) for r in rs),
            "halluc": statistics.fmean(t.get("hallucinated", 0) for t in tot),
            "missed": statistics.fmean(t.get("missed", 0) for t in tot),
            "rows_pred": statistics.fmean(r.get("rows_predicted", 0) or 0 for r in rs),
            "rows_truth": statistics.fmean(r.get("rows_truth", 0) or 0 for r in rs),
            "usd": statistics.fmean(r.get("cost_uncached_usd", 0.0) for r in rs),
            "valid": all(r.get("valid") for r in rs),
        }
    return out


def gate(base: dict[str, dict], cand: dict[str, dict]) -> dict[str, Any]:
    common = sorted(set(base) & set(cand))
    only = sorted(set(base) ^ set(cand))
    mb = statistics.fmean(base[d]["score"] for d in common) if common else 0.0
    mc = statistics.fmean(cand[d]["score"] for d in common) if common else 0.0
    drops = [d for d in common if cand[d]["set"] == "dev"
             and cand[d]["score"] - base[d]["score"] < -GATE_MAX_DEV_DROP]  # fmt: skip
    hb = sum(base[d]["halluc"] for d in common)
    hc = sum(cand[d]["halluc"] for d in common)
    n_c = sum(cand[d]["n"] for d in common)
    usd_c = sum(cand[d]["usd"] * cand[d]["n"] for d in common) / n_c if n_c else 0.0
    invalid = [d for d in common if not cand[d]["valid"]]
    checks = {
        "same_docs": (not only and bool(common), f"{len(common)} common, {len(only)} one-sided"),
        "mean_gain": (mc >= mb + GATE_MIN_GAIN - 1e-9,
                      f"cand {mc:.4f} vs base {mb:.4f} (+{GATE_MIN_GAIN} needed, "
                      f"delta {mc - mb:+.4f})"),
        "no_dev_drop": (not drops, f"{len(drops)} DEV docs drop > {GATE_MAX_DEV_DROP}"
                        + (f": {', '.join(drops)}" if drops else "")),
        "halluc": (hc <= hb + 1e-9, f"cand {hc:.1f} vs base {hb:.1f}"),
        "usd_per_doc": (usd_c <= GATE_MAX_USD_PER_DOC,
                        f"cand ${usd_c:.5f}/doc (max ${GATE_MAX_USD_PER_DOC})"),
        "all_valid": (not invalid, f"{len(invalid)} invalid"
                      + (f": {', '.join(invalid)}" if invalid else "")),
    }  # fmt: skip
    return {
        "verdict": "PASS" if all(ok for ok, _ in checks.values()) else "FAIL",
        "checks": checks,
        "common": common,
        "one_sided": only,
        "mean_base": mb,
        "mean_cand": mc,
    }


def fmt_side(a: dict | None) -> str:
    if not a:
        return f"{'-':>6} {'-':>6} {'-':>6} {'-':>9} {'-':>9} {'-':>4}"
    rows = f"{a['rows_pred']:.0f}/{a['rows_truth']:.0f}"
    return (
        f"{a['score']:6.3f} {a['halluc']:6.1f} {a['missed']:6.1f} {rows:>9} "
        f"{a['usd']:9.5f} {'yes' if a['valid'] else 'NO':>4}"
    )


def print_table(base: dict, cand: dict | None) -> None:
    head = f"{'score':>6} {'halluc':>6} {'missed':>6} {'rows p/t':>9} {'$/doc':>9} {'ok':>4}"
    print(
        f"{'doc':18s} {'set':4s} {'n':>3} | BASE {head}"
        + (f" | CAND {head} | delta" if cand is not None else "")
    )
    for doc in sorted(set(base) | set(cand or {}), key=lambda d: (doc_sets.set_of(d), d)):
        b, c = base.get(doc), (cand or {}).get(doc)
        n = f"{(b or c)['n']}" + (f"/{c['n']}" if b and c else "")
        line = f"{doc:18s} {doc_sets.set_of(doc):4s} {n:>3} |      {fmt_side(b)}"
        if cand is not None:
            delta = f"{c['score'] - b['score']:+.3f}" if b and c else "-"
            line += f" |      {fmt_side(c)} | {delta}"
        print(line)
    for name, agg in (("BASE", base), ("CAND", cand)):
        if not agg:
            continue
        for s in ("dev", "syn"):
            docs = [a for a in agg.values() if a["set"] == s]
            if docs:
                print(f"{name} {s.upper()} mean {statistics.fmean(a['score'] for a in docs):.4f} "
                      f"over n = {len(docs)} docs; halluc {sum(a['halluc'] for a in docs):.1f}; "
                      f"missed {sum(a['missed'] for a in docs):.1f}")  # fmt: skip
        print(f"{name} DEV+SYN mean {statistics.fmean(a['score'] for a in agg.values()):.4f} "
              f"over n = {len(agg)} docs")  # fmt: skip


def side(selectors: list[str], history: list[dict], rows: dict, runs_dir: Path) -> dict:
    entries, notes = resolve(selectors, history)
    for n in notes:
        print(f"note: {n}")
    recs = [r for e in entries for r in run_records(e, rows, runs_dir)]
    return aggregate(recs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", nargs="+", required=True, help="run_index or raw_dir selectors")
    ap.add_argument("--cand", nargs="+", help="run_index or raw_dir selectors")
    args = ap.parse_args(argv)
    history = load_history(eval_dev.HISTORY)
    rows = doc_sets.rows_for("all")
    try:
        base = side(args.base, history, rows, eval_dev.RUNS)
        cand = side(args.cand, history, rows, eval_dev.RUNS) if args.cand else None
    except SelectorError as exc:
        print(f"error: {exc}")
        return 2
    print_table(base, cand)
    if cand is None:
        return 0
    g = gate(base, cand)
    print("\nGATE (D49)")
    for name, (ok, msg) in g["checks"].items():
        print(f"  {'pass' if ok else 'FAIL'}  {name:12s} {msg}")
    print(f"VERDICT: {g['verdict']}")
    return 0 if g["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
