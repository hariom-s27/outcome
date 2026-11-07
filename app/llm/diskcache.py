"""Dev-only response cache (P2-11). On only when LLM_CACHE_DIR is set (compose.dev.yaml).

Key = sha256 of the canonical request body. Only good 200 bodies are stored.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def request_key(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        p = self._path(key)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, key: str, response: dict[str, Any]) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
