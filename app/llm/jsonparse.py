"""Local JSON parsing of model text (P2-05): strip code fences, take the first balanced {...}."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)


class JSONParseError(ValueError):
    pass


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Return the JSON object in `text`, or raise JSONParseError with a short reason."""
    if not text or not text.strip():
        raise JSONParseError("empty response text")
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    last_error = "no JSON object found"
    for cand in candidates:
        cand = cand.strip()
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError as exc:
            last_error = f"{exc.msg} at line {exc.lineno} column {exc.colno}"
            block = _first_balanced_object(cand)
            if block is None:
                continue
            try:
                obj = json.loads(block)
            except json.JSONDecodeError as exc2:
                last_error = f"{exc2.msg} at line {exc2.lineno} column {exc2.colno}"
                continue
        if isinstance(obj, dict):
            return obj
        last_error = f"top-level JSON is {type(obj).__name__}, not an object"
    raise JSONParseError(last_error)
