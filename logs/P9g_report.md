# P9g report: t12 retry fix (lenient keys + E0 retry feedback), stopped before the live test

Branch `lab`. Decisions Z-61..Z-64 approved by Hariom. Part 0 and Part A done. Part B stopped after
one run: the LLM key is dead (HTTP 401), and Hariom ended P9g with no more runs (deadline).

## PLAIN SUMMARY

- **What was built:** a switch `SPEC_RETRY_FEEDBACK` (default **off**) with two changes on the
  table spec path:
  1. **Lenient keys:** an unknown extra key inside an otherwise valid recipe entry is ignored
     and counted, so the entry is kept. Required keys and value checks are unchanged.
  2. **Feedback retry:** when E0 retries the recipe, the prompt says what code rejected: the
     entry, the reason and the key names, the allowed keys, and the unfilled field names when
     fill < 0.5.
- **Tests:** unit-tested with invented specs (776 tests pass, ruff and pre-commit clean, dry runs
  pass). **Not validated live.**
- **Live test:** one run was made (175). The gateway refused the call (HTTP 401), so it is
  **excluded: http_401** and is not a test. The Z-62 gate was **not run**.
- **Decision:** `SPEC_RETRY_FEEDBACK` stays **OFF** by default. The code ships switched off;
  default off reproduces the current lab behaviour (shipped-config test).
- **Open risk:** the t12 residual collapse risk (2 of 7 jobs in P9c) remains in the shipped default.
- **Spend:** $0.

## Part 0: facts ($0)

- **Target jobs not read.** The t12 job ids for runs 157, 161, 164 and 165 exist only in:
  - worker logs, lost when the worker restarted before this session
  - the raw run folders under `cache/`, never read
  - the database, not queried (metadata via the API only)

  The API has no list endpoint. Hariom said not to chase the old ids.
- **No key names were stored.** `ask_spec` kept only the text before the first `:` of each drop
  error. An entry error would show as kind `row_fields.<field>`.
- **Top-level key, not an entry.** The kind recorded for t12 (P9b, run 103: 1 drop, fill 2/7)
  was `unknown keys`. Only the top-level check makes that kind. That check does not drop a whole
  entry: it ignores the unknown top-level key, and everything inside that key is lost.
- **Likely cause (INFERENCE, not confirmed for runs 157/164):** fill 2/7 fits most field rules
  being placed under a wrong top-level key.
- **Fix 1 alone would most likely not have kept those entries.** Fix 1 covers keys inside
  entries; top-level keys were already ignored. For t12 the feedback retry is the mechanism
  expected to matter.

## Part A: build ($0)

| File | Change |
|---|---|
| `app/tables/spec.py` | `salvage_spec(..., report=)`: lenient entry keys. Covers a `row_fields` rule, its `except_label`, `pick_by_label`, `derived` and `map_distinct` objects, and a `doc_fields` ref. An ignored key is counted only when its entry is kept. Top-level handling unchanged. `validate_spec` (heuristic) stays strict. |
| `app/pipeline/table_spec.py` | `ask_spec(notes=, feedback=)`, `feedback_block`, `_e0_retry` and the switch passed through `_spec_path`, `_grid_path`, `extract_grid`, `extract`. Keep-the-higher-fill rule unchanged. |
| `app/config.py`, `app/worker.py`, `compose.yaml` | `spec_retry_feedback` default False; `feedback` kwarg only when on; start line `spec_retry_feedback=`; compose `${SPEC_RETRY_FEEDBACK:-0}`. |
| `tests/test_p9g_feedback.py`, `tests/test_shipped_config.py` | Covers: extra key kept; missing required key and bad values still dropped; feedback carries key names, allowed keys and unfilled fields; off = unchanged (the retry prompt equals today's); no values or model-made keys in metadata or logs; switch default off; worker wiring. |

**Metadata (counts and safe names only).** `ai_spec` and `retry` carry:
- `unknown_keys_ignored`
- `unknown_key_names`
- `unknown_top_keys`

Key names appear only when they are grammar words or field keys; any other name shows as
`"other"`. `e0.feedback` holds counts: `{problems, ignored, top_unknown, unfilled}`. The
validator's messages go only into the retry prompt.

**Verify:**
- ruff check: clean. ruff format: clean.
- pytest: 776 passed, 95 subtests.
- pre-commit: 7/7 hooks passed, on all files and on the new test file.
- Dry runs: `--set dev` PASSED (6 docs), `--set syn` PASSED (8 docs).

Committed as 1d3c9ae, 6921ba0, a544d9f.

## Part B: live test (stopped)

The stack was restarted with `SPEC_RETRY_FEEDBACK=1`. The worker start line read `cache_mode=off,
lab_mode=on, e0_robust=on, pdf_table=grid, table_cleanup=on, spec_retry_feedback=on`.

| run | job | score | calls | result | status |
|---|---|---|---|---|---|
| 175 | 935362ee | 0.077 | 1 (refused, 0 tokens, $0) | `ai_spec.llm_status=failed`; worker log `status=http_401`; heuristic recipe chosen (fill 0.0); no E0 (model failed), no feedback | **excluded: http_401** (not a test) |

- Run 175's history line (`eval/history.jsonl`) and `logs/P9g_eval_t12_175.md` are kept as a
  record. They must not be counted in any score.
- **Z-62: not run.** None of the 8 counted runs and no full-set run.
- **Z-63: not applied.** The default stays off.

## Decision

`SPEC_RETRY_FEEDBACK` stays **OFF** by default (lab and ship). It is built and unit-tested, but not
validated live. It can be turned on later with `SPEC_RETRY_FEEDBACK=1` only after the Z-62 gate
passes on a working key.

## Where it fails

- **t12 residual collapse risk remains in the shipped default.**
  - In P9c, 2 of 7 t12 jobs (runs 157, 164) collapsed to about 0.08–0.09.
  - In both, a dropped recipe entry gave fill 0.2857, and E0's plain retry repeated the mistake.
  - The fix that targets this is switched off.
- Part 0's cause (a top-level unknown key) is an inference from code and the P9b record, not
  confirmed for runs 157/164.

## Spend

| item | $ |
|---|---|
| P9g (run 175: refused, 0 tokens) | 0.000000 |
| project running total | **1.122552** (unchanged) |
| lab running total | **≈ 0.5557** (unchanged, cap $3) |

## Deviations

- **Part 0:** the target jobs' metadata was not read (ids unavailable within the rules).
- **Part B:** stopped after one excluded run (dead key); Hariom ended P9g.

## SELF-AUDIT

- [x] Default off reproduces the current lab behaviour. The shipped-config test checks the
  default, and the off test checks the unchanged retry prompt and metadata.
- [x] Required-key and value checks unchanged; only unknown extra keys inside entries are ignored.
- [x] Feedback holds key names and reason codes only, in the prompt. Metadata and logs carry
  counts and safe names only (test).
- [x] No `cache/` reads; no held-out run; no `.env` read.
- [ ] Gate as pre-registered: **not run** (dead key).
- [x] Spend within cap ($0 of $0.06). Running totals reported.
