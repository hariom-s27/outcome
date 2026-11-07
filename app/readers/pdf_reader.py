"""PDF -> blocks per page (P3-14, CD82), page triage (P3-15), scans as images (P3-16, R13).

Per page, one page at a time, every pdfium object closed after the page:
  1. triage with pypdfium2: non-space text chars and the page share covered by images.
     chars < 50 and images > 50%  -> scan: one grayscale JPEG, long side ~1600 px (image block)
     images > 30% with text        -> mixed: text blocks flagged image_text_risk
  2. text pages: pdfplumber words (box, font, size, colour) -> lines -> blocks.
     - doubled "fake bold" characters deduplicated (dedupe_chars)
     - number spans split into several words are joined ("1," + "250.00")
     - words inside a vector rectangle that holds 2+ lines stay together: one callout block
     - lines in the top / bottom 7% of the page are tagged header / footer (not dropped)
     - wide gaps inside a line become " | " (columns / table cells)
  3. a layout failure or the parse time budget falls back to the pypdfium2 page text
     (flag layout_failed / layout_skipped); the job never dies on one bad page (R20).

Runs inside the worker process (the P2 render path); nothing leaves it but text and JPEG
bytes for the prompt. No document text in logs or errors (R23).
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.readers.base import Block, DocMap, ReaderError, number_blocks

SCAN_MAX_CHARS = 50  # P3-15
SCAN_MIN_IMAGE_SHARE = 0.5
MIXED_MIN_IMAGE_SHARE = 0.3
IMAGE_LONG_SIDE = 1600
JPEG_QUALITY = 80
HEADER_ZONE = 0.07
PARSE_BUDGET_S = 90.0  # whole-document layout budget; later pages fall back to plain text
MIN_BOX_W, MIN_BOX_H = 20.0, 10.0

NUM_TAIL = re.compile(r"[\d,.$€£(-]$")
NUM_HEAD = re.compile(r"^[\d,.)%]")
CURRENCY = {"$", "€", "£", "₹"}


# --- triage + render (pypdfium2) -----------------------------------------------------------------


def _image_share(page, pdfium_c) -> float:
    w, h = page.get_size()
    area = max(w * h, 1.0)
    covered = 0.0
    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
        left, bottom, right, top = obj.get_bounds()
        cw = max(0.0, min(right, w) - max(left, 0.0))
        ch = max(0.0, min(top, h) - max(bottom, 0.0))
        covered += cw * ch
    return min(1.0, covered / area)


def _render_jpeg(page) -> tuple[bytes, int, int]:
    w_pt, h_pt = page.get_size()
    scale = IMAGE_LONG_SIDE / max(w_pt, h_pt, 1.0)
    bitmap = page.render(scale=scale, grayscale=True)
    try:
        img = bitmap.to_pil()
        if img.mode not in ("L", "RGB"):
            img = img.convert("L")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue(), img.width, img.height
    finally:
        bitmap.close()


def _plain_blocks(text: str, n: int, flags: tuple[str, ...]) -> list[Block]:
    clean = "\n".join(" ".join(line.split()) for line in text.splitlines())
    clean = "\n".join(line for line in clean.splitlines() if line)
    return [Block("paragraph", f"Page {n}", clean, page=n, flags=flags)] if clean else []


# --- block model (pdfplumber) --------------------------------------------------------------------


@dataclass
class _Line:
    words: list[dict[str, Any]]
    top: float
    bottom: float
    x0: float
    size: float
    zone: str = "body"
    text: str = ""


@dataclass
class _Group:
    box: tuple[float, float, float, float] | None
    words: list[dict[str, Any]] = field(default_factory=list)


def _contains(box: tuple[float, float, float, float], w: dict[str, Any]) -> bool:
    x0, top, x1, bottom = box
    return (
        w["x0"] >= x0 - 1
        and w["x1"] <= x1 + 1
        and w["top"] >= top - 1
        and w["bottom"] <= bottom + 1
    )


def _boxes(ppage) -> list[tuple[float, float, float, float]]:
    page_area = ppage.width * ppage.height
    out = []
    for r in ppage.rects:
        w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if w >= MIN_BOX_W and h >= MIN_BOX_H and w * h < 0.8 * page_area:
            out.append((r["x0"], r["top"], r["x1"], r["bottom"]))
    return sorted(set(out), key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))


def _lines(words: list[dict[str, Any]]) -> list[_Line]:
    lines: list[_Line] = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        h = max(w["bottom"] - w["top"], 1.0)
        if lines:
            cur = lines[-1]
            overlap = min(cur.bottom, w["bottom"]) - max(cur.top, w["top"])
            if overlap >= 0.5 * min(h, cur.bottom - cur.top):
                cur.words.append(w)
                cur.top, cur.bottom = min(cur.top, w["top"]), max(cur.bottom, w["bottom"])
                continue
        lines.append(_Line([w], w["top"], w["bottom"], w["x0"], float(w.get("size") or h)))
    for ln in lines:
        ln.words.sort(key=lambda w: w["x0"])
        ln.x0 = ln.words[0]["x0"]
        ln.size = max(float(w.get("size") or 0) for w in ln.words) or (ln.bottom - ln.top)
        ln.text = _join_words(ln.words)
    return lines


def _join_words(words: list[dict[str, Any]]) -> str:
    out = ""
    prev = None
    for w in words:
        t = w["text"]
        if prev is None:
            out = t
        else:
            size = float(w.get("size") or 10.0)
            gap = w["x0"] - prev["x1"]
            if gap > max(1.5 * size, 12.0):
                out += " | " + t
            elif (NUM_TAIL.search(prev["text"]) and NUM_HEAD.match(t) and gap < 0.2 * size) or (
                prev["text"] in CURRENCY and t[:1].isdigit() and gap < 0.6 * size
            ):
                out += t  # one number split into spans
            else:
                out += " " + t
        prev = w
    return out


def _white(word: dict[str, Any]) -> bool:
    c = word.get("non_stroking_color")
    if isinstance(c, list | tuple) and c and all(isinstance(v, int | float) for v in c):
        return (len(c) in (1, 3) and min(c) >= 0.98) or (len(c) == 4 and max(c) <= 0.02)
    return False


def _group_words(words: list[dict[str, Any]], boxes: list) -> list[_Group]:
    """Words -> groups by the smallest rectangle around them; a rectangle holding < 2 lines
    is not a callout (table cell, highlight) and gives its words to the next bigger one."""
    live = list(boxes)
    for _ in range(6):
        groups: dict[Any, _Group] = {}
        for w in words:
            box = next((b for b in live if _contains(b, w)), None)
            groups.setdefault(box, _Group(box)).words.append(w)
        weak = {b for b, g in groups.items() if b is not None and len(_lines(g.words)) < 2}
        if not weak:
            return list(groups.values())
        live = [b for b in live if b not in weak]
    return [_Group(None, words)]


def _layout_blocks(ppage, n: int, page_flags: tuple[str, ...]) -> list[Block]:
    ppage = ppage.dedupe_chars(tolerance=1)
    words = ppage.extract_words(
        x_tolerance=1.5, y_tolerance=2, extra_attrs=["fontname", "size", "non_stroking_color"]
    )
    if not words:
        return []
    height = float(ppage.height) or 1.0
    pieces: list[tuple[float, float, Block]] = []
    for g in _group_words(words, _boxes(ppage)):
        lines = _lines(g.words)
        for ln in lines:
            if ln.bottom <= HEADER_ZONE * height:
                ln.zone = "header"
            elif ln.top >= (1 - HEADER_ZONE) * height:
                ln.zone = "footer"
        chunks: list[list[_Line]] = []
        for ln in lines:
            if chunks and g.box is not None:
                chunks[-1].append(ln)  # a callout stays whole
                continue
            if chunks:
                last = chunks[-1][-1]
                gap = ln.top - last.bottom
                same_size = abs(ln.size - last.size) <= 0.2 * max(ln.size, last.size, 1.0)
                if ln.zone == last.zone and gap <= 0.8 * max(last.size, 1.0) and same_size:
                    chunks[-1].append(ln)
                    continue
            chunks.append([ln])
        for chunk in chunks:
            flags = list(page_flags)
            zone = chunk[0].zone
            if zone != "body":
                flags.append(zone)
            if all(_white(w) for ln in chunk for w in ln.words):
                flags.append("invisible_text")
            kind = "callout" if g.box is not None else "paragraph"
            text = "\n".join(ln.text for ln in chunk)
            block = Block(kind, f"Page {n}", text, page=n, flags=tuple(flags))
            pieces.append((chunk[0].top, min(ln.x0 for ln in chunk), block))
    pieces.sort(key=lambda p: (round(p[0]), p[1]))
    return [b for _, _, b in pieces]


# --- reader --------------------------------------------------------------------------------------


def read_pdf(content: bytes) -> DocMap:
    import pdfplumber
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    try:
        pdf = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as exc:
        raise ReaderError(f"pdf reader: {type(exc).__name__}") from exc
    counts = {"pages": 0, "scan_pages": 0, "mixed_pages": 0, "empty_pages": 0}
    counts |= {"layout_failed": 0, "layout_skipped": 0}
    blocks: list[Block] = []
    deadline = time.monotonic() + PARSE_BUDGET_S
    plumber = None
    try:
        try:
            plumber = pdfplumber.open(io.BytesIO(content))
        except Exception as exc:  # pdfminer raises many types; recorded, page text still read
            counts["layout_failed_open"] = type(exc).__name__
        for i in range(len(pdf)):
            n = i + 1
            counts["pages"] += 1
            page = pdf[i]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded() or ""
                finally:
                    textpage.close()
                chars = len("".join(text.split()))
                share = _image_share(page, pdfium_c)
                if chars < SCAN_MAX_CHARS and share > SCAN_MIN_IMAGE_SHARE:
                    jpeg, w, h = _render_jpeg(page)
                    blocks.append(Block("image", f"Page {n}", page=n, jpeg=jpeg, width=w, height=h))
                    counts["scan_pages"] += 1
                    continue
                flags: tuple[str, ...] = ()
                if share > MIXED_MIN_IMAGE_SHARE:
                    flags = ("image_text_risk",)
                    counts["mixed_pages"] += 1
                page_blocks = _page_layout(plumber, i, n, flags, deadline, counts)
                if page_blocks is None:
                    page_blocks = _plain_blocks(text, n, (*flags, "layout_fallback"))
                if not page_blocks:
                    counts["empty_pages"] += 1
                blocks.extend(page_blocks)
            finally:
                page.close()
    finally:
        if plumber is not None:
            plumber.close()
        pdf.close()
    return DocMap("pdf", number_blocks("P", blocks), counts)


def _page_layout(
    plumber, i: int, n: int, flags: tuple[str, ...], deadline: float, counts: dict[str, Any]
) -> list[Block] | None:
    """Block-model blocks for one page; None = use the plain pdfium text (flagged)."""
    if plumber is None:
        return None
    if time.monotonic() > deadline:
        counts["layout_skipped"] += 1
        return None
    ppage = plumber.pages[i]
    try:
        return _layout_blocks(ppage, n, flags)
    except Exception as exc:  # one bad page must not kill the job (R20); counted, not hidden
        counts["layout_failed"] += 1
        counts.setdefault("layout_errors", []).append(type(exc).__name__)
        return None
    finally:
        ppage.close()
