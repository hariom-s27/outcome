"""CSV -> one row block per non-empty row, refs Sheet1!A1 (the contract's citation style).

Encoding: utf-8-sig, then UTF-16 when a BOM says so, then cp1252 (latin-1 as the last resort,
flagged). Delimiter sniffed from , ; tab |; comma when sniffing fails (flagged). Every cell
stays text exactly as written (whitespace collapsed).
"""

from __future__ import annotations

import codecs
import csv
import io

from app.readers.base import DocMap, ReaderError, number_blocks, row_block

SHEET = "Sheet1"


def _decode(content: bytes) -> tuple[str, str, list[str]]:
    """-> (text, encoding, flags)."""
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return content.decode("utf-16"), "utf-16", []
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc), enc, []
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1"), "latin-1", ["encoding_fallback"]  # every byte maps


def read_csv(content: bytes) -> DocMap:
    text, encoding, doc_flags = _decode(content)
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:8192], delimiters=",;\t|"
        )
    except csv.Error:
        dialect = csv.excel
        doc_flags.append("delimiter_fallback")
    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error as exc:
        raise ReaderError(f"csv reader: {type(exc).__name__}") from exc
    flags = tuple(doc_flags)
    blocks = []
    for n, row in enumerate(rows, start=1):
        cells = [(i, " ".join(v.split())) for i, v in enumerate(row)]
        b = row_block(SHEET, n, cells, flags)
        if b is not None:
            blocks.append(b)
    meta = {
        "sheets": 1,
        "encoding": encoding,
        "delimiter": getattr(dialect, "delimiter", ","),
        "flags": doc_flags,
    }
    return DocMap("csv", number_blocks("C", blocks), meta)
