"""P9g Z-61: SPEC_RETRY_FEEDBACK (default off). Lenient unknown entry keys + E0 retry feedback.
INVENTED widget specs only (R31); no network, no key (R32).
"""

from __future__ import annotations

import json
import logging

import pytest
from test_p9c_cleanup import BIN_FIELDS
from test_tables import (
    CTX,
    FLAT_FIELDS,
    NO_MATCH,
    FakeLLM,
    blocks_of,
    flat_rows,
    flat_spec,
    make_xlsx,
    ok,
    renamed,
)

from app import worker
from app.config import Settings
from app.pipeline import baseline, table_spec
from app.tables.profile import profile_blocks
from app.tables.spec import salvage_spec, validate_spec

DATA = make_xlsx({"Stock": renamed(flat_rows(70), NO_MATCH)})  # heuristic cannot map fields
WP = profile_blocks(blocks_of(DATA))
ODD_KEY = "Widget 7 subtotal"  # an invented model-made key that looks like sheet text


def _rf(**rules):
    return flat_spec(row_fields={"item_name": {"col": "B"}, "qty": {"col": "C"},
                                 "unit_price": {"col": "D"}, **rules})  # fmt: skip


# --- lenient keys in the validator -------------------------------------------------------------


def test_strict_drops_an_entry_with_an_extra_key():  # off = v1.0 / lab
    spec, core, dropped = salvage_spec(_rf(qty={"col": "C", "colour": "x"}), FLAT_FIELDS, WP)
    assert core == [] and "qty" not in spec.row_fields
    assert dropped == ["row_fields.qty: unknown keys ['colour']"]


def test_lenient_keeps_an_entry_whose_only_fault_is_an_extra_key():
    report: dict = {}
    raw = _rf(qty={"col": "C", "colour": "x"})
    spec, core, dropped = salvage_spec(raw, FLAT_FIELDS, WP, report=report)
    assert core == [] and dropped == []
    assert spec.row_fields["qty"] == {"col": "C", "fold": "first_nonempty"}
    assert report["ignored"] == ["row_fields.qty.colour"] and report["top_unknown"] == []


def test_lenient_on_inner_objects_and_doc_fields():
    report: dict = {}
    raw = flat_spec(
        row_fields={
            "item_name": {"pick_by_label": {"label_col": "B", "label_text": "Widget 1",
                                            "value_col": "B", "row": 3}, "fold": "sum"},
            "qty": {"derived": {"op": "sum", "cols": ["C"], "weight": 2}},
            "unit_price": {"col": "D", "fold": "sum",
                           "except_label": {"label_col": "B", "labels": [], "case": "any"}},
        },
        doc_fields={"depot": {"cell": "Stock!B2", "note": "header"}},
    )  # fmt: skip
    spec, core, dropped = salvage_spec(raw, FLAT_FIELDS, WP, report=report)
    assert core == [] and dropped == []
    assert set(spec.row_fields) == {"item_name", "qty", "unit_price"}
    assert spec.row_fields["item_name"]["pick_by_label"] == {
        "label_col": "B", "label_text": "Widget 1", "value_col": "B"}  # fmt: skip
    assert spec.doc_fields == {"depot": "Stock!B2"}
    assert sorted(report["ignored"]) == sorted([
        "row_fields.item_name.fold", "row_fields.item_name.pick_by_label.row",
        "row_fields.qty.derived.weight", "row_fields.unit_price.except_label.case",
        "doc_fields.depot.note"])  # fmt: skip


@pytest.mark.parametrize(
    "rule",
    [
        {"pick_by_label": {"label_col": "B", "value_col": "C", "colour": 1}},  # no label_text
        {"fold": "sum", "colour": 1},  # no rule kind at all
        {"col": "b1", "colour": 1},  # invalid value
        {"col": "C", "fold": "average", "colour": 1},  # invalid fold
        {"derived": {"op": "mean", "cols": ["C"], "colour": 1}},  # invalid op
    ],
)
def test_lenient_still_drops_missing_required_keys_and_bad_values(rule):
    report: dict = {}
    spec, core, dropped = salvage_spec(_rf(qty=rule), FLAT_FIELDS, WP, report=report)
    assert "qty" not in spec.row_fields and len(dropped) == 1
    assert report["ignored"] == []  # a dropped entry's extra keys are not counted as ignored


def test_lenient_leaves_top_level_unknown_keys_as_drops():
    report: dict = {}
    spec, core, dropped = salvage_spec(flat_spec(fields={}), FLAT_FIELDS, WP, report=report)
    assert dropped == ["unknown keys: ['fields']"] and report["top_unknown"] == ["fields"]


def test_validate_spec_stays_strict():  # heuristic specs: unchanged
    spec, errors = validate_spec(_rf(qty={"col": "C", "colour": "x"}), FLAT_FIELDS, WP)
    assert spec is None and errors


# --- pipeline: lenient rescue, feedback retry, off = unchanged ---------------------------------


def _table(out) -> dict:
    return out.notes["extraction"]["table"]


def test_lenient_rescue_needs_no_retry():
    fake = FakeLLM(ok(_rf(qty={"col": "C", "fold": "first_nonempty", ODD_KEY: 1})))
    out = table_spec.extract(
        fake, CTX, FLAT_FIELDS, blocks_of(DATA), "xlsx", robust=True, feedback=True
    )
    t = _table(out)
    assert [c[0] for c in fake.calls] == ["table_spec"] and "e0" not in t
    assert t["ai_spec"]["unknown_keys_ignored"] == 1
    assert t["ai_spec"]["unknown_key_names"] == ["other"]  # never the model's own key text
    assert t["candidates"][t["chosen"]]["filled"] == 1.0


BAD = flat_spec(
    extra_key=1,
    row_fields={
        "item_name": {"col": "B"},
        "qty": {"col": "C", "x": 1},
        "unit_price": {"pick_by_label": {"label_col": "B"}},
    },
)


def test_feedback_retry_names_keys_allowed_keys_and_unfilled_fields():
    fake = FakeLLM(ok(BAD), ok(flat_spec()))
    out = table_spec.extract(
        fake, CTX, FLAT_FIELDS, blocks_of(DATA), "xlsx", robust=True, feedback=True
    )
    t = _table(out)
    assert [c[0] for c in fake.calls] == ["table_spec", "table_spec_e0"]
    retry_user = fake.calls[1][1][1]["content"]
    assert "FEEDBACK ON YOUR PREVIOUS SPEC" in retry_user
    assert "unknown keys: ['extra_key']" in retry_user  # entry + reason + key names
    assert "row_fields.unit_price: pick_by_label needs label_col, label_text, value_col" in (
        retry_user
    )
    assert "Top-level keys ['extra_key'] are not allowed" in retry_user
    assert "row_fields.qty.x" in retry_user  # ignored inside a kept entry
    assert "Allowed top-level keys: sheet, header_row" in retry_user
    assert "Unfilled:" not in retry_user  # fill 2/3 >= 0.5 (qty kept by lenient keys)
    assert t["e0"]["feedback"] == {"problems": 2, "ignored": 1, "top_unknown": 1, "unfilled": 0}
    assert t["e0"]["why"] == "entries_dropped" and t["e0"]["kept"] == "retry_result"
    assert t["retry"]["unknown_keys_ignored"] == 0
    assert t["candidates"][t["chosen"]]["filled"] == 1.0


def test_feedback_lists_unfilled_fields_only_below_half_fill():
    first = flat_spec(row_fields={"item_name": {"col": "B"}})  # fill 1/3, nothing dropped
    fake = FakeLLM(ok(first), ok(flat_spec()))
    table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(DATA), "xlsx", robust=True, feedback=True)
    user = fake.calls[1][1][1]["content"]
    assert "Only 1 of 3 row-level fields were filled. Unfilled: qty, unit_price." in user


def test_off_is_unchanged():
    fake = FakeLLM(ok(BAD), ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(DATA), "xlsx", robust=True)
    t = _table(out)
    retry_msgs = fake.calls[1][1]
    assert retry_msgs == table_spec.build_messages(FLAT_FIELDS, WP, "xlsx")  # plain retry
    assert "unknown_keys_ignored" not in t["ai_spec"] and "feedback" not in t["e0"]
    assert t["ai_spec"]["entries_dropped"] == 3  # qty's extra key drops the entry, as today


def test_no_values_or_model_keys_in_metadata_or_logs(caplog):
    raw = flat_spec(**{ODD_KEY: 1}, row_fields={"item_name": {"col": "B", ODD_KEY: 2}})
    fake = FakeLLM(ok(raw), ok(flat_spec()))
    with caplog.at_level(logging.INFO):
        out = table_spec.extract(
            fake, CTX, FLAT_FIELDS, blocks_of(DATA), "xlsx", robust=True, feedback=True
        )
    meta = json.dumps(out.notes)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    for text in (ODD_KEY, "North Widget Yard", "Widget 7", "WX-1"):
        assert text not in meta and text not in logs
    assert ODD_KEY in fake.calls[1][1][1]["content"]  # the model may see its own key back
    assert _table(out)["ai_spec"]["unknown_top_keys"] == ["other"]


# --- switch + worker wiring --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, on",
    [(None, False), ("", False), ("0", False), ("off", False), ("1", True), ("TRUE", True)],
)
def test_switch_defaults_off(monkeypatch, raw, on):
    assert Settings().spec_retry_feedback is False
    if raw is None:
        monkeypatch.delenv("SPEC_RETRY_FEEDBACK", raising=False)
    else:
        monkeypatch.setenv("SPEC_RETRY_FEEDBACK", raw)
    assert Settings.from_env().spec_retry_feedback is on


@pytest.mark.parametrize("on", [False, True])
def test_worker_passes_feedback_only_when_switched_on(settings, client, monkeypatch, on):
    seen: list[dict] = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return baseline.BaselineOutcome(None, "llm_unusable")

    monkeypatch.setattr(table_spec, "extract", spy)
    s = settings.__class__(**{**settings.__dict__, "spec_retry_feedback": on})
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
    assert len(seen) == 1 and ("feedback" in seen[0]) is on
