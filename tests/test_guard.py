"""Regression tests for the PreToolUse guard (stdlib unittest; also collected by pytest).

Each case runs the guard as Claude Code does: JSON payload on stdin, exit 2 = blocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude" / "hooks" / "guard.py"
R = ROOT.as_posix()
DOCS = R + "/sample/sample-data-documents/"
ANSWERS = R + "/sample/sample-data-output-validated/"
GIT = "git "

BLOCK, ALLOW = True, False

CASES = [
    # .env files (only .env.example allowed)
    (BLOCK, "Read", {"file_path": R + "/.env"}),
    (BLOCK, "Read", {"file_path": R + "/.env.local"}),
    (ALLOW, "Read", {"file_path": R + "/.env.example"}),
    (BLOCK, "Bash", {"command": "type .env"}),
    (BLOCK, "PowerShell", {"command": "Get-Content .env"}),
    (BLOCK, "Bash", {"command": "cp .env.example .env"}),
    (ALLOW, "Bash", {"command": 'python -c "print(1)" && cat .env.example'}),
    (BLOCK, "Glob", {"pattern": "**/.env*"}),
    # answers, held-out docs, cache/
    (BLOCK, "Read", {"file_path": ANSWERS + "lease_002.json"}),
    (BLOCK, "Read", {"file_path": DOCS + "budget_001.pdf"}),
    (BLOCK, "Read", {"file_path": DOCS + "lease_003.pdf"}),
    (ALLOW, "Read", {"file_path": DOCS + "lease_001.pdf"}),
    (BLOCK, "Grep", {"pattern": "x", "path": R + "/cache"}),
    (BLOCK, "Bash", {"command": "ls cache/"}),
    (BLOCK, "Bash", {"command": "uv run python tools/validate.py cache/runs/"}),
    (BLOCK, "PowerShell", {"command": "Get-Content sample\\sample-data-output-validated\\x.json"}),
    (BLOCK, "Read", {"file_path": R + "/cache/spikes/a1.txt"}),
    (BLOCK, "Bash", {"command": "cat ./sample/sample-data-documents/lease_003.docx"}),
    (ALLOW, "Bash", {"command": "rm -r .pytest_cache/ __pycache__/ .ruff_cache/"}),
    (ALLOW, "Bash", {"command": "ls ~/.cache/pre-commit"}),
    # PR-70: cache/ only as a real path token in shell commands
    (ALLOW, "Bash", {"command": 'grep -n "cache\\|def" app/llm/client.py'}),
    (ALLOW, "PowerShell", {"command": "Select-String -Pattern 'cache\\|def' app\\x.py"}),
    (ALLOW, "Bash", {"command": "docker compose build --no-cache worker"}),
    (ALLOW, "Bash", {"command": "uv run ruff check app/llm/cache_store.py"}),
    (BLOCK, "Bash", {"command": "cat cache/llm/x.json"}),
    (BLOCK, "PowerShell", {"command": "Get-Content cache\\debug\\y"}),
    (BLOCK, "PowerShell", {"command": "Get-ChildItem .\\cache\\z"}),
    (BLOCK, "Bash", {"command": "ls cache"}),
    (BLOCK, "Bash", {"command": "ls cache|head"}),
    (BLOCK, "PowerShell", {"command": "Get-ChildItem -Path 'cache'"}),
    (BLOCK, "Bash", {"command": "ls cache/*"}),
    (BLOCK, "Glob", {"pattern": "cache/**/*.json"}),
    (BLOCK, "Read", {"file_path": R + "\\cache\\spikes\\a.json"}),
    # git writes
    (BLOCK, "Bash", {"command": GIT + "commit -m test"}),
    (BLOCK, "PowerShell", {"command": "& " + GIT + "-c user.name=x commit -m t"}),
    (BLOCK, "Bash", {"command": GIT + "pu" + "sh origin main"}),
    (BLOCK, "Bash", {"command": GIT + "reset --hard HEAD"}),
    (BLOCK, "Bash", {"command": GIT + "rebase main"}),
    (ALLOW, "Bash", {"command": GIT + "add pyproject.toml && " + GIT + "status"}),
    (ALLOW, "Bash", {"command": GIT + "reset"}),
    # environment printing
    (BLOCK, "Bash", {"command": "printenv"}),
    (BLOCK, "Bash", {"command": "env"}),
    (BLOCK, "Bash", {"command": "echo $LLM_API_KEY"}),
    (BLOCK, "PowerShell", {"command": "Get-ChildItem env:"}),
    (BLOCK, "PowerShell", {"command": "echo $env:LLM_API_KEY"}),
    (ALLOW, "PowerShell", {"command": "$env:UV_PYTHON_DOWNLOADS='never'; uv sync"}),
    (BLOCK, "Bash", {"command": "python -c 'import os; print(os.environ)'"}),
    (BLOCK, "Bash", {"command": "docker compose config"}),
    # frozen files
    (BLOCK, "Write", {"file_path": R + "/contract/openapi.yaml", "content": "x"}),
    (BLOCK, "Edit", {"file_path": str(ROOT / "tools" / "validate.py")}),
    (BLOCK, "Edit", {"file_path": R + "/ASSIGNMENT.md"}),
    (ALLOW, "Read", {"file_path": R + "/contract/openapi.yaml"}),
    (BLOCK, "Bash", {"command": "echo x > contract/README.md"}),
    (ALLOW, "Bash", {"command": "cat contract/README.md"}),
    (ALLOW, "Write", {"file_path": R + "/app/api.py"}),
    # frozen files (PR-08): reading or running is allowed, writing/moving/deleting is not
    (ALLOW, "Bash", {"command": "uv run python tools/validate.py out/ --schema-dir s/ 2>&1"}),
    (ALLOW, "PowerShell", {"command": "uv run python tools\\validate.py out\\ > logs/v.txt"}),
    (ALLOW, "PowerShell", {"command": "Get-Content tools/validate.py | Select-Object -First 5"}),
    (ALLOW, "Bash", {"command": "cat ASSIGNMENT.md > logs/brief_copy.txt"}),
    (ALLOW, "Bash", {"command": "sed -n 1,20p tools/validate.py"}),
    (ALLOW, "Bash", {"command": "cp contract/schema.json logs/x.json"}),
    (ALLOW, "PowerShell", {"command": "Copy-Item -Path contract/a.yaml -Destination logs/"}),
    (ALLOW, "Bash", {"command": GIT + "diff -- contract/ tools/validate.py"}),
    (BLOCK, "Bash", {"command": "echo x >> tools/validate.py"}),
    (BLOCK, "PowerShell", {"command": "'x' > .\\ASSIGNMENT.md"}),
    (BLOCK, "PowerShell", {"command": "Set-Content -Path contract/a.yaml -Value x"}),
    (BLOCK, "PowerShell", {"command": "Add-Content ASSIGNMENT.md 'x'"}),
    (BLOCK, "PowerShell", {"command": "'x' | Out-File -FilePath:tools\\validate.py"}),
    (BLOCK, "PowerShell", {"command": "Remove-Item -Recurse contract"}),
    (BLOCK, "PowerShell", {"command": "Move-Item tools/validate.py tools/old.py"}),
    (BLOCK, "PowerShell", {"command": "Copy-Item logs/x.py -Destination tools/validate.py"}),
    (BLOCK, "PowerShell", {"command": "Copy-Item logs/x.md ASSIGNMENT.md"}),
    (BLOCK, "Bash", {"command": "rm -f contract/openapi.yaml"}),
    (BLOCK, "Bash", {"command": "mv ASSIGNMENT.md a.md"}),
    (BLOCK, "Bash", {"command": "cp /tmp/x.py " + R + "/tools/validate.py"}),
    (BLOCK, "Bash", {"command": "cp -t contract/ logs/x.json"}),
    (BLOCK, "Bash", {"command": "sed -i s/a/b/ tools/validate.py"}),
    (BLOCK, "Bash", {"command": "echo x | tee contract/README.md"}),
    (BLOCK, "Bash", {"command": GIT + "checkout HEAD -- tools/validate.py"}),
    (BLOCK, "PowerShell", {"command": GIT + "restore contract/"}),
    # .claude/ via shell (edits there must go through Edit/Write, which ask)
    (BLOCK, "Bash", {"command": "uv run ruff format .claude/hooks/guard.py"}),
    (BLOCK, "Bash", {"command": "uv run ruff format .claude\\hooks"}),
    (BLOCK, "PowerShell", {"command": "Set-Content .claude/settings.json '{}'"}),
    (BLOCK, "Bash", {"command": "rm -r .claude"}),
    (BLOCK, "Bash", {"command": 'sed -i s/a/b/ ".claude/settings.json"'}),
    (BLOCK, "Bash", {"command": "cat ~/.claude/settings.json"}),
    (ALLOW, "Bash", {"command": "uv run ruff format scripts/ && cat CLAUDE.md"}),
    (ALLOW, "Edit", {"file_path": R + "/.claude/hooks/guard.py"}),  # Edit -> settings "ask"
]


def run_guard(stdin: str) -> int:
    proc = subprocess.run(
        [sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True, timeout=30
    )
    return proc.returncode


class GuardCases(unittest.TestCase):
    def test_cases(self) -> None:
        for expect_block, tool, tool_input in CASES:
            payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": R})
            with self.subTest(tool=tool, input=tool_input):
                self.assertEqual(run_guard(payload), 2 if expect_block else 0)

    def test_malformed_payload_fails_closed(self) -> None:
        self.assertEqual(run_guard("not json"), 2)

    def test_bad_shapes_fail_closed(self) -> None:
        for payload in (
            {"tool_name": "Bash", "tool_input": "ls"},
            {"tool_name": "Bash", "tool_input": {"command": 123}},
            {"tool_name": "Read", "tool_input": ["x"]},
            [1, 2],
        ):
            with self.subTest(payload=payload):
                self.assertEqual(run_guard(json.dumps(payload)), 2)


if __name__ == "__main__":
    unittest.main()
