"""P1-11: a file is accepted if its extension OR its magic bytes say PDF/DOCX/XLSX/CSV.

Content wins when both are known and disagree (a PDF named .csv is read as a PDF).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePath

EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv"}


def sniff(content: bytes) -> str | None:
    head = content[:1024]
    if b"%PDF-" in head:
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return _sniff_ooxml(content)
    if _looks_like_csv(content):
        return "csv"
    return None


def _sniff_ooxml(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    return None


def _looks_like_csv(content: bytes) -> bool:
    sample = content[:8192]
    if not sample or b"\x00" in sample:
        return False
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError:
        # a multi-byte character cut at the sample edge is fine
        try:
            text = sample[:-3].decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return any(sep in first_line for sep in (",", ";", "\t"))


def detect(filename: str | None, content: bytes) -> str | None:
    by_content = sniff(content)
    if by_content:
        return by_content
    suffix = PurePath(filename or "").suffix.lower()
    return EXTENSIONS.get(suffix)
