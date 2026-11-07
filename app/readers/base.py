"""Block: one addressed piece of a document (a row, a paragraph, a page text or a page image)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


class ReaderError(Exception):
    """The file could not be read. The message names the reader and error type only (R23)."""


@dataclass(frozen=True)
class Block:
    kind: str  # "text" | "image"
    address: str  # "Page 3", "Page ?", "Sheet1!A4:F4"
    text: str = ""  # text blocks: content; image blocks: empty
    page: int | None = None  # 1-based PDF page, None elsewhere
    jpeg: bytes | None = None  # image blocks only
    width: int = 0
    height: int = 0
    unit: str = "row"  # what one block is, for truncation notes: row | paragraph | page

    def render(self) -> str:
        """Text as the model sees it: '[address] text'."""
        return f"[{self.address}] {self.text}"


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_text(value: object) -> str:
    """A cell value as plain text: ints without .0, dates as ISO, None as ''."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    return " ".join(str(value).split())


def row_block(sheet: str, row_number: int, values: list[object]) -> Block | None:
    """One sheet row -> '[Sheet!A4:F4] A4=… | C4=…' (empty cells skipped); None if empty."""
    parts = []
    first = last = None
    for i, v in enumerate(values):
        t = cell_text(v)
        if not t:
            continue
        ref = f"{column_letter(i)}{row_number}"
        first = first or ref
        last = ref
        parts.append(f"{ref}={t}")
    if not parts:
        return None
    address = f"{sheet}!{first}" if first == last else f"{sheet}!{first}:{last}"
    return Block("text", address, " | ".join(parts))
