"""Readers (P3) on fixtures generated here from invented data (R31, P3-23). No network."""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pytest

from app.readers import DocMap, ReaderError, read_document
from app.readers.base import KINDS, column_letter
from app.readers.docx_reader import DocxLayout, RawBlock, docx_pages
from app.readers.xlsx_reader import display_text, format_date

# --- PDF fixtures ---------------------------------------------------------------------------------


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


def _txt(x: float, y: float, size: int, text: str) -> bytes:
    return f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET\n".encode()


def _image(x: int, y: int, w: int, h: int) -> bytes:
    # a 2x2 grayscale inline image scaled up, like a scanned page
    return (
        f"q {w} 0 0 {h} {x} {y} cm BI /W 2 /H 2 /CS /G /BPC 8 /F /AHx ID 00FF00FF> EI Q\n".encode()
    )


LAYOUT_PAGE = b"".join(
    [
        _txt(72, 770, 9, "Widget Co quarterly sheet"),  # header zone
        _txt(72, 700, 12, "Invented widget ledger body text."),
        _txt(72, 686, 12, "Second line of the same paragraph."),
        b"0 0 0 RG 70 560 250 60 re S\n",  # a boxed callout
        _txt(80, 600, 11, "Callout: sprocket fee"),
        _txt(80, 585, 11, "applies to gears too."),
        _txt(72, 450, 12, "Total 1,"),  # a number split into two spans ...
        _txt(114, 450, 12, "250.00"),  # ... 2 pt apart
        _txt(72, 400, 12, "Bold widget"),  # "fake bold": the same text drawn twice
        _txt(72.3, 400, 12, "Bold widget"),
        _txt(72, 20, 8, "Widget footer line"),  # footer zone
    ]
)
SCAN_PAGE = _image(50, 50, 500, 700)  # no text, image covers > 50%
MIXED_PAGE = _txt(72, 720, 12, "Mixed page: widget photo below with enough caption text.") + _image(
    80, 100, 450, 400
)


def test_column_letters():
    assert [column_letter(i) for i in (0, 25, 26, 27, 701, 702)] == [
        "A",
        "Z",
        "AA",
        "AB",
        "ZZ",
        "AAA",
    ]


def test_pdf_block_model_header_footer_callout_numbers_fake_bold():
    dm = read_document("pdf", make_pdf([LAYOUT_PAGE]))
    assert isinstance(dm, DocMap) and dm.file_type == "pdf"
    by_text = {b.text: b for b in dm.blocks}
    assert by_text["Widget Co quarterly sheet"].flags == ("header",)
    assert by_text["Widget footer line"].flags == ("footer",)
    body = by_text["Invented widget ledger body text.\nSecond line of the same paragraph."]
    assert body.kind == "paragraph" and body.page == 1 and body.address == "Page 1"
    callout = by_text["Callout: sprocket fee\napplies to gears too."]
    assert callout.kind == "callout"
    assert "Total 1,250.00" in by_text
    assert "Bold widget" in by_text  # doubled characters removed
    assert [b.block_id for b in dm.blocks] == [f"P{i:04d}" for i in range(1, len(dm.blocks) + 1)]
    tops = [b.text for b in dm.blocks]
    assert tops[0] == "Widget Co quarterly sheet" and tops[-1] == "Widget footer line"


def test_pdf_scan_page_becomes_grayscale_jpeg_and_mixed_page_is_flagged():
    dm = read_document("pdf", make_pdf([LAYOUT_PAGE, SCAN_PAGE, MIXED_PAGE]))
    img = [b for b in dm.blocks if b.kind == "image"]
    assert [(b.page, b.address) for b in img] == [(2, "Page 2")]
    assert img[0].jpeg[:3] == b"\xff\xd8\xff"
    assert max(img[0].width, img[0].height) == pytest.approx(1600, abs=2)
    from PIL import Image

    assert Image.open(io.BytesIO(img[0].jpeg)).mode == "L"
    mixed = [b for b in dm.blocks if b.page == 3]
    assert mixed and all("image_text_risk" in b.flags for b in mixed)
    assert dm.meta["scan_pages"] == 1 and dm.meta["mixed_pages"] == 1


def test_pdf_layout_failure_falls_back_to_page_text(monkeypatch):
    from app.readers import pdf_reader

    def boom(*a, **k):
        raise ValueError("invented failure")

    monkeypatch.setattr(pdf_reader, "_layout_blocks", boom)
    dm = read_document("pdf", make_pdf([LAYOUT_PAGE]))
    assert len(dm.blocks) == 1 and "layout_fallback" in dm.blocks[0].flags
    assert "Invented widget ledger" in dm.blocks[0].text
    assert dm.meta["layout_failed"] == 1 and dm.meta["layout_errors"] == ["ValueError"]


# --- XLSX -----------------------------------------------------------------------------------------


def _xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Widgets"
    ws["A1"] = "Widget register"
    ws.merge_cells("A1:C1")  # merged header
    ws.append(["Code", "Shipped", "Double"])
    ws["A3"] = 42
    ws["A3"].number_format = "00000"  # leading-zero key
    ws["B3"] = dt.datetime(2031, 4, 5)
    ws["B3"].number_format = "mm/dd/yyyy"
    ws["C3"] = "=A3*2"  # saved by openpyxl: no cached value
    ws["A4"] = "sprocket"
    ws.row_dimensions[4].hidden = True
    hidden = wb.create_sheet("Spare")
    hidden["B2"] = "gear stock"
    hidden.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_merged_hidden_formula_without_cache_and_displayed_keys():
    dm = read_document("xlsx", _xlsx())
    got = {b.address: b for b in dm.blocks}
    assert list(got) == ["Widgets!A1", "Widgets!A2:C2", "Widgets!A3:C3", "Widgets!A4", "Spare!B2"]
    assert got["Widgets!A1"].flags == ("merged=A1:C1",)
    row3 = got["Widgets!A3:C3"]
    assert row3.text == "A3=00042 | B3=04/05/2031 | C3="
    assert row3.flags == ("formula_no_cache=C3",)
    assert "hidden_row" in got["Widgets!A4"].flags
    assert got["Spare!B2"].flags == ("hidden_sheet",) and got["Spare!B2"].text == "B2=gear stock"
    assert {b.kind for b in dm.blocks} == {"row"}
    assert dm.meta == {"sheets": 2, "hidden_sheets": 1, "merged_ranges": 1, "formula_no_cache": 1}


def test_number_formats_render_as_displayed():
    d = dt.datetime(2031, 4, 5, 14, 7)
    assert format_date(d, "d-mmm-yy") == "5-Apr-31"
    assert format_date(d, "yyyy-mm-dd h:mm") == "2031-04-05 14:07"
    assert format_date(d, "General") is None
    assert display_text(7, "000") == "007"
    assert display_text(7.5, "000") == "7.5"
    assert display_text(1250, "#,##0.00") == "1250"  # only keys and dates change
    assert display_text(dt.date(2031, 1, 2), "General") == "2031-01-02"


# --- CSV ------------------------------------------------------------------------------------------


def test_csv_utf16_semicolons_cells_kept_as_text():
    data = "widget;code;price\r\nsprocket;007;1.50\r\n;;\r\ngear;;2\r\n".encode("utf-16")
    dm = read_document("csv", data)
    assert [b.address for b in dm.blocks] == ["Sheet1!A1:C1", "Sheet1!A2:C2", "Sheet1!A4:C4"]
    assert dm.blocks[1].text == "A2=sprocket | B2=007 | C2=1.50"
    assert dm.blocks[2].text == "A4=gear | C4=2"
    assert dm.meta["encoding"] == "utf-16" and dm.meta["delimiter"] == ";"


def test_csv_cp1252_and_delimiter_fallback():
    dm = read_document("csv", "name;size\ncafé widget;12\n".encode("cp1252"))
    assert dm.blocks[1].text == "A2=café widget | B2=12" and dm.meta["encoding"] == "cp1252"
    dm = read_document("csv", b"onlyonecolumn\nsecondrow\n")
    assert dm.meta["flags"] == ["delimiter_fallback"]
    assert all("delimiter_fallback" in b.flags for b in dm.blocks)


# --- DOCX -----------------------------------------------------------------------------------------

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml" mc:Ignorable="wps"'
)


def _p(text: str, ppr: str = "") -> str:
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _num(ilvl: int) -> str:
    return f'<w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="1"/></w:numPr></w:pPr>'


TEXT_BOX = (
    "<w:p><w:r><w:t>Host paragraph for a box.</w:t></w:r><w:r><mc:AlternateContent>"
    '<mc:Choice Requires="wps"><w:drawing><wp:anchor><a:graphic><a:graphicData>'
    "<wps:wsp><wps:txbx><w:txbxContent>"
    + _p("Boxed widget note.")
    + "</w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>"
    "</mc:Choice><mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>"
    + _p("Boxed widget note.")
    + "</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent>"
    "</w:r></w:p>"
)
TRACKED = (
    '<w:p><w:r><w:t xml:space="preserve">Fee is </w:t></w:r>'
    '<w:del w:id="1" w:author="x"><w:r><w:delText>ten</w:delText></w:r></w:del>'
    '<w:ins w:id="2" w:author="x"><w:r><w:t>twelve</w:t></w:r></w:ins>'
    '<w:moveFrom w:id="3" w:author="x"><w:r><w:t>old place</w:t></w:r></w:moveFrom>'
    '<w:r><w:t xml:space="preserve"> sprockets</w:t></w:r>'
    '<w:moveTo w:id="4" w:author="x"><w:r><w:t xml:space="preserve"> monthly</w:t></w:r></w:moveTo>'
    '<w:r><w:rPr><w:strike/></w:rPr><w:t xml:space="preserve"> per gear</w:t></w:r></w:p>'
)
TABLE = (
    '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
    + _p("Widget schedule")
    + '</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr>'
    + _p("Gear")
    + "</w:tc><w:tc>"
    + _p("7")
    + "</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc><w:tc>"
    + _p("9")
    + "</w:tc></w:tr></w:tbl>"
)
BODY = "".join(
    [
        _p("Widget delivery", _num(0)),
        _p("Sprockets ship monthly", _num(1)),
        _p("Gear pricing", _num(0)),
        TRACKED,
        TEXT_BOX,
        TABLE,
        "<w:sdt><w:sdtPr/><w:sdtContent>"
        + _p("Controlled widget text.")
        + "</w:sdtContent></w:sdt>",
        _p("Item\tQty\tPrice"),
        '<w:p><w:r><w:br w:type="page"/></w:r></w:p>',
        _p("After the page break."),
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>',
    ]
)
NUMBERING = (
    f"<w:numbering {NS}>"
    '<w:abstractNum w:abstractNumId="0">'
    '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
    '<w:lvlText w:val="%1."/></w:lvl>'
    '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/>'
    '<w:lvlText w:val="(%2)"/></w:lvl></w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
)

CT = "application/vnd.openxmlformats-officedocument."
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def make_docx(body: str, pages: int | None = 4) -> bytes:
    files = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{CT}wordprocessingml.'
            'document.main+xml"/>'
            f'<Override PartName="/word/numbering.xml" ContentType="{CT}wordprocessingml.'
            'numbering+xml"/>'
            f'<Override PartName="/word/header1.xml" ContentType="{CT}wordprocessingml.'
            'header+xml"/>'
            f'<Override PartName="/word/footer1.xml" ContentType="{CT}wordprocessingml.'
            'footer+xml"/>'
            f'<Override PartName="/docProps/app.xml" ContentType="{CT}extended-properties+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}officeDocument" Target="word/document.xml"/>'
            f'<Relationship Id="rId2" Type="{REL}extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>"
        ),
        "word/_rels/document.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}numbering" Target="numbering.xml"/>'
            f'<Relationship Id="rId2" Type="{REL}header" Target="header1.xml"/>'
            f'<Relationship Id="rId3" Type="{REL}footer" Target="footer1.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": f"<w:document {NS}><w:body>{body}</w:body></w:document>",
        "word/numbering.xml": NUMBERING,
        "word/header1.xml": f"<w:hdr {NS}>{_p('Widget Co header')}</w:hdr>",
        "word/footer1.xml": f"<w:ftr {NS}>{_p('Widget Co footer')}</w:ftr>",
        "docProps/app.xml": (
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'extended-properties">{f"<Pages>{pages}</Pages>" if pages else ""}</Properties>'
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + text)
    return buf.getvalue()


def test_docx_order_numbering_tracked_changes_text_box_tables(monkeypatch):
    monkeypatch.delenv("DOCX_PAGE_METHOD", raising=False)
    dm = read_document("docx", make_docx(BODY))
    texts = [b.text for b in dm.blocks]
    assert texts == [
        "Widget Co header",
        "1. Widget delivery",
        "(a) Sprockets ship monthly",
        "2. Gear pricing",
        "Fee is twelve sprockets monthly per gear",
        "Host paragraph for a box.",
        "Boxed widget note.",  # once: the Fallback copy is skipped
        "Widget schedule",
        "Gear | 7",
        "9",
        "Controlled widget text.",
        "Item | Qty | Price",
        "After the page break.",
        "Widget Co footer",
    ]
    flags = {b.text: b.flags for b in dm.blocks}
    assert "strike" in flags["Fee is twelve sprockets monthly per gear"]
    assert "text_box" in flags["Boxed widget note."]
    assert "numbered" in flags["1. Widget delivery"]
    assert "tabbed" in flags["Item | Qty | Price"]
    assert all("merged_cell" in flags[t] for t in ("Widget schedule", "Gear | 7", "9"))
    assert {b.kind for b in dm.blocks} == {"paragraph", "table_row"}
    assert flags["Widget Co header"] == ("header",) and flags["Widget Co footer"] == ("footer",)


def test_docx_estimated_pages_follow_breaks_and_app_page_count(monkeypatch):
    monkeypatch.setenv("DOCX_PAGE_METHOD", "estimate")
    dm = read_document("docx", make_docx(BODY, pages=4))
    assert dm.meta["page_source"] == "estimated" and dm.meta["app_pages"] == 4
    assert dm.result_metadata() == {"page_source": "estimated"}
    body = [b for b in dm.blocks if "header" not in b.flags and "footer" not in b.flags]
    assert body[0].page == 1 and body[-1].page == 4
    assert max(b.page for b in body[:-1]) < body[-1].page  # the page break starts a new page
    assert all("page_estimated" in b.flags and b.address == f"Page {b.page}" for b in body)
    assert all(b.page is None and b.address == "" for b in dm.blocks if b not in body)


def test_docx_page_method_none_is_the_default(monkeypatch):
    monkeypatch.delenv("DOCX_PAGE_METHOD", raising=False)
    dm = read_document("docx", make_docx(BODY))
    assert dm.result_metadata() == {"page_source": "none"}
    assert all(b.page is None and b.address == "" for b in dm.blocks)
    assert all(not b.render().startswith("[") for b in dm.blocks)  # no [Page N]
    monkeypatch.setenv("DOCX_PAGE_METHOD", "crystal-ball")
    with pytest.raises(ReaderError):
        read_document("docx", make_docx(BODY))


def test_docx_estimate_without_app_pages_uses_layout():
    blocks = [RawBlock("paragraph", "w" * 700) for _ in range(10)]
    blocks[5].break_before = True
    pages, source = docx_pages(DocxLayout(blocks, None, 95.0, 46.0), "estimate")
    assert source == "estimated"
    assert pages[:5] == [1, 1, 1, 1, 1] and pages[5] == 2  # 5 x 8.5 lines < 46 per page
    blocks = [RawBlock("paragraph", "w" * 700) for _ in range(20)]
    pages, _ = docx_pages(DocxLayout(blocks, None, 95.0, 46.0), "estimate")
    assert pages[0] == 1 and pages[-1] == 4  # 170 lines / 46 per page -> 4 pages


# --- all readers ----------------------------------------------------------------------------------


def test_every_block_uses_the_one_schema(monkeypatch):
    monkeypatch.delenv("DOCX_PAGE_METHOD", raising=False)
    maps = [
        read_document("pdf", make_pdf([LAYOUT_PAGE, SCAN_PAGE])),
        read_document("xlsx", _xlsx()),
        read_document("csv", b"a,b\n1,2\n"),
        read_document("docx", make_docx(BODY)),
    ]
    for dm in maps:
        ids = [b.block_id for b in dm.blocks]
        assert len(set(ids)) == len(ids) and all(ids)
        for b in dm.blocks:
            assert b.kind in KINDS and isinstance(b.flags, tuple)
            assert (b.kind == "image") == (b.jpeg is not None)


@pytest.mark.parametrize("kind", ["pdf", "xlsx", "docx"])
def test_corrupt_files_raise_reader_error(kind):
    with pytest.raises(ReaderError) as exc:
        read_document(kind, b"this is not a real document at all")
    assert "not a real" not in str(exc.value)  # no content in the message (R23)


def test_unknown_type_raises_reader_error():
    with pytest.raises(ReaderError):
        read_document("pptx", b"x")
