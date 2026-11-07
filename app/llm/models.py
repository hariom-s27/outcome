"""The model catalogue (config/models.yaml): the 9 allowed ids, prices, params (P2-02)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODELS_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
SNAPSHOT_NAME = "models_snapshot.json"  # next to models.yaml (P2-14)
REASONING_SETTINGS = ("default", "none")  # P2-31

# ASSIGNMENT §3, byte-for-byte. The YAML may not add anything outside this set.
ALLOWED_MODEL_IDS: frozenset[str] = frozenset(
    {
        "google/gemini-3.8-flash",
        "google/gemini-3.1-pro-preview",
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
        "openai/gpt-6-luna",
        "openai/gpt-6.1-sol",
        "z-ai/glm-5.3-flash",
        "qwen/qwen3-vl-235b-a22b-instruct",
        "deepseek/deepseek-v3.2",
    }
)


class UnknownModelError(ValueError):
    """A model id that is not in config/models.yaml (or not in the brief's list)."""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    vision: bool
    price_in: float  # USD per 1M prompt tokens
    price_out: float  # USD per 1M completion tokens
    reasoning: str
    response_format: bool
    max_tokens: int
    cliff_tokens: int | None = None
    cliff_multiplier: float = 1.0
    reasoning_none_ok: bool = False  # snapshot lists reasoning, not mandatory, "none" allowed

    def reasoning_param(self, setting: str | None = None) -> dict[str, str] | None:
        """P2-31: {"effort": "none"} only when asked for and the snapshot allows it."""
        if (setting or self.reasoning) == "none" and self.reasoning_none_ok:
            return {"effort": "none"}
        return None

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        usd = (tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000
        if self.cliff_tokens is not None and tokens_in >= self.cliff_tokens:
            usd *= self.cliff_multiplier
        return usd


@dataclass(frozen=True)
class Estimate:
    """P2-36: high-side input-token estimate made before every call (config `estimate:`)."""

    chars_per_token: float = 1.5
    image_tokens: int = 2600
    margin: float = 0.15
    message_overhead: int = 8  # role and framing tokens per message

    def tokens(self, messages: list[dict[str, Any]]) -> int:
        chars = images = 0
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                chars += len(content)
                continue
            for part in content or []:
                if part.get("type") == "image_url":
                    images += 1
                else:
                    chars += len(part.get("text") or "")
        raw = (
            chars / self.chars_per_token
            + images * self.image_tokens
            + len(messages) * self.message_overhead
        )
        return math.ceil(raw * (1 + self.margin))


class ModelCatalog:
    estimate: Estimate = Estimate()

    def __init__(self, specs: dict[str, ModelSpec], baseline: str, fallback_order: list[str]):
        for mid in [*specs, baseline, *fallback_order]:
            if mid not in ALLOWED_MODEL_IDS:
                raise UnknownModelError(f"model id not allowed by the brief: {mid!r}")
        if baseline not in specs:
            raise UnknownModelError(f"baseline {baseline!r} has no entry under models:")
        self._specs = specs
        self.baseline = baseline
        self.fallback_order = list(fallback_order)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_MODELS_PATH) -> ModelCatalog:
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        snap_path = path.with_name(SNAPSHOT_NAME)
        snapshot = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else None
        return cls.from_dict(raw, snapshot)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], snapshot: dict[str, Any] | None = None) -> ModelCatalog:
        snap_models = (snapshot or {}).get("models") or {}
        specs: dict[str, ModelSpec] = {}
        for mid, m in raw["models"].items():
            if m["reasoning"] not in REASONING_SETTINGS:
                raise ValueError(f"{mid}: reasoning must be one of {REASONING_SETTINGS}")
            cliff = m.get("price_cliff") or {}
            specs[mid] = ModelSpec(
                id=mid,
                vision=bool(m["vision"]),
                price_in=float(m["price_in"]),
                price_out=float(m["price_out"]),
                reasoning=m["reasoning"],
                response_format=bool(m["response_format"]),
                max_tokens=int(m["max_tokens"]),
                cliff_tokens=int(cliff["prompt_tokens"]) if cliff else None,
                cliff_multiplier=float(cliff.get("multiplier", 1.0)) if cliff else 1.0,
                reasoning_none_ok=_none_allowed(snap_models.get(mid)),
            )
        catalog = cls(specs, raw["baseline"], raw.get("fallback_order") or [])
        est = raw.get("estimate") or {}
        catalog.estimate = Estimate(
            chars_per_token=float(est.get("chars_per_token", Estimate.chars_per_token)),
            image_tokens=int(est.get("image_tokens", Estimate.image_tokens)),
            margin=float(est.get("margin", Estimate.margin)),
        )
        return catalog

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._specs[model_id]
        except KeyError:
            raise UnknownModelError(f"model id not in config/models.yaml: {model_id!r}") from None

    def ids(self) -> list[str]:
        return list(self._specs)

    def cheapest_text_model(self) -> ModelSpec:
        """For the text-only JSON repair call (P2-08); ties keep YAML order."""
        return min(self._specs.values(), key=lambda s: s.price_in + s.price_out)


def _none_allowed(snap: dict[str, Any] | None) -> bool:
    """True when the snapshot lists a reasoning block that is not mandatory and allows none."""
    r = (snap or {}).get("reasoning")
    if not isinstance(r, dict) or r.get("mandatory") is not False:
        return False
    efforts = r.get("supported_efforts")
    return efforts is None or "none" in efforts
