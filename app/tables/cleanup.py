"""P9c Z-51 table cleanup (TABLE_CLEANUP, default off): two general rules on code-copied rows.

Applied to the spec path's final entries (spreadsheets and the PDF grid) after the recipe is
chosen, so recipe choice and checks are unchanged.

1. placeholder -> null: a non-key text field (text / free_text / code) whose WHOLE cell is a
   generic placeholder (vacant, vacancy, unoccupied, n/a, none, tbd, a lone dash; any case)
   becomes null. Only whole cells: "Vacant since May" stays as printed.
2. continued section labels: a field filled from the nearest section label (the
   `section_context` rule) loses a trailing "(continued)" / "(cont.)" / "continued", the
   marker a label carries when it is repeated at the top of a new page.

No document's labels or values; counts only in metadata. Nothing here logs (R23).
"""

from __future__ import annotations

import re
from typing import Any

from app.extract.compile_fields import compile_fields

TEXT_TYPES = ("text", "free_text", "code")
PLACEHOLDERS = frozenset({"vacant", "vacancy", "unoccupied", "n/a", "none", "tbd"})
DASHES = frozenset({"-", "--", "–", "—", "−", "‒"})
_CONTINUED = re.compile(
    r"\s*(?:[-–—:,]\s*)?(?:\(\s*(?:continued|cont\.?)\s*\)|\bcontinued)\s*$", re.IGNORECASE
)


def is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    t = " ".join(value.split()).casefold()
    return t in PLACEHOLDERS or t in DASHES


def strip_continued(value: str) -> str:
    """'Repairs (continued)' -> 'Repairs'; a label that is only the marker is kept as is."""
    out = _CONTINUED.sub("", value).rstrip(" -–—:,")
    return out if out.strip() else value


def clean_entries(
    entries: list[dict[str, Any]],
    field_list: dict[str, Any],
    field_sources: dict[str, str],
    null_confidence: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """-> (cleaned entries, counts). field_sources: field -> rule kind of the chosen spec."""
    specs = compile_fields(field_list)
    text_keys = {k for k, fs in specs.items() if not fs.primary and fs.type in TEXT_TYPES}
    section_keys = {k for k, src in field_sources.items() if src == "section_context"}
    counts = {"placeholder_nulls": 0, "section_suffixes": 0}
    out = []
    for e in entries:
        row = {}
        for k, cell in e.items():
            c = dict(cell)
            v = c.get("value")
            if k in text_keys and is_placeholder(v):
                c = {"value": None, "citation": "", "confidence": null_confidence}
                counts["placeholder_nulls"] += 1
            elif k in section_keys and isinstance(v, str):
                stripped = strip_continued(v)
                if stripped != v:
                    c["value"] = stripped
                    counts["section_suffixes"] += 1
            row[k] = c
        out.append(row)
    return out, counts
