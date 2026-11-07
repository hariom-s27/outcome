"""scripts/fetch_models.py helpers, offline (invented gateway payloads)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("fetch_models", ROOT / "scripts/fetch_models.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fm = _load()

YAML_IN = """# comment kept
baseline: a/one
models:
  a/one:
    vision: false
    price_in: 9.0
    price_out: 9.0
    price_source: card
    reasoning: omit
    response_format: false
    max_tokens: 100
  b/two:
    vision: true
    price_in: 1.0
    price_out: 2.0
    price_source: card
    reasoning: omit
    response_format: false
    max_tokens: 100
"""


def test_summarise_per_million_and_flags():
    m = {
        "pricing": {"prompt": "0.0000002", "completion": "-1"},
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["max_tokens", "response_format", "reasoning"],
        "context_length": 1000,
    }
    f = fm.summarise(m)
    assert f["price_in"] == 0.2 and f["price_out"] is None  # -1 = variable, keep card price
    assert f["vision"] and f["response_format"] and f["reasoning_param"]


def test_update_yaml_touches_only_listed_model_and_keeps_comments():
    facts = {
        "a/one": {"price_in": 0.25, "price_out": None, "vision": True, "response_format": True}
    }
    out = fm.update_yaml(YAML_IN, facts)
    assert out.startswith("# comment kept")
    one, two = out.split("  b/two:")
    assert "price_in: 0.25" in one and "price_out: 9.0" in one
    assert "vision: true" in one and "response_format: true" in one
    assert "price_source: snapshot" in one
    assert "price_in: 1.0" in two and "price_source: card" in two


def test_fake_llm_server_shape_and_429_injection():
    from fastapi.testclient import TestClient

    from app.devtools.fake_llm import create_app

    body = {"model": "anthropic/claude-haiku-5.5", "messages": [], "max_tokens": 10}
    with TestClient(create_app(replies=['{"widget_count": 1}'])) as c:
        r = c.post("/v1/chat/completions", json=body)
        assert r.status_code == 200 and r.json()["model"] == body["model"]
        assert r.json()["choices"][0]["message"]["content"] == '{"widget_count": 1}'
        assert len(c.get("/v1/models").json()["data"]) == 9
    with TestClient(create_app(rate_429=1.0)) as c:
        r = c.post("/v1/chat/completions", json=body)
        assert r.status_code == 429 and r.headers["retry-after"] == "1"
