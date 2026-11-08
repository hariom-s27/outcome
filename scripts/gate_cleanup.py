"""P9c Z-59 targeted-fix gate for TABLE_CLEANUP (pre-registered before runs 154-156).

    uv run python scripts/gate_cleanup.py --cand 154 155 156

Declared docs and their bases (fixed): syn_budget_pdf, syn_rentroll_pdf -> grid runs 141-143;
rentroll_001, syn_rentroll_xlsx -> runs 104-106. Candidate runs are re-scored from their raw
jobs, like compare_runs. The switch passes only if ALL hold:
  (i)   no declared doc's mean score is below its base mean
  (ii)  targeted error cells, summed over the declared docs (mean per run per doc), are strictly
        fewer than the base's. A targeted error cell is a cell of a matched row that does not
        match the truth and whose predicted value is text that EITHER is a whole-cell
        placeholder (app.tables.cleanup.is_placeholder) where the truth is null (a hallucinated
        placeholder) OR carries a trailing continued-marker (cleanup.strip_continued changes it;
        a wrong section label)
  (iii) paired hallucinations (compare_runs Z-50) summed over the declared docs <= base
  plus every candidate output VALID.
Step (iv), the full --set all must-not-error run, is a separate run and check.
Prints doc ids, counts, scores only (no values). Exit 0 = PASS, 1 = FAIL, 2 = bad selector.
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

import compare_runs as cr
import doc_sets
import eval_dev

from app.tables.cleanup import is_placeholder, strip_continued

BASES = {
    "syn_budget_pdf": ["141", "142", "143"],
    "syn_rentroll_pdf": ["141", "142", "143"],
    "rentroll_001": ["104", "105", "106"],
    "syn_rentroll_xlsx": ["104", "105", "106"],
}
DOCS = list(BASES)


def targeted_cells(doc_id: str, row: dict, job: dict) -> int:
    """Targeted error cells of one job (see the module doc). Counts only; nothing kept."""
    v = eval_dev.validator()
    own = row if "truth_path" in row else None
    schema = json.loads(eval_dev._schema_file(row["schema_name"], own).read_text(encoding="utf-8"))
    truth = json.loads(eval_dev._truth_file(doc_id, own).read_text(encoding="utf-8"))
    fields, primary = v.schema_fields(schema)
    truth_entries = truth.get("entries", truth if isinstance(truth, list) else [truth])
    pred = (job.get("result") or {}).get("entries", [])
    n = 0
    for pe, te, _label in v.align_rows(pred, truth_entries, primary):  # label never kept
        if pe is None or te is None:
            continue
        for k in fields:
            pv, tv = v.value_of(pe, k), v.value_of(te, k)
            if not isinstance(pv, str) or v.cell_match(pv, tv) == 1.0:
                continue
            placeholder = is_placeholder(pv) and eval_dev.value_type(tv) == "null"
            if placeholder or strip_continued(pv) != pv:
                n += 1
    return n


def side_targeted(selectors: list[str], doc: str, history: list[dict], rows: dict) -> float:
    entries, _notes = cr.resolve(selectors, history)
    counts = []
    for e in entries:
        raw = eval_dev.RUNS / e["raw_dir"] / f"{doc}.json"
        if not raw.exists():
            raise cr.SelectorError(f"{doc}: raw job missing for run {e['raw_dir']}")
        counts.append(targeted_cells(doc, rows[doc], json.loads(raw.read_text(encoding="utf-8"))))
    return statistics.fmean(counts)


def gate(base: dict, cand: dict, t_base: dict, t_cand: dict) -> dict[str, Any]:
    below = [d for d in DOCS if cand[d]["score"] < base[d]["score"] - 1e-9]
    tb, tc = sum(t_base.values()), sum(t_cand.values())
    paired = {d: cr.paired_halluc(base[d], cand[d]) for d in DOCS}
    hb, hc = sum(p[0] for p in paired.values()), sum(p[1] for p in paired.values())
    invalid = [d for d in DOCS if not cand[d]["valid"]]
    checks = {
        "no_doc_below": (not below, f"{len(below)} docs below their base mean"
                         + (f": {', '.join(below)}" if below else "")),
        "targeted": (tc < tb, f"targeted error cells cand {tc:.1f} vs base {tb:.1f} "
                     "(strictly fewer needed)"),
        "halluc_paired": (hc <= hb + 1e-9, f"paired cand {hc:.1f} vs base {hb:.1f}"),
        "all_valid": (not invalid, f"{len(invalid)} invalid"),
    }  # fmt: skip
    return {
        "verdict": "PASS" if all(ok for ok, _ in checks.values()) else "FAIL",
        "checks": checks,
        "paired": paired,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cand", nargs="+", required=True, help="candidate run_index selectors")
    args = ap.parse_args(argv)
    history = cr.load_history(eval_dev.HISTORY)
    rows = doc_sets.rows_for("all")
    try:
        base: dict[str, dict] = {}
        t_base: dict[str, float] = {}
        for doc, sel in BASES.items():
            base.update(cr.restrict(cr.side(sel, history, rows, eval_dev.RUNS), [doc]))
            t_base[doc] = side_targeted(sel, doc, history, rows)
        cand = cr.restrict(cr.side(args.cand, history, rows, eval_dev.RUNS), DOCS)
        t_cand = {d: side_targeted(args.cand, d, history, rows) for d in DOCS}
    except cr.SelectorError as exc:
        print(f"error: {exc}")
        return 2
    if set(cand) != set(DOCS):
        print(f"error: candidate runs cover {len(cand)} of {len(DOCS)} declared docs")
        return 2
    cr.print_table(base, cand)
    g = gate(base, cand, t_base, t_cand)
    print("\nper doc (mean per run): targeted cells base -> cand | halluc paired | total")
    for d in DOCS:
        pb, pc, n = g["paired"][d]
        tb, tc = base[d]["halluc"], cand[d]["halluc"]
        print(f"  {d:18s} targeted {t_base[d]:.1f} -> {t_cand[d]:.1f} | paired ({n} rows) "
              f"{pb:.1f} -> {pc:.1f} | total {tb:.1f} -> {tc:.1f}")  # fmt: skip
    print("\nGATE (P9c Z-59 targeted fix)")
    for name, (ok, msg) in g["checks"].items():
        print(f"  {'pass' if ok else 'FAIL'}  {name:14s} {msg}")
    print(f"VERDICT: {g['verdict']}")
    return 0 if g["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
