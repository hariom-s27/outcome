# P4 plan — Session 1 of 2 (safety tools + measuring harness, $0)

## Hariom's answers (8 Nov) — applied

1. **Budget:** the total cap is **$0.35** (`p4_launch.py --total-cap` default changed to 0.35). Caps per run: pilot $0.01, B1 $0.22 with Gemini last, B2 $0.02 (methods b and c), B3 $0.05, B4 $0.03; they add up to $0.33. B1's Haiku result is reused as B2(a).
2. **Guard scope confirmed:** the path-token rule applies to `cache/` only. `.env*`, the answers folder and the held-out ids stay blocked on any mention. No code change.
3. **The clean-tree check now looks only at code/config paths:** `app/`, `scripts/`, `config/`, `tests/`, `.claude/`, `compose*.yaml`, `Dockerfile`, `pyproject.toml` and `uv.lock`. Both tracked changes and untracked files there count, and so do both sides of a rename. Result and log files (`eval/`, `logs/`, anything else) do not count (`scripts/run_gates.py`). Tests updated: code changes are refused with a count only, `eval/` and `logs/` changes pass, each listed path is covered by its own test, and a rename into `scripts/` counts.
4. **Read-only mounts of `sample/schemas` and `sample/manifest.csv` approved.** The answers folder is never mounted (tested).

Items 1, 3, 4 and 5 under "Anything unclear" below are settled by these answers.

**Re-verified after the changes (8 Nov):**

- `tests/test_p4_gates.py`: `28 passed`.
- Full run: `229 passed, 1 warning in 42.45s`.
- ruff: `All checks passed!` and `91 files already formatted`.
- pre-commit: all 7 hooks `Passed` with `--all-files` and with `--files <14 untracked>`.

## PLAIN SUMMARY

Session 1 built the four safety tools and the measuring harness, tested them on invented
data and ran every spike in free `--dry-run` mode. **No LLM call was made; $0 spent.**
All tests pass (217), ruff is clean, and every pre-commit hook passes on tracked files and on
the 13 new files.

The dry runs show the full spike set costs about **$0.25 (realistic) to $0.33 (fuse
high-side)**. That is near the $0.30 total cap (P4-13). Most of it is Gemini 3.8 Flash in B1.
B1 costs about 2× the P4-08 guess. The proposal below keeps the total at or under $0.30 by
reusing B1's Haiku result as B2(a) and running Gemini last, so its cap can stop it. The other
option is to raise the total to $0.35, which needs your yes.

**Next step (Session 2), only after your APPROVED:** pilot = B1, Haiku, first batch of 8
pages, cap $0.01, then STOP with a projection.

## What Part 0 built

| Item | File(s) | What it does |
|---|---|---|
| PR-70 guard pattern | `.claude/hooks/guard.py` | In shell commands, `cache/` is blocked only when it is a real path token: the folder name + `/` or `\` + a path character (letter, digit, `_ . -`, or a glob `*`), or the bare folder name as a whole argument (`ls cache`, `ls cache/`, `ls cache\|x` piped). The check runs on the raw text (backslashes kept), so a regex fragment like `cache\|def` is allowed. Tool path fields (Read/Grep/Glob `path`, `glob`, `pattern`) keep the strict rule: any `cache/` segment or a path ending in `cache` is blocked. `.env*`, the answer folder and the held-out ids are still blocked on any mention. |
| PR-63/PR-73 fresh-clone check | `scripts/fresh_clone_check.ps1` | Hariom runs it; the agent never does. Steps: stop if :8080 is busy (prints the `down` line, no `-v`) → refuse a dirty local tree → delete `_freshclone` → `git clone` origin → print the cloned commit id and local HEAD, fail if they differ → `docker compose -p freshcheck up -d --build` → poll `/health` every 2 s for up to 60 s and print status + seconds → `down -v` and delete the folder (in `finally`). Exit 0 only on HTTP 200. Windows PowerShell 5.1, ASCII only. |
| R-A dry run | `scripts/dry_run.py` | For each DEV doc (or `--docs`) it runs the worker's steps before the call: `read_document` → `baseline.build_messages` → the fuse's token estimate. No LLM, no DB. Prints blocks, images and estimated tokens per doc, plus any exception type. Exits 1 on any exception or any estimate ≥ 90k. Full records go to the git-ignored cache folder. |
| R-A gate in eval | `scripts/eval_dev.py` | A paid run (not `--reuse`) runs the dry run first and refuses on failure. `--skip-dry-run` exists. The history line and the report say `dry_run: passed / skipped` and `allow_dirty_used`. |
| PR-09 clean tree | `scripts/run_gates.py` (+ `eval_dev.py`, `spikes/p4_launch.py`) | Refuses a paid run when `git status --porcelain` lists a code/config path: `app/`, `scripts/`, `config/`, `tests/`, `.claude/`, `compose*.yaml`, `Dockerfile`, `pyproject.toml` or `uv.lock`, whether a tracked change or an untracked file (scope from the 8 Nov answer). `eval/` and `logs/` do not count. `--allow-dirty` is for Hariom's yes only and is recorded. It prints a path count, never path names or contents. |

**Test evidence (copied from pytest output):**

- `tests/test_guard.py`: `3 passed, 92 subtests passed`. 14 new PR-70 cases: the regex fragment is allowed in Bash and PowerShell; `cache/llm/x.json`, `cache\debug\y`, `.\cache\z`, bare `cache`, `cache|head`, `'cache'`, `cache/*`, a `cache/**` glob and a backslash Read path are all blocked; every older case still passes.
- `tests/test_p4_gates.py` + `tests/test_p4_spikes.py` + `tests/test_eval_dev.py`: `35 passed`. The two new files hold 16 + 11 tests:
  - Clean tree (fake git result): passes, refuses with a count only, the flag allows and says DIRTY.
  - Dry run (invented CSV): ok, an exception fails it, the token limit fails it, held-out ids are refused, and the exit codes are right.
  - Eval gate: a dirty tree is refused before any HTTP, a failed dry run is refused, a skip or a dirty tree is recorded, and `--reuse` needs no gate.
  - Launcher: the total cap holds, the answers folder is never mounted, and a dirty tree is refused before Docker.
  - Merge rules, field groups, page choice, thumbnail size, dry estimates kept per document, and the scorer's held-out refusal.
- Full run: `217 passed, 1 warning in 53.12s` (the warning is the existing starlette TestClient one).
- `ruff check .`: `All checks passed!`. `ruff format --check .`: `90 files already formatted`.
- `pre-commit run --all-files` and `pre-commit run --files <13 untracked>`: all 7 hooks `Passed`.

**Dry run on all 6 DEV docs (`scripts/dry_run.py`):** `dry run PASSED (6 docs)`.

| doc | type | blocks sent / total | images sent / total | truncated | est. tokens (fuse) |
|---|---|---|---|---|---|
| boxscore_001 | csv | 15/15 | 0/0 | no | 4,388 |
| lease_001 | pdf (scan) | 8/25 | 8/25 | **yes** | 30,021 |
| lease_002 | docx | 221/221 | 0/0 | no | 37,525 |
| om_001 | pdf | 199/199 | 1/1 | no | 20,384 |
| t12_001 | xlsx | 148/148 | 0/0 | no | 26,863 |
| rentroll_001 | xlsx | 811/3073 | 0/0 | **yes** | 67,953 |

Every doc is under 90k. lease_001's baseline sends only 8 of its 25 page images. That is the
reason for B1 and B2.

## Part A: measuring harness (built; runs in Session 2)

- **Runner (P4-07):** `scripts/spikes/p4_launch.py <b1|b2|b3|b4> --max-usd X [--no-cache] [-- spike args]`. On the host it runs, in order:
  1. Clean tree.
  2. Dry run of the spike's documents.
  3. Total cap: the spend of earlier paid spike runs plus this run's cap must be ≤ `--total-cap 0.30`, and the run's cap is cut to fit.
  4. Run id `<sha>-<spike>-<utc>`, plus a `launch.json` with the gate results.
  5. `docker compose -f compose.yaml -f compose.dev.yaml run --rm worker python scripts/spikes/p4_<x>.py …`

  Mounts: `scripts/` (ro), the DEV documents folder (ro), `sample/schemas` and `sample/manifest.csv` (ro), and `cache/spikes/` (rw). The answers folder is never mounted (tested). The real `LLMClient` from env does the calls, so the fuses, the ledger, the dev budget and the reasoning settings all apply. `--no-cache` passes `-e LLM_CACHE_DIR=` and also drops the cache in-process.
- **Spike scripts:** each has `--max-usd`, `--dry-run` and `--no-cache`. A paid run refuses outside the container or without the launcher's `--run-id`.
  - `p4_b1.py`: batches of ≤ 8 pages, the baseline prompt per batch, merge by code.
  - `p4_b2.py`: methods a / b / c.
  - `p4_ocr.py`: RapidOCR on the host via `uv run --with rapidocr-onnxruntime`; never added to pyproject, `uv.lock` or the image.
  - `p4_b3.py`: the baseline unchanged, ×3. It refuses a paid run without `--no-cache`.
  - `p4_b4.py`: one call vs 3 field groups.
- **Merge rule (B1, B2a):** a non-null value wins. Equal values keep the highest confidence. Two different non-null values keep the one whose citation names a `[Page N]` that was in its own batch, if exactly one value has that. Otherwise the field is null and a conflict is recorded (by field name). Table schemas merge rows by the row key.
- **Byproducts (P4-12), one `calls.jsonl` line per call:**
  - Model requested and returned, model mismatch, JSON mode sent, a repair call used, and the reasoning parameter sent.
  - Tokens in, out, reasoning and cached; images; an image-tokens-per-image estimate taken from usage.
  - Latency, $ reported vs $ computed, cache hit, and skips (cap or token limit).
- **Caps:** before every live call the wrapper projects the cost (fuse input estimate + ≤ 3,000 output tokens). If spend plus that projection is over `--max-usd`, the run stops and the partial result is reported. A request estimated at ≥ 90k tokens is skipped (R22).
- **Scoring (host):** `uv run python scripts/spikes/p4_score.py --run <run_id> …` scores with `eval_dev.score_doc`, which uses `tools/validate.py`'s `score()`. It prints one line per prediction, plus mean / min / max / spread for repeats. It appends to `eval/spikes.jsonl` (P4-15, new file) with field names and numbers only.

## Spikes: estimated calls, tokens, $ (from the free dry runs) and proposed caps

"Fuse" uses the config's high-side estimate (2,600 tokens per image + 15%). "Realistic" uses
rough per-provider image rules (Anthropic about w×h/750, capped near 1,600; Gemini 1,120;
OpenAI tiles; 28-px patches for Qwen/GLM). Output is a plan-only guess: about 60 tokens per
field, plus about 1,500 reasoning tokens for GLM and Gemini. Real numbers come from usage in
Session 2.

| Spike | Calls | Images | Est. input tokens (fuse) | Est. $ fuse / realistic | Proposed cap |
|---|---|---|---|---|---|
| **Pilot**: B1, Haiku, first batch of 8 pages | 1 | 8 | 29,989 | 0.0042 / 0.0031 | **$0.01** |
| B1: lease_001, 25 pages = 4 batches × 5 models | 20 | 125 | 494,020 | 0.2236 / 0.1713 | ~~$0.18~~ **$0.22** (8 Nov) |
| ↳ Haiku 5.5 | 4 | 25 | 98,804 | 0.0147 / 0.0112 | |
| ↳ GPT-6 Luna | 4 | 25 | 98,804 | 0.0147 / 0.0100 | |
| ↳ GLM-5.3 Flash | 4 | 25 | 98,804 | 0.0226 / 0.0189 | |
| ↳ Qwen3-VL | 4 | 25 | 98,804 | 0.0390 / 0.0337 | |
| ↳ Gemini 3.8 Flash | 4 | 25 | 98,804 | 0.1326 / 0.0975 | |
| B2 (a) batches: same calls as B1-Haiku | 4 | 25 | 98,804 | 0.0147 / 0.0112 | **reuse B1-Haiku** |
| B2 (b) locate: 4 thumbnail calls + 1 read call | 5 | 25 thumbnails + 8 | 125,512 | 0.0144 / 0.0063 | |
| B2 (c) OCR text → Haiku (placeholder text size) | 1 | 0 | 32,924 | 0.0045 / 0.0045 | |
| B2 (b + c) | 6 | 33 | 158,436 | 0.0188 / 0.0108 | **$0.02** |
| B3: 3 repeats × om_001 / lease_002 / rentroll_001 (20,384 / 37,525 / 67,953 tokens per call) | 9 | 3 | 377,586 | 0.0455 / 0.0451 | **$0.05** |
| B4: lease_002 one / grouped; om_001 one / grouped | 8 | 4 | 217,380 | 0.0259 / 0.0253 | **$0.03** |
| **Total (pilot + B1 + B2 b,c + B3 + B4)** | 44 | | 1,277,411 | **0.318 / 0.256** | **$0.33 of $0.35** (8 Nov) |

Proposed run order in Session 2:

1. Pilot, then STOP with a projection and wait for your yes.
2. B3.
3. B4.
4. B2 (b, c).
5. B1, with Gemini as its last model. If the total cap cuts Gemini short, the partial result is reported.

Then score each run on the host and write the `logs/P4_report.md` FINAL STOP.

## Anything unclear (needs your call)

1. **Budget:** the fuse estimate (0.318) is over $0.30, and the realistic one (0.256) is under. B1 is about 2× the P4-08 guess of ≈ $0.06–0.10, and Gemini alone is about $0.10–0.13. Choose one:
   - (a) Keep $0.30, reuse B1-Haiku as B2(a), and run Gemini last under the caps above. **Recommended.**
   - (b) Raise the total cap to $0.35.
   - (c) Run Gemini on 2 of the 4 batches only.
2. **Guard scope:** the path-token rule now applies to `cache/` only. `.env*`, the answer folder and the held-out ids stay blocked on any mention, which is stricter. Please confirm that this is what "the other secret paths" meant.
3. **The dry run stops before the per-doc fuse.** `fit_to_doc_budget` needs the DB ledger, so the dry run reproduces read → prompt build → fuse estimate only. DB and gateway failures are not caught by it.
4. **The clean-tree gate counts untracked files** (`git status --porcelain`). An eval run writes `eval/history.jsonl` and a report, so the tree is dirty after every run until you commit. Spike runs write only to the git-ignored cache plus `eval/spikes.jsonl` at scoring time.
5. **Extra read-only mounts:** `sample/schemas` and `sample/manifest.csv` are mounted beside the three listed mounts, because the container needs the field lists. The dev overlay already mounts the whole cache folder, and the spikes write to the explicit `/spikes` mount.
6. **B2(c)** is estimated with invented filler text (2,500 characters per page), because OCR is not run in Session 1. RapidOCR is installed into uv's tool cache (its default location) in Session 2. If the install fails, (c) is reported as not run (P4-09).
7. **B2(b):** R13 limits a call to ≤ 8 images, so the locate pass needs 4 thumbnail calls (512 px long side, sent with `detail: low`) plus 1 read call. Pages are chosen by votes across fields, at most 8.
8. **"Citation found on its page"** is read as: the citation's `[Page N]` is one of the pages that batch was shown.
9. **B3 and B4's one-call variant** use a fresh job id, so the shipped per-doc $ fuse applies exactly as in the worker. rentroll_001 and lease_001 are truncated by the shipped baseline, and B3 measures that behaviour unchanged.

## SELF-AUDIT

- No LLM call. No `.env`, answers, held-out documents or cache contents were read with agent tools. Commands never named the cache folder; scripts wrote there.
- No sample value appears in any file, test or message. Only doc ids, field and page counts, tokens and $ are used. All tests use invented data.
- No dependency was added. Pillow was already present through the reader stack, and RapidOCR is temporary in Session 2 only.
- Frozen files were not touched. No commit or push. The fresh-clone script was not run.
- Deviation: `ruff format` reformatted one new file (`scripts/spikes/p4_common.py`); only layout changed.
