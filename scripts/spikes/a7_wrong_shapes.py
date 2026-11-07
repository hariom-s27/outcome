"""A7 (PR-02): shape of each P2 "wrong" cell (both sides non-null, scorer says no match).

Uses the saved P2 run (cache/eval_runs/<last run_id in eval/history.jsonl>) and the scorer's
own norm()/align_rows(). Classes, first that applies:
  number_format   both parse as numbers in different ways, or one side is a number and the
                  other a numeric-looking string
  date_format     one side parses as a date, the other has digits but is not that date
  case_only       equal after lower-casing
  ws_punct_only   equal after removing whitespace and punctuation
  pred_in_truth   normalised prediction is a substring of normalised truth
  truth_in_pred   normalised truth is a substring of normalised prediction
  list_partial    list field with some (not all) items right
  other
Printed: counts per class and per field (field names only).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from _common import RUNS, Report, dev_docs, last_run_id, schema, truth, truth_entries

from app.contract_check import validator


def squash(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def classify(v, pv, tv) -> str:
    if isinstance(tv, list) or isinstance(pv, list):
        pl = pv if isinstance(pv, list) else [pv]
        tl = tv if isinstance(tv, list) else [tv]
        hits = sum(any(v.scalar_match(p, t) == 1.0 for p in pl) for t in tl)
        return "list_partial" if hits else "list_none_right"
    kp, _ = v.norm(pv)
    kt, _ = v.norm(tv)
    sp, st = str(pv), str(tv)
    if kp == "num" and kt == "num":
        return "number_value"  # both numbers, outside tolerance: a different number
    if "num" in (kp, kt) and re.search(r"\d", sp) and re.search(r"\d", st):
        return "number_format"
    if "date" in (kp, kt) and re.search(r"\d", sp) and re.search(r"\d", st):
        return "date_format" if kp != kt else "date_value"
    if sp.lower().strip() == st.lower().strip():
        return "case_only"
    if squash(sp) == squash(st):
        return "ws_punct_only"
    np_, nt = squash(sp), squash(st)
    if np_ and np_ in nt:
        return "pred_in_truth"
    if nt and nt in np_:
        return "truth_in_pred"
    return "other"


def main() -> None:
    v = validator()
    rid = last_run_id()
    rep = Report("a7_wrong_shapes")
    totals: Counter = Counter()
    per_field: dict[str, Counter] = defaultdict(Counter)
    for d in dev_docs():
        path = RUNS / rid / f"{d}.json"
        if not path.exists():
            rep.line(f"{d}: no saved run")
            continue
        job = json.loads(path.read_text(encoding="utf-8"))
        result = job.get("result") or {}
        sch = schema(d)
        fields, primary = v.schema_fields(sch)
        pairs = v.align_rows(result.get("entries", []), truth_entries(truth(d)), primary)
        for pe, te, _label in pairs:  # _label is a row key: never printed
            if pe is None or te is None:
                continue
            for k in fields:
                tv, pv = v.value_of(te, k), v.value_of(pe, k)
                if v.cell_match(pv, tv) == 1.0:
                    continue
                t_null = (not tv) if isinstance(tv, list) else v.norm(tv)[0] == "null"
                p_null = (not pv) if isinstance(pv, list) else v.norm(pv)[0] == "null"
                if t_null or p_null:
                    continue  # missed / hallucinated, not "wrong"
                c = classify(v, pv, tv)
                totals[c] += 1
                per_field[f"{d}.{k}"][c] += 1
    rep.sum(f"run {rid}: wrong cells={sum(totals.values())} by class {dict(totals.most_common())}")
    by_doc: dict[str, list[str]] = defaultdict(list)
    for fk, c in sorted(per_field.items(), key=lambda kv: -sum(kv[1].values())):
        rep.line(f"{fk}: {dict(c.most_common())}")
        doc, field = fk.split(".", 1)
        by_doc[doc].append(f"{field}=" + "+".join(f"{n}x{k}" for k, n in c.most_common()))
    for doc, items in by_doc.items():
        rep.sum(f"{doc}: {', '.join(items)}")
    rep.close()


if __name__ == "__main__":
    main()
