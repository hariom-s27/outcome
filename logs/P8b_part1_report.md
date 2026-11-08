# P8b Part 1 — live floors, re-tests, ship decisions (S1)

## PLAIN SUMMARY

- **Tables: SHIP.** T-16b with the corrected (live) floor passes all conditions. The shipped
  default is now `EXTRACT_TABLE_PATH=spec` (config + compose + shipped-config test).
- **Scan page choice: NOT SHIPPED.** The lease_001 3-run mean with locate (0.6417) is below the
  bar (live old mean 0.675 + 0.025 = 0.700). `SCAN_PAGE_METHOD` stays `first`, and
  `outputs/lease_001.json` was restored.
- **The live old box score is 0.100** (3 of 3 runs). Every run was cut off at the 8,192-token
  cap with 1 of 10 rows. This confirms that P6b's 1.000 was a cache replay.
- **The date gap is not fixed in practice.** The box score `date` field is still null in 3 of 3
  recipe runs (0.950 each), and t12's period fields are still null.
- **Risk found (n = 1):** t12_001 scored **0.1571** on the new prompt, against 0.5485 in
  every P6b run. See "Where it fails" item 2 and "For Hariom".
- **Spend this session:** $0.04026 (cap $0.07). **RUNNING TOTAL $0.543845.**

## Live floor (old path, cache off) — step 1

Stack: `table_path=baseline, scan_pages=first, cache_mode=off` (both workers, checked).
Commit `fc5e6f1`. Every run: 0 replays, valid = True.

| run | doc | score | rows pred/truth | out tokens | output_flags | cost $ |
|---|---|---|---|---|---|---|
| 21 | boxscore_001 | 0.100 | 1/10 | 8,192 | truncated_output | 0.00440 |
| 22 | boxscore_001 | 0.100 | 1/10 | 8,192 | truncated_output | 0.00440 |
| 23 | boxscore_001 | 0.100 | 1/10 | 8,192 | truncated_output | 0.00440 |
| 28 | lease_001 | 0.650 | 1/1 | 2,338 | — | 0.00308 |
| 29 | lease_001 | 0.700 | 1/1 | 2,330 | — | 0.00308 |

- **Live old box mean** = (0.100 + 0.100 + 0.100) / 3 = **0.100** (n = 3).
- **Live old lease mean** = (0.650 + 0.700) / 2 = **0.675** (n = 2; pages 1–8 of 25 sent).
- `repetition_loop` did not fire on the box runs: no 5-word phrase repeated in more than 10% of
  the answer. Only `truncated_output` fired.

## Recipe and page-choice runs — step 2

Stack: `table_path=spec, scan_pages=locate, cache_mode=off` (both workers, checked).
Every run: 0 replays, valid = True.

| run | doc | score | rows pred/truth | calls | in / out tokens | path | cost $ |
|---|---|---|---|---|---|---|---|
| 24 | boxscore_001 | 0.950 | 10/10 | 1 | 6,841 / 451 | table:ai | 0.00091 |
| 25 | boxscore_001 | 0.950 | 10/10 | 1 | 6,841 / 451 | table:ai | 0.00091 |
| 26 | boxscore_001 | 0.950 | 10/10 | 1 | 6,841 / 451 | table:ai | 0.00091 |
| 27 | t12_001 | 0.1571 | 140/119 | 1 | 9,847 / 542 | table:ai | 0.00126 |
| 31 | lease_001 | 0.850 | 1/1 | 5 | 34,503 / 4,434 | locate:located | 0.00567 |
| 32 | lease_001 | 0.825 | 1/1 | 5 | 34,503 / 4,575 | locate:located | 0.00574 |
| 33 | lease_001 | 0.250 | 1/1 | 5 | 34,503 / 4,104 | locate:located | 0.00550 |

- **Box score:** the only cells lost are `date`, null in all 10 rows of every run
  (`logs/eval_p8b_run24.md`: date 0.00, missed 10; property_name 1.00).
- **Run-24 recipe metadata** (read from `outputs/boxscore_001.json` with a metadata-only script):
  - chosen = ai, 1 call, AI spec valid, no repair;
  - ai: rank 6.0 (4 checks, filled 1.0), doc_filled 1, `date` source = doc;
  - heuristic: rank 6.0, doc_filled 0, `date` source = none.
  - So the AI maps `date` to a document cell, but the value comes out null. The metadata
    does not record whether that entry had a `parse`, so I can't tell "no parse" from "the
    parse found no date".
- **lease_001 with locate:** 4 locate calls plus 1 read per run. Run 33 lost 30 cells (missed,
  0 wrong) with the same input size as runs 31–32. I can't see why without the job metadata,
  which is under `cache/` and I did not read it.
- **rentroll_001:** reuses P6b run 11 (no new calls).

## Arithmetic

**T-16b (Z-5; formula unchanged, box-score "old" = live 3-run mean):**

| condition | value | target | result |
|---|---|---|---|
| 1a rentroll_001 mean (P6b, n=3) | 0.9494 | ≥ 0.0845 | PASS |
| 1b t12_001 mean (P6b, n=3) | 0.5485 | ≥ 0.0208 | PASS |
| 2 rentroll + t12 | 0.9494 + 0.5485 = 1.4979 | ≥ 0.2553 | PASS |
| 3 boxscore_001 recipe mean (n=3) | (0.950 × 3) / 3 = 0.950 | ≥ 0.100 − 0.025 = 0.075 | PASS |

Sensitivity check (not part of the rule): if t12 is taken as run 27 alone (0.1571), condition 1b
still passes (0.1571 ≥ 0.0208), and so does condition 2 (0.9494 + 0.1571 = 1.1065 ≥ 0.2553). So
the ship decision does not depend on the t12 drop.

**Z-14 (page choice, separate decision):**
lease_001 locate mean = (0.850 + 0.825 + 0.250) / 3 = 1.925 / 3 = **0.6417**;
bar = 0.675 + 0.025 = **0.700**. 0.6417 < 0.700 → **keep `first`**. The single run 33 decides
this: runs 31–32 alone would pass. I applied the rule as written, with no runs excluded.

## Decision and what changed

- **Ship tables:**
  - `app/config.py`: `table_path` default and env fallback are now `spec`.
  - `compose.yaml`: `EXTRACT_TABLE_PATH: ${EXTRACT_TABLE_PATH:-spec}`.
  - `tests/test_shipped_config.py`: shipped default is spec.
  - Three older tests that exercise the baseline worker path on a table list now set
    `table_path="baseline"` explicitly: `tests/test_baseline.py` (×2) and
    `tests/test_single_value.py` (×1). `tests/test_tables.py` and `tests/test_p8b.py` switch
    tests were updated to the new default.
- **Outputs (Z-6):**
  - `boxscore_001` from run 24 (`--write-outputs`).
  - `rentroll_001` + `t12_001` via `eval_dev.py --reuse 4aa72a9/run11 --write-outputs --docs
    rentroll_001 t12_001 --no-record`: re-scored 0.930 / 0.548, no calls.
  - `lease_001` restored: `git checkout -- outputs/lease_001.json`.
  - Validate: `uv run python tools/validate.py outputs/ --schema-dir sample/schemas` → exit 0,
    8 files.
- **Page choice:** default stays `first` (compose + config unchanged; the switch remains for
  experiments).

## Where it fails

1. **boxscore_001 `date` is null in 3 of 3 recipe runs, and t12 period fields are null in
   run 27.**
   - The `parse` grammar works on invented sheets (tests), but it brought no measured gain on
     DEV.
   - The heuristic fills no document field on boxscore_001 or t12_001 (dry run:
     `heuristic_doc_filled=0`), so only the AI recipe could use `parse`.
   - The metadata doesn't record per-entry `parse`, so the cause is not visible.
2. **t12_001 dropped to 0.1571 (n = 1).**
   - 140/119 rows (21 extra); `property_name`, `period_start` and `period_end` missed in all
     119 rows.
   - Still `table:ai`, so this is a different AI recipe from P6b's (which gave 119/119, 0.5485,
     3 of 3).
   - The only change on this path's input is the Part A prompt text (`parse` explanation and
     example). Likely cause: that wording shifted the recipe the model writes. This is not
     verified: n = 1, and the metadata for run 27 is under `cache/`.
   - The sealed S2 run will use this prompt.
3. **lease_001 locate run 33 collapsed to 0.250** (30 missed) with the same pages-sized input.
   The cause is unknown.
4. **Old box path:** cut off at the cap 3 of 3 times. `truncated_output` caught it;
   `repetition_loop` did not (threshold 10%).
5. **Measure live:** P6b's box "old 1.000" was a cache replay; live it is 0.100 (P6 + 3 runs
   here).

## For Hariom (before S2; needs your call)

1. **Recommended: revert the `parse` explanation and example in the table-spec prompt to the
   P6b wording.**
   - Keep the grammar, the executor and the heuristic.
   - Why: the new wording gave no measured gain (box `date` still null 3 of 3) and coincides
     with the t12 drop.
   - Then confirm with t12_001 × 2 live on the reverted prompt (about $0.0025) before the sealed
     run.
   - This is a code change after Part B, so it needs your yes.
2. Or measure first: t12_001 × 2 more on the current prompt (about $0.0025), then decide.
3. Or accept as is. The sealed run's t12 may land anywhere from about 0.16 to 0.55.
4. Optional: record each doc field's `parse` in the recipe metadata (counts and kinds only),
   so a null like the box `date` can be explained next time.

## SELF-AUDIT

1. **Steps:**
   - Part A committed by Hariom (3b8a887, 5bad60b, 5ea594b, fc5e6f1).
   - Worker logs checked before each half (`baseline/first/off`, then `spec/locate/off`).
   - Runs exactly as pre-registered: 21–23, 28–29, 24–26, 27, 31–33; `--write-outputs` on 24
     and 31 only.
   - T-16b and Z-14 applied as written.
2. **Decisions not in the prompt:**
   - Per-run caps: $0.01 for the old box and lease runs; $0.005 for the recipe runs.
   - `--no-record` on the reuse step, so no duplicate history line.
   - A metadata-only scratchpad script read run 24's `metadata.extraction.table` (no values).
3. **Deviations:**
   - Runs after 21 are recorded as `fc5e6f1-dirty`, because `eval/history.jsonl` and
     `outputs/` were changed by earlier runs. The gate printed "clean tree" each time;
     `--allow-dirty` was not used.
   - Three older tests were pinned to `table_path="baseline"` because the default changed.
4. **Numbers:**
   - Scores from `eval/history.jsonl` `per_doc` (`tools/validate.py score()` via eval_dev),
     with n stated per row.
   - Costs from eval_dev output.
   - P6b means from `logs/P6b_report.md` (committed history lines 16–18).
5. **Tests:** 581 passed; ruff clean; pre-commit all passed.
6. **Frozen files:** `contract/`, `tools/validate.py` and `ASSIGNMENT.md` untouched. Outputs
   validate exit 0 (8 files).
7. **Held-out seal:** lease_003 and budget_001 were not opened or run.
8. **Safety:**
   - no `.env`, `cache/` or answer files read by me;
   - no sample values in this report (doc ids, field names, counts, scores, source kinds);
   - no guard blocks;
   - no stack restarts or env changes;
   - no commits.
9. **Spend:**
   - step 1: 3 × $0.00440 + 2 × $0.00308 = $0.01936;
   - step 2: 3 × $0.00091 + $0.00126 + $0.00567 + $0.00574 + $0.00550 = $0.02090;
   - session total **$0.04026** (cap $0.07).
   - **RUNNING TOTAL $0.503585 + $0.04026 = $0.543845.**
