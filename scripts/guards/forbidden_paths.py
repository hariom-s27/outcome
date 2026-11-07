"""Block staged files that must never be committed: .env files, sample/, cache/."""

from __future__ import annotations

import re
import sys

from _common import files_from_argv, finish

ENV_RE = re.compile(r"(^|/)\.env(\.[^/]*)?$")


def reason(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if ENV_RE.search(path) and name != ".env.example":
        return "env file (only .env.example may be committed)"
    if path.startswith("sample/"):
        return "sample data is never committed"
    if path.startswith("cache/"):
        return "cache/ is never committed"
    return None


def main() -> int:
    problems = [f"{p}: {r}" for p in files_from_argv() if (r := reason(p))]
    return finish(problems, "forbidden paths staged")


if __name__ == "__main__":
    sys.exit(main())
