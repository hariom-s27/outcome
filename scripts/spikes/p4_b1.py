"""B1 vision bake-off (P4-08): one scanned DEV lease, all pages, batches of <= 8 page images
per call, the lease field list, the baseline prompt per batch; batch answers merged by code
(p4_common.merge_batches). Five cheap vision models, each with its reasoning setting from
config/models.yaml; reasoning tokens actually billed are recorded per call.

    uv run python scripts/spikes/p4_b1.py --dry-run --max-usd 0.10        # free, host
    uv run python scripts/spikes/p4_launch.py b1 --max-usd 0.01 -- \\
        --models anthropic/claude-haiku-5.5 --max-batches 1               # pilot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p4_common as pc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pc.common_args(ap)
    ap.add_argument("--doc", default="lease_001")
    ap.add_argument("--models", nargs="+", default=list(pc.B1_MODELS))
    ap.add_argument("--batch-size", type=int, default=pc.MAX_IMAGES)
    ap.add_argument("--max-batches", type=int, help="pilot: only the first N batches")
    args = ap.parse_args()
    if args.batch_size > pc.MAX_IMAGES:
        ap.error(f"--batch-size must be <= {pc.MAX_IMAGES} (R13)")
    s = pc.open_session("b1", args)
    doc = s.load(args.doc)
    fields = doc.field_list["fields"]
    batches = pc.page_batches(doc.blocks, args.batch_size)[: args.max_batches]
    print(
        f"{doc.doc_id}: blocks={len(doc.blocks)} pages={len({b.page for b in doc.blocks})} "
        f"batches={len(batches)} fields={len(fields)} models={len(args.models)}"
    )
    for model in args.models:
        variant = "b1-" + model.split("/", 1)[1]
        s.caller.variant = variant
        results = []
        for batch in batches:
            entries = pc.extract_call(s.caller, model, doc.field_list, batch, doc.file_type)
            results.append((entries, pc.batch_pages(batch)))
            if s.rec.budget.stop:
                break
        ok = sum(1 for e, _ in results if e)
        merged, conflicts = pc.merge_batches(results, fields) if ok else (None, [])
        extra = {
            "batches": len(batches),
            "batches_ok": ok,
            "conflicts": len(conflicts),
            "conflict_fields": conflicts,
            "pages_sent": sorted(p for _, ps in results for p in ps),
        }
        print(s.write(doc.doc_id, variant, merged, extra))
        if s.rec.budget.stop:
            break
    pc.print_summary(s.close("b1", {"doc": doc.doc_id, "batches": len(batches)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
