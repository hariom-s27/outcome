"""P9e Z-53/Z-54: SCAN_PAGE_METHOD=all. INVENTED blank page images and INVENTED answers only
(R31). No network, no key (R32).
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_p9b import DOC_FIELDS, _post
from test_single_value import SCAN_FIELDS, scan_pages, valid

from app import worker
from app.config import Settings
from app.llm import CallContext, JSONOutcome
from app.llm.client import Projection
from app.llm.models import Estimate
from app.pipeline import baseline

HAIKU = "anthropic/claude-haiku-5.5"
CTX = CallContext(job_id=None, deadline=4_000_000_000.0)


class FakeLLM:
    """Every call returns the next scripted outcome; records the messages sent."""

    def __init__(self, *outcomes: JSONOutcome):
        self.outcomes = list(outcomes)
        self.calls: list[list] = []
        self.catalog = SimpleNamespace(baseline=HAIKU, estimate=Estimate())

    def projection(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        return Projection(Estimate().tokens(messages, kind_chars), 0.01, 0.0, None)

    def complete_json(self, ctx, model, messages, **kwargs):
        self.calls.append(messages)
        return self.outcomes.pop(0)


def cell(value, citation, conf=0.9):
    return {"value": value, "citation": citation, "confidence": conf}


def answer(tenant_cite="[Page 3] Tenant: Example Tenant LLC", rent_cite="[Page 7] Rent 12,345"):
    return JSONOutcome("ok", data={"entries": [{
        "tenant_name": cell("Example Tenant LLC", tenant_cite),
        "monthly_rent": cell(12345, rent_cite),
    }]})  # fmt: skip


def run(n_pages: int, scan_all: bool = True, out: JSONOutcome | None = None, **kw):
    fake = FakeLLM(out or answer())
    res = baseline.extract(
        fake, CTX, SCAN_FIELDS, scan_pages(n_pages), "pdf", scan_all=scan_all, **kw
    )
    return res, fake


def parts_of(fake: FakeLLM) -> list[dict]:
    return fake.calls[0][1]["content"]


def images_in(fake: FakeLLM) -> int:
    return sum(1 for p in parts_of(fake) if p["type"] == "image_url")


def tags_before_images(fake: FakeLLM) -> list[str]:
    """The last text line right before each image part."""
    parts, tags = parts_of(fake), []
    for i, p in enumerate(parts):
        if p["type"] == "image_url":
            tags.append(parts[i - 1]["text"].splitlines()[-1])
    return tags


# --- all pages, tags, cap --------------------------------------------------------------------


def test_all_pages_are_sent_up_to_the_cap():
    res, fake = run(25)
    assert len(fake.calls) == 1  # one call
    assert images_in(fake) == 25
    sp = res.notes["scan_pages"]
    assert sp["method"] == "all"
    assert (sp["pages_total"], sp["image_pages"], sp["pages_sent"]) == (25, 25, 25)
    assert sp["capped"] is False and res.notes["truncated"] is False
    assert valid(res.entries, SCAN_FIELDS)


def test_each_image_follows_its_page_tag_in_order():
    _, fake = run(12)
    assert tags_before_images(fake) == [
        f"[Page {n}] PAGE {n} of 12 (no text layer; page image follows)" for n in range(1, 13)
    ]


def test_cap_keeps_the_first_40_pages():
    res, fake = run(45)
    assert images_in(fake) == baseline.MAX_SCAN_IMAGES == 40
    tags = tags_before_images(fake)
    assert tags[0].startswith("[Page 1] PAGE 1 of 45") and tags[-1].startswith("[Page 40] PAGE 40")
    sp = res.notes["scan_pages"]
    assert (sp["pages_total"], sp["image_pages"], sp["pages_sent"]) == (45, 45, 40)
    assert sp["capped"] is True
    assert res.notes["pages_dropped"] == [41, 42, 43, 44, 45]


def test_input_token_cap_still_applies():
    """Large page images: the v1.0 60k input cap stops before 40 pages (no price-tier call)."""
    big = [replace(b, width=1600, height=1600) for b in scan_pages(40)]  # 3413 est. tokens each
    fake = FakeLLM(answer())
    res = baseline.extract(fake, CTX, SCAN_FIELDS, big, "pdf", scan_all=True)
    sent = res.notes["scan_pages"]["pages_sent"]
    assert 8 < sent < 40 and images_in(fake) == sent
    assert res.notes["input_tokens_est"] <= baseline.INPUT_TOKEN_CAP


# --- page numbers from code ------------------------------------------------------------------


def test_page_numbers_come_from_sent_pages_only():
    res, _ = run(45, out=answer(rent_cite="[Page 44] Rent 12,345"))  # page 44 was not sent
    tenant, rent = res.entries[0]["tenant_name"], res.entries[0]["monthly_rent"]
    assert tenant["page_numbers"] == [3]
    assert "page_numbers" not in rent
    assert rent["value"] == 12345 and rent["citation"].startswith("[Page 44]")  # value kept
    sp = res.notes["scan_pages"]
    assert (sp["page_numbers_set"], sp["page_numbers_dropped"]) == (1, 1)
    assert valid(res.entries, SCAN_FIELDS)


def test_a_page_number_beyond_the_document_is_dropped():
    res, _ = run(12, out=answer(tenant_cite="[Page 99] Tenant: Example Tenant LLC"))
    assert "page_numbers" not in res.entries[0]["tenant_name"]
    assert res.entries[0]["monthly_rent"]["page_numbers"] == [7]


def test_null_values_get_no_page_numbers():
    out = JSONOutcome("ok", data={"entries": [{
        "tenant_name": cell(None, "[Page 2] nothing here"),
        "monthly_rent": cell(12345, "[Page 2] Rent 12,345 [page 5]"),
    }]})  # fmt: skip
    res, _ = run(10, out=out)
    assert "page_numbers" not in res.entries[0]["tenant_name"]
    assert res.entries[0]["monthly_rent"]["page_numbers"] == [2, 5]


def test_e0_path_also_gets_page_numbers():
    res, fake = run(10, robust=True)
    assert len(fake.calls) == 1 and res.notes["e0"]["calls"] == 1
    assert res.entries[0]["tenant_name"]["page_numbers"] == [3]


def test_unusable_answer_stays_the_skeleton_reason():
    res, _ = run(10, out=JSONOutcome("ok", data={"nothing": 1}))
    assert res.entries is None and res.reason == "llm_unusable"
    assert res.notes["scan_pages"]["pages_sent"] == 10
    assert "page_numbers_set" not in res.notes["scan_pages"]


# --- default unchanged -----------------------------------------------------------------------


def test_default_first_is_the_v1_call():
    res, fake = run(25, scan_all=False)
    assert images_in(fake) == baseline.MAX_IMAGES
    assert tags_before_images(fake)[0] == "[Page 1] (no text layer; page image follows)"
    assert "scan_pages" not in res.notes and baseline.PAGES_SENT not in res.notes
    assert all("page_numbers" not in c for c in res.entries[0].values())
    v1, _ = baseline.build_messages(SCAN_FIELDS, scan_pages(25), "pdf", est=Estimate())
    assert fake.calls[0] == v1


def test_short_scan_with_all_is_the_v1_call():
    """<= 8 page images: nothing is cut today, so `all` changes nothing (same request)."""
    res, fake = run(8, scan_all=True)
    v1, _ = baseline.build_messages(SCAN_FIELDS, scan_pages(8), "pdf", est=Estimate())
    assert fake.calls[0] == v1
    assert "scan_pages" not in res.notes
    assert baseline.scan_page_total(scan_pages(8)) is None
    assert baseline.scan_page_total(scan_pages(9)) == 9


def test_switch_defaults_to_all_and_first_turns_it_off(monkeypatch):  # Z-56 passed
    assert Settings().scan_page_method == "all"
    monkeypatch.setenv("SCAN_PAGE_METHOD", " FIRST ")
    assert Settings.from_env().scan_page_method == "first"
    monkeypatch.delenv("SCAN_PAGE_METHOD")
    assert Settings.from_env().scan_page_method == "all"


@pytest.mark.parametrize("method", ["first", "all"])
def test_worker_passes_scan_all_only_when_switched_on(settings, client, monkeypatch, method):
    seen: list[dict] = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return baseline.BaselineOutcome(None, "llm_unusable")

    monkeypatch.setattr(baseline, "extract", spy)
    s = settings.__class__(**{**settings.__dict__, "scan_page_method": method})
    assert _post(client, HAIKU).status_code == 202  # a single-value list (DOC_FIELDS)
    assert worker.is_single_value(DOC_FIELDS)
    llm = FakeLLM()
    llm.store = type("S", (), {"job_metadata": staticmethod(lambda jid, ms: {"latency_ms": ms})})
    llm.cache_mode = "off"
    llm.catalog.call_cap = type("C", (), {"for_doc": staticmethod(lambda ft, p, d: 4)})
    llm.settings = type("L", (), {"max_calls_per_doc": 4})
    assert worker.process_one(s, "w1", llm) is True
    assert len(seen) == 1 and ("scan_all" in seen[0]) is (method == "all")


def test_table_field_lists_never_get_scan_all():
    s = Settings(scan_page_method="all", table_path="baseline")
    table_list = {"name": "bins", "fields": {
        "code": {"name": "Code", "description": "Bin code.", "primary": True},
        "qty": {"name": "Qty", "description": "Units."},
    }}  # fmt: skip
    assert worker.choose_pipeline(s, table_list) is baseline
    assert not worker.is_single_value(table_list)  # process() adds scan_all only when single
