"""Baseline extractor (P2-16, P2-17) with a fake LLM, plus the worker path end to end with a
MockTransport gateway. Invented widget data only (R31). No network, no key (R32).
"""

from __future__ import annotations

import dataclasses
import json
import random
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from conftest import CSV_BYTES, FIELD_LIST, FIELD_LIST_JSON, validator

from app import worker
from app.llm import CallContext, JSONOutcome, LLMClient, LLMSettings, LLMStore, ModelCatalog
from app.llm.client import Projection, check_messages
from app.llm.models import Estimate
from app.pipeline import baseline
from app.readers.base import Block

HAIKU = "anthropic/claude-haiku-5.5"
CTX = CallContext(job_id=None, deadline=4_000_000_000.0)

DOC_FIELDS = {
    "name": "widget_contract",
    "fields": {
        "supplier": {"name": "Supplier", "description": "Supplier name."},
        "monthly_fee": {"name": "Monthly Fee", "description": "Monthly fee, a number."},
        "start_date": {"name": "Start Date", "description": "Start date."},
        "discount_pct": {"name": "Discount %", "description": "Discount as printed."},
    },
}
TABLE_FIELDS = {
    "name": "widget_table",
    "fields": {
        "sku": {"name": "SKU", "description": "Widget SKU.", "primary": True},
        "qty": {"name": "Qty", "description": "Quantity."},
        "site": {"name": "Site", "description": "Site name, same for every row."},
    },
}
TEXT_BLOCKS = [
    Block("paragraph", "Page 1", "Widget supply agreement. Supplier: Acme Sprockets.", page=1),
    Block("paragraph", "Page 2", "Monthly fee $1,250.00 from 2031-04-01. Discount 4.5%.", page=2),
]


class FakeLLM:
    def __init__(self, outcome: JSONOutcome):
        self.outcome = outcome
        self.calls: list[tuple] = []
        self.catalog = SimpleNamespace(baseline=HAIKU, estimate=Estimate())
        self.fits_up_to: int | None = None  # P2-36: estimated tokens a call may carry
        self.estimates: list[int] = []
        self.kind_chars: list[dict | None] = []

    def projection(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        est = Estimate().tokens(messages, kind_chars)
        self.estimates.append(est)
        cap = None if self.fits_up_to is None else 0.05
        return Projection(est, 0.01 if (cap is None or est <= self.fits_up_to) else 0.06, 0.0, cap)

    def complete_json(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        self.calls.append((model, messages, max_tokens))
        self.kind_chars.append(kind_chars)
        return self.outcome


def f(value, citation="[Page 1] x", confidence=0.9):
    return {"value": value, "citation": citation, "confidence": confidence}


def valid(entries, fields) -> bool:
    meta = {"model_calls": 1, "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "latency_ms": 1}
    return validator.validate_contract({"entries": entries, "metadata": meta}, fields) == []


# --- prompt -----------------------------------------------------------------------------------


def test_prompt_has_rules_fields_and_addressed_text():
    fake = FakeLLM(JSONOutcome("ok", data={"entries": [{}]}))
    baseline.extract(fake, CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf")
    model, messages, max_tokens = fake.calls[0]
    assert model == HAIKU and max_tokens == baseline.MAX_TOKENS
    system, user = messages[0]["content"], messages[1]["content"]
    assert "never guess" in system.lower() and "YYYY-MM-DD" in system
    assert "exactly one entry" in system
    assert "- monthly_fee (Monthly Fee): Monthly fee, a number." in user
    assert "[Page 2] Monthly fee" in user
    check_messages(messages, ModelCatalog.load().get(HAIKU))  # text only, nothing forbidden


def test_table_schema_asks_for_one_entry_per_row():
    fake = FakeLLM(JSONOutcome("ok", data={"entries": []}))
    baseline.extract(fake, CTX, TABLE_FIELDS, TEXT_BLOCKS, "csv")
    system = fake.calls[0][1][0]["content"]
    assert 'The field "sku" identifies table rows' in system
    assert "[row key]" in fake.calls[0][1][1]["content"]


def test_caps_cut_text_and_images_and_record_it():
    many_rows = [Block("row", f"Sheet1!A{i}:C{i}", "x" * 700) for i in range(1, 400)]
    msgs, notes = baseline.build_messages(TABLE_FIELDS, many_rows, "xlsx")
    assert notes["truncated"] and notes["rows_dropped"] > 0
    assert notes["input_tokens_est"] <= baseline.INPUT_TOKEN_CAP
    assert "document cut here" in msgs[1]["content"]

    jpeg = b"\xff\xd8\xff\xe0fakejpeg"
    pages = [
        Block("image", f"Page {i}", page=i, jpeg=jpeg, width=1236, height=1600)
        for i in range(1, 11)
    ]
    msgs, notes = baseline.build_messages(DOC_FIELDS, pages, "pdf")
    images = [p for p in msgs[1]["content"] if p["type"] == "image_url"]
    assert len(images) == baseline.MAX_IMAGES == notes["images_sent"]
    assert notes["pages_dropped"] == [9, 10]
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    check_messages(msgs, ModelCatalog.load().get(HAIKU))


def test_sheet_rows_are_estimated_denser_than_prose():
    # P3-18: per-kind ratios = A9 measurement - 10% (rows 1.78 -> 1.6, prose 2.96 -> 2.66),
    # read from config/models.yaml; table rows count like sheet rows, callouts like prose.
    est = ModelCatalog.load().estimate
    assert est.ratio("row") == 1.6 and est.ratio("prose") == 2.66 and est.ratio("x") == 1.5
    row = Block("row", "Sheet1!A7:H7", " | ".join(f"{c}7=1234.56" for c in "ABCDEFGH"))
    trow = Block("table_row", "Page 2", row.text)
    prose = Block("paragraph", "Page 1", "The widget supplier delivers sprockets monthly. " * 4)
    callout = Block("callout", "Page 1", prose.text)
    assert baseline._estimate_tokens(row, est) >= len(row.render()) / 1.6
    assert baseline._estimate_tokens(trow, est) >= len(trow.render()) / 1.6
    assert baseline._estimate_tokens(prose, est) >= len(prose.render()) / 2.66
    assert baseline._estimate_tokens(callout, est) == baseline._estimate_tokens(prose, est)
    big = [Block("row", f"Sheet1!A{i}:H{i}", row.text) for i in range(1, 5000)]
    _, notes = baseline.build_messages(TABLE_FIELDS, big, "xlsx", est=est)
    sent_chars = sum(len(b.text) for b in big[: 4999 - notes["rows_dropped"]])
    assert sent_chars / 1.78 <= baseline.INPUT_TOKEN_CAP  # even at the measured density
    assert notes[baseline.KIND_CHARS]["row"] > sent_chars  # text + address per row


def test_fuse_estimate_uses_kind_ratios():
    est = Estimate()
    rows_text = "A1=1 | B1=2 " * 100
    msgs = [{"role": "user", "content": "rules " * 50 + rows_text}]
    plain = est.tokens(msgs)  # everything at chars_per_token 1.5
    typed = est.tokens(msgs, {"row": len(rows_text)})
    assert typed < plain  # rows at 1.6 chars/token
    assert est.tokens(msgs, {"prose": 10**9}) > 0  # over-count is clamped to the message size


def test_extract_passes_block_chars_to_the_call():
    fake = FakeLLM(JSONOutcome("ok", data={"entries": [{}]}))
    baseline.extract(fake, CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf")
    assert set(fake.kind_chars[0]) == {"prose"}
    assert fake.kind_chars[0]["prose"] == sum(len(b.render()) + 1 for b in TEXT_BLOCKS)


# --- answer checks ----------------------------------------------------------------------------


def test_good_answer_is_cleaned_and_valid():
    data = {
        "entries": [
            {
                "supplier": f("Acme Sprockets", confidence=1.7),  # clamp
                "monthly_fee": f("$1,250.00"),  # currency string -> number
                "start_date": f(None, citation="[Page 2] should be dropped"),
                "discount_pct": f(4.5),
                "invented_extra": f("x"),  # unknown key dropped
            }
        ]
    }
    out = baseline.extract(
        FakeLLM(JSONOutcome("ok", data=data)), CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf"
    )
    assert out.reason is None and out.entries is not None
    e = out.entries[0]
    assert e["supplier"]["confidence"] == 1.0
    assert e["monthly_fee"]["value"] == 1250
    assert e["start_date"] == {"value": None, "citation": "", "confidence": 0.9}
    assert out.notes["unknown_keys_dropped"] == 1 and out.notes["values_normalised"] == 1
    assert valid(out.entries, DOC_FIELDS)


def test_partial_answer_gets_every_key_as_null():
    data = {"supplier": f("Acme Sprockets"), "monthly_fee": 1250}  # no wrapper, bare value
    out = baseline.extract(
        FakeLLM(JSONOutcome("ok", data=data)), CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf"
    )
    e = out.entries[0]
    assert set(e) == set(DOC_FIELDS["fields"])
    assert e["start_date"]["value"] is None and e["start_date"]["citation"] == ""
    assert e["monthly_fee"] == {"value": 1250, "citation": "", "confidence": 0.5}
    assert valid(out.entries, DOC_FIELDS)


def test_strings_and_odd_values_are_not_guessed():
    data = {
        "entries": [
            {
                "supplier": f({"nested": "object"}),  # not a value -> null
                "monthly_fee": f("1250"),  # plain digit string stays as returned
                "start_date": f("April 1, 2031"),
                "discount_pct": f(float("nan")),
            }
        ]
    }
    out = baseline.extract(
        FakeLLM(JSONOutcome("ok", data=data)), CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf"
    )
    e = out.entries[0]
    assert e["supplier"]["value"] is None and e["discount_pct"]["value"] is None
    assert e["monthly_fee"]["value"] == "1250" and e["start_date"]["value"] == "April 1, 2031"
    assert out.notes["values_nulled"] == 2
    assert valid(out.entries, DOC_FIELDS)


def test_table_rows_keyless_and_duplicates_dropped():
    data = {
        "entries": [
            {"sku": f("W-1"), "qty": f(3), "site": f("North")},
            {"sku": f(None), "qty": f(9), "site": f("North")},
            {"sku": f("w-1"), "qty": f(4), "site": f("North")},  # same key after normalising
            {"sku": f("W-2"), "qty": f(0), "site": f("North")},
            "junk row",
        ]
    }
    out = baseline.extract(
        FakeLLM(JSONOutcome("ok", data=data)), CTX, TABLE_FIELDS, TEXT_BLOCKS, "csv"
    )
    assert [e["sku"]["value"] for e in out.entries] == ["W-1", "W-2"]
    assert out.notes["rows_without_key_dropped"] == 1
    assert out.notes["duplicate_rows_dropped"] == 1 and out.notes["bad_entries_dropped"] == 1
    assert valid(out.entries, TABLE_FIELDS)


def test_extra_entries_for_a_document_schema_keep_the_first():
    data = {"entries": [{"supplier": f("A")}, {"supplier": f("B")}]}
    out = baseline.extract(
        FakeLLM(JSONOutcome("ok", data=data)), CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf"
    )
    assert len(out.entries) == 1 and out.entries[0]["supplier"]["value"] == "A"
    assert out.notes["extra_entries_dropped"] == 1


@pytest.mark.parametrize(
    "data",
    [{"answer": "none of your keys"}, {"entries": "not a list"}, {"entries": []}, ["x"]],
)
def test_junk_is_unusable(data):
    out = baseline.extract(
        FakeLLM(JSONOutcome("ok", data=data)), CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf"
    )
    assert out.entries is None and out.reason == "llm_unusable"


@pytest.mark.parametrize(
    "outcome, reason",
    [
        (JSONOutcome("unusable", reason="llm_truncated"), "llm_truncated"),
        (JSONOutcome("unusable", reason="llm_unusable"), "llm_unusable"),
        (JSONOutcome("stopped", reason="doc_llm_cap"), "doc_llm_cap"),
        (JSONOutcome("failed", reason="llm_failed", detail="http_500"), "llm_failed"),
    ],
)
def test_llm_trouble_passes_the_reason_through(outcome, reason):
    out = baseline.extract(FakeLLM(outcome), CTX, DOC_FIELDS, TEXT_BLOCKS, "pdf")
    assert out.entries is None and out.reason == reason


def test_empty_document_makes_no_call():
    fake = FakeLLM(JSONOutcome("ok", data={}))
    out = baseline.extract(fake, CTX, DOC_FIELDS, [], "pdf")
    assert out.reason == "no_content" and fake.calls == []


# --- worker path, end to end with a MockTransport gateway --------------------------------------


def _llm_client(database_url, reply_json: dict) -> tuple[LLMClient, list]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE llm_state SET cooldown_until = NULL, consecutive_failures = 0, "
            "breaker_open_until = NULL, probe_until = NULL"
        )
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        body = {
            "model": HAIKU,
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps(reply_json)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 900, "completion_tokens": 80, "cost": 0.00013},
        }
        return httpx.Response(200, json=body)

    c = LLMClient(
        LLMSettings(base_url="http://llm.test/v1", api_key="test-key"),
        ModelCatalog.load(),
        LLMStore(database_url),
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        rng=random.Random(0),
    )
    return c, seen


def _submit_csv(client) -> str:
    r = client.post("/jobs", files={"file": ("w.csv", CSV_BYTES)}, data={"schema": FIELD_LIST_JSON})
    assert r.status_code == 202
    return r.json()["job_id"]


def test_worker_with_key_runs_baseline_to_success(client, settings, database_url):
    reply = {
        "entries": [
            {"widget_name": f("alpha", "[Sheet1!A2] A2=alpha"), "widget_count": f(1)},
            {"widget_name": f("beta"), "widget_count": f(2)},
        ]
    }
    llm, seen = _llm_client(database_url, reply)
    jid = _submit_csv(client)
    settings = dataclasses.replace(settings, table_path="baseline")  # the baseline path itself
    assert worker.process_one(settings, "w1", llm) is True
    body = client.get(f"/jobs/{jid}").json()
    assert body["status"] == "SUCCESS"
    res = body["result"]
    assert validator.validate_contract(res, FIELD_LIST) == []
    meta = res["metadata"]
    assert meta["model_calls"] == 1 and meta["tokens_in"] == 900
    assert meta["cost_usd"] == pytest.approx(0.00013) and meta["pipeline"] == "baseline-v1"
    assert len(seen) == 1 and "[Sheet1!A2:B2] A2=alpha | B2=1" in seen[0]["messages"][1]["content"]
    llm.close()


def test_worker_with_unusable_answer_is_partial_skeleton(client, settings, database_url):
    llm, _ = _llm_client(database_url, {"nothing": "useful"})
    jid = _submit_csv(client)
    settings = dataclasses.replace(settings, table_path="baseline")  # the baseline path itself
    worker.process_one(settings, "w1", llm)
    body = client.get(f"/jobs/{jid}").json()
    assert body["status"] == "PARTIAL"
    res = body["result"]
    assert res["metadata"]["terminal_reason"] == "llm_unusable"
    assert res["metadata"]["model_calls"] == 1  # the spend is still reported
    assert all(v["value"] is None for v in res["entries"][0].values())
    assert validator.validate_contract(res, FIELD_LIST) == []
    llm.close()


def test_worker_without_key_keeps_the_stub(client, settings):
    jid = _submit_csv(client)
    worker.process_one(settings, "w1", None)
    body = client.get(f"/jobs/{jid}").json()
    assert body["status"] == "PARTIAL" and body["result"]["metadata"]["model_calls"] == 0


# --- P2-36: per-document cost fuse in the baseline ---------------------------------------------

MANY_ROWS = [
    Block("row", f"Sheet1!A{i}:B{i}", f"A{i}=widget-{i:04d} | B{i}={i * 7}", page=None)
    for i in range(2, 202)
]


def _rows_answer():
    return JSONOutcome("ok", data={"entries": [{"widget_name": f("widget-0002")}]})


def test_fuse_fits_sends_everything_and_records_the_estimate():
    llm = FakeLLM(_rows_answer())
    out = baseline.extract(llm, CTX, FIELD_LIST, MANY_ROWS, "csv")
    assert len(llm.calls) == 1 and out.notes["truncated"] is False
    assert out.notes["tokens_estimated"] == llm.estimates[0]
    assert "cost_fuse" not in out.notes


def test_fuse_trims_rows_until_the_call_fits():
    llm = FakeLLM(_rows_answer())
    full = Estimate().tokens(baseline.build_messages(FIELD_LIST, MANY_ROWS, "csv")[0])
    llm.fits_up_to = full // 2
    out = baseline.extract(llm, CTX, FIELD_LIST, MANY_ROWS, "csv")
    assert len(llm.calls) == 1
    n = out.notes
    assert n["cost_fuse"] == "trimmed" and n["truncated"] is True
    assert n["tokens_estimated"] <= llm.fits_up_to
    assert n["blocks_sent"] + n["blocks_dropped"] == len(MANY_ROWS)
    assert n["rows_dropped"] == n["blocks_dropped"] > 0
    sent = llm.calls[0][1][1]["content"]
    assert "document cut here" in sent and "widget-0201" not in sent


def test_fuse_skips_the_call_when_nothing_fits():
    llm = FakeLLM(_rows_answer())
    llm.fits_up_to = 1
    out = baseline.extract(llm, CTX, FIELD_LIST, MANY_ROWS, "csv")
    assert llm.calls == [] and out.entries is None
    assert out.reason == "doc_llm_cap" and out.notes["cost_fuse"] == "skipped"
