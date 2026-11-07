"""PreToolUse guard for Claude Code (stdlib only).

Reads the hook payload (JSON) on stdin. Exit 0 = allow; exit 2 = block, reason on stderr.
Any internal error also exits 2 (fail closed). Run with the repo venv interpreter:
  .venv/Scripts/python.exe .claude/hooks/guard.py

Blocks when a tool path or shell command:
  - mentions a .env file (not .env.example)
  - mentions the answer folder, a held-out document, or cache/
  - runs git commit / push / rebase / reset --hard
  - prints environment variables
  - writes, moves, deletes or restores a frozen file: contract/, tools/validate.py,
    ASSIGNMENT.md (Edit/Write tools; shell redirects, rm/mv/cp-to, Set-Content, sed -i,
    git checkout/restore ...). Reading or running them is allowed (PR-08).
  - (shell only) mentions .claude/ at all, so edits there always go through the ask step
Secret paths (.env*, answers, held-out docs) stay blocked on any mention. cache/ is blocked
in any tool path field, and in shell commands when it is a real path token (PR-70), so a
regex fragment like cache\\|def is not a false stop.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

ENV_FILE = re.compile(r"(?<!\w)\.env(?!\.example)(?!\w)")
# Tool path fields are always paths: any cache/ segment or a path ending in cache is blocked.
CACHE_DIR = re.compile(r"(?<![\w.-])cache[/\\]")
CACHE_PATH_END = re.compile(r"(?<![\w.-])cache$")
# PR-70, shell commands: cache/ counts only as a real path token, checked on the raw text
# (backslashes kept): the folder + / or \ + a path char (letter, digit, _ . - or a glob *),
# or the bare folder name as a whole argument (optionally with one trailing separator).
# A regex fragment such as cache\|def is not a path and stays allowed.
CACHE_TOKEN = re.compile(
    r"(?<![\w.-])cache(?:"
    r"(?:/|\\{1,2})[\w.*-]"  # cache/llm/x.json, cache\debug\y, .\cache\z
    r"|[/\\]?(?=$|[\s\"'`;&),])"  # bare argument: ls cache, ls cache/, "cache"
    r"|(?=\|)"  # bare argument piped: ls cache|x (not cache\|x)
    r")",
    re.IGNORECASE,
)
SEALED = ("sample-data-output-validated", "lease_003", "budget_001")

PATH_KEYS = ("file_path", "path", "notebook_path", "glob")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}

# Shell commands may not touch .claude/ at all: edits there go through Edit/Write, which ask.
CLAUDE_DIR = re.compile(r"(?<![\w.-])\.claude(?=[/\\\s\"']|$)", re.IGNORECASE)

FROZEN_REL = re.compile(r"^(contract/|tools/validate\.py$|assignment\.md$)")
# A shell argument that names a frozen file (relative, absolute or ./-prefixed). Loose on
# purpose: a false block costs one round trip, a missed write costs the contract.
FROZEN_ARG = re.compile(r"(?:^|/)(?:contract(?:/.*)?|tools/validate\.py|assignment\.md)$")
REDIRECT = re.compile(r">{1,2}\s*[\"']?([^\s\"';|&<>()]+)")
# Shell verbs that change any file named in their arguments (bash + PowerShell + aliases).
WRITE_VERBS = {
    "rm", "rmdir", "del", "erase", "rd", "ri", "remove-item", "unlink", "shred",
    "mv", "move", "mi", "move-item", "ren", "rename", "rni", "rename-item",
    "tee", "tee-object", "truncate", "set-content", "sc", "add-content", "ac",
    "out-file", "clear-content", "clc", "new-item", "ni",
}  # fmt: skip
COPY_VERBS = {"cp", "copy", "cpi", "copy-item", "xcopy", "robocopy", "install"}
GIT_WRITE_SUBS = {"checkout", "restore", "mv", "rm", "stash"}

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
                return f"git {sub} is reserved for Hariom"
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
    if is_path:
        if CACHE_DIR.search(t) or CACHE_PATH_END.search(t.rstrip("/")):
            return "touches cache/"
    elif CACHE_TOKEN.search(text):
        return "touches cache/"
    return None


def _arg_paths(tok: str) -> list[str]:
    """A shell token -> the path(s) it may name: quotes, -Param: prefixes and commas removed."""
    t = tok.strip("\"'").replace("\\", "/").lower()
    if t.startswith("-") and ":" in t:
        t = t.split(":", 1)[1]
    return [p.strip("\"'").rstrip("/") for p in t.split(",") if p.strip("\"'")]


def _is_frozen(tok: str) -> bool:
    return any(FROZEN_ARG.search(p) for p in _arg_paths(tok))


def _copy_targets(args: list[str]) -> list[str]:
    """Destination argument(s) of cp / Copy-Item; sources are reads and stay allowed."""
    targets, positional, i = [], [], 0
    while i < len(args):
        low = args[i].lower()
        name = low.split(":", 1)[0]
        if name in ("-t", "--target-directory") or (
            len(name) > 2 and "-destination".startswith(name)
        ):
            if ":" in low:
                targets.append(args[i])
            elif i + 1 < len(args):
                targets.append(args[i + 1])
            i += 2
            continue
        if low.startswith("--target-directory="):
            targets.append(low.split("=", 1)[1])
        elif name in ("-path", "-literalpath", "-lp"):
            i += 2  # source
            continue
        elif not low.startswith("-") or low == "-":
            positional.append(args[i])
        i += 1
    if not targets and len(positional) >= 2:
        targets.append(positional[-1])
    return targets


def frozen_write_block(command: str) -> str | None:
    """Block shell commands that write, move, delete or restore a frozen file. Reads and runs
    (cat, Get-Content, uv run python tools/validate.py ...) stay allowed."""
    reason = "command may modify a frozen file (contract/, tools/validate.py, ASSIGNMENT.md)"
    if any(_is_frozen(m) for m in REDIRECT.findall(command)):
        return reason
    for seg in _segments(command):
        toks = _tokens(seg.replace("\\", "/"))  # posix shlex would eat Windows backslashes
        for i, tok in enumerate(toks):
            verb, args = _base(tok), toks[i + 1 :]
            if verb in WRITE_VERBS and any(_is_frozen(a) for a in args):
                return reason
            if verb == "sed" and any(a == "-i" or a.startswith(("-i", "--in-place")) for a in args):
                if any(_is_frozen(a) for a in args):
                    return reason
            if verb in COPY_VERBS and any(_is_frozen(a) for a in _copy_targets(args)):
                return reason
            if verb in ("git", "git.exe") and any(a.lower() in GIT_WRITE_SUBS for a in args):
                if any(_is_frozen(a) for a in args):
                    return reason
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
        if reason := frozen_write_block(command):
            return reason
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
