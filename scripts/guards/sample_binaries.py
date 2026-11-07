"""Block document-type files (the kinds the sample set uses) outside tests/fixtures/."""

from __future__ import annotations

import sys

from _common import files_from_argv, finish

DOC_EXTS = (".pdf", ".xlsx", ".xls", ".docx", ".doc", ".csv")


def main() -> int:
    problems = [
        f"{p}: document file outside tests/fixtures/"
        for p in files_from_argv()
        if p.lower().endswith(DOC_EXTS) and not p.startswith("tests/fixtures/")
    ]
    return finish(problems, "document binaries staged")


if __name__ == "__main__":
    sys.exit(main())
