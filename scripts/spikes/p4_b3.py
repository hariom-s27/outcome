"""B3 noise floor (P4-10, PR-69, R-E): the shipped baseline, unchanged, N repeats per DEV doc
with the dev cache bypassed, so repeats are real calls. p4_score.py prints mean / min / max /
spread per doc.

    uv run python scripts/spikes/p4_b3.py --dry-run --max-usd 0.05
    uv run python scripts/spikes/p4_launch.py b3 --max-usd 0.05 --no-cache
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p4_common as pc  # noqa: E402

DOCS = ("om_001", "lease_002", "rentroll_001")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pc.common_args(ap)
    ap.add_argument("--docs", nargs="+", default=list(DOCS))
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    if not args.dry_run and not args.no_cache:
        ap.error("B3 needs --no-cache: cached repeats would measure nothing")
    s = pc.open_session("b3", args)
    for doc_id in args.docs:
        doc = s.load(doc_id)
        for r in range(1, args.repeats + 1):
            print(s.baseline_variant(doc, f"b3-r{r}"))
            if s.rec.budget.stop:
                break
        if s.rec.budget.stop:
            break
    pc.print_summary(s.close("b3", {"docs": args.docs, "repeats": args.repeats}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
