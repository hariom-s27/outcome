"""The one LLM wrapper (P2-01 … P2-12, P2-28, P2-29). Every model call in the service goes here.

- plain httpx, no SDK auto-retries (R3); POST {LLM_BASE_URL}/chat/completions, Bearer key
- always max_tokens; no reasoning or temperature parameter (R4/R7 generic profile, P2-04)
- never a file part; images only as JPEG data URIs, only to vision models (R1, R13)
- up to 4 attempts on 429 / 5xx / timeout / connection error / error-inside-200, backoff
  1-2-4-8 s + jitter, Retry-After honoured, never waiting past the job's time left (P2-06)
- global in-flight cap + shared 429 cool-down + circuit breaker, all in Postgres (P2-07, P2-29)
- one ledger row per attempt (P2-09); per-doc call/$ caps (P2-28); dev budget (P2-10)
- JSON ladder: json_object if the snapshot lists it, local parse, one text-only repair (P2-05/08)
Logs carry metadata only (R23): job id, model, status, timings. Never prompt or output text.
"""

from __future__ import annotations

import email.utils
import logging
import os
import random
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.llm.diskcache import DiskCache, request_key
from app.llm.jsonparse import JSONParseError, parse_json_object
from app.llm.models import ModelCatalog, ModelSpec
from app.llm.settings import LLMSettings
from app.llm.store import LedgerRow, LLMStore

log = logging.getLogger(__name__)

JPEG_DATA_URI = "data:image/jpeg;base64,"
REPAIR_INPUT_MAX_CHARS = 60_000


class ForbiddenContentError(ValueError):
    """A request part the wrapper never sends (file parts, non-JPEG or remote images)."""


class LLMStopped(Exception):
    """No further LLM calls for this document; `reason` goes to result metadata."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LLMCallFailed(Exception):
    """One logical call failed after its retries (or on a non-retryable answer)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CallContext:
    job_id: str | None  # None only in dev scripts: per-doc caps then do not apply
    deadline: float  # absolute, on the client's clock (time.time by default)
    purpose: str = "extract"


@dataclass
class ChatResult:
    text: str | None
    finish_reason: str | None
    model_requested: str
    model_returned: str | None
    model_mismatch: bool
    usage: dict[str, Any]
    cache_hit: bool = False


@dataclass
class JSONOutcome:
    status: str  # "ok" | "unusable" | "stopped" | "failed"
    data: dict[str, Any] | None = None
    reason: str | None = None  # llm_unusable, llm_truncated, doc_llm_cap, dev_budget_reached…
    detail: str | None = None
    repaired: bool = False
    model_mismatch: bool = False


@dataclass
class _Attempt:
    ok: bool
    status: str
    retryable: bool = False
    retry_after: float | None = None
    data: dict[str, Any] | None = None


def check_messages(messages: list[dict[str, Any]], spec: ModelSpec) -> None:
    """R1/R13: only text parts and JPEG data-URI images; images only for vision models."""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            raise ForbiddenContentError(f"message content must be str or list, got {content!r}")
        for part in content:
            kind = part.get("type") if isinstance(part, dict) else None
            if kind == "text":
                continue
            if kind == "image_url":
                img = part.get("image_url")
                url = img.get("url") if isinstance(img, dict) else img
                if not isinstance(url, str) or not url.startswith(JPEG_DATA_URI):
                    raise ForbiddenContentError("images must be JPEG data URIs (R13)")
                if not spec.vision:
                    raise ForbiddenContentError(f"{spec.id} has no vision input")
                continue
            raise ForbiddenContentError(f"content part type {kind!r} is never sent (R1)")


def _parse_retry_after(value: str | None, now: float) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, dt.timestamp() - now)


def _usage_numbers(data: dict[str, Any] | None) -> dict[str, Any]:
    usage = (data or {}).get("usage") or {}
    out_details = usage.get("completion_tokens_details") or {}
    in_details = usage.get("prompt_tokens_details") or {}
    cost = usage.get("cost")
    return {
        "tokens_in": int(usage.get("prompt_tokens") or 0),
        "tokens_out": int(usage.get("completion_tokens") or 0),
        "tokens_reasoning": out_details.get("reasoning_tokens"),
        "tokens_cached": in_details.get("cached_tokens"),
        "cost_reported": float(cost) if isinstance(cost, int | float) else None,
    }


def _retryable_error_code(code: Any) -> bool:
    if code is None:
        return True
    try:
        n = int(code)
    except (TypeError, ValueError):
        return True  # unknown string codes: treat as transient, retries are capped anyway
    return n == 408 or n == 429 or n >= 500


class LLMClient:
    def __init__(
        self,
        settings: LLMSettings,
        catalog: ModelCatalog,
        store: LLMStore,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ):
        self.settings = settings
        self.catalog = catalog
        self.store = store
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._http = httpx.Client(transport=transport, timeout=settings.request_timeout_s)
        self._cache = DiskCache(settings.cache_dir) if settings.cache_dir else None
        self._holder_prefix = f"{socket.gethostname()}:{os.getpid()}"
        self.store.ensure_slots(settings.max_concurrency)

    @classmethod
    def from_env(cls, database_url: str) -> LLMClient:
        return cls(LLMSettings.from_env(), ModelCatalog.load(), LLMStore(database_url))

    def close(self) -> None:
        self._http.close()
        self.store.close()

    # --- public API ---------------------------------------------------------------------

    def complete_json(
        self,
        ctx: CallContext,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> JSONOutcome:
        """The JSON ladder. Never raises for LLM trouble; the caller maps the outcome."""
        spec = self.catalog.get(model)
        check_messages(messages, spec)
        mismatch = False
        try:
            res = self.chat(ctx, model, messages, max_tokens=max_tokens)
            mismatch |= res.model_mismatch
            if res.finish_reason == "length":
                bigger = 2 * (max_tokens or spec.max_tokens)
                res = self.chat(ctx, model, messages, max_tokens=bigger)
                mismatch |= res.model_mismatch
                if res.finish_reason == "length":
                    return JSONOutcome("unusable", reason="llm_truncated", model_mismatch=mismatch)
            try:
                return JSONOutcome("ok", data=parse_json_object(res.text), model_mismatch=mismatch)
            except JSONParseError as exc:
                parse_error = str(exc)
            repair = self.catalog.cheapest_text_model()
            rep = self.chat(
                replace(ctx, purpose="repair"),
                repair.id,
                _repair_messages(res.text or "", parse_error),
                max_tokens=max(repair.max_tokens, max_tokens or spec.max_tokens),
            )
            mismatch |= rep.model_mismatch
            if rep.finish_reason != "length":
                try:
                    data = parse_json_object(rep.text)
                    return JSONOutcome("ok", data=data, repaired=True, model_mismatch=mismatch)
                except JSONParseError:
                    pass
            return JSONOutcome("unusable", reason="llm_unusable", model_mismatch=mismatch)
        except LLMStopped as exc:
            return JSONOutcome("stopped", reason=exc.reason, model_mismatch=mismatch)
        except LLMCallFailed as exc:
            return JSONOutcome(
                "failed", reason="llm_failed", detail=exc.reason, model_mismatch=mismatch
            )

    def chat(
        self,
        ctx: CallContext,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        json_mode: bool | None = None,
    ) -> ChatResult:
        """One logical call with retries. Raises LLMStopped / LLMCallFailed."""
        spec = self.catalog.get(model)
        check_messages(messages, spec)
        body: dict[str, Any] = {
            "model": spec.id,
            "messages": messages,
            "max_tokens": int(max_tokens or spec.max_tokens),
        }
        if spec.response_format if json_mode is None else json_mode:
            body["response_format"] = {"type": "json_object"}

        key = request_key(body) if self._cache else None
        if self._cache and key:
            hit = self._cache.get(key)
            if hit is not None:
                return self._from_cache(ctx, spec, hit)

        if not self.settings.base_url or not self.settings.api_key:
            raise LLMCallFailed("llm_not_configured")

        last_status = "no_attempt"
        for attempt in range(1, self.settings.max_attempts + 1):
            self._check_stops(ctx)
            self._wait_shared(ctx)
            holder = f"{self._holder_prefix}:{uuid.uuid4().hex[:8]}"
            slot = self._acquire_slot(ctx, holder)
            try:
                result = self._attempt(ctx, spec, body, attempt)
            finally:
                self.store.release_slot(slot, holder)
            last_status = result.status
            if result.ok:
                self.store.note_success()
                if self._cache and key:
                    self._cache.put(key, result.data or {})
                return self._to_result(spec, result.data or {})
            if self.store.note_failure(
                self.settings.breaker_threshold, self.settings.breaker_pause_s
            ):
                log.warning("llm circuit breaker opened (%ss)", self.settings.breaker_pause_s)
            if not result.retryable:
                raise LLMCallFailed(last_status)
            if attempt == self.settings.max_attempts:
                break
            base = self.settings.backoff_s[min(attempt - 1, len(self.settings.backoff_s) - 1)]
            delay = max(base + self._rng.uniform(0, 0.25 * base), result.retry_after or 0.0)
            if delay >= self._time_left(ctx):
                raise LLMStopped("deadline")
            self._sleep(delay)
        raise LLMCallFailed(last_status)

    # --- internals ----------------------------------------------------------------------

    def _time_left(self, ctx: CallContext) -> float:
        return ctx.deadline - self._clock()

    def _check_stops(self, ctx: CallContext) -> None:
        s = self.settings
        if s.dev_budget_usd is not None and self.store.total_spend() >= s.dev_budget_usd:
            raise LLMStopped("dev_budget_reached")
        if ctx.job_id is not None:
            used = self.store.doc_usage(ctx.job_id)
            if used.calls >= s.max_calls_per_doc or used.cost_computed >= s.max_usd_per_doc:
                raise LLMStopped("doc_llm_cap")
        if self._time_left(ctx) <= 0:
            raise LLMStopped("deadline")

    def _wait_shared(self, ctx: CallContext) -> None:
        cooldown, breaker = self.store.waits()
        if breaker > 0:
            if self.settings.breaker_abort:
                raise LLMStopped("circuit_open")
            if breaker >= self._time_left(ctx):
                raise LLMStopped("deadline")
            self._sleep(breaker)  # then one probe call; its result closes or re-opens
        elif cooldown > 0:
            if cooldown >= self._time_left(ctx):
                raise LLMStopped("deadline")
            self._sleep(cooldown)

    def _acquire_slot(self, ctx: CallContext, holder: str) -> int:
        s = self.settings
        while True:
            slot = self.store.try_acquire_slot(holder, s.max_concurrency, s.slot_lease_s)
            if slot is not None:
                return slot
            if self._time_left(ctx) <= s.slot_poll_s:
                raise LLMStopped("deadline")
            self._sleep(s.slot_poll_s)

    def _attempt(
        self, ctx: CallContext, spec: ModelSpec, body: dict[str, Any], attempt: int
    ) -> _Attempt:
        timeout = max(1.0, min(self.settings.request_timeout_s, self._time_left(ctx)))
        t0 = time.monotonic()
        http_status: int | None = None
        data: dict[str, Any] | None = None
        try:
            resp = self._http.post(
                f"{self.settings.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                timeout=timeout,
            )
            http_status = resp.status_code
            out = self._classify(resp)
            data = out.data
        except httpx.TimeoutException:
            out = _Attempt(False, "timeout", retryable=True)
        except httpx.TransportError:
            out = _Attempt(False, "connect_error", retryable=True)
        latency_ms = int((time.monotonic() - t0) * 1000)

        nums = _usage_numbers(data)
        returned = (data or {}).get("model")
        mismatch = isinstance(returned, str) and returned != spec.id
        choice = ((data or {}).get("choices") or [{}])[0]
        self.store.record(
            LedgerRow(
                job_id=ctx.job_id,
                purpose=ctx.purpose,
                attempt=attempt,
                model_requested=spec.id,
                model_returned=returned if isinstance(returned, str) else None,
                model_mismatch=mismatch,
                status=out.status,
                http_status=http_status,
                finish_reason=choice.get("finish_reason") if isinstance(choice, dict) else None,
                cost_computed=spec.cost(nums["tokens_in"], nums["tokens_out"]),
                latency_ms=latency_ms,
                **nums,
            )
        )
        log.info(
            "llm call job=%s model=%s attempt=%d status=%s http=%s latency_ms=%d",
            ctx.job_id,
            spec.id,
            attempt,
            out.status,
            http_status,
            latency_ms,
        )
        if mismatch:
            log.warning("llm model mismatch job=%s requested=%s", ctx.job_id, spec.id)
        return out

    def _classify(self, resp: httpx.Response) -> _Attempt:
        code = resp.status_code
        retry_after = _parse_retry_after(resp.headers.get("retry-after"), self._clock())
        if code == 429:
            self.store.set_cooldown(retry_after or self.settings.default_cooldown_s)
            return _Attempt(False, "http_429", retryable=True, retry_after=retry_after)
        if code >= 500 or code == 408:
            return _Attempt(False, f"http_{code}", retryable=True, retry_after=retry_after)
        if code != 200:
            return _Attempt(False, f"http_{code}", retryable=False)
        try:
            data = resp.json()
        except ValueError:
            return _Attempt(False, "bad_body", retryable=True)
        if not isinstance(data, dict):
            return _Attempt(False, "bad_body", retryable=True)
        if data.get("error"):
            err = data["error"]
            err_code = err.get("code") if isinstance(err, dict) else None
            return _Attempt(
                False, "error_in_200", retryable=_retryable_error_code(err_code), data=data
            )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return _Attempt(False, "bad_body", retryable=True, data=data)
        if choices[0].get("finish_reason") == "error":
            return _Attempt(False, "error_in_200", retryable=True, data=data)
        return _Attempt(True, "ok", data=data)

    def _to_result(self, spec: ModelSpec, data: dict[str, Any], cache_hit=False) -> ChatResult:
        choice = data["choices"][0]
        message = choice.get("message") or {}
        returned = data.get("model")
        return ChatResult(
            text=message.get("content"),
            finish_reason=choice.get("finish_reason"),
            model_requested=spec.id,
            model_returned=returned,
            model_mismatch=isinstance(returned, str) and returned != spec.id,
            usage=data.get("usage") or {},
            cache_hit=cache_hit,
        )

    def _from_cache(self, ctx: CallContext, spec: ModelSpec, data: dict[str, Any]) -> ChatResult:
        nums = _usage_numbers(data)
        nums["cost_reported"] = None
        self.store.record(
            LedgerRow(
                job_id=ctx.job_id,
                purpose=ctx.purpose,
                attempt=0,
                model_requested=spec.id,
                model_returned=data.get("model"),
                status="cache_hit",
                cache_hit=True,
                **nums,
            )
        )
        return self._to_result(spec, data, cache_hit=True)


def _repair_messages(broken: str, parse_error: str) -> list[dict[str, Any]]:
    """Text-only repair request (P2-08): the broken output + the parser's error, no images."""
    return [
        {
            "role": "system",
            "content": (
                "You repair malformed JSON. Return only the corrected JSON object, with the "
                "same keys and values. Do not add, remove or change any value."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Parser error: {parse_error}\n\nMalformed output:\n"
                f"{broken[:REPAIR_INPUT_MAX_CHARS]}"
            ),
        },
    ]
