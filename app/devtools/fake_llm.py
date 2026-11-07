"""Tiny fake LLM gateway for load tests (P2-13; used from P8, not by unit tests).

Speaks POST /chat/completions and GET /models in the OpenAI/OpenRouter shape, with scripted
replies, added latency and random 429s. Invented content only.

    uv run python -m app.devtools.fake_llm --port 9999 --latency 0.5 --rate-429 0.2
    # then point the service at it: LLM_BASE_URL=http://host.docker.internal:9999/v1
"""

from __future__ import annotations

import argparse
import asyncio
import random
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.llm.models import ALLOWED_MODEL_IDS

DEFAULT_CONTENT = '{"widget_name": "sprocket", "widget_count": 3}'


def create_app(
    replies: list[str] | None = None,
    latency_s: float = 0.0,
    rate_429: float = 0.0,
    seed: int = 0,
) -> FastAPI:
    """replies: assistant contents returned in turn (cycled); default one widget object."""
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
        if latency_s:
            await asyncio.sleep(latency_s)
        if rate_429 and rng.random() < rate_429:
            return JSONResponse(
                {"error": {"code": 429, "message": "rate limited (fake)"}},
                status_code=429,
                headers={"Retry-After": "1"},
            )
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


def main() -> None:  # pragma: no cover - manual dev tool
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9999)
    p.add_argument("--latency", type=float, default=0.0, help="seconds added to each reply")
    p.add_argument("--rate-429", type=float, default=0.0, help="share of calls answered 429")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    app = create_app(latency_s=a.latency, rate_429=a.rate_429, seed=a.seed)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    main()
