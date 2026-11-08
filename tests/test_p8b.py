"""P8b Part A: date / number from cell text (Z-2), the merge's document-field guard (Z-3) and
scan page choice for the baseline single-value path (Z-13).

Every sheet, field list and page here is invented (R31). No network, no key.
"""

from __future__ import annotations

import importlib.util

import pytest
from conftest import ROOT
from test_single_value import CTX as SV_CTX
from test_single_value import SCAN_FIELDS, scan_pages, valid
from test_single_value import FakeLLM as ScriptLLM
from test_single_value import ok as sv_ok
from test_tables import (
    CTX,
    FLAT_FIELDS,
    LONG,
    FakeLLM,
    blocks_of,
    contract_ok,
    flat_rows,
    flat_spec,
    make_xlsx,
    ok,
)

from app import worker
from app.config import Settings
from app.extract.compile_fields import compile_fields
from app.llm import JSONOutcome
from app.pipeline import baseline, baseline_located, single_value, table_spec
from app.readers.base import Block
from app.tables import heuristic
from app.tables.execute import execute
from app.tables.profile import profile_blocks
from app.tables.spec import salvage_spec, validate_spec

# --- invented weekly count sheet -----------------------------------------------------------------

WEEK_FIELDS = {
    "name": "widget_count",
    "fields": {
        "sku": {"name": "SKU", "description": "Stock keeping unit code. One per row.",
                "primary": True},
        "qty": {"name": "Quantity", "description": "Units counted, as a number."},
        "week_start": {"name": "Week Start Date",
                       "description": "Date the counting week starts. Same for every row."},
        "week_end": {"name": "Week End Date",
                     "description": "Date the counting week ends. Same for every row."},
        "count_date": {"name": "Count Date",
                       "description": "Date of the count. Same for every row."},
        "start_month": {"name": "Start Month",
                        "description": "Month the period starts, as YYYY-MM. Same for every row."},
        "period_end": {"name": "Period End Date",
                       "description": "Date the reporting period ends, period end date. "
                                      "Same for every row."},
        "lot_window": {"name": "Lot Window End", "description": "Date the lot window ends."},
    },
}  # fmt: skip

HEADER = "Week of Mar 2, 2031 – Mar 8, 2031"
PERIOD = "Period: Jan 2031 – Dec 2031"


def week_rows(n: int = 30, header: str = HEADER, period: str = PERIOD) -> list[list]:
    rows: list[list] = [[header], [period], ["SKU", "Qty", "Lot window"]]
    rows += [[f"WK-{100 + i}", i % 5 + 1, "Jan 3, 2031 - Jan 9, 2031"] for i in range(n)]
    return rows


def week_spec(**over) -> dict:
    spec = {
        "sheet": "Count",
        "header_row": 3,
        "data_first_row": 4,
        "data_last_row": None,
        "until_blank_run": None,
        "key_column": "A",
        "record_start": "key_matches_shape",
        "skip": ["total_like", "header_repeat", "blank"],
        "row_fields": {"qty": {"col": "B"}},
        "doc_fields": {},
    }
    spec.update(over)
    return spec


def run_spec(raw: dict, rows: list[list] | None = None):
    wp = profile_blocks(blocks_of(make_xlsx({"Count": rows or week_rows()})))
    spec, errors = validate_spec(raw, WEEK_FIELDS, wp)
    assert spec is not None, errors
    return execute(spec, wp, WEEK_FIELDS), wp


def test_invented_fields_compile_to_the_types_the_tests_need():
    specs = compile_fields(WEEK_FIELDS)
    assert specs["week_start"].type == "date" and specs["week_start"].date_role == "start"
    assert specs["week_end"].type == "date" and specs["week_end"].date_role == "end"
    assert specs["count_date"].type == "date" and specs["count_date"].date_role is None
    assert specs["start_month"].type == "month"
    assert specs["period_end"].type == "date" and specs["period_end"].date_role == "period_end"
    assert specs["qty"].type in ("number", "integer")


# --- Z-2: parse ----------------------------------------------------------------------------------


def test_week_of_header_cell_gives_start_and_end():
    ex, _wp = run_spec(week_spec(doc_fields={
        "week_start": {"cell": "Count!A1", "parse": "date_start"},
        "week_end": {"cell": "Count!A1", "parse": "date_end"},
        "count_date": {"cell": "Count!A1", "parse": "date_end"},
    }))  # fmt: skip
    e = ex.entries[0]
    assert e["week_start"]["value"] == "2031-03-02"
    assert e["week_end"]["value"] == "2031-03-08"
    assert e["count_date"]["value"] == "2031-03-08"  # a role-less field: the parse decides
    assert e["week_end"]["source_locations"] == ["Count!A1"]
    assert e["week_end"]["citation"].startswith("[Count!A1] ")
    assert all(x["week_start"] == e["week_start"] for x in ex.entries)  # repeated (R30)
    assert ex.field_sources["week_end"] == "doc"


def test_a_range_without_parse_on_a_roleless_field_stays_null():
    ex, _wp = run_spec(week_spec(doc_fields={"count_date": {"cell": "Count!A1"}}))
    assert ex.entries[0]["count_date"]["value"] is None


def test_period_month_year_range_as_the_field_asks():
    ex, _wp = run_spec(week_spec(doc_fields={
        "start_month": {"cell": "Count!A2", "parse": "date_start"},
        "period_end": {"cell": "Count!A2", "parse": "date_end"},
        "week_start": {"cell": "Count!A2", "parse": "date_start"},
    }))  # fmt: skip
    e = ex.entries[0]
    assert e["start_month"]["value"] == "2031-01"  # a month field: the month
    assert e["period_end"]["value"] == "2031-12-31"  # period end: the month's last day
    assert e["week_start"]["value"] is None  # a day is never invented (R24)


def test_unparseable_cell_text_is_null_not_a_guess():
    rows = week_rows(header="Week of the big spring count", period="Period: to be confirmed")
    ex, _wp = run_spec(week_spec(doc_fields={
        "week_start": {"cell": "Count!A1", "parse": "date_start"},
        "period_end": {"cell": "Count!A2", "parse": "date_end"},
    }), rows)  # fmt: skip
    e = ex.entries[0]
    assert e["week_start"] == {"value": None, "citation": ""}
    assert e["period_end"] == {"value": None, "citation": ""}


def test_parse_on_a_row_field_reads_a_range_in_one_cell():
    ex, _wp = run_spec(week_spec(row_fields={
        "qty": {"col": "B"}, "lot_window": {"col": "C", "parse": "date_end"}}))  # fmt: skip
    assert {e["lot_window"]["value"] for e in ex.entries} == {"2031-01-09"}
    assert ex.field_sources["lot_window"] == "col"
    assert ex.parse["lot_window"] == [len(ex.entries), len(ex.entries)]


def test_parse_number_and_text_on_doc_cells():
    fields = {
        **FLAT_FIELDS,
        "fields": {
            **FLAT_FIELDS["fields"],
            "pallets": {
                "name": "Pallets",
                "description": "Pallets on site, as a number. Same for every row.",
            },
        },
    }
    rows = flat_rows(70)
    rows[0] = ["Invented stock list", "Pallets on site: 42"]
    wp = profile_blocks(blocks_of(make_xlsx({"Stock": rows})))
    raw = flat_spec(
        doc_fields={
            "depot": {"cell": "Stock!B2", "parse": "text"},
            "pallets": {"cell": "Stock!B1", "parse": "number"},
        }
    )
    spec, errors = validate_spec(raw, fields, wp)
    assert spec is not None, errors
    e = execute(spec, wp, fields).entries[0]
    assert e["pallets"]["value"] == 42 and e["depot"]["value"] == "North Widget Yard"


def test_grammar_rejects_bad_parse_entries_one_by_one():
    wp = profile_blocks(blocks_of(make_xlsx({"Count": week_rows()})))
    raw = week_spec(
        row_fields={
            "qty": {"col": "B", "parse": "date_end"},  # date parse on a number field
            "lot_window": {"col": "C", "fold": "sum", "parse": "date_end"},  # sum + parse
        },
        doc_fields={
            "week_start": {"cell": "Count!A1", "parse": "weekday"},  # unknown parse
            "week_end": {"cell": "Count!A1", "parse": "date_end", "x": 1},  # extra key
            "period_end": {"cell": "Count!A2", "parse": "date_end"},  # fine
        },
    )
    spec, core, dropped = salvage_spec(raw, WEEK_FIELDS, wp)
    assert core == [] and spec is not None
    assert spec.row_fields == {} and set(spec.doc_fields) == {"period_end"}
    assert spec.doc_parse == {"period_end": "date_end"}
    assert len(dropped) == 4
    ok_rule = week_spec(
        row_fields={
            "lot_window": {
                "pick_by_label": {"label_col": "A", "label_text": "WK-101", "value_col": "C"},
                "parse": "date_end",
            }
        }
    )
    assert validate_spec(ok_rule, WEEK_FIELDS, wp)[0] is not None
    bad_kind = week_spec(row_fields={"qty": {"section_context": True, "parse": "number"}})
    assert validate_spec(bad_kind, WEEK_FIELDS, wp)[0] is None


COUNT_WEEK = {"name": "Counting Week Date",
              "description": "Last day of the counting week. Same for every row."}  # fmt: skip


def test_heuristic_adds_a_parse_for_a_labelled_date_range():
    fields = {"name": "widget_count", "fields": {
        "sku": WEEK_FIELDS["fields"]["sku"], "qty": WEEK_FIELDS["fields"]["qty"],
        "week_end": COUNT_WEEK,
        "count_date": {"name": "Count Date",
                       "description": "Date of the count. Same for every row."},
    }}  # fmt: skip
    rows = week_rows(header="Counting week: Mar 2, 2031 - Mar 8, 2031", period="Count date:")
    rows[1] = ["Count date:", "Depot north"]  # label matched, but no date in the cell text
    wp = profile_blocks(blocks_of(make_xlsx({"Count": rows})))
    raw = heuristic.build(fields, wp)
    assert raw["doc_fields"]["week_end"] == {"cell": "Count!A1", "parse": "date_end"}
    assert raw["doc_fields"]["count_date"] == {"cell": "Count!B2"}
    spec, errors = validate_spec(raw, fields, wp, "heuristic")
    assert spec is not None, errors
    assert execute(spec, wp, fields).entries[0]["week_end"]["value"] == "2031-03-08"


def test_spec_prompt_teaches_parse_with_an_invented_example():
    s = table_spec.SYSTEM
    for word in ('"parse"', "date_start", "date_end", '"number"', '"text"'):
        assert word in s
    assert '"count_date": {"cell": "Ledger!A2", "parse": "date_end"}' in s


# --- Z-3: merge document-field guard --------------------------------------------------------------


def _week_specs(winner_doc: dict, other_doc: dict, rows: list[list] | None = None):
    wp = profile_blocks(blocks_of(make_xlsx({"Count": rows or week_rows()})))
    win = validate_spec(week_spec(doc_fields=winner_doc), WEEK_FIELDS, wp)[0]
    other = validate_spec(week_spec(doc_fields=other_doc), WEEK_FIELDS, wp, "heuristic")[0]
    return win, other, wp


def test_merge_takes_a_doc_cell_only_where_the_winner_value_is_null():
    win, other, wp = _week_specs(
        {"count_date": {"cell": "Count!A1"}},  # mapped, but null (a range, no parse)
        {"count_date": {"cell": "Count!A1", "parse": "date_end"}},
    )
    merged, added = table_spec.merge_spec(win, [other], wp, WEEK_FIELDS)
    assert added == 1 and merged.doc_parse == {"count_date": "date_end"}
    assert execute(merged, wp, WEEK_FIELDS).entries[0]["count_date"]["value"] == "2031-03-08"


def test_merge_keeps_a_non_null_winner_value():
    win, other, wp = _week_specs(
        {"week_end": {"cell": "Count!A1", "parse": "date_end"}},
        {"week_end": {"cell": "Count!A1", "parse": "date_start"}},
    )
    assert table_spec.merge_spec(win, [other], wp, WEEK_FIELDS) == (None, 0)


def test_merge_drops_a_doc_cell_that_does_not_normalise():
    win, other, wp = _week_specs({}, {"week_end": {"cell": "Count!C3"}})  # a header text cell
    assert table_spec.merge_spec(win, [other], wp, WEEK_FIELDS) == (None, 0)


def test_merge_replaces_a_raw_text_fallback_with_a_typed_value():
    # a field typed only from a noun keeps unparsed cell text as text; the guard does not
    # count that as a value of the field's type, so a parsed date may take its place
    fields = {"name": "widget_count", "fields": {
        "sku": WEEK_FIELDS["fields"]["sku"], "qty": WEEK_FIELDS["fields"]["qty"],
        "week_tag": {"name": "Counting Week",
                     "description": "Date of the counting week. Same for every row."},
    }}  # fmt: skip
    wp = profile_blocks(blocks_of(make_xlsx({"Count": week_rows()})))
    win = validate_spec(week_spec(doc_fields={"week_tag": {"cell": "Count!A1"}}), fields, wp)[0]
    assert isinstance(execute(win, wp, fields).entries[0]["week_tag"]["value"], str)
    other_raw = week_spec(doc_fields={"week_tag": {"cell": "Count!A1", "parse": "date_start"}})
    other = validate_spec(other_raw, fields, wp, "heuristic")[0]
    merged, added = table_spec.merge_spec(win, [other], wp, fields)
    assert added == 1
    assert execute(merged, wp, fields).entries[0]["week_tag"]["value"] == "2031-03-02"


def _cand(rank: float, doc_filled: int) -> dict:
    return {"rank": rank, "doc_filled": doc_filled, "hard_fail": False}


def test_doc_fields_break_rank_ties_then_ai_wins():
    assert table_spec.choose({"ai": _cand(6, 0), "merged": _cand(6, 1)}) == "merged"
    assert table_spec.choose({"ai": _cand(6, 1), "merged": _cand(6, 1)}) == "ai"
    assert table_spec.choose({"ai": _cand(6, 1), "heuristic": _cand(6, 2)}) == "heuristic"
    assert table_spec.choose({"ai": _cand(6, 2), "heuristic": _cand(6.5, 0)}) == "heuristic"


def test_pipeline_merge_adds_the_heuristic_date_and_reports_doc_filled():
    fields = {"name": "widget_count", "fields": {
        "sku": WEEK_FIELDS["fields"]["sku"], "qty": WEEK_FIELDS["fields"]["qty"],
        "week_end": COUNT_WEEK,
    }}  # fmt: skip
    rows = week_rows(header="Counting week: Mar 2, 2031 - Mar 8, 2031")
    data = make_xlsx({"Count": rows})
    ai = week_spec(doc_fields={"week_end": {"cell": "Count!A2"}})  # wrong cell: no date there
    out = table_spec.extract(FakeLLM(ok(ai)), CTX, fields, blocks_of(data), "xlsx")
    table = out.notes["extraction"]["table"]
    cand = table["candidates"]
    assert cand["ai"]["doc_filled"] == 0 and cand["heuristic"]["doc_filled"] == 1
    assert table["chosen"] in ("merged", "heuristic")
    assert {e["week_end"]["value"] for e in out.entries} == {"2031-03-08"}
    assert contract_ok(out.entries, fields)


def test_pipeline_merge_never_replaces_the_ai_depot():
    out = table_spec.extract(FakeLLM(ok(flat_spec())), CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx")
    table = out.notes["extraction"]["table"]
    assert table["chosen"] == "ai" and "merged" not in table["candidates"]


# --- Z-13: scan page choice on the baseline path --------------------------------------------------


def base_answer() -> JSONOutcome:
    cell = {"value": "Example Tenant LLC", "citation": "[Page 3] Tenant", "confidence": 0.8}
    null = {"value": None, "citation": "", "confidence": 0.5}
    return sv_ok({"entries": [{"tenant_name": cell, "monthly_rent": null}]})


def image_pages(messages) -> list[int]:
    parts = messages[1]["content"]
    texts = [p["text"] for p in parts if p["type"] == "text"]
    return [int(t.split("]")[0]) for x in texts for t in x.split("[Page ")[1:]]


def test_switch_defaults_to_first_and_validates():
    assert Settings().scan_page_method == "first"
    assert Settings(scan_page_method="locate").scan_page_method == "locate"
    with pytest.raises(ValueError):
        Settings(scan_page_method="all")


def test_switch_from_env(monkeypatch):
    monkeypatch.setenv("SCAN_PAGE_METHOD", " Locate ")
    assert Settings.from_env().scan_page_method == "locate"
    monkeypatch.delenv("SCAN_PAGE_METHOD")
    assert Settings.from_env().scan_page_method == "first"


def test_switch_routes_single_value_lists_only():
    on = Settings(scan_page_method="locate")
    assert worker.choose_pipeline(Settings(), SCAN_FIELDS) is baseline
    assert worker.choose_pipeline(on, SCAN_FIELDS) is baseline_located
    assert worker.choose_pipeline(on, FLAT_FIELDS) is baseline  # table lists unchanged
    smart = Settings(scan_page_method="locate", single_value_path="smart")
    assert worker.choose_pipeline(smart, SCAN_FIELDS) is single_value


def test_locate_picks_pages_for_todays_baseline_prompt():
    locate = [
        sv_ok({"pages": {"tenant_name": [3, 99], "monthly_rent": [11]}}),  # 99: not a real page
        sv_ok({"pages": {"monthly_rent": [11, 7]}}),
    ]
    fake = ScriptLLM({"locate": locate, "extract": [base_answer()]})
    out = baseline_located.extract(fake, SV_CTX, SCAN_FIELDS, scan_pages(12), "pdf")
    assert [c[0] for c in fake.calls] == ["locate", "locate", "extract"]
    read = fake.calls[2][1]
    assert read[0]["content"].startswith(baseline.RULES)  # today's baseline prompt, no checker
    assert image_pages(read) == [3, 7, 11]  # page order
    sp = out.notes["scan_pages"]
    assert sp == {"method": "locate", "image_pages": 12, "locate_calls": 2,
                  "result": "located", "pages_chosen": [3, 7, 11]}  # fmt: skip
    assert out.notes["images_sent"] == 3 and out.notes["pipeline"] == baseline.PIPELINE
    assert out.entries is not None and valid(out.entries, SCAN_FIELDS)


def test_locate_without_usable_pages_falls_back_to_first_pages():
    unusable = JSONOutcome("unusable", reason="llm_unusable")
    fake = ScriptLLM({"locate": [unusable, unusable], "extract": [base_answer()]})
    out = baseline_located.extract(fake, SV_CTX, SCAN_FIELDS, scan_pages(12), "pdf")
    assert image_pages(fake.calls[-1][1]) == list(range(1, 9))
    sp = out.notes["scan_pages"]
    assert sp["result"] == "fallback_first" and sp["reason"] == "no_pages"
    assert out.notes["pages_dropped"] == [9, 10, 11, 12]


def test_locate_stop_falls_back_to_first_pages():
    stopped = JSONOutcome("stopped", reason="doc_llm_cap")
    fake = ScriptLLM({"locate": [stopped], "extract": [base_answer()]})
    out = baseline_located.extract(fake, SV_CTX, SCAN_FIELDS, scan_pages(12), "pdf")
    assert [c[0] for c in fake.calls] == ["locate", "extract"]
    sp = out.notes["scan_pages"]
    assert sp["result"] == "fallback_first" and sp["reason"] == "doc_llm_cap"


def test_locate_error_is_surfaced_and_falls_back(caplog):
    def boom(_messages):
        raise RuntimeError("invented failure")

    fake = ScriptLLM({"locate": boom, "extract": [base_answer()]})
    out = baseline_located.extract(fake, SV_CTX, SCAN_FIELDS, scan_pages(12), "pdf")
    sp = out.notes["scan_pages"]
    assert sp["result"] == "fallback_first" and sp["error"] == "RuntimeError"
    assert "locate error RuntimeError" in caplog.text and "invented failure" not in caplog.text
    assert out.entries is not None


def test_small_scan_and_text_docs_skip_the_locate_call():
    fake = ScriptLLM({"extract": [base_answer()]})
    out = baseline_located.extract(fake, SV_CTX, SCAN_FIELDS, scan_pages(8), "pdf")
    assert [c[0] for c in fake.calls] == ["extract"]
    assert out.notes["scan_pages"]["result"] == "all_pages_fit"
    text = [Block("paragraph", "Page 1", "Tenant: Example Tenant LLC", 1, block_id="P0001")]
    fake = ScriptLLM({"extract": [base_answer()]})
    out = baseline_located.extract(fake, SV_CTX, SCAN_FIELDS, text, "pdf")
    assert [c[0] for c in fake.calls] == ["extract"]
    assert out.notes["scan_pages"]["image_pages"] == 0


def test_plan_pages_for_the_dry_run():
    assert baseline_located.plan_pages(scan_pages(12)) == {"image_pages": 12, "locate": True}
    assert baseline_located.plan_pages(scan_pages(8)) == {"image_pages": 8, "locate": False}


def test_load_harness_reads_the_new_worker_start_line():
    spec = importlib.util.spec_from_file_location("load_test", ROOT / "scripts" / "load_test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    line = ("worker abc:1:x started (pipeline=baseline-v1, single_value_path=baseline, "
            "table_path=spec, scan_pages=locate, cache_mode=off)")  # fmt: skip
    assert mod.STARTED_RE.findall(line) == [("baseline-v1", "baseline", "off")]
