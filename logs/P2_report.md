# P2 report: LLM wrapper, rough readers, one-prompt baseline, first DEV numbers

## PLAIN SUMMARY

The service now extracts something real. With a key, the worker reads the file (CSV, XLSX,
DOCX or PDF; scanned PDF pages go in as images), sends **one** request to Claude Haiku 5.5 with
all fields, checks the JSON in code and returns it. Without a key it still runs and returns the
all-null skeleton, as in P1.

DEV score: **0.599 mean over the 6 DEV documents** (validate.py `score()`), all 8 outputs
VALID. Documents with one value per field score 0.70 to 1.00; the two big tables score
0.05 and 0.11 because the model returns tens of rows instead of hundreds. That is the
expected baseline gap (P2-16), and it is what P5/P6 are for.

Cost: **running total $0.108** (10 paid calls; P1 and Session 1 were $0). **≈ $0.0055 per
document uncached**, i.e. what a grader with no dev cache pays. In the first eval one request
cost $0.064 alone: my input-size estimate undercounted spreadsheet rows about 1.9×, so the
rent-roll request crossed Haiku's 100k-token price cliff (5× price). After your go-ahead
(P2-34/35/36, 7 Nov):

- the estimate is calibrated per block type, and a second, high-side estimate now runs before
  **every** LLM call. If it would take the document past `LLM_MAX_USD_PER_DOC` (the whole call
  priced at the cliff rate when the estimate reaches the cliff), the input is trimmed, or the
  call is skipped → PARTIAL `doc_llm_cap`;
- rentroll_001 was re-run: 57,118 real tokens (fuse estimate 79,469), **$0.0097**, score
  0.009 → **0.110**;
- the sample-values guard no longer treats `_` as a word boundary, so the 2 false positives in
  `logs/P2_eval.md` are gone; all pre-commit hooks pass.

Haiku reasoning: sending `effort: none` scored the same (1.000) on the pilot document as the
default, with 0 instead of 3,964 reasoning tokens and a lower cost. The baseline uses `none`.

## SELF-AUDIT

### Steps done

| Step | Status | Evidence |
|---|---|---|
| Plan + cost estimate printed (pilot ≈ $0.005, DEV ≈ $0.04–0.08, worst ~$0.10; < $0.20) | done | chat, start of session |
| Part 0: one retry wait = max(backoff, Retry-After, cool-down left) | done | `app/llm/client.py` `chat()`; tests `test_429_retry_after_is_waited_once_not_twice`, `test_429_without_retry_after_waits_the_longer_of_backoff_and_cooldown`, `test_other_callers_still_honour_the_shared_cooldown` |
| Part 0: half-open breaker, one probe claimed in Postgres | done | `llm_state.probe_until`, `LLMStore.try_claim_probe`, `_wait_shared`; tests `test_only_one_caller_can_claim_the_probe`, `test_probe_success_closes_the_breaker`, `test_probe_failure_reopens_for_another_pause`, `test_others_wait_while_the_probe_is_out`, `test_crashed_probers_lease_frees_the_probe`, `test_after_the_pause_exactly_one_probe_then_everyone_goes` |
| Part 0: per-model reasoning default/none, snapshot-gated, 400 → one retry without + ledger flag | done | `config/models.yaml`, `ModelSpec.reasoning_param`, `llm_calls.reasoning_param_dropped`; tests `test_reasoning_none_sent_only_where_configured`, `test_400_to_reasoning_param_retries_once_without_it`, `test_second_400_without_reasoning_fails`, `test_none_needs_the_snapshot_to_allow_it` (4 cases) |
| Readers for CSV / XLSX / DOCX / PDF (image-only page → grayscale JPEG, 1600 px) | done | `app/readers/`; `tests/test_readers.py` (10 tests, invented generated fixtures incl. a hand-built 2-page PDF with one image-only page) |
| Baseline extractor, caps, code checks, contract check | done | `app/pipeline/baseline.py`, `app/contract_check.py`; `tests/test_baseline.py` (21 tests: good / partial / junk JSON, caps, LLM-trouble reasons) |
| Worker: baseline with key, stub without | done | `app/worker.py`; tests `test_worker_with_key_runs_baseline_to_success`, `test_worker_with_unusable_answer_is_partial_skeleton`, `test_worker_without_key_keeps_the_stub`; live no-key start below |
| Pilot boxscore_001 ×2 (default vs none), cap $0.03 each | done | numbers below |
| `scripts/eval_dev.py` (HTTP only, --max-usd, held-out refused, taxonomy, abort after 2 LLM failures) | done | `tests/test_eval_dev.py` (4 tests incl. held-out refusal with no HTTP) |
| Full DEV eval, --max-usd 0.15 | done | `logs/P2_eval.md`, `eval/history.jsonl` (1 line) |
| 6 DEV outputs regenerated; held-out stay P1 stubs | done | `git diff --stat`: only the 6 DEV files under `outputs/` changed |
| VALID: batch exit 0 + single-file VALID | done | `batch exit=0`; `VALID` for all 8 files (6 DEV + 2 stubs) |
| README scores table + DESIGN lines | done | `README.md` §Scores, `DESIGN.md` decisions / spend / what broke |
| This report | done | |

### Decisions I made that the prompt did not specify

| What | Why | Alternative |
|---|---|---|
| `LLM_REASONING_OVERRIDE` env (dev overlay only) to switch reasoning for the pilot | the pilot must use HTTP only (P2-32); the setting lives in the image's YAML | rebuild the image with an edited YAML between runs |
| Half-open probe claim keyed on the `breaker_open_until` value the caller waited out, not on the DB clock | one probe per pause, robust to clock skew, testable with a fake clock | `breaker_open_until < now()` condition (untestable with fake sleep) |
| A 400 answered to the reasoning param uses no attempt and no breaker count | it is a parameter problem, not an outage | count it like any 4xx |
| When a call trips the breaker, skip that call's backoff (the 60 s pause replaces it) | avoids backoff + pause back to back | keep both |
| `tools/validate.py` copied unchanged into the image; results checked with its `validate_contract` | the service checks itself with the graders' code | re-implement the check |
| Currency-formatted strings ("$1,250") converted to numbers in code | they make the output INVALID; the conversion is exact, not a guess | null them |
| Table rows without a primary value dropped; duplicate keys dropped (first kept) | validate.py ignores later duplicates anyway; keyless rows can only score as extras | keep them |
| Reader errors → PARTIAL skeleton `read_failed` (not retry/poison) | a broken file will not read better on retry | release and let the poison cap end it |
| Unusable/stopped results carry the ledger metadata (calls, tokens, cost), not zeros | spend must be visible | P1 stub zeros |
| Metadata extras: `pipeline`, `input_tokens_est`, truncation counts/pages, `images_sent`, `models_returned`, `reasoning_effort`, check counters | eval and debugging without reading content | none |
| Baseline output cap `max_tokens` 8192 (wrapper retries once at 16384) | bounded cost and HTTP time within the 120 s request timeout | 4096 default (truncates nearly every table) |
| Prompt rule "skip subtotal and total lines unless the descriptions ask" | generic table hygiene | none |
| One script for pilot and eval (`--no-record` for the pilot) | one scorer, one HTTP path | separate pilot script |
| New packages pinned exactly (`==`), like the existing ones | reproducible builds | ranges |
| Token estimate recalibrated after the run (rows 1.75, prose 2.6 chars/token) | measured 1.9× / 1.1–1.4× under-estimate | leave it, rely on the per-doc $ cap |

### Deviations from the prompt

- **Price cliff crossed once** (rentroll_001: 114,566 input tokens vs a 60k-token target). The
  per-doc $0.05 cap (P2-28) is checked before calls, so one call could exceed it ($0.064).
  The estimator was fixed and tested afterwards; the document was re-run after approval
  (addendum below).
- "Before" test count is copied from `logs/P2_session1_notes.md` (110 passed, 49 subtests);
  I did not re-run the suite at the start of Session 2.
- `eval/history.jsonl` lines carry the run's spend but not a project running total (P2-10
  asks for one). The running total is in this report and in DESIGN.md. The pilot runs used
  `--no-record`, so they are not in history.
- boxscore_001 in the DEV eval was answered from the dev cache (the reasoning=none pilot's
  replies, identical request). Its eval cost is $0; README $/doc uses its measured uncached
  cost ($0.00951). Because cache-hit ledger rows do not record `reasoning_effort`, the history
  line lists `["default", "none"]` although only `none` was sent.
- I briefly ran `git add -N` on new files for pre-commit, then `git reset -q -- <paths>` to
  leave the index as I found it. Nothing was committed.
- My Python patch scripts wrote CRLF on Windows; all changed files were normalised back to
  LF before the end.

### Numbers (source)

**Pilot, boxscore_001** (eval_dev.py output; `--no-record`):

| setting | calls | tokens in / out | reasoning tokens | cost reported / computed | latency | score | VALID |
|---|---|---|---|---|---|---|---|
| default | 2 (first hit `length` at 8192) | 6,134 / 20,328 | 3,964 | $0.01078 / $0.01078 | 61.3 s | 1.000 | yes |
| none | 2 (first hit `length` at 8192) | 6,132 / 17,789 | 0 | $0.00951 / $0.00951 | 51.2 s | 1.000 | yes |

Model returned: `anthropic/claude-haiku-5.5` (no mismatch). **Pick: none** (score not lower).
Projection for the other 5 DEV docs at that point: ≈ $0.071 worst case (3 single-entry docs
≤ $0.0075 each + 2 table docs ≤ $0.024 each at the 60k-token cap) → auto-continue. Actual:
$0.07794. It was higher on the rent roll because of the estimator bug.

**First DEV eval** (`eval/history.jsonl` line 1, run `455cb6d-dirty`; superseded for
rentroll_001 by the addendum re-run):

| doc | score | rows pred/truth | wrong / missed / halluc. | $ | latency s |
|---|---|---|---|---|---|
| boxscore_001 | 1.000 | 10/10 | 0/0/0 | 0 (cache) | 0.3 |
| lease_001 | 0.700 | 1/1 | 5/7/0 | 0.00306 | 15.4 |
| lease_002 | 0.775 | 1/1 | 8/0/1 | 0.00402 | 10.8 |
| om_001 | 0.966 | 1/1 | 1/0/0 | 0.00259 | 8.3 |
| t12_001 | 0.046 | 6/119 | 6/0/0 | 0.00394 | 12.3 |
| rentroll_001 | 0.009 | 3/325 | 1/0/0 | 0.06434 | 12.1 |

Mean **0.583** (n = 6) · total $0.07794 · $0.01299/doc as run, ≈ $0.0146/doc with boxscore at its
uncached cost · p50 latency 11.4 s · reasoning tokens 0.
Input-size estimate vs actual (`outputs/*.json` metadata): lease_001 19,926 / 19,106 (8 page
images; 17 pages dropped by the 8-image cap) · lease_002 24,621 / 27,641 · om_001 13,042 /
17,738 · t12_001 11,757 / 21,834 · rentroll_001 59,974 / 114,566 (1,345 rows dropped).

### Tests (copied from pytest output)

- Before (Session 1 notes): `110 passed, 49 subtests`.
- Now: `163 passed, 1 warning, 49 subtests passed in 28.07s`. Per file (collect-only):
  test_llm 64 (47 per Session 1 notes, +17), test_baseline 21 (new), test_readers 10 (new),
  test_eval_dev 4 (new) = +52. Total rose by 53 (163 − 110); I cannot place the remaining 1
  without Session 1's per-file list. One existing test changed (Haiku now sends `reasoning`).
- Network: conftest blocks every non-loopback socket and unsets `LLM_API_KEY`; LLM tests use
  `httpx.MockTransport` or a fake client object. No test touched the network.
- `uv run ruff check .` → All checks passed; `ruff format --check` → 57 files already formatted.

### Addendum (P2-34, P2-35, P2-36, uncached $; approved 7 Nov)

| Item | Status | Evidence |
|---|---|---|
| P2-34 guard: `_` added to both boundary classes | done | `scripts/guards/sample_values.py` (one-line diff); tests `test_answer_inside_a_field_key_is_not_flagged`, `test_answer_standing_alone_in_a_log_line_is_flagged`, `test_answer_inside_prose_is_flagged` (invented values); report text not touched; hook now Passed on `logs/P2_eval.md` |
| P2-36 fuse: high-side estimate before every call, cliff pricing, trim → skip, after-call check kept | done | `Estimate` in `app/llm/models.py` + `estimate:` in `config/models.yaml`; `LLMClient.projection()` and the pre-attempt check in `chat()`; `fit_to_doc_budget()` in `app/pipeline/baseline.py`; tests `test_fuse_*` (5 in test_llm, 3 in test_baseline); `test_per_doc_usd_cap` (after-call check) kept |
| `tokens_estimated` on every `llm_calls` row (paid and cache hit) | done | `app/schema.sql`; test `test_fuse_call_that_fits_goes_out_and_writes_the_estimate` |
| P2-35 rentroll_001 re-run through the service, `--max-usd 0.03` | done | eval_dev.py output; `outputs/rentroll_001.json` regenerated |
| Re-score with the other 5 saved results, new history line | done | `--reuse 455cb6d-dirty`; `eval/history.jsonl` line 2; `logs/P2_eval.md` regenerated |
| Uncached $ per doc (ledger cost of the call that filled the cache) | done | `llm_calls.cost_original` on cache-hit rows → metadata `cost_uncached_usd`; eval_dev `$ uncached` column, `usd_per_doc` = uncached (`usd_per_doc_paid` kept); tests `test_cache_hit_keeps_the_original_cost_for_the_uncached_figure`, `test_cache_hits_are_priced_uncached_for_dollars_per_doc`, `test_score_doc_reads_the_uncached_cost` |

Re-run numbers (eval_dev.py output; ledger via `psql` in the db container, numbers only):

| doc | score | rows pred/truth | calls | estimate (fuse) / baseline est. / real prompt tokens | out | $ paid | $ uncached |
|---|---|---|---|---|---|---|---|
| rentroll_001 (new) | 0.110 (was 0.009) | 36/325 | 1 | 79,469 / 59,965 / 57,118 | 7,986 (`stop`) | 0.00971 | 0.00971 |
| boxscore_001 (re-submit) | 1.000 | 10/10 | 0 (2 cache hits) | 4,505 / – / 3,066 per hit | – | 0 | 0.00951 |

New mean **0.599** (n = 6, was 0.583) · paid this eval $0.02331 · uncached $0.03281 ·
**$0.00547/doc uncached** · p50 11.5 s. The rent-roll input was still cut by the 60k-token
selection cap (2,183 of 3,073 row blocks dropped); the fuse itself did not need to trim.

Decisions in the addendum that the prompt did not fix:

- **chars_per_token 1.5, not 3.** The prompt said "about 1 token per 3 characters". The P2
  calls measured 1.75 chars/token for sheet rows and 2.6 for prose, so 3 would *under*count by
  up to ~1.7×. With 3, the rent-roll request that crossed the cliff (114,566 real tokens) would
  have been estimated at ≈ 77k, under the cliff, and passed the fuse. 1.5 is high side for
  both. It is one line in `config/models.yaml` (`estimate:`). Image tokens 2,600 per page image
  (≈ 1600×1236 / 750, rounded up); margin 15%.
- Trimming keeps the longest prefix of blocks that fits (binary search over the block count,
  each candidate re-priced with the same estimator); metadata gets `cost_fuse: trimmed |
  skipped`, `tokens_estimated`, and the existing `truncated` / `blocks_dropped` /
  `rows_dropped` / `pages_dropped` counts. Dev scripts without a job id have no per-doc cap.
- The fuse check also runs inside the wrapper before every attempt (retries, the 2×
  `max_tokens` retry, the repair call), not only in the baseline.
- boxscore_001 was **re-submitted** (not reused) once, so that its metadata carries
  `cost_uncached_usd` from the ledger; the saved result predates the field. It was a dev-cache
  hit: 0 paid calls, $0. This is a small deviation from "reuse the other 5".
- `test_per_doc_usd_cap` (Session 1) now uses a $0.01 cap instead of $0.001: at $0.001 the
  new fuse already refuses the first call (4,096 output tokens alone project $0.002), and the
  test is about the after-call check.
- Guard blocks this addendum: 2, both "may modify a frozen file" on commands that only
  *mention* the validator path (a read-only verify command with `2>&1`, and a patch script
  whose text named it). Neither wrote to it; per CLAUDE.md ("rephrase, don't bypass") I ran
  the checks as separate commands and made these report edits with the Edit tool.

Tests (copied from pytest output): `177 passed, 1 warning, 49 subtests passed in 25.58s`
(was 163; +14: guard 3, fuse 8, uncached 3). `ruff check` → All checks passed; `ruff format
--check` → 58 files already formatted. pre-commit `--all-files`: 7/7 Passed; `--files` on all
untracked + modified files: 7/7 Passed. Validator batch on `outputs/` → exit 0; single-file
`VALID` for all 8 (rentroll_001 now 36 entries). Held-out outputs unchanged (P1 stubs). Dev
stack stopped afterwards (`docker compose down`, volume kept).

**Running total spend: $0.107927** (ledger: reported = computed, 10 paid calls; this addendum
$0.009705, 1 paid call).

### Frozen items, outputs, compose

- `contract/`, `tools/validate.py`, `ASSIGNMENT.md`, `sample/` untouched (pre-commit "given
  files unchanged" Passed). `tools/validate.py` is only copied into the image.
- `outputs/`: batch `tools/validate.py outputs/ --schema-dir sample/schemas` exit 0; single-file
  `VALID` for all 8.
- Fresh `docker compose up -d --build` with the key blanked in the shell (plain compose.yaml):
  `/health` → `{"status":"ok"}`, worker log `LLM_API_KEY not set … pipeline=stub`, an invented
  CSV job → `PARTIAL`, `model_calls 0`. Stack stopped afterwards (`docker compose down`, volume kept).

### Held-out seal

lease_003 / budget_001: not opened, not run, not scored. Their `outputs/` files are the P1
stubs, unchanged. `eval_dev.py` refuses held-out ids without `--final-sealed`; I tested that
with the id taken from the script's own constant, because the guard blocks naming it in a
command (it did block my first attempt, as designed).

### Safety

No commit, no push. No key printed; `.env` not opened (compose reads it itself). Guard blocks hit
this session: 3, all by design (`cache/` in a shell command, a held-out id in a shell command
×2); each time I switched to Edit/Write or to a test, never a workaround. No sample values in
code, tests, logs or this report; pre-commit `--all-files` 7/7 Passed for tracked files, but
`--files` on the new files flags `logs/P2_eval.md` (false positive, see Risks).

### LLM calls (ledger `llm_calls`, dev DB)

- Paid calls: **9** (7 with `reasoning: none`, 2 default) + 2 dev-cache hits. Statuses: 7 `ok/stop`,
  2 `ok/length` (the two pilot first calls). No 429, no 5xx, no retries, no `reasoning_param_dropped`,
  no model mismatch. Returned model string: `anthropic/claude-haiku-5.5`.
- Tokens paid: in 213,151 / out 50,878. Reasoning tokens: default 3,964 (2 calls), none 0 (7 calls).
- Cost this phase: reported **$0.098223**, computed **$0.098223** (default $0.010777, none $0.087445).
- **Running total spend: $0.098** (P1 $0, Session 1 $0).

## Session 1 (merged from `logs/P2_session1_notes.md`)

Spend $0; one free `GET /models`. Built: `config/models.yaml` (9 ids, snapshot prices, vision,
`response_format`, price cliffs, baseline Haiku, fallback order); catalogue refusing unknown ids;
httpx wrapper (`/chat/completions`, always `max_tokens`, R1/R13 message check); retries 4 ×
1-2-4-8 s + jitter with Retry-After and job time left; Postgres ledger, in-flight slots, 429
cool-down, breaker; JSON ladder (json_object, local parse, one text-only repair, one 2×
`max_tokens` retry on truncation); per-doc caps 8 calls / $0.05, `DEV_BUDGET_USD`; dev disk
cache; fake gateway for P8; snapshot script. Tests then: 110 passed, 49 subtests. Snapshot:
all 9 ids present; Haiku reasoning not mandatory, default effort medium, `none` supported.
Two weaknesses listed there (double wait after a 429; every worker probing at once after a
breaker pause) are fixed in Part 0 above.

## Risks and open items for P3

1. ~~Sample-values guard false positive~~: fixed (P2-34, addendum).
2. ~~Price cliff / per-doc cap~~: pre-call fuse added and rentroll_001 re-run (P2-35/36,
   addendum). Open: the fuse estimate runs 1.39× high on sheet rows, which may trim inputs
   that would have fit; recalibrate when more calls are measured.
3. **Big tables** (t12 6/119 rows, rentroll 36/325): one prompt cannot list hundreds of rows.
   Table rows must be copied from cells by code (R11), which is the P5/P6 plan.
4. **Scanned lease** (lease_001): 17 of 25 pages dropped by the 8-image cap; 7 misses.
   Needs page selection or OCR (P3/P4).
5. **Output truncation on small tables**: a 10-row × 20-field answer needed ~9.6k output
   tokens, so the first call at 8,192 was wasted. Use more compact output or size `max_tokens`
   from the row count.
6. PDF parsing/rendering runs in the worker process (R20 timeouts/memory caps not yet); DOCX
   pages unknown (`[Page ?]`).
7. rentroll_001 used 7,986 of 8,192 output tokens for 36 rows: output size, not input, now
   limits the one-prompt table answer.
8. Cache-hit ledger rows do not record `reasoning_effort`; `eval/history.jsonl` has no running
   total column (P2-10).
