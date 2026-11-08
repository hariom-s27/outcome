"""Table spec grammar (P6 T-7): a closed JSON recipe, validated by code. Unknown keys -> invalid
(P9g SPEC_RETRY_FEEDBACK: unknown extra keys inside an otherwise valid entry are ignored).

{
  "sheet": "<sheet name>",
  "header_row": 4 | null,
  "data_first_row": 5,
  "data_last_row": 900 | null,          # or
  "until_blank_run": 3 | null,          # stop at the first run of this many blank rows
  "key_column": "A",
  "record_start": "key_nonempty" | "key_matches_shape" | "column_nonempty:<letter>",
  "skip": ["total_like", "header_repeat", "blank", "formula_sum_rows", "section_header",
           "no_amount"],                # no_amount: a record line with no number but its key
  "row_fields": {
    "<field>": {"col": "C", "fold": "first_nonempty" | "sum" | "last_nonempty"},
    "<field>": {"col": "F", "fold": "sum",
                "except_label": {"label_col": "D", "labels": ["<label as printed>"]}},
    "<field>": {"pick_by_label": {"label_col": "D", "label_text": "<text>", "value_col": "F"}},
    "<field>": {"section_context": true},
    "<field>": {"derived": {"op": "count_nonzero" | "sum", "cols": ["C", "D"]}},
    "<field>": {"map_distinct": {"from": "<letter>" | "section_context",
                                 "map": {"<distinct value>": "<allowed value>"}}}
  },
  "doc_fields": {"<field>": {"cell": "<Sheet>!B2"} | {"cell": "<Sheet>!B2", "parse": "<p>"} | null}
}

`except_label` (fold "sum" only) sums the block's labelled lines whose label is not listed.
`map_distinct` is accepted only for a field whose description lists its allowed values
("One of: A, B, C"); every mapped value must be one of them.
`parse` (P8b Z-2) reads a value out of a cell's text through the normaliser: date_start /
date_end take the first / last date of a range ("Week of <d1> - <d2>"), date uses the field's
own date role, number / text read the cell as that type. Allowed on doc_fields entries and on
row rules that read one cell (col with a first/last fold, pick_by_label); the parse must fit
the field's compiled type (date_* and date: date or month fields; number: numeric fields;
text: text fields). An unparseable cell gives null, never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.extract.compile_fields import compile_fields
from app.tables.profile import WorkbookProfile, split_ref

SPEC_KEYS = frozenset(
    {
        "sheet",
        "header_row",
        "data_first_row",
        "data_last_row",
        "until_blank_run",
        "key_column",
        "record_start",
        "skip",
        "row_fields",
        "doc_fields",
    }
)
SKIPS = (
    "total_like",
    "header_repeat",
    "blank",
    "formula_sum_rows",
    "section_header",
    "no_amount",
)
FOLDS = ("first_nonempty", "sum", "last_nonempty")
DERIVED_OPS = ("count_nonzero", "sum")
RULES = ("col", "pick_by_label", "section_context", "derived", "map_distinct")
PARSES = ("date_start", "date_end", "date", "number", "text")
PARSE_TYPES = {
    "date_start": ("date", "month"),
    "date_end": ("date", "month"),
    "date": ("date", "month"),
    "number": ("number", "integer", "percent"),
    "text": ("text", "free_text", "code"),
}
COL_KEYS = frozenset({"col", "fold", "except_label", "parse"})
EXCEPT_KEYS = frozenset({"label_col", "labels"})
PICK_KEYS = frozenset({"label_col", "label_text", "value_col"})
DERIVED_KEYS = frozenset({"op", "cols"})
MAP_KEYS = frozenset({"from", "map"})
# P9g: words of the grammar itself; an unknown key outside these (and the field keys) is
# reported in metadata as "other", never by name (a model-made key could echo document text)
GRAMMAR_WORDS = (
    SPEC_KEYS | COL_KEYS | EXCEPT_KEYS | PICK_KEYS | DERIVED_KEYS | MAP_KEYS
    | set(RULES) | {"cell", "spec", "fields", "row_field", "doc_field"}
)  # fmt: skip
_LETTER = re.compile(r"^[A-Z]{1,3}$")
_ONE_OF = re.compile(r"\bone of\s*:?\s*([^.;]+)", re.IGNORECASE)
MAX_BLANK_RUN = 50


@dataclass(frozen=True)
class Spec:
    sheet: str
    data_first_row: int
    key_column: str
    record_start: str  # key_nonempty | key_matches_shape | column_nonempty
    record_col: str | None = None
    header_row: int | None = None
    data_last_row: int | None = None
    until_blank_run: int | None = None
    skip: tuple[str, ...] = ()
    row_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    doc_fields: dict[str, str | None] = field(default_factory=dict)  # field -> "Sheet!B2"
    source: str = "ai"  # ai | heuristic
    doc_parse: dict[str, str] = field(default_factory=dict)  # field -> PARSES (Z-2)


def allowed_values(description: str) -> list[str]:
    """'One of: Revenue, Expense, Other.' -> ['Revenue', 'Expense', 'Other']; [] if none."""
    m = _ONE_OF.search(description or "")
    if not m:
        return []
    parts = re.split(r",|\bor\b|/", m.group(1))
    return [p.strip(" '\"") for p in parts if p.strip(" '\"")]


def _letter(v: Any) -> bool:
    return isinstance(v, str) and bool(_LETTER.match(v))


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_parse(where: str, parse: Any, ftype: str | None, errors: list[str]) -> str | None:
    """Z-2: a parse kind that fits the field's compiled type, else an error (entry dropped)."""
    if parse not in PARSES:
        errors.append(f"{where}: parse must be one of {PARSES}")
        return None
    if ftype not in PARSE_TYPES[parse]:
        errors.append(f"{where}: parse {parse} does not fit the field's type")
        return None
    return parse


def _keys_ok(
    body: dict[str, Any], need: frozenset[str], where: str, ignored: list[str] | None
) -> bool:
    """Exactly the `need` keys; or (P9g lenient, `ignored` given) at least them, with every
    extra key ignored and recorded as '<where>.<key>'."""
    have = set(body)
    if have == need:
        return True
    if ignored is not None and need <= have:
        ignored.extend(f"{where}.{k}" for k in sorted(have - need))
        return True
    return False


def _check_rule(
    key: str,
    rule: Any,
    fields: dict[str, Any],
    errors: list[str],
    ftype: str | None = None,
    ignored: list[str] | None = None,
) -> dict[str, Any] | None:
    """`ignored` None = strict (v1.0); a list = P9g lenient: unknown extra keys are ignored
    (recorded there), every required key and value check is unchanged."""
    where = f"row_fields.{key}"
    if not isinstance(rule, dict) or not rule:
        errors.append(f"{where}: must be an object")
        return None
    kinds = [k for k in rule if k in RULES]
    if len(kinds) != 1:
        errors.append(f"{where}: needs exactly one of {', '.join(RULES)}")
        return None
    kind = kinds[0]
    parse = None
    if "parse" in rule:
        if kind not in ("col", "pick_by_label") or rule.get("fold") == "sum":
            errors.append(f"{where}: parse only on col (first/last fold) or pick_by_label")
            return None
        parse = check_parse(where, rule["parse"], ftype, errors)
        if parse is None:
            return None
    if kind == "col":
        extra = set(rule) - COL_KEYS
        if extra and ignored is None:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
            return None
        if extra and ignored is not None:
            ignored.extend(f"{where}.{k}" for k in sorted(extra))
        fold = rule.get("fold", "first_nonempty")
        if not _letter(rule["col"]) or fold not in FOLDS:
            errors.append(f"{where}: col must be a column letter and fold one of {FOLDS}")
            return None
        out: dict[str, Any] = {"col": rule["col"], "fold": fold}
        if parse:
            out["parse"] = parse
        if "except_label" in rule:
            ex = rule["except_label"]
            ok = (
                fold == "sum"
                and isinstance(ex, dict)
                and _keys_ok(ex, EXCEPT_KEYS, f"{where}.except_label", ignored)
                and _letter(ex.get("label_col"))
                and isinstance(ex.get("labels"), list)
                and all(isinstance(x, str) for x in ex["labels"])
            )
            if not ok:
                errors.append(f"{where}: except_label needs fold sum, label_col and labels")
                return None
            out["except_label"] = {"label_col": ex["label_col"], "labels": list(ex["labels"])}
        return out
    if len(rule) != 1 + (parse is not None):
        extra = set(rule) - {kind, "parse"}
        if ignored is None:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
            return None
        ignored.extend(f"{where}.{k}" for k in sorted(extra))
    body = rule[kind]
    if kind == "section_context":
        if body is not True:
            errors.append(f"{where}: section_context must be true")
            return None
        return {"section_context": True}
    if kind == "pick_by_label":
        ok = (
            isinstance(body, dict)
            and _keys_ok(body, PICK_KEYS, f"{where}.pick_by_label", ignored)
            and _letter(body.get("label_col"))
            and _letter(body.get("value_col"))
            and isinstance(body.get("label_text"), str)
            and body["label_text"].strip()
        )
        if not ok:
            errors.append(f"{where}: pick_by_label needs label_col, label_text, value_col")
            return None
        pick = {k: body[k] for k in ("label_col", "label_text", "value_col")}
        return {"pick_by_label": pick, **({"parse": parse} if parse else {})}
    if kind == "derived":
        ok = (
            isinstance(body, dict)
            and _keys_ok(body, DERIVED_KEYS, f"{where}.derived", ignored)
            and body.get("op") in DERIVED_OPS
            and isinstance(body.get("cols"), list)
            and body["cols"]
            and all(_letter(c) for c in body["cols"])
        )
        if not ok:
            errors.append(f"{where}: derived needs op in {DERIVED_OPS} and a list of cols")
            return None
        return {"derived": {"op": body["op"], "cols": list(body["cols"])}}
    # map_distinct
    allowed = allowed_values(str((fields.get(key) or {}).get("description") or ""))
    if not allowed:
        errors.append(f"{where}: map_distinct only for a field that lists its allowed values")
        return None
    ok = (
        isinstance(body, dict)
        and _keys_ok(body, MAP_KEYS, f"{where}.map_distinct", ignored)
        and (_letter(body.get("from")) or body.get("from") == "section_context")
        and isinstance(body.get("map"), dict)
    )
    if not ok:
        errors.append(f"{where}: map_distinct needs from (letter or section_context) and map")
        return None
    canon = {a.casefold(): a for a in allowed}
    mapping: dict[str, str] = {}
    for src, dst in body["map"].items():
        if not isinstance(dst, str) or dst.strip().casefold() not in canon:
            errors.append(f"{where}: map value not among the allowed values")
            return None
        mapping[str(src)] = canon[dst.strip().casefold()]
    return {"map_distinct": {"from": body["from"], "map": mapping}}


def validate_spec(
    raw: Any, field_list: dict[str, Any], wp: WorkbookProfile, source: str = "ai"
) -> tuple[Spec | None, list[str]]:
    """Strict: model (or heuristic) JSON -> Spec, or None with the reasons (no document text).
    Any error (core or entry) makes the spec invalid."""
    spec, core_errors, entry_errors = salvage_spec(raw, field_list, wp, source)
    errors = core_errors + entry_errors
    return (None, errors) if errors else (spec, [])


def salvage_spec(
    raw: Any,
    field_list: dict[str, Any],
    wp: WorkbookProfile,
    source: str = "ai",
    *,
    report: dict[str, list[str]] | None = None,
) -> tuple[Spec | None, list[str], list[str]]:
    """P6b B-3 per-entry salvage: (spec, core errors, dropped-entry errors).

    The core (sheet, header_row, data rows, until_blank_run, key_column, record_start, skip)
    must be valid, else spec is None. Each row_fields / doc_fields entry is checked on its
    own; a bad entry is dropped with its reason and the rest of the spec is kept. Unknown
    top-level keys are dropped too (reported with the entries).

    `report` (P9g SPEC_RETRY_FEEDBACK; None = v1.0 strict): lenient entry keys. An unknown
    extra key inside an entry is ignored and the entry kept when every other check passes;
    report["ignored"] gets '<entry>.<key>' and report["top_unknown"] the unknown top-level
    key names (top-level handling itself is unchanged). For the retry prompt only."""
    if not isinstance(raw, dict):
        return None, ["spec must be a JSON object"], []
    if "spec" in raw and isinstance(raw["spec"], dict) and len(raw) == 1:
        raw = raw["spec"]  # tolerated wrapper
    core = _check_core(raw, wp)
    errors: list[str] = []  # entry level
    unknown = set(raw) - SPEC_KEYS
    if unknown:
        errors.append(f"unknown keys: {sorted(unknown)}")
    ignored: list[str] | None = None
    if report is not None:
        ignored = report.setdefault("ignored", [])
        report.setdefault("top_unknown", []).extend(sorted(unknown))
    key_col = raw.get("key_column")
    row_fields, doc_fields, doc_parse = _check_entries(
        raw, field_list, wp, key_col, errors, ignored
    )
    if core.errors:
        return None, core.errors, errors
    return (
        Spec(
            sheet=raw["sheet"],
            header_row=raw.get("header_row"),
            data_first_row=raw["data_first_row"],
            data_last_row=raw.get("data_last_row"),
            until_blank_run=raw.get("until_blank_run"),
            key_column=key_col,
            record_start=core.record_start,
            record_col=core.record_col,
            skip=tuple(dict.fromkeys(core.skip)),
            row_fields=row_fields,
            doc_fields=doc_fields,
            source=source,
            doc_parse=doc_parse,
        ),
        [],
        errors,
    )


@dataclass
class _Core:
    errors: list[str]
    record_start: str = ""
    record_col: str | None = None
    skip: list[str] = field(default_factory=list)


def _check_core(raw: dict[str, Any], wp: WorkbookProfile) -> _Core:
    errors: list[str] = []
    sheet = raw.get("sheet")
    if not isinstance(sheet, str) or sheet not in wp.sheets:
        errors.append("sheet: must name one of the workbook's sheets")
    hr = raw.get("header_row")
    if hr is not None and not (_int(hr) and hr >= 1):
        errors.append("header_row: a row number or null")
    first = raw.get("data_first_row")
    if not (_int(first) and first >= 1):
        errors.append("data_first_row: a row number")
    last = raw.get("data_last_row")
    if last is not None and not (_int(last) and _int(first) and last >= first):
        errors.append("data_last_row: a row number >= data_first_row, or null")
    run = raw.get("until_blank_run")
    if run is not None and not (_int(run) and 1 <= run <= MAX_BLANK_RUN):
        errors.append(f"until_blank_run: 1..{MAX_BLANK_RUN} or null")
    key_col = raw.get("key_column")
    if not _letter(key_col):
        errors.append("key_column: a column letter")
    rs = raw.get("record_start")
    record_col = None
    if isinstance(rs, str) and rs.startswith("column_nonempty:"):
        record_col = rs.split(":", 1)[1]
        if not _letter(record_col):
            errors.append("record_start: column_nonempty:<letter>")
        rs = "column_nonempty"
    elif rs not in ("key_nonempty", "key_matches_shape"):
        errors.append("record_start: key_nonempty | key_matches_shape | column_nonempty:<letter>")
    skip = raw.get("skip", [])
    if not isinstance(skip, list) or any(s not in SKIPS for s in skip):
        errors.append(f"skip: a list of {SKIPS}")
        skip = []
    return _Core(errors, rs if isinstance(rs, str) else "", record_col, list(skip))


def _check_entries(
    raw: dict[str, Any],
    field_list: dict[str, Any],
    wp: WorkbookProfile,
    key_col: Any,
    errors: list[str],
    ignored: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str | None], dict[str, str]]:
    """Each row_fields / doc_fields entry on its own; bad ones go to `errors` and are left out.
    `ignored` given = P9g lenient entry keys (see salvage_spec)."""
    fields: dict[str, Any] = field_list.get("fields") or {}
    types = {k: fs.type for k, fs in compile_fields(field_list).items()}
    primary = next(
        (k for k, v in fields.items() if isinstance(v, dict) and v.get("primary") is True), None
    )
    row_fields: dict[str, dict[str, Any]] = {}
    rf = raw.get("row_fields", {})
    if rf is None:
        rf = {}
    if not isinstance(rf, dict):
        errors.append("row_fields: an object")
        rf = {}
    for key, rule in rf.items():
        if key not in fields:
            errors.append(f"row_fields: unknown field key {key!r}")
            continue
        if rule is None:
            continue
        local: list[str] | None = None if ignored is None else []
        checked = _check_rule(key, rule, fields, errors, types.get(key), local)
        if checked is None:
            continue
        if key == primary and checked.get("col") != key_col:
            errors.append("row_fields: the primary field can only be the key_column")
            continue
        row_fields[key] = checked
        if ignored is not None and local:  # counted only for entries actually kept
            ignored.extend(local)
    doc_fields: dict[str, str | None] = {}
    doc_parse: dict[str, str] = {}
    df = raw.get("doc_fields", {})
    if df is None:
        df = {}
    if not isinstance(df, dict):
        errors.append("doc_fields: an object")
        df = {}
    for key, ref in df.items():
        if key not in fields:
            errors.append(f"doc_fields: unknown field key {key!r}")
            continue
        if key in row_fields:
            errors.append(f"doc_fields: {key!r} is also a row field")
            continue
        if key == primary:
            errors.append("doc_fields: the primary field is a row field")
            continue
        if ref is None:
            doc_fields[key] = None
            continue
        shape_ok = isinstance(ref, dict) and set(ref) in ({"cell"}, {"cell", "parse"})
        extra_ref: list[str] = []
        if not shape_ok and ignored is not None and isinstance(ref, dict) and "cell" in ref:
            extra_ref = [f"doc_fields.{key}.{k}" for k in sorted(set(ref) - {"cell", "parse"})]
            shape_ok = True  # P9g lenient: extra keys ignored, cell (+ parse) still checked
        cell = ref.get("cell") if shape_ok else None
        if not isinstance(cell, str) or "!" not in cell:
            errors.append(f'doc_fields.{key}: {{"cell": "<Sheet>!<A1>"[, "parse": ...]}} or null')
            continue
        sh, a1 = cell.rsplit("!", 1)
        sh = sh.strip("'")
        if sh not in wp.sheets or split_ref(a1) is None:
            errors.append(f"doc_fields.{key}: unknown sheet or bad cell reference")
            continue
        if "parse" in ref:
            parse = check_parse(f"doc_fields.{key}", ref["parse"], types.get(key), errors)
            if parse is None:
                continue
            doc_parse[key] = parse
        doc_fields[key] = f"{sh}!{a1.strip().upper().replace('$', '')}"
        if ignored is not None and extra_ref:
            ignored.extend(extra_ref)
    return row_fields, doc_fields, doc_parse
