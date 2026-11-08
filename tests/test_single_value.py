"""Single-value pipeline (P5 Part D) with a scripted fake LLM. Invented data only (R31).
No network, no key (R32). Every result is checked with the frozen validator.
"""

from __future__ import annotations

import io
import json
import random
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from conftest import validator

from app import worker
from app.config import Settings
from app.extract.compile_fields import compile_fields
from app.llm import CallContext, JSONOutcome, LLMClient, LLMSettings, LLMStore, ModelCatalog
from app.llm.client import Projection, check_messages
from app.llm.jsonparse import salvage_object
from app.llm.models import Estimate, OutputBudget
from app.pipeline import baseline, single_value
from app.pipeline.single_value import (
    Checked,
    DocView,
    apply_op,
    block_text,
    choose_pages,
    lease_self_check,
    months_between,
)
from app.readers.base import Block

HAIKU = "anthropic/claude-haiku-5.5"
CTX = CallContext(job_id=None, deadline=4_000_000_000.0)

LEASE_FIELDS = {
    "name": "widget_lease",
    "fields": {
        "tenant_name": {"name": "Tenant Name", "description": "Legal name of the tenant."},
        "monthly_rent": {"name": "Monthly Rent", "description": "Base rent per month in dollars."},
        "commencement_date": {
            "name": "Commencement Date",
            "description": "Date the lease term starts.",
        },
        "expiration_date": {"name": "Expiration Date", "description": "Date the term ends."},
        "term_months": {
            "name": "Term (months)",
            "description": "Lease term in months from commencement to expiration.",
        },
        "has_renewal_option": {
            "name": "Renewal Option",
            "description": "True if the tenant has an option to renew.",
        },
    },
}
TEXT_BLOCKS = [
    Block("paragraph", "Page 1", "Widget lease between Example Landlord Inc. and", 1,
          block_id="P0001"),
    Block("paragraph", "Page 1", "Tenant: Example Tenant LLC\nSuite 400", 1, block_id="P0002"),
    Block("paragraph", "Page 2", "Monthly Base Rent: $12,345.00 payable in advance.", 2,
          block_id="P0003"),
    Block("paragraph", "Page 2", "The term commences on April 1, 2031.", 2, block_id="P0004"),
    Block("paragraph", "Page 3", "The term expires on March 31, 2036.", 3, block_id="P0005"),
    Block("paragraph", "Page 3", "Tenant may renew for one period of five years.", 3,
          block_id="P0006"),
]  # fmt: skip


def a(q, loc, v, conf="high", **extra):
    return {"q": q, "loc": loc, "v": v, "conf": conf, **extra}


GOOD = {
    "tenant_name": a("Tenant: Example Tenant LLC", "P0002", "Example Tenant LLC"),
    "monthly_rent": a("Monthly Base Rent: $12,345.00", "P0003", 12345),
    "commencement_date": a("commences on April 1, 2031", "P0004", "2031-04-01"),
    "expiration_date": a("expires on March 31, 2036", "P0005", "2036-03-31"),
    "term_months": a("", "", 60, parts=[
        {"q": "April 1, 2031", "loc": "P0004", "v": "2031-04-01"},
        {"q": "March 31, 2036", "loc": "P0005", "v": "2036-03-31"},
    ], op="months_between"),
    "has_renewal_option": a("Tenant may renew for one period", "P0006", True),
}  # fmt: skip


class FakeLLM:
    """complete_json scripted by purpose; projection always fits (baseline fallback)."""

    def __init__(self, script):
        self.script = script  # purpose -> list of JSONOutcome (popped in turn) or callable
        self.calls: list[tuple[str, list, int | None, bool]] = []
        self.catalog = SimpleNamespace(baseline=HAIKU, estimate=Estimate(), output=OutputBudget())

    def projection(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        return Projection(1000, 0.001)

    def complete_json(self, ctx, model, messages, *, max_tokens=None, kind_chars=None,
                      salvage=False):  # fmt: skip
        self.calls.append((ctx.purpose, messages, max_tokens, salvage))
        item = self.script[ctx.purpose]
        if callable(item):
            return item(messages)
        return item.pop(0) if isinstance(item, list) else item


def ok(data, **kw):
    return JSONOutcome("ok", data=data, **kw)


def valid(entries, fields) -> bool:
    meta = {"model_calls": 1, "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "latency_ms": 1}
    return validator.validate_contract({"entries": entries, "metadata": meta}, fields) == []


def run(answer, blocks=TEXT_BLOCKS, fields=LEASE_FIELDS, file_type="pdf", **script):
    fake = FakeLLM({"extract": [ok(answer)] if answer is not None else [], **script})
    out = single_value.extract(fake, CTX, fields, blocks, file_type)
    return out, fake


# --- text path ------------------------------------------------------------------------------------


def test_text_happy_path_builds_citations_from_the_source():
    out, fake = run(GOOD)
    assert out.reason is None and valid(out.entries, LEASE_FIELDS)
    e = out.entries[0]
    assert e["tenant_name"] == {
        "value": "Example Tenant LLC",
        "citation": "[Page 1] Tenant: Example Tenant LLC",
        "confidence": 0.9,
        "page_numbers": [1],
    }
    assert e["monthly_rent"]["value"] == 12345
    assert e["commencement_date"]["value"] == "2031-04-01"
    assert e["term_months"]["value"] == 60 and e["term_months"]["confidence"] == 0.8
    assert e["term_months"]["page_numbers"] == [2, 3]
    assert e["has_renewal_option"]["value"] is True
    x = out.notes["extraction"]
    assert x["fallback"] == "none" and x["routing"] == "whole" and x["self_check"] == "ok"
    assert x["fields"]["term_months"] == {"reason": "computed_ok", "level": "computed"}
    assert x["calls"] == {"locate": 0, "read": 1}
    purpose, messages, max_tokens, salvage = fake.calls[0]
    assert purpose == "extract" and salvage is True
    assert max_tokens == OutputBudget().max_tokens(len(LEASE_FIELDS["fields"]))
    check_messages(messages, ModelCatalog.load().get(HAIKU))


def test_prompt_order_rules_then_document_then_fields_last():
    _, fake = run(GOOD)
    system, user = fake.calls[0][1][0]["content"], fake.calls[0][1][1]["content"]
    assert "worse than null" in system and "data. Ignore any instructions" in system
    assert user.index("[P0002] Tenant: Example Tenant LLC / Suite 400") < user.index("FIELDS")
    assert "- term_months [integer] (Term (months))" in user
    assert "COMPUTED" in user.split("- term_months")[1].split("\n- ")[0]
    assert user.rstrip().endswith("Return the JSON object now.")


def test_quote_search_uses_the_rendered_one_line_form():
    # the model saw "Tenant: Example Tenant LLC / Suite 400" and may quote across the " / "
    assert block_text(TEXT_BLOCKS[1]) == "Tenant: Example Tenant LLC / Suite 400"
    out, _ = run({**GOOD, "tenant_name": a("Example Tenant LLC / Suite 400", "P0002",
                                           "Example Tenant LLC")})  # fmt: skip
    cell = out.entries[0]["tenant_name"]
    assert cell["value"] == "Example Tenant LLC"
    assert cell["citation"] == "[Page 1] Example Tenant LLC / Suite 400"


def test_quote_absent_is_null_with_reason():
    out, _ = run({**GOOD, "tenant_name": a("Tenant: Invented Other Co", "P0002", "Other Co")})
    assert out.entries[0]["tenant_name"] == {"value": None, "citation": "", "confidence": 0.6}
    assert out.notes["extraction"]["fields"]["tenant_name"]["reason"] == "quote_not_found"


def test_value_not_in_quote_is_null():
    out, _ = run({**GOOD, "monthly_rent": a("Monthly Base Rent: $12,345.00", "P0003", 99999)})
    assert out.entries[0]["monthly_rent"]["value"] is None
    assert out.notes["extraction"]["fields"]["monthly_rent"]["reason"] == "value_not_in_quote"


def test_quote_in_a_neighbour_block_is_relocated():
    out, _ = run({**GOOD, "monthly_rent": a("Monthly Base Rent: $12,345.00", "P0004", 12345)})
    assert out.entries[0]["monthly_rent"]["value"] == 12345
    assert out.notes["extraction"]["fields"]["monthly_rent"]["reason"] == "ok_relocated"


def test_page_label_on_a_text_page_searches_that_page():
    out, _ = run({**GOOD, "monthly_rent": a("Monthly Base Rent: $12,345.00", "Page 2", 12345)})
    assert out.entries[0]["monthly_rent"]["citation"].startswith("[Page 2] Monthly Base Rent")


def test_one_malformed_field_among_good_ones():
    out, _ = run({**GOOD, "tenant_name": "just a string", "monthly_rent": a("x", "P9999", 1)})
    e = out.entries[0]
    assert e["tenant_name"]["value"] is None and e["monthly_rent"]["value"] is None
    assert e["commencement_date"]["value"] == "2031-04-01"
    reasons = out.notes["extraction"]["fields"]
    assert reasons["tenant_name"]["reason"] == "parse_failed"
    assert reasons["monthly_rent"]["reason"] == "loc_unknown"
    assert valid(out.entries, LEASE_FIELDS)


def test_salvaged_members_are_null_the_rest_kept():
    fake = FakeLLM({"extract": [ok(dict(GOOD), salvaged=("monthly_rent",))]})
    out = single_value.extract(fake, CTX, LEASE_FIELDS, TEXT_BLOCKS, "pdf")
    assert out.entries[0]["monthly_rent"]["value"] is None
    assert out.entries[0]["tenant_name"]["value"] == "Example Tenant LLC"
    assert out.notes["extraction"]["salvaged_fields"] == 1


def test_forgiving_parse_keeps_good_members():
    text = (
        'Here you go:\n```json\n{"tenant_name": {"q": "Tenant: Example", "v": "Example"},'
        '\n "monthly_rent": {"q": "Rent $1", "v": 1,, oops},'
        '\n "term_months": {"q": "", "v": null},\n}\n```'
    )
    data, bad = salvage_object(text)
    assert bad == ["monthly_rent"]
    assert data["tenant_name"]["v"] == "Example" and data["term_months"]["v"] is None
    assert salvage_object('{"a": 1, "b": [1, 2,],}') == ({"a": 1, "b": [1, 2]}, [])
    assert salvage_object("no json here") == (None, [])


def test_boolean_false_needs_no_quote_true_does():
    out, _ = run({**GOOD, "has_renewal_option": a("", "", False)})
    cell = out.entries[0]["has_renewal_option"]
    assert cell == {"value": False, "citation": "", "confidence": 0.6}
    out, _ = run({**GOOD, "has_renewal_option": a("", "", True)})
    assert out.entries[0]["has_renewal_option"]["value"] is None


def test_low_confidence_word_and_clip():
    out, _ = run({**GOOD, "tenant_name": {**GOOD["tenant_name"], "conf": "low"}})
    assert out.entries[0]["tenant_name"]["confidence"] == 0.75


# --- computed fields ------------------------------------------------------------------------


def test_computed_mismatch_takes_the_code_value_when_parts_verify():
    term = {**GOOD["term_months"], "v": 61}
    out, _ = run({**GOOD, "term_months": term})
    assert out.entries[0]["term_months"]["value"] == 60
    assert out.notes["extraction"]["fields"]["term_months"]["reason"] == "computed_fixed"


def test_computed_unverified_part_is_null():
    parts = [dict(p) for p in GOOD["term_months"]["parts"]]
    parts[1]["q"] = "January 31, 2099"  # not in the document
    out, _ = run({**GOOD, "term_months": {**GOOD["term_months"], "parts": parts}})
    assert out.entries[0]["term_months"]["value"] is None
    assert out.notes["extraction"]["fields"]["term_months"]["reason"] == "part_unverified"


def test_computed_field_without_parts_is_checked_like_any_field():
    out, _ = run({**GOOD, "term_months": a("", "", 60)})  # no parts, no quote -> null
    assert out.entries[0]["term_months"]["value"] is None
    assert out.notes["extraction"]["fields"]["term_months"]["reason"] == "quote_missing"


def test_op_whitelist_and_date_math():
    import datetime as dt

    assert apply_op("sum", [1, 2.5]) == 3.5 and apply_op("difference", [10, 4]) == 6
    assert apply_op("ratio", [1, 0]) is None and apply_op("times_12", [1111]) == 13332
    assert apply_op("divide_12", [1200]) == 100 and apply_op("product", [2, 3]) == 6
    assert apply_op("rm -rf", [1]) is None
    d = dt.date(2031, 1, 31)
    assert apply_op("add_months", [d, 1]) == dt.date(2031, 2, 28)
    assert apply_op("day_before_anniversary", [dt.date(2031, 3, 1), 60]) == dt.date(2036, 2, 29)
    assert months_between(dt.date(2031, 3, 1), dt.date(2036, 2, 29)) == 60
    assert months_between(dt.date(2031, 3, 1), dt.date(2036, 3, 1)) == 60
    assert months_between(dt.date(2031, 3, 1), dt.date(2031, 3, 17)) is None


def test_lease_self_check_mismatch_lowers_confidence_only():
    specs = compile_fields(LEASE_FIELDS)
    cells = {k: Checked(None, "", 0.6, "model_null", "none") for k in specs}
    cells["commencement_date"] = Checked("2031-03-01", "c", 0.9, "ok", "exact")
    cells["expiration_date"] = Checked("2035-02-28", "c", 0.9, "ok", "exact")
    cells["term_months"] = Checked(60, "c", 0.8, "computed_ok", "computed")
    assert lease_self_check(specs, cells) == "mismatch"
    assert cells["expiration_date"].value == "2035-02-28"
    assert cells["expiration_date"].confidence == 0.7 and cells["term_months"].confidence == 0.6
    cells["expiration_date"] = Checked("2036-02-29", "c", 0.9, "ok", "exact")
    assert lease_self_check(specs, cells) == "ok"


# --- scan path ------------------------------------------------------------------------------


def _jpeg(w=800, h=1000) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (w, h), 255).save(buf, format="JPEG")
    return buf.getvalue()


SCAN_FIELDS = {
    "name": "widget_scan",
    "fields": {
        "tenant_name": LEASE_FIELDS["fields"]["tenant_name"],
        "monthly_rent": LEASE_FIELDS["fields"]["monthly_rent"],
    },
}


def scan_pages(n: int) -> list[Block]:
    jpeg = _jpeg()
    return [
        Block("image", f"Page {i}", page=i, jpeg=jpeg, width=800, height=1000, block_id=f"P{i:04d}")
        for i in range(1, n + 1)
    ]


SCAN_ANSWER = {
    "tenant_name": a("Tenant: Example Tenant LLC", "Page 3", "Example Tenant LLC"),
    "monthly_rent": a("Monthly Rent $12,345.00", "Page 7", 12345),
}


def _images_in(messages) -> list[int]:
    parts = messages[1]["content"]
    labels = [p["text"] for p in parts if p["type"] == "text"]
    pages = []
    for t in labels:
        for tok in t.split("[Page ")[1:]:
            pages.append(int(tok.split("]")[0]))
    return pages


def test_scan_locate_then_read_with_clamped_pages():
    blocks = scan_pages(12)
    locate = [
        ok({"pages": {"tenant_name": [3, 99], "monthly_rent": [7]}}),  # 99 is not a real page
        ok({"pages": {"monthly_rent": [7, 11], "tenant_name": ["x"]}}),
    ]
    fake = FakeLLM({"locate": locate, "extract": [ok(SCAN_ANSWER)]})
    out = single_value.extract(fake, CTX, SCAN_FIELDS, blocks, "pdf")
    purposes = [c[0] for c in fake.calls]
    assert purposes == ["locate", "locate", "extract"]
    loc_imgs = [p for p in fake.calls[0][1][1]["content"] if p["type"] == "image_url"]
    assert len(loc_imgs) == 8 and loc_imgs[0]["image_url"]["detail"] == "low"
    read = fake.calls[2][1]
    assert sorted(set(_images_in(read))) == [3, 7, 11]
    x = out.notes["extraction"]
    assert x["pages_chosen"] == [3, 7, 11] and x["mode"] == "scan"
    e = out.entries[0]
    assert e["tenant_name"]["citation"] == "[Page 3] Tenant: Example Tenant LLC"
    assert e["tenant_name"]["page_numbers"] == [3] and e["tenant_name"]["confidence"] == 0.7
    assert x["fields"]["monthly_rent"]["level"] == "vision"
    assert valid(out.entries, SCAN_FIELDS)


def test_scan_cites_a_page_that_was_not_sent_is_null():
    blocks = scan_pages(12)
    locate = [ok({"pages": {"tenant_name": [3]}}), ok({"pages": {}})]
    answer = {**SCAN_ANSWER, "monthly_rent": a("Monthly Rent $12,345.00", "Page 9", 12345)}
    fake = FakeLLM({"locate": locate, "extract": [ok(answer)]})
    out = single_value.extract(fake, CTX, SCAN_FIELDS, blocks, "pdf")
    assert out.entries[0]["monthly_rent"]["value"] is None
    assert out.notes["extraction"]["fields"]["monthly_rent"]["reason"] == "page_not_sent"


def test_locate_parse_failure_falls_back_to_batches():
    blocks = scan_pages(12)
    unusable = JSONOutcome("unusable", reason="llm_unusable")
    second = {**SCAN_ANSWER, "tenant_name": a("", "", None)}
    fake = FakeLLM({"locate": [unusable, unusable], "extract": [ok(SCAN_ANSWER), ok(second)]})
    out = single_value.extract(fake, CTX, SCAN_FIELDS, blocks, "pdf")
    assert [c[0] for c in fake.calls] == ["locate", "locate", "extract", "extract"]
    assert sorted(set(_images_in(fake.calls[2][1]))) == list(range(1, 9))
    assert sorted(set(_images_in(fake.calls[3][1]))) == [9, 10, 11, 12]
    x = out.notes["extraction"]
    assert x["locate_fallback"] == "batches" and x["calls"] == {"locate": 2, "read": 2}
    e = out.entries[0]
    # page 3 / page 7 were in batch 1 only: batch 2 citing them is not a sent page -> null there
    assert e["tenant_name"]["value"] == "Example Tenant LLC"
    assert e["monthly_rent"]["value"] == 12345 and valid(out.entries, SCAN_FIELDS)


def test_small_scan_skips_the_locate_call():
    fake = FakeLLM({"extract": [ok(SCAN_ANSWER)]})
    out = single_value.extract(fake, CTX, SCAN_FIELDS, scan_pages(8), "pdf")
    assert [c[0] for c in fake.calls] == ["extract"] and out.entries is not None


def test_choose_pages_is_the_p4_vote():
    answers = [{"pages": {"f1": [2, 5], "f2": [5], "f3": [True, 9]}}, None, {"pages": "x"}]
    assert choose_pages(answers, {1, 2, 3, 4, 5}, limit=1) == [5]
    assert choose_pages(answers, {1, 2, 3, 4, 5}) == [2, 5]


# --- BM25 cap -------------------------------------------------------------------------------


def test_bm25_routing_keeps_first_page_and_relevant_blocks():
    filler = "lorem ipsum dolor sit amet consectetur adipiscing elit " * 30
    blocks = [Block("paragraph", "Page 1", "Widget lease cover page.", 1, block_id="P0001")]
    for i in range(2, 400):
        blocks.append(Block("paragraph", f"Page {i}", filler, i, block_id=f"P{i:04d}"))
    blocks.append(Block("paragraph", "Page 400", "Tenant: Example Tenant LLC is the tenant.", 400,
                        block_id="P0400"))  # fmt: skip
    answer = {"tenant_name": a("Tenant: Example Tenant LLC", "P0400", "Example Tenant LLC")}
    out, fake = run(answer, blocks=blocks)
    x = out.notes["extraction"]
    assert x["routing"] == "bm25" and x["blocks_dropped"] > 0
    user = fake.calls[0][1][1]["content"]
    assert "[P0001] Widget lease cover page." in user and "[P0400] Tenant:" in user
    assert out.entries[0]["tenant_name"]["value"] == "Example Tenant LLC"
    assert x["tokens_estimated"][0] < single_value.INPUT_TOKEN_CAP


# --- fallback (P5-16) -----------------------------------------------------------------------


def test_nothing_parsed_runs_the_baseline_once():
    base_answer = {
        "entries": [
            {
                "tenant_name": {
                    "value": "Example Tenant LLC",
                    "citation": "[Page 1] x",
                    "confidence": 0.9,
                }
            }
        ]
    }
    fake = FakeLLM({"extract": [ok({"unrelated": 1}), ok(base_answer)]})
    out = single_value.extract(fake, CTX, LEASE_FIELDS, TEXT_BLOCKS, "pdf")
    assert [c[0] for c in fake.calls] == ["extract", "extract"]
    assert out.notes["pipeline"] == baseline.PIPELINE
    assert out.notes["extraction"]["fallback"] == "baseline"
    assert out.notes["extraction"]["smart_reason"] == "nothing_parsed"
    assert valid(out.entries, LEASE_FIELDS)


def test_smart_error_falls_back_and_is_recorded(monkeypatch):
    def boom(*_a, **_k):
        raise KeyError("invented")

    monkeypatch.setattr(single_value, "_extract_smart", boom)
    fake = FakeLLM({"extract": [JSONOutcome("unusable", reason="llm_unusable")]})
    out = single_value.extract(fake, CTX, LEASE_FIELDS, TEXT_BLOCKS, "pdf")
    assert out.entries is None and out.reason == "llm_unusable"
    x = out.notes["extraction"]
    assert x["fallback"] == "skeleton" and x["smart_error"] == "KeyError"


def test_llm_stopped_does_not_run_the_baseline():
    fake = FakeLLM({"extract": [JSONOutcome("stopped", reason="doc_llm_cap")]})
    out = single_value.extract(fake, CTX, LEASE_FIELDS, TEXT_BLOCKS, "pdf")
    assert out.entries is None and out.reason == "doc_llm_cap" and len(fake.calls) == 1


def test_empty_document_makes_no_call():
    fake = FakeLLM({})
    out = single_value.extract(fake, CTX, LEASE_FIELDS, [], "pdf")
    assert out.reason == "no_content" and fake.calls == []


# --- switch (P5-03, P5-04) ------------------------------------------------------------------


TABLE_FIELDS = {
    "name": "widget_table",
    "fields": {
        "sku": {"name": "SKU", "description": "Widget SKU.", "primary": True},
        "qty": {"name": "Qty", "description": "Quantity."},
    },
}


def test_switch_default_is_baseline_and_tables_never_go_smart():
    assert Settings().single_value_path == "baseline"
    assert worker.choose_pipeline(Settings(), LEASE_FIELDS) is baseline
    smart = Settings(single_value_path="smart")
    assert worker.choose_pipeline(smart, LEASE_FIELDS) is single_value
    assert worker.choose_pipeline(smart, TABLE_FIELDS) is baseline
    with pytest.raises(ValueError):
        Settings(single_value_path="clever")


def test_switch_off_output_is_byte_identical_to_baseline():
    base_answer = {
        "entries": [
            {
                "tenant_name": {
                    "value": "Example Tenant LLC",
                    "citation": "[Page 1] x",
                    "confidence": 0.9,
                }
            }
        ]
    }
    outs = []
    for path in ("baseline", None):
        fake = FakeLLM({"extract": [ok(base_answer)]})
        mod = worker.choose_pipeline(Settings(single_value_path="baseline"), LEASE_FIELDS)
        if path is None:
            mod = baseline
        o = mod.extract(fake, CTX, LEASE_FIELDS, TEXT_BLOCKS, "pdf")
        outs.append(json.dumps({"e": o.entries, "n": o.notes}, sort_keys=True))
    assert outs[0] == outs[1]


# --- P5 D-4: per-document call cap ----------------------------------------------------------


def _cap_llm(floor=8):
    return SimpleNamespace(
        catalog=ModelCatalog.load(), settings=LLMSettings(max_calls_per_doc=floor)
    )


@pytest.mark.parametrize("pages, cap", [(1, 8), (8, 8), (16, 8), (17, 10), (25, 12), (60, 20)])
def test_pdf_call_cap_grows_with_pages(pages, cap):
    assert worker.doc_call_cap(_cap_llm(), "pdf", scan_pages(pages)) == cap


def test_non_pdf_keeps_the_floor_and_config_is_read():
    rows = [Block("row", f"Sheet1!A{i}", "x", block_id=f"C{i:04d}") for i in range(1, 500)]
    assert worker.doc_call_cap(_cap_llm(), "csv", rows) == 8
    assert worker.doc_call_cap(_cap_llm(), "docx", TEXT_BLOCKS) == 8
    cc = ModelCatalog.load().call_cap
    assert (cc.calls_base, cc.calls_per_batch) == (4, 2)
    assert worker.doc_call_cap(_cap_llm(floor=30), "pdf", scan_pages(60)) == 30  # max(floor, …)


def test_a_60_page_scan_fits_its_cap_even_after_a_locate_failure():
    # 8 locate calls + 8 fallback batches = 16 <= 20
    blocks = scan_pages(60)
    unusable = JSONOutcome("unusable", reason="llm_unusable")
    fake = FakeLLM({"locate": [unusable] * 8, "extract": [ok(SCAN_ANSWER)] + [ok({})] * 7})
    out = single_value.extract(fake, CTX, SCAN_FIELDS, blocks, "pdf")
    assert len(fake.calls) == 16 <= worker.doc_call_cap(_cap_llm(), "pdf", blocks) == 20
    assert out.notes["extraction"]["calls"] == {"locate": 8, "read": 8}


# --- dry-run planner ------------------------------------------------------------------------


def test_planned_calls_for_text_and_scan():
    cat = ModelCatalog.load()
    calls, info = single_value.planned_calls(LEASE_FIELDS, TEXT_BLOCKS, "pdf", cat)
    assert [c["purpose"] for c in calls] == ["read"] and info["mode"] == "text"
    calls, info = single_value.planned_calls(SCAN_FIELDS, scan_pages(20), "pdf", cat)
    assert [c["purpose"] for c in calls] == ["locate", "locate", "locate", "read"]
    assert calls[-1]["images"] == 8 and info["locate"] is True
    assert all(c["est_tokens_in"] < 90_000 for c in calls)


def test_docview_maps_pages_and_skips_images():
    doc = DocView("pdf", [*TEXT_BLOCKS, *scan_pages(1)], single_value.DocHints())
    assert doc.page_ids[3] == ["P0005", "P0006"] and "P0001" in doc.by_id
    assert all(b.kind != "image" for b in doc.by_id.values())


# --- worker end to end (MockTransport gateway, smart path on) -------------------------------

SV_FIELDS = {
    "name": "widget_single",
    "fields": {
        "widget_name": {"name": "Widget Name", "description": "Name of the first widget."},
        "widget_count": {"name": "Widget Count", "description": "Number of widgets listed."},
    },
}
SV_CSV = b"widget_name,widget_count\nsprocket,3\n"


def test_worker_smart_path_end_to_end(client, database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE llm_state SET cooldown_until = NULL, consecutive_failures = 0, "
            "breaker_open_until = NULL, probe_until = NULL"
        )
    reply = {
        "widget_name": a("sprocket", "C0002", "sprocket"),
        "widget_count": a("B2=3", "C0002", 3),
    }
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        body = {
            "model": HAIKU,
            "choices": [{"message": {"role": "assistant", "content": json.dumps(reply)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 700, "completion_tokens": 60, "cost": 0.0001},
        }  # fmt: skip
        return httpx.Response(200, json=body)

    llm = LLMClient(
        LLMSettings(base_url="http://llm.test/v1", api_key="test-key"),
        ModelCatalog.load(),
        LLMStore(database_url),
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        rng=random.Random(0),
    )
    smart = Settings(database_url=database_url, max_pending=3, single_value_path="smart")
    r = client.post("/jobs", files={"file": ("w.csv", SV_CSV)},
                    data={"schema": json.dumps(SV_FIELDS)})  # fmt: skip
    jid = r.json()["job_id"]
    assert worker.process_one(smart, "w1", llm) is True
    body = client.get(f"/jobs/{jid}").json()
    assert body["status"] == "SUCCESS"
    res = body["result"]
    assert validator.validate_contract(res, SV_FIELDS) == []
    e = res["entries"][0]
    assert e["widget_name"]["value"] == "sprocket" and e["widget_count"]["value"] == 3
    assert e["widget_name"]["citation"].startswith("[Sheet1!") and "page_numbers" not in e[
        "widget_name"]  # fmt: skip
    meta = res["metadata"]
    assert meta["pipeline"] == single_value.PIPELINE and meta["model_calls"] == 1
    assert meta["extraction"]["usage"]["cost_usd"] == pytest.approx(0.0001)
    assert seen[0]["response_format"] == {"type": "json_object"}
    llm.close()
