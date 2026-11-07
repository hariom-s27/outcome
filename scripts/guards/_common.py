"""Shared helpers for the pre-commit guard scripts (stdlib only)."""

from __future__ import annotations

import sys
from pathlib import Path

# Files handed to us as-is by the assignment. Never scanned for content, only hash-checked.
GIVEN_FILES = ("ASSIGNMENT.md", "tools/validate.py")
GIVEN_DIRS = ("contract/",)


def norm(path: str) -> str:
    """Repo-relative path with forward slashes."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def is_given(path: str) -> bool:
    p = norm(path)
    return p in GIVEN_FILES or p.startswith(GIVEN_DIRS)


def read_text(path: str, limit: int = 5 * 1024 * 1024) -> str | None:
    """Text content of a file, or None for binaries / unreadable / oversized files."""
    try:
        f = Path(path)
        if f.stat().st_size > limit:
            return None
        data = f.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="ignore")


def finish(problems: list[str], title: str) -> int:
    if problems:
        print(f"{title}:")
        for line in problems:
            print(f"  {line}")
        return 1
    return 0


def files_from_argv() -> list[str]:
    return [norm(a) for a in sys.argv[1:]]
