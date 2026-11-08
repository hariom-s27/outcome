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


# --- PR-72: forgiving parse with per-member salvage ---------------------------------------------

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_DECODER = json.JSONDecoder()


def _skip_ws(text: str, i: int, extra: str = "") -> int:
    while i < len(text) and (text[i].isspace() or text[i] in extra):
        i += 1
    return i


def _skip_value(text: str, i: int) -> int:
    """Index of the ',' or '}' that ends the (broken) value starting at i, depth-aware."""
    depth = 0
    in_str = esc = False
    while i < len(text):
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
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            if depth == 0:
                return i
            depth -= 1
        elif ch == "," and depth == 0:
            return i
        i += 1
    return i


def salvage_object(text: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Forgiving parse (PR-72). Strict parse first; then trailing commas removed; then each
    top-level member of the first object parsed on its own. Returns (object or None, keys whose
    value could not be parsed). One broken member never loses the others."""
    try:
        return parse_json_object(text), []
    except JSONParseError:
        pass
    if not text:
        return None, []
    fenced = [m.group(1) for m in _FENCE.finditer(text)]
    body = fenced[0] if fenced else text
    body = _TRAILING_COMMA.sub(r"\1", body)
    try:
        return parse_json_object(body), []
    except JSONParseError:
        pass
    start = body.find("{")
    if start == -1:
        return None, []
    out: dict[str, Any] = {}
    bad: list[str] = []
    i = start + 1
    while True:
        i = _skip_ws(body, i, ",")
        if i >= len(body) or body[i] == "}":
            break
        if body[i] != '"':
            j = body.find('"', i)  # junk between members: skip to the next key
            if j == -1:
                break
            i = j
            continue
        try:
            key, i = _DECODER.raw_decode(body, i)
        except ValueError:
            break
        i = _skip_ws(body, i)
        if i >= len(body) or body[i] != ":":
            bad.append(str(key))
            i = _skip_value(body, i)
            continue
        i = _skip_ws(body, i + 1)
        try:
            val, i = _DECODER.raw_decode(body, i)
            out[str(key)] = val
        except ValueError:
            bad.append(str(key))
            i = _skip_value(body, i)
    return (out or None), bad
