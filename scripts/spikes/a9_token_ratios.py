"""A9 (PR-06): characters per real input token, per DEV doc and per block kind. No LLM call.

Rebuilds the P2 baseline prompt with the P2 readers (build_messages, same field list), counts
characters by block kind (sheet rows = XLSX/CSV rows; prose = DOCX/PDF text; other = system
prompt, field list, headings, separators) and reads tokens_in from the saved P2 run.
Docs with image blocks or more than one model call are flagged and left out of the per-kind
ratios (their tokens include images or repairs).
"""

from __future__ import annotations

import json

from _common import RUNS, Report, dev_docs, dev_row, doc_path, last_run_id, schema

from app.pipeline.baseline import build_messages
from app.readers import read_document


def text_chars(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            n += len(c)
        else:
            n += sum(len(p.get("text", "")) for p in c if p.get("type") == "text")
    return n


def main() -> None:
    rid = last_run_id()
    rep = Report("a9_token_ratios")
    pools: dict[str, list[tuple[int, int]]] = {"sheet": [], "prose": []}
    for d in dev_docs():
        ftype = dev_row(d)["file"].rsplit(".", 1)[-1].lower()
        blocks = read_document(ftype, doc_path(d).read_bytes())
        messages, notes = build_messages(schema(d), blocks, ftype)
        # select_blocks keeps text blocks in order until the cap: the first blocks_sent text
        # blocks are exactly what was sent when the doc has no image blocks
        kind = "sheet" if ftype in ("xlsx", "csv") else "prose"
        body = sum(len(b.render()) + 1 for b in blocks[: notes["blocks_sent"]] if b.kind == "text")
        total = text_chars(messages)
        other = total - body
        images = notes["images_sent"]
        job = json.loads((RUNS / rid / f"{d}.json").read_text(encoding="utf-8"))
        meta = (job.get("result") or {}).get("metadata") or {}
        tin, calls = int(meta.get("tokens_in", 0)), int(meta.get("model_calls", 0))
        flag = []
        if images:
            flag.append(f"images={images}")
        if calls != 1:
            flag.append(f"calls={calls}")
        if notes["truncated"]:
            flag.append("truncated")
        ratio = total / tin if tin else 0.0
        rep.sum(
            f"{d}: chars {kind}={body} other={other} total={total} tokens_in={tin} "
            f"chars/token={ratio:.2f} est_P2={notes['input_tokens_est']} "
            f"{' '.join(flag) or 'clean'}"
        )
        if not images and calls == 1 and tin:  # truncation alone keeps the count exact
            pools[kind].append((total, tin))
    for kind, rows in pools.items():
        if rows:
            c, t = sum(r[0] for r in rows), sum(r[1] for r in rows)
            rep.sum(f"per kind {kind}: chars/token={c / t:.2f} over {len(rows)} clean doc(s)")
        else:
            rep.sum(f"per kind {kind}: no clean doc")
    rep.close()


if __name__ == "__main__":
    main()
