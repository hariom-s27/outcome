# P1 lock check (P1-18)

**PLAIN SUMMARY:** All 6 lock checks passed. The agent could not read the env file, the answer
folder or a held-out document, and could not commit. A commit containing a fake key was
rejected by pre-commit. Only after this may the real key be placed in the env file.

- Date: 2026-11-07
- Tool: Claude Code 2.1.229, model Opus 5.5 (`claude-opus-5-5`), default permission mode
- Env file at check time: fake (placeholder values only)
- No key strings, env values or sample values appear in this log.

## Results

| # | Action (by whom) | Result | Blocking layer | Message (as shown) |
|---|---|---|---|---|
| 1 | Agent: Read tool on `.env` | BLOCKED | `.claude/settings.json` deny rule | "File is in a directory that is denied by your permission settings." |
| 2 | Agent: shell `type .env` | BLOCKED | `.claude/hooks/guard.py` (PreToolUse) | "touches a .env file (only .env.example is allowed)" |
| 3 | Agent: Read tool on a file in `sample/sample-data-output-validated/` (`lease_002.json`) | BLOCKED | deny rule | "File is in a directory that is denied by your permission settings." |
| 4 | Agent: Read tool on held-out document `budget_001.pdf` | BLOCKED | deny rule | "File is in a directory that is denied by your permission settings." |
| 5 | Agent: shell `git commit -m test` | BLOCKED | guard.py | "git commit is reserved for Hariom" |
| 6 | Hariom: commit staging a fake key | BLOCKED | pre-commit `key-strings` hook (`scripts/guards/key_strings.py`) | — |

**6/6 blocked → PASS.**

## Notes
- Checks 1, 3, 4: the deny rule stopped the call first, so this run does not show guard.py
  on its own for those paths. guard.py's own behaviour is covered by its unit tests (below).
- Check 6: gitleaks did **not** flag the fake key (low entropy); the local `key-strings`
  hook caught it. Both stay enabled: gitleaks for real high-entropy secrets, `key-strings`
  for the provider's key format regardless of entropy.
- Guard regression tests: `uv run python -m unittest discover -s tests -v` → 2 tests, OK
  (run by Hariom).
- During the session before the check, guard.py also blocked a shell command that named a
  `.claude/` path (memory index outside the repo). Expected behaviour (P1-17).
