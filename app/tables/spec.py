"""Table spec grammar (P6 T-7): a closed JSON recipe, validated by code. Unknown keys -> invalid.

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
  "doc_fields": {"<field>": {"cell": "<Sheet>!B2"} | null}
}

`except_label` (fold "sum" only) sums the block's labelled lines whose label is not listed.
`map_distinct` is accepted only for a field whose description lists its allowed values
("One of: A, B, C"); every mapped value must be one of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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


def _check_rule(
    key: str, rule: Any, fields: dict[str, Any], errors: list[str]
) -> dict[str, Any] | None:
    where = f"row_fields.{key}"
    if not isinstance(rule, dict) or not rule:
        errors.append(f"{where}: must be an object")
        return None
    kinds = [k for k in rule if k in RULES]
    if len(kinds) != 1:
        errors.append(f"{where}: needs exactly one of {', '.join(RULES)}")
        return None
    kind = kinds[0]
    if kind == "col":
        extra = set(rule) - {"col", "fold", "except_label"}
        if extra:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
            return None
        fold = rule.get("fold", "first_nonempty")
        if not _letter(rule["col"]) or fold not in FOLDS:
            errors.append(f"{where}: col must be a column letter and fold one of {FOLDS}")
            return None
        out: dict[str, Any] = {"col": rule["col"], "fold": fold}
        if "except_label" in rule:
            ex = rule["except_label"]
            ok = (
                fold == "sum"
                and isinstance(ex, dict)
                and set(ex) == {"label_col", "labels"}
                and _letter(ex.get("label_col"))
                and isinstance(ex.get("labels"), list)
                and all(isinstance(x, str) for x in ex["labels"])
            )
            if not ok:
                errors.append(f"{where}: except_label needs fold sum, label_col and labels")
                return None
            out["except_label"] = {"label_col": ex["label_col"], "labels": list(ex["labels"])}
        return out
    if len(rule) != 1:
        errors.append(f"{where}: unknown keys {sorted(set(rule) - {kind})}")
        return None
    body = rule[kind]
    if kind == "section_context":
        if body is not True:
            errors.append(f"{where}: section_context must be true")
            return None
        return {"section_context": True}
    if kind == "pick_by_label":
        ok = (
            isinstance(body, dict)
            and set(body) == {"label_col", "label_text", "value_col"}
            and _letter(body.get("label_col"))
            and _letter(body.get("value_col"))
            and isinstance(body.get("label_text"), str)
            and body["label_text"].strip()
        )
        if not ok:
            errors.append(f"{where}: pick_by_label needs label_col, label_text, value_col")
            return None
        return {"pick_by_label": dict(body)}
    if kind == "derived":
        ok = (
            isinstance(body, dict)
            and set(body) == {"op", "cols"}
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
        and set(body) == {"from", "map"}
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
    """Model (or heuristic) JSON -> Spec, or None with the reasons (no document text)."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["spec must be a JSON object"]
    if "spec" in raw and isinstance(raw["spec"], dict) and len(raw) == 1:
        raw = raw["spec"]  # tolerated wrapper
    unknown = set(raw) - SPEC_KEYS
    if unknown:
        errors.append(f"unknown keys: {sorted(unknown)}")
    fields: dict[str, Any] = field_list.get("fields") or {}
    primary = next(
        (k for k, v in fields.items() if isinstance(v, dict) and v.get("primary") is True), None
    )
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
    row_fields: dict[str, dict[str, Any]] = {}
    rf = raw.get("row_fields", {})
    if not isinstance(rf, dict):
        errors.append("row_fields: an object")
        rf = {}
    for key, rule in rf.items():
        if key not in fields:
            errors.append(f"row_fields: unknown field key {key!r}")
            continue
        if rule is None:
            continue
        checked = _check_rule(key, rule, fields, errors)
        if checked is None:
            continue
        if key == primary and checked.get("col") != key_col:
            errors.append("row_fields: the primary field can only be the key_column")
            continue
        row_fields[key] = checked
    doc_fields: dict[str, str | None] = {}
    df = raw.get("doc_fields", {})
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
        cell = ref.get("cell") if isinstance(ref, dict) and set(ref) == {"cell"} else None
        if not isinstance(cell, str) or "!" not in cell:
            errors.append(f'doc_fields.{key}: {{"cell": "<Sheet>!<A1>"}} or null')
            continue
        sh, a1 = cell.rsplit("!", 1)
        sh = sh.strip("'")
        if sh not in wp.sheets or split_ref(a1) is None:
            errors.append(f"doc_fields.{key}: unknown sheet or bad cell reference")
            continue
        doc_fields[key] = f"{sh}!{a1.strip().upper().replace('$', '')}"
    if errors:
        return None, errors
    return (
        Spec(
            sheet=sheet,
            header_row=hr,
            data_first_row=first,
            data_last_row=last,
            until_blank_run=run,
            key_column=key_col,
            record_start=rs,
            record_col=record_col,
            skip=tuple(dict.fromkeys(skip)),
            row_fields=row_fields,
            doc_fields=doc_fields,
            source=source,
        ),
        [],
    )
