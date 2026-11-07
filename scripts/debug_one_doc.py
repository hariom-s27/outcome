"""Debug one DEV document through the real reader + baseline path (P3, om_001 diagnosis).

Runs INSIDE the dev worker container (real DB ledger, env from compose; nothing printed from
it). Same code path as the worker: read_document -> baseline.extract with LLMClient.from_env.
The client's chat/complete_json are wrapped only to record what happened.

    docker compose -f compose.yaml -f compose.dev.yaml run --rm -e LLM_CACHE_DIR= \
        -e LLM_MAX_USD_PER_DOC=0.01 -v "${PWD}/scripts:/srv/scripts:ro" \
        -v "${PWD}/sample/sample-data-documents:/srv/devdocs:ro" \
        -v "${PWD}/sample/schemas:/srv/schemas:ro" worker \
        python scripts/debug_one_doc.py --doc /srv/devdocs/om_001.pdf \
        --schema /srv/schemas/offering_memorandum.json

Raw model text, parsed JSON and the prompt go to /cache/debug/<doc>/ (the dev overlay's
mount of the git-ignored cache folder). Printed: block counts, estimated vs real tokens,
finish_reason, parse ok, repair tried, contract errors (field names + error kind, quoted
parts masked), images sent. No document text, no values (R23, D04).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.contract_check import contract_errors  # noqa: E402
from app.llm import CallContext, LLMClient  # noqa: E402
from app.pipeline import baseline  # noqa: E402
from app.readers import read_document  # noqa: E402

HELD_OUT = ("lease_003", "budget_001")  # D03
OUT_ROOT = Path("/cache") / "debug"


def mask(err: str) -> str:
    """Contract error -> field names and error kind only (quoted parts masked)."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", "<v>", err)[:160]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doc", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    args = ap.parse_args()
    if any(h in args.doc.name for h in HELD_OUT):
        print("refused: held-out document (D03)")
        return 2
    out_dir = OUT_ROOT / args.doc.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    field_list = json.loads(args.schema.read_text(encoding="utf-8"))
    file_type = args.doc.suffix.lower().lstrip(".")

    dm = read_document(file_type, args.doc.read_bytes())
    kinds = Counter(b.kind for b in dm.blocks)
    flags = Counter(f.split("=", 1)[0] for b in dm.blocks for f in b.flags)
    print(f"blocks={len(dm.blocks)} kinds={dict(kinds)} flags={dict(flags)}")

    llm = LLMClient.from_env(Settings.from_env().database_url)
    calls: list[dict] = []
    outcomes: list = []
    orig_chat, orig_json = llm.chat, llm.complete_json

    def chat(ctx, model, messages, **kw):
        res = orig_chat(ctx, model, messages, **kw)
        n = len(calls) + 1
        (out_dir / f"call{n}_{ctx.purpose}.txt").write_text(res.text or "", encoding="utf-8")
        (out_dir / f"call{n}_{ctx.purpose}_prompt.json").write_text(
            json.dumps(messages, ensure_ascii=False)[:2_000_000], encoding="utf-8"
        )
        calls.append(
            {
                "purpose": ctx.purpose,
                "finish_reason": res.finish_reason,
                "tokens_in": res.usage.get("prompt_tokens"),
                "tokens_out": res.usage.get("completion_tokens"),
                "max_tokens": kw.get("max_tokens"),
                "est": llm.catalog.estimate.tokens(messages, kw.get("kind_chars")),
                "cache_hit": res.cache_hit,
            }
        )
        return res

    def complete_json(ctx, model, messages, **kw):
        out = orig_json(ctx, model, messages, **kw)
        outcomes.append(out)
        return out

    llm.chat, llm.complete_json = chat, complete_json
    ctx = CallContext(job_id=str(uuid.uuid4()), deadline=time.time() + 600)
    try:
        res = baseline.extract(llm, ctx, field_list, dm.blocks, file_type)
    finally:
        llm.close()

    for i, c in enumerate(calls, 1):
        print(
            f"call{i} purpose={c['purpose']} finish_reason={c['finish_reason']} "
            f"tokens_in real={c['tokens_in']} est={c['est']} tokens_out={c['tokens_out']} "
            f"max_tokens={c['max_tokens']} cache_hit={c['cache_hit']}"
        )
    keep = ("images_sent", "blocks_sent", "truncated", "tokens_estimated", "json_repaired")
    notes = {k: v for k, v in res.notes.items() if k in keep or k.endswith("_dropped")}
    print(f"notes={notes} contract_errors_count={res.notes.get('contract_errors', 0)}")
    out = outcomes[0] if outcomes else None
    print(
        f"outcome status={getattr(out, 'status', None)} reason={getattr(out, 'reason', None)} "
        f"parse_ok={bool(out and out.status == 'ok')} "
        f"repair_tried={any(c['purpose'] == 'repair' for c in calls)} "
        f"repaired={getattr(out, 'repaired', False)} final_reason={res.reason}"
    )
    if out is not None and out.data is not None:
        (out_dir / "parsed.json").write_text(json.dumps(out.data, indent=1), encoding="utf-8")
        entries, checks = baseline.check_answer(out.data, field_list)
        print(f"check_answer entries={len(entries or [])} checks={checks}")
        if entries:
            meta = {"model_calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
            errs = contract_errors(
                {"entries": entries, "metadata": meta | {"latency_ms": 0}}, field_list
            )
            for e in errs[:12]:
                print(f"contract_error {mask(e)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
