"""XLSX -> every sheet, one block per non-empty row, cached values (data_only), refs Sheet!A1."""

from __future__ import annotations

import io
import zipfile

from app.readers.base import Block, ReaderError, row_block


def read_xlsx(content: bytes) -> list[Block]:
    import openpyxl  # heavy import, only in the worker path

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ReaderError(f"xlsx reader: {type(exc).__name__}") from exc
    blocks: list[Block] = []
    try:
        for ws in wb.worksheets:
            for n, row in enumerate(ws.iter_rows(values_only=True), start=1):
                b = row_block(ws.title, n, list(row))
                if b is not None:
                    blocks.append(b)
    finally:
        wb.close()
    return blocks
