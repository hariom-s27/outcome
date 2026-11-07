"""Readers (P3): file bytes -> one document map (DocMap: ordered Blocks + document facts).

Every reader emits the same Block schema (block_id, kind, text, address, page, flags; see
base.py). Addresses: "Page N" (PDF; DOCX with the estimate page method), "Sheet!A1:F1"
(XLSX/CSV), "" (DOCX with page method none). Scanned PDF pages become grayscale JPEG blocks
for a vision model (R13). Readers never log or raise with document text (R23).
"""

from __future__ import annotations

from collections.abc import Callable

from app.readers.base import Block, DocMap, ReaderError
from app.readers.csv_reader import read_csv
from app.readers.docx_reader import read_docx
from app.readers.pdf_reader import read_pdf
from app.readers.xlsx_reader import read_xlsx

READERS: dict[str, Callable[[bytes], DocMap]] = {
    "csv": read_csv,
    "xlsx": read_xlsx,
    "docx": read_docx,
    "pdf": read_pdf,
}


def read_document(file_type: str, content: bytes) -> DocMap:
    try:
        reader = READERS[file_type]
    except KeyError:
        raise ReaderError(f"no reader for file type {file_type!r}") from None
    return reader(content)


__all__ = ["Block", "DocMap", "ReaderError", "read_document"]
