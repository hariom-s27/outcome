"""Block OpenRouter-style keys in staged text. Prints file:line only, never the match."""

from __future__ import annotations

import re
import sys

from _common import files_from_argv, finish, read_text

KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_\-]{8,}")


def main() -> int:
    problems = []
    for p in files_from_argv():
        text = read_text(p)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if KEY_RE.search(line):
                problems.append(f"{p}:{n}: key-like string (sk-or-...)")
    return finish(problems, "possible API keys staged")


if __name__ == "__main__":
    sys.exit(main())
