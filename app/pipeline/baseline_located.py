"""Baseline single-value path with locate-then-read page choice for scans (P8b Z-13).

SCAN_PAGE_METHOD=locate. When a document has more page images than the baseline can send
(MAX_IMAGES), the P5 locate step (single_value._locate: page thumbnails -> pages per field,
clamped to the real pages, most-named pages first) picks at most MAX_IMAGES pages, and
today's baseline prompt reads those pages in page order. No quote checker, no smart path.
Locate failure (no usable answer, a stop, or an error) -> the first pages, as before.
Documents that fit (<= MAX_IMAGES images) go to the baseline unchanged, with no extra call.
Metadata `scan_pages`: method, result, page counts, locate calls (never document text, R23).
"""

from __future__ import annotations

import logging
from typing import Any

from app.llm import CallContext, LLMClient
from app.pipeline import baseline, single_value
from app.readers import Block

log = logging.getLogger("app.pipeline.baseline_located")

PIPELINE = baseline.PIPELINE
MAX_IMAGES = baseline.MAX_IMAGES


def pick_pages(
    llm: LLMClient,
    ctx: CallContext,
    model: str,
    field_list: dict[str, Any],
    blocks: list[Block],
) -> tuple[list[Block], dict[str, Any]]:
    """(blocks for the baseline, scan_pages metadata). Text blocks are always kept."""
    images = [b for b in blocks if b.kind == "image"]
    info: dict[str, Any] = {"method": "locate", "image_pages": len(images), "locate_calls": 0}
    if len(images) <= MAX_IMAGES:
        info["result"] = "all_pages_fit"
        return blocks, info
    notes: dict[str, Any] = {"calls": {"locate": 0}}
    try:
        chosen, stop = single_value._locate(llm, ctx, model, field_list, images, notes)
    except Exception as exc:  # surfaced (type + code location, no text, R23), then first pages
        tb = exc.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
        where = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb else "?"
        log.error("job %s locate error %s at %s", ctx.job_id, type(exc).__name__, where)
        info.update(result="fallback_first", reason="error", error=type(exc).__name__)
        info["locate_calls"] = notes["calls"]["locate"]
        return blocks, info
    info["locate_calls"] = notes["calls"]["locate"]
    if stop or not chosen:
        info.update(result="fallback_first", reason=stop or "no_pages")
        return blocks, info
    keep = set(chosen)
    info.update(result="located", pages_chosen=chosen)
    return [b for b in blocks if b.kind != "image" or b.page in keep], info


def extract(
    llm: LLMClient,
    ctx: CallContext,
    field_list: dict[str, Any],
    blocks: list[Block],
    file_type: str,
    model: str | None = None,
) -> baseline.BaselineOutcome:
    model = model or llm.catalog.baseline
    picked, info = pick_pages(llm, ctx, model, field_list, blocks)
    out = baseline.extract(llm, ctx, field_list, picked, file_type, model)
    out.notes["scan_pages"] = info
    return out


def plan_pages(blocks: list[Block]) -> dict[str, Any]:
    """Dry run: whether the locate step would run (no call; the chosen pages are unknown)."""
    images = sum(1 for b in blocks if b.kind == "image")
    return {"image_pages": images, "locate": images > MAX_IMAGES}
