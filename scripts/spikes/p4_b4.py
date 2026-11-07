"""B4 one call vs grouped (P4-11) on Haiku: (1) the shipped baseline, all fields in one call;
(2) the same fields split into 3 groups in field-list order (row key in every group), 3 calls
over the same document blocks, merged by code. p4_score.py reports score; this prints $,
latency and calls.

    uv run python scripts/spikes/p4_b4.py --dry-run --max-usd 0.02
    uv run python scripts/spikes/p4_launch.py b4 --max-usd 0.02 --no-cache
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p4_common as pc  # noqa: E402

DOCS = ("lease_002", "om_001")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pc.common_args(ap)
    ap.add_argument("--docs", nargs="+", default=list(DOCS))
    ap.add_argument("--groups", type=int, default=3)
    args = ap.parse_args()
    s = pc.open_session("b4", args)
    for doc_id in args.docs:
        doc = s.load(doc_id)
        print(s.baseline_variant(doc, "b4-one"))
        if s.rec.budget.stop:
            break
        s.caller.variant = "b4-grouped"
        parts = pc.split_fields(doc.field_list, args.groups)
        got = [pc.extract_call(s.caller, pc.HAIKU, p, doc.blocks, doc.file_type) for p in parts]
        merged = pc.merge_groups(got, doc.field_list["fields"])
        extra = {"groups": len(parts), "groups_ok": sum(1 for g in got if g)}
        print(s.write(doc.doc_id, "b4-grouped", merged, extra))
        if s.rec.budget.stop:
            break
    pc.print_summary(s.close("b4", {"docs": args.docs, "groups": args.groups}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
