"""Rule-based field compiler (P5-05) and the single-value path rule (P5-04).

From the field list only (key, display name, description, the contract's `primary` flag) it
derives a FieldSpec per field: value type, list item type, date role, computed-candidate flag,
and generic null / format rule text for the prompt. Deterministic, no LLM, no document text,
no keyword fitted to a sample document. Unknown or odd fields fall back to free text.

Type rules, first match wins (P5 brief, Part C):
  1 explicit format hints in the description ("YYYY-MM-DD", "true if", "list of",
    "as a number", "whole number", "percentage", "four-digit year", "short phrase", ...)
  2 code-like nouns -> code        3 year nouns -> year        4 percent nouns -> percent
  5 count nouns -> integer         6 money / area nouns -> number
  7 date nouns -> date; month / period -> month
  8 "whether / is / has / does" -> boolean
  9 "list of / all ... names" -> list
  10 short categorical phrase -> text          11 otherwise free_text
Rules 2-9 look at the field's name (key + display name) first; only when the name says
nothing do they look at the description.

Path rule (P5-04): a field list is single-value unless a field carries the contract's
`"primary": true` marker (contract/README: table lists mark exactly one primary column).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.extract.normalise import TYPES

_CACHE_MAX = 64
_cache: OrderedDict[str, dict[str, FieldSpec]] = OrderedDict()


@dataclass(frozen=True)
class FieldSpec:
    key: str
    name: str
    description: str
    type: str  # one of normalise.TYPES
    item_type: str | None = None  # list fields only
    date_role: str | None = None  # date / month fields: start | end | period_end | None
    computed: bool = False  # description asks for a total / ratio / months-between ...
    primary: bool = False
    null_rule: str = ""
    format_rule: str = ""
    rule: str = ""  # which compiler rule set the type (for tests and metadata)


# --- rule patterns (generic CRE / document vocabulary, never sample-document content) ---------


def _rx(*alts: str) -> re.Pattern[str]:
    return re.compile("|".join(alts), re.I)


_HINT_DATE = _rx(r"yyyy-mm-dd", r"mm/dd/yyyy", r"dd/mm/yyyy", r"\bas an? (?:iso )?date\b")
_HINT_MONTH = _rx(r"yyyy-mm(?!-dd)", r"\bmonth and year\b", r"\bas a month\b")
_HINT_YEAR = _rx(r"four[- ]digit year", r"\byyyy\b(?!-)", r"\bas a year\b")
_HINT_BOOL = _rx(
    r"\btrue if\b", r"\btrue or false\b", r"\btrue/false\b", r"\byes or no\b", r"\by/n\b"
)
_HINT_LIST = _rx(r"^\s*(?:a |the )?list\b", r"\blist of\b", r"\bas a list\b", r"\bjson array\b")
_HINT_INT = _rx(r"\bwhole number\b", r"\binteger\b", r"\bwhole months\b", r"\bcount of\b")
_HINT_PCT = _rx(r"\bpercentage\b", r"\bas a percent\b", r"\bpercent number\b")
_HINT_NUM = _rx(
    r"\bas a number\b",
    r"\bplain number\b",
    r"\bnumbers? only\b",
    r"\bnumber with no\b",
    r"\bas a numeric\b",
    r"\bnumeric value\b",
)
_HINT_SHORT = _rx(r"\bshort phrase\b", r"\bone or two words\b", r"\bcategory\b", r"\bone of\b")
_HINT_FREE = _rx(
    r"\bsentence\b",
    r"\bdescribe\b",
    r"\bas the \w+ states it\b",
    r"\bas (?:it is )?written\b",
    r"\bas stated\b",
    r"\bverbatim\b",
    r"\bin words\b",
)

_N_CODE = _rx(
    r"\bcode\b",
    r"\bzip\b",
    r"\bpostal\b",
    r"\bgl\b",
    r"\baccount (?:number|no\.?|#)",
    r"\bidentifier\b",
    r"\bid\b",
    r"\bparcel\b",
    r"\bapn\b",
    r"\bsku\b",
    r"\bphone\b",
    r"\bunit (?:number|no\.?|#)",
    r"\bsuite (?:number|no\.?|#)",
)
_N_YEAR = _rx(r"\bbase year\b", r"\byear built\b", r"\byear renovated\b", r"\byear\b(?!s)")
_N_PCT = _rx(
    r"%",
    r"\bpercent\b",
    r"\bpct\b",
    r"\brate\b",
    r"\boccupancy\b",
    r"\bvacancy\b",
    r"\bmargin\b",
    r"\byield\b",
    r"\bratio\b",
)
_N_COUNT = _rx(
    r"\bnumber of\b",
    r"\bcount\b",
    r"\bhow many\b",
    r"\b(?:units|spaces|stalls|beds|floors|stories|keys|rooms|options)\b",
    r"\(months\)",
    r"\bmonths\b",
    r"\bin months\b",
)
_N_MONEY = _rx(
    r"\brent\b",
    r"\bprice\b",
    r"\bamount\b",
    r"\bcost\b",
    r"\bdeposit\b",
    r"\ballowance\b",
    r"\bcharge\b",
    r"\bfee\b",
    r"\bincome\b",
    r"\brevenue\b",
    r"\bexpenses?\b",
    r"\btax(?:es)?\b",
    r"\bvalue\b",
    r"\bbudget\b",
    r"\bactual\b",
    r"\bvariance\b",
    r"\bbalance\b",
    r"\bnoi\b",
    r"\bdollars?\b",
    r"\$",
    r"\bsquare (?:feet|footage)\b",
    r"\bsq\.? ?ft\b",
    r"\b[rsu]?sf\b",
    r"\bfootage\b",
    r"\barea\b",
    r"\bacres?\b",
    r"\btotal\b",
)
_N_DATE = _rx(
    r"\bdates?\b",
    r"\bdated\b",
    r"\bcommencement\b",
    r"\bexpiration\b",
    r"\bexpiry\b",
    r"\bas of\b",
    r"\beffective\b",
    r"\bday\b",
)
_N_MONTH = _rx(r"\bmonth\b(?!ly)", r"\bperiod\b")
_N_BOOL = _rx(r"^\s*whether\b", r"^\s*(?:is|has|does|are|can|was)\b", r"\bexists?\b", r"\?\s*$")
_N_LIST = _rx(r"\ball\b.*\bnames\b", r"\bnames of all\b", r"\beach\b.*\bin order\b")
_N_CATEGORICAL = _rx(r"\be\.g\.", r"\bsuch as\b", r"\btype\b", r"\bstatus\b", r"\bclass\b")

_COMPUTED = _rx(
    r"\btotal\b",
    r"\bsum\b",
    r"\bper\b",
    r"\bannual\w*\b.*\bmonthly\b",
    r"\bmonthly\b.*\b(?:times|x) ?12\b",
    r"\bmonths between\b",
    r"\bterm in months\b",
    r"\bfrom commencement to expiration\b",
    r"\bafter (?:an? |any |the )?abatement\b",
    r"\bcompute\b",
    r"\bcalculate\b",
)

_COMPUTABLE = ("number", "integer", "percent", "date", "month", "year")

_ROLE_PERIOD_END = _rx(
    r"\bend (?:date )?of the (?:\w+ )?period\b",
    r"\bperiod end",
    r"\bperiod ending\b",
    r"\bmonth[- ]end\b",
    r"\bend date of the\b",
)
_ROLE_END = _rx(
    r"\bend\b", r"\bending\b", r"\bexpir", r"\bthrough\b", r"\blast day\b", r"\bterminat"
)
_ROLE_START = _rx(r"\bstart", r"\bbegin", r"\bcommence", r"\bfirst day\b", r"\beffective\b")
_NULL_SENTENCE = re.compile(r"[^.]*\b(?:null|empty list|0 if none|none if|n/a)\b[^.]*\.?", re.I)

_FORMAT_RULES = {
    "date": "ISO date YYYY-MM-DD. Never fill a missing day, month or year.",
    "month": "Year and month as YYYY-MM.",
    "year": "Four-digit year as a JSON number.",
    "number": "JSON number: no currency symbol, no thousands separators; (1,234) is negative; "
    "apply a scale only when it is attached ($3.4M).",
    "integer": "Whole JSON number.",
    "percent": "The number as printed: 5.26 for '5.26%'.",
    "boolean": "true or false.",
    "list": "JSON array, one item per entry, in document order; [] if none.",
    "code": "String exactly as printed; keep leading zeros and dashes.",
    "text": "Short verbatim phrase from the document, labels trimmed.",
    "free_text": "Verbatim wording from the document, labels and cross-references trimmed.",
}
_NULL_RULES = {
    "boolean": "false when the document is complete and grants nothing; null only when the "
    "relevant part is missing or unreadable.",
}
_DEFAULT_NULL = "null when the document does not state it. Never guess."


# --- compiler --------------------------------------------------------------------------------


def _first_type(text: str, *, explicit: bool) -> tuple[str, str] | None:
    """Return (type, rule id) from one text, or None."""
    if explicit:
        for rx, t, rid in (
            (_HINT_LIST, "list", "1:list"),
            (_HINT_BOOL, "boolean", "1:boolean"),
            (_HINT_DATE, "date", "1:date"),
            (_HINT_MONTH, "month", "1:month"),
            (_HINT_YEAR, "year", "1:year"),
            (_HINT_PCT, "percent", "1:percent"),
            (_HINT_INT, "integer", "1:integer"),
            (_HINT_NUM, "number", "1:number"),
            (_HINT_SHORT, "text", "1:text"),
            (_HINT_FREE, "free_text", "1:free_text"),
        ):
            if rx.search(text):
                return t, rid
        return None
    for rx, t, rid in _NOUN_RULES:
        if rx.search(text):
            return t, rid
    return None


_NOUN_RULES = (
    (_N_CODE, "code", "2:code"),
    (_N_YEAR, "year", "3:year"),
    (_N_PCT, "percent", "4:percent"),
    (_N_COUNT, "integer", "5:integer"),
    (_N_MONEY, "number", "6:number"),
    (_N_DATE, "date", "7:date"),
    (_N_MONTH, "month", "7:month"),
    (_N_BOOL, "boolean", "8:boolean"),
    (_N_LIST, "list", "9:list"),
)
_UNIT_PAREN = (
    (_rx(r"^\s*(?:months?|years?|days?|weeks?|#|count|no\.?)\s*$"), "integer", "5:integer"),
    (_rx(r"^\s*(?:%|percent|pct)\s*$"), "percent", "4:percent"),
    (_rx(r"^\s*(?:\$|usd|dollars|[rsu]?sf|sq\.? ?ft|\$/sf|psf)\s*$"), "number", "6:number"),
)


def _name_type(name: str) -> tuple[str, str] | None:
    """Rules 2-9 on a field name. A unit in parentheses ('(months)', '(%)') decides; else the
    head noun wins: the LAST rule match in the name ('Rent Commencement Date' is a date), ties
    broken by rule order. Other parentheticals ('Base Year (Taxes)') are qualifiers, ignored."""
    for paren in re.findall(r"\(([^)]*)\)", name):
        for rx, t, rid in _UNIT_PAREN:
            if rx.search(paren):
                return t, rid
    base = re.sub(r"\([^)]*\)", " ", name)
    best: tuple[int, int, str, str] | None = None  # (-start, order, type, rule)
    for order, (rx, t, rid) in enumerate(_NOUN_RULES):
        for m in rx.finditer(base):
            cand = (-m.start(), order, t, rid)
            if best is None or cand < best:
                best = cand
    return (best[2], best[3]) if best else None


def _item_type(desc: str, name: str) -> str:
    """Type of one list item: the name's head noun first ('Start Dates'), then the explicit
    hints and nouns of the description text after 'list of'."""
    hit = _name_type(name)
    if hit and hit[0] not in ("list", "boolean"):
        return hit[0]
    tail = re.split(r"\blist of\b", desc, maxsplit=1, flags=re.I)[-1]
    for explicit in (True, False):
        hit = _first_type(tail, explicit=explicit)
        if hit and hit[0] not in ("list", "boolean"):
            return hit[0]
    return "text"


def _date_role(text: str) -> str | None:
    if _ROLE_PERIOD_END.search(text):
        return "period_end"
    if _ROLE_END.search(text):
        return "end"
    if _ROLE_START.search(text):
        return "start"
    return None


def _is_primary(field: Any) -> bool:
    if not isinstance(field, dict):
        return False
    p = field.get("primary")
    return p is True or (isinstance(p, str) and p.strip().lower() == "true")


def compile_field(key: str, field: Any) -> FieldSpec:
    f = field if isinstance(field, dict) else {}
    name = str(f.get("name") or "")
    desc = str(f.get("description") or "")
    label = name.strip() or key.replace("_", " ")

    hit = _first_type(desc, explicit=True)
    if hit is None:
        hit = (
            _name_type(label)
            or (_name_type(key.replace("_", " ")) if name.strip() else None)
            or _first_type(desc, explicit=False)
        )
    if hit is None:
        hit = ("text", "10:text") if _N_CATEGORICAL.search(desc) else ("free_text", "11:free_text")
    type_, rid = hit
    if type_ not in TYPES:  # defensive: never emit a type the normaliser lacks
        type_, rid = "free_text", "11:free_text"

    item_type = _item_type(desc, label) if type_ == "list" else None
    role_type = item_type if type_ == "list" else type_
    role = _date_role(f"{label} {desc}") if role_type in ("date", "month") else None
    nulls = _NULL_SENTENCE.findall(desc)
    null_rule = " ".join(s.strip() for s in nulls) or _NULL_RULES.get(type_, _DEFAULT_NULL)
    fmt = _FORMAT_RULES[type_]
    if type_ == "list" and item_type:
        fmt = f"{fmt} Each item: {_FORMAT_RULES.get(item_type, _FORMAT_RULES['text'])}"
    return FieldSpec(
        key=key,
        name=name,
        description=desc,
        type=type_,
        item_type=item_type,
        date_role=role,
        # only numbers and dates are computed (text that says "per annum" is not arithmetic)
        computed=role_type in _COMPUTABLE and bool(_COMPUTED.search(desc)),
        primary=_is_primary(field),
        null_rule=null_rule,
        format_rule=fmt,
        rule=rid,
    )


def field_list_hash(field_list: Any) -> str:
    raw = json.dumps(field_list, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fields(field_list: Any) -> dict[str, Any]:
    fields = field_list.get("fields") if isinstance(field_list, dict) else None
    return fields if isinstance(fields, dict) else {}


def compile_fields(field_list: Any) -> dict[str, FieldSpec]:
    """FieldSpec per key, in field-list order; cached by the hash of the field list."""
    h = field_list_hash(field_list)
    if h in _cache:
        _cache.move_to_end(h)
        return dict(_cache[h])
    specs = {str(k): compile_field(str(k), v) for k, v in _fields(field_list).items()}
    _cache[h] = specs
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return dict(specs)


def is_single_value(field_list: Any) -> bool:
    """P5-04: single-value (one entry per document) unless a field is marked primary."""
    return not any(_is_primary(f) for f in _fields(field_list).values())
