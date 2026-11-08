"""Dev-only: ask the LLM gateway how much this key has spent (GET {LLM_BASE_URL}/key).

Run inside the worker container (scripts/ is not in the image, so mount it):

    docker compose -f compose.yaml -f compose.dev.yaml run --rm \
        -v ${PWD}/scripts:/srv/scripts:ro worker python scripts/key_status.py

Prints only label, usage_usd, limit_usd, limit_remaining_usd, is_free_tier. Never prints the
key, the request headers, the response body or any environment variable. Not imported by the
app; not part of the shipped pipeline.
"""

from __future__ import annotations

import os
import sys

import httpx

FIELDS = (
    ("usage_usd", "usage"),
    ("limit_usd", "limit"),
    ("limit_remaining_usd", "limit_remaining"),
    ("is_free_tier", "is_free_tier"),
)


def _unavailable(code: object) -> int:
    print(f"status {code}: endpoint not available on this gateway")
    return 1


def main() -> int:
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    if not base or not key:
        print("LLM_BASE_URL or LLM_API_KEY not set in this container")
        return 1
    try:
        resp = httpx.get(f"{base}/key", headers={"Authorization": f"Bearer {key}"}, timeout=10.0)
    except httpx.HTTPError as exc:
        # exception text is not printed: it can carry request details
        return _unavailable(type(exc).__name__)
    if resp.status_code != 200:
        return _unavailable(resp.status_code)
    try:
        body = resp.json()
    except ValueError:
        return _unavailable(f"{resp.status_code} (non-JSON body)")
    data = body.get("data", body) if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return _unavailable(f"{resp.status_code} (unexpected body)")

    label = data.get("label")
    if label:
        # some gateways set the label to a masked form of the key itself: never print that
        if str(label).lower().startswith(("sk-", "key-")):
            print("label: (key-derived label, not printed)")
        else:
            print(f"label: {label}")
    for out_name, src in FIELDS:
        print(f"{out_name}: {data.get(src)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
