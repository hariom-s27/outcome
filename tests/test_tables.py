"""P6 long-table path: profiler, spec grammar, executor, checks, heuristic spec, pipeline.

Every spreadsheet here is invented and built in code with openpyxl (R31). No network, no key.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import validator

from app import worker
from app.config import Settings
from app.llm import CallContext, JSONOutcome
from app.llm.client import Projection
from app.llm.models import Estimate
from app.pipeline import baseline, single_value, table_spec
from app.readers import read_document
from app.readers.base import Block
from app.readers.xlsx_reader import vertical_sum
from app.tables import heuristic
from app.tables.checks import run_checks, spec_score
from app.tables.execute import execute
from app.tables.profile import cell_kind, preview, profile_blocks, shape, to_number
from app.tables.spec import allowed_values, salvage_spec, validate_spec

HAIKU = "anthropic/claude-haiku-5.5"
CTX = CallContext(job_id=None, deadline=4_000_000_000.0)


# --- invented workbooks ------------------------------------------------------------------------


def make_xlsx(
    sheets: dict[str, list[list[Any]]],
    cached: dict[str, dict[str, float]] | None = None,
    formats: dict[str, dict[str, str]] | None = None,
) -> bytes:
    """Rows from row 1; None = empty cell. `cached` writes a cached value for formula cells
    (openpyxl saves formulas without one), the way a spreadsheet app would."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r, row in enumerate(rows, start=1):
            for c, v in enumerate(row, start=1):
                if v is not None:
                    ws.cell(row=r, column=c, value=v)
        for ref, fmt in (formats or {}).get(name, {}).items():
            ws[ref].number_format = fmt
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if not cached:
        return data
    names = list(sheets)
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            raw = zin.read(item)
            m = re.match(r"xl/worksheets/sheet(\d+)\.xml$", item)
            if m and names[int(m[1]) - 1] in cached:
                xml = raw.decode("utf-8")
                for ref, val in cached[names[int(m[1]) - 1]].items():
                    xml = re.sub(
                        rf'(<c r="{ref}"[^>]*><f>[^<]*</f>)<v\s*/?>(?:</v>)?',
                        rf"\g<1><v>{val}</v>",
                        xml,
                    )
                raw = xml.encode("utf-8")
            zout.writestr(item, raw)
    return out.getvalue()


def blocks_of(data: bytes, file_type: str = "xlsx") -> list[Block]:
    return read_document(file_type, data).blocks


FLAT_FIELDS = {
    "name": "widget_stock",
    "fields": {
        "sku": {
            "name": "SKU",
            "description": "Stock keeping unit code. One per row.",
            "primary": True,
        },
        "item_name": {"name": "Item Name", "description": "Item name as shown."},
        "qty": {"name": "Quantity", "description": "Units on hand, as a number."},
        "unit_price": {"name": "Unit Price", "description": "Price per unit, as a number."},
        "depot": {
            "name": "Depot",
            "description": "Depot name from the report header. Same for every row.",
        },
    },
}


def flat_rows(n: int = 70, *, total: bool = True, repeat_at: int | None = None) -> list[list]:
    rows: list[list] = [["Invented stock list"], ["Depot:", "North Widget Yard"], [
        "SKU", "Item Name", "Qty", "Unit Price"]]  # fmt: skip
    qty_sum = 0
    for i in range(n):
        if repeat_at is not None and i == repeat_at:
            rows.append(["SKU", "Item Name", "Qty", "Unit Price"])
        q = i % 7 + 1
        qty_sum += q
        rows.append([f"WX-{100 + i}", f"Widget {i}", q, 2.5 + i])
    if total:
        rows.append([None, "Total", qty_sum, None])
    return rows


def flat_spec(**over: Any) -> dict[str, Any]:
    spec = {
        "sheet": "Stock",
        "header_row": 3,
        "data_first_row": 4,
        "data_last_row": None,
        "until_blank_run": None,
        "key_column": "A",
        "record_start": "key_matches_shape",
        "skip": ["total_like", "header_repeat", "blank"],
        "row_fields": {
            "item_name": {"col": "B"},
            "qty": {"col": "C"},
            "unit_price": {"col": "D"},
        },
        "doc_fields": {"depot": {"cell": "Stock!B2"}},
    }
    spec.update(over)
    return spec


def run_spec(raw: dict, fields: dict, data: bytes):
    wp = profile_blocks(blocks_of(data))
    spec, errors = validate_spec(raw, fields, wp)
    assert errors == [], errors
    ex = execute(spec, wp, fields)
    return wp, ex, run_checks(ex)


def contract_ok(entries: list[dict], fields: dict) -> bool:
    meta = {"model_calls": 1, "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "latency_ms": 1}
    return validator.validate_contract({"entries": entries, "metadata": meta}, fields) == []


# --- profile helpers ---------------------------------------------------------------------------


def test_cell_helpers():
    assert to_number("1,250.00") == 1250.0
    assert to_number("(1,250)") == -1250.0
    assert to_number("$12") == 12.0
    assert to_number("-") is None and cell_kind("-") == "dash"
    assert to_number("WX-101") is None and cell_kind("WX-101") == "text"
    assert cell_kind("2031-04-05") == "date"
    assert shape("WX-101") == "A-9" and shape("00042") == "9"


def test_vertical_sum_only():
    assert vertical_sum("=SUM(C4:C9)")
    assert vertical_sum("=SUBTOTAL(9,$C$4:$C$9)")
    assert not vertical_sum("=SUM(C4:N4)")  # a line's own row total
    assert not vertical_sum("=C4+C5")


def test_profile_header_preview_and_sample_cap():
    wp = profile_blocks(blocks_of(make_xlsx({"Stock": flat_rows(80)})))
    sp = wp.sheet()
    assert sp.header_row == 3 and sp.headers["C"] == "Qty"
    assert wp.data_line_count() == 81  # 80 rows + the total line
    text = preview(wp)
    assert "[Stock!A4] WX-100" in text and "HEADER BLOCK" in text
    sampled = [ln for ln in text.split("LINES", 1)[1].splitlines() if ln.startswith("[Stock!")]
    assert len(sampled) <= 30
    assert "total-word" in text  # the total line is in the tail sample


# --- flat table with a total row -------------------------------------------------------------


def test_flat_table_with_total_row():
    _wp, ex, checks = run_spec(flat_spec(), FLAT_FIELDS, make_xlsx({"Stock": flat_rows()}))
    assert len(ex.entries) == 70
    assert ex.dispositions["skipped-total_like"] == 1
    first = ex.entries[0]
    assert first["sku"]["value"] == "WX-100" and first["sku"]["source_locations"] == ["Stock!A4"]
    assert first["qty"]["value"] == 1 and first["qty"]["citation"] == "[Stock!C4] 1"
    assert first["unit_price"]["value"] == 2.5
    assert {e["depot"]["value"] for e in ex.entries} == {"North Widget Yard"}  # broadcast
    assert checks["C3"].passed is True and checks["C3"].detail["matched"] == 1
    score, hard = spec_score(checks)
    assert score == 5 and not hard


# --- unit blocks with child charge lines + per-unit total lines -----------------------------

BAY_FIELDS = {
    "name": "bay_lettings",
    "fields": {
        "bay": {"name": "Bay", "description": "Bay identifier. One per row.", "primary": True},
        "kind": {"name": "Kind", "description": "Bay kind code."},
        "holder": {"name": "Holder", "description": "Holder name as shown."},
        "base_fee": {"name": "Base Fee", "description": "The 'Base fee' charge, as a number."},
        "other_fees": {
            "name": "Other Fees",
            "description": "Sum of charge lines other than the base fee, as a number. 0 if none.",
        },
        "fee_total": {"name": "Fee Total", "description": "The block's charge total, a number."},
    },
}


def bay_rows() -> list[list]:
    rows: list[list] = [["Invented bay register"], [
        "Bay", "Kind", "Area", "Holder", "Charge", "Amount"]]  # fmt: skip
    for i in range(30):
        rows.append([f"B-{101 + i}", "Small" if i % 2 else "Large", 100 + i, f"Holder {i}"])
        if i % 5 == 4:  # an empty bay: no charge lines, no total line
            continue
        base, power, wash = 500 + i, 40, (15 if i % 3 == 0 else None)
        rows.append([None, None, None, None, "Base fee", base])
        rows.append([None, None, None, None, "Power", power])
        if wash:
            rows.append([None, None, None, None, "Wash", wash])
        rows.append([None, None, None, None, "Charge Total", base + power + (wash or 0)])
    return rows


BAY_SPEC = {
    "sheet": "Bays",
    "header_row": 2,
    "data_first_row": 3,
    "data_last_row": None,
    "until_blank_run": None,
    "key_column": "A",
    "record_start": "key_matches_shape",
    "skip": ["total_like", "header_repeat", "blank", "section_header"],
    "row_fields": {
        "kind": {"col": "B"},
        "holder": {"col": "D"},
        "base_fee": {
            "pick_by_label": {"label_col": "E", "label_text": "Base fee", "value_col": "F"}
        },
        "other_fees": {
            "col": "F",
            "fold": "sum",
            "except_label": {"label_col": "E", "labels": ["Base fee"]},
        },
        "fee_total": {
            "pick_by_label": {"label_col": "E", "label_text": "Charge Total", "value_col": "F"}
        },
    },
    "doc_fields": {},
}


def test_unit_blocks_fold_children_and_pick_totals():
    _wp, ex, checks = run_spec(BAY_SPEC, BAY_FIELDS, make_xlsx({"Bays": bay_rows()}))
    assert len(ex.entries) == 30
    by = {e["bay"]["value"]: e for e in ex.entries}
    b0 = by["B-101"]  # base 500, power 40, wash 15
    assert b0["base_fee"]["value"] == 500
    assert b0["other_fees"]["value"] == 55
    assert b0["fee_total"]["value"] == 555
    assert len(b0["other_fees"]["source_locations"]) == 2
    empty = by["B-105"]  # no charge lines: money fields are 0 (R26), the key cell is cited
    assert empty["base_fee"]["value"] == 0 and empty["other_fees"]["value"] == 0
    assert empty["fee_total"]["value"] == 0 and empty["fee_total"]["citation"].startswith("[Bays!A")
    assert ex.dispositions["child"] > 0 and ex.dispositions.get("unexplained", 0) == 0
    assert checks["C3"].passed is True  # each Charge Total equals its block
    assert checks["C1"].passed and checks["C5"].passed


# --- GL lines under section headers with SUM subtotals --------------------------------------

GL_FIELDS = {
    "name": "ledger_lines",
    "fields": {
        "code": {"name": "Code", "description": "Account code exactly as shown.", "primary": True},
        "account": {"name": "Account", "description": "Account name exactly as shown."},
        "section": {"name": "Section", "description": "The nearest section header above."},
        "category": {
            "name": "Category",
            "description": "One of: Revenue, Expense, Other. Revenue for income lines.",
        },
        "total": {"name": "Total", "description": "The Total column, as a number."},
        "active_months": {
            "name": "Active Months",
            "description": "Count of monthly columns with a non-zero value, as a number.",
        },
    },
}


def gl_workbook() -> bytes:
    rows = [
        ["Invented ledger"],
        ["Code", "Account", "Jan", "Feb", "Total"],
        ["SALES"],
        ["4000-10", "Widget sales", 100, 50, "=SUM(C4:D4)"],
        ["4000-20", "Total care plans", 30, 0, "=SUM(C5:D5)"],  # a real line named Total
        [None, "Total Sales", "=SUM(C4:C5)", "=SUM(D4:D5)", "=SUM(E4:E5)"],
        ["COSTS"],
        ["6000-10", "Power", 20, 25, "=SUM(C8:D8)"],
        ["6000-20", "Rates", 0, 0, "=SUM(C9:D9)"],
        [None, "Costs subtotal", "=SUM(C8:C9)", "=SUM(D8:D9)", "=SUM(E8:E9)"],
    ]
    cached = {
        "Ledger": {
            "E4": 150,
            "E5": 30,
            "C6": 130,
            "D6": 50,
            "E6": 180,
            "E8": 45,
            "E9": 0,
            "C10": 20,
            "D10": 25,
            "E10": 45,
        }  # fmt: skip
    }
    return make_xlsx({"Ledger": rows}, cached)


GL_SPEC = {
    "sheet": "Ledger",
    "header_row": 2,
    "data_first_row": 3,
    "data_last_row": None,
    "until_blank_run": None,
    "key_column": "A",
    "record_start": "key_matches_shape",
    "skip": ["total_like", "formula_sum_rows", "section_header", "blank"],
    "row_fields": {
        "account": {"col": "B"},
        "section": {"section_context": True},
        "category": {
            "map_distinct": {
                "from": "section_context",
                "map": {"SALES": "revenue", "COSTS": "Expense"},
            }
        },
        "total": {"col": "E"},
        "active_months": {"derived": {"op": "count_nonzero", "cols": ["C", "D"]}},
    },
    "doc_fields": {},
}


def test_reader_flags_vertical_sum_cells_only():
    got = {b.address: b for b in blocks_of(gl_workbook())}
    assert {"sum_formula=C6", "sum_formula=D6", "sum_formula=E6"} <= set(got["Ledger!B6:E6"].flags)
    assert not any(f.startswith("sum_formula") for f in got["Ledger!A4:E4"].flags)  # row-wise


def test_gl_sections_subtotals_formulas_and_maps():
    _wp, ex, checks = run_spec(GL_SPEC, GL_FIELDS, gl_workbook())
    keys = [e["code"]["value"] for e in ex.entries]
    assert keys == ["4000-10", "4000-20", "6000-10", "6000-20"]  # "Total care plans" kept
    by = {e["code"]["value"]: e for e in ex.entries}
    assert by["4000-10"]["section"]["value"] == "SALES"
    assert by["6000-10"]["category"]["value"] == "Expense"
    assert by["4000-20"]["category"]["value"] == "Revenue"  # mapped to the allowed spelling
    assert by["4000-10"]["active_months"]["value"] == 2
    assert by["4000-20"]["active_months"]["value"] == 1
    assert by["6000-20"]["total"]["value"] == 0
    assert ex.dispositions["skipped-section_header"] == 2
    assert ex.dispositions["skipped-total_like"] + ex.dispositions["skipped-formula_sum_rows"] == 2
    assert checks["C3"].passed is True and checks["C3"].detail["checked"] == 2


def test_map_distinct_needs_listed_allowed_values():
    assert allowed_values("One of: Revenue, Expense, Other.") == ["Revenue", "Expense", "Other"]
    wp = profile_blocks(blocks_of(gl_workbook()))
    bad = dict(GL_SPEC, row_fields={"section": {"map_distinct": {"from": "B", "map": {}}}})
    spec, errors = validate_spec(bad, GL_FIELDS, wp)
    assert spec is None and any("allowed values" in e for e in errors)
    wrong = dict(
        GL_SPEC,
        row_fields={"category": {"map_distinct": {"from": "B", "map": {"x": "Asset"}}}},
    )
    assert validate_spec(wrong, GL_FIELDS, wp)[0] is None


# --- parameters sheet ----------------------------------------------------------------------------

PARAM_FIELDS = {
    "name": "stock_with_params",
    "fields": {
        **FLAT_FIELDS["fields"],
        "report_month": {
            "name": "Report Period",
            "description": "Month and year of the report, as YYYY-MM. Same for every row.",
        },
    },
}


def test_parameters_sheet_label_value_and_heuristic_doc_fields():
    params = [["Report Period", "04/2031"], ["Prepared by", "Invented Clerk"]]
    data = make_xlsx({"Stock": flat_rows(), "Params": params})
    wp = profile_blocks(blocks_of(data))
    assert wp.main == "Stock" and wp.sheets["Params"].is_parameters
    assert 'PARAMETERS "Params"' in preview(wp)
    raw = heuristic.build(PARAM_FIELDS, wp)
    assert raw["doc_fields"]["report_month"] == {"cell": "Params!B1"}
    assert raw["doc_fields"]["depot"] == {"cell": "Stock!B2"}
    spec, errors = validate_spec(raw, PARAM_FIELDS, wp, "heuristic")
    assert errors == []
    ex = execute(spec, wp, PARAM_FIELDS)
    assert {e["report_month"]["value"] for e in ex.entries} == {"2031-04"}
    assert ex.entries[0]["report_month"]["citation"] == "[Params!B1] 04/2031"


def test_heuristic_spec_on_flat_table():
    wp = profile_blocks(blocks_of(make_xlsx({"Stock": flat_rows()})))
    raw = heuristic.build(FLAT_FIELDS, wp)
    assert raw["key_column"] == "A" and raw["record_start"] == "key_nonempty"
    assert raw["row_fields"] == {
        "item_name": {"col": "B", "fold": "first_nonempty"},
        "qty": {"col": "C", "fold": "first_nonempty"},
        "unit_price": {"col": "D", "fold": "first_nonempty"},
    }
    spec, errors = validate_spec(raw, FLAT_FIELDS, wp, "heuristic")
    assert errors == [] and spec.source == "heuristic"
    assert "pick_by_label" not in str(raw) and "derived" not in str(raw)


# --- header repeat, leading zeros, blank money cells -----------------------------------------


def test_header_repeat_mid_sheet_is_skipped():
    data = make_xlsx({"Stock": flat_rows(repeat_at=35)})
    _wp, ex, checks = run_spec(flat_spec(), FLAT_FIELDS, data)
    assert ex.dispositions["skipped-header_repeat"] == 1
    assert len(ex.entries) == 70 and checks["C2"].passed


def test_leading_zero_keys_are_copied_as_displayed():
    rows = [["Code", "Item Name", "Qty"]]
    rows += [[i, f"Part {i}", i] for i in range(1, 11)]
    formats = {"Parts": {f"A{r}": "00000" for r in range(2, 12)}}
    data = make_xlsx({"Parts": rows}, formats=formats)
    raw = flat_spec(sheet="Parts", header_row=1, data_first_row=2, record_start="key_nonempty",
                    doc_fields={}, row_fields={"qty": {"col": "C"}})  # fmt: skip
    fields = {"name": "parts", "fields": {
        "sku": {"name": "Code", "description": "Part code.", "primary": True},
        "qty": {"name": "Qty", "description": "Quantity, as a number."}}}  # fmt: skip
    _wp, ex, _checks = run_spec(raw, fields, data)
    assert [e["sku"]["value"] for e in ex.entries][:2] == ["00001", "00002"]


def test_blank_and_dash_money_cells_are_zero_others_null():
    rows = [["SKU", "Item Name", "Unit Price", "Weight"]]
    rows += [[f"WX-{i}", f"Widget {i}", 3.0, 1.5] for i in range(100, 108)]
    rows += [["WX-200", "Widget blank", None, None], ["WX-201", "Widget dash", "-", "-"]]
    fields = {"name": "w", "fields": {
        "sku": {"name": "SKU", "description": "Code.", "primary": True},
        "unit_price": {"name": "Unit Price", "description": "Price per unit, as a number."},
        "weight": {"name": "Weight", "description": "Weight in kg, as a number."}}}  # fmt: skip
    raw = flat_spec(sheet="W", header_row=1, data_first_row=2, doc_fields={},
                    row_fields={"unit_price": {"col": "C"}, "weight": {"col": "D"}})  # fmt: skip
    _wp, ex, _checks = run_spec(raw, fields, make_xlsx({"W": rows}))
    by = {e["sku"]["value"]: e for e in ex.entries}
    assert by["WX-200"]["unit_price"]["value"] == 0  # R26: blank money cell of a real record
    assert by["WX-200"]["weight"]["value"] is None  # not money: null
    assert by["WX-201"]["unit_price"]["value"] == 0 and by["WX-201"]["weight"]["value"] == 0


# --- wrong specs and the grammar -----------------------------------------------------------------


def test_wrong_key_column_fails_c1_hard():
    raw = flat_spec(key_column="C", record_start="key_nonempty", row_fields={})
    _wp, ex, checks = run_spec(raw, FLAT_FIELDS, make_xlsx({"Stock": flat_rows()}))
    assert checks["C1"].passed is False
    assert spec_score(checks)[1] is True  # hard fail
    assert ex.duplicates > 0


def test_spec_missing_records_fails_c3():
    raw = flat_spec(data_first_row=40)  # half the records are outside the range
    _wp, _ex, checks = run_spec(raw, FLAT_FIELDS, make_xlsx({"Stock": flat_rows()}))
    assert checks["C3"].passed is False


def test_unknown_spec_keys_are_invalid():
    wp = profile_blocks(blocks_of(make_xlsx({"Stock": flat_rows()})))
    spec, errors = validate_spec(flat_spec(extra=1), FLAT_FIELDS, wp)
    assert spec is None and any("unknown keys" in e for e in errors)
    rule = flat_spec(row_fields={"qty": {"col": "C", "scale": 2}})
    assert validate_spec(rule, FLAT_FIELDS, wp)[0] is None
    assert validate_spec(flat_spec(sheet="Nope"), FLAT_FIELDS, wp)[0] is None
    assert validate_spec(flat_spec(skip=["everything"]), FLAT_FIELDS, wp)[0] is None
    assert validate_spec(flat_spec(row_fields={"ghost": {"col": "B"}}), FLAT_FIELDS, wp)[0] is None


def test_no_amount_skip_drops_key_only_records():
    rows = flat_rows(70, total=False) + [["WX-999", "Widget without stock"]]
    raw = flat_spec(skip=["total_like", "header_repeat", "blank", "no_amount"])
    _wp, ex, _checks = run_spec(raw, FLAT_FIELDS, make_xlsx({"Stock": rows}))
    assert len(ex.entries) == 70 and ex.dispositions["skipped-no_amount"] == 1


# --- pipeline ------------------------------------------------------------------------------------


class FakeLLM:
    """Scripted outcomes in order; table spec calls and baseline calls share the queue."""

    def __init__(self, *outcomes: JSONOutcome):
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, list]] = []
        self.catalog = SimpleNamespace(baseline=HAIKU, estimate=Estimate())

    def projection(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        return Projection(Estimate().tokens(messages, kind_chars), 0.01, 0.0, None)

    def complete_json(
        self, ctx, model, messages, *, max_tokens=None, kind_chars=None, salvage=False
    ):
        self.calls.append((ctx.purpose, messages))
        return self.outcomes.pop(0)


def ok(data: dict) -> JSONOutcome:
    return JSONOutcome("ok", data=data)


LONG = make_xlsx({"Stock": flat_rows(70)})


def baseline_answer(n: int = 2) -> JSONOutcome:
    cell = {"value": None, "citation": "", "confidence": 0.5}
    rows = [{**dict.fromkeys(FLAT_FIELDS["fields"], cell), "sku": {
        "value": f"WX-{i}", "citation": "[Stock!A4] x", "confidence": 0.9}}
        for i in range(n)]  # fmt: skip
    return ok({"entries": rows})


def test_pipeline_ai_spec_chosen_and_schema_valid():
    fake = FakeLLM(ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["chosen"] == "ai" and table["calls"] == 1 and table["rows"] == 70
    assert len(out.entries) == 70 and contract_ok(out.entries, FLAT_FIELDS)
    assert out.entries[0]["qty"]["confidence"] == table_spec.CONF_TOTALS  # C3 passed
    assert fake.calls[0][0] == "table_spec"
    user = fake.calls[0][1][1]["content"]
    assert user.index("SPREADSHEET PREVIEW") < user.index("FIELDS:")  # field list last
    assert "[row key]" in user


def test_pipeline_invalid_spec_then_repaired():
    fake = FakeLLM(ok(flat_spec(sheet="Nope")), ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["calls"] == 2 and table["ai_spec"]["repaired"] is True
    assert table["chosen"] == "ai"
    repair = fake.calls[1][1][-1]["content"]
    assert "validator rejected" in repair and "Keep every valid entry" in repair
    assert fake.calls[1][0] == "table_spec_repair"


def test_pipeline_garbage_spec_heuristic_wins():
    fake = FakeLLM(JSONOutcome("unusable", reason="llm_unusable"))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["ai_spec"]["valid"] is False and table["chosen"] == "heuristic"
    assert len(out.entries) == 70 and contract_ok(out.entries, FLAT_FIELDS)
    assert out.entries[0]["qty"]["confidence"] == table_spec.CONF_HEURISTIC


def test_pipeline_invalid_twice_gives_up_after_one_repair():
    fake = FakeLLM(ok({"sheet": "Nope"}), ok({"sheet": "Nope"}))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["calls"] == 2 and table["chosen"] == "heuristic"


def test_pipeline_both_hard_fail_falls_back_to_baseline():
    rows = [["Kind", "Qty"]] + [["Small" if i % 2 else "Large", i] for i in range(80)]
    data = make_xlsx({"Bins": rows})
    fields = {"name": "bins", "fields": {
        "serial": {"name": "Serial", "description": "Serial.", "primary": True},
        "qty": {"name": "Qty", "description": "Quantity, as a number."}}}  # fmt: skip
    serial = {"value": "S-1", "citation": "[Bins!A2] x", "confidence": 0.5}
    qty = {"value": 1, "citation": "[Bins!B2] 1", "confidence": 0.5}
    answer = ok({"entries": [{"serial": serial, "qty": qty}]})
    fake = FakeLLM(JSONOutcome("unusable", reason="llm_unusable"), answer)
    out = table_spec.extract(fake, CTX, fields, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["chosen"] == "fallback" and table["fallback_result"] == "baseline"
    assert table["candidates"]["heuristic"]["hard_fail"] is True
    assert [c[0] for c in fake.calls] == ["table_spec", "extract"]
    assert out.entries is not None and contract_ok(out.entries, fields)


def _cand(score: int, filled: float, hard: bool = False) -> dict:
    return {
        "score": score,
        "filled": filled,
        "hard_fail": hard,
        "rank": table_spec.rank(score, filled),
    }


def test_winner_ai_fills_many_with_one_soft_fail_beats_heuristic_key_only():
    # AI: 4 checks (one soft fail), 9 of 10 fields; heuristic: 5 checks, 0 fields
    cands = {"ai": _cand(4, 0.9), "heuristic": _cand(5, 0.0)}
    assert table_spec.choose(cands) == "ai"


def test_winner_equal_fills_more_checks_wins_and_ties_go_to_ai():
    assert table_spec.choose({"ai": _cand(3, 0.5), "heuristic": _cand(4, 0.5)}) == "heuristic"
    assert table_spec.choose({"ai": _cand(4, 0.5), "heuristic": _cand(4, 0.5)}) == "ai"


def test_winner_hard_fail_never_wins():
    cands = {"ai": _cand(5, 1.0, hard=True), "heuristic": _cand(2, 0.0)}
    assert table_spec.choose(cands) == "heuristic"
    both = {"ai": _cand(5, 1.0, hard=True), "heuristic": _cand(4, 1.0, hard=True)}
    assert table_spec.choose(both) is None


def test_winner_rule_on_a_sheet_ai_fills_more_despite_soft_fail():
    # the AI spec fills 2 of 3 row fields but soft-fails C3 (the total disagrees) and C4
    # (unit_price read from a text column); the heuristic sees no headers here, maps only the
    # key and passes more checks. Old rule: heuristic. New rule: 3 + 2*(2/3) > 4 + 0 -> AI.
    rows = [["Invented stock list"], ["Depot:", "North Widget Yard"], [None, None, "Jan", None]]
    names = [f"Widget {chr(65 + i % 26)}{chr(65 + i // 26)}" for i in range(70)]  # no digits
    rows += [[f"WX-{100 + i}", names[i], i % 7 + 1, 2.5 + i] for i in range(70)]
    rows.append([None, "Total", 999, None])
    data = make_xlsx({"Stock": rows})
    ai = flat_spec(row_fields={"item_name": {"col": "B"}, "qty": {"col": "C"},
                               "unit_price": {"col": "B"}})  # fmt: skip
    out = table_spec.extract(FakeLLM(ok(ai)), CTX, FLAT_FIELDS, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    cand = table["candidates"]
    assert cand["ai"]["checks"]["C3"]["passed"] is False
    assert cand["ai"]["checks"]["C4"]["passed"] is False
    assert not cand["ai"]["hard_fail"]
    assert round(cand["ai"]["filled"], 4) == 0.6667 and cand["heuristic"]["filled"] == 0.0
    assert cand["heuristic"]["score"] > cand["ai"]["score"]
    assert table["chosen"] == "ai"


def test_filled_fraction_ignores_primary_and_doc_level_fields():
    assert table_spec.row_level_fields(FLAT_FIELDS) == ["item_name", "qty", "unit_price"]

    def row(name, qty):
        return {"item_name": {"value": name}, "qty": {"value": qty}, "unit_price": {"value": None}}

    entries = [row("x", None), row(None, 0)]  # 0 is a value, None is not
    assert table_spec.filled_fraction(entries, ["item_name", "qty", "unit_price"]) == 2 / 3


def test_short_table_takes_the_spec_path():  # P6b B-2: no length threshold
    short = blocks_of(make_xlsx({"Stock": flat_rows(20)}))
    fake = FakeLLM(ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, short, "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["why"] == "table" and table["chosen"] == "ai" and table["rows"] == 20
    assert [c[0] for c in fake.calls] == ["table_spec"]  # the model never types the rows
    assert len(out.entries) == 20 and contract_ok(out.entries, FLAT_FIELDS)


def test_sheet_without_data_lines_keeps_the_current_path():
    empty = blocks_of(make_xlsx({"Stock": [["SKU", "Item Name"]]}))
    ok_, why, _wp = table_spec.applies(FLAT_FIELDS, empty, "xlsx")
    assert not ok_ and why == "no_table"


def test_pdf_keeps_the_current_path():
    pages = [Block("paragraph", f"Page {i}", f"WX-{i} widget line", page=i) for i in range(1, 90)]
    fake = FakeLLM(baseline_answer())
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, pages, "pdf")
    assert [c[0] for c in fake.calls] == ["extract"] and "extraction" not in out.notes


def test_switch_routes_and_defaults_to_baseline():
    single = {"name": "s", "fields": {"a": {"name": "A", "description": "A."}}}
    off, on = Settings(), Settings(table_path="spec")
    assert off.table_path == "baseline"
    assert worker.choose_pipeline(off, FLAT_FIELDS) is baseline
    assert worker.choose_pipeline(on, FLAT_FIELDS) is table_spec
    assert worker.choose_pipeline(on, single) is baseline
    both = Settings(table_path="spec", single_value_path="smart")
    assert worker.choose_pipeline(both, single) is single_value
    with pytest.raises(ValueError):
        Settings(table_path="fast")


def test_switch_from_env(monkeypatch):
    monkeypatch.setenv("EXTRACT_TABLE_PATH", " Spec ")
    assert Settings.from_env().table_path == "spec"
    monkeypatch.delenv("EXTRACT_TABLE_PATH")
    assert Settings.from_env().table_path == "baseline"


def test_switch_off_output_identical_on_long_table():
    blocks = blocks_of(LONG)
    via_worker = worker.choose_pipeline(Settings(), FLAT_FIELDS).extract(
        FakeLLM(baseline_answer()), CTX, FLAT_FIELDS, blocks, "xlsx"
    )
    direct = baseline.extract(FakeLLM(baseline_answer()), CTX, FLAT_FIELDS, blocks, "xlsx")
    assert via_worker.entries == direct.entries and via_worker.notes == direct.notes


def test_results_pass_the_frozen_validator_with_schema_shape():
    for outcome in (ok(flat_spec()), JSONOutcome("unusable", reason="llm_unusable")):
        out = table_spec.extract(FakeLLM(outcome), CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
        meta = {"model_calls": 1, "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0,
                "latency_ms": 1, **out.notes}  # fmt: skip
        doc = {"schema": "widget_stock", "document": "invented", "entries": out.entries,
               "metadata": meta}  # fmt: skip
        assert validator.validate_contract(doc, FLAT_FIELDS) == []


def test_plan_reports_path_tokens_and_cost():
    from app.llm.models import ModelCatalog

    cat = ModelCatalog.load()
    rec = table_spec.plan(FLAT_FIELDS, blocks_of(LONG), "xlsx", cat)
    # 1 spec call; at most 1 repair (broken core) + 1 fresh retry (key-only winner)
    assert rec["path"] == "table_spec" and rec["calls_planned"] == 1 and rec["calls_max"] == 3
    assert 0 < rec["est_usd_realistic"] <= rec["est_usd_fuse"] < 0.08
    short = table_spec.plan(
        FLAT_FIELDS, blocks_of(make_xlsx({"Stock": flat_rows(20)})), "xlsx", cat
    )
    assert short["path"] == "table_spec" and short["why"] == "table"
    pdf = [Block("paragraph", "Page 1", "WX-1 widget line", page=1)]
    assert table_spec.plan(FLAT_FIELDS, pdf, "pdf", cat)["path"] == "baseline"


def test_metadata_carries_no_cell_text():
    out = table_spec.extract(FakeLLM(ok(flat_spec())), CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    text = str(out.notes)
    assert "Widget" not in text and "North Widget Yard" not in text and "WX-1" not in text


# --- P6b B-3: per-entry salvage ------------------------------------------------------------------


def test_salvage_drops_bad_entries_and_keeps_the_rest():
    wp = profile_blocks(blocks_of(LONG))
    raw = flat_spec(
        extra=1,
        row_fields={"item_name": {"col": "B"}, "qty": {"col": "C", "scale": 2},
                    "unit_price": {"col": "D"}, "ghost": {"col": "E"}},
        doc_fields={"depot": {"cell": "Nowhere!B2"}},
    )  # fmt: skip
    spec, core, dropped = salvage_spec(raw, FLAT_FIELDS, wp)
    assert core == [] and spec is not None
    assert set(spec.row_fields) == {"item_name", "unit_price"} and spec.doc_fields == {}
    assert len(dropped) == 4  # unknown top key, bad rule, unknown field, bad cell
    assert validate_spec(raw, FLAT_FIELDS, wp)[0] is None  # the strict check still refuses


def test_salvage_broken_core_gives_no_spec():
    wp = profile_blocks(blocks_of(LONG))
    spec, core, dropped = salvage_spec(flat_spec(sheet="Nope", key_column="1"), FLAT_FIELDS, wp)
    assert spec is None and len(core) == 2 and dropped == []


def test_pipeline_bad_entry_is_dropped_without_a_repair_call():
    raw = flat_spec(
        extra=1, row_fields={"item_name": {"col": "B"}, "qty": {"col": "C", "scale": 2},
                             "unit_price": {"col": "D"}})  # fmt: skip
    fake = FakeLLM(ok(raw))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    table = out.notes["extraction"]["table"]
    assert [c[0] for c in fake.calls] == ["table_spec"]
    assert table["ai_spec"]["valid"] is True and table["ai_spec"]["entries_dropped"] == 2
    assert table["ai_spec"]["repaired"] is False
    # the salvaged AI spec keeps 2 of 3 row fields (qty dropped), not key-only, no retry
    assert round(table["candidates"]["ai"]["filled"], 4) == 0.6667 and "retry" not in table
    # the heuristic maps all 3 here and outranks it
    assert table["chosen"] == "heuristic"
    assert all(e["qty"]["value"] is not None for e in out.entries)


def test_repair_prompt_lists_only_core_errors():
    raw = flat_spec(sheet="Nope", row_fields={"item_name": {"col": "B"}, "ghost": {"col": "E"}})
    fake = FakeLLM(ok(raw), ok(flat_spec()))
    table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    repair = fake.calls[1][1][-1]["content"]
    assert "sheet:" in repair and "ghost" not in repair


# --- P6b B-4: field-level merge ------------------------------------------------------------------


def renamed(rows: list[list], header: list[str]) -> list[list]:
    """Replace the header line of flat_rows (third line) with invented header texts."""
    return rows[:2] + [header] + rows[3:]


def test_merge_fills_fields_the_winner_left_unmapped():
    # the heuristic cannot match "Label" to Item Name; the AI maps item_name + qty only
    data = make_xlsx({"Stock": renamed(flat_rows(70), ["SKU", "Label", "Qty", "Unit Price"])})
    h_raw = heuristic.build(FLAT_FIELDS, profile_blocks(blocks_of(data)))
    assert "item_name" not in h_raw["row_fields"] and "unit_price" in h_raw["row_fields"]
    ai = flat_spec(row_fields={"item_name": {"col": "B"}, "qty": {"col": "C"}})
    out = table_spec.extract(FakeLLM(ok(ai)), CTX, FLAT_FIELDS, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    cand = table["candidates"]
    assert table["chosen"] == "merged" and cand["merged"]["base"] == "ai"
    assert cand["merged"]["filled"] == 1.0 and cand["merged"]["rank"] >= cand["ai"]["rank"]
    assert all(e["unit_price"]["value"] is not None for e in out.entries)
    assert contract_ok(out.entries, FLAT_FIELDS)


def test_merge_that_breaks_c3_is_not_chosen():
    rows = flat_rows(70)
    rows[-1] = [None, "Total", rows[-1][2], 1.0]  # the price total does not add up
    data = make_xlsx({"Stock": renamed(rows, ["SKU", "Label", "Qty", "Unit Price"])})
    ai = flat_spec(row_fields={"item_name": {"col": "B"}, "qty": {"col": "C"}})
    out = table_spec.extract(FakeLLM(ok(ai)), CTX, FLAT_FIELDS, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    cand = table["candidates"]
    assert cand["ai"]["checks"]["C3"]["passed"] is True
    assert cand["merged"]["checks"]["C3"]["passed"] is False
    assert cand["merged"]["rank"] < cand["ai"]["rank"] and table["chosen"] == "ai"


def test_merge_needs_the_same_sheet_and_key_column():
    wp = profile_blocks(blocks_of(LONG))

    def spec(**over):
        return validate_spec(flat_spec(**over), FLAT_FIELDS, wp)[0]

    win = spec(row_fields={"item_name": {"col": "B"}})
    other_key = spec(key_column="B", row_fields={"qty": {"col": "C"}})
    same = spec(record_start="key_nonempty", row_fields={"qty": {"col": "C"}})
    col = spec(record_start="column_nonempty:C", row_fields={"qty": {"col": "C"}})
    assert table_spec.merge_spec(win, [other_key]) == (None, 0)
    assert table_spec.merge_spec(win, [col]) == (None, 0)
    merged, added = table_spec.merge_spec(win, [same])
    assert added == 1 and set(merged.row_fields) == {"item_name", "qty"}
    assert merged.record_start == win.record_start  # the winner's core is kept


def test_merge_never_overrides_a_winner_entry():
    wp = profile_blocks(blocks_of(LONG))
    win = validate_spec(flat_spec(), FLAT_FIELDS, wp)[0]
    other = validate_spec(flat_spec(row_fields={"qty": {"col": "D"}}), FLAT_FIELDS, wp)[0]
    assert table_spec.merge_spec(win, [other]) == (None, 0)


# --- P6b B-5: fresh retry when the chosen spec is key-only -------------------------------------

NO_MATCH = ["Code", "Label", "Count", "Each"]  # invented headers the heuristic cannot match


def test_key_only_winner_gets_one_fresh_retry():
    data = make_xlsx({"Stock": renamed(flat_rows(70), NO_MATCH)})
    fake = FakeLLM(ok(flat_spec(row_fields={})), ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    assert [c[0] for c in fake.calls] == ["table_spec", "table_spec_retry"]
    assert len(fake.calls[1][1]) == 2  # fresh: system + user, no repair history
    assert table["calls"] == 2 and table["retry"]["valid"] is True
    assert table["candidates"]["heuristic"]["filled"] == 0.0
    assert table["chosen"] == "retry" and table["candidates"]["retry"]["filled"] == 1.0


def test_retry_happens_at_most_once():
    data = make_xlsx({"Stock": renamed(flat_rows(70), NO_MATCH)})
    fake = FakeLLM(ok(flat_spec(row_fields={})), ok(flat_spec(row_fields={})))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["calls"] == 2 and table["chosen"] == "ai"  # tie -> the first spec


def test_no_retry_when_a_field_is_filled_or_the_model_was_stopped():
    fake = FakeLLM(ok(flat_spec()))
    table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    assert len(fake.calls) == 1
    data = make_xlsx({"Stock": renamed(flat_rows(70), NO_MATCH)})
    stopped = FakeLLM(JSONOutcome("stopped", reason="doc_llm_cap"))
    out = table_spec.extract(stopped, CTX, FLAT_FIELDS, blocks_of(data), "xlsx")
    assert len(stopped.calls) == 1 and out.notes["extraction"]["table"]["chosen"] == "heuristic"


# --- P6b B-6: truncation / loop flags on the old path ------------------------------------------


def test_baseline_flags_truncated_and_looping_answers_without_retry():
    pages = [Block("paragraph", "Page 1", "WX-1 widget line", page=1)]
    cases = [
        (replace(baseline_answer(), finish_reason="length"), ["truncated_output"]),
        (replace(baseline_answer(), repetition=0.4), ["repetition_loop"]),
        (
            replace(baseline_answer(), finish_reason="length", repetition=0.9),
            ["truncated_output", "repetition_loop"],
        ),
    ]
    for outcome, flags in cases:
        fake = FakeLLM(outcome)
        out = baseline.extract(fake, CTX, FLAT_FIELDS, pages, "pdf")
        assert out.notes["output_flags"] == flags and len(fake.calls) == 1
        assert out.entries is not None  # flagged, still used
    clean = baseline.extract(FakeLLM(baseline_answer()), CTX, FLAT_FIELDS, pages, "pdf")
    assert "output_flags" not in clean.notes
    cut = FakeLLM(JSONOutcome("unusable", reason="llm_truncated", finish_reason="length"))
    bad = baseline.extract(cut, CTX, FLAT_FIELDS, pages, "pdf")
    assert bad.entries is None and bad.notes["output_flags"] == ["truncated_output"]
