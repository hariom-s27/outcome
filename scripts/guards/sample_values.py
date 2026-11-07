"""Block staged text that contains a value from the sample answer files.

The answer files are loaded only inside this process. Output is file:line plus the
field name; the matched value itself is never printed. Skips cleanly when the answer
folder is absent (fresh clone, grader machine).

Flagged:
  - answer strings of 8+ characters (case-insensitive, whole-token match)
  - answer numbers with 5+ digits, in common written forms (12345, 12,345, 12345.00)

Not flagged:
  - anything under outputs/: a required deliverable that holds extracted values by design
  - a string match that EXACTLY equals a field key from sample/schemas/*.json (field names
    are schema text, not answers). Every other key and value is still checked. No allowlist
    file; the exemption is simply empty when sample/schemas is absent.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _common import files_from_argv, finish, is_given, norm, read_text

ANSWER_DIR = Path("sample") / "sample-data-output-validated"
SKIP = {"uv.lock"}  # generated; hashes and sizes only
SCHEMA_DIR = Path("sample") / "schemas"
OUTPUTS_DIR = "outputs/"
MIN_STR = 8
MIN_DIGITS = 5


def _scalars(value):
    if isinstance(value, list):
        for v in value:
            yield from _scalars(v)
    else:
        yield value


def _number_forms(x: float) -> set[str]:
    x = abs(x)
    if float(x).is_integer():
        i = int(x)
        return {str(i), f"{i:,}", f"{i}.00", f"{i:,}.00"}
    return {repr(float(x)), f"{x:,}", f"{x:.2f}", f"{x:,.2f}"}


def load_answers() -> tuple[dict[str, str], dict[str, str]] | None:
    """-> (lowercased string -> field, number text -> field), or None if no answers."""
    if not ANSWER_DIR.is_dir():
        return None
    strings: dict[str, str] = {}
    numbers: dict[str, str] = {}
    for f in sorted(ANSWER_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = data.get("entries", []) if isinstance(data, dict) else data
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            for field, fr in entry.items():
                raw = fr.get("value") if isinstance(fr, dict) else fr
                for v in _scalars(raw):
                    if isinstance(v, bool) or v is None:
                        continue
                    if isinstance(v, str):
                        s = v.strip()
                        if len(s) >= MIN_STR:
                            strings.setdefault(s.lower(), field)
                    elif isinstance(v, (int, float)):
                        digits = re.sub(r"\D", "", f"{abs(v):f}".rstrip("0").rstrip("."))
                        if len(digits) >= MIN_DIGITS:
                            for form in _number_forms(v):
                                numbers.setdefault(form, field)
    return strings, numbers


def load_field_keys(schema_dir: Path = SCHEMA_DIR) -> set[str]:
    """Field keys from every schema's `fields` object; empty set if the folder is absent."""
    keys: set[str] = set()
    if not schema_dir.is_dir():
        return keys
    for f in sorted(schema_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fields = data.get("fields") if isinstance(data, dict) else None
        if isinstance(fields, dict):
            keys.update(k for k in fields if isinstance(k, str))
    return keys


def _alternation(keys) -> str:
    return "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))


def scan(
    paths: list[str],
    strings: dict[str, str],
    numbers: dict[str, str],
    field_keys: set[str],
) -> list[str]:
    """-> problem lines (file:line + field name); matched values are never included."""
    str_re = (
        re.compile(rf"(?<![0-9A-Za-z_])({_alternation(strings)})(?![0-9A-Za-z_])", re.IGNORECASE)
        if strings
        else None
    )
    num_re = re.compile(rf"(?<![\w.,])({_alternation(numbers)})(?!\w|[.,]\d)") if numbers else None

    problems = []
    for raw in paths:
        p = norm(raw)
        if p in SKIP or is_given(p) or p.startswith(OUTPUTS_DIR):
            continue
        text = read_text(p)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            fields = set()
            if str_re:
                fields |= {
                    strings[m.group(1).lower()]
                    for m in str_re.finditer(line)
                    if m.group(1) not in field_keys
                }
            if num_re:
                fields |= {numbers[m.group(1)] for m in num_re.finditer(line)}
            for field in sorted(fields):
                problems.append(f"{p}:{n}: matches an answer value for field '{field}'")
    return problems


def main() -> int:
    answers = load_answers()
    if answers is None:
        print("sample-value scan skipped: answer folder absent")
        return 0
    strings, numbers = answers
    problems = scan(files_from_argv(), strings, numbers, load_field_keys())
    return finish(problems, "sample answer values found in staged text")


if __name__ == "__main__":
    sys.exit(main())
