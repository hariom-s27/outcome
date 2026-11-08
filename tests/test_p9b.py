"""P9b Part A: model switch (SV_MODEL, LAB_MODE debug_model, reasoning "lowest", text-only
models) and the Z-24 gate repair. Invented widget data only (R31). No network, no key (R32).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import random
import sys
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from conftest import CSV_BYTES, ROOT, validator

from app import lab, worker
from app.config import Settings
from app.llm import CallContext, JSONOutcome, LLMClient, LLMSettings, LLMStore, ModelCatalog
from app.llm.client import Projection
from app.llm.models import Estimate
from app.pipeline import baseline
from app.readers.base import Block

HAIKU = "anthropic/claude-haiku-5.5"
LUNA = "openai/gpt-6-luna"
DEEPSEEK = "deepseek/deepseek-v3.2"
CTX = CallContext(job_id=None, deadline=4_000_000_000.0)

DOC_FIELDS = {
    "name": "widget_contract",
    "fields": {
        "supplier": {"name": "Supplier", "description": "Supplier name."},
        "widget_count": {"name": "Widget Count", "description": "How many widgets."},
    },
}
TABLE_FIELDS = {
    "name": "widget_table",
    "fields": {
        "sku": {"name": "SKU", "description": "Widget SKU.", "primary": True},
        "qty": {"name": "Qty", "description": "Quantity."},
    },
}


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


compare_runs = _load("compare_runs")
make_outputs = _load("make_outputs")
eval_dev = _load("eval_dev")


# --- reasoning "lowest" ---


def _catalog(reasoning: str, snap) -> ModelCatalog:
    raw = {
        "baseline": HAIKU,
        "models": {
            HAIKU: {"vision": True, "price_in": 0.1, "price_out": 0.5, "reasoning": reasoning,
                    "response_format": True, "max_tokens": 64},
        },
    }  # fmt: skip
    return ModelCatalog.from_dict(raw, {"models": {HAIKU: {"reasoning": snap} if snap else {}}})


@pytest.mark.parametrize(
    "snap, expect",
    [
        ({"mandatory": False, "supported_efforts": ["low", "none"]}, {"effort": "none"}),
        ({"mandatory": True, "supported_efforts": ["high", "medium", "low"]}, {"effort": "low"}),
        ({"mandatory": True, "supported_efforts": ["max", "high", "low"]}, {"effort": "low"}),
        ({"mandatory": False, "default_enabled": False}, None),  # off by default, no efforts
        (None, None),  # no reasoning block: nothing to turn down
    ],
)
def test_lowest_turns_reasoning_off_or_to_its_lowest_effort(snap, expect):
    assert _catalog("lowest", snap).get(HAIKU).reasoning_param() == expect


def test_shipped_yaml_keeps_haiku_and_its_repair_model():
    cat = ModelCatalog.load()
    assert cat.baseline == HAIKU
    assert cat.get(HAIKU).reasoning_param() == {"effort": "none"}  # v1.0, unchanged
    assert cat.cheapest_text_model().id == HAIKU  # the repair call is unchanged
    assert cat.get(LUNA).reasoning_param() == {"effort": "none"}
    for mid in ("z-ai/glm-5.3-flash", "google/gemini-3.8-flash", "anthropic/claude-sonnet-5.5"):
        assert cat.get(mid).reasoning_param() == {"effort": "low"}
    assert cat.get(DEEPSEEK).reasoning_param() is None  # reasoning off by default
    assert all(cat.get(m).max_tokens == cat.get(HAIKU).max_tokens for m in cat.ids())


# --- settings + lab switches ---


def test_settings_default_to_v1_and_refuse_unknown_model():
    s = Settings()
    assert s.sv_model is None and s.lab_mode is False
    with pytest.raises(ValueError):
        Settings(sv_model="acme/widget-llm")


def test_settings_read_sv_model_and_lab_mode(monkeypatch):
    monkeypatch.setenv("SV_MODEL", LUNA)
    monkeypatch.setenv("LAB_MODE", "1")
    s = Settings.from_env()
    assert s.sv_model == LUNA and s.lab_mode is True
    monkeypatch.delenv("SV_MODEL")
    monkeypatch.delenv("LAB_MODE")
    s = Settings.from_env()
    assert s.sv_model is None and s.lab_mode is False


def test_debug_model_ignored_when_lab_mode_off():
    off = Settings()
    assert lab.attach_debug_model(off, DOC_FIELDS, LUNA) is DOC_FIELDS
    stored = {**DOC_FIELDS, lab.LAB_MODEL_KEY: LUNA}  # even if a client sent the key itself
    fl, model = lab.split_debug_model(off, stored)
    assert fl is stored and model is None
    assert lab.sv_model_for(off, DOC_FIELDS, None) is None


def test_debug_model_round_trip_in_lab_mode():
    on = Settings(lab_mode=True)
    stored = lab.attach_debug_model(on, DOC_FIELDS, f" {LUNA} ")
    assert stored[lab.LAB_MODEL_KEY] == LUNA and lab.LAB_MODEL_KEY not in DOC_FIELDS
    fl, model = lab.split_debug_model(on, stored)
    assert fl == DOC_FIELDS and model == LUNA
    assert lab.sv_model_for(on, fl, model) == LUNA
    assert lab.sv_model_for(on, TABLE_FIELDS, model) is None  # tables keep the baseline
    assert lab.attach_debug_model(on, DOC_FIELDS, "") is DOC_FIELDS
    with pytest.raises(lab.BadDebugModel):
        lab.attach_debug_model(on, DOC_FIELDS, "acme/widget-llm")


def test_sv_model_setting_applies_to_single_value_lists_only():
    s = Settings(sv_model=LUNA)
    assert lab.sv_model_for(s, DOC_FIELDS, None) == LUNA
    assert lab.sv_model_for(s, TABLE_FIELDS, None) is None


# --- API ---


def _stored_field_list(database_url: str, job_id: str) -> dict:
    with psycopg.connect(database_url) as conn:
        return conn.execute("SELECT field_list FROM jobs WHERE id = %s", (job_id,)).fetchone()[0]


def _post(c, model: str):
    return c.post(
        "/jobs",
        files={"file": ("w.csv", CSV_BYTES)},
        data={"schema": json.dumps(DOC_FIELDS), "debug_model": model},
    )


def test_api_ignores_debug_model_in_the_shipped_config(client, database_url):
    r = _post(client, LUNA)
    assert r.status_code == 202
    assert _stored_field_list(database_url, r.json()["job_id"]) == DOC_FIELDS
    assert _post(client, "acme/widget-llm").status_code == 202  # not even validated


def test_api_stores_debug_model_in_lab_mode(settings, clean_db, database_url):
    from fastapi.testclient import TestClient

    from app.api import create_app

    with TestClient(create_app(dataclasses.replace(settings, lab_mode=True))) as c:
        r = _post(c, LUNA)
        assert r.status_code == 202
        assert _stored_field_list(database_url, r.json()["job_id"])[lab.LAB_MODEL_KEY] == LUNA
        bad = _post(c, "acme/widget-llm")
        assert bad.status_code == 400 and bad.json()["code"] == "invalid_debug_model"


# --- worker end to end (MockTransport gateway) ---


def _client(database_url) -> tuple[LLMClient, list]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE llm_state SET cooldown_until = NULL, consecutive_failures = 0, "
            "breaker_open_until = NULL, probe_until = NULL"
        )
    seen: list = []
    reply = {"entries": [{"supplier": {"value": None, "citation": "", "confidence": 0.9},
                          "widget_count": {"value": 2, "citation": "[Sheet1!B3] B3=2",
                                           "confidence": 0.9}}]}  # fmt: skip

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={
            "model": body["model"],
            "choices": [{"message": {"role": "assistant", "content": json.dumps(reply)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 40},
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


@pytest.mark.parametrize(
    "lab_on, sent, expect_model, expect_note",
    [
        (False, LUNA, HAIKU, None),  # shipped: the part is ignored, v1.0 model
        (True, LUNA, LUNA, LUNA),  # lab: one job, one model
        (True, "", HAIKU, None),  # lab, no part: still v1.0
    ],
)
def test_worker_uses_debug_model_only_in_lab_mode(
    settings, clean_db, database_url, lab_on, sent, expect_model, expect_note
):
    from fastapi.testclient import TestClient

    from app.api import create_app

    s = dataclasses.replace(settings, lab_mode=lab_on)
    llm, seen = _client(database_url)
    with TestClient(create_app(s)) as c:
        jid = _post(c, sent).json()["job_id"]
        assert worker.process_one(s, "w1", llm) is True
        body = c.get(f"/jobs/{jid}").json()
    assert body["status"] == "SUCCESS"
    assert [b["model"] for b in seen] == [expect_model]
    meta = body["result"]["metadata"]
    assert meta.get("sv_model") == expect_note
    assert validator.validate_contract(body["result"], DOC_FIELDS) == []
    llm.close()


# --- text-only models ---


class FakeLLM:
    def __init__(self, vision: bool):
        self.calls: list = []
        self.catalog = SimpleNamespace(
            baseline=HAIKU, estimate=Estimate(), get=lambda m: SimpleNamespace(vision=vision)
        )

    def projection(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        return Projection(100, 0.001)

    def complete_json(self, ctx, model, messages, *, max_tokens=None, kind_chars=None):
        self.calls.append((model, messages))
        cell = {"value": "Acme Sprockets", "citation": "[Page 1] x", "confidence": 0.9}
        return JSONOutcome("ok", data={"entries": [{"supplier": cell}]})


IMG = Block("image", "Page 2", "", page=2, width=100, height=100, jpeg=b"\xff\xd8widget")
TXT = Block("paragraph", "Page 1", "Widget supply agreement. Supplier: Acme Sprockets.", page=1)


def _parts(messages) -> list[str]:
    content = messages[1]["content"]
    return ["text"] if isinstance(content, str) else [p["type"] for p in content]


def test_text_only_model_gets_text_blocks_and_counts_skipped_images():
    fake = FakeLLM(vision=False)
    out = baseline.extract(fake, CTX, DOC_FIELDS, [TXT, IMG], "pdf", DEEPSEEK)
    assert out.entries is not None and out.notes["images_skipped_no_vision"] == 1
    assert "image_url" not in _parts(fake.calls[0][1])


def test_text_only_model_on_images_only_is_na_not_a_failure():
    fake = FakeLLM(vision=False)
    out = baseline.extract(fake, CTX, DOC_FIELDS, [IMG], "pdf", DEEPSEEK)
    assert out.entries is None and out.reason == "model_no_vision" and fake.calls == []


def test_vision_model_still_gets_the_image():
    fake = FakeLLM(vision=True)
    out = baseline.extract(fake, CTX, DOC_FIELDS, [TXT, IMG], "pdf", HAIKU)
    assert "images_skipped_no_vision" not in out.notes
    assert "image_url" in _parts(fake.calls[0][1])


# --- eval script ---


def test_multipart_default_body_is_unchanged_and_extra_adds_a_part(tmp_path):
    doc = tmp_path / "w.csv"
    doc.write_bytes(CSV_BYTES)
    body, ctype = make_outputs.multipart(doc, "{}")
    assert b"debug_model" not in body and body.endswith(b"--\r\n")
    assert body.count(b"Content-Disposition") == 2
    body2, _ = make_outputs.multipart(doc, "{}", {"debug_model": LUNA})
    assert body2.count(b"Content-Disposition") == 3
    assert b'name="debug_model"\r\n\r\n' + LUNA.encode() in body2


def test_debug_model_must_be_reported_on_single_value_docs(tmp_path):
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps(DOC_FIELDS), encoding="utf-8")
    row = {"schema_name": "s", "schema_path": str(schema)}
    ok = {"result": {"metadata": {"sv_model": LUNA}}}
    ignored = {"result": {"metadata": {}}}
    assert eval_dev.debug_model_honoured(ok, row, LUNA)
    assert not eval_dev.debug_model_honoured(ignored, row, LUNA)
    schema.write_text(json.dumps(TABLE_FIELDS), encoding="utf-8")
    assert eval_dev.debug_model_honoured(ignored, row, LUNA)  # tables keep the baseline


# --- gate repair (Z-24), fake runs ---


def agg(scores, halluc=0.0, usd=0.005, valid=True, set_="dev"):
    return {"set": set_, "n": len(scores), "score": sum(scores) / len(scores),
            "scores": list(scores), "min": min(scores), "halluc": halluc, "missed": 0.0,
            "rows_pred": 1, "rows_truth": 1, "usd": usd, "valid": valid}  # fmt: skip


BASE = {
    "widget_a": agg([0.60, 0.62, 0.58]),
    "widget_b": agg([0.90, 0.20, 0.88]),  # one v1.0 collapse (0.20 < 0.5 x 0.88)
    "widget_c": agg([0.50, 0.50, 0.50]),  # not affected by the switch
    "syn_x": agg([0.40, 0.40, 0.40], set_="syn"),
}


def test_aggregate_keeps_per_run_scores_and_min():
    recs = [{"doc": "widget_a", "score": s, "totals": {}, "valid": True} for s in (0.5, 0.9, 0.7)]
    a = compare_runs.aggregate(recs)["widget_a"]
    assert a["scores"] == [0.5, 0.9, 0.7] and a["min"] == 0.5 and a["n"] == 3


def test_collapse_counts_runs_below_half_the_v1_median():
    assert compare_runs.collapses(BASE, BASE, ["widget_a", "widget_b"]) == 1
    cand = {"widget_a": agg([0.70, 0.25, 0.70]), "widget_b": agg([0.90, 0.40, 0.10])}
    assert compare_runs.collapses(cand, BASE, ["widget_a", "widget_b"]) == 3


def test_docs_limit_the_gate_to_the_declared_set():
    # widget_c drops a lot but is outside the declared set; on all docs it would fail
    cand = {
        "widget_a": agg([0.66, 0.68, 0.64]),
        "widget_b": agg([0.92, 0.90, 0.91]),
        "widget_c": agg([0.10, 0.10, 0.10]),
        "syn_x": agg([0.40, 0.40, 0.40], set_="syn"),
    }
    declared = ["widget_a", "widget_b"]
    g = compare_runs.gate(BASE, cand, declared)
    assert g["verdict"] == "PASS", g["checks"]
    assert g["common"] == declared
    assert compare_runs.gate(BASE, cand)["verdict"] == "FAIL"


def test_more_collapses_than_base_fail_alone():
    cand = {"widget_a": agg([0.90, 0.90, 0.25]), "widget_b": agg([0.90, 0.10, 0.90])}
    g = compare_runs.gate(BASE, cand, ["widget_a", "widget_b"])
    assert [k for k, (ok, _) in g["checks"].items() if not ok] == ["collapses"]
    assert (g["collapses_base"], g["collapses_cand"]) == (1, 2)


def test_declared_doc_missing_on_one_side_fails_same_docs():
    cand = {"widget_a": agg([0.9, 0.9, 0.9])}
    g = compare_runs.gate(BASE, cand, ["widget_a", "widget_b"])
    assert not g["checks"]["same_docs"][0]


def test_thresholds_unchanged():
    assert compare_runs.GATE_MIN_GAIN == 0.025
    assert compare_runs.GATE_MAX_DEV_DROP == 0.05
    assert compare_runs.GATE_MAX_USD_PER_DOC == 0.01
    assert compare_runs.COLLAPSE_SHARE == 0.5
