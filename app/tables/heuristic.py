"""Heuristic table spec (P6 T-6): built by code, no model. An independent second opinion.

- header match: rapidfuzz on the field's name and key words (common abbreviations expanded)
  against each column's header text; a header quoted in the description counts as a match;
  a type clash (number field on a text column) costs points; greedy one-to-one assignment
- key column: the primary field's match, else the most unique, shape-consistent column
- record_start key_nonempty; skip total_like, header_repeat, blank, formula_sum_rows,
  section_header
- document-level fields (description says the value is the same for every row / the whole
  document / the report header): label match in a parameters sheet or the header block
  above the table; the value is the cell after the label (or the label cell's own text
  after a colon)
- no pick_by_label / map_distinct / derived: those fields stay null
Output is plain spec JSON, validated by the same grammar as a model's spec.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

from app.extract.compile_fields import FieldSpec, compile_fields
from app.tables.profile import (
    ColumnProfile,
    Line,
    SheetProfile,
    WorkbookProfile,
    cell_kind,
    letter_index,
)

MATCH_MIN = 75
LABEL_MIN = 80
DOC_LEVEL = re.compile(
    r"\bsame (?:value )?for (?:every|each|all) (?:rows?|entr(?:y|ies)|lines?)\b"
    r"|\bwhole document\b|\breport header\b|\bapplies to the (?:whole|entire)\b",
    re.IGNORECASE,
)
ABBREV = {
    "sq": "square",
    "ft": "feet",
    "sf": "square feet",
    "sqft": "square feet",
    "amt": "amount",
    "no": "number",
    "#": "number",
    "num": "number",
    "%": "percent",
    "pct": "percent",
    "qty": "quantity",
    "acct": "account",
    "bal": "balance",
    "dep": "deposit",
    "mo": "month",
    "yr": "year",
    "avg": "average",
    "mkt": "market",
    "sched": "scheduled",
    "exp": "expected",
    "desc": "description",
}
NUMERIC_TYPES = ("number", "integer", "percent")
SKIP = ["total_like", "header_repeat", "blank", "formula_sum_rows", "section_header"]


def norm_words(s: str) -> str:
    s = s.lower().replace("%", " % ").replace("#", " # ")
    toks = re.findall(r"[a-z0-9]+|%|#", s)
    return " ".join(ABBREV.get(t, t) for t in toks)


def text_score(a: str, b: str) -> float:
    a, b = norm_words(a), norm_words(b)
    if not a or not b:
        return 0.0
    return (fuzz.token_set_ratio(a, b) + fuzz.ratio(a, b)) / 2


def _quoted(desc: str) -> set[str]:
    return {
        (x or y).strip().casefold()
        for x, y in re.findall(r"'([^']{1,40})'|\"([^\"]{1,40})\"", desc or "")
    }


def match_score(fs: FieldSpec, header: str) -> float:
    if not header.strip():
        return 0.0
    if header.strip().casefold() in _quoted(fs.description):
        return 100.0
    names = [fs.name, fs.key.replace("_", " ")]
    return max(text_score(n, header) for n in names if n)


def _numeric_share(cp: ColumnProfile) -> float:
    n = max(1, cp.n - cp.kinds.get("blank", 0) - cp.kinds.get("dash", 0))
    return (cp.kinds.get("number", 0)) / n


def _type_penalty(fs: FieldSpec, cp: ColumnProfile) -> float:
    share = _numeric_share(cp)
    if fs.type in NUMERIC_TYPES and share < 0.5:
        return 25.0
    if fs.type in ("text", "free_text") and share > 0.8:
        return 15.0
    return 0.0


def is_doc_level(fs: FieldSpec) -> bool:
    return bool(DOC_LEVEL.search(fs.description))


def pick_key_column(sp: SheetProfile, fs: FieldSpec | None) -> str | None:
    if fs is not None:  # among the columns matching the primary field, the most unique one
        matching = [
            (cp.distinct_ratio * cp.shape_share, match_score(fs, cp.header), cp.letter)
            for cp in sp.columns.values()
            if match_score(fs, cp.header) >= MATCH_MIN
        ]
        if matching:
            return max(matching)[2]
    usable = [
        cp
        for cp in sp.columns.values()
        if cp.n and (1 - cp.blank_ratio) >= 0.1 and _numeric_share(cp) < 1.0
    ]
    if not usable:
        return None
    return max(
        usable, key=lambda cp: (cp.distinct_ratio * cp.shape_share, -letter_index(cp.letter))
    ).letter


def label_cells(wp: WorkbookProfile) -> list[tuple[str, Line]]:
    """Where document-level labels live: parameters sheets, then the header block."""
    out: list[tuple[str, Line]] = []
    for name, sp in wp.sheets.items():
        if sp.is_parameters:
            out += [(name, sp.lines[r]) for r in sp.rows]
    sp = wp.sheet()
    if sp is not None:
        first = sp.header_rows[0] if sp.header_rows else sp.data_first
        out += [(sp.name, sp.lines[r]) for r in sp.rows if r < first]
    return out


def find_doc_cell(fs: FieldSpec, wp: WorkbookProfile) -> str | None:
    best: tuple[float, str] | None = None
    for sheet, ln in label_cells(wp):
        cells = sorted(ln.nonempty.items(), key=lambda kv: letter_index(kv[0]))
        for i, (col, text) in enumerate(cells):
            if cell_kind(text) != "text":
                continue
            label, _, after = text.partition(":")
            s = max(text_score(n, label) for n in (fs.name, fs.key.replace("_", " ")) if n)
            if s < LABEL_MIN:
                continue
            if after.strip():
                ref = f"{sheet}!{col}{ln.row}"
            elif i + 1 < len(cells):
                ref = f"{sheet}!{cells[i + 1][0]}{ln.row}"
            else:
                continue
            if best is None or s > best[0]:
                best = (s, ref)
    return best[1] if best else None


def build(field_list: dict[str, Any], wp: WorkbookProfile) -> dict[str, Any] | None:
    sp = wp.sheet()
    if sp is None:
        return None
    specs = compile_fields(field_list)
    primary = next((fs for fs in specs.values() if fs.primary), None)
    key_col = pick_key_column(sp, primary)
    if key_col is None:
        return None
    row_fields: dict[str, Any] = {}
    doc_fields: dict[str, Any] = {}
    cands: list[tuple[float, str, str]] = []
    for key, fs in specs.items():
        if fs.primary or is_doc_level(fs):
            continue
        for cp in sp.columns.values():
            if cp.letter == key_col or not cp.header:
                continue
            s = match_score(fs, cp.header) - _type_penalty(fs, cp)
            if s >= MATCH_MIN:
                cands.append((s, key, cp.letter))
    used_cols: set[str] = {key_col}
    for _s, key, col in sorted(cands, key=lambda t: (-t[0], letter_index(t[2]))):
        if key in row_fields or col in used_cols:
            continue
        row_fields[key] = {"col": col, "fold": "first_nonempty"}
        used_cols.add(col)
    for key, fs in specs.items():
        if is_doc_level(fs):
            doc_fields[key] = {"cell": ref} if (ref := find_doc_cell(fs, wp)) is not None else None
    return {
        "sheet": sp.name,
        "header_row": sp.header_row,
        "data_first_row": sp.data_first,
        "data_last_row": None,
        "until_blank_run": None,
        "key_column": key_col,
        "record_start": "key_nonempty",
        "skip": list(SKIP),
        "row_fields": row_fields,
        "doc_fields": doc_fields,
    }
