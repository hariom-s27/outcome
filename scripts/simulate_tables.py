"""Free table gate (P6 Part B, T-12): no LLM calls, $0.

For each long-table DEV doc: read -> profile -> heuristic spec -> execute on every line ->
checks -> score exactly as eval_dev.py scores a job. Old score = the shipped
outputs/<doc>.json re-scored the same way. Also prints the T-16b ship-rule targets from the
re-scored shipped outputs (rentroll_001, t12_001, boxscore_001).

    uv run python scripts/simulate_tables.py --report logs/P6_free_gate.md

Prints/writes doc ids, field names, scores, counts, check numbers and column letters only;
never a value, a header text, a sheet name or a row label (D04, R31). Held-out docs refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_dev import HELD_OUT, score_doc  # noqa: E402
from make_outputs import DOCS, OUT, ROOT, SCHEMAS, manifest  # noqa: E402

from app.pipeline import table_spec  # noqa: E402
from app.readers import read_document  # noqa: E402
from app.tables import heuristic  # noqa: E402
from app.tables.profile import profile_blocks  # noqa: E402
from app.tables.spec import validate_spec  # noqa: E402

DEFAULT_DOCS = ["rentroll_001", "t12_001"]
SHIP_DOCS = ["rentroll_001", "t12_001", "boxscore_001"]
NO_REGRESSION = 0.025  # T-16b: each table doc's 3-run mean >= old - this
MEAN_GAIN = 0.05  # T-16b: mean of the two gains >= this
BOX_DROP = 0.025  # T-16b: boxscore_001 may not drop by more than this


def old_score(doc: str, schema: str) -> dict[str, Any]:
    out = json.loads((OUT / f"{doc}.json").read_text(encoding="utf-8"))
    job = {"status": "SUCCESS", "result": {k: out[k] for k in ("entries", "metadata")}}
    return score_doc(doc, schema, job)


def source_label(rule: dict[str, Any] | None, kind: str) -> str:
    if rule is None:
        return kind
    if "col" in rule:
        return f"col {rule['col']} ({rule.get('fold', 'first_nonempty')})"
    return next(iter(rule))


def simulate(doc: str, row: dict[str, str]) -> dict[str, Any]:
    schema = row["schema_name"]
    path = DOCS / row["file"]
    file_type = path.suffix.lower().lstrip(".")
    field_list = json.loads((SCHEMAS / f"{schema}.json").read_text(encoding="utf-8"))
    dm = read_document(file_type, path.read_bytes())
    ok, why, _wp = table_spec.applies(field_list, dm.blocks, file_type)
    wp = profile_blocks(dm.blocks)
    rec: dict[str, Any] = {"doc": doc, "applies": ok, "why": why}
    rec["data_lines"] = wp.data_line_count()
    raw = heuristic.build(field_list, wp)
    spec, errors = validate_spec(raw, field_list, wp, "heuristic") if raw else (None, ["none"])
    rec["old"] = old_score(doc, schema)
    if spec is None:
        rec.update(valid=False, errors=len(errors), score=0.0)
        return rec
    cand = table_spec.run_candidate(spec, wp, field_list)
    entries = table_spec.entries_with_confidence(cand["ex"], table_spec.CONF_HEURISTIC)
    meta = {"model_calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "latency_ms": 0}
    meta["extraction"] = {"path": "table-sim", "table": table_spec.summary(cand)}
    job = {"status": "SUCCESS", "result": {"entries": entries or [{}], "metadata": meta}}
    scored = score_doc(doc, schema, job) if entries else {"score": 0.0, "valid": False}
    rec.update(
        valid=True,
        score=scored["score"],
        result_valid=scored.get("valid"),
        rows=scored.get("rows_predicted", 0),
        rows_truth=scored.get("rows_truth", rec["old"].get("rows_truth")),
        per_field=scored.get("per_field", {}),
        totals=scored.get("totals", {}),
        spec_score=cand["score"],
        filled=cand["filled"],
        rank=cand["rank"],
        hard_fail=cand["hard_fail"],
        checks={k: c.as_dict() for k, c in cand["checks"].items()},
        lines=dict(sorted(cand["ex"].dispositions.items())),
        duplicates=cand["ex"].duplicates,
        key_column=spec.key_column,
        header_row_found=spec.header_row is not None,
        sources={
            k: source_label(spec.row_fields.get(k), kind)
            for k, kind in sorted(cand["ex"].field_sources.items())
        },
    )
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--docs", nargs="+", default=DEFAULT_DOCS)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--title", default="P6 Part B: free table gate ($0, no LLM calls)")
    args = ap.parse_args()
    rows = manifest()
    if any(d in HELD_OUT for d in args.docs + SHIP_DOCS):
        print("refused: held-out documents are sealed")
        return 2
    recs = [simulate(d, rows[d]) for d in args.docs]
    olds = {d: old_score(d, rows[d]["schema_name"])["score"] for d in SHIP_DOCS}

    lines = [
        f"# {args.title}",
        "",
        "Heuristic spec (header match, no model) -> executor on every line -> checks -> "
        "`eval_dev.score_doc` (tools/validate.py `score()`, mean of per-field means). Old = the "
        "shipped `outputs/<doc>.json` re-scored the same way (n = 1 each).",
        "",
        "## Scores",
        "",
        "| Doc | path applies | data lines | heuristic score | old score | delta | "
        "rows pred/truth | checks passed | filled | rank | hard fail | valid |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        o = r["old"]
        lines.append(
            f"| {r['doc']} | {r['applies']} ({r['why']}) | {r['data_lines']} | "
            f"{r.get('score', 0):.4f} | {o['score']:.4f} | {r.get('score', 0) - o['score']:+.4f} | "
            f"{r.get('rows', '-')}/{r.get('rows_truth', '-')} | {r.get('spec_score', '-')} | "
            f"{r.get('filled', 0):.4f} | {r.get('rank', 0):.4f} | "
            f"{r.get('hard_fail', '-')} | {r.get('result_valid', r.get('valid'))} |"
        )
    lines += [
        "",
        "## Checks",
        "",
        "| Doc | check | passed | value | detail |",
        "|---|---|---|---|---|",
    ]
    for r in recs:
        for k, c in (r.get("checks") or {}).items():
            det = ", ".join(f"{a}={b}" for a, b in c.items() if a not in ("passed", "value"))
            lines.append(f"| {r['doc']} | {k} | {c['passed']} | {c['value']} | {det} |")
    lines += ["", "## Lines by disposition", ""]
    for r in recs:
        lines.append(
            f"- {r['doc']}: key column {r.get('key_column')}, header row found "
            f"{r.get('header_row_found')}, duplicates {r.get('duplicates')}; "
            + ", ".join(f"{k} {v}" for k, v in (r.get("lines") or {}).items())
        )
    lines += [
        "",
        "## Per-field scores (field names only)",
        "",
        "| Doc | field | heuristic source | heuristic | old |",
        "|---|---|---|---|---|",
    ]
    for r in recs:
        old_pf = r["old"].get("per_field", {})
        for k in sorted(old_pf):
            lines.append(
                f"| {r['doc']} | {k} | {(r.get('sources') or {}).get(k, '-')} | "
                f"{(r.get('per_field') or {}).get(k, 0.0):.2f} | {old_pf[k]:.2f} |"
            )
    lines += [
        "",
        "## T-16b ship-rule targets (old scores re-scored from shipped outputs by this script)",
        "",
        f"- rentroll_001: old {olds['rentroll_001']:.4f} -> 3-run mean must be >= "
        f"{olds['rentroll_001'] - NO_REGRESSION:.4f} (no regression)",
        f"- t12_001: old {olds['t12_001']:.4f} -> 3-run mean must be >= "
        f"{olds['t12_001'] - NO_REGRESSION:.4f} (no regression)",
        f"- mean of the two gains >= +{MEAN_GAIN:.2f}, i.e. (rentroll mean + t12 mean) >= "
        f"{olds['rentroll_001'] + olds['t12_001'] + 2 * MEAN_GAIN:.4f}",
        f"- boxscore_001: old {olds['boxscore_001']:.4f} -> must stay >= "
        f"{olds['boxscore_001'] - BOX_DROP:.4f}",
    ]
    free = [r for r in recs if r["doc"] in ("rentroll_001", "t12_001") and "score" in r]
    if len(free) == 2:
        gains = [r["score"] - r["old"]["score"] for r in free]
        lines.append(
            f"- free gate (heuristic only, n = 1) against T-16b: gains "
            f"{gains[0]:+.4f} / {gains[1]:+.4f}, mean {sum(gains) / 2:+.4f}"
        )
    text = "\n".join(lines) + "\n"
    print(text)
    if args.report:
        report = args.report if args.report.is_absolute() else ROOT / args.report
        report.write_text(text, encoding="utf-8", newline="\n")
        print(f"written: {report.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
