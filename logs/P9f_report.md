# P9f report — ship v1.1 without live LLM calls (gateway key expired), $0

Branch `main` = tag `v1.1` = `7032c28`. Decisions: Z-73..Z-80 approved; Z-81 (guard false
positive, patch through Edit/Write) and Z-82 (keep v1.0 outputs) were added during the run.
Doc ids, field names, counts, scores and $ only (D04, R31). **No LLM call was made in any part.**

## PLAIN SUMMARY

- **v1.1 ships the four changes that passed a live gate:**
  - E0 robust parsing
  - PDF table grid
  - table cleanup
  - all-page scans

  P9g (`SPEC_RETRY_FEEDBACK`) ships as code, **switched off**. It is built and unit-tested but was never tested live.
- **Measured gain (run 174, the last full run on the shipped settings, n = 1):**
  - DEV+SYN: 0.649 → **0.906** (14 docs)
  - DEV: 0.697 → 0.839 (6 docs)
  - SYN: 0.614 → 0.956 (8 docs)
  - The v1.0 base is runs 90/103/101/102, n = 2. Source: `eval/history.jsonl`, rendered by `scripts/render_docs.py`.
- **`outputs/` are the v1.0 files from sealed run 90 (Z-76 fallback, then Z-82).** The run-174 job
  ids are only stored in the dev run store, which the agent may not read, and the API has no list
  endpoint. All 8 files are VALID. README says this plainly.
- **Held-out numbers are v1.0 only** (run 90): budget 0.013, lease 0.600. No v1.1 held-out run exists.
- **README and DESIGN are re-rendered from existing runs.** DESIGN went from 250 lines to 126 and
  gained "What we could not finish".
- **Fresh clone of `v1.1`:** `/health` returned 200 **1.2 s** after `up` returned, and **9.1 s**
  after the start of `up --build`. The build was warm.
- **Zip:** `dist/229070422_hariom_singh_aiml.zip`, **7.10 MB**, `.git` included, 0 forbidden
  paths, 8/8 outputs VALID from inside the zip. The v1.0 fallback zip is untouched.

## Shipped config (Part A)

| Setting | Shipped | Evidence |
|---|---|---|
| `E0_ROBUST` | 1 | gate runs 105–106 |
| `PDF_TABLE_METHOD` | grid | gate runs 141–143, full set run 144 |
| `TABLE_CLEANUP` | 1 | gate runs 154–156, full set run 157 |
| `SCAN_PAGE_METHOD` | all | gate runs 171–173, full set run 174 |
| `SPEC_RETRY_FEEDBACK` | 0 | not live-tested (run 175 excluded: HTTP 401) |
| `LAB_MODE`, `SV_MODEL` | absent | `tests/test_shipped_config.py` |

**Tooling changes:**
- `scripts/dry_run.py`: the defaults now plan the shipped path (spec + grid + every scan page), routing each doc as the worker does.
- `scripts/render_docs.py`: new `v11` and `gates` blocks; run 90 relabelled v1.0.
- `scripts/plot_cost_accuracy.py`: "final (shipped)" became "sealed v1.0 (run 90)".

**Checks:**
- Dry run `--set dev`: PASSED, 6 docs. The highest estimate is 81,667 tokens, under the 90k limit.
- Dry run `--set syn`: PASSED, 8 docs.
- pytest: 783 passed (Part A), then 784 passed (Part C), with 95 subtests.
- pre-commit `--all-files`: 7/7 passed in both parts.

## Outputs source (Part B)

| Files | Source | Settings | VALID |
|---|---|---|---|
| 6 DEV + 2 held-out | sealed run 90 (`c01b567`), unchanged since tag `v1.0` | v1.0 | 8/8 |

Detail: `logs/P9f_outputs.md`.

## Docs (Part C)

- **README:**
  - The outputs statement (Z-82).
  - The config table: `SCAN_PAGE_METHOD` default `all`, plus rows for `PDF_TABLE_METHOD`, `TABLE_CLEANUP`, `E0_ROBUST` and `SPEC_RETRY_FEEDBACK` (off).
  - The `v11`, `scores` (v1.0 sealed), `chart` and `load` blocks.
  - A load note (Z-78): the load numbers are v1.0 with a fake model; v1.1 scans take p50 30.0 s vs 13.1 s on the 25-page scan (runs 171–173, `logs/P9e_report.md`).
  - Known limitations, including a "not finished" line.
- **DESIGN:**
  - The `gates`, `v11` and `cost` blocks.
  - "Where it fails", including the t12_001 spread: 0.548 in 17 of 23 recipe-era runs.
  - "What we could not finish".
- `render_docs.py --check` passes. The sample-values guard passes.

## Fresh clone (Z-79)

- `git clone --branch v1.1 . .scratch/fresh` gave `7032c28`.
- `docker compose -p freshcheck up -d --build` started 4 containers: db, api, 2 workers.
- `/health` returned 200 (`{"status":"ok","version":"dev"}`) 1.2 s after `up`, 9.1 s in total.
  The limit is 60 s.
- `docker compose -p freshcheck down -v` exited 0, and 0 containers were left.
- The folder `.scratch/fresh/` was kept.

## Zip verify (Z-80)

Built with `uv run python scripts/make_zip.py` on a clean tree at `7032c28`. Its own checks passed:
clean tree, no forbidden paths, no document binaries outside fixtures, no key-like strings,
size < 100 MB.

An independent check from the zip's contents (`.scratch/verify_zip.py`):

| Check | Result |
|---|---|
| size | 7,442,340 bytes (7.10 MB) < 100 MB |
| entries | 642 (294 tracked + 348 in `.git`), one root folder, CRC ok |
| `.git` present | yes; zip HEAD → `refs/heads/main` → `7032c28` |
| forbidden paths (sample/, the dev store, key file, .scratch/, dist/, _freshclone/, .venv/, __pycache__/) | **0** |
| outputs from the zip, `tools/validate.py` dir mode | exit 0 |
| outputs from the zip, single-file mode | **8/8 VALID** |
| zip outputs = repo outputs (sha256) | identical |

The v1.0 fallback zip (`dist/229070422_hariom_singh_aiml_v1.0_fallback.zip`, 2,246,890 bytes) was not touched.

**This report is not in the zip.** It is committed after the zip was built. The zip is the
`v1.1` tree; this file is a process log.

## What could not be done (gateway key expired at the deadline)

- **P9g live gate:** run 175 got HTTP 401, so the switch ships off.
- **v1.1 held-out run:** the held-out scores are v1.0's.
- **v1.1 load test:** the load evidence is v1.0, fake model, L1 20/20, 0 lost.
- **v1.1 `outputs/`:** the run-174 results could not be fetched. Job ids are not reachable through allowed routes.

## Deviations

1. **Two guard blocks in Part A, both stopped and reported:**
   - "cache" matched a label inside a heredoc. That led to Z-81.
   - ".env" appeared in `git check-ignore`. Hariom ran that check himself.
2. **Part B fell back to v1.0 outputs** (Z-76 (b), confirmed as Z-82).
3. **A bug I introduced in Part A was found in Part C.** The block-name regex skipped `v11`. It was
   fixed, a test was added, and both docs were re-rendered.
4. **DESIGN is about 1 page of prose plus two generated tables** (126 lines in total). The tables
   carry the evidence, so I kept them.
5. **The fresh-clone build was warm** (reused layers). The time measures up → health, not a cold build.
   PowerShell reported `$?` = False after `up`. That is the known 5.1 behaviour of `2>&1` on a native
   command; every container started and health returned 200.

## SELF-AUDIT

- [x] main == lab at the start (`4256ad4`); shipped config proven by test; P9g switch off; lab switches absent.
- [x] No LLM call made: no paid run, no eval, no job POSTed. The fresh clone ran `/health` only.
- [x] All 8 outputs VALID; source per file stated (v1.0 run 90); the dev run store was never read.
- [x] README/DESIGN numbers come from existing files with sources (`eval/history.jsonl` by run index, the phase reports); "could not finish" is present in both.
- [x] Fresh clone healthy in ≤ 60 s (1.2 s after up; 9.1 s total, warm build).
- [x] Zip < 100 MB (7.10 MB), `.git` in, 0 forbidden paths, 8/8 outputs VALID from inside the zip.
- [x] No commits, merges, tags, pushes or main-stack restarts by the agent. No rm/del. Scratch only in `.scratch/`.
- [x] No sample values in logs, reports or commit messages (pre-commit sample-values guard).
