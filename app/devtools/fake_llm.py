"""Tiny fake LLM gateway for load tests (P2-13; used by the P8a load stack, compose.loadtest.yaml).

Speaks POST /chat/completions and GET /models in the OpenAI/OpenRouter shape, with scripted
or field-aware replies, added latency and random 429s. Invented content only. It never logs
request headers or bodies (uvicorn runs with access logs off).

    uv run python -m app.devtools.fake_llm --port 9999 --latency 0.5 --rate-429 0.2
    # P8a load profile (A-4): seeded latency 1-6 s, ~8% 429 with Retry-After: 2,
    # a valid JSON answer for whatever field list the baseline prompt carries
    uv run python -m app.devtools.fake_llm --latency-min 1 --latency-max 6 --rate-429 0.08 \
        --retry-after 2 --field-aware
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.llm.models import ALLOWED_MODEL_IDS

DEFAULT_CONTENT = '{"widget_name": "sprocket", "widget_count": 3}'

# baseline prompt shape (app/pipeline/baseline.py): "- key (Name)[ [row key]]: description"
_FIELD_LINE = re.compile(r"^- (\S+) \(.*?\)( \[row key\])?:", re.M)
_NULL_SHARE = 0.15


def _user_text(messages: list[dict[str, Any]]) -> str:
    out = []
    for m in messages:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out.extend(p.get("text", "") for p in c if isinstance(p, dict))
    return "\n".join(out)


def requested_fields(messages: list[dict[str, Any]]) -> tuple[list[str], str | None]:
    """(field keys in prompt order, row-key field or None) from a baseline-shaped prompt."""
    text = _user_text(messages)
    head = text.split("\n\nDOCUMENT", 1)[0]
    keys: list[str] = []
    primary = None
    for m in _FIELD_LINE.finditer(head):
        keys.append(m.group(1))
        if m.group(2):
            primary = m.group(1)
    return keys, primary


def fake_value(key: str, rng: random.Random) -> Any:
    """A plausible-typed invented value, chosen from the key's wording only."""
    k = key.lower()
    if any(w in k for w in ("date", "commencement", "expiration")):
        return f"20{rng.randint(30, 39)}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}"
    if k.startswith(("is_", "has_")) or k.endswith(("_right", "_flag")):
        return rng.random() < 0.5
    if any(w in k for w in ("pct", "percent", "share", "rate")):
        return round(rng.uniform(1, 99), 2)
    if any(w in k for w in ("count", "months", "units", "year", "number_of")):
        return rng.randint(1, 120)
    if any(w in k for w in ("amount", "rent", "price", "cost", "total", "income", "expense")):
        return round(rng.uniform(100, 99_999), 2)
    if k.endswith(("_names", "_list", "_types", "amenities")):
        return [f"invented item {i}" for i in range(1, rng.randint(2, 4))]
    return f"invented {k.replace('_', ' ')} {rng.randint(1, 999)}"


def field_reply(messages: list[dict[str, Any]], rng: random.Random) -> str:
    """JSON answer in the baseline reply shape for the field list in the prompt.
    Table field lists get 2-6 rows with distinct row keys; others get one entry."""
    keys, primary = requested_fields(messages)
    rows = rng.randint(2, 6) if primary else 1
    entries = []
    for r in range(1, rows + 1):
        entry: dict[str, Any] = {}
        for key in keys:
            if key == primary:
                value: Any = f"row-{r}"
            elif rng.random() < _NULL_SHARE:
                value = None
            else:
                value = fake_value(key, rng)
            entry[key] = {
                "value": value,
                "citation": "" if value is None else f"[Page {r}] invented snippet for {key}",
                "confidence": round(rng.uniform(0.5, 0.99), 2),
            }
        entries.append(entry)
    return json.dumps({"entries": entries})


def create_app(
    replies: list[str] | None = None,
    latency_s: float = 0.0,
    rate_429: float = 0.0,
    seed: int = 0,
    *,
    latency_range: tuple[float, float] | None = None,
    retry_after: str = "1",
    field_aware: bool = False,
) -> FastAPI:
    """replies: assistant contents returned in turn (cycled); default one widget object.
    latency_range: uniform (lo, hi) seconds per reply, seeded (overrides latency_s).
    field_aware: answer the baseline prompt's field list instead of the scripted replies."""
    app = FastAPI(title="fake-llm")
    rng = random.Random(seed)
    script = list(replies or [DEFAULT_CONTENT])
    state = {"n": 0}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {
            "data": [
                {"id": mid, "pricing": {"prompt": "0", "completion": "0"}}
                for mid in sorted(ALLOWED_MODEL_IDS)
            ]
        }

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        delay = rng.uniform(*latency_range) if latency_range else latency_s
        if delay:
            await asyncio.sleep(delay)
        if rate_429 and rng.random() < rate_429:
            return JSONResponse(
                {"error": {"code": 429, "message": "rate limited (fake)"}},
                status_code=429,
                headers={"Retry-After": retry_after},
            )
        if field_aware:
            content = field_reply(body.get("messages") or [], rng)
        else:
            content = script[state["n"] % len(script)]
        state["n"] += 1
        return JSONResponse(
            {
                "id": f"gen-fake-{state['n']}",
                "model": body.get("model"),
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                    "cost": 0.0,
                },
            }
        )

    return app


def main() -> None:  # pragma: no cover - manual dev tool / load-stack entry point
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9999)
    p.add_argument("--latency", type=float, default=0.0, help="seconds added to each reply")
    p.add_argument("--latency-min", type=float, default=None, help="uniform latency, low end")
    p.add_argument("--latency-max", type=float, default=None, help="uniform latency, high end")
    p.add_argument("--rate-429", type=float, default=0.0, help="share of calls answered 429")
    p.add_argument("--retry-after", default="1", help="Retry-After header on a 429")
    p.add_argument("--field-aware", action="store_true", help="answer the prompt's field list")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    lat = None
    if a.latency_min is not None or a.latency_max is not None:
        lo = a.latency_min if a.latency_min is not None else 0.0
        lat = (lo, a.latency_max if a.latency_max is not None else lo)
    app = create_app(
        latency_s=a.latency,
        rate_429=a.rate_429,
        seed=a.seed,
        latency_range=lat,
        retry_after=a.retry_after,
        field_aware=a.field_aware,
    )
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", access_log=False)


if __name__ == "__main__":  # pragma: no cover
    main()
