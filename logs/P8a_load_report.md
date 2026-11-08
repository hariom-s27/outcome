# P8a S1 report: load + chaos test with a fake LLM ($0)

## PLAIN SUMMARY

- **What ran:** 4 scenarios (6 runs, 110 jobs) on a separate throwaway stack. It used project
  `loadtest`, api on :18080, a fake key and a fake LLM container. Every command passed
  `-p loadtest --env-file tests/load/loadtest.env`. The main `docextract` stack kept running
  and was never touched.
- **Result: every pass criterion met in every run.**
  - 110 / 110 jobs terminal. 0 lost, 0 duplicates, 100 % VALID, all `SUCCESS`.
  - Max job time 77.6 s (limit 1800 s). Max POST time 0.297 s (limit 2 s). 0 × 5xx.
- **Chaos (L2):** SIGKILL hit the worker that held a lease. The killed job was re-claimed
  (2 claims), finished `SUCCESS` and was terminal exactly once, 66.4 s after the kill. That is
  the 60 s lease plus the 5 s sweep, as designed.
- **Scaling (L3):** 11.3 → 23.4 → 30.7 jobs/min for 1 → 2 → 3 workers. p95 dropped from
  65.2 s to 28.7 s to 24.7 s.
- **No fixes were needed (A-7).** No queue, worker or API code changed. No extraction logic
  changed.
- **Caveat:** the fake LLM answers in 1–6 s. With real models a job takes longer, so these
  times measure our queue and service, not real model latency (A-4; P8b adds real p50).

## What was built

| File | What |
|---|---|
| `app/devtools/fake_llm.py` | P2 fake server, extended (A-4). It adds a seeded uniform latency (`--latency-min/--latency-max`) and `--retry-after`. `--field-aware` reads the field keys and row key from the baseline prompt and returns one entry (or 2–6 rows with distinct row keys) of invented values, typed from the key wording, with 15 % nulls. Access log off; headers and bodies never logged. The old defaults are unchanged (P2 test still passes) |
| `compose.loadtest.yaml` | `fakellm` service (1–6 s, 8 % 429 with `Retry-After: 2`, seed 8). api `ports: !override` → 18080 only. Own image tag `docextract-loadtest:local`, so the main stack's `docextract:local` is not rebuilt. Worker `LLM_BASE_URL=http://fakellm:9999/v1`, `LLM_API_KEY=${LOADTEST_LLM_API_KEY:?}`. No dev budget, no cache |
| `tests/load/loadtest.env` | fake values only (`LOADTEST_LLM_API_KEY=fake-key-not-real`, `APP_VERSION=loadtest`) |
| `tests/load/compose.small.yaml` | L4: worker `cpus: 2`, `mem_limit: 3g` |
| `scripts/load_test.py` | L1–L4 runner. Refuses held-out ids (imports `HELD_OUT` from `eval_dev`). Refuses to run unless the worker start line shows `single_value_path=baseline, cache_mode=off`. Writes `eval/load.jsonl`, `logs/P8a_load_jobs.jsonl`, `logs/P8a_load_tables.md`. Always `down -v` at the end |
| `tests/test_load_harness.py` | 25 tests: prompt parse, reply passes `baseline.check_answer` + the frozen contract check, row keys, value types, seeding, 429 + Retry-After, latency range, 429 share, percentile, throughput, VALID check, lost/dup maths, criteria, held-out refusal, isolation constants, fake-only env file |

**Start-line check (after `up`, filtered on "started"):**
`started (pipeline=baseline-v1, single_value_path=baseline, cache_mode=off)`. The script
checked the same line on every stack (re)start: 6 / 6 showed `baseline` and `off`.

## Method

- **Clients:** 10 in flight (thread pool). Each does POST /jobs (file + field list), then GET
  every 2 s until terminal. A POST 429 is retried after its `Retry-After`.
- **Docs:** the 6 DEV docs (boxscore_001, lease_001, lease_002, om_001, t12_001,
  rentroll_001), cycled to 20 jobs (4/4/3/3/3/3). L2 uses 10 jobs.
- **Time:** submit → terminal on the client clock, from POST start to the first poll that sees
  a terminal status, so ±2 s. Percentiles use linear interpolation. Throughput = terminal jobs
  × 60 / (batch start → last terminal seen).
- **VALID:** the JobStatus shape (required keys, no extras, no `stage` once terminal), plus the
  result top level `{entries, metadata}`, plus the frozen `validate_contract`
  (`tools/validate.py`, via `app.contract_check`). A FAILED job counts as not VALID. No answer
  files were used.
- **Duplicates:** (a) jobs with more than 1 terminal row in `job_events` (DB query); (b) jobs
  whose GET body changed after it was first seen terminal (re-GET of every job after the run).
- **Slot time (A-8 / PR-65):** DB time from the last CLAIMED event to the terminal event.
- **Stack per scenario:** L1 has 1 worker (shipped default). L2 has 2. L3 has 1 / 2 / 3
  (`--scale`). L4 has 1 worker with the small profile.

## Results (source: `eval/load.jsonl`, 6 lines; per job: `logs/P8a_load_jobs.jsonl`, 110 lines)

| Scenario | Workers | n | Terminal | Lost | Dup | VALID % | p50 s | p95 s | max s | jobs/min | POST max s | POST 429 | 5xx | slot > 60 s | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | 1 | 20 | 20 | 0 | 0 | 100.0 | 52.15 | 63.95 | 65.47 | 11.04 | 0.297 | 0 | 0 | 0 | PASS |
| L2 | 2 | 10 | 10 | 0 | 0 | 100.0 | 13.44 | 53.74 | 77.55 | 7.74 | 0.234 | 0 | 0 | 0 | PASS |
| L3 | 1 | 20 | 20 | 0 | 0 | 100.0 | 52.98 | 65.22 | 65.45 | 11.29 | 0.235 | 0 | 0 | 0 | PASS |
| L3 | 2 | 20 | 20 | 0 | 0 | 100.0 | 23.59 | 28.74 | 30.66 | 23.39 | 0.218 | 0 | 0 | 0 | PASS |
| L3 | 3 | 20 | 20 | 0 | 0 | 100.0 | 16.63 | 24.65 | 24.75 | 30.65 | 0.282 | 0 | 0 | 0 | PASS |
| L4 | 1 | 20 | 20 | 0 | 0 | 100.0 | 46.11 | 55.3 | 55.36 | 12.46 | 0.235 | 0 | 0 | 0 | PASS |

- Statuses: `SUCCESS` for all 110 jobs.
- Worker slot time (claim → terminal): max 9.9 s (L1), 6.3 s (L2), 12.6 / 10.6 / 11.2 s (L3),
  11.7 s (L4). So with 1 worker, most of the 50–65 s is queue wait behind 10 in-flight jobs,
  not processing.
- L4 (2 CPUs, 3 GB) was not slower than L1 (12.5 vs 11.0 jobs/min). The CPU work per job is
  small next to the 1–6 s fake model wait.

### Per doc (submit → terminal s; full table in `logs/P8a_load_tables.md`)

| Doc | Kind | L1 p50 / p95 (1 w) | L3 p50 / p95 (2 w) | L3 p50 / p95 (3 w) | L4 p50 / p95 |
|---|---|---|---|---|---|
| boxscore_001 | csv | 36.91 / 60.29 | 17.43 / 29.74 | 10.26 / 16.35 | 30.77 / 51.84 |
| lease_001 | pdf (scan) | 50.13 / 62.07 | 21.59 / 28.33 | 17.49 / 20.37 | 37.96 / 51.28 |
| lease_002 | docx | 30.72 / 60.56 | 12.39 / 23.40 | 12.50 / 21.44 | 24.72 / 46.59 |
| om_001 | pdf | 59.34 / 61.52 | 24.70 / 28.22 | 24.56 / 24.73 | 55.30 / 55.35 |
| rentroll_001 | xlsx | 53.06 / 64.23 | 26.58 / 28.36 | 22.48 / 24.43 | 53.36 / 55.07 |
| t12_001 | xlsx | 55.50 / 63.02 | 22.48 / 26.17 | 18.42 / 20.31 | 51.23 / 54.78 |

n per doc per run = 3–4 (L1, L3, L4), so per-doc p95 is close to the max.

### L2 chaos detail

- About 10 s into the batch, the script found the worker container holding a RUNNING job's
  lease (`jobs.lease_owner`). It sent `docker kill --signal KILL`, waited 3 s and ran
  `docker start` on the container.
- Killed job: 2 claims, 1 terminal event, `SUCCESS`, seen terminal 66.4 s after the kill
  (lease 60 s + sweep ≤ 5 s + poll ≤ 2 s). That is the L2 max of 77.6 s (rentroll_001).
- 1 re-claimed job in the batch (the victim). The other 9 jobs were not disturbed.
- The L2 throughput (7.7 jobs/min) is low only because the run waits out the 60 s lease. It
  is not a scaling number.

## Pass / fail per criterion (A-6)

| Criterion | L1 | L2 | L3 ×3 | L4 |
|---|---|---|---|---|
| 100 % terminal | pass | pass | pass | pass |
| 0 lost | pass | pass | pass | pass |
| 0 duplicates (DB terminal rows + re-GET) | pass | pass | pass | pass |
| ≥ 80 % VALID (target 100 %) | 100 % | 100 % | 100 % | 100 % |
| every job < 1800 s | 65.5 s | 77.6 s | ≤ 65.5 s | 55.4 s |
| POST < 2 s | 0.297 s | 0.234 s | ≤ 0.282 s | 0.235 s |
| no 5xx | pass | pass | pass | pass |
| POST 429s carry Retry-After | n/a (0 × 429) | n/a | n/a | n/a |
| killed job re-claimed, terminal once | — | pass | — | — |
| throughput 1 → 2 workers rises | — | — | 11.29 → 23.39 pass | — |

**What broke:** nothing. No A-7 fix was made.

## PR-65 (A-8)

No job held a worker slot longer than 60 s (max 12.6 s over 110 jobs). No parse step blocked a
worker on the DEV docs. This is measure-only, as approved: no killable child process was
built. A hostile or very large file is still covered only by the job deadline (→ PARTIAL).
That belongs in the DESIGN limitations.

## SELF-AUDIT

1. **Steps:**
   - Read the listed files. Extended the fake LLM. Added the overlay, the fake env file and the
     small profile. Wrote the load script and 25 tests.
   - Confirmed the start line, ran L1–L4 (one run, exit 0), then `down -v`.
   - Ran ruff, pytest and pre-commit; validated outputs.
   - Evidence: the tables above, `eval/load.jsonl`, `logs/P8a_load_jobs.jsonl`,
     `logs/P8a_load_tables.md`.
2. **Decisions not in the prompt:**
   - **Own image tag** `docextract-loadtest:local` for api, worker and fakellm, so the load
     build never retags the main stack's image.
   - **Fake key under its own name** (`LOADTEST_LLM_API_KEY`), so a shell `LLM_API_KEY` can
     never reach the load stack.
   - **`ports: !override`**, because Compose would otherwise add 18080 next to 8080 and clash
     with the main stack.
   - **The fake LLM runs from the same image** (`python -m app.devtools.fake_llm`), so no new
     dependency is needed.
   - **The VALID check** uses the frozen `validate_contract` plus a hand-written JobStatus /
     top-level check. `jsonschema` is not installed and was not added (rule 10).
   - **L2 uses 2 workers**, so the survivor keeps working during the kill. The killed
     container is restarted with `docker start` after 3 s.
   - **The script also refuses to run** if the start line is not `baseline` / `off` (a second
     guard on Hariom's check).
3. **Deviations:**
   - **The config check was skipped** (guard block; Hariom: skip, do not re-run). It was
     replaced by the start-line check.
   - **L4 `mem_limit` is 3g, not 4g** (Hariom, inside A-5). The Docker VM has 4 CPUs and
     ~3.8 GB (`docker info`), so 4g would never bite.
   - **20 jobs instead of "2 rounds".** The prompt says "2 rounds over the 6 DEV docs
     (20 jobs)", but 2 × 6 = 12. I kept the 20 jobs and cycled the docs (4/4/3/3/3/3).
   - **The runs used a dirty tree.** The image was built from the working tree (`6f2da24` plus
     these uncommitted harness files), so `git_sha` is recorded as `6f2da24-dirty`. No service
     code under `app/` changed except `app/devtools/fake_llm.py`.
4. **Numbers:** every number is from `eval/load.jsonl` (6 lines; n per line 20 or 10) or
   `logs/P8a_load_jobs.jsonl` (110 lines), both written by `scripts/load_test.py`. The VM size
   is from `docker info`.
5. **Tests:** 445 before → **470** after (25 new in `tests/test_load_harness.py`; 0 failed).
   - `uv run pytest -q`: `470 passed, 1 warning, 95 subtests passed in 48.01s`.
   - No network, no key.
6. **Frozen and outputs:** `contract/`, `tools/validate.py` and `ASSIGNMENT.md` are untouched
   (pre-commit "given files unchanged" Passed). `outputs/` is unchanged:
   `tools/validate.py outputs/ --schema-dir sample/schemas` exit 0, 8 files.
7. **Held-out seal:** lease_003 and budget_001 were not opened, sent or scored. The script
   refuses them (tested).
8. **Safety:**
   - every load-stack command used `-p loadtest --env-file tests/load/loadtest.env` (the script
     hard-codes the prefix; tested)
   - the real key never entered the load stack
   - `.env` was not opened
   - the main `docextract` stack kept running throughout and was not stopped, rebuilt or changed
     (`docker compose ls` before and after)
   - `down -v` done: no loadtest containers or volumes remain
   - no commits
   - 1 guard block, reported and not retried (see open items)
9. **Spend:** $0. No real LLM calls (the fake server reports cost 0). RUNNING TOTAL is
   unchanged at **$0.480041**.
10. **Open items for P6 lean+ / P8b:**
    - **Guard false positive:** a read-only `docker compose -p loadtest --env-file … -f … config`
      piped into `grep -nE "<pattern list>"` was blocked as "touches cache/". The grep pattern
      list contained the word `CACHE` (no path into `cache/`). It was not re-run in any form
      (Hariom). A possible guard fix is to treat the bare word, without a `/`, as allowed.
      Hariom decides; `.claude/` was not edited.
    - **Fake-LLM 429s not counted.** The fake server's ~8 % 429s were absorbed by the client
      retries (all 110 jobs SUCCESS). The worker logs were removed by `down -v` before I
      counted them, so the share was not measured in the run. The 8 % rate is covered by a unit
      test (500 calls, 4–12 %). A rerun could count `http_429` in the ledger first.
    - **POST 429** (queue full, `MAX_PENDING` 500) was never reached at 10 in flight, so the
      Retry-After criterion is n/a here. It is covered by the existing API tests.
    - **Real latency:** P8b should note the real-model p50 / p95. With 1 worker and real calls of
      ~10–30 s, queue wait grows in proportion. 20 jobs should still stay far below 1800 s.
    - **PR-65:** not seen. Add a DESIGN limitation (deadline is the only bound on a stuck parse).
