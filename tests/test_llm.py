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
from app.llm.store import LedgerRow

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
            "breaker_open_until = NULL, probe_until = NULL"
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
    assert body["reasoning"] == {"effort": "none"}  # P2-31: Haiku set to none, snapshot allows
    assert "temperature" not in body and "models" not in body
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
                "reasoning": "default",
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
    # the projection (tiny prompt + max_tokens) fits 0.01; the real bill does not: the
    # after-call check stops the next call (P2-36 keeps it)
    client = make_client(fake, max_usd_per_doc=0.01)
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


def test_cache_hit_keeps_the_original_cost_for_the_uncached_figure(
    make_client, ctx, tmp_path, store, database_url
):
    fake = FakeLLM(j(ok_body(cost=0.0002)))
    client = make_client(fake, cache_dir=str(tmp_path / "llm"))
    client.complete_json(ctx, HAIKU, MSGS)
    client.complete_json(ctx, HAIKU, MSGS)
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "SELECT cache_hit, cost_reported, cost_original FROM llm_calls ORDER BY id"
        ).fetchall()
    assert rows == [(False, 0.0002, None), (True, None, 0.0002)]
    meta = store.job_metadata(JOB, 0)
    assert meta["cost_usd"] == pytest.approx(0.0002)  # paid
    assert meta["cost_uncached_usd"] == pytest.approx(0.0004)  # what a grader would pay


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


# --- P2 addendum (P2-31, P2-33): wrapper fixes, MockTransport fakes, no network ----------
#
# - one wait after a 429: max(backoff, Retry-After, shared cool-down left), never the sum
# - half-open breaker: after the pause exactly one probe call goes; success closes, failure
#   re-opens for another pause; the others wait
# - per-model reasoning: none -> {"effort": "none"} only when the snapshot allows it;
#   a 400 to it -> one retry without, ledger flag reasoning_param_dropped
# Payloads are invented (widgets).


def _state(url: str) -> tuple:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT breaker_open_until IS NOT NULL, "
            "coalesce(extract(epoch FROM breaker_open_until - now()), 0), "
            "probe_until IS NOT NULL, consecutive_failures FROM llm_state"
        ).fetchone()


def _half_open(url: str, probe_held: bool = False) -> None:
    """Breaker pause already over (half-open); optionally a live caller holds the probe."""
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE llm_state SET breaker_open_until = now() - interval '1 second', "
            "probe_until = CASE WHEN %s THEN now() + interval '5 minutes' END",
            (probe_held,),
        )


def _ledger_flags(url: str) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT status, reasoning_effort, reasoning_param_dropped FROM llm_calls ORDER BY id"
        ).fetchall()


# --- one wait after a 429 ------------------------------------------------------------------


def test_429_retry_after_is_waited_once_not_twice(make_client, ctx, clock, store):
    fake = FakeLLM(j({"error": {"message": "slow"}}, 429, {"Retry-After": "7"}), j(ok_body()))
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert store.waits()[0] > 0  # the shared cool-down is still set for other workers...
    assert len(clock.sleeps) == 1 and 7 <= clock.sleeps[0] < 8  # ...but this caller waited once


def test_429_without_retry_after_waits_the_longer_of_backoff_and_cooldown(make_client, ctx, clock):
    fake = FakeLLM(j({"error": {"message": "slow"}}, 429), j(ok_body()))
    assert make_client(fake, default_cooldown_s=5.0).complete_json(ctx, HAIKU, MSGS).status == "ok"
    # backoff 1-1.25 s, cool-down 5 s -> one wait of about 5 s, not 6+
    assert len(clock.sleeps) == 1 and 4.5 <= clock.sleeps[0] <= 5.0


def test_other_callers_still_honour_the_shared_cooldown(make_client, ctx, clock, store):
    store.set_cooldown(3.0)  # another worker hit a 429
    assert make_client(FakeLLM(j(ok_body()))).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert len(clock.sleeps) == 1 and 2.0 < clock.sleeps[0] <= 3.0


# --- half-open breaker ----------------------------------------------------------------------


def test_only_one_caller_can_claim_the_probe(store):
    _half_open(store._url)
    open_until = store.shared_state().open_until
    assert store.try_claim_probe(open_until, lease_s=60) is True
    assert store.try_claim_probe(open_until, lease_s=60) is False  # second caller waits
    assert store.shared_state().probe_held is True


def test_probe_success_closes_the_breaker(make_client, ctx, store):
    _half_open(store._url)
    fake = FakeLLM(j(ok_body()))
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert len(fake.requests) == 1
    assert _state(store._url) == (False, 0, False, 0)  # closed, probe cleared


def test_probe_failure_reopens_for_another_pause(make_client, ctx, store):
    _half_open(store._url)
    fake = FakeLLM(j({"error": "bad request"}, 400))  # DeepSeek: no reasoning param to drop
    with pytest.raises(LLMCallFailed):
        make_client(fake).chat(ctx, DEEPSEEK, MSGS)
    is_open, left, probe, _ = _state(store._url)
    assert is_open and 55 <= left <= 60 and not probe  # one failure was enough to re-open


def test_others_wait_while_the_probe_is_out(make_client, clock, store):
    _half_open(store._url, probe_held=True)
    short = CallContext(job_id=JOB, deadline=clock() + 5)
    fake = FakeLLM()
    with pytest.raises(LLMStopped, match="deadline"):
        make_client(fake).chat(short, HAIKU, MSGS)
    assert fake.requests == []  # no second probe
    assert clock.sleeps and all(s == 1.0 for s in clock.sleeps)  # polled, did not call


def test_crashed_probers_lease_frees_the_probe(make_client, ctx, store):
    _half_open(store._url)
    with psycopg.connect(store._url) as conn:
        conn.execute("UPDATE llm_state SET probe_until = now() - interval '1 second'")
    fake = FakeLLM(j(ok_body()))
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert len(fake.requests) == 1


def test_after_the_pause_exactly_one_probe_then_everyone_goes(make_client, ctx, clock, store):
    store.note_failure(threshold=1, pause_s=60)  # breaker open for 60 s
    fake = FakeLLM(j(ok_body()), j(ok_body()))
    first = make_client(fake)
    assert first.complete_json(ctx, HAIKU, MSGS).status == "ok"  # waits 60 s, probes, closes
    assert any(55 <= s <= 60.5 for s in clock.sleeps)
    clock.sleeps.clear()
    assert make_client(fake).complete_json(ctx, HAIKU, MSGS).status == "ok"
    assert clock.sleeps == [] and len(fake.requests) == 2  # breaker closed: no wait at all


# --- per-model reasoning ---------------------------------------------------------------------


def test_reasoning_none_sent_only_where_configured(make_client, ctx, database_url):
    fake = FakeLLM(j(ok_body()), j(ok_body(model=DEEPSEEK)))
    client = make_client(fake)
    client.chat(ctx, HAIKU, MSGS)
    client.chat(ctx, DEEPSEEK, MSGS)
    assert fake.requests[0]["reasoning"] == {"effort": "none"}
    assert "reasoning" not in fake.requests[1]  # DeepSeek: default
    assert _ledger_flags(database_url) == [("ok", "none", False), ("ok", None, False)]


def test_reasoning_override_default_sends_nothing(make_client, ctx):
    fake = FakeLLM(j(ok_body()))
    make_client(fake, reasoning_override="default").chat(ctx, HAIKU, MSGS)
    assert "reasoning" not in fake.requests[0]


def test_400_to_reasoning_param_retries_once_without_it(make_client, ctx, store, database_url):
    fake = FakeLLM(j({"error": {"message": "unsupported parameter"}}, 400), j(ok_body()))
    out = make_client(fake).complete_json(ctx, HAIKU, MSGS)
    assert out.status == "ok"
    assert "reasoning" in fake.requests[0] and "reasoning" not in fake.requests[1]
    assert _ledger_flags(database_url) == [("http_400", "none", False), ("ok", None, True)]
    assert store.job_metadata(JOB, 0)["reasoning_param_dropped"] is True
    assert _state(database_url)[3] == 0  # not counted as a gateway failure


def test_second_400_without_reasoning_fails(make_client, ctx):
    fake = FakeLLM(j({"error": "bad"}, 400), j({"error": "bad"}, 400))
    with pytest.raises(LLMCallFailed, match="http_400"):
        make_client(fake).chat(ctx, HAIKU, MSGS)
    assert len(fake.requests) == 2


@pytest.mark.parametrize(
    "snap, expect",
    [
        ({"mandatory": False, "supported_efforts": ["low", "none"]}, {"effort": "none"}),
        ({"mandatory": True, "supported_efforts": ["low", "none"]}, None),  # mandatory
        ({"mandatory": False, "supported_efforts": ["low", "high"]}, None),  # no "none"
        (None, None),  # snapshot lists no reasoning for the model
    ],
)
def test_none_needs_the_snapshot_to_allow_it(snap, expect):
    raw = {
        "baseline": HAIKU,
        "models": {
            HAIKU: {
                "vision": True,
                "price_in": 0.1,
                "price_out": 0.5,
                "reasoning": "none",
                "response_format": True,
                "max_tokens": 64,
            }
        },
    }
    snapshot = {"models": {HAIKU: {"reasoning": snap} if snap else {}}}
    assert ModelCatalog.from_dict(raw, snapshot).get(HAIKU).reasoning_param() == expect


def test_unknown_reasoning_setting_refused():
    raw = {
        "baseline": HAIKU,
        "models": {
            HAIKU: {
                "vision": True,
                "price_in": 0.1,
                "price_out": 0.5,
                "reasoning": "omit",
                "response_format": True,
                "max_tokens": 64,
            }
        },
    }
    with pytest.raises(ValueError, match="reasoning"):
        ModelCatalog.from_dict(raw)


# --- P2-36: per-document cost fuse, predicted before every call --------------------------------


def test_fuse_estimate_is_high_side_and_counts_images(catalog):
    est = catalog.estimate
    text = [{"role": "user", "content": "x" * 3000}]
    assert est.tokens(text) >= 3000 / 3 * 1.15  # never below the 1-per-3-chars rule
    img = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": JPEG}}]}]
    assert est.tokens(img) >= est.image_tokens * (1 + est.margin)


def test_fuse_call_that_fits_goes_out_and_writes_the_estimate(
    make_client, ctx, catalog, database_url
):
    fake = FakeLLM(j(ok_body(cost=0.0002)))
    client = make_client(fake)
    proj = client.projection(ctx, HAIKU, MSGS)
    assert proj.fits and proj.spent_usd == 0.0 and proj.cap_usd == 0.05
    assert client.complete_json(ctx, HAIKU, MSGS).status == "ok"
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("SELECT tokens_estimated, tokens_in FROM llm_calls").fetchall()
    assert rows == [(catalog.estimate.tokens(MSGS), 1000)]  # estimate next to real tokens


def test_fuse_prices_the_whole_call_at_the_cliff_rate(make_client, ctx, catalog):
    spec = catalog.get(HAIKU)
    client = make_client(FakeLLM())
    big = [{"role": "user", "content": "7" * 160_000}]
    proj = client.projection(ctx, HAIKU, big, max_tokens=1000)
    assert proj.tokens_estimated >= spec.cliff_tokens
    plain = (proj.tokens_estimated * spec.price_in + 1000 * spec.price_out) / 1e6
    assert proj.cost_usd == pytest.approx(plain * spec.cliff_multiplier)
    small = client.projection(ctx, HAIKU, MSGS, max_tokens=1000)
    assert small.cost_usd == pytest.approx(
        (small.tokens_estimated * spec.price_in + 1000 * spec.price_out) / 1e6
    )


def test_fuse_skips_a_call_that_would_pass_the_cap(make_client, ctx, database_url):
    fake = FakeLLM(j(ok_body()))
    client = make_client(fake, max_usd_per_doc=0.000001)
    out = client.complete_json(ctx, HAIKU, MSGS)
    assert out.status == "stopped" and out.reason == "doc_llm_cap"
    assert fake.requests == [] and ledger(database_url) == []


def test_fuse_counts_what_the_doc_already_spent(make_client, ctx, store):
    store.record(
        LedgerRow(
            job_id=JOB,
            purpose="extract",
            attempt=1,
            model_requested=HAIKU,
            status="ok",
            cost_computed=0.0499,
        )
    )
    client = make_client(FakeLLM(j(ok_body())))
    proj = client.projection(ctx, HAIKU, MSGS)
    assert proj.spent_usd == pytest.approx(0.0499) and not proj.fits
