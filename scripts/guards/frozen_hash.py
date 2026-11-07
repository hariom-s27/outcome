"""Check that the files given with the assignment are unchanged.

Compares contract/*, tools/validate.py and ASSIGNMENT.md with .guards/frozen.sha256.
Hashes are taken after CRLF -> LF so a Windows checkout does not trip the check.
`--write` records the baseline (done once, when the files are first added).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

BASELINE = Path(".guards") / "frozen.sha256"


def frozen_files() -> list[str]:
    files = ["ASSIGNMENT.md", "tools/validate.py"]
    files += sorted(p.as_posix() for p in Path("contract").rglob("*") if p.is_file())
    return files


def digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    if "--write" in sys.argv:
        lines = [f"{digest(p)}  {p}" for p in frozen_files()]
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(lines)} hashes to {BASELINE.as_posix()}")
        return 0

    if not BASELINE.exists():
        print(f"frozen-file check: {BASELINE.as_posix()} missing")
        return 1
    expected = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, p = line.split(maxsplit=1)
            expected[p.strip()] = h

    problems = []
    current = frozen_files()
    for p in current:
        if p not in expected:
            problems.append(f"{p}: not in baseline (new file in a frozen area)")
        elif digest(p) != expected[p]:
            problems.append(f"{p}: changed")
    for p in expected:
        if p not in current:
            problems.append(f"{p}: missing")
    if problems:
        print("frozen files differ from .guards/frozen.sha256:")
        for line in problems:
            print(f"  {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
