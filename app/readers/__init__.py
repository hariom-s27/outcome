"""Rough readers (P2-15): file bytes -> ordered blocks, each with an address the model can cite.

Text blocks carry "[Page N]" (PDF), "[Page ?]" (DOCX: pages unknown yet) or "[Sheet!A1]"
style refs (XLSX/CSV). PDF pages with (almost) no text layer become grayscale JPEG blocks for
a vision model (R13). Readers never log or raise with document text (R23).
P3 replaces these with real readers; the Block shape is what the extractor consumes.
"""

from __future__ import annotations

from collections.abc import Callable

from app.readers.base import Block, ReaderError
from app.readers.csv_reader import read_csv
from app.readers.docx_reader import read_docx
from app.readers.pdf_reader import read_pdf
from app.readers.xlsx_reader import read_xlsx

READERS: dict[str, Callable[[bytes], list[Block]]] = {
    "csv": read_csv,
    "xlsx": read_xlsx,
    "docx": read_docx,
    "pdf": read_pdf,
}


def read_document(file_type: str, content: bytes) -> list[Block]:
    try:
        reader = READERS[file_type]
    except KeyError:
        raise ReaderError(f"no reader for file type {file_type!r}") from None
    return reader(content)


__all__ = ["Block", "ReaderError", "read_document"]
