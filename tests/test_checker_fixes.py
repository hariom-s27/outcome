"""P5b checker fixes F-2 ... F-8 on invented data only (no sample values). No network, no key.

Fixes are by value type, never by document or field: every field here is an invented widget
field, every value an invented one.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from conftest import ROOT
from test_single_value import CTX, FakeLLM, a, ok, scan_pages, valid

from app.extract.compile_fields import compile_fields
from app.extract.normalise import DocHints, all_numbers, extract_dates, round_trip
from app.extract.verify import find_quote, value_in_quote
from app.pipeline import single_value
from app.pipeline.single_value import (
    DocView,
    check_field,
    free_text_value,
    loc_shape,
    page_label,
)
from app.readers.base import Block

FIELDS = {
    "name": "widget_agreement",
    "fields": {
        "widget_use": {"name": "Widget Use", "description": "What the widget space is for."},
        "agent_names": {"name": "Agents", "description": "List of all agent names."},
        "review_dates": {"name": "Review Dates", "description": "List of all review dates."},
        "option_count": {"name": "Options", "description": "Count of extension options."},
        "fee_total": {"name": "Total Fees", "description": "Total of the two fees in dollars."},
        "signed_date": {"name": "Signed Date", "description": "Date the agreement was signed."},
        "share_pct": {"name": "Share", "description": "Share of the building as a percentage."},
    },
}  # fmt: skip
SPECS = compile_fields(FIELDS)

BLOCKS = [
    Block("paragraph", "Page 1", "Widget Use: storage of blue widgets and related parts "
          "(see Section 9).", 1, block_id="P0001"),
    Block("paragraph", "Page 1", "Agents: Invented Agency Co; Sample Brokers Ltd", 1,
          block_id="P0002"),
    Block("paragraph", "Page 1", "Also acting: Placeholder Realty", 1, block_id="P0003"),
    Block("paragraph", "Page 2", "Reviews occur on March 3, 2032 and on the 1st of June, 2033.",
          2, block_id="P0004"),
    Block("paragraph", "Page 2", "Holder has two (2) extension options of five years each.", 2,
          block_id="P0005"),
    Block("paragraph", "Page 2", "Setup fee $1,250.00 due at signing.", 2, block_id="P0006"),
    Block("paragraph", "Page 3", "Service fee $750.00 due yearly.", 3, block_id="P0007"),
    Block("paragraph", "Page 3", "Signed on 14/02/2021 by both parties.", 3, block_id="P0008"),
    Block("paragraph", "Page 3", "Holder's share is .5% of the building.", 3, block_id="P0009"),
]  # fmt: skip


NO_HINT = DocHints()


def doc(blocks=BLOCKS, hints=NO_HINT, sent=()) -> DocView:
    return DocView("pdf", list(blocks), hints, set(sent))


def check(key, raw, d=None):
    return check_field(SPECS[key], raw, d or doc())


# --- F-2 scan page reference -------------------------------------------------------------------


@pytest.mark.parametrize(
    "loc",
    ["Page 3", "[Page 3]", "page 3", "PAGE  3", "p. 3", "p.3", "p3", "pg 3", "3", "[3]",
     "Page 3 of 25", "[Page 3 of 25]"],
)  # fmt: skip
def test_page_number_is_read_from_any_form(loc):
    assert page_label(loc) == 3


@pytest.mark.parametrize("loc", ["", "Section 3", "Exhibit B", "page", "3.2.1", "Page three"])
def test_not_a_page_reference(loc):
    assert page_label(loc) is None


SCAN_FIELDS = {"name": "widget_scan", "fields": {k: FIELDS["fields"][k] for k in
                                                 ("widget_use", "option_count")}}  # fmt: skip


def run_scan(answer, n_pages):
    fake = FakeLLM({"extract": [ok(answer)]})
    return single_value.extract(fake, CTX, SCAN_FIELDS, scan_pages(n_pages), "pdf")


def test_scan_accepts_any_page_form_for_a_sent_page():
    answer = {
        "widget_use": a("Widget Use: storage of blue widgets", "p. 2", "storage of blue widgets"),
        "option_count": a("two (2) extension options", "[Page 4 of 5]", 2),
    }
    out = run_scan(answer, 5)
    e = out.entries[0]
    assert e["widget_use"]["value"] == "storage of blue widgets"
    assert e["widget_use"]["citation"].startswith("[Page 2] ")
    assert e["option_count"]["value"] == 2 and e["option_count"]["page_numbers"] == [4]
    assert valid(out.entries, SCAN_FIELDS)


def test_scan_page_that_was_not_sent_still_fails():
    out = run_scan({"option_count": a("two (2) extension options", "p. 9", 2)}, 5)
    assert out.entries[0]["option_count"]["value"] is None
    assert out.notes["extraction"]["fields"]["option_count"]["reason"] == "loc_unknown"
    # a page the document has but the read call did not carry -> page_not_sent
    d = DocView("pdf", scan_pages(12), DocHints(), {1, 2})
    got = check_field(SPECS["option_count"], a("two (2) options", "page 9", 2), d)
    assert got.value is None and got.reason == "page_not_sent"


def test_one_image_sent_and_no_reference_uses_that_page():
    out = run_scan({"option_count": a("two (2) extension options", "", 2)}, 1)
    assert out.entries[0]["option_count"]["value"] == 2
    assert out.entries[0]["option_count"]["page_numbers"] == [1]


def test_two_images_sent_and_no_reference_is_null():
    out = run_scan({"option_count": a("two (2) extension options", "", 2)}, 2)
    assert out.entries[0]["option_count"]["value"] is None
    assert out.notes["extraction"]["fields"]["option_count"]["reason"] == "page_not_sent"


def test_loc_shapes_are_counted_by_shape_never_by_text():
    answer = {
        "widget_use": a("Widget Use: storage", "Section 4 Widget Use", "storage"),
        "option_count": a("two (2) extension options", "[Page 1]", 2),
    }
    shapes = run_scan(answer, 1).notes["extraction"]["loc_shapes"]
    assert shapes == {"other": 1, "[Page 1]".replace("1", "N"): 1}
    assert "Section" not in json.dumps(shapes)
    assert loc_shape("P0004", {"P0004"}) == "block_id" and loc_shape("") == "empty"
    assert loc_shape("p. 7") == "p. N" and loc_shape("Page 7 of 9") == "Page N of N"


# --- F-3 free text -------------------------------------------------------------------------------


def test_free_text_value_is_the_source_words_not_the_retyped_text():
    raw = a("widget use: storage of blue widgets and related parts (see Section 9).", "P0001",
            "Storage Of Blue Widgets")  # fmt: skip
    got = check("widget_use", raw)
    assert got.value == "storage of blue widgets" and got.reason == "ok"
    assert got.citation.startswith("[Page 1] Widget Use: storage of blue widgets")


def test_free_text_paraphrase_takes_the_whole_span_trimmed():
    raw = a("Widget Use: storage of blue widgets and related parts (see Section 9).", "P0001",
            "keeping widgets")  # fmt: skip
    got = check("widget_use", raw)  # no round trip: the paraphrase is replaced by source text
    assert got.value == "storage of blue widgets and related parts" and got.reason == "ok"


def test_free_text_quote_not_found_is_null():
    got = check("widget_use", a("Widget Use: invented other purpose", "P0001", "other"))
    assert got.value is None and got.reason == "quote_not_found"


def test_free_text_value_helper():
    assert free_text_value("Example Co", "Holder: Example Co / Unit 4") == "Example Co"
    assert free_text_value("zzz", "Holder: Example Co") == "Example Co"


# --- F-4 lists ------------------------------------------------------------------------------


def test_list_items_checked_one_by_one_keeps_verified_in_model_order():
    raw = a("Agents: Invented Agency Co; Sample Brokers Ltd", "P0002",
            ["Sample Brokers Ltd", "Made Up Partners", "Invented Agency Co"])  # fmt: skip
    got = check("agent_names", raw)
    assert got.value == ["Sample Brokers Ltd", "Invented Agency Co"]
    assert got.reason == "ok_partial" and got.citation.startswith("[Page 1] ")


def test_list_item_in_a_neighbour_block_verifies():
    raw = a("Agents: Invented Agency Co", "P0002", ["Invented Agency Co", "Placeholder Realty"])
    got = check("agent_names", raw)
    assert got.value == ["Invented Agency Co", "Placeholder Realty"] and got.reason == "ok"


def test_list_item_fuzzy_needs_90_and_4_chars():
    raw = a("Agents", "P0002", ["Placeholdr Realty", "Ltd", "Ltdx", "Totally Different Name"])
    got = check("agent_names", raw)  # typo: fuzzy >= 90 in the neighbour; "Ltd": exact word
    assert got.value == ["Placeholdr Realty", "Ltd"] and got.level == "fuzzy"


def test_list_with_no_verified_item_is_null():
    got = check("agent_names", a("Agents:", "P0002", ["Made Up Partners", "Other Firm Inc"]))
    assert got.value is None and got.reason == "list_unverified"


def test_list_of_dates_is_compared_as_dates():
    raw = a("Reviews occur on March 3, 2032", "P0004", ["2032-03-03", "2033-06-01", "2034-01-01"])
    got = check("review_dates", raw)
    assert got.value == ["2032-03-03", "2033-06-01"] and got.reason == "ok_partial"


def test_list_on_a_scan_checks_the_transcription():
    d = DocView("pdf", scan_pages(3), DocHints(), {2})
    raw = a("Agents: Invented Agency Co; Sample Brokers Ltd", "Page 2",
            ["Invented Agency Co", "Made Up Partners"])  # fmt: skip
    got = check_field(SPECS["agent_names"], raw, d)
    assert got.value == ["Invented Agency Co"] and got.level == "vision" and got.pages == [2]
    got = check_field(SPECS["agent_names"], {**raw, "loc": "Page 3"}, d)  # not sent
    assert got.value is None and got.reason == "page_not_sent"


# --- F-5 computed --------------------------------------------------------------------------------


def test_computed_parts_verified_final_value_needs_no_quote():
    raw = a("", "", 2000, parts=[
        {"q": "Setup fee $1,250.00", "loc": "P0006", "v": 1250},
        {"q": "Service fee $750.00", "loc": "P0007", "v": 750},
    ], op="sum")  # fmt: skip
    got = check("fee_total", raw)  # 2,000 is printed nowhere: computed in code
    assert got.value == 2000 and got.reason == "computed_ok" and got.pages == [2, 3]


def test_computed_wrong_part_value_still_fails():
    raw = a("", "", 2100, parts=[
        {"q": "Setup fee $1,250.00", "loc": "P0006", "v": 1350},
        {"q": "Service fee $750.00", "loc": "P0007", "v": 750},
    ], op="sum")  # fmt: skip
    assert check("fee_total", raw).reason == "part_unverified"


def test_computed_without_parts_is_a_normal_field_of_its_type():
    assert check("fee_total", a("Setup fee $1,250.00", "P0006", 1250)).value == 1250
    assert check("fee_total", a("Setup fee $1,250.00", "P0006", 2000)).reason == (
        "value_not_in_quote"
    )


# --- F-6 numbers / counts ------------------------------------------------------------------------


def test_count_written_as_words_passes():
    assert check("option_count", a("two (2) extension options", "P0005", 2)).value == 2
    assert value_in_quote(5, "options of five years each", "integer")
    assert value_in_quote(25, "twenty-five parking spaces", "integer")
    assert value_in_quote(120, "one hundred twenty days", "integer")
    assert value_in_quote(3000, "three thousand square feet", "number")
    assert value_in_quote(0, "zero spaces", "integer")


def test_every_number_in_the_quote_counts():
    q = "Setup fee $1,250.00 and a service fee of $750.00 for 12 months"
    assert {n.value for n in all_numbers(q)} >= {1250.0, 750.0, 12.0}
    assert value_in_quote(750, q, "number") and value_in_quote(12, q, "integer")


def test_wrong_number_not_in_the_quote_still_fails():
    assert check("option_count", a("two (2) extension options", "P0005", 3)).value is None
    assert not value_in_quote(1350, "Setup fee $1,250.00", "number")


def test_leading_decimal_point_is_a_fraction():
    assert check("share_pct", a("share is .5% of the building", "P0009", 0.5)).value == 0.5
    assert not value_in_quote(5, "share is .5% of the building", "percent")
    assert value_in_quote(4.5, "Section 4.5 applies", "number")  # a normal decimal unchanged


def test_number_tolerance_is_the_scorers():
    assert round_trip(1250.004, "fee $1,250.00", "number")
    assert not round_trip(1260, "fee $1,250.00", "number")


# --- F-7 dates -----------------------------------------------------------------------------------


def test_every_date_expression_in_the_quote_is_parsed():
    q = "Reviews occur on March 3, 2032 and on the 1st of June, 2033."
    dates = {c.date for c in extract_dates(q) if c.date}
    assert {str(d) for d in dates} == {"2032-03-03", "2033-06-01"}
    assert value_in_quote("2033-06-01", q, "date")
    assert not value_in_quote("2033-06-02", q, "date")


def test_ambiguous_date_uses_the_hint_else_null():
    q = "Signed on 03/04/2031 by both parties."
    assert value_in_quote("2031-04-03", q, "date", hints=DocHints(date_order="DMY"))
    assert not value_in_quote("2031-03-04", q, "date", hints=DocHints(date_order="DMY"))
    assert not value_in_quote("2031-03-04", q, "date")  # no hint: ambiguous -> no match
    assert value_in_quote("2031-02-14", "Signed on 14/02/2031", "date")  # not ambiguous


def test_scan_votes_the_date_order_from_the_quotes():
    fields = {"name": "w", "fields": {k: FIELDS["fields"][k] for k in ("signed_date",)}}
    fields["fields"]["review_on"] = {"name": "Review On", "description": "Date of the review."}
    answer = {
        "signed_date": a("Signed on 14/02/2021", "Page 1", "2021-02-14"),
        "review_on": a("Review on 03/04/2032", "Page 1", "2032-04-03"),
    }
    fake = FakeLLM({"extract": [ok(answer)]})
    out = single_value.extract(fake, CTX, fields, scan_pages(1), "pdf")
    e = out.entries[0]  # 14/02 votes DMY, so 03/04 reads as 3 April
    assert e["signed_date"]["value"] == "2021-02-14" and e["review_on"]["value"] == "2032-04-03"
    wrong = {**answer, "review_on": a("Review on 03/04/2032", "Page 1", "2032-03-04")}
    out = single_value.extract(FakeLLM({"extract": [ok(wrong)]}), CTX, fields, scan_pages(1), "pdf")
    assert out.entries[0]["review_on"]["value"] is None


def test_date_check_on_text_blocks():
    d = doc(hints=DocHints(date_order="DMY"))
    assert check("signed_date", a("Signed on 14/02/2021", "P0008", "2021-02-14"), d).value
    assert check("signed_date", a("Signed on 14/02/2021", "P0008", "2021-02-15"), d).value is None


# --- G-1 source wins / G-2 list strings and empty lists -------------------------------------

G_FIELDS = {"name": "w", "fields": {
    "widget_area": {"name": "Widget Area", "description": "Area of the space in square feet."},
    "fee_list": {"name": "Fees", "description": "List of all fees in dollars."},
}}  # fmt: skip
G_SPECS = compile_fields(G_FIELDS)
G_BLOCKS = [
    Block("paragraph", "Page 1", "The space contains 12,345 square feet.", 1, block_id="P0001"),
    Block("paragraph", "Page 1", "Fees: $1,250.00; $750.00", 1, block_id="P0002"),
]  # fmt: skip


def test_g1_number_within_tolerance_outputs_the_quoted_number():
    d = doc(G_BLOCKS)
    got = check_field(G_SPECS["widget_area"], a("contains 12,345 square feet", "P0001", 12354), d)
    assert got.value == 12345 and got.reason == "ok"
    got = check_field(G_SPECS["widget_area"], a("contains 12,345 square feet", "P0001", 12445), d)
    assert got.value is None and got.reason == "value_not_in_quote"  # outside tolerance


def test_g1_source_value_helper():
    from app.extract.normalise import source_value

    assert source_value(12354, "contains 12,345 square feet", "number") == 12345
    assert source_value(1250.004, "fee $1,250.00 and $1,250.01", "number") == 1250
    assert source_value(2, "two (2) options", "integer") == 2
    assert source_value("2031-04-01", "April 1, 2031", "date") == "2031-04-01"  # equal anyway
    assert source_value(12, "no number here", "number") == 12  # nothing near: unchanged


def test_g1_list_number_items_and_computed_parts_use_the_quote():
    d = doc(G_BLOCKS)
    assert G_SPECS["fee_list"].item_type == "number"
    got = check_field(G_SPECS["fee_list"], a("Fees: $1,250.00; $750.00", "P0002", [1251, 750]), d)
    assert got.value == [1250, 750]
    raw = a("", "", 2000, parts=[
        {"q": "Setup fee $1,250.00", "loc": "P0006", "v": 1251},
        {"q": "Service fee $750.00", "loc": "P0007", "v": 750},
    ], op="sum")  # fmt: skip
    got = check("fee_total", raw)
    assert got.value == 2000 and got.reason == "computed_ok"  # 1,250 + 750 from the quotes


def test_g2_list_returned_as_a_string_is_split_and_checked_per_item():
    raw = a("Agents: Invented Agency Co; Sample Brokers Ltd", "P0002",
            "Invented Agency Co; Made Up Partners\nSample Brokers Ltd")  # fmt: skip
    got = check("agent_names", raw)
    assert got.value == ["Invented Agency Co", "Sample Brokers Ltd"] and got.reason == "ok_partial"
    raw = a("Agents", "P0002", "Invented Agency Co, Made Up Partners")
    got = check("agent_names", raw)  # commas are not a list delimiter: one item, not found
    assert got.value is None and got.reason == "list_unverified"


def test_g2_empty_list_is_model_null():
    for empty in ([], ["", "  "], " ; "):
        got = check("agent_names", a("", "", empty))
        assert got.value is None and got.reason == "model_null", empty
    got = check("review_dates", a("Reviews", "P0004", ["not a date"]))
    assert got.reason == "type_invalid"  # items that do not normalise stay type_invalid


# --- verify helper --------------------------------------------------------------------------


def test_find_quote_min_chars_for_short_items():
    assert find_quote("Sample Brokerz Ltd", "Sample Brokers Ltd", min_chars=4).kind == "fuzzy"
    assert find_quote("Ltd", "Sample Brokers Ltd", min_chars=4).kind == "exact"
    assert find_quote("Ltdx", "Sample Brokers Ltd", min_chars=4) is None  # below 90
    assert find_quote("Ltdx", "Sample Brokers Ltd", min_chars=5) is None  # too short to try


# --- F-8 one raw folder per run -------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("eval_dev_f8", ROOT / "scripts" / "eval_dev.py")
eval_dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_dev)


def test_each_run_index_gets_its_own_raw_folder(monkeypatch, tmp_path):
    job = {"status": "SUCCESS", "result": {"entries": [], "metadata": {"cost_usd": 0.0}}}
    rows = {"d1": {"schema_name": "s", "file": "x"}}
    (tmp_path / "s.json").write_text(json.dumps({"fields": {"n": {"name": "N",
                                     "description": "x"}}}), encoding="utf-8")  # fmt: skip
    (tmp_path / "d1.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(eval_dev, "manifest", lambda: rows)
    monkeypatch.setattr(eval_dev, "paid_run_gates", lambda *a, **k: (True, {}))
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: (200, {}))
    monkeypatch.setattr(eval_dev, "submit_and_wait", lambda base, d, row: job)
    monkeypatch.setattr(eval_dev, "run_id", lambda: "abc1234")
    monkeypatch.setattr(eval_dev, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(eval_dev, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(eval_dev, "ROOT", tmp_path)
    monkeypatch.setattr(eval_dev, "SCHEMAS", tmp_path)
    monkeypatch.setattr(eval_dev, "TRUTH", tmp_path)
    for idx in (1, 2):
        monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--docs", "d1", "--run-index", str(idx),
                                          "--report", str(tmp_path / "r.md")])  # fmt: skip
        assert eval_dev.main() == 0
    assert (tmp_path / "runs" / "abc1234" / "run1" / "d1.json").exists()
    assert (tmp_path / "runs" / "abc1234" / "run2" / "d1.json").exists()
    hist = [json.loads(x) for x in (tmp_path / "history.jsonl").read_text().splitlines()]
    assert [h["raw_dir"] for h in hist] == ["abc1234/run1", "abc1234/run2"]
    # --reuse reads the per-run folder back without HTTP
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: pytest.fail("no HTTP expected"))
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--docs", "d1", "--reuse", "abc1234/run2",
                                      "--no-record"])  # fmt: skip
    assert eval_dev.main() == 0
