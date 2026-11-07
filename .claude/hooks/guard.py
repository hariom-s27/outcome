"""PreToolUse guard for Claude Code (stdlib only).

Reads the hook payload (JSON) on stdin. Exit 0 = allow; exit 2 = block, reason on stderr.
Any internal error also exits 2 (fail closed). Run with the repo venv interpreter:
  .venv/Scripts/python.exe .claude/hooks/guard.py

Blocks when a tool path or shell command:
  - mentions a .env file (not .env.example)
  - mentions the answer folder, a held-out document, or cache/
  - runs git commit / push / rebase / reset --hard
  - prints environment variables
  - edits a frozen file: contract/, tools/validate.py, ASSIGNMENT.md
  - (shell only) mentions .claude/ at all, so edits there always go through the ask step
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

ENV_FILE = re.compile(r"(?<!\w)\.env(?!\.example)(?!\w)")
CACHE_DIR = re.compile(r"(?<![\w.-])cache[/\\]")
CACHE_PATH_END = re.compile(r"(?<![\w.-])cache$")
SEALED = ("sample-data-output-validated", "lease_003", "budget_001")

PATH_KEYS = ("file_path", "path", "notebook_path", "glob")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}

# Shell commands may not touch .claude/ at all: edits there go through Edit/Write, which ask.
CLAUDE_DIR = re.compile(r"(?<![\w.-])\.claude(?=[/\\\s\"']|$)", re.IGNORECASE)

FROZEN_REL = re.compile(r"^(contract/|tools/validate\.py$|assignment\.md$)")
FROZEN_MENTION = re.compile(r"(?<![\w.-])(contract[/\\]|tools[/\\]validate\.py|assignment\.md)")
SHELL_WRITE = re.compile(
    r"(>|\bsed\s+-i|\brm\b|\bmv\b|\bcp\b|\btee\b|\btruncate\b|\bdel\b|\bset-content\b"
    r"|\badd-content\b|\bout-file\b|\bremove-item\b|\bmove-item\b|\bcopy-item\b"
    r"|\bclear-content\b|\bnew-item\b|\bren(ame-item)?\b|\bgit\s+(checkout|restore|mv|rm)\b)"
)

ENV_PRINT_TOKENS = {"env", "printenv", "env.exe", "printenv.exe"}
ENV_PRINT_RE = re.compile(
    r"(?<!\$)\benv:"  # PowerShell env: drive (gci env:, dir env:)
    r"|\$env:\w++(?!\s*=)"  # PowerShell $env:NAME read (assignment allowed)
    r"|\$\{?\w*(key|token|secret|password)"  # bash $..._KEY reads
    r"|environ\b|getenv\b"  # os.environ / os.getenv / /proc/*/environ
    r"|docker\s+(compose\s+config(?!.*--no-interpolate)|(container\s+)?inspect)"
)
GIT_BLOCKED = {"commit", "push", "rebase"}
GIT_OPTS_WITH_ARG = {"-c", "-C", "--git-dir", "--work-tree", "--namespace"}


def _segments(command: str) -> list[str]:
    return [s for s in re.split(r"&&|\|\||[;|&\n]", command) if s.strip()]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _base(tok: str) -> str:
    return tok.replace("\\", "/").rsplit("/", 1)[-1].lower()


def git_block(command: str) -> str | None:
    for seg in _segments(command):
        toks = _tokens(seg)
        for i, tok in enumerate(toks):
            if _base(tok) not in ("git", "git.exe"):
                continue
            j = i + 1
            while j < len(toks) and toks[j].startswith("-"):
                j += 2 if toks[j] in GIT_OPTS_WITH_ARG else 1
            if j >= len(toks):
                continue
            sub, rest = toks[j].lower(), [t.lower() for t in toks[j + 1 :]]
            if sub in GIT_BLOCKED:
                return f"git {sub} is reserved for Shyam"
            if sub == "reset" and "--hard" in rest:
                return "git reset --hard is not allowed"
    return None


def env_print_block(command: str) -> str | None:
    if ENV_PRINT_RE.search(command.lower()):
        return "command may print environment variables"
    for seg in _segments(command):
        toks = [_base(t) for t in _tokens(seg)]
        if any(t in ENV_PRINT_TOKENS for t in toks):
            return "command may print environment variables"
        if (
            toks
            and toks[0] in ("set", "export", "declare")
            and (len(toks) == 1 or toks[1] in ("-p", "-x"))
        ):
            return "command may print environment variables"
    return None


def sealed_block(text: str, is_path: bool) -> str | None:
    t = text.replace("\\", "/").lower()
    if ENV_FILE.search(t):
        return "touches a .env file (only .env.example is allowed)"
    for s in SEALED:
        if s in t:
            return f"touches a sealed path ({s})"
    if CACHE_DIR.search(t) or (is_path and CACHE_PATH_END.search(t.rstrip("/"))):
        return "touches cache/"
    return None


def rel_path(path: str, cwd: str) -> str:
    p = path.replace("\\", "/")
    root = (os.environ.get("CLAUDE_PROJECT_DIR") or cwd or "").replace("\\", "/").rstrip("/")
    if root and p.lower().startswith(root.lower() + "/"):
        p = p[len(root) + 1 :]
    while p.startswith("./"):
        p = p[2:]
    return p.lower()


def check(payload: dict) -> str | None:
    tool = payload.get("tool_name", "")
    tin = payload.get("tool_input") or {}
    cwd = payload.get("cwd", "")

    for key in PATH_KEYS:
        val = tin.get(key)
        if isinstance(val, str) and val:
            if reason := sealed_block(val, is_path=True):
                return reason
    if tool == "Glob" and isinstance(tin.get("pattern"), str):
        if reason := sealed_block(tin["pattern"], is_path=True):
            return reason

    if tool in WRITE_TOOLS:
        path = tin.get("file_path") or tin.get("notebook_path") or ""
        if path and FROZEN_REL.search(rel_path(path, cwd)):
            return "frozen file (contract/, tools/validate.py, ASSIGNMENT.md) must not be edited"

    if tool in SHELL_TOOLS:
        command = tin.get("command") or ""
        if reason := sealed_block(command, is_path=False):
            return reason
        if CLAUDE_DIR.search(command):
            return "shell commands may not touch .claude/ (use Edit/Write, which ask first)"
        if reason := git_block(command):
            return reason
        if reason := env_print_block(command):
            return reason
        low = command.lower()
        if FROZEN_MENTION.search(low) and SHELL_WRITE.search(low):
            return "command may modify a frozen file (contract/, tools/validate.py, ASSIGNMENT.md)"
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        reason = check(payload)
    except Exception as exc:  # fail closed: a broken guard must block, not allow
        print(f"guard error, blocking to be safe: {type(exc).__name__}", file=sys.stderr)
        return 2
    if reason:
        print(f"Blocked by .claude/hooks/guard.py: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
