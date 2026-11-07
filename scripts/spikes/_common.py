"""Shared helpers for the P3 free spikes (P3-04, P3-06).

Each spike writes its full output to cache/spikes/<name>.txt (git-ignored) and prints at most
15 summary lines. DEV answers are read inside the script only; printed output carries doc ids,
field names, column letters, counts and scores, never a document or answer value (D04, R31).
Held-out documents are refused in code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_outputs import DOCS, SCHEMAS, manifest  # noqa: E402

TRUTH = ROOT / "sample" / "sample-data-output-validated"
OUT_DIR = ROOT / "cache" / "spikes"
RUNS = ROOT / "cache" / "eval_runs"
HISTORY = ROOT / "eval" / "history.jsonl"
HELD_OUT = frozenset({"lease_003", "budget_001"})  # D03: sealed until P8
MAX_SUMMARY = 15


def dev_row(doc_id: str) -> dict[str, str]:
    if doc_id in HELD_OUT:
        raise SystemExit(f"refused: {doc_id} is held out (D03)")
    rows = manifest()
    if doc_id not in rows:
        raise SystemExit(f"unknown doc id {doc_id}")
    return rows[doc_id]


def dev_docs() -> list[str]:
    return [d for d in manifest() if d not in HELD_OUT]


def doc_path(doc_id: str) -> Path:
    return DOCS / dev_row(doc_id)["file"]


def truth(doc_id: str) -> dict[str, Any]:
    dev_row(doc_id)  # refuses held-out ids
    return json.loads((TRUTH / f"{doc_id}.json").read_text(encoding="utf-8"))


def schema(doc_id: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{dev_row(doc_id)['schema_name']}.json").read_text("utf-8"))


def truth_entries(t: dict[str, Any]) -> list[dict[str, Any]]:
    return t.get("entries", t if isinstance(t, list) else [t])


def last_run_id() -> str:
    lines = [ln for ln in HISTORY.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1])["run_id"]


class Report:
    """Full lines go to cache/spikes/<name>.txt; summary lines (max 15) go to stdout."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.full: list[str] = []
        self.summary: list[str] = []

    def line(self, text: str = "") -> None:
        self.full.append(text)

    def sum(self, text: str) -> None:
        self.summary.append(text)
        self.full.append("SUMMARY " + text)

    def close(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{self.name}.txt").write_text(
            "\n".join(self.full) + "\n", encoding="utf-8", newline="\n"
        )
        for s in self.summary[:MAX_SUMMARY]:
            print(s)
        if len(self.summary) > MAX_SUMMARY:
            print(f"... {len(self.summary) - MAX_SUMMARY} more summary lines in the full output")
