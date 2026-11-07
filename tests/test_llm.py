"""LLM wrapper behaviour with httpx MockTransport fakes (P2-13). No network, no key (R32).

All payloads are invented (widgets); nothing comes from a sample document.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from typing import Any

import httpx
import psycopg
import pytest

from app import db
from app.llm import (
    CallContext,
    ForbiddenContentError,
    LLMCallFailed,
    LLMClient,
    LLMSettings,
    LLMStopped,
    LLMStore,
    ModelCatalog,
    UnknownModelError,
)
from app.llm.client import _parse_retry_after
from app.llm.jsonparse import JSONParseError, parse_json_object
from app.llm.models import ALLOWED_MODEL_IDS

HAIKU = "anthropic/claude-haiku-5.5"
DEEPSEEK = "deepseek/deepseek-v3.2"
JOB = "00000000-0000-4000-8000-0000000000a1"
JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="
MSGS = [{"role": "user", "content": "Return the widget count as JSON."}]


# --- fakes ------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def ok_body(
    content: str = '{"widget_count": 3}',
    *,
    model: str = HAIKU,
    finish: str = "stop",
    tokens_in: int = 1000,
    tokens_out: int = 100,
    cost: float | None = None,
) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "prompt_tokens": tokens_in,
        "completion_tokens": tokens_out,
        "completion_tokens_details": {"reasoning_tokens": 0},
    }
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "gen-test",
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
        "usage": usage,
    }


Reply = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class FakeLLM:
    """Scripted MockTransport. Asserts on every request that no file part is ever sent."""

    def __init__(self, *replies: Reply, repeat_last: bool = False) -> None:
        self.replies = list(replies)
        self.repeat_last = repeat_last
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert_no_file_parts(body)
        self.requests.append(body)
        self.headers.append(request.headers)
        if not self.replies:
            raise AssertionError("unexpected extra HTTP call")
        reply = self.replies[0] if (self.repeat_last and len(self.replies) == 1) else None
        if reply is None:
            reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply) and not isinstance(reply, httpx.Response):
            return reply(request)
        return reply


def assert_no_file_parts(body: dict[str, Any]) -> None:
    for msg in body["messages"]:
        content = msg["content"]
        if isinstance(content, list):
            for part in content:
                assert part["type"] in ("text", "image_url"), part["type"]
                if part["type"] == "image_url":
                    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "file" not in json.dumps(body).lower().replace("profile", "")


def j(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None):
    return httpx.Response(status, json=body, headers=headers)


# --- fixtures ---------------------------------------------------------------------------------


@pytest.fixture
def store(database_url):
    db.migrate(database_url)
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE llm_calls, llm_slots")
        conn.execute(
            "UPDATE llm_state SET cooldown_until = NULL, consecutive_failures = 0, "
            "breaker_open_until = NULL"
        )
    s = LLMStore(database_url)
    yield s
    s.close()


@pytest.fixture
def catalog():
    return ModelCatalog.load()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_client(store, catalog, clock):
    made: list[LLMClient] = []

    def _make(fake: FakeLLM, **overrides) -> LLMClient:
        settings = LLMSettings(base_url="http://llm.test/v1", api_key="test-key", **overrides)
        c = LLMClient(
            settings,
            catalog,
            store,
            transport=httpx.MockTransport(fake),
            clock=clock,
            sleep=clock.sleep,
            rng=random.Random(0),
        )
        made.append(c)
        return c

    yield _make
    for c in made:
        c._http.close()


@pytest.fixture
def ctx(clock):
    return CallContext(job_id=JOB, deadline=clock() + 1000)


def ledger(database_url) -> list[tuple]:
    with psycopg.connect(database_url) as conn:
        return conn.execute(
            "SELECT status, attempt, model_requested, cache_hit, model_mismatch, purpose "
            "FROM llm_calls ORDER BY id"
        ).fetchall()


# --- behaviour --------------------------------------------------------------------------------


def test_success_shape_and_ledger(make_client, ctx, store, database_url):
    fake = FakeLLM(j(ok_body(cost=0.0002)))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "ok" and out.data == {"widget_count": 3}
    body = fake.requests[0]
    assert body["model"] == HAIKU and body["max_tokens"] == 4096
    assert "reasoning" not in body and "temperature" not in body and "models" not in body
    assert fake.headers[0]["authorization"] == "Bearer test-key"
    assert ledger(database_url) == [("ok", 1, HAIKU, False, False, "extract")]
    meta = store.job_metadata(JOB, latency_ms=1234)
    assert meta["model_calls"] == 1 and meta["tokens_in"] == 1000 and meta["tokens_out"] == 100
    assert meta["cost_usd"] == pytest.approx(0.0002)  # reported cost wins
    assert meta["cost_computed_usd"] == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)
    assert meta["models"][HAIKU]["calls"] == 1 and meta["latency_ms"] == 1234


def test_429_with_retry_after_then_success(make_client, ctx, clock, database_url, store):
    fake = FakeLLM(j({"error": {"message": "slow down"}}, 429, {"Retry-After": "7"}), j(ok_body()))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "ok"
    assert [r[0] for r in ledger(database_url)] == ["http_429", "ok"]
    assert max(clock.sleeps) >= 7  # waited at least Retry-After
    cooldown, _ = store.waits()
    assert cooldown > 0  # shared cool-down set for every worker


def test_500_then_success(make_client, ctx, store, database_url):
    fake = FakeLLM(j({"error": "boom"}, 500), j(ok_body()))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "ok"
    assert [r[0] for r in ledger(database_url)] == ["http_500", "ok"]
    assert store.job_metadata(JOB, 0)["model_calls"] == 2


def test_timeout_and_connection_errors_are_retried(make_client, ctx, database_url):
    fake = FakeLLM(httpx.ReadTimeout("slow"), httpx.ConnectError("refused"), j(ok_body()))
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert [r[0] for r in ledger(database_url)] == ["timeout", "connect_error", "ok"]


def test_error_inside_200_counts_as_failure(make_client, ctx, database_url):
    fake = FakeLLM(j({"error": {"code": 502, "message": "upstream"}}), j(ok_body()))
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert [r[0] for r in ledger(database_url)] == ["error_in_200", "ok"]


def test_non_retryable_error_inside_200_fails_once(make_client, ctx, database_url):
    fake = FakeLLM(j({"error": {"code": 400, "message": "bad request"}}))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "failed" and out.detail == "error_in_200"
    assert len(fake.requests) == 1


def test_finish_reason_error_is_retried(make_client, ctx, database_url):
    fake = FakeLLM(j(ok_body(finish="error")), j(ok_body()))
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert [r[0] for r in ledger(database_url)] == ["error_in_200", "ok"]


def test_4xx_is_not_retried(make_client, ctx):
    fake = FakeLLM(j({"error": {"message": "no credit"}}, 402))
    with pytest.raises(LLMCallFailed, match="http_402"):
        make_client(fake).chat(ctx, HAIKU, MSGS)
    assert len(fake.requests) == 1


def test_four_attempts_then_failed(make_client, ctx, clock):
    fake = FakeLLM(j({}, 503), repeat_last=True)
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "failed" and out.reason == "llm_failed"
    assert len(fake.requests) == 4
    backoffs = clock.sleeps
    assert len(backoffs) == 3
    for got, base in zip(backoffs, (1, 2, 4), strict=True):
        assert base <= got <= base * 1.25  # 1-2-4 s + jitter


def test_never_waits_past_time_left(make_client, clock):
    short = CallContext(job_id=JOB, deadline=clock() + 1.5)
    fake = FakeLLM(j({}, 503), j({}, 503), repeat_last=True)
    with pytest.raises(LLMStopped, match="deadline"):
        make_client(fake).chat(short, HAIKU, MSGS)
    assert len(fake.requests) == 2  # second backoff (2 s+) would pass the deadline
    assert all(s < 1.5 for s in clock.sleeps)


def test_malformed_json_gets_one_text_only_repair(make_client, ctx, catalog, database_url):
    vision_msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Count the widgets."},
                {"type": "image_url", "image_url": {"url": JPEG}},
            ],
        }
    ]
    fake = FakeLLM(
        j(ok_body('Sure! ```json\n{"widget_count": 3,,}\n```')),
        j(ok_body('{"widget_count": 3}')),
    )
    out = make_client(fake).complete_json(ctx, HAIKU, vision_msgs)
    assert out.status == "ok" and out.repaired and out.data == {"widget_count": 3}
    repair = fake.requests[1]
    assert repair["model"] == catalog.cheapest_text_model().id
    assert all(isinstance(m["content"], str) for m in repair["messages"])  # no images
    assert [r[5] for r in ledger(database_url)] == ["extract", "repair"]


def test_repair_still_bad_is_unusable(make_client, ctx):
    fake = FakeLLM(j(ok_body("not json at all")), j(ok_body("still not json")))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "unusable" and out.reason == "llm_unusable"
    assert len(fake.requests) == 2


def test_truncation_retries_once_with_bigger_max_tokens(make_client, ctx):
    fake = FakeLLM(j(ok_body('{"widget', finish="length")), j(ok_body()))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS, max_tokens=500)
    assert out.status == "ok"
    assert [r["max_tokens"] for r in fake.requests] == [500, 1000]


def test_truncation_twice_is_unusable(make_client, ctx):
    fake = FakeLLM(j(ok_body("{", finish="length")), repeat_last=True)
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "unusable" and out.reason == "llm_truncated"
    assert len(fake.requests) == 2


def test_model_mismatch_recorded_not_stopped(make_client, ctx, store, database_url):
    fake = FakeLLM(j(ok_body(model=HAIKU + "-20991231")))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "ok" and out.model_mismatch
    assert ledger(database_url)[0][4] is True
    assert store.job_metadata(JOB, 0)["model_mismatch"] is True


@pytest.mark.parametrize("listed", [True, False])
def test_json_object_only_when_config_lists_it(store, clock, ctx, listed):
    raw = {
        "baseline": HAIKU,
        "models": {
            HAIKU: {
                "vision": True,
                "price_in": 0.1,
                "price_out": 0.5,
                "reasoning": "omit",
                "response_format": listed,
                "max_tokens": 100,
            }
        },
    }
    fake = FakeLLM(j(ok_body()))
    c = LLMClient(
        LLMSettings(base_url="http://llm.test/v1", api_key="k"),
        ModelCatalog.from_dict(raw),
        store,
        transport=httpx.MockTransport(fake),
        clock=clock,
        sleep=clock.sleep,
    )
    c.complete_json(ctx, HAIKU, MSGS)
    if listed:
        assert fake.requests[0]["response_format"] == {"type": "json_object"}
    else:
        assert "response_format" not in fake.requests[0]  # prompt-only rung of the ladder
    c._http.close()


# --- stop-loss --------------------------------------------------------------------------------


def _insert_cost(database_url, usd: float, job_id: str | None = None) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO llm_calls (job_id, attempt, model_requested, status, cost_computed) "
            "VALUES (%s, 1, %s, 'ok', %s)",
            (job_id, HAIKU, usd),
        )


def test_dev_budget_stop(make_client, ctx, database_url):
    _insert_cost(database_url, 0.02)
    fake = FakeLLM()
    out = make_client(fake, dev_budget_usd=0.01).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "stopped" and out.reason == "dev_budget_reached"
    assert fake.requests == []


def test_per_doc_call_cap(make_client, ctx):
    fake = FakeLLM(j({}, 500), repeat_last=True)
    out = make_client(fake, max_calls_per_doc=2).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "stopped" and out.reason == "doc_llm_cap"
    assert len(fake.requests) == 2  # retries count toward the cap


def test_per_doc_usd_cap(make_client, ctx):
    fake = FakeLLM(j(ok_body(tokens_in=100_000, tokens_out=10_000)))
    client = make_client(fake, max_usd_per_doc=0.001)
    assert client.complete_json(ctx, HAIKU, MSGS).status == "ok"
    out = client.complete_json(ctx, HAIKU, MSGS)
    assert out.status == "stopped" and out.reason == "doc_llm_cap"
    assert len(fake.requests) == 1


def test_caps_are_per_document(make_client, clock, database_url):
    _insert_cost(database_url, 1.0, job_id=JOB)
    other = CallContext(job_id="00000000-0000-4000-8000-0000000000b2", deadline=clock() + 100)
    fake = FakeLLM(j(ok_body()))
    assert make_client(fake).complete_json(other, HAIKU, MSGS).status == "ok"


def test_circuit_breaker_trips_and_resets(make_client, ctx, clock, store):
    fake = FakeLLM(*[j({}, 500)] * 5, j(ok_body()))
    client = make_client(fake, max_calls_per_doc=100)
    with pytest.raises(LLMCallFailed):
        client.chat(ctx, HAIKU, MSGS)  # 4 failures
    clock.sleeps.clear()
    client.chat(ctx, HAIKU, MSGS)  # 5th failure trips; next attempt waits ~60 s, then succeeds
    assert any(55 <= s <= 60.5 for s in clock.sleeps)
    assert store.waits() == (0.0, 0.0)  # success closed the breaker
    with psycopg.connect(store._url) as conn:
        (n,) = conn.execute("SELECT consecutive_failures FROM llm_state").fetchone()
    assert n == 0


def test_tripped_breaker_aborts_dev_scripts(make_client, ctx, store):
    store.note_failure(threshold=1, pause_s=60)
    fake = FakeLLM()
    with pytest.raises(LLMStopped, match="circuit_open"):
        make_client(fake, breaker_abort=True).chat(ctx, HAIKU, MSGS)
    assert fake.requests == []


# --- cache, limiter, request hygiene ------------------------------------------------------------


def test_cache_hit_makes_no_second_http_call(make_client, ctx, tmp_path, store, database_url):
    fake = FakeLLM(j(ok_body()))
    client = make_client(fake, cache_dir=str(tmp_path / "llm"))
    first = client.complete_json(ctx, HAIKU, MSGS)
    second = client.complete_json(ctx, HAIKU, MSGS)
    assert first.data == second.data and len(fake.requests) == 1
    assert [r[3] for r in ledger(database_url)] == [False, True]
    meta = store.job_metadata(JOB, 0)
    assert meta["model_calls"] == 1 and meta["cache_hits"] == 1


def test_no_cache_unless_configured(make_client, ctx):
    fake = FakeLLM(j(ok_body()), j(ok_body()))
    client = make_client(fake)
    client.complete_json(ctx, HAIKU, MSGS)
    client.complete_json(ctx, HAIKU, MSGS)
    assert len(fake.requests) == 2


def test_crashed_holders_slot_frees_itself(make_client, ctx, store, database_url):
    store.ensure_slots(1)
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE llm_slots SET holder = 'dead-worker', "
            "lease_until = now() - interval '1 second' WHERE slot = 0"
        )
    fake = FakeLLM(j(ok_body()))
    assert make_client(fake, max_concurrency=1).complete_json(ctx, HAIKU, MSGS).status == "ok"
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT holder FROM llm_slots WHERE slot = 0").fetchone() == (None,)


def test_live_slot_holder_blocks_until_deadline(make_client, clock, store, database_url):
    store.ensure_slots(1)
    assert store.try_acquire_slot("live-worker", cap=1, lease_s=300) == 0
    short = CallContext(job_id=JOB, deadline=clock() + 2)
    fake = FakeLLM()
    with pytest.raises(LLMStopped, match="deadline"):
        make_client(fake, max_concurrency=1).chat(short, HAIKU, MSGS)
    assert fake.requests == []


@pytest.mark.parametrize(
    "part",
    [
        {"type": "file", "file": {"filename": "w.pdf", "file_data": "data:application/pdf;b,"}},
        {"type": "input_file", "file_id": "f1"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        {"type": "image_url", "image_url": {"url": "https://example.invalid/w.jpg"}},
    ],
)
def test_file_parts_and_non_jpeg_images_never_sent(make_client, ctx, part):
    fake = FakeLLM()
    msgs = [{"role": "user", "content": [{"type": "text", "text": "widgets"}, part]}]
    with pytest.raises(ForbiddenContentError):
        make_client(fake).complete_json(ctx, HAIKU, msgs)
    assert fake.requests == []


def test_images_refused_for_text_only_model(make_client, ctx):
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": JPEG}}]}]
    with pytest.raises(ForbiddenContentError):
        make_client(FakeLLM()).chat(ctx, DEEPSEEK, msgs)


def test_unknown_model_id_refused(make_client, ctx, catalog):
    fake = FakeLLM()
    for bad in ("openai/gpt-4o", "anthropic/claude-haiku-5.5:free", "~anthropic/claude-haiku"):
        with pytest.raises(UnknownModelError):
            make_client(fake).chat(ctx, bad, MSGS)
    assert fake.requests == []
    raw = {"baseline": "x/not-allowed", "models": {}}
    with pytest.raises(UnknownModelError):
        ModelCatalog.from_dict(raw)


def test_config_lists_exactly_the_nine_allowed_ids(catalog):
    assert set(catalog.ids()) == ALLOWED_MODEL_IDS and len(catalog.ids()) == 9
    assert set(catalog.fallback_order) <= ALLOWED_MODEL_IDS


def test_missing_key_fails_without_http(store, catalog, clock, ctx):
    fake = FakeLLM()
    c = LLMClient(
        LLMSettings(base_url="http://llm.test/v1", api_key=""),
        catalog,
        store,
        transport=httpx.MockTransport(fake),
        clock=clock,
        sleep=clock.sleep,
    )
    out = c.complete_json(ctx, HAIKU, MSGS)
    assert out.status == "failed" and out.detail == "llm_not_configured"
    assert fake.requests == []


# --- pure helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"widget_count": 3}',
        '```json\n{"widget_count": 3}\n```',
        'Here you go: {"widget_count": 3} hope that helps',
        '```\n{"widget_count": 3}\n```',
    ],
)
def test_parse_json_object_variants(text):
    assert parse_json_object(text) == {"widget_count": 3}


def test_parse_json_object_braces_inside_strings():
    assert parse_json_object('x {"note": "a } b {", "n": 1} y') == {"note": "a } b {", "n": 1}


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2]", '{"a": 1,,}'])
def test_parse_json_object_failures(text):
    with pytest.raises(JSONParseError):
        parse_json_object(text)


def test_retry_after_forms():
    assert _parse_retry_after("3", 0) == 3.0
    assert _parse_retry_after(None, 0) is None
    assert _parse_retry_after("Thu, 01 Jan 1970 00:00:10 GMT", 4.0) == pytest.approx(6.0)
    assert _parse_retry_after("soon", 0) is None


def test_price_cliff(catalog):
    spec = catalog.get(HAIKU)
    below = spec.cost(99_999, 0)
    at = spec.cost(100_000, 0)
    assert at == pytest.approx(5 * 100_000 * 0.10 / 1e6) and below < at / 4
