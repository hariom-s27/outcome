"""Sheet profiler (P6 T-5): structure facts about every sheet, from the document map only.

Per sheet: lines (one per non-empty row; cells by column letter), header-row candidates,
regions split by blank bands, per-column profiles (header text, type mix, distinct and blank
ratios, vertical SUM formulas, dominant shape) and per-line facts (numeric cells, total-like
word, equals-sum-of-block, header repeat, blank). `preview()` renders the compact view the
model sees: header block, header rows, up to 30 sampled lines with cell addresses, the column
profiles, the sheet list and any parameters sheet as label/value pairs.

Rules are structural and generic (no sheet name, header text or value of any document).
Nothing here logs (R23).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.readers.base import Block, column_letter

TOTAL_WORDS = re.compile(r"\b(?:grand\s+totals?|sub-?totals?|totals?|sum)\b", re.IGNORECASE)
DASHES = frozenset({"-", "--", "–", "—", "−", "‒"})
_REF = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")
_NUM = re.compile(
    r"^\(?\s*[-+]?\s*[$€£]?\s*[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?\s*\)?\s*%?\s*-?$"
)
_DATE = re.compile(
    r"^(?:\d{4}-\d{1,2}(?:-\d{1,2})?(?:[ T][\d:.]+)?"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|\d{1,2}[- ][A-Za-z]{3,9}\.?[- ,]+\d{2,4}"
    r"|[A-Za-z]{3,9}\.?[- ]\d{1,2},?[- ]\d{2,4}"
    r"|[A-Za-z]{3,9}\.?[- ']\d{2,4}"
    r"|\d{1,2}/\d{4})$"
)
_MONTH_WORD = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?$", re.IGNORECASE
)
HEADER_SCAN = 80  # header candidates come from the first lines of a sheet
REGION_GAP = 3  # this many blank rows split a region
PREVIEW_LINES = 30
PREVIEW_CELL_CHARS = 40
HEADER_BLOCK_LINES = 12


# --- cell helpers ------------------------------------------------------------------------------


def letter_index(letter: str) -> int:
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def split_ref(ref: str) -> tuple[str, int] | None:
    m = _REF.match(ref.strip().upper())
    return (m[1], int(m[2])) if m else None


def to_number(text: str) -> float | None:
    """A cell's text as a number: plain, '$1,250.00', '(1,250)' and '1,250-' negative, '4.5%'
    as 4.5. Dashes and blanks are not numbers (the caller decides what they mean, R26)."""
    t = text.strip().replace("−", "-")
    if not t or t in DASHES:
        return None
    try:
        v = (
            float(t.replace(",", ""))
            if re.fullmatch(r"[-+]?[\d,]*\.?\d+(?:[eE][-+]?\d+)?", t)
            else None
        )
    except ValueError:
        v = None
    if v is None:
        if not _NUM.match(t) or not re.search(r"\d", t):
            return None
        neg = (t.startswith("(") and t.endswith(")")) or t.endswith("-") or "-" in t[:3]
        core = re.sub(r"[^\d.]", "", t)
        try:
            v = float(core)
        except ValueError:
            return None
        v = -v if neg else v
    return v if math.isfinite(v) else None


def is_dash(text: str) -> bool:
    return text.strip() in DASHES


def cell_kind(text: str) -> str:
    t = text.strip()
    if not t:
        return "blank"
    if t in DASHES:
        return "dash"
    if to_number(t) is not None:
        return "number"
    if _DATE.match(t) or _MONTH_WORD.match(t):
        return "date"
    return "text"


def shape(text: str) -> str:
    """Shape signature: digit runs -> 9, letter runs -> A, punctuation kept ('C-101' -> 'A-9')."""
    s = re.sub(r"\d+", "9", text.strip())
    s = re.sub(r"[^\W\d_]+", "A", s)
    return re.sub(r"\s+", " ", s)


def has_total_word(text: str) -> bool:
    return bool(TOTAL_WORDS.search(text))


# --- lines -------------------------------------------------------------------------------------


@dataclass
class Line:
    row: int
    cells: dict[str, str]  # column letter -> text ('' for a flagged empty cell)
    flags: tuple[str, ...] = ()
    equals_sum_cols: set[str] = field(default_factory=set)
    header_repeat: bool = False

    @property
    def nonempty(self) -> dict[str, str]:
        return {c: t for c, t in self.cells.items() if t.strip()}

    @property
    def numeric(self) -> dict[str, float]:
        out = {}
        for c, t in self.cells.items():
            v = to_number(t)
            if v is not None:
                out[c] = v
        return out

    @property
    def blank(self) -> bool:
        return not self.nonempty

    @property
    def total_like(self) -> bool:
        return any(cell_kind(t) == "text" and has_total_word(t) for t in self.cells.values())

    @property
    def sum_cols(self) -> set[str]:
        out = set()
        for f in self.flags:
            if f.startswith("sum_formula="):
                ref = split_ref(f.split("=", 1)[1])
                if ref:
                    out.add(ref[0])
        return out

    def text(self, col: str) -> str:
        return self.cells.get(col, "").strip()


def parse_block(b: Block) -> tuple[str, Line] | None:
    """'[Sheet!A4:F4] A4=… | C4=…' -> (sheet, Line). Non-row blocks -> None."""
    if b.kind != "row" or "!" not in b.address:
        return None
    sheet, rng = b.address.rsplit("!", 1)
    ref = split_ref(rng.split(":", 1)[0])
    if ref is None:
        return None
    row = ref[1]
    parts = re.split(rf"(?:^| \| )([A-Z]{{1,3}}){row}=", b.text)
    cells: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        cells[parts[i]] = parts[i + 1]
    return sheet, Line(row, cells, tuple(b.flags))


# --- profiles ----------------------------------------------------------------------------------


@dataclass
class ColumnProfile:
    letter: str
    header: str
    n: int  # data lines
    kinds: dict[str, int]
    distinct_ratio: float
    blank_ratio: float
    formula_count: int
    shape: str
    shape_share: float


@dataclass
class SheetProfile:
    name: str
    lines: dict[int, Line]
    header_candidates: list[int]
    header_row: int | None
    header_rows: tuple[int, ...]
    headers: dict[str, str]
    columns: dict[str, ColumnProfile]
    regions: list[tuple[int, int]]
    is_parameters: bool
    data_first: int
    data_last: int

    @property
    def rows(self) -> list[int]:
        return sorted(self.lines)

    def data_lines(self, first: int | None = None, last: int | None = None) -> list[Line]:
        lo = self.data_first if first is None else first
        hi = self.data_last if last is None else last
        return [self.lines[r] for r in self.rows if lo <= r <= hi]

    def cell(self, col: str, row: int) -> str:
        line = self.lines.get(row)
        return line.text(col) if line else ""


@dataclass
class WorkbookProfile:
    sheets: dict[str, SheetProfile]
    main: str | None  # the sheet with the most lines that is not a parameters sheet

    def sheet(self, name: str | None = None) -> SheetProfile | None:
        return self.sheets.get(name or self.main or "")

    def data_line_count(self) -> int:
        sp = self.sheet()
        return len(sp.data_lines()) if sp else 0


def _header_score(line: Line, below: list[Line]) -> float:
    ne = line.nonempty
    if len(ne) < 2:
        return 0.0
    texts = [c for c, t in ne.items() if cell_kind(t) in ("text", "date")]
    if len(texts) / len(ne) < 0.6:
        return 0.0
    under = sum(
        1
        for c in texts
        if any(cell_kind(b.cells.get(c, "")) in ("number", "date", "dash") for b in below)
    )
    return len(texts) + 2 * under


def _headers(lines: dict[int, Line], rows: list[int], header_row: int) -> tuple[tuple, dict]:
    line = lines[header_row]
    hdr = {c: t.strip() for c, t in line.nonempty.items()}
    used = [header_row]
    above = lines.get(header_row - 1)
    wide = above is not None and len(above.nonempty) >= 2 and len(above.nonempty) > len(hdr) / 2
    if above is not None and wide:  # a two-row header, not a "Label: value" line above it
        texts = list(above.nonempty.values())
        if all(cell_kind(t) in ("text", "date") and not t.rstrip().endswith(":") for t in texts):
            for c, t in above.nonempty.items():
                hdr[c] = f"{t.strip()} {hdr.get(c, '')}".strip()
            used.insert(0, header_row - 1)
    return tuple(used), hdr


def _mark_equals_sum(data: list[Line]) -> None:
    block: dict[str, list[float]] = {}
    prev_row = None
    for line in data:
        if prev_row is not None and line.row - prev_row > 1:
            block = {}
        prev_row = line.row
        if line.header_repeat or line.blank:
            block = {}
            continue
        nums = line.numeric
        for c, v in nums.items():
            vals = block.get(c, [])
            if len(vals) >= 2:
                s = sum(vals)
                if (v != 0 or s != 0) and close(v, s):
                    line.equals_sum_cols.add(c)
        if line.equals_sum_cols or line.total_like or line.sum_cols:
            block = {}
            continue
        for c, v in nums.items():
            block.setdefault(c, []).append(v)


def close(a: float, b: float, rel: float = 0.005) -> bool:
    return abs(a - b) <= max(0.011, rel * max(abs(a), abs(b)))


def _is_parameters(lines: list[Line]) -> bool:
    if not lines or len(lines) > 60:
        return False
    pairs = 0
    for ln in lines:
        ne = ln.nonempty
        if 1 <= len(ne) <= 3:
            first = ne[min(ne, key=letter_index)]
            if cell_kind(first) == "text":
                pairs += 1
    return pairs / len(lines) >= 0.6


def _regions(rows: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for r in rows:
        if out and r - out[-1][1] <= REGION_GAP:
            out[-1] = (out[-1][0], r)
        else:
            out.append((r, r))
    return out


def profile_sheet(name: str, lines: dict[int, Line]) -> SheetProfile:
    rows = sorted(lines)
    scan = rows[:HEADER_SCAN]
    scored = []
    for i, r in enumerate(scan):
        below = [lines[x] for x in rows[i + 1 : i + 16]]
        s = _header_score(lines[r], below)
        if s > 0:
            scored.append((s, -r, r))
    scored.sort(reverse=True)
    candidates = [r for _s, _neg, r in scored[:3]]
    header_row = candidates[0] if candidates else None
    header_rows: tuple[int, ...] = ()
    headers: dict[str, str] = {}
    if header_row is not None:
        header_rows, headers = _headers(lines, rows, header_row)
    data_first = (header_row + 1) if header_row is not None else (rows[0] if rows else 1)
    data_last = rows[-1] if rows else data_first
    data = [lines[r] for r in rows if data_first <= r <= data_last]
    if header_row is not None:
        hdr_cells = {c: t.casefold() for c, t in lines[header_row].nonempty.items()}
        for ln in data:
            same = sum(1 for c, t in hdr_cells.items() if ln.text(c).casefold() == t)
            ln.header_repeat = len(hdr_cells) >= 2 and same >= 0.7 * len(hdr_cells)
    _mark_equals_sum(data)
    letters = sorted({c for ln in data for c in ln.cells} | set(headers), key=letter_index)
    columns: dict[str, ColumnProfile] = {}
    n = len(data)
    for c in letters:
        kinds = Counter(cell_kind(ln.cells.get(c, "")) for ln in data)
        vals = [ln.text(c) for ln in data if ln.text(c)]
        shapes = Counter(shape(v) for v in vals)
        top, top_n = shapes.most_common(1)[0] if shapes else ("", 0)
        columns[c] = ColumnProfile(
            letter=c,
            header=headers.get(c, ""),
            n=n,
            kinds=dict(kinds),
            distinct_ratio=round(len(set(vals)) / len(vals), 3) if vals else 0.0,
            blank_ratio=round(kinds.get("blank", 0) / n, 3) if n else 1.0,
            formula_count=sum(1 for ln in data if c in ln.sum_cols),
            shape=top,
            shape_share=round(top_n / len(vals), 3) if vals else 0.0,
        )
    return SheetProfile(
        name=name,
        lines=lines,
        header_candidates=candidates,
        header_row=header_row,
        header_rows=header_rows,
        headers=headers,
        columns=columns,
        regions=_regions(rows),
        is_parameters=False,
        data_first=data_first,
        data_last=data_last,
    )


def profile_blocks(blocks: list[Block]) -> WorkbookProfile:
    by_sheet: dict[str, dict[int, Line]] = {}
    for b in blocks:
        parsed = parse_block(b)
        if parsed is None:
            continue
        sheet, line = parsed
        by_sheet.setdefault(sheet, {})[line.row] = line
    sheets = {name: profile_sheet(name, lines) for name, lines in by_sheet.items()}
    main = max(sheets, key=lambda s: len(sheets[s].lines), default=None)
    for name, sp in sheets.items():
        sp.is_parameters = name != main and _is_parameters(list(sp.lines.values()))
    return WorkbookProfile(sheets, main)


# --- preview -----------------------------------------------------------------------------------


def _clip(text: str, n: int = PREVIEW_CELL_CHARS) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def render_line(sheet: str, line: Line) -> str:
    cells = sorted(line.nonempty.items(), key=lambda kv: letter_index(kv[0]))
    return " | ".join(f"[{sheet}!{c}{line.row}] {_clip(t)}" for c, t in cells)


def sample_lines(sp: SheetProfile, limit: int = PREVIEW_LINES) -> list[Line | None]:
    """First 15, a middle 10 starting just before a block boundary (a total-like or sum line
    near the middle), last 5; None marks a gap."""
    data = sp.data_lines()
    if len(data) <= limit:
        return list(data)
    n = len(data)
    mid = n // 2
    start = mid
    found = False
    for off in range(0, n // 4):
        for i in (mid + off, mid - off):
            ln = data[i]
            if 15 <= i < n - 5 and (ln.total_like or ln.equals_sum_cols or ln.sum_cols):
                start, found = i, True
                break
        if found:
            break
    start = max(15, min(start - 3, n - 15))
    picked = sorted({*range(15), *range(start, start + 10), *range(n - 5, n)})
    out: list[Line | None] = []
    for k, i in enumerate(picked):
        if k and i != picked[k - 1] + 1:
            out.append(None)
        out.append(data[i])
    return out


def _column_line(cp: ColumnProfile) -> str:
    n_ne = max(1, cp.n - cp.kinds.get("blank", 0))
    mix = ", ".join(
        f"{k} {round(100 * v / n_ne)}%"
        for k, v in sorted(cp.kinds.items(), key=lambda kv: -kv[1])
        if k != "blank"
    )
    hdr = f'"{_clip(cp.header)}"' if cp.header else "(no header)"
    return (
        f"{cp.letter} {hdr}: {mix or 'empty'}; blank {round(100 * cp.blank_ratio)}%; "
        f"distinct {cp.distinct_ratio:.2f}; shape '{cp.shape}' {round(100 * cp.shape_share)}%"
        + (f"; SUM formulas {cp.formula_count}" if cp.formula_count else "")
    )


def preview(wp: WorkbookProfile) -> str:
    out: list[str] = ["SHEETS:"]
    for name, sp in wp.sheets.items():
        role = "parameters" if sp.is_parameters else ("main" if name == wp.main else "other")
        hdr = f", header row {sp.header_row}" if sp.header_row else ""
        out.append(f'- "{name}" ({role}; {len(sp.lines)} non-empty rows{hdr})')
    sp = wp.sheet()
    if sp is None:
        return "\n".join(out)
    first_hdr = sp.header_rows[0] if sp.header_rows else sp.data_first
    top = [sp.lines[r] for r in sp.rows if r < first_hdr][:HEADER_BLOCK_LINES]
    if top:
        out += ["", f'HEADER BLOCK of "{sp.name}" (rows above the table header):']
        out += [render_line(sp.name, ln) for ln in top]
    if sp.header_rows:
        out += ["", f'TABLE HEADER of "{sp.name}" (rows {", ".join(map(str, sp.header_rows))}):']
        out += [render_line(sp.name, sp.lines[r]) for r in sp.header_rows]
        if len(sp.header_candidates) > 1:
            out.append(f"(other header-row candidates: {sp.header_candidates[1:]})")
    data = sp.data_lines()
    out += [
        "",
        f'COLUMNS of "{sp.name}" (data rows {sp.data_first}-{sp.data_last}, {len(data)} '
        "non-empty lines):",
    ]
    out += [_column_line(cp) for cp in sp.columns.values()]
    shown = sample_lines(sp)
    out += ["", f"LINES (sample of {sum(1 for x in shown if x)} of {len(data)}; … = rows skipped):"]
    for ln in shown:
        if ln is None:
            out.append("…")
            continue
        tags = []
        if ln.total_like:
            tags.append("total-word")
        if ln.equals_sum_cols:
            tags.append("equals-sum:" + ",".join(sorted(ln.equals_sum_cols, key=letter_index)))
        if ln.sum_cols:
            tags.append("SUM-formula:" + ",".join(sorted(ln.sum_cols, key=letter_index)))
        if ln.header_repeat:
            tags.append("header-repeat")
        out.append(render_line(sp.name, ln) + (f"   <{'; '.join(tags)}>" if tags else ""))
    for name, other in wp.sheets.items():
        if name == wp.main:
            continue
        kind = "PARAMETERS" if other.is_parameters else "OTHER SHEET"
        out += ["", f'{kind} "{name}" (label | value):']
        out += [render_line(name, ln) for ln in [other.lines[r] for r in other.rows][:25]]
    return "\n".join(out)


def column_letters(n: int) -> list[str]:
    return [column_letter(i) for i in range(n)]
