"""DOCX -> paragraphs and table rows in body order. Pages are unknown here ("Page ?", P3)."""

from __future__ import annotations

import io
import zipfile

from app.readers.base import Block, ReaderError

PAGE_UNKNOWN = "Page ?"


def read_docx(content: bytes) -> list[Block]:
    import docx  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(content))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ReaderError(f"docx reader: {type(exc).__name__}") from exc
    blocks: list[Block] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = " ".join(item.text.split())
            if text:
                blocks.append(Block("text", PAGE_UNKNOWN, text, unit="paragraph"))
        elif isinstance(item, Table):
            for row in item.rows:
                cells: list[str] = []
                for cell in row.cells:
                    t = " ".join(cell.text.split())
                    if t and (not cells or cells[-1] != t):  # merged cells repeat their text
                        cells.append(t)
                if cells:
                    blocks.append(Block("text", PAGE_UNKNOWN, " | ".join(cells), unit="row"))
    return blocks
