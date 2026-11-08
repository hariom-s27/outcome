"""P9c: PDF tables through a line grid (PDF_TABLE_METHOD, Z-42..Z-45, Z-48).

Invented two-page widget stock list built here as a PDF (no sample document, no network).
"""

from __future__ import annotations

import json

import pytest
from test_readers import _image, make_pdf
from test_tables import CTX, FakeLLM, ok

from app import worker
from app.config import Settings
from app.llm import JSONOutcome
from app.pipeline import baseline, table_spec
from app.readers import read_document
from app.tables import heuristic, pdf_grid

FIELDS = {
    "name": "widget_stock",
    "fields": {
        "sku": {"name": "SKU", "description": "Widget code. One per row.", "primary": True},
        "item_name": {"name": "Item Name", "description": "Item name as shown."},
        "qty": {"name": "Quantity", "description": "Units on hand, as a number."},
        "unit_price": {"name": "Unit Price", "description": "Price per unit, as a number."},
        "note": {"name": "Note", "description": "Free-text note, if any."},
    },
}

# Helvetica advance widths (1/1000 em) for the characters right-aligned below
_W = {**dict.fromkeys("0123456789$", 556), ",": 278, ".": 278, "(": 333, ")": 333, "-": 333}


def _txt(x: float, y: float, text: str, size: float = 9) -> bytes:
    return f"BT /F1 {size} Tf {x:.2f} {y} Td ({text}) Tj ET\n".encode()


def _right(x_right: float, y: float, text: str, size: float = 9) -> bytes:
    width = sum(_W.get(ch, 556) for ch in text) * size / 1000
    return _txt(x_right - width, y, text, size)


X_CODE, X_ITEM, R_QTY, R_PRICE, X_NOTE = 50, 110, 330, 420, 440
ROWS_P1 = [
    ("WX-101", "Sprocket bin", "12", "4.50", "Recount due"),
    ("WX-102", "Gear crate", "7", "11.25", "Two cases open,"),  # wraps onto a second line
    ("WX-103", "Spring pack", "40", "0.95", ""),
    ("WX-104", "Axle rod", "3", "(2.00)", "Credit line"),
    ("WX-105", "Cog tray", "18", "6.10", ""),
]
ROWS_P2 = [
    ("WX-106", "Bolt jar", "25", "1.20", ""),
    ("WX-107", "Nut box", "31", "0.80", "Damp shelf"),
    ("WX-108", "Washer roll", "9", "2.40", ""),
]


def _page(n: int, rows: list[tuple[str, ...]], total: bool) -> bytes:
    out = [
        _txt(50, 760, "Widget Co stock list", 10),  # top margin, repeats on both pages
        _txt(50, 730, f"Depot: North Yard  Count date: 2031-0{n}-01"),  # body zone, not table
        _txt(X_CODE, 700, "Code"),
        _txt(X_ITEM, 700, "Item"),
        _txt(R_QTY - 16, 700, "Qty"),
        _txt(R_PRICE - 22, 700, "Price"),
        _txt(X_NOTE, 700, "Note"),
    ]
    y = 684
    for code, item, qty, price, note in rows:
        out += [_txt(X_CODE, y, code), _txt(X_ITEM, y, item), _right(R_QTY, y, qty)]
        out += [_right(R_PRICE, y, price)]
        if note:
            out.append(_txt(X_NOTE, y, note))
        if note.endswith(","):  # the wrapped part of the comment: note band only
            y -= 10
            out.append(_txt(X_NOTE, y, "one sealed"))
        y -= 14
    if total:
        out += [
            _txt(X_ITEM, y, "Total stock"),
            _right(R_QTY, y, "145"),
            _right(R_PRICE, y, "25.20"),
        ]
    out.append(_txt(50, 30, "Widget Co internal"))  # bottom margin, repeats
    out.append(_txt(500, 30, f"Page {n} of 2"))
    return b"".join(out)


PDF = make_pdf([_page(1, ROWS_P1, False), _page(2, ROWS_P2, True)])
N_ROWS = len(ROWS_P1) + len(ROWS_P2)


def _grid() -> pdf_grid.Grid:
    res = pdf_grid.build(PDF)
    assert res.reason == "ok", res.reason
    assert res.grid is not None
    return res.grid


def _cells(grid: pdf_grid.Grid) -> dict[int, dict[str, str]]:
    sp = table_spec.profile_blocks(grid.blocks).sheet()
    return {r: dict(sp.lines[r].cells) for r in grid.body_rows}


def grid_spec(grid: pdf_grid.Grid, **over) -> dict:
    spec = {
        "sheet": pdf_grid.SHEET,
        "header_row": grid.header_row,
        "data_first_row": grid.header_row + 1,
        "data_last_row": None,
        "until_blank_run": None,
        "key_column": "A",
        "record_start": "key_matches_shape",
        "skip": ["total_like", "header_repeat", "blank"],
        "row_fields": {
            "item_name": {"col": "B"},
            "qty": {"col": "C"},
            "unit_price": {"col": "D"},
            "note": {"col": "E"},
        },
        "doc_fields": {},
    }
    spec.update(over)
    return spec


def _baseline_answer() -> JSONOutcome:
    cell = {"value": None, "citation": "", "confidence": 0.5}
    sku = {"value": "WX-101", "citation": "[Page 1] WX-101", "confidence": 0.9}
    return ok({"entries": [{**dict.fromkeys(FIELDS["fields"], cell), "sku": sku}]})


def _run(fake: FakeLLM, robust: bool = False):
    blocks = read_document("pdf", PDF).blocks
    out = table_spec.extract(
        fake, CTX, FIELDS, blocks, "pdf", robust=robust, pdf_grid=pdf_grid.build(PDF)
    )
    return out, out.notes["extraction"]["table"]


# --- grid rules (Z-44) -------------------------------------------------------------------------


def test_grid_bands_and_rows_across_pages_with_repeated_header():
    grid = _grid()
    assert grid.stats["bands"] == 5 and grid.stats["repeated_headers"] == 1
    cells = _cells(grid)
    keys = [c.get("A") for c in cells.values() if c.get("A", "").startswith("WX-")]
    assert keys == [r[0] for r in ROWS_P1 + ROWS_P2]  # every row, page 1 then page 2
    assert {grid.row_page[r] for r in grid.body_rows} == {1, 2}
    assert all(grid.row_line[r].startswith(f"P{grid.row_page[r]}L") for r in grid.body_rows)
    assert not any(c.get("A") == "Code" for c in cells.values())  # repeated header skipped


def test_wrapped_comment_joins_its_row():
    grid = _grid()
    assert grid.stats["continuations"] == 1
    row = next(c for c in _cells(grid).values() if c.get("A") == "WX-102")
    assert row["E"] == "Two cases open, one sealed"
    assert row["C"] == "7" and row["D"] == "11.25"


def test_page_header_and_footer_lines_are_skipped():
    grid = _grid()
    assert grid.stats["page_furniture"] == 2  # one footer line ("... Page N of 2") per page
    texts = " ".join(v for c in _cells(grid).values() for v in c.values())
    assert "Widget Co internal" not in texts and "Page 1 of 2" not in texts
    assert "Depot:" not in texts  # page 2's body-zone page header sits above the header
    sp = table_spec.profile_blocks(grid.blocks).sheet()
    above = [sp.lines[r] for r in sp.rows if r < grid.header_row]
    assert any("Depot:" in v for ln in above for v in ln.cells.values())  # kept for doc fields


def test_two_row_header_and_a_label_wider_than_its_column():
    lines = [
        _txt(50, 700, "Code"),
        _txt(300, 712, "Prior"),  # upper header row over the number column
        _txt(260, 700, "Year Amount"),  # a label much wider than the numbers under it
        _txt(380, 700, "Note"),
    ]
    for i in range(6):
        y = 684 - 14 * i
        lines += [_txt(50, y, f"WX-{i}"), _right(330, y, f"{i + 1}0.00"), _txt(380, y, "ok")]
    res = pdf_grid.build(make_pdf([b"".join(lines)]))
    assert res.grid is not None and res.stats["bands"] == 3 and res.stats["header_rows"] == 2
    sp = table_spec.profile_blocks(res.grid.blocks).sheet()
    assert sp.lines[res.grid.header_row].cells == {
        "A": "Code",
        "B": "Prior Year Amount",
        "C": "Note",
    }


def test_no_table_gives_no_grid():
    prose = make_pdf([_txt(72, 700, "A short invented memo with no table at all.")])
    res = pdf_grid.build(prose)
    assert res.grid is None and res.reason == "no_header"
    assert pdf_grid.build(b"not a pdf").reason.startswith("open_failed")


# --- the spec path on the grid (Z-42, Z-45) ----------------------------------------------------


def test_grid_rows_values_and_citations_come_from_code():
    grid = _grid()
    out, t = _run(FakeLLM(ok(grid_spec(grid))))
    assert t["grid_result"] == "ok" and t["grid_fallback"] is False and t["chosen"] == "ai"
    assert len(out.entries) == N_ROWS and t["calls"] == 1
    by_key = {e["sku"]["value"]: e for e in out.entries}
    assert by_key["WX-104"]["unit_price"]["value"] == -2  # "(2.00)" through the normaliser
    assert by_key["WX-107"]["qty"]["value"] == 31
    e = by_key["WX-107"]["qty"]
    assert e["citation"].startswith("[Page 2] ") and e["page_numbers"] == [2]
    assert "source_locations" not in e  # an XLSX/CSV field; PDFs carry page_numbers
    assert by_key["WX-101"]["sku"]["page_numbers"] == [1]
    assert (
        table_spec.contract_errors(
            {"entries": out.entries, "metadata": table_spec._zero_meta()}, FIELDS
        )
        == []
    )


def test_total_line_is_not_a_row():
    out, t = _run(FakeLLM(ok(grid_spec(_grid()))))
    assert len(out.entries) == N_ROWS
    assert t["lines"].get("skipped-total_like") == 1
    assert not any("Total" in str(e["item_name"]["value"]) for e in out.entries)


def test_incomplete_recipe_loses_to_a_candidate_that_passes(monkeypatch):
    grid = _grid()
    short = grid_spec(grid, data_last_row=grid.header_row + 3)  # stops on page 1
    out, t = _run(FakeLLM(ok(short)))
    assert t["grid_checks"]["ai"]["missing"] > 0 and "complete" in t["grid_checks"]["ai"]["failed"]
    assert t["chosen"] != "ai" and len(out.entries) == N_ROWS  # heuristic/merge passed, no call


def test_check_failure_retries_once_then_falls_back_to_single(monkeypatch):
    monkeypatch.setattr(heuristic, "build", lambda field_list, wp: None)
    grid = _grid()
    short = grid_spec(grid, data_last_row=grid.header_row + 3)
    fake = FakeLLM(ok(short), ok(short), _baseline_answer())
    out, t = _run(fake)
    assert [c[0] for c in fake.calls] == ["table_spec", "table_spec_e0", "extract"]
    assert t["grid_result"] == "checks_failed" and "complete" in t["grid_failed"]
    assert t["grid_fallback"] is True and t["chosen"] == "fallback"
    assert t["fallback_result"] == "baseline" and out.entries is not None


def test_no_check_retry_when_e0_already_made_its_call(monkeypatch):
    monkeypatch.setattr(heuristic, "build", lambda field_list, wp: None)
    grid = _grid()
    low = grid_spec(grid, data_last_row=grid.header_row + 3, row_fields={"item_name": {"col": "B"}})
    fake = FakeLLM(ok(low), ok(low), _baseline_answer())
    out, t = _run(fake, robust=True)
    assert [c[0] for c in fake.calls] == ["table_spec", "table_spec_e0", "extract"]
    assert "grid_retry" not in t and t["grid_fallback"] is True


def test_duplicate_keys_fail_the_checks():
    rows = [*ROWS_P1, ("wx-105 ", "Cog tray copy", "2", "6.10", "")]  # same key, normalised
    grid = pdf_grid.build(make_pdf([_page(1, rows, False)])).grid
    assert grid is not None
    wp = table_spec.profile_blocks(grid.blocks)
    spec, errors = table_spec.validate_spec(grid_spec(grid), FIELDS, wp, "ai")
    assert spec is not None, errors
    res = table_spec.grid_checks(table_spec.run_candidate(spec, wp, FIELDS), wp, FIELDS, grid)
    assert res["failed"] == ["unique_keys"] and res["duplicate_keys"] == 1


def test_good_recipe_passes_every_check():
    grid = _grid()
    wp = table_spec.profile_blocks(grid.blocks)
    spec, _errors = table_spec.validate_spec(grid_spec(grid), FIELDS, wp, "ai")
    res = table_spec.grid_checks(table_spec.run_candidate(spec, wp, FIELDS), wp, FIELDS, grid)
    assert res["failed"] == [] and res["key_lines"] == N_ROWS and res["missing"] == 0


def test_no_grid_falls_back_without_a_spec_call():
    fake = FakeLLM(_baseline_answer())
    blocks = read_document("pdf", PDF).blocks
    res = pdf_grid.GridResult(None, "no_header")
    out = table_spec.extract(fake, CTX, FIELDS, blocks, "pdf", pdf_grid=res)
    t = out.notes["extraction"]["table"]
    assert [c[0] for c in fake.calls] == ["extract"]
    assert t["grid_result"] == "no_header" and t["grid_fallback"] is True


# --- default single = v1.0 (off-by-default rule) -----------------------------------------------


def test_default_single_is_the_v1_call():
    fake = FakeLLM(_baseline_answer())
    blocks = read_document("pdf", PDF).blocks
    out = table_spec.extract(fake, CTX, FIELDS, blocks, "pdf")
    assert [c[0] for c in fake.calls] == ["extract"] and "extraction" not in out.notes


@pytest.mark.parametrize(
    "raw, method", [(None, "single"), ("", "single"), ("grid", "grid"), (" GRID ", "grid")]
)
def test_switch_defaults_to_single(monkeypatch, raw, method):
    assert Settings().pdf_table_method == "single"
    if raw is None:
        monkeypatch.delenv("PDF_TABLE_METHOD", raising=False)
    else:
        monkeypatch.setenv("PDF_TABLE_METHOD", raw)
    assert Settings.from_env().pdf_table_method == method


def test_switch_rejects_unknown_values():
    with pytest.raises(ValueError, match="PDF_TABLE_METHOD"):
        Settings(pdf_table_method="chunks")


def test_scanned_pdf_keeps_the_v1_path():
    scan = make_pdf([_image(50, 50, 500, 700)])
    assert worker.has_scan(read_document("pdf", scan).blocks) is True
    assert worker.has_scan(read_document("pdf", PDF).blocks) is False


TABLE_FIELDS_JSON = json.dumps(FIELDS)


@pytest.mark.parametrize("method", ["single", "grid"])
def test_worker_passes_the_grid_only_when_switched_on(settings, client, monkeypatch, method):
    seen: list[dict] = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return baseline.BaselineOutcome(None, "llm_unusable")

    monkeypatch.setattr(table_spec, "extract", spy)
    s = settings.__class__(**{**settings.__dict__, "pdf_table_method": method})
    r = client.post("/jobs", files={"file": ("w.pdf", PDF)}, data={"schema": TABLE_FIELDS_JSON})
    assert r.status_code == 202
    llm = FakeLLM()
    llm.store = type("S", (), {"job_metadata": staticmethod(lambda jid, ms: {"latency_ms": ms})})
    llm.cache_mode = "off"
    llm.catalog.call_cap = type("C", (), {"for_doc": staticmethod(lambda ft, p, d: 4)})
    llm.settings = type("L", (), {"max_calls_per_doc": 4})
    assert worker.process_one(s, "w1", llm) is True
    assert len(seen) == 1
    if method == "single":
        assert "pdf_grid" not in seen[0]  # the v1.0 call exactly
    else:
        assert isinstance(seen[0]["pdf_grid"], pdf_grid.GridResult)
        assert seen[0]["pdf_grid"].reason == "ok"
