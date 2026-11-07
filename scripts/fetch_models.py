"""One free GET {LLM_BASE_URL}/models -> config/models_snapshot.json (P2-14). No chat call.

Keeps only the 9 allowed ids, then updates price_in / price_out / vision / response_format in
config/models.yaml (line edits, comments kept). Exit 2 if any allowed id is missing.
Never prints the key or any environment value.

    uv run python scripts/fetch_models.py            # fetch, save, update yaml
    uv run python scripts/fetch_models.py --dry-run  # fetch and report only
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.llm.models import ALLOWED_MODEL_IDS  # noqa: E402

SNAPSHOT = ROOT / "config" / "models_snapshot.json"
MODELS_YAML = ROOT / "config" / "models.yaml"
KEEP_KEYS = (
    "id",
    "canonical_slug",
    "name",
    "created",
    "context_length",
    "pricing",
    "architecture",
    "top_provider",
    "supported_parameters",
    "default_parameters",
    "reasoning",
)


def per_million(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return None if v < 0 else round(v * 1_000_000, 6)


def summarise(m: dict[str, Any]) -> dict[str, Any]:
    pricing = m.get("pricing") or {}
    arch = m.get("architecture") or {}
    params = m.get("supported_parameters") or []
    return {
        "price_in": per_million(pricing.get("prompt")),
        "price_out": per_million(pricing.get("completion")),
        "vision": "image" in (arch.get("input_modalities") or []),
        "response_format": "response_format" in params,
        "structured_outputs": "structured_outputs" in params,
        "reasoning_param": "reasoning" in params,
        "context_length": m.get("context_length"),
    }


def update_yaml(text: str, facts: dict[str, dict[str, Any]]) -> str:
    out: list[str] = []
    current: str | None = None
    in_models = False
    for line in text.splitlines():
        if line.startswith("models:"):
            in_models = True
        elif in_models and (m := re.match(r"^  (\S+):\s*$", line)):
            current = m.group(1)
        elif in_models and current in facts and (m := re.match(r"^(    )(\w+):(.*)$", line)):
            key = m.group(2)
            f = facts[current]
            new = None
            if key in ("price_in", "price_out") and f[key] is not None:
                new = f"{f[key]:g}"
            elif key in ("vision", "response_format"):
                new = "true" if f[key] else "false"
            elif key == "price_source":
                new = "snapshot"
            if new is not None:
                line = f"    {key}: {new}"
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = (os.environ.get("LLM_BASE_URL") or "").rstrip("/")
    if not base:
        print("LLM_BASE_URL is not set in this shell; nothing fetched.", file=sys.stderr)
        return 1
    headers = {}
    key = os.environ.get("LLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = httpx.get(f"{base}/models", headers=headers, timeout=30.0)
    print(f"GET /models -> HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json().get("data") or []
    by_id = {m.get("id"): m for m in data if isinstance(m, dict)}
    print(f"gateway lists {len(by_id)} models")

    missing = sorted(ALLOWED_MODEL_IDS - set(by_id))
    for mid in missing:
        provider = mid.split("/")[0]
        near = difflib.get_close_matches(
            mid, [i for i in by_id if i and i.startswith(provider + "/")], n=3, cutoff=0.6
        )
        print(f"MISSING {mid}  (close: {', '.join(near) or 'none'})")

    kept = {
        mid: {k: by_id[mid][k] for k in KEEP_KEYS if k in by_id[mid]}
        for mid in sorted(ALLOWED_MODEL_IDS)
        if mid in by_id
    }
    facts = {mid: summarise(m) for mid, m in kept.items()}
    for mid, f in facts.items():
        print(
            f"{mid:36} in={f['price_in']} out={f['price_out']} vision={f['vision']} "
            f"response_format={f['response_format']} reasoning={f['reasoning_param']} "
            f"ctx={f['context_length']}"
        )
    if missing:
        print(f"STOP: {len(missing)} allowed id(s) missing; snapshot and yaml not written.")
        return 2
    if args.dry_run:
        return 0

    snapshot = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "GET {LLM_BASE_URL}/models",
        "models": kept,
    }
    SNAPSHOT.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    MODELS_YAML.write_text(
        update_yaml(MODELS_YAML.read_text(encoding="utf-8"), facts), encoding="utf-8"
    )
    print(f"wrote {SNAPSHOT.relative_to(ROOT)} and updated {MODELS_YAML.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
