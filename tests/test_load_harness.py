"""P8a load harness: fake-LLM reply shape (A-4) and the load script's timing / check maths.
Invented widget data only. No network, no Docker, no key."""

from __future__ import annotations

import importlib.util
import json
import random

import pytest
from conftest import ROOT
from fastapi.testclient import TestClient

from app.contract_check import contract_errors
from app.devtools import fake_llm
from app.pipeline import baseline
from app.readers import Block
from app.results import stub_result

_spec = importlib.util.spec_from_file_location("load_test", ROOT / "scripts" / "load_test.py")
load_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_test)

SINGLE = {
    "name": "widget_sheet",
    "fields": {
        "widget_name": {"name": "Widget Name", "description": "Name of the widget."},
        "launch_date": {"name": "Launch", "description": "Launch date."},
        "unit_count": {"name": "Units", "description": "How many units."},
        "discount_pct": {"name": "Discount", "description": "Discount percent."},
        "monthly_rent": {"name": "Rent", "description": "Monthly fee."},
        "has_warranty": {"name": "Warranty", "description": "Whether there is a warranty."},
        "colour_names": {"name": "Colours", "description": "List of colours."},
    },
}
TABLE = {
    "name": "widget_rows",
    "fields": {
        "sku": {"name": "SKU", "description": "Row id.", "primary": True},
        "qty": {"name": "Qty", "description": "Quantity count."},
        "label": {"name": "Label", "description": "Label text."},
    },
}
BLOCKS = [Block("paragraph", "Page 1", "Invented widget sheet.", page=1)]
BODY = {"model": "anthropic/claude-haiku-5.5", "max_tokens": 10}


def _messages(field_list):
    return baseline.build_messages(field_list, BLOCKS, "pdf")[0]


# --- fake LLM ------------------------------------------------------------------------------------


@pytest.mark.parametrize("fl,primary", [(SINGLE, None), (TABLE, "sku")])
def test_requested_fields_reads_baseline_prompt(fl, primary):
    keys, got_primary = fake_llm.requested_fields(_messages(fl))
    assert keys == list(fl["fields"])
    assert got_primary == primary


@pytest.mark.parametrize("fl", [SINGLE, TABLE])
@pytest.mark.parametrize("seed", range(5))
def test_field_reply_passes_baseline_checks_and_contract(fl, seed):
    data = json.loads(fake_llm.field_reply(_messages(fl), random.Random(seed)))
    entries, _notes = baseline.check_answer(data, fl)
    assert entries, "fake answer must be usable by the baseline"
    meta = {"model_calls": 1, "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "latency_ms": 1}
    assert contract_errors({"entries": entries, "metadata": meta}, fl) == []


def test_field_reply_table_rows_have_distinct_keys_and_single_has_one():
    rng = random.Random(3)
    rows = json.loads(fake_llm.field_reply(_messages(TABLE), rng))["entries"]
    assert 2 <= len(rows) <= 6
    assert len({r["sku"]["value"] for r in rows}) == len(rows)
    one = json.loads(fake_llm.field_reply(_messages(SINGLE), rng))["entries"]
    assert len(one) == 1


def test_fake_value_types_follow_key_wording():
    rng = random.Random(0)
    assert isinstance(fake_llm.fake_value("launch_date", rng), str)
    assert isinstance(fake_llm.fake_value("has_warranty", rng), bool)
    assert isinstance(fake_llm.fake_value("unit_count", rng), int)
    assert isinstance(fake_llm.fake_value("discount_pct", rng), float)
    assert isinstance(fake_llm.fake_value("colour_names", rng), list)


def test_server_field_aware_429_retry_after_and_seeded():
    body = {**BODY, "messages": _messages(TABLE)}
    with TestClient(fake_llm.create_app(field_aware=True, seed=8)) as c:
        content = c.post("/v1/chat/completions", json=body).json()
        first = content["choices"][0]["message"]["content"]
        assert set(json.loads(first)["entries"][0]) == set(TABLE["fields"])
    with TestClient(fake_llm.create_app(field_aware=True, seed=8)) as c:
        again = c.post("/v1/chat/completions", json=body).json()["choices"][0]["message"]
        assert again["content"] == first  # same seed -> same answer
    with TestClient(fake_llm.create_app(rate_429=1.0, retry_after="2")) as c:
        r = c.post("/v1/chat/completions", json=body)
        assert r.status_code == 429 and r.headers["retry-after"] == "2"


def test_server_latency_is_uniform_in_range(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(fake_llm.asyncio, "sleep", fake_sleep)
    with TestClient(fake_llm.create_app(latency_range=(1.0, 6.0), seed=1)) as c:
        for _ in range(40):
            c.post("/v1/chat/completions", json={**BODY, "messages": []})
    assert len(delays) == 40 and all(1.0 <= d <= 6.0 for d in delays)
    assert max(delays) - min(delays) > 2.0  # spread, not a constant


def test_server_429_share_is_about_eight_percent():
    with TestClient(fake_llm.create_app(rate_429=0.08, seed=8)) as c:
        codes = [
            c.post("/v1/chat/completions", json={**BODY, "messages": []}).status_code
            for _ in range(500)
        ]
    share = codes.count(429) / len(codes)
    assert 0.04 < share < 0.12


# --- load script maths ---------------------------------------------------------------------------


def test_percentile_linear_interpolation():
    v = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert load_test.percentile(v, 50) == 3.0
    assert load_test.percentile(v, 95) == pytest.approx(4.8)
    assert load_test.percentile([7.0], 95) == 7.0
    assert load_test.percentile([], 50) is None
    assert load_test.percentile([5.0, 1.0, 3.0], 0) == 1.0


def test_throughput_per_min():
    assert load_test.throughput_per_min(20, 120.0) == 10.0
    assert load_test.throughput_per_min(5, 0) == 0.0


def _job(status="PARTIAL", result=None, **extra):
    body = {
        "job_id": "00000000-0000-0000-0000-000000000001",
        "status": status,
        "created_at": "2031-01-01T00:00:00Z",
        "updated_at": "2031-01-01T00:00:05Z",
    }
    if result is not None:
        body["result"] = result
    body.update(extra)
    return body


def test_result_valid_accepts_contract_results_only():
    ok = stub_result(SINGLE, 1200)
    assert load_test.result_valid("PARTIAL", _job(result=ok), SINGLE)
    assert load_test.result_valid("SUCCESS", _job("SUCCESS", result=ok), SINGLE)
    assert not load_test.result_valid("FAILED", _job("FAILED", error={"code": "x"}), SINGLE)
    assert not load_test.result_valid("PARTIAL", _job(), SINGLE)  # no result
    assert not load_test.result_valid("PARTIAL", _job(result={**ok, "extra": 1}), SINGLE)
    assert not load_test.result_valid("PARTIAL", _job(result=ok, stage="EXTRACTING"), SINGLE)
    assert not load_test.result_valid("RUNNING", _job("RUNNING"), SINGLE)
    missing = {
        "entries": [{"widget_name": ok["entries"][0]["widget_name"]}],
        "metadata": ok["metadata"],
    }
    assert not load_test.result_valid("PARTIAL", _job(result=missing), SINGLE)


def _rec(doc, job_id, status, t, valid=True, **kw):
    r = {
        "doc_id": doc,
        "kind": "csv",
        "job_id": job_id,
        "status": status,
        "valid": valid,
        "post_code": 202 if job_id else 500,
        "post_s": 0.1,
        "post_429s": 0,
        "post_429_no_ra": 0,
        "http_5xx": 0,
        "terminal_s": t,
    }
    r.update(kw)
    return r


def test_summarize_counts_lost_duplicates_and_percentiles():
    recs = [
        _rec("widget_a", "j1", "SUCCESS", 10.0),
        _rec("widget_a", "j2", "PARTIAL", 20.0, valid=False),
        _rec("widget_b", "j3", "SUCCESS", 30.0, changed_after_terminal=True),
        _rec("widget_b", "j4", None, None, valid=False),  # accepted, never terminal
        _rec("widget_b", None, None, None, valid=False, http_5xx=1),  # POST failed
    ]
    s = load_test.summarize("Lx", 2, recs, 60.0, {"j1": 1, "j2": 2, "j3": 1})
    assert s["n"] == 5 and s["submitted"] == 4 and s["terminal"] == 3
    assert s["lost"] == 2
    assert s["duplicates"] == 2  # j2 two terminal events, j3 changed after terminal
    assert s["completion_pct"] == 60.0 and s["valid_pct"] == 40.0
    assert s["p50_s"] == 20.0 and s["max_s"] == 30.0
    assert s["throughput_per_min"] == 3.0
    assert s["per_doc"]["widget_a"] == {"n": 2, "p50_s": 15.0, "p95_s": 19.5, "max_s": 20.0}
    c = load_test.criteria(s)
    assert not c["0 lost"] and not c["0 duplicates"] and not c["no 5xx"]
    assert not c[">= 80% VALID"] and c["POST < 2 s"]


def test_criteria_all_pass_on_a_clean_run():
    recs = [_rec("widget_a", f"j{i}", "SUCCESS", 5.0 + i) for i in range(10)]
    s = load_test.summarize("Lx", 1, recs, 30.0, {f"j{i}": 1 for i in range(10)})
    assert all(load_test.criteria(s).values())


def test_load_script_refuses_held_out_docs():
    sealed = sorted(load_test.HELD_OUT)[0]
    with pytest.raises(SystemExit, match="refused"):
        load_test.refuse_held_out(["widget_a", sealed])
    load_test.refuse_held_out(["widget_a"])  # DEV ids pass


def test_load_stack_commands_are_isolated():
    assert load_test.COMPOSE[:4] == ["docker", "compose", "-p", "loadtest"]
    assert load_test.COMPOSE[4:] == ["--env-file", "tests/load/loadtest.env"]
    assert load_test.BASE == "http://localhost:18080"


def test_loadtest_env_and_overlay_carry_fake_values_only():
    env = (ROOT / "tests" / "load" / "loadtest.env").read_text(encoding="utf-8")
    kv = dict(ln.split("=", 1) for ln in env.splitlines() if ln.strip() and not ln.startswith("#"))
    assert kv["LOADTEST_LLM_API_KEY"] == "fake-key-not-real"
    assert "LLM_API_KEY" not in kv and "LLM_BASE_URL" not in kv
    overlay = (ROOT / "compose.loadtest.yaml").read_text(encoding="utf-8")
    assert "18080:8080" in overlay and "!override" in overlay
    assert "http://fakellm:9999/v1" in overlay and "${LOADTEST_LLM_API_KEY:?" in overlay
    assert "docextract-loadtest:local" in overlay
    for dev_only in ("DEV_BUDGET_USD", "LLM_CACHE", "env_file"):
        assert dev_only not in overlay
