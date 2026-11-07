"""The document map (P3-17): every reader turns a file into one ordered list of Blocks.

Block schema (one for all readers): block_id, kind, text, address, page, flags.
  kind     row        a sheet/CSV row            ("[Sheet1!A4:F4] A4=… | F4=…")
           table_row  a DOCX table row           (cells joined with " | ")
           paragraph  prose: a DOCX paragraph, a PDF text block
           callout    a PDF block kept whole because a vector rectangle boxes it
           image      a page with no usable text layer (grayscale JPEG for a vision model)
  address  what a citation points at: "Sheet1!A4:F4", "Page 3"; "" when unknown (DOCX, none)
  page     1-based page (PDF, DOCX estimate) or None
  flags    reader facts: header, footer, hidden_sheet, merged=A1:C1, formula_no_cache=B3,
           page_estimated, strike, text_box, image_text_risk, …

Readers never log or raise with document text (R23).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

KINDS = ("row", "table_row", "paragraph", "callout", "image")
# token-ratio class of each kind (P3-18): rows tokenise densest, prose least; images by pixels
TOKEN_CLASS = {
    "row": "row",
    "table_row": "row",
    "paragraph": "prose",
    "callout": "prose",
    "image": "image",
}


class ReaderError(Exception):
    """The file could not be read. The message names the reader and error type only (R23)."""


@dataclass(frozen=True)
class Block:
    kind: str
    address: str = ""
    text: str = ""
    page: int | None = None
    flags: tuple[str, ...] = ()
    block_id: str = ""
    jpeg: bytes | None = None  # image blocks only
    width: int = 0
    height: int = 0

    def render(self) -> str:
        """Text as the model sees it: '[address] text' ('text' alone without an address), on
        ONE line: inner line breaks become ' / ' and tabs spaces. The model copies citations
        verbatim; a raw newline copied into a JSON string makes the answer unparseable."""
        lines = (" ".join(ln.split()) for ln in self.text.splitlines())
        text = " / ".join(ln for ln in lines if ln)
        return f"[{self.address}] {text}" if self.address else text

    @property
    def token_class(self) -> str:
        return TOKEN_CLASS.get(self.kind, "other")


@dataclass
class DocMap:
    """Blocks in reading order plus document-level facts (counts and labels only)."""

    file_type: str
    blocks: list[Block]
    meta: dict[str, Any] = field(default_factory=dict)

    def result_metadata(self) -> dict[str, Any]:
        """What goes into the job result's metadata (no document text)."""
        out: dict[str, Any] = {}
        if "page_source" in self.meta:
            out["page_source"] = self.meta["page_source"]
        return out


def number_blocks(prefix: str, blocks: list[Block]) -> list[Block]:
    """Give every block a stable id in reading order: '<prefix>0001', …"""
    from dataclasses import replace

    return [replace(b, block_id=f"{prefix}{i:04d}") for i, b in enumerate(blocks, start=1)]


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


def row_block(
    sheet: str,
    row_number: int,
    cells: list[tuple[int, str]],
    flags: tuple[str, ...] = (),
) -> Block | None:
    """(column index, text) cells of one row -> '[Sheet!A4:F4] A4=… | C4=…'; None if empty.
    A cell whose text is None-like ('') is skipped unless the row is kept for its flags."""
    parts = []
    first = last = None
    for i, t in cells:
        ref = f"{column_letter(i)}{row_number}"
        if not t and not any(f.endswith("=" + ref) for f in flags):
            continue
        first = first or ref
        last = ref
        parts.append(f"{ref}={t}")
    if not parts:
        return None
    address = f"{sheet}!{first}" if first == last else f"{sheet}!{first}:{last}"
    return Block("row", address, " | ".join(parts), flags=flags)
