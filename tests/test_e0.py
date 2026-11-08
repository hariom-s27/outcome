"""P9b E0 (Z-33): robust parsing behind E0_ROBUST. INVENTED broken JSON and INVENTED bad specs
only (R31). No network, no key (R32).
"""

from __future__ import annotations

import json
import random

import httpx
import psycopg
import pytest
from conftest import validator
from test_p9b import DOC_FIELDS, _post
from test_tables import (
    CTX,
    FLAT_FIELDS,
    LONG,
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
from app.llm import JSONOutcome, LLMClient, LLMSettings, LLMStore, ModelCatalog
from app.pipeline import baseline, table_spec
from app.readers.base import Block

HAIKU = "anthropic/claude-haiku-5.5"
TEXT = [
    Block("paragraph", "Page 1", "Widget supply agreement. Supplier: Acme Sprockets.", page=1),
    Block("paragraph", "Page 2", "The order covers 12 widgets.", page=2),
]
GOOD = json.dumps({"entries": [{
    "supplier": {"value": "Acme Sprockets", "citation": "[Page 1] Supplier: Acme Sprockets",
                 "confidence": 0.9},
    "widget_count": {"value": 12, "citation": "[Page 2] 12 widgets", "confidence": 0.8},
}]})  # fmt: skip
# invented breakage: a missing comma inside one field's object; the other field is fine
BROKEN_ONE_FIELD = (
    '{"entries": [{"widget_count": {"value": 12, "citation": "[Page 2] 12 widgets" '
    '"confidence": 0.8}, "supplier": {"value": "Acme Sprockets", "citation": '
    '"[Page 1] Supplier: Acme Sprockets", "confidence": 0.9}}]}'
)
GARBAGE = "Sorry, here are the widgets: supplier Acme, count twelve"


# --- the forgiving parse itself ---


def test_salvage_entries_keeps_the_good_fields_of_a_broken_entry():
    data, bad = baseline.salvage_entries(BROKEN_ONE_FIELD)
    assert bad == ["entries.widget_count"]
    assert data["entries"][0]["supplier"]["value"] == "Acme Sprockets"
    assert "widget_count" not in data["entries"][0]


def test_salvage_entries_on_good_json_and_on_garbage():
    assert baseline.salvage_entries(GOOD) == (json.loads(GOOD), [])
    assert baseline.salvage_entries(GARBAGE)[0] is None
    trailing = GOOD[:-2] + ",]}"  # invented trailing comma
    assert baseline.salvage_entries(trailing)[0] == json.loads(GOOD)


# --- the single-value ladder, real client + MockTransport gateway ---


def _client(database_url, replies: list[str]) -> tuple[LLMClient, list]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE llm_state SET cooldown_until = NULL, consecutive_failures = 0, "
            "breaker_open_until = NULL, probe_until = NULL"
        )
    seen: list = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": HAIKU,
            "choices": [{"message": {"role": "assistant", "content": queue.pop(0)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 60},
        })  # fmt: skip

    c = LLMClient(
        LLMSettings(base_url="http://llm.test/v1", api_key="test-key"),
        ModelCatalog.load(),
        LLMStore(database_url),
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        rng=random.Random(0),
    )
    return c, seen


def _purposes(database_url) -> list[str]:
    with psycopg.connect(database_url) as conn:
        return [r[0] for r in conn.execute("SELECT purpose FROM llm_calls ORDER BY id")]


@pytest.fixture
def ledger(clean_db, database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE llm_calls")
    return database_url


def test_e0_salvage_rescues_one_broken_field_without_a_repair_call(ledger):
    llm, seen = _client(ledger, [BROKEN_ONE_FIELD])
    out = baseline.extract(llm, CTX, DOC_FIELDS, TEXT, "pdf", robust=True)
    assert out.entries is not None and len(seen) == 1
    e = out.entries[0]
    assert e["supplier"]["value"] == "Acme Sprockets" and e["widget_count"]["value"] is None
    assert out.notes["e0"] == {"calls": 1, "salvage_used": 1, "fields_salvaged_away": 1,
                               "rescued_by": "salvage"}  # fmt: skip
    llm.close()


def test_e0_recall_after_salvage_and_repair_fail(ledger):
    llm, _ = _client(ledger, [GARBAGE, GARBAGE, GOOD])
    out = baseline.extract(llm, CTX, DOC_FIELDS, TEXT, "pdf", robust=True)
    assert out.entries is not None and out.entries[0]["widget_count"]["value"] == 12
    assert _purposes(ledger) == ["extract", "repair", "e0_recall"]
    assert out.notes["e0"]["rescued_by"] == "recall"
    assert out.notes["e0"]["first_reason"] == "llm_unusable"
    llm.close()


def test_e0_gives_up_after_one_recall(ledger):
    llm, _ = _client(ledger, [GARBAGE] * 4)
    out = baseline.extract(llm, CTX, DOC_FIELDS, TEXT, "pdf", robust=True)
    assert out.entries is None and out.reason == "llm_unusable"
    assert _purposes(ledger) == ["extract", "repair", "e0_recall", "repair"]
    assert out.notes["e0"]["rescued_by"] is None and out.notes["e0"]["calls"] == 2
    llm.close()


def test_e0_good_answer_needs_nothing(ledger):
    llm, seen = _client(ledger, [GOOD])
    out = baseline.extract(llm, CTX, DOC_FIELDS, TEXT, "pdf", robust=True)
    assert out.entries is not None and len(seen) == 1
    assert out.notes["e0"]["rescued_by"] == "none_needed"
    llm.close()


def test_default_off_keeps_the_v1_ladder(ledger):
    llm, _ = _client(ledger, [BROKEN_ONE_FIELD, GOOD])
    out = baseline.extract(llm, CTX, DOC_FIELDS, TEXT, "pdf")
    assert out.entries is not None and out.notes.get("json_repaired") is True
    assert _purposes(ledger) == ["extract", "repair"] and "e0" not in out.notes
    llm.close()


def test_e0_leaves_table_field_lists_on_the_v1_path(ledger):
    table_fields = {"name": "w", "fields": {
        "sku": {"name": "SKU", "description": "Widget SKU.", "primary": True}}}  # fmt: skip
    llm, _ = _client(ledger, [GARBAGE, GARBAGE])
    out = baseline.extract(llm, CTX, table_fields, TEXT, "pdf", robust=True)
    assert out.entries is None and "e0" not in out.notes
    assert _purposes(ledger) == ["extract", "repair"]
    llm.close()


# --- table spec: one more spec call on low fill or dropped entries ---

NO_MATCH_DATA = make_xlsx({"Stock": renamed(flat_rows(70), NO_MATCH)})


def _table(out) -> dict:
    return out.notes["extraction"]["table"]


def test_e0_dropped_entry_asks_once_more_and_keeps_the_higher_fill():
    # invented bad spec: an unknown top-level key and only 1 of 3 row fields mapped
    bad = flat_spec(extra_key=1, row_fields={"item_name": {"col": "B"}})
    fake = FakeLLM(ok(bad), ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(NO_MATCH_DATA), "xlsx", robust=True)
    t = _table(out)
    assert [c[0] for c in fake.calls] == ["table_spec", "table_spec_e0"]
    assert t["e0"]["why"] == "entries_dropped" and t["e0"]["kept"] == "retry_result"
    assert t["e0"]["fill_before"] == 0.3333 and t["e0"]["fill_after"] == 1.0
    assert t["candidates"][t["chosen"]]["filled"] == 1.0 and t["calls"] == 2
    assert (
        validator.validate_contract(
            {"entries": out.entries, "metadata": baseline._zero_meta()}, FLAT_FIELDS
        )
        == []
    )


def test_e0_low_fill_retry_that_is_worse_keeps_the_first_choice():
    first = flat_spec(row_fields={"item_name": {"col": "B"}})  # fill 1/3, nothing dropped
    fake = FakeLLM(ok(first), ok(flat_spec(row_fields={})))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(NO_MATCH_DATA), "xlsx", robust=True)
    t = _table(out)
    assert t["e0"]["why"] == "low_fill" and t["e0"]["kept"] == "first"
    assert t["chosen"] == "ai" and t["candidates"]["ai"]["filled"] == 0.3333  # summary: 4 dp


def test_e0_no_retry_on_a_full_fill_or_when_the_model_was_stopped():
    fake = FakeLLM(ok(flat_spec()))
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(LONG), "xlsx", robust=True)
    assert len(fake.calls) == 1 and "e0" not in _table(out)
    stopped = FakeLLM(JSONOutcome("stopped", reason="doc_llm_cap"))
    out = table_spec.extract(
        stopped, CTX, FLAT_FIELDS, blocks_of(NO_MATCH_DATA), "xlsx", robust=True
    )
    assert len(stopped.calls) == 1 and "e0" not in _table(out)


def test_default_off_keeps_b5_only():
    bad = flat_spec(extra_key=1, row_fields={"item_name": {"col": "B"}})
    fake = FakeLLM(ok(bad))  # fill 1/3 > 0: no B-5 retry, no E0
    out = table_spec.extract(fake, CTX, FLAT_FIELDS, blocks_of(NO_MATCH_DATA), "xlsx")
    assert len(fake.calls) == 1 and "e0" not in _table(out)


# --- worker wiring + switch ---


@pytest.mark.parametrize(
    "raw, on",
    [(None, True), ("", True), ("1", True), ("0", False), ("false", False), ("OFF", False)],
)
def test_e0_switch_defaults_on_and_can_be_turned_off(monkeypatch, raw, on):  # Z-35
    assert Settings().e0_robust is True
    if raw is None:
        monkeypatch.delenv("E0_ROBUST", raising=False)
    else:
        monkeypatch.setenv("E0_ROBUST", raw)
    assert Settings.from_env().e0_robust is on


@pytest.mark.parametrize("on", [False, True])
def test_worker_passes_robust_only_when_switched_on(
    settings, client, database_url, monkeypatch, on
):
    seen: list[dict] = []
    real = baseline.extract

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(baseline, "extract", spy)
    llm, _ = _client(database_url, [GOOD])
    # P9e: scan_page_method pinned to first so only the E0 kwarg is under test (all is the
    # lab default and adds scan_all; tests/test_p9e.py covers that kwarg)
    s = settings.__class__(**{**settings.__dict__, "e0_robust": on, "scan_page_method": "first"})
    jid = _post(client, "").json()["job_id"]
    assert worker.process_one(s, "w1", llm) is True
    assert seen == ([{"robust": True}] if on else [{}])
    meta = client.get(f"/jobs/{jid}").json()["result"]["metadata"]
    assert ("e0" in meta) is on
    llm.close()
