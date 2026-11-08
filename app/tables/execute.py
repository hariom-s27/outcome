"""Spec executor (P6 T-9, T-11): apply one spec to EVERY line of the sheet.

Each line gets a disposition: record / child / skipped-<reason> / unexplained. Children fold
into the last record. Keys and values are copied from cells (keys as displayed, leading zeros
kept; values through the normaliser by field type; R26: a blank or dash money cell of a real
record is 0). Document-level fields are read once and repeated in every row (R30). One row per
key: the first wins, duplicates are counted. Citations are "[Sheet!C12] <cell text>" and
source_locations lists every cell used.

Order of rules per line: header_repeat, blank, total_like, formula_sum_rows, section_header
(each only when listed in `skip`), then record start (a would-be record with no number
outside its key cell is skipped-no_amount when `no_amount` is listed), then child (after a
record, key cell empty) or unexplained. A field typed only from nouns in its description
("null for vacant units" -> integer) keeps a text cell as text instead of nulling it.
The three content skips never drop a line whose key is a proper key (non-empty, the key
column's dominant shape, no total word): a GL line named "Total ..." with its own code is a
record.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.extract.compile_fields import FieldSpec, _name_type, compile_fields
from app.extract.normalise import NO_HINTS, DocHints, normalise, vote_date_order
from app.tables.profile import (
    Line,
    WorkbookProfile,
    cell_kind,
    has_total_word,
    is_dash,
    letter_index,
    shape,
    split_ref,
    to_number,
)
from app.tables.spec import Spec

MONEY = re.compile(
    r"\b(?:rent|price|amount|cost|deposits?|charges?|fees?|income|revenue|expenses?|tax(?:es)?"
    r"|budget|actual|variance|balance|total|noi|dollars?)\b|\$",
    re.IGNORECASE,
)
ZERO_IF = re.compile(r"\b(?:0|zero) if\b", re.IGNORECASE)
NUMERIC_TYPES = ("number", "integer", "percent")
TEXT_TYPES = ("text", "free_text", "code")
MAX_CITED = 3
MAX_LOCATIONS = 24


def weak_type(fs: FieldSpec) -> bool:
    """The type came from a noun in the description only (no explicit hint, nothing in the
    field's name or key): a text cell then stays text rather than becoming null."""
    if fs.rule.startswith("1:"):
        return False
    words = fs.key.replace("_", " ")
    return _name_type(fs.name.strip() or words) is None and _name_type(words) is None


def is_money(fs: FieldSpec) -> bool:
    """R26: a blank money cell in a real record is 0 (the description's '0 if ...' too)."""
    if fs.type not in NUMERIC_TYPES:
        return False
    return bool(MONEY.search(f"{fs.key.replace('_', ' ')} {fs.name}")) or bool(
        ZERO_IF.search(fs.description)
    )


@dataclass
class Record:
    key: str
    row: int
    lines: list[Line]  # record line + children (what folds read)
    block: list[Line]  # + skipped total lines after it (what pick_by_label may read)
    section: str | None = None
    section_ref: str | None = None


@dataclass
class Got:
    """One field of one record before normalising."""

    text: str | None = None  # a cell's text (normalised later by field type)
    number: float | None = None  # a sum / count computed from cells
    refs: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    empty: bool = True


@dataclass
class Execution:
    spec: Spec
    entries: list[dict[str, Any]]
    records: list[Record]  # unique keys, first wins
    keys_seen: list[str]  # every record key in order, duplicates included
    dispositions: Counter
    ordered: list[tuple[Line, str]]  # every line in the data range with its disposition
    region_lines: int
    duplicates: int
    keyless: int
    key_shape: str
    value_cols: list[str]  # numeric columns the spec reads (for the totals check)
    parse: dict[str, list[int]]  # field -> [parsed, tried] over non-empty source cells
    field_sources: dict[str, str]  # field -> rule kind (col, pick_by_label, ..., doc, none)


def _ref(sheet: str, col: str, row: int) -> str:
    return f"{sheet}!{col}{row}"


def range_lines(spec: Spec, wp: WorkbookProfile) -> list[Line]:
    sp = wp.sheets[spec.sheet]
    out: list[Line] = []
    prev = None
    for r in sp.rows:
        if r < spec.data_first_row:
            continue
        if spec.data_last_row is not None and r > spec.data_last_row:
            break
        if spec.until_blank_run and prev is not None and r - prev - 1 >= spec.until_blank_run:
            break
        out.append(sp.lines[r])
        prev = r
    return out


def dominant_key_shape(lines: list[Line], key_col: str) -> str:
    shapes = Counter(
        shape(ln.text(key_col))
        for ln in lines
        if ln.text(key_col) and not has_total_word(ln.text(key_col))
    )
    return shapes.most_common(1)[0][0] if shapes else ""


def _section_like(ln: Line, key: str, key_ok: bool) -> bool:
    ne = ln.nonempty
    return (
        1 <= len(ne) <= 2
        and not ln.numeric
        and not ln.total_like
        and not ln.header_repeat
        and not key_ok
        and any(len(t.strip()) > 1 for t in ne.values())
    )


def _first_text(ln: Line) -> tuple[str, str] | None:
    ne = ln.nonempty
    if not ne:
        return None
    col = min(ne, key=letter_index)
    return col, ne[col].strip()


def classify(spec: Spec, lines: list[Line], key_shape: str) -> list[tuple[Line, str]]:
    out: list[tuple[Line, str]] = []
    have_record = False
    skip = set(spec.skip)
    for ln in lines:
        key = ln.text(spec.key_column)
        key_ok = bool(key) and shape(key) == key_shape and not has_total_word(key)
        if "header_repeat" in skip and ln.header_repeat:
            disp = "skipped-header_repeat"
        elif "blank" in skip and ln.blank:
            disp = "skipped-blank"
        elif "total_like" in skip and ln.total_like and not key_ok:
            disp = "skipped-total_like"
        elif "formula_sum_rows" in skip and (ln.sum_cols or ln.equals_sum_cols) and not key_ok:
            disp = "skipped-formula_sum_rows"
        elif "section_header" in skip and _section_like(ln, key, key_ok):
            disp = "skipped-section_header"
        elif ln.blank:
            disp = "child" if have_record else "skipped-blank"
        else:
            if spec.record_start == "key_nonempty":
                start = bool(key)
            elif spec.record_start == "key_matches_shape":
                start = key_ok
            else:
                start = bool(ln.text(spec.record_col or ""))
            if start and "no_amount" in skip and not any(c != spec.key_column for c in ln.numeric):
                disp = "skipped-no_amount"
            elif start:
                disp = "record"
                have_record = True
            elif have_record and not key:
                disp = "child"
            else:
                disp = "unexplained"
        out.append((ln, disp))
    return out


def _records(
    spec: Spec, ordered: list[tuple[Line, str]], key_shape: str
) -> tuple[list[Record], int]:
    records: list[Record] = []
    keyless = 0
    current: Record | None = None
    section: tuple[str, str] | None = None
    for ln, disp in ordered:
        key = ln.text(spec.key_column)
        key_ok = bool(key) and shape(key) == key_shape and not has_total_word(key)
        if disp != "record" and _section_like(ln, key, key_ok):
            ft = _first_text(ln)
            if ft:
                section = (ft[1], _ref(spec.sheet, ft[0], ln.row))
        if disp == "record":
            current = Record(key, ln.row, [ln], [ln])
            if section:
                current.section, current.section_ref = section
            if key:
                records.append(current)
            else:
                keyless += 1
        elif disp == "child" and current is not None:
            current.lines.append(ln)
            current.block.append(ln)
        elif disp in ("skipped-total_like", "skipped-formula_sum_rows") and current is not None:
            current.block.append(ln)
    return records, keyless


def _norm_label(s: str) -> str:
    return " ".join(s.split()).casefold().rstrip(":")


def evaluate(spec: Spec, rec: Record, rule: dict[str, Any]) -> Got:
    sh = spec.sheet
    if "col" in rule:
        col, fold = rule["col"], rule.get("fold", "first_nonempty")
        if fold in ("first_nonempty", "last_nonempty"):
            seq = rec.lines if fold == "first_nonempty" else list(reversed(rec.lines))
            for ln in seq:
                t = ln.text(col)
                if t:
                    return Got(text=t, refs=[_ref(sh, col, ln.row)], texts=[t], empty=False)
            return Got()
        ex = rule.get("except_label")
        excl = {_norm_label(x) for x in ex["labels"]} if ex else set()
        total, refs, texts, any_cell = 0.0, [], [], False
        for ln in rec.lines:
            if ex:
                lab = ln.text(ex["label_col"])
                if not lab or _norm_label(lab) in excl:
                    continue
            t = ln.text(col)
            v = to_number(t) if t else None
            if v is None and not (t and is_dash(t)):
                continue
            any_cell = True
            total += v or 0.0
            refs.append(_ref(sh, col, ln.row))
            texts.append(t)
        return Got(number=total if any_cell else None, refs=refs, texts=texts, empty=not any_cell)
    if "pick_by_label" in rule:
        p = rule["pick_by_label"]
        want = _norm_label(p["label_text"])
        for ln in rec.block:
            if _norm_label(ln.text(p["label_col"])) == want:
                t = ln.text(p["value_col"])
                if t:
                    return Got(
                        text=t, refs=[_ref(sh, p["value_col"], ln.row)], texts=[t], empty=False
                    )
                return Got()
        return Got()
    if "section_context" in rule:
        if rec.section:
            return Got(
                text=rec.section, refs=[rec.section_ref or ""], texts=[rec.section], empty=False
            )
        return Got()
    if "derived" in rule:
        d = rule["derived"]
        ln = rec.lines[0]
        vals = [(c, ln.text(c), to_number(ln.text(c))) for c in d["cols"]]
        refs = [_ref(sh, c, ln.row) for c, t, _v in vals if t]
        texts = [t for _c, t, _v in vals if t]
        if d["op"] == "count_nonzero":
            n = sum(1 for _c, _t, v in vals if v is not None and v != 0)
            return Got(number=float(n), refs=refs, texts=texts, empty=False)
        nums = [v for _c, _t, v in vals if v is not None]
        return Got(number=sum(nums), refs=refs, texts=texts, empty=not nums)
    m = rule["map_distinct"]
    if m["from"] == "section_context":
        src = evaluate(spec, rec, {"section_context": True})
    else:
        src = evaluate(spec, rec, {"col": m["from"], "fold": "first_nonempty"})
    if src.empty or src.text is None:
        return Got()
    mapping = m["map"]
    hit = mapping.get(src.text)
    if hit is None:
        low = {_norm_label(k): v for k, v in mapping.items()}
        hit = low.get(_norm_label(src.text))
    if hit is None:
        return Got()
    return Got(text=hit, refs=src.refs, texts=src.texts, empty=False)


def _cite(refs: list[str], texts: list[str]) -> str:
    parts = [f"[{r}] {t}" for r, t in zip(refs, texts, strict=False)][:MAX_CITED]
    more = " + …" if len(refs) > MAX_CITED else ""
    return " + ".join(parts) + more


def parse_text(fs: FieldSpec, text: str, parse: str, hints: DocHints = NO_HINTS) -> Any:
    """Z-2: a value read out of a cell's text by the normaliser, or None (never a guess).
    date_start / date_end pick the first / last date of a range (date_end keeps a
    period_end field's month-end reading); date uses the field's own role."""
    if parse == "text":
        return normalise(text, "text")[0]
    if parse == "number":
        return normalise(text, fs.type if fs.type in NUMERIC_TYPES else "number", hints=hints)[0]
    if parse == "date_start":
        role = "start"
    elif parse == "date_end":
        role = "period_end" if fs.date_role == "period_end" else "end"
    else:
        role = fs.date_role
    type_ = fs.type if fs.type in ("date", "month") else "date"
    return normalise(text, type_, hints=hints, role=role, year_range=fs.year_range)[0]


def finish(
    fs: FieldSpec,
    got: Got,
    rule_kind: str,
    key_ref: str,
    key_text: str,
    doc: bool = False,
    hints: DocHints = NO_HINTS,
    parse: str | None = None,
    strict: bool = False,
) -> tuple[dict[str, Any], bool | None]:
    """-> (field cell without confidence, parsed?) ; parsed None when there was nothing to try.
    strict (Z-3 merge guard): no weak-type text fallback, only values of the field's type."""
    null = {"value": None, "citation": ""}
    if got.empty:
        if not doc and is_money(fs) and rule_kind in ("col", "pick_by_label"):
            return {"value": 0, "citation": f"[{key_ref}] {key_text}", "source_locations": [
                key_ref]}, None  # fmt: skip
        return null, None
    refs = [r for r in got.refs if r][:MAX_LOCATIONS]
    if parse and got.number is None:
        parsed = parse_text(fs, got.text or "", parse, hints)
        if parsed is None:
            return null, False
        return {
            "value": parsed,
            "citation": _cite(got.refs, got.texts),
            "source_locations": refs,
        }, True
    if got.number is not None:
        v: Any = got.number
        v = int(v) if float(v).is_integer() else round(v, 6)
        if fs.type == "integer" and not float(v).is_integer():
            return null, False
        cite = _cite(got.refs, got.texts) or f"[{key_ref}] {key_text}"
        return {"value": v, "citation": cite, "source_locations": refs or [key_ref]}, True
    t = got.text or ""
    if fs.type in TEXT_TYPES:
        if doc:
            value, _r = normalise(t, "text")
        else:
            value = " ".join(t.split())
        ok = value is not None
    elif fs.type in NUMERIC_TYPES and is_dash(t):
        value, ok = 0, True
    else:
        value, _r = normalise(
            t,
            fs.type,
            hints=hints,
            role=fs.date_role,
            item_type=fs.item_type or "text",
            year_range=fs.year_range,
        )
        ok = value is not None
        if value is None and not strict and weak_type(fs) and cell_kind(t) == "text":
            value, ok = " ".join(t.split()), True
    if value is None:
        return null, ok
    return {"value": value, "citation": _cite(got.refs, got.texts), "source_locations": refs}, ok


def _value_cols(spec: Spec, specs: dict[str, FieldSpec]) -> list[str]:
    cols: list[str] = []
    for key, rule in spec.row_fields.items():
        fs = specs.get(key)
        if fs is None or fs.type not in NUMERIC_TYPES:
            continue
        if "col" in rule:
            cols.append(rule["col"])
        elif "pick_by_label" in rule:
            cols.append(rule["pick_by_label"]["value_col"])
    return list(dict.fromkeys(cols))


def date_hints(wp: WorkbookProfile, lines: list[Line]) -> DocHints:
    """One MDY/DMY vote per workbook from every date-like cell (DR15 document-level vote)."""
    texts = [t for ln in lines for t in ln.cells.values() if cell_kind(t) == "date"]
    for sp in wp.sheets.values():
        if sp.is_parameters:
            texts += [t for ln in sp.lines.values() for t in ln.cells.values()]
    return DocHints(date_order=vote_date_order(texts))


def doc_cells(
    spec: Spec,
    wp: WorkbookProfile,
    specs: dict[str, FieldSpec],
    hints: DocHints = NO_HINTS,
    strict: bool = False,
) -> dict[str, tuple[dict[str, Any], bool | None]]:
    out = {}
    for key, ref in spec.doc_fields.items():
        fs = specs.get(key)
        if fs is None or ref is None:
            continue
        sh, a1 = ref.rsplit("!", 1)
        col, row = split_ref(a1) or ("", 0)
        t = wp.sheets[sh].cell(col, row) if sh in wp.sheets else ""
        got = Got(text=t, refs=[ref], texts=[t], empty=not t)
        parse = spec.doc_parse.get(key)
        out[key] = finish(fs, got, "doc", ref, t, doc=True, hints=hints, parse=parse, strict=strict)
    return out


def execute(spec: Spec, wp: WorkbookProfile, field_list: dict[str, Any]) -> Execution:
    specs = compile_fields(field_list)
    primary = next((k for k, fs in specs.items() if fs.primary), None)
    lines = range_lines(spec, wp)
    key_shape = dominant_key_shape(lines, spec.key_column)
    ordered = classify(spec, lines, key_shape)
    records_all, keyless = _records(spec, ordered, key_shape)
    seen: set[str] = set()
    records: list[Record] = []
    for r in records_all:
        if r.key in seen:
            continue
        seen.add(r.key)
        records.append(r)
    hints = date_hints(wp, lines)
    docs = doc_cells(spec, wp, specs, hints)
    parse: dict[str, list[int]] = {}
    sources: dict[str, str] = {}
    for key in specs:
        if key == primary:
            sources[key] = "key"
        elif key in spec.row_fields:
            sources[key] = next(k for k in spec.row_fields[key] if k not in ("fold", "parse"))
        elif key in docs:
            sources[key] = "doc"
        else:
            sources[key] = "none"
    # C4 is per mapped COLUMN: document-level cells are not columns, so they are not counted
    entries: list[dict[str, Any]] = []
    for rec in records:
        key_ref = _ref(spec.sheet, spec.key_column, rec.row)
        entry: dict[str, Any] = {}
        for key, fs in specs.items():
            if key == primary:
                entry[key] = {
                    "value": rec.key,
                    "citation": f"[{key_ref}] {rec.key}",
                    "source_locations": [key_ref],
                }
                continue
            if key in docs:
                entry[key] = dict(docs[key][0])
                continue
            rule = spec.row_fields.get(key)
            if rule is None:
                entry[key] = {"value": None, "citation": ""}
                continue
            kind = sources[key]
            cell, ok = finish(
                fs, evaluate(spec, rec, rule), kind, key_ref, rec.key, hints=hints,
                parse=rule.get("parse"),
            )  # fmt: skip
            if ok is not None:
                c = parse.setdefault(key, [0, 0])
                c[0] += int(ok)
                c[1] += 1
            entry[key] = cell
        entries.append(entry)
    disp = Counter(d for _ln, d in ordered)
    return Execution(
        spec=spec,
        entries=entries,
        records=records,
        keys_seen=[r.key for r in records_all],
        dispositions=disp,
        ordered=ordered,
        region_lines=sum(1 for ln, _d in ordered if not ln.blank),
        duplicates=len(records_all) - len(records),
        keyless=keyless,
        key_shape=key_shape,
        value_cols=_value_cols(spec, specs),
        parse=parse,
        field_sources=sources,
    )
