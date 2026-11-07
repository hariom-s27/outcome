"""Result objects in the contract shape (contract/output.schema.json)."""

from __future__ import annotations

from typing import Any


def null_field() -> dict[str, Any]:
    return {"value": None, "citation": "", "confidence": 0.0}


def stub_result(
    field_list: dict[str, Any], latency_ms: int, terminal_reason: str | None = None
) -> dict[str, Any]:
    """P1-09: one entry, every field null, no model calls.

    terminal_reason (e.g. "deadline_exceeded", "too_many_attempts") says why a PARTIAL job
    got the skeleton; `error` on the job is reserved for FAILED.
    """
    entry = {key: null_field() for key in field_list["fields"]}
    metadata: dict[str, Any] = {
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "latency_ms": max(0, int(latency_ms)),
    }
    if terminal_reason:
        metadata["terminal_reason"] = terminal_reason
    return {"entries": [entry], "metadata": metadata}
