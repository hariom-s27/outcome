"""Result objects in the contract shape (contract/output.schema.json)."""

from __future__ import annotations

from typing import Any


def null_field() -> dict[str, Any]:
    return {"value": None, "citation": "", "confidence": 0.0}


def stub_result(field_list: dict[str, Any], latency_ms: int) -> dict[str, Any]:
    """P1-09: one entry, every field null, no model calls."""
    entry = {key: null_field() for key in field_list["fields"]}
    return {
        "entries": [entry],
        "metadata": {
            "model_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "latency_ms": max(0, int(latency_ms)),
        },
    }
