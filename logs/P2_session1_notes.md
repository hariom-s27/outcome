# P2 Session 1 notes — LLM wrapper + /models snapshot (handoff to Session 2)

Spend: **$0**. No chat-completion call was made; the only network call was one free `GET /models`.

## What was built
| Item | Where |
|---|---|
| Part 0: P1 report entry now names guard-fix commit 443d3a4 (it already said FIXED) | `logs/P1_report.md` |
| Model config: 9 ids, vision, prices (snapshot), `reasoning: omit`, `response_format`, `max_tokens` 4096, price cliffs (Haiku 100k ×5, Gemini Pro 200k ×2), baseline Haiku, fallback order | `config/models.yaml` |
| Catalogue: refuses any id not in the YAML **and** not in the brief's hard-coded set | `app/llm/models.py` |
| Wrapper: httpx, `/chat/completions`, Bearer, always `max_tokens`, no reasoning/temperature params, R1/R13 message check (text + JPEG data-URI only; images only to vision models) | `app/llm/client.py` |
| Retries: 4 attempts, 1-2-4(-8) s + ≤25 % jitter, Retry-After (seconds or HTTP date), never past time left (`LLMStopped("deadline")`); 429/408/5xx/timeout/connect/error-in-200/`finish_reason: error`/bad body retried; other 4xx not | `client.py` |
| Shared state in Postgres: `llm_calls` ledger (one row per attempt + per cache hit), `llm_slots` (lease = timeout + 30 s; dead holder frees itself), `llm_state` (429 cool-down, breaker 5 → 60 s, success resets) | `app/schema.sql`, `app/llm/store.py` |
| JSON ladder: `json_object` when config says so, local parse (fences, first balanced `{…}`), 1 text-only repair on `cheapest_text_model()`, truncation → 1 retry with 2× `max_tokens` → `llm_truncated` | `client.py`, `app/llm/jsonparse.py` |
| Stops: per doc 8 calls / $0.05 computed (`doc_llm_cap`), `DEV_BUDGET_USD` vs ledger total (`dev_budget_reached`), `LLM_BREAKER_ABORT=1` → `circuit_open` | `client.py`, `app/llm/settings.py` |
| Dev disk cache (sha256 of canonical body) only when `LLM_CACHE_DIR` set | `app/llm/diskcache.py`, `compose.dev.yaml` |
| Fake gateway for P8 load test (scripted replies, latency, 429 rate) | `app/devtools/fake_llm.py` |
| Snapshot script (free GET, 9 ids only, updates YAML lines, exit 2 if an id is missing) | `scripts/fetch_models.py`, `config/models_snapshot.json` |
| Deps: httpx moved dev → runtime; PyYAML 6.0.3 added (P2-22). `config/` now copied into the image (`Dockerfile`, `.dockerignore`). `compose.yaml` unchanged. | |

## Evidence
- `uv run pytest -q` → **110 passed**, 49 subtests (P1: 55). New: 47 in `tests/test_llm.py`, 3 in `tests/test_fetch_models.py`. Network blocked, key unset.
- `uv run ruff check .` → All checks passed. `ruff format` applied.
- `uv run pre-commit run --all-files` → 7/7 Passed; same 7/7 with `--files` on all new/modified files (untracked files are not covered by `--all-files`).

## Snapshot findings (`fetched_at` 2026-11-07T10:56:31Z)
- **All 9 ids present, none renamed.** Gateway lists 418 models.
- Prices $/M in/out: Haiku 0.10/0.50 · Luna 0.10/0.50 · GLM-flash 0.15/0.50 · Qwen-VL 0.21/1.90 · DeepSeek 0.26/0.38 · Gemini Flash **0.75/3.75** (card said 0.825/4.125) · Gemini Pro 2/12 · Sonnet 2/10 · Sol 2/10.
- Vision: all except DeepSeek. **All 9 list `response_format` and `structured_outputs`** → every model gets `json_object`.
- Reasoning (snapshot `reasoning` block): Haiku `mandatory: false`, **default_effort `medium`**, supports `none` (settles C17: with our "send nothing" profile Haiku will likely reason at medium and bill it) · Luna default enabled, not mandatory, `none` ok · DeepSeek default off · Qwen-VL no reasoning · Gemini Flash/Pro, Sonnet, Sol, GLM mandatory (GLM default `max`).
- `temperature` not in supported params for Anthropic/OpenAI ids (we never send it anyway). Max output: Qwen-VL 32768, Gemini 65536, others ≥ 128000.

## Session 2 must know
1. **`LLM_BASE_URL`/`LLM_API_KEY` are not in the host shell** (they live only in `.env`, which the agent never reads). The snapshot ran inside the worker container, where compose injects them:
   `docker compose run --rm --no-deps -v "<repo>/scripts:/srv/scripts:ro" -v "<repo>/config:/srv/config" worker python scripts/fetch_models.py` (Git Bash needs `MSYS_NO_PATHCONV=1` and `$(pwd -W)`). Paid pilot/eval scripts need the same route (plus `-f compose.dev.yaml` for budget + cache), or Hariom exports the vars in the shell.
2. Watch `tokens_reasoning` in the pilot ledger rows for Haiku (default effort medium). If large, that is the P4 spike-10 question; do not add a reasoning param in P2 (P2-04).
3. Wrapper is **not wired into the worker yet**. API: `LLMClient.from_env(database_url)`; `complete_json(CallContext(job_id, deadline_epoch), model, messages) -> JSONOutcome(status ok|unusable|stopped|failed, data, reason, model_mismatch)`. Never raises for LLM trouble (only `ForbiddenContentError` / `UnknownModelError` for caller bugs). Suggested mapping: ok+valid → SUCCESS; unusable → PARTIAL skeleton `llm_unusable`/`llm_truncated`; stopped → PARTIAL `doc_llm_cap` / `dev_budget_reached` / `deadline` / `circuit_open`; failed → PARTIAL `llm_failed`. Reason goes in `metadata.terminal_reason` (P1 convention).
4. Metadata: `LLMStore(url).job_metadata(job_id, latency_ms)` → contract fields + `models` breakdown, `cost_computed_usd`, `tokens_reasoning`, `model_mismatch`, `cache_hits`. `cost_usd` uses `usage.cost` when reported, else computed. Cache hits cost 0 and are excluded from `model_calls`.
5. `cheapest_text_model()` = Haiku (tie with Luna at 0.60, YAML order wins).
6. Deadline: `CallContext.deadline` is epoch seconds; use the job's `deadline_at` (P1: created + 1500 s).
7. `compose.dev.yaml` passes `DEV_BUDGET_USD` (default 8) and `LLM_CACHE_DIR=/cache/llm` with `./cache` mounted. `docker compose down -v` wipes the ledger total → keep the running total in `eval/history.jsonl` (P2-10).

## Known limits / deviations
- R28 says stop on model mismatch; P2-12 overrides for P2: flag only.
- After a 429 the wait can be backoff **then** cool-down (worst case ~2× Retry-After). Harmless at our volumes; revisit in P8.
- When the breaker's 60 s ends, every waiting worker probes at once (no single half-open probe).
- Part 0: the entry already read FIXED; only the commit hash was added (smallest true change).
