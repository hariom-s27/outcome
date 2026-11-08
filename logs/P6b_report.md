# P6b — robust table recipe, all spreadsheet tables routed, decision by T-16b

## PLAIN SUMMARY

- **Decision under T-16b (applied as written, B-1/B-8): NO SHIP.** The default stays
  `EXTRACT_TABLE_PATH=baseline`. The 3 run-11 outputs were reverted, and validate exits 0 (8/8).
- **The box score now runs on the recipe path, and the runaway is gone.** In all 3 runs it
  returned 10/10 rows from 1 call (about 440 output tokens, $0.00087). In P6 the old path
  returned 1/10 rows and stopped at the 8,192-token cap. But its 3-run mean is
  **0.9267 < 0.9750**:
  - `date` is null in every run;
  - `property_name` was missed in run 13;
  - two percent fields were wrong in 2 cells each in run 13.
- **Rent roll and T12 keep their gains:**
  - rentroll_001 mean 0.9494 (0.9298 / 0.9886 / 0.9298);
  - t12_001 mean 0.5485, the same in all 3 runs. In P6 one of its 3 runs went key-only
    (0.0940); no P6b run did.
- **Spend:** $0.009597 for 9 Haiku calls (cap $0.04). **RUNNING TOTAL $0.503585.**

## Part B — evidence

Pre-checks:
```
worker-1 ... started (pipeline=baseline-v1, single_value_path=baseline, table_path=spec, cache_mode=off)
worker-2 ... started (pipeline=baseline-v1, single_value_path=baseline, table_path=spec, cache_mode=off)
uv run python scripts/dry_run.py --table-path spec  -> dry run PASSED (6 docs)
  boxscore_001 / t12_001 / rentroll_001 path=table_spec why=table (calls 1, max 3)
```

Commands:
```
eval_dev.py --docs rentroll_001 t12_001 boxscore_001 --expect-live --run-index 11 --write-outputs --max-usd 0.013 --label p6b-spec-r11 --report logs/eval_p6b_run11.md
eval_dev.py --docs rentroll_001 t12_001 boxscore_001 --expect-live --run-index 12 --max-usd 0.013 --label p6b-spec-r12 --report logs/eval_p6b_run12.md
eval_dev.py --docs rentroll_001 t12_001 boxscore_001 --expect-live --run-index 13 --max-usd 0.013 --label p6b-spec-r13 --report logs/eval_p6b_run13.md
```
Every run: 0 replays, `cache_mode=off`, all results valid. Total cap: 3 × $0.013 = $0.039,
within the $0.04 cap.

### Per run (source: `eval/history.jsonl` + `logs/eval_p6b_run1{1,2,3}.md`)

| run | doc | score | rows pred/truth | calls | in / out tokens | cost $ | latency s |
|---|---|---|---|---|---|---|---|
| 11 | rentroll_001 | 0.9298 | 325/325 | 1 | 8,951 / 512 | 0.00115 | 7.3 |
| 11 | t12_001 | 0.5485 | 119/119 | 1 | 9,538 / 423 | 0.00117 | 3.1 |
| 11 | boxscore_001 | 0.9500 | 10/10 | 1 | 6,532 / 435 | 0.00087 | 4.5 |
| 12 | rentroll_001 | 0.9886 | 325/325 | 1 | 8,951 / 531 | 0.00116 | 8.0 |
| 12 | t12_001 | 0.5485 | 119/119 | 1 | 9,538 / 423 | 0.00117 | 4.1 |
| 12 | boxscore_001 | 0.9500 | 10/10 | 1 | 6,532 / 435 | 0.00087 | 4.2 |
| 13 | rentroll_001 | 0.9298 | 325/325 | 1 | 8,951 / 512 | 0.00115 | 6.1 |
| 13 | t12_001 | 0.5485 | 119/119 | 1 | 9,538 / 462 | 0.00119 | 3.4 |
| 13 | boxscore_001 | 0.8800 | 10/10 | 1 | 6,532 / 447 | 0.00088 | 3.1 |

Run costs: r11 $0.003187, r12 $0.003197, r13 $0.003213.

## Candidate choices

**Run 11** (read from `metadata.extraction.table` of the run-11 outputs before the revert,
using a metadata-only script; no values printed):

| doc | chosen | AI spec | candidates: rank (checks, filled) | merge |
|---|---|---|---|---|
| rentroll_001 | **merged** | valid, no repair, 0 entries dropped | ai 7.0 (5, 1.0) · merged 7.0 (5, 1.0) · heuristic 6.71 (5, 0.857) | base ai, +1 field (`report_period`, a document cell from the heuristic) |
| t12_001 | **ai** | valid, no repair | ai 6.0 (4, 1.0) · heuristic 4.0 (4, 0.0) | none (heuristic has nothing extra) |
| boxscore_001 | **ai** | valid, no repair | ai 6.0 (4, 1.0) · heuristic 6.0 (4, 1.0) | none (AI already maps both doc fields) |

- No retry in any run: no chosen spec was key-only, and every run made 1 call.
- No repair: the metadata shows run 11 directly. For runs 12–13, calls = 1 per doc rules out
  a repair or a retry.

**Runs 12–13:**
- The full metadata of runs 12–13 is only in the job results under `cache/`, which I did not
  read. Only the run-11 outputs were written.
- Inference from calls and tokens (not verified):
  - rentroll runs 11 and 13 have identical tokens (512 out) and score, so they are probably the
    same spec and the same merged choice.
  - run 12 (531 out, 0.9886) matches the P6 AI spec, which maps `report_period` itself.

## Truncation flags (B-6)

- No job in P6b took the baseline path: every table doc used recipes and no fallback happened.
  So no `truncated_output` / `repetition_loop` flags could fire live.
- The flags are covered by tests only: fake LLM in `tests/test_tables.py`, MockTransport in
  `tests/test_llm.py`.

## Free gate vs live

| doc | old (shipped) | free gate (heuristic, n=1) | live mean (n=3) | live min / max |
|---|---|---|---|---|
| rentroll_001 | 0.1095 | 0.7191 | **0.9494** | 0.9298 / 0.9886 |
| t12_001 | 0.0458 | 0.0773 | **0.5485** | 0.5485 / 0.5485 |
| boxscore_001 | 1.0000 (cache replay) | 0.9000 | **0.9267** | 0.8800 / 0.9500 |

- **Box score.** The free gate predicted a ceiling of about 0.90–0.95: 18 columns right, and the
  2 document fields depend on the AI.
  - **Runs 11–12:** the AI recipe filled `property_name` but not `date`, so 0.95.
  - **Run 13:** `property_name` and `date` were both missed, and `percent_occupied` /
    `p_occ_wornonrev` had 2 wrong cells each, so 0.88.

## Ship arithmetic (T-16b, pre-registered; box score on the new path, 3-run mean, B-8)

| condition | value | target | result |
|---|---|---|---|
| 1a rentroll_001 mean | (0.9298 + 0.9886 + 0.9298) / 3 = 0.9494 | ≥ 0.0845 | PASS |
| 1b t12_001 mean | (0.5485 × 3) / 3 = 0.5485 | ≥ 0.0208 | PASS |
| 2 rentroll mean + t12 mean | 1.4979 (mean gain +0.6713) | ≥ 0.2553 | PASS |
| 3 boxscore_001 3-run mean | (0.95 + 0.95 + 0.88) / 3 = 0.9267 | ≥ 0.9750 | **FAIL** |

**Decision: NO SHIP.**
- Applied: `git checkout -- outputs/rentroll_001.json outputs/t12_001.json outputs/boxscore_001.json`.
- Default stays `baseline`; no config, outputs or docs changed. Validate: exit 0, 8/8.

## Where it fails

1. **boxscore_001 `date` is null in all 3 runs.**
   - The AI recipe names a document cell for it (`field_sources: doc` in run 11), but the cell
     doesn't parse as a date.
   - This is the grammar gap already listed in P6: there is no "date from a header-cell text"
     source. The same gap causes t12's `period_start` / `period_end` to be null.
   - It alone caps the box score at 0.95, below the 0.975 floor. **On this field list the
     recipe path can't pass condition 3 until the grammar can read a date from header text.**
2. **boxscore_001 run 13:**
   - `property_name` was missed;
   - two percent columns had 2 wrong cells each (rows 10/10, so not truncation).
   - Without the run-13 metadata (it's in `cache/`), I can't say which spec entry differed.
3. **Merge ranking is blind to document-level fields.**
   - `filled` counts only row-level fields, so a merge that only adds a document cell ties
     the winner, and the tie goes to the merge (B-4: "rank ≥ best").
   - In rentroll run 11 the added `report_period` cell from the heuristic came out null, so it
     made no difference (the AI spec had it unmapped too).
   - But a document cell that is wrong rather than null would be kept with no check against it.
   - Possible fix (P8b): require a merge to add a row-level field, or compare document cells.
4. **rentroll_001 leftovers** (same as P6): `resident_name` / `balance` have 22 hallucinated
   cells each; `monthly_rent` has 13 wrong, `monthly_other_charges` 6.
5. **t12_001 fields that stay low** (same as P6):
   - `property_name` is wrong in 119 rows;
   - `period_start` / `period_end` are null (item 1);
   - `section` / `category` score 0.02.
   - The 0.5485 ceiling is unchanged.
6. **The box score's old 1.000** was a cache replay of the baseline path. The live baseline
   path ran away in P6. Neither path has shown ≥ 0.975 live with the cache off.

## For Hariom (not done, needs your call)

1. Accept no ship (current state).
2. **P8b grammar item:** add a "date parsed from a document cell's text" source. It should fix
   box `date` and t12 `period_*`. Then re-run T-16b on the box score as a new phase, with the
   same goalposts.
3. Ship on conditions 1–2 and treat the box score as a separate item. That would be a rule
   change, and I did not do it.

## SELF-AUDIT

1. **Steps:**
   - worker log checked (`table_path=spec, cache_mode=off`);
   - tree clean at start of Part B (Part A committed by Hariom, `4aa72a9`);
   - dry run passed;
   - 3 × 3 live runs as planned;
   - T-16b applied as written;
   - outputs reverted; validate exit 0.
2. **Decisions not in the prompt:**
   - Per-run cap: `--max-usd 0.013` each (3 × 0.013 = 0.039 ≤ 0.04).
   - Run-11 candidate metadata read with a scratchpad script that prints only
     `metadata.extraction.table` keys, ranks, checks and source kinds (no values).
3. **Deviations:**
   - Runs 12–13 are recorded as `4aa72a9-dirty`, because run 11's `--write-outputs` changed
     `outputs/`. This is the same as P6, and `--allow-dirty` was not used.
   - The candidate choice for runs 12–13 is inferred, not read (see above).
4. **Numbers:**
   - Scores: `eval/history.jsonl` `per_doc` (`tools/validate.py score()` via `eval_dev`), n = 3
     per doc.
   - Costs and tokens: eval_dev output.
   - Old scores: `logs/P6b_free_gate.md` (re-scored shipped outputs).
5. **Tests:**
   - Part A: 538 → 553 (15 new), all passed; ruff clean; pre-commit all passed.
   - Part B: no code change.
6. **Frozen and outputs:**
   - `contract/`, `tools/validate.py` and `ASSIGNMENT.md` untouched.
   - `outputs/` back to the committed state.
7. **Held-out seal:** lease_003 and budget_001 were not opened or run.
8. **Safety:**
   - no `.env`, `cache/` or answer files read;
   - no sample values in this report (doc ids, field names, counts, scores, source kinds only);
   - no guard blocks;
   - stack not restarted;
   - no commits.
9. **LLM calls / spend:** 9 Haiku calls, $0.009597 this session.
   **RUNNING TOTAL $0.493988 + $0.009597 = $0.503585.**
