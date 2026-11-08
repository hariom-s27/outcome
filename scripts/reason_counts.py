"""Counts-only diagnosis (P5b F-11): reason code x field value type, per document, from the raw
jobs eval_dev.py saved. Prints doc ids, reason codes, type buckets and counts; never a value, a
quote or a field key (D04, R31). Held-out documents are skipped.

    uv run python scripts/reason_counts.py                     # list saved run folders
    uv run python scripts/reason_counts.py --run <run_id>[/run<n>] [--docs d1 d2]

Type buckets: date (date/month/year), number, integer, percent, boolean, list, text
(text/free_text/code), computed (a field the compiler marked as a computed candidate).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_dev import HELD_OUT, RUNS  # noqa: E402
from make_outputs import SCHEMAS, manifest  # noqa: E402

from app.extract.compile_fields import FieldSpec, compile_fields  # noqa: E402

BUCKETS = ("date", "number", "integer", "percent", "boolean", "list", "text", "computed")


def bucket(spec: FieldSpec) -> str:
    if spec.computed:
        return "computed"
    t = spec.type
    if t in ("date", "month", "year"):
        return "date"
    if t in ("number", "integer", "percent", "boolean", "list"):
        return t
    return "text"


def counts_for(job: dict[str, Any], field_list: dict[str, Any]) -> dict[str, Any]:
    """{reason: Counter(bucket)} plus loc-shape counts, from metadata.extraction only."""
    meta = ((job.get("result") or {}).get("metadata")) or {}
    ext = meta.get("extraction") if isinstance(meta.get("extraction"), dict) else {}
    specs = compile_fields(field_list)
    table: dict[str, Counter] = {}
    for key, info in (ext.get("fields") or {}).items():
        spec = specs.get(key)
        if spec is None or not isinstance(info, dict):
            continue
        table.setdefault(str(info.get("reason")), Counter())[bucket(spec)] += 1
    return {
        "mode": ext.get("mode", "?"),
        "path": ext.get("path", "baseline"),
        "fallback": ext.get("fallback", "-"),
        "table": table,
        "loc_shapes": dict(ext.get("loc_shapes") or {}),
    }


def render(doc: str, c: dict[str, Any]) -> list[str]:
    lines = [
        f"### {doc} (path {c['path']}, mode {c['mode']}, fallback {c['fallback']})",
        "",
        "| reason | " + " | ".join(BUCKETS) + " | total |",
        "|---|" + "---|" * (len(BUCKETS) + 1),
    ]
    for reason in sorted(c["table"], key=lambda r: -sum(c["table"][r].values())):
        row = c["table"][reason]
        cells = " | ".join(str(row.get(b, 0) or "") for b in BUCKETS)
        lines.append(f"| {reason} | {cells} | {sum(row.values())} |")
    if c["loc_shapes"]:
        shapes = ", ".join(f"`{k}` {v}" for k, v in sorted(c["loc_shapes"].items()))
        lines += ["", f"loc shapes: {shapes}"]
    return lines + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", help="run folder under the eval raw folder: <run_id>[/run<n>]")
    ap.add_argument("--docs", nargs="+", help="doc ids (default: every saved doc)")
    args = ap.parse_args()
    if not args.run:
        for p in sorted(RUNS.glob("*")):
            subs = sorted(s.name for s in p.iterdir() if s.is_dir()) if p.is_dir() else []
            n = len(list(p.glob("*.json"))) if p.is_dir() else 0
            print(f"{p.name}: {n} docs" + (f", runs {', '.join(subs)}" if subs else ""))
        return 0
    run_dir = RUNS / args.run
    rows = manifest()
    docs = args.docs or sorted(p.stem for p in run_dir.glob("*.json"))
    for doc in docs:
        if doc in HELD_OUT or doc not in rows:
            continue  # sealed or unknown: never opened
        raw = run_dir / f"{doc}.json"
        if not raw.exists():
            print(f"### {doc}: no raw job\n")
            continue
        job = json.loads(raw.read_text(encoding="utf-8"))
        fl = json.loads((SCHEMAS / f"{rows[doc]['schema_name']}.json").read_text(encoding="utf-8"))
        print("\n".join(render(doc, counts_for(job, fl))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
