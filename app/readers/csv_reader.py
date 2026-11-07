"""CSV -> one block per non-empty row, refs as Sheet1!A1 (the contract's citation style)."""

from __future__ import annotations

import csv
import io

from app.readers.base import Block, ReaderError, row_block

SHEET = "Sheet1"


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")  # never fails: every byte maps


def read_csv(content: bytes) -> list[Block]:
    text = _decode(content)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error as exc:
        raise ReaderError(f"csv reader: {type(exc).__name__}") from exc
    blocks = []
    for n, row in enumerate(rows, start=1):
        b = row_block(SHEET, n, list(row))
        if b is not None:
            blocks.append(b)
    return blocks
