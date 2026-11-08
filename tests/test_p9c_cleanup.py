"""P9c Z-51: TABLE_CLEANUP (default off). Invented bins and widgets only; no network."""

from __future__ import annotations

import json

import pytest
from test_p9c import FIELDS as GRID_FIELDS
from test_p9c import _page, grid_spec, make_pdf
from test_tables import CTX, FakeLLM, blocks_of, make_xlsx, ok

from app import worker
from app.config import Settings
from app.pipeline import baseline, table_spec
from app.readers import read_document
from app.tables import pdf_grid
from app.tables.cleanup import clean_entries, is_placeholder, strip_continued

# --- rule 1: whole-cell placeholders -----------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["Vacant", " VACANT ", "vacancy", "Unoccupied", "n/a", "N/A", "None", "TBD", "-", "—"]
)
def test_whole_cell_placeholders(text):
    assert is_placeholder(text)


@pytest.mark.parametrize(
    "value", ["Vacant since May", "Nonexistent", "N/A pending", "--x", "Ann Lee", 0, None, 3.5]
)
def test_not_placeholders(value):
    assert not is_placeholder(value)


# --- rule 2: continued section labels ----------------------------------------------------------


@pytest.mark.parametrize(
    "label, want",
    [
        ("Zone North (continued)", "Zone North"),
        ("Zone North (Cont.)", "Zone North"),
        ("Zone North (cont)", "Zone North"),
        ("Zone North continued", "Zone North"),
        ("Zone North - Continued", "Zone North"),
        ("Zone North", "Zone North"),
        ("Continued Care Wing", "Continued Care Wing"),  # only a trailing marker goes
        ("(continued)", "(continued)"),  # nothing left: kept as printed
    ],
)
def test_strip_continued(label, want):
    assert strip_continued(label) == want


# --- clean_entries -----------------------------------------------------------------------------

BIN_FIELDS = {
    "name": "bin_list",
    "fields": {
        "sku": {"name": "Bin Code", "description": "Bin code. One per row.", "primary": True},
        "holder": {"name": "Holder", "description": "Holder name as shown."},
        "qty": {"name": "Quantity", "description": "Units held, as a number."},
        "zone": {"name": "Zone", "description": "Zone label the bin is listed under."},
    },
}


def _cell(v, cite="[Bins!B2] x"):
    return {"value": v, "citation": cite, "confidence": 0.85, "source_locations": ["Bins!B2"]}


def test_clean_entries_nulls_placeholders_and_strips_section_markers():
    entries = [
        {"sku": _cell("TBD"), "holder": _cell("Vacant"), "qty": _cell(0),
         "zone": _cell("Zone North (continued)")},
        {"sku": _cell("BX-2"), "holder": _cell("Vacant since May"), "qty": _cell(2),
         "zone": _cell("Zone South")},
    ]  # fmt: skip
    sources = {"sku": "key", "holder": "col", "qty": "col", "zone": "section_context"}
    out, counts = clean_entries(entries, BIN_FIELDS, sources, 0.6)
    assert out[0]["sku"]["value"] == "TBD"  # the row key is never nulled
    assert out[0]["holder"] == {"value": None, "citation": "", "confidence": 0.6}
    assert out[0]["qty"]["value"] == 0 and out[0]["zone"]["value"] == "Zone North"
    assert out[0]["zone"]["citation"] == "[Bins!B2] x"  # the verbatim snippet stays
    assert out[1]["holder"]["value"] == "Vacant since May"
    assert counts == {"placeholder_nulls": 1, "section_suffixes": 1}
    assert entries[0]["holder"]["value"] == "Vacant"  # input not mutated


def test_marker_is_kept_on_fields_not_read_from_section_labels():
    entries = [{"sku": _cell("BX-1"), "holder": _cell("Ann (continued)"), "qty": _cell(1),
                "zone": _cell("Zone North (continued)")}]  # fmt: skip
    sources = {"sku": "key", "holder": "col", "qty": "col", "zone": "col"}
    out, counts = clean_entries(entries, BIN_FIELDS, sources, 0.6)
    assert out[0]["holder"]["value"] == "Ann (continued)"
    assert out[0]["zone"]["value"] == "Zone North (continued)"
    assert counts == {"placeholder_nulls": 0, "section_suffixes": 0}


# --- spreadsheet path --------------------------------------------------------------------------

BINS = make_xlsx(
    {
        "Bins": [
            ["Code", "Holder", "Qty"],
            ["Zone North", None, None],
            ["BX-1", "Ann Lee", 3],
            ["BX-2", "Vacant", 0],
            ["Zone North (continued)", None, None],
            ["BX-3", "TBD", 4],
            ["BX-4", "Vacant since May", 2],
        ]
    }
)
BIN_SPEC = {
    "sheet": "Bins",
    "header_row": 1,
    "data_first_row": 2,
    "data_last_row": None,
    "until_blank_run": None,
    "key_column": "A",
    "record_start": "key_matches_shape",
    "skip": ["blank", "section_header", "total_like", "header_repeat"],
    "row_fields": {"holder": {"col": "B"}, "qty": {"col": "C"}, "zone": {"section_context": True}},
    "doc_fields": {},
}


def _by_key(out) -> dict:
    return {e["sku"]["value"]: e for e in out.entries}


def test_spreadsheet_path_with_cleanup_on():
    out = table_spec.extract(FakeLLM(ok(BIN_SPEC)), CTX, BIN_FIELDS, blocks_of(BINS), "xlsx",
                             cleanup=True)  # fmt: skip
    t = out.notes["extraction"]["table"]
    rows = _by_key(out)
    assert rows["BX-2"]["holder"]["value"] is None and rows["BX-3"]["holder"]["value"] is None
    assert rows["BX-4"]["holder"]["value"] == "Vacant since May"
    assert rows["BX-3"]["zone"]["value"] == "Zone North"
    assert t["cleanup"] == {"placeholder_nulls": 2, "section_suffixes": 2}
    assert (
        table_spec.contract_errors(
            {"entries": out.entries, "metadata": table_spec._zero_meta()}, BIN_FIELDS
        )
        == []
    )


def test_spreadsheet_path_default_is_unchanged():
    out = table_spec.extract(FakeLLM(ok(BIN_SPEC)), CTX, BIN_FIELDS, blocks_of(BINS), "xlsx")
    rows = _by_key(out)
    assert rows["BX-2"]["holder"]["value"] == "Vacant"
    assert rows["BX-3"]["zone"]["value"] == "Zone North (continued)"
    assert "cleanup" not in out.notes["extraction"]["table"]


# --- PDF grid path -----------------------------------------------------------------------------

GRID_ROWS = [
    ("WX-201", "Hinge set", "5", "3.10", "TBD"),
    ("WX-202", "Latch kit", "8", "2.75", "n/a"),
    ("WX-203", "Pin box", "11", "0.40", "Check lid"),
]


@pytest.mark.parametrize("cleanup", [False, True])
def test_grid_path_cleanup(cleanup):
    pdf = make_pdf([_page(1, GRID_ROWS, False)])
    res = pdf_grid.build(pdf)
    assert res.grid is not None
    out = table_spec.extract(
        FakeLLM(ok(grid_spec(res.grid))), CTX, GRID_FIELDS, read_document("pdf", pdf).blocks,
        "pdf", pdf_grid=res, cleanup=cleanup,
    )  # fmt: skip
    t = out.notes["extraction"]["table"]
    notes = {e["sku"]["value"]: e["note"]["value"] for e in out.entries}
    assert t["grid_result"] == "ok"
    if cleanup:
        assert notes == {"WX-201": None, "WX-202": None, "WX-203": "Check lid"}
        assert t["cleanup"]["placeholder_nulls"] == 2
        assert all("page_numbers" not in e["note"] for e in out.entries[:2])
    else:
        assert notes["WX-201"] == "TBD" and "cleanup" not in t


# --- switch + worker ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, on",
    [(None, True), ("", True), ("1", True), ("0", False), ("false", False), ("OFF", False)],
)
def test_switch_defaults_on_and_can_be_turned_off(monkeypatch, raw, on):  # Z-60
    assert Settings().table_cleanup is True
    if raw is None:
        monkeypatch.delenv("TABLE_CLEANUP", raising=False)
    else:
        monkeypatch.setenv("TABLE_CLEANUP", raw)
    assert Settings.from_env().table_cleanup is on


@pytest.mark.parametrize("on", [False, True])
def test_worker_passes_cleanup_only_when_switched_on(settings, client, monkeypatch, on):
    seen: list[dict] = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return baseline.BaselineOutcome(None, "llm_unusable")

    monkeypatch.setattr(table_spec, "extract", spy)
    s = settings.__class__(**{**settings.__dict__, "table_cleanup": on})
    r = client.post(
        "/jobs", files={"file": ("b.csv", b"code,qty\nBX-1,3\nBX-2,4\n")},
        data={"schema": json.dumps(BIN_FIELDS)},
    )  # fmt: skip
    assert r.status_code == 202
    llm = FakeLLM()
    llm.store = type("S", (), {"job_metadata": staticmethod(lambda jid, ms: {"latency_ms": ms})})
    llm.cache_mode = "off"
    llm.catalog.call_cap = type("C", (), {"for_doc": staticmethod(lambda ft, p, d: 4)})
    llm.settings = type("L", (), {"max_calls_per_doc": 4})
    assert worker.process_one(s, "w1", llm) is True
    assert len(seen) == 1 and ("cleanup" in seen[0]) is on


# --- Z-59: weakly typed fields holding text ----------------------------------------------------

BAY_FIELDS = {
    "name": "bay_list",
    "fields": {
        "bay": {"name": "Bay", "description": "Bay code.", "primary": True},
        # typed integer only from a noun ("units"): a weak type, text cells stay text
        "occupant": {
            "name": "Occupant",
            "description": "Occupant of the bay; null for empty units.",
        },
        "crates": {"name": "Crates", "description": "Crates in the bay, as a number."},
    },
}
BAYS = make_xlsx(
    {
        "Bays": [
            ["Bay", "Occupant", "Crates"],
            ["BY-1", "Rowe Supply", 4],
            ["BY-2", "VACANT", 0],
            ["BY-3", "Unoccupied", 0],
            ["BY-4", "Vacant from June", 2],
            ["BY-5", 17, 3],  # a number in the weak column: never touched
        ]
    }
)
BAY_SPEC = {
    "sheet": "Bays", "header_row": 1, "data_first_row": 2, "data_last_row": None,
    "until_blank_run": None, "key_column": "A", "record_start": "key_matches_shape",
    "skip": ["blank", "total_like", "header_repeat"],
    "row_fields": {"occupant": {"col": "B"}, "crates": {"col": "C"}}, "doc_fields": {},
}  # fmt: skip


def test_weak_typed_field_is_weak_and_number_field_is_not():
    from app.extract.compile_fields import compile_fields
    from app.tables.execute import weak_type

    specs = compile_fields(BAY_FIELDS)
    assert specs["occupant"].type == "integer" and weak_type(specs["occupant"])
    assert specs["crates"].type == "number" and not weak_type(specs["crates"])


def test_clean_entries_weak_typed_placeholder_text_becomes_null():
    entries = [
        {"bay": _cell("BY-2"), "occupant": _cell("VACANT"), "crates": _cell(0)},
        {"bay": _cell("BY-5"), "occupant": _cell(17), "crates": _cell(3)},
        {"bay": _cell("BY-4"), "occupant": _cell("Vacant from June"), "crates": _cell(2)},
    ]
    sources = {"bay": "key", "occupant": "col", "crates": "col"}
    out, counts = clean_entries(entries, BAY_FIELDS, sources, 0.6)
    assert out[0]["occupant"] == {"value": None, "citation": "", "confidence": 0.6}
    assert out[0]["crates"]["value"] == 0  # a real number is never touched
    assert out[1]["occupant"]["value"] == 17  # a number in the weak field stays
    assert out[2]["occupant"]["value"] == "Vacant from June"  # whole cell only
    assert counts == {"placeholder_nulls": 1, "section_suffixes": 0}


def test_strong_numeric_field_is_out_of_scope():
    entries = [{"bay": _cell("BY-1"), "occupant": _cell("Rowe Supply"), "crates": _cell("none")}]
    sources = {"bay": "key", "occupant": "col", "crates": "col"}
    out, counts = clean_entries(entries, BAY_FIELDS, sources, 0.6)
    assert out[0]["crates"]["value"] == "none" and counts["placeholder_nulls"] == 0


def test_row_key_placeholder_is_never_nulled_even_when_weak():
    fields = {"name": "k", "fields": {
        "unit": {"name": "Unit", "description": "Unit; null for empty units.", "primary": True},
        "occupant": BAY_FIELDS["fields"]["occupant"]}}  # fmt: skip
    entries = [{"unit": _cell("TBD"), "occupant": _cell("TBD")}]
    out, _counts = clean_entries(entries, fields, {"unit": "key", "occupant": "col"}, 0.6)
    assert out[0]["unit"]["value"] == "TBD" and out[0]["occupant"]["value"] is None


@pytest.mark.parametrize("cleanup", [False, True])
def test_spreadsheet_path_weak_typed_column(cleanup):
    out = table_spec.extract(FakeLLM(ok(BAY_SPEC)), CTX, BAY_FIELDS, blocks_of(BAYS), "xlsx",
                             cleanup=cleanup)  # fmt: skip
    occ = {e["bay"]["value"]: e["occupant"]["value"] for e in out.entries}
    crates = {e["bay"]["value"]: e["crates"]["value"] for e in out.entries}
    assert occ["BY-1"] == "Rowe Supply" and occ["BY-4"] == "Vacant from June"
    assert occ["BY-5"] == 17 and crates == {"BY-1": 4, "BY-2": 0, "BY-3": 0, "BY-4": 2, "BY-5": 3}
    if cleanup:
        assert occ["BY-2"] is None and occ["BY-3"] is None
        assert out.notes["extraction"]["table"]["cleanup"]["placeholder_nulls"] == 2
    else:
        assert occ["BY-2"] == "VACANT" and occ["BY-3"] == "Unoccupied"


# --- Z-59 targeted-fix gate (scripts/gate_cleanup.py) ------------------------------------------


def _gate_mod():
    from test_p9a import _load

    return _load("gate_cleanup")


def test_targeted_cells_count_placeholder_halluc_and_continued_labels(tmp_path):
    gc = _gate_mod()
    schema = {"name": "bins", "fields": {
        "sku": {"name": "SKU", "description": "Code.", "primary": True},
        "holder": {"name": "Holder", "description": "Holder name."},
        "zone": {"name": "Zone", "description": "Zone label."}}}  # fmt: skip
    truth = {"schema": "bins", "entries": [
        {"sku": "BX-1", "holder": None, "zone": "North"},
        {"sku": "BX-2", "holder": "Ann Lee", "zone": "North"},
        {"sku": "BX-3", "holder": None, "zone": "South"}]}  # fmt: skip
    (tmp_path / "s.json").write_text(json.dumps(schema), encoding="utf-8")
    (tmp_path / "t.json").write_text(json.dumps(truth), encoding="utf-8")
    row = {"schema_name": "bins", "schema_path": str(tmp_path / "s.json"),
           "truth_path": str(tmp_path / "t.json")}  # fmt: skip

    def c(v):
        return {"value": v, "citation": "", "confidence": 0.5}

    job = {
        "result": {
            "entries": [
                {
                    "sku": c("BX-1"),
                    "holder": c("Vacant"),
                    "zone": c("North (continued)"),
                },  # 2 targeted
                {"sku": c("BX-2"), "holder": c("Vacant"), "zone": c("North")},  # truth not null: no
                {
                    "sku": c("BX-3"),
                    "holder": c("Someone"),
                    "zone": c("South"),
                },  # halluc, not placeholder
                {"sku": c("BX-9"), "holder": c("Vacant"), "zone": c("X (cont.)")},
            ]
        }
    }  # extra row: no
    assert gc.targeted_cells("bins_t", row, job) == 2


def _g(score: float, halluc: float = 0.0, valid: bool = True) -> dict:
    return {"set": "syn", "n": 3, "score": score, "scores": [score] * 3, "min": score,
            "halluc": halluc, "missed": 0.0, "rows_pred": 1, "rows_truth": 1, "usd": 0.001,
            "valid": valid, "cells": None}  # fmt: skip


def test_targeted_gate_rules():
    gc = _gate_mod()
    docs = gc.DOCS
    base = {d: _g(0.98, 1.0) for d in docs}
    t_base = dict.fromkeys(docs, 2.0)
    good = {d: _g(0.99, 1.0) for d in docs}
    assert gc.gate(base, good, t_base, dict.fromkeys(docs, 1.0))["verdict"] == "PASS"
    # (ii) strictly fewer: equal counts fail
    assert gc.gate(base, good, t_base, t_base)["checks"]["targeted"][0] is False
    # (i) one doc a hair below its base fails
    low = {**good, docs[0]: _g(0.979, 1.0)}
    assert (
        gc.gate(base, low, t_base, dict.fromkeys(docs, 0.0))["checks"]["no_doc_below"][0] is False
    )
    # (iii) more hallucinations fail (totals used when no per-run cell data)
    worse = {d: _g(0.99, 2.0) for d in docs}
    assert (
        gc.gate(base, worse, t_base, dict.fromkeys(docs, 0.0))["checks"]["halluc_paired"][0]
        is False
    )
    assert gc.BASES == {"syn_budget_pdf": ["141", "142", "143"],
                        "syn_rentroll_pdf": ["141", "142", "143"],
                        "rentroll_001": ["104", "105", "106"],
                        "syn_rentroll_xlsx": ["104", "105", "106"]}  # fmt: skip
