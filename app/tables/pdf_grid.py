"""PDF table -> line grid -> virtual sheet (P9c Z-42, Z-44), for PDF_TABLE_METHOD=grid.

A text-layer PDF table becomes the same `row` blocks the XLSX reader emits ("[Table!C14]
C14=..."), so the spreadsheet spec path (app.pipeline.table_spec) runs on it unchanged: the
model names the columns once, code copies every row. Rows, citations and page numbers come
from code.

Rules (general, structural; no document's labels, keys or values):
1. words (pdfplumber, the reader's settings) -> physical lines by vertical overlap; every line
   gets an id P<page>L<nnn>.
2. segments: words of a line split where the gap is wider than SEG_GAP_EM x font size.
3. table header: the multi-segment, mostly-text line with the most text segments that have
   numbers under them (earliest page wins near-ties); a text-only line touching it from above
   (or below) is merged into it (two-row headers). A later line similar to it is a repeated
   header (skipped).
4. lines in the top / bottom margin whose digit-masked text repeats on 2+ pages, or that hold
   "Page N", are page header / footer lines (skipped). On later pages, lines above the
   repeated header are skipped too. The first table page's lines above the header are kept
   (header block, for document-level fields).
5. column bands: the x-ranges between whitespace rivers of the header and the multi-segment
   body lines outside the margins; a river tolerates RIVER_TOL of those lines crossing it
   (at least one from RIVER_MIN_LINES lines). Each word goes to the band it overlaps most
   (else the nearest).
6. continuation: a body line with an empty first band, no number, and text only in bands the
   previous line also fills -> its text joins the previous line (wrapped comments / names).
7. numbers stay as printed; the spec path's normaliser reads "(1,234)" as -1234 and N/A, dashes
   and blanks as null (existing rules).

Nothing here logs or raises with document text (R23).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from app.readers.base import Block, row_block
from app.readers.pdf_reader import HEADER_ZONE, _join_words, _lines
from app.tables.profile import cell_kind

SHEET = "Table"
SEG_GAP_EM = 0.6  # a word gap wider than this x font size starts a new segment
HEADER_MIN_SEGMENTS = 3
HEADER_NEAR_TIE = 0.8  # an earlier page's header candidate wins at >= 0.8 x the best score
HEADER_SIMILAR = 0.7  # a repeated header shares >= 70% of the header's segment texts
HEADER_BELOW = 15  # lines below a header candidate that are checked for numbers
RIVER_TOL = 0.02  # a river may be crossed by this share of the band lines
RESOLUTION = 2  # histogram bins per point
MIN_BANDS = 2
_PAGE_WORD = re.compile(r"\bpage\s+\d+(\s+of\s+\d+)?\b", re.IGNORECASE)
RIVER_MIN_LINES = 10  # with this many band lines a river tolerates at least one crossing
_REF = re.compile(rf"{SHEET}!([A-Z]{{1,3}})(\d+)")


@dataclass
class Seg:
    x0: float
    x1: float
    text: str


@dataclass
class GLine:
    page: int
    idx: int  # 1-based line number on its page
    top: float
    bottom: float
    zone: str  # header | footer | body (top / bottom margin, HEADER_ZONE)
    words: list[dict[str, Any]]
    segs: list[Seg]
    text: str

    @property
    def line_id(self) -> str:
        return f"P{self.page}L{self.idx:03d}"

    def numeric_segs(self) -> int:
        return sum(1 for s in self.segs if cell_kind(s.text) == "number")


@dataclass
class Grid:
    """The virtual sheet: `blocks` feed app.tables.profile.profile_blocks unchanged."""

    blocks: list[Block]
    row_page: dict[int, int]  # virtual row -> page
    row_line: dict[int, str]  # virtual row -> line id (P2L014)
    header_row: int
    body_rows: list[int]
    stats: dict[str, Any] = field(default_factory=dict)  # counts only


@dataclass
class GridResult:
    grid: Grid | None
    reason: str  # "ok" or why no grid was built
    stats: dict[str, Any] = field(default_factory=dict)


# --- words -> lines -> segments ------------------------------------------------------------------


def _segments(words: list[dict[str, Any]]) -> list[Seg]:
    out: list[list[dict[str, Any]]] = []
    for w in words:
        if out:
            prev = out[-1][-1]
            size = float(w.get("size") or prev.get("size") or 10.0)
            if w["x0"] - prev["x1"] <= SEG_GAP_EM * size:
                out[-1].append(w)
                continue
        out.append([w])
    return [Seg(g[0]["x0"], g[-1]["x1"], _text(g)) for g in out]


def _text(words: list[dict[str, Any]]) -> str:
    """Words of one cell as text: the reader's join (number spans glued), no ' | ' inside."""
    return _join_words(words).replace(" | ", " ")


def page_lines(ppage, page: int) -> list[GLine]:
    ppage = ppage.dedupe_chars(tolerance=1)
    words = ppage.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["size"])
    height = float(ppage.height) or 1.0
    out: list[GLine] = []
    for i, ln in enumerate(_lines(words), start=1):
        if ln.bottom <= HEADER_ZONE * height:
            zone = "header"
        elif ln.top >= (1 - HEADER_ZONE) * height:
            zone = "footer"
        else:
            zone = "body"
        segs = _segments(ln.words)
        text = " ".join(s.text for s in segs)
        out.append(GLine(page, i, ln.top, ln.bottom, zone, ln.words, segs, text))
    return out


# --- header ------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _masked(text: str) -> str:
    return re.sub(r"\d+", "#", _norm(text))


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def header_score(ln: GLine, below: list[GLine]) -> float:
    """profile._header_score on segments: text segments + 2 x those with a number under them."""
    if len(ln.segs) < HEADER_MIN_SEGMENTS:
        return 0.0
    texts = [s for s in ln.segs if cell_kind(s.text) in ("text", "date")]
    if len(texts) / len(ln.segs) < 0.6:
        return 0.0
    under = sum(
        1
        for s in texts
        if any(
            cell_kind(b.text) in ("number", "date", "dash") and _overlap(s.x0, s.x1, b.x0, b.x1) > 0
            for ln_b in below
            for b in ln_b.segs
        )
    )
    return len(texts) + 2 * under if under else 0.0


def find_header(pages: list[list[GLine]]) -> tuple[int, int] | None:
    """(page index, line index in that page) of the table header, or None."""
    best_per_page: list[tuple[float, int]] = []
    for lines in pages:
        best = (0.0, -1)
        for i, ln in enumerate(lines):
            if ln.zone != "body":
                continue
            s = header_score(ln, lines[i + 1 : i + 1 + HEADER_BELOW])
            if s > best[0]:
                best = (s, i)
        best_per_page.append(best)
    top = max((s for s, _i in best_per_page), default=0.0)
    if top <= 0:
        return None
    for p, (s, i) in enumerate(best_per_page):
        if s >= HEADER_NEAR_TIE * top:
            return p, i
    return None


def _touches(a: GLine, b: GLine) -> bool:
    """b sits directly above or below a (gap under ~0.6 line height)."""
    h = max(a.bottom - a.top, b.bottom - b.top, 1.0)
    gap = max(a.top - b.bottom, b.top - a.bottom)
    return gap <= 0.6 * h


SINGLE_LABEL_MAX_WIDTH = 2.5  # a one-label header row: at most this x the label under it


def _header_extension(ln: GLine, header: GLine) -> bool:
    """A text-only line touching the header whose segments all sit over header segments. A
    one-segment line must also be narrow (<= 2.5 x the header label it sits on), so a title
    line just above the table is not taken for a header row."""
    if not ln.segs or ln.numeric_segs() or not _touches(ln, header):
        return False
    for s in ln.segs:
        under = [h for h in header.segs if _overlap(s.x0, s.x1, h.x0, h.x1) > 0]
        if cell_kind(s.text) != "text" or not under:
            return False
        if len(ln.segs) == 1:
            widest = max(h.x1 - h.x0 for h in under)
            if s.x1 - s.x0 > SINGLE_LABEL_MAX_WIDTH * max(widest, 1.0):
                return False
    return True


def is_repeat_header(ln: GLine, header_texts: set[str]) -> bool:
    if len(ln.segs) < 2 or not header_texts:
        return False
    texts = {_norm(s.text) for s in ln.segs}
    return len(texts & header_texts) >= HEADER_SIMILAR * len(header_texts)


# --- bands -------------------------------------------------------------------------------------


def find_bands(lines: list[GLine]) -> list[tuple[float, float]]:
    """Column bands between whitespace rivers of these lines' segments."""
    if not lines:
        return []
    lo = min(s.x0 for ln in lines for s in ln.segs)
    hi = max(s.x1 for ln in lines for s in ln.segs)
    n = int((hi - lo) * RESOLUTION) + 2
    cover = [0] * n
    for ln in lines:
        hit = [False] * n
        for s in ln.segs:
            for k in range(int((s.x0 - lo) * RESOLUTION), int((s.x1 - lo) * RESOLUTION) + 1):
                hit[k] = True
        for k in range(n):
            cover[k] += hit[k]
    tol = max(1 if len(lines) >= RIVER_MIN_LINES else 0, int(RIVER_TOL * len(lines)))
    bands: list[tuple[float, float]] = []
    start = None
    for k in range(n):
        filled = cover[k] > tol
        if filled and start is None:
            start = k
        elif not filled and start is not None:
            bands.append((lo + start / RESOLUTION, lo + (k - 1) / RESOLUTION))
            start = None
    if start is not None:
        bands.append((lo + start / RESOLUTION, hi))
    return bands


def band_of(x0: float, x1: float, bands: list[tuple[float, float]]) -> int:
    best = max(range(len(bands)), key=lambda b: _overlap(x0, x1, *bands[b]))
    if _overlap(x0, x1, *bands[best]) > 0:
        return best
    mid = (x0 + x1) / 2
    return min(range(len(bands)), key=lambda b: min(abs(mid - bands[b][0]), abs(mid - bands[b][1])))


def _hits(x0: float, x1: float, bands: list[tuple[float, float]]) -> list[int]:
    return [b for b in range(len(bands)) if _overlap(x0, x1, *bands[b]) > 0]


def start_band(s: Seg, bands: list[tuple[float, float]]) -> int:
    start = [b for b in _hits(s.x0, s.x1, bands) if bands[b][0] <= s.x0 <= bands[b][1]]
    return start[0] if start else band_of(s.x0, s.x1, bands)


def _word_bands(words: list[dict[str, Any]], bands: list[tuple[float, float]]) -> list[int]:
    """Words of one segment (x order): a word overlapping a band goes there; a word in a
    river (a header label wider than its column) follows its nearer neighbour word."""
    out: list[int | None] = [
        max(_hits(w["x0"], w["x1"], bands), key=lambda b: _overlap(w["x0"], w["x1"], *bands[b]))
        if _hits(w["x0"], w["x1"], bands)
        else None
        for w in words
    ]
    for _ in range(len(words)):
        if None not in out:
            break
        for i, w in enumerate(words):
            if out[i] is not None:
                continue
            left = w["x0"] - words[i - 1]["x1"] if i > 0 and out[i - 1] is not None else None
            right = (
                words[i + 1]["x0"] - w["x1"]
                if i + 1 < len(words) and out[i + 1] is not None
                else None
            )
            if left is not None and (right is None or left <= right):
                out[i] = out[i - 1]
            elif right is not None:
                out[i] = out[i + 1]
    return [
        b if b is not None else band_of(w["x0"], w["x1"], bands)
        for w, b in zip(words, out, strict=True)
    ]


def band_cells(ln: GLine, bands: list[tuple[float, float]]) -> dict[int, str]:
    """Rule 5. A label-only line (one segment) stays whole in the band it starts in (a section
    title running across columns). On other lines a segment inside one band goes there; one
    spanning bands (two cells printed too close together) is split word by word."""
    if len(ln.segs) == 1:
        return {start_band(ln.segs[0], bands): ln.segs[0].text}
    groups: dict[int, list[dict[str, Any]]] = {}
    for s in ln.segs:
        words = [w for w in ln.words if w["x0"] >= s.x0 - 0.01 and w["x1"] <= s.x1 + 0.01]
        if len(_hits(s.x0, s.x1, bands)) <= 1:
            groups.setdefault(band_of(s.x0, s.x1, bands), []).extend(words)
            continue
        for w, b in zip(words, _word_bands(words, bands), strict=True):
            groups.setdefault(b, []).append(w)
    return {b: _text(sorted(ws, key=lambda w: w["x0"])) for b, ws in sorted(groups.items())}


# --- the grid ----------------------------------------------------------------------------------


def _page_furniture(pages: list[list[GLine]]) -> set[tuple[int, int]]:
    """(page, idx) of margin lines that repeat (digit-masked) on 2+ pages or read 'Page N'."""
    seen: dict[str, set[int]] = {}
    for lines in pages:
        for ln in lines:
            if ln.zone != "body":
                seen.setdefault(_masked(ln.text), set()).add(ln.page)
    out = set()
    for lines in pages:
        for ln in lines:
            if ln.zone == "body":
                continue
            if len(seen.get(_masked(ln.text), ())) >= 2 or _PAGE_WORD.search(ln.text):
                out.add((ln.page, ln.idx))
    return out


def build_from_lines(pages: list[list[GLine]]) -> GridResult:
    stats: dict[str, Any] = {"pages": len(pages), "lines": sum(len(p) for p in pages)}
    found = find_header(pages)
    if found is None:
        return GridResult(None, "no_header", stats)
    hp, hi = found
    header = pages[hp][hi]
    head_lines = [header]
    if hi > 0 and _header_extension(pages[hp][hi - 1], header):
        head_lines.insert(0, pages[hp][hi - 1])
    if hi + 1 < len(pages[hp]) and _header_extension(pages[hp][hi + 1], header):
        head_lines.append(pages[hp][hi + 1])
    head_ids = {(ln.page, ln.idx) for ln in head_lines}
    header_texts = {_norm(s.text) for s in header.segs}
    furniture = _page_furniture(pages)
    pre: list[GLine] = [ln for ln in pages[hp][:hi] if (ln.page, ln.idx) not in head_ids]
    body: list[GLine] = []
    counts = {"repeated_headers": 0, "page_furniture": 0, "page_header_lines": 0}
    for p in range(hp, len(pages)):
        lines = pages[p]
        start = hi + 1 if p == hp else 0
        if p > hp:
            rep = next(
                (i for i, ln in enumerate(lines) if is_repeat_header(ln, header_texts)), None
            )
            if rep is not None:
                counts["page_header_lines"] += rep
                counts["repeated_headers"] += 1
                start = rep + 1
        for ln in lines[start:]:
            if (ln.page, ln.idx) in head_ids:
                continue
            if (ln.page, ln.idx) in furniture:
                counts["page_furniture"] += 1
                continue
            if is_repeat_header(ln, header_texts):
                counts["repeated_headers"] += 1
                continue
            body.append(ln)
    band_lines = [*head_lines, *(ln for ln in body if len(ln.segs) >= 2 and ln.zone == "body")]
    bands = find_bands(band_lines)
    stats.update(counts, bands=len(bands), header_page=hp + 1, header_rows=len(head_lines))
    if len(bands) < MIN_BANDS:
        return GridResult(None, "too_few_bands", stats)
    if not body:
        return GridResult(None, "no_body", stats)

    # header text per band (two-row headers joined top to bottom)
    head_cells: dict[int, str] = {}
    for ln in head_lines:
        for b, t in band_cells(ln, bands).items():
            head_cells[b] = f"{head_cells.get(b, '')} {t}".strip()

    # body rows with continuation joins
    rows: list[tuple[GLine, dict[int, str]]] = []
    joined = 0
    for ln in body:
        cells = band_cells(ln, bands)
        if rows and _continuation(cells, rows[-1][1]):
            prev = rows[-1][1]
            for b, t in cells.items():
                prev[b] = f"{prev[b]} {t}"
            joined += 1
            continue
        rows.append((ln, cells))
    stats.update(body_lines=len(rows), continuations=joined, header_block_lines=len(pre))

    blocks: list[Block] = []
    row_page: dict[int, int] = {}
    row_line: dict[int, str] = {}
    r = 0
    for ln in pre:  # header block: segments in reading order, A, B, C, ...
        r += 1
        blk = row_block(SHEET, r, [(i, s.text) for i, s in enumerate(ln.segs)])
        if blk is not None:
            blocks.append(blk)
            row_page[r], row_line[r] = ln.page, ln.line_id
    r += 1
    header_row = r
    blk = row_block(SHEET, r, sorted(head_cells.items()))
    if blk is not None:
        blocks.append(blk)
    row_page[r], row_line[r] = header.page, header.line_id
    body_rows: list[int] = []
    for ln, cells in rows:
        r += 1
        blk = row_block(SHEET, r, sorted(cells.items()))
        if blk is None:
            continue
        blocks.append(blk)
        row_page[r], row_line[r] = ln.page, ln.line_id
        body_rows.append(r)
    grid = Grid(blocks, row_page, row_line, header_row, body_rows, stats)
    return GridResult(grid, "ok", stats)


def _continuation(cells: dict[int, str], prev: dict[int, str]) -> bool:
    """Rule 6: empty first band, no number, text only in bands the previous line fills."""
    if not cells or 0 in cells:
        return False
    if any(cell_kind(t) in ("number", "date", "dash") for t in cells.values()):
        return False
    return all(b in prev for b in cells)


def build(content: bytes) -> GridResult:
    """PDF bytes -> GridResult. Never raises on a bad file: the reason says what failed."""
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:  # pdfminer raises many types; the job falls back to v1.0
        return GridResult(None, f"open_failed:{type(exc).__name__}")
    try:
        pages: list[list[GLine]] = []
        for n, ppage in enumerate(pdf.pages, start=1):
            try:
                pages.append(page_lines(ppage, n))
            finally:
                ppage.close()
    except Exception as exc:  # one bad page: no grid, v1.0 path instead (counted, R20)
        return GridResult(None, f"layout_failed:{type(exc).__name__}")
    finally:
        pdf.close()
    return build_from_lines(pages)


# --- citations from code -------------------------------------------------------------------------


def to_pdf_cells(entries: list[dict[str, Any]], grid: Grid) -> list[dict[str, Any]]:
    """Virtual cell refs -> the contract's PDF form: '[Table!C14] x' -> '[Page 2] x' and
    page_numbers [2]; source_locations (an XLSX/CSV field) is dropped."""
    out = []
    for e in entries:
        row = {}
        for k, cell in e.items():
            c = dict(cell)
            refs = c.pop("source_locations", None) or []
            pages = sorted({p for ref in refs if (p := _page_of(ref, grid)) is not None})
            c["citation"] = _REF.sub(
                lambda m: f"Page {grid.row_page.get(int(m[2]), grid.row_page[grid.header_row])}",
                c.get("citation", ""),
            )
            if c.get("value") is not None and pages:
                c["page_numbers"] = pages
            row[k] = c
        out.append(row)
    return out


def _page_of(ref: str, grid: Grid) -> int | None:
    m = _REF.fullmatch(ref)
    return grid.row_page.get(int(m[2])) if m else None


def cell_line(ref: str, grid: Grid) -> str | None:
    """'Table!C14' -> 'P2L014:C3' (line id + band number), or None."""
    m = _REF.fullmatch(ref)
    if not m or int(m[2]) not in grid.row_line:
        return None
    col = 0
    for ch in m[1]:
        col = col * 26 + ord(ch) - 64
    return f"{grid.row_line[int(m[2])]}:C{col}"


__all__ = ["SHEET", "Grid", "GridResult", "build", "cell_line", "to_pdf_cells"]
