"""Rough readers (P2-15) on fixtures generated here from invented data (R31). No network."""

from __future__ import annotations

import datetime as dt
import io

import pytest

from app.readers import ReaderError, read_document
from app.readers.base import column_letter


def make_pdf(streams: list[bytes]) -> bytes:
    """A minimal valid PDF, one page per content stream, Helvetica as /F1."""
    n = len(streams)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, st in enumerate(streams):
        objs.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(st) + st + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


TEXT_PAGE = b"BT /F1 12 Tf 72 720 Td (Invented widget ledger, page one: 42 sprockets.) Tj ET"
# no text layer: a 2x2 grayscale inline image scaled up, like a scanned page
IMAGE_PAGE = b"q 300 0 0 300 150 250 cm BI /W 2 /H 2 /CS /G /BPC 8 /F /AHx ID 00FF00FF> EI Q"


def test_column_letters():
    assert [column_letter(i) for i in (0, 25, 26, 27, 701, 702)] == [
        "A",
        "Z",
        "AA",
        "AB",
        "ZZ",
        "AAA",
    ]


def test_csv_rows_with_sheet1_refs():
    data = b"widget,count,price\nsprocket,3,1.50\n\n,,\ngear,,2\n"
    blocks = read_document("csv", data)
    assert [b.address for b in blocks] == ["Sheet1!A1:C1", "Sheet1!A2:C2", "Sheet1!A5:C5"]
    assert blocks[1].text == "A2=sprocket | B2=3 | C2=1.50"
    assert blocks[2].text == "A5=gear | C5=2"  # empty cell skipped, ref kept exact
    assert blocks[0].render().startswith("[Sheet1!A1:C1] ")


def test_csv_semicolon_and_latin1():
    data = "name;size\ncafé widget;12\n".encode("cp1252")
    blocks = read_document("csv", data)
    assert blocks[1].text == "A2=café widget | B2=12"


def test_xlsx_every_sheet_values_and_refs():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Widgets"
    ws.append(["Widget", "Count", "Shipped"])
    ws.append(["sprocket", 3.0, dt.datetime(2031, 4, 5)])
    ws["B3"] = "=B2*2"  # formula without a cached value -> empty in data_only mode
    p = wb.create_sheet("Params")
    p["C4"] = "region: north"
    buf = io.BytesIO()
    wb.save(buf)
    blocks = read_document("xlsx", buf.getvalue())
    assert [b.address for b in blocks] == ["Widgets!A1:C1", "Widgets!A2:C2", "Params!C4"]
    assert blocks[1].text == "A2=sprocket | B2=3 | C2=2031-04-05"
    assert blocks[2].text == "C4=region: north"


def test_docx_paragraphs_and_tables_in_order():
    import docx

    d = docx.Document()
    d.add_paragraph("Widget supply agreement between Acme Sprockets and Gearco.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Item", "Monthly fee"
    t.cell(1, 0).text, t.cell(1, 1).text = "Sprocket", "1,250.00"
    d.add_paragraph("   ")  # empty paragraph skipped
    d.add_paragraph("Term: thirty-six months.")
    buf = io.BytesIO()
    d.save(buf)
    blocks = read_document("docx", buf.getvalue())
    assert [b.text for b in blocks] == [
        "Widget supply agreement between Acme Sprockets and Gearco.",
        "Item | Monthly fee",
        "Sprocket | 1,250.00",
        "Term: thirty-six months.",
    ]
    assert {b.address for b in blocks} == {"Page ?"}
    assert [b.unit for b in blocks] == ["paragraph", "row", "row", "paragraph"]


def test_pdf_text_page_and_image_only_page():
    blocks = read_document("pdf", make_pdf([TEXT_PAGE, IMAGE_PAGE]))
    assert [(b.kind, b.address, b.page) for b in blocks] == [
        ("text", "Page 1", 1),
        ("image", "Page 2", 2),
    ]
    assert "42 sprockets" in blocks[0].text
    img = blocks[1]
    assert img.jpeg[:3] == b"\xff\xd8\xff"  # JPEG
    assert max(img.width, img.height) == pytest.approx(1600, abs=2)

    from PIL import Image

    assert Image.open(io.BytesIO(img.jpeg)).mode == "L"  # grayscale


@pytest.mark.parametrize("kind", ["pdf", "xlsx", "docx"])
def test_corrupt_files_raise_reader_error(kind):
    with pytest.raises(ReaderError) as exc:
        read_document(kind, b"this is not a real document at all")
    assert "not a real" not in str(exc.value)  # no content in the message (R23)


def test_unknown_type_raises_reader_error():
    with pytest.raises(ReaderError):
        read_document("pptx", b"x")
