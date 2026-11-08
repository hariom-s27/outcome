"""Build the submission zip (P8a A-9) from tracked files + the whole .git folder.

    uv run python scripts/make_zip.py            # -> dist/229070422_hariom_singh_aiml.zip

Entries are rooted at the repo folder name (<repo>/app/..., <repo>/.git/...). Only files that
`git ls-files` lists go in, so untracked data (sample/, cache/, a local env file) cannot.
Fails (exit 1, no zip left behind) when any of these hold:
  - the working tree is dirty
  - a tracked path is an env file (only .env.example is allowed) or lies under sample/, cache/,
    _freshclone/, dist/, .venv/ or __pycache__/
  - a *.pdf / *.xlsx / *.docx / *.csv is tracked outside tests/fixtures/
  - a key-like string (the OpenRouter sk-or- pattern) is in tracked text (file:line printed,
    never the match)
  - the zip is >= 100 MB
Prints the file count, total size, the 10 largest files and the checks passed. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ZIP_NAME = "229070422_hariom_singh_aiml.zip"
MAX_BYTES = 100 * 1024 * 1024
FORBIDDEN_DIRS = ("sample", "cache", "_freshclone", "dist", ".venv", "__pycache__")
DOC_SUFFIXES = (".pdf", ".xlsx", ".docx", ".csv")
FIXTURES = "tests/fixtures/"
ENV_ALLOWED = ".env.example"
KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_\-]{8,}")  # same pattern as scripts/guards/key_strings.py


class ZipCheckError(Exception):
    """A safety check failed; the message lists every problem."""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return out.stdout


def tracked_files(repo: Path) -> list[str]:
    return [p for p in _git(repo, "ls-files", "-z").split("\0") if p]


def dirty_paths(repo: Path) -> list[str]:
    return [line for line in _git(repo, "status", "--porcelain").splitlines() if line.strip()]


def path_problem(path: str) -> str | None:
    parts = path.split("/")
    name = parts[-1]
    if (name == ".env" or name.startswith(".env.")) and name != ENV_ALLOWED:
        return "env file (only .env.example is allowed)"
    for d in FORBIDDEN_DIRS:
        if d in parts[:-1]:
            return f"under {d}/"
    if name.lower().endswith(DOC_SUFFIXES) and not path.startswith(FIXTURES):
        return f"document binary outside {FIXTURES}"
    return None


def key_problems(repo: Path, paths: list[str]) -> list[str]:
    problems = []
    for p in paths:
        try:
            raw = (repo / p).read_bytes()
        except OSError as exc:
            problems.append(f"{p}: unreadable ({exc.__class__.__name__})")
            continue
        if b"\0" in raw:
            continue  # binary
        text = raw.decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if KEY_RE.search(line):
                problems.append(f"{p}:{n}: key-like string (sk-or-...)")
    return problems


def git_dir_files(repo: Path) -> list[str]:
    git_dir = repo / ".git"
    return sorted(f.relative_to(repo).as_posix() for f in git_dir.rglob("*") if f.is_file())


def check(repo: Path) -> list[str]:
    """Runs every pre-build check; returns tracked paths or raises ZipCheckError."""
    dirty = dirty_paths(repo)
    if dirty:
        raise ZipCheckError(f"working tree is dirty ({len(dirty)} paths): commit first")
    paths = tracked_files(repo)
    problems = [f"{p}: {r}" for p in paths if (r := path_problem(p))]
    problems += key_problems(repo, paths)
    if problems:
        raise ZipCheckError("\n".join(problems))
    return paths


def build(repo: Path, out: Path, paths: list[str], max_bytes: int = MAX_BYTES) -> dict:
    root = repo.name
    entries = paths + git_dir_files(repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    sizes = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in entries:
            src = repo / rel
            zf.write(src, f"{root}/{rel}")
            sizes.append((src.stat().st_size, rel))
    size = out.stat().st_size
    if size >= max_bytes:
        out.unlink()
        raise ZipCheckError(f"zip is {size} bytes, limit {max_bytes}")
    sizes.sort(reverse=True)
    return {"files": len(entries), "tracked": len(paths), "bytes": size, "largest": sizes[:10]}


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.2f} MB"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--out", type=Path, default=None, help=f"default <repo>/dist/{ZIP_NAME}")
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    out = args.out or repo / "dist" / ZIP_NAME
    try:
        paths = check(repo)
        info = build(repo, out, paths)
    except ZipCheckError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"zip: {out}")
    in_git = info["files"] - info["tracked"]
    print(f"files: {info['files']} ({info['tracked']} tracked + {in_git} in .git)")
    print(f"size: {_mb(info['bytes'])} (limit {_mb(MAX_BYTES)})")
    print("largest files (uncompressed):")
    for n, rel in info["largest"]:
        print(f"  {_mb(n):>10}  {rel}")
    print(
        "checks passed: clean tree, no forbidden paths, no document binaries outside "
        f"{FIXTURES}, no key-like strings, size < 100 MB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
