"""Gates before any paid run (P4-05, P4-06): clean git tree (PR-09) and the dry run (R-A).

Used by scripts/eval_dev.py and scripts/spikes/p4_launch.py on the host. Every paid number
must be tied to a commit, so uncommitted code/config (tracked changes or untracked files under
app/, scripts/, config/, tests/, .claude/, compose*.yaml, Dockerfile, pyproject.toml,
uv.lock) refuses the run unless --allow-dirty (Hariom's yes; the report says so). Result and
log files (eval/, logs/, ...) do not count.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GitRunner = Callable[[list[str]], str]


def _git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT, check=True)
    return proc.stdout


# Hariom, 8 Nov: only code/config decides what a paid number is tied to; results and logs
# (eval/, logs/, outputs/ ...) never count.
CODE_DIRS = ("app/", "scripts/", "config/", "tests/", ".claude/")
CODE_FILES = ("Dockerfile", "pyproject.toml", "uv.lock")
COMPOSE = re.compile(r"^compose[^/]*\.yaml$")


def is_code_path(path: str) -> bool:
    p = path.strip().strip('"').replace("\\", "/")
    return p.startswith(CODE_DIRS) or p in CODE_FILES or bool(COMPOSE.match(p))


def _porcelain_paths(line: str) -> list[str]:
    """`XY path` or `XY old -> new` (renames: both sides count)."""
    return [p for p in line[3:].split(" -> ") if p.strip()]


def dirty_paths(git: GitRunner = _git) -> list[str]:
    """Porcelain lines (tracked changes and untracked files) that touch code/config paths;
    empty list = clean for a paid run."""
    lines = [ln for ln in git(["status", "--porcelain"]).splitlines() if ln.strip()]
    return [ln for ln in lines if any(is_code_path(p) for p in _porcelain_paths(ln))]


def head_sha(git: GitRunner = _git) -> str:
    return git(["rev-parse", "--short", "HEAD"]).strip()


def clean_tree_gate(allow_dirty: bool, git: GitRunner = _git) -> tuple[bool, str]:
    """(may run, one-line message). Prints paths count only, never file contents."""
    dirty = dirty_paths(git)
    if not dirty:
        return True, "clean tree"
    if allow_dirty:
        return True, f"DIRTY tree ({len(dirty)} paths) allowed by --allow-dirty"
    return False, (
        f"refused: {len(dirty)} uncommitted code/config paths; commit first (PR-09) "
        "or pass --allow-dirty with Hariom's yes"
    )
