"""The model catalogue (config/models.yaml): the 9 allowed ids, prices, params (P2-02)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODELS_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"

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

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        usd = (tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000
        if self.cliff_tokens is not None and tokens_in >= self.cliff_tokens:
            usd *= self.cliff_multiplier
        return usd


class ModelCatalog:
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
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModelCatalog:
        specs: dict[str, ModelSpec] = {}
        for mid, m in raw["models"].items():
            if m["reasoning"] != "omit":
                # P2-04: generic profile only; P4 spike 10 decides per-model controls.
                raise ValueError(f"{mid}: reasoning {m['reasoning']!r} not supported in P2")
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
            )
        return cls(specs, raw["baseline"], raw.get("fallback_order") or [])

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
