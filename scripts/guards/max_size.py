"""Block staged files larger than 5 MB."""

from __future__ import annotations

import os
import sys

from _common import files_from_argv, finish

LIMIT = 5 * 1024 * 1024


def main() -> int:
    problems = []
    for p in files_from_argv():
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size > LIMIT:
            problems.append(f"{p}: {size / 1024 / 1024:.1f} MB > 5 MB")
    return finish(problems, "files too large")


if __name__ == "__main__":
    sys.exit(main())
