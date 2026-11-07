"""A5 (spike 22): lease structure counts. Counts only, no text.

lease_002 (DOCX): parts by type from heading-like paragraphs (short, heading style or mostly
upper case) whose text starts with a part keyword; signature blocks; tracked changes.
lease_001 (PDF): page count and pages without a text layer (no OCR).
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from xml.etree import ElementTree as ET

import pypdfium2 as pdfium
from _common import Report, doc_path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PART_RE = [
    ("amendment", re.compile(r"^(first|second|third|\w+)?\s*amendment\b")),
    ("exhibit", re.compile(r"^exhibit\b")),
    ("schedule", re.compile(r"^schedule\b")),
    ("rider", re.compile(r"^rider\b|\brider$")),
    ("memo", re.compile(r"^memorandum\b")),
    ("addendum", re.compile(r"^addendum\b")),
    ("guaranty", re.compile(r"^guarant(y|ee)\b")),
    ("summary", re.compile(r"(basic lease (information|provisions)|summary|abstract)")),
    ("body", re.compile(r"^(article|section)\s+(1|i|one)\b")),
]
SIG_RE = re.compile(r"in witness whereof")
BY_RE = re.compile(r"^by\s*[:_]")


def docx_paragraphs(xml: bytes) -> list[tuple[str, str]]:
    root = ET.fromstring(xml)
    out = []
    for p in root.iter(W + "p"):
        style_el = p.find(f"{W}pPr/{W}pStyle")
        style = style_el.get(W + "val", "") if style_el is not None else ""
        text = "".join(t.text or "" for t in p.iter(W + "t"))
        if text.strip():
            out.append((style, " ".join(text.split())))
    return out


def main() -> None:
    rep = Report("a5_lease_structure")
    with zipfile.ZipFile(doc_path("lease_002")) as z:
        xml = z.read("word/document.xml")
        names = z.namelist()
    paras = docx_paragraphs(xml)
    parts: Counter = Counter()
    sig = by_lines = 0
    for style, text in paras:
        low = text.lower()
        sig += bool(SIG_RE.search(low))
        by_lines += bool(BY_RE.match(low))
        letters = [c for c in text if c.isalpha()]
        heading = style.lower().startswith(("heading", "title")) or (
            len(text) <= 80 and letters and sum(c.isupper() for c in letters) / len(letters) > 0.8
        )
        if not heading:
            continue
        for kind, rx in PART_RE:
            if rx.search(low):
                parts[kind] += 1
                rep.line(f"heading-like paragraph -> {kind} (style={style or '-'})")
                break
    root = ET.fromstring(xml)
    ins = sum(1 for _ in root.iter(W + "ins"))
    dels = sum(1 for _ in root.iter(W + "del"))
    moves = sum(1 for _ in root.iter(W + "moveFrom")) + sum(1 for _ in root.iter(W + "moveTo"))
    tables = sum(1 for _ in root.iter(W + "tbl"))
    textboxes = sum(1 for _ in root.iter(W + "txbxContent"))
    headers = sum(1 for n in names if re.match(r"word/(header|footer)\d*\.xml", n))
    rep.sum(f"lease_002 parts by type: {dict(parts) or '{}'} (paragraphs={len(paras)})")
    rep.sum(
        f"lease_002 signature blocks: 'in witness whereof'={sig}, 'By:' lines={by_lines}; "
        f"tracked ins={ins} del={dels} moves={moves}"
    )
    rep.sum(
        f"lease_002 tables={tables} text boxes={textboxes} header/footer parts={headers} "
        f"footnotes={'word/footnotes.xml' in names} comments={'word/comments.xml' in names}"
    )

    pdf = pdfium.PdfDocument(doc_path("lease_001"))
    no_text = 0
    for i in range(len(pdf)):
        page = pdf[i]
        tp = page.get_textpage()
        chars = len("".join((tp.get_text_bounded() or "").split()))
        tp.close()
        no_text += chars < 25
        rep.line(f"lease_001 p{i + 1} text_chars={chars}")
        page.close()
    rep.sum(
        f"lease_001: pages={len(pdf)} pages without text layer={no_text} "
        f"scanned_no_text_layer={'yes' if no_text == len(pdf) else 'partly' if no_text else 'no'}"
    )
    pdf.close()
    rep.close()


if __name__ == "__main__":
    main()
