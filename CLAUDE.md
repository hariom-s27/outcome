# CLAUDE.md — Outcome DocExtract

Document extraction service for the Outcome take-home (role: AI/ML Developer).
`POST /jobs` takes a file (PDF/DOCX/XLSX/CSV) + a field-list JSON and returns a job id;
a worker fills a result in the fixed contract format. Brief: `ASSIGNMENT.md`. Contract: `contract/`.
Plan: `claude/ROADMAP.md`. Decisions: `decisions/DECISION_LOG.md`. Rules: `research/SYNTHESIS.md` §3, §7.

## Hard rules
1. Never read `.env` or `.env.*` (only `.env.example`). Never print environment variables.
2. Never read anything under `sample/sample-data-output-validated/` (answers) or the held-out
   documents `lease_003` and `budget_001`. Never read `cache/`.
3. Never edit `contract/`, `tools/validate.py`, `ASSIGNMENT.md`, `sample/`.
4. Never run `git commit`, `git push`, `git reset --hard`, `git rebase`. Hariom commits.
5. Never put a value from a sample document or answer file in code, tests, fixtures, logs,
   reports or messages. Doc ids, field names, counts and scores only (D04, R31).
6. All LLM calls go through `LLM_BASE_URL` / `LLM_API_KEY` only; listed models only (brief §3).
7. Default test run makes no network calls and has no key (R32).
8. Logs carry metadata only (job id, status, timings); never file content or field descriptions (R23).
9. Every job reaches a terminal status with schema-valid output; terminal statuses never change.
10. Add a dependency only after asking. Only decisions in the current phase's table may be added.

These are enforced, not just written: `.claude/settings.json` (deny/ask/allow),
`.claude/hooks/guard.py` (PreToolUse, fails closed) and `.pre-commit-config.yaml`.

## Commands
```
uv sync                                   # create .venv from uv.lock (Python 3.12)
uv run pre-commit install                 # once per clone (Hariom)
uv run pre-commit run --all-files         # all guards: gitleaks, paths, binaries, size, keys,
                                          #   sample values, frozen-file hashes
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # fast tests (network blocked, no key)
docker compose up -d --build              # api on :8080, worker, db
curl -s localhost:8080/health
uv run python tools/validate.py outputs/ --schema-dir sample/schemas   # exit 0 = all valid
```

## Repo map
| Path | What | Agent access |
|---|---|---|
| `ASSIGNMENT.md`, `contract/`, `tools/validate.py` | given by Outcome; frozen (hash-checked) | read only |
| `sample/manifest.csv`, `sample/schemas/` | doc → schema map, field lists | read only |
| `sample/sample-data-documents/` | DEV documents | read only; **lease_003, budget_001 never** |
| `sample/sample-data-output-validated/` | answers | **never** |
| `cache/` | dev LLM cache | **never** |
| `.env`, `.env.*` | secrets | **never** (`.env.example` is fine) |
| `app/` | service code (api, worker, db) | edit |
| `tests/` | pytest; `tests/fixtures/` = invented data only | edit |
| `scripts/guards/` | pre-commit guard scripts | edit (ask) |
| `scripts/` | chaos test, output maker | edit |
| `outputs/` | one result JSON per sample doc | generated |
| `logs/` | phase reports, lock check, chaos output | write |
| `claude/`, `decisions/`, `research/`, `prompts/` | process files, on disk only (git-ignored) | read; edit only when asked |
| `.claude/`, `.pre-commit-config.yaml`, `pyproject.toml` | guards and config | edit only after asking |

## Workflow (every phase)
1. **Plan**: read the listed files, report a read-only plan, wait for APPROVED when asked.
2. **Implement**: only what the phase's decision table approves; tests first where listed.
3. **Verify**: run the commands; paste output tails; all `outputs/*.json` valid.
4. **Report**: `logs/P#_report.md` with PLAIN SUMMARY, evidence, deviations, SELF-AUDIT.
5. **STOP** at the end of each Part with draft commit messages. Never commit.

## Conventions
- Python 3.12, stdlib-first; ruff config in `pyproject.toml`.
- Commits (Hariom): `test:` → `feat:`/`fix:` → `docs:` → `chore(process):`; subject ≤ 72 chars.
  Drafted messages carry NO `Assisted-by:` or `Co-Authored-By:` trailer (P1-19).
- No broad `except` that hides errors; surface errors with context.
- Windows host, Linux containers: LF line endings (`.gitattributes`); compose never sets `platform:`.

## Known gotchas
- The guard blocks any path or command containing `.env` (except `.env.example`), `cache/`,
  the answer folder or the held-out doc ids — even in harmless commands. Frozen files are
  blocked only for writes (reads and `uv run python tools/validate.py` are fine).
  If a guard blocks you: STOP and report. Never rephrase or reach the goal another way.
- Shell commands may not mention `.claude/` at all; edit files there with Edit/Write (asks).
  Guard regression tests: `uv run python -m unittest discover -s tests -v`.
- `tools/validate.py` in directory mode prints nothing for valid files; use the exit code, or
  single-file mode (`--schema`) to see `VALID` lines.
- OpenAPI 3.1 ignores `nullable`: omit `result` / `error` / `stage` instead of sending null.
