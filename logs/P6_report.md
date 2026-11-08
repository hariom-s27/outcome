# P6 lean+ · Session 2 — live runs, ship decision, report

## PLAIN SUMMARY

- **The table path works on both long tables.**
  - **rentroll_001:** 0.1095 → **0.9886** in all 3 runs; 325/325 rows; $0.00116 per run.
  - **t12_001:** 0.0458 → **0.3970** mean (0.5485 / 0.0940 / 0.5485); 119/119 rows; $0.00202 mean per run.
  - The model's spec won the winner rule in every run (`table:ai` 6/6).
- **Ship decision under T-16b: NO SHIP.** Conditions 1 and 2 pass easily, but condition 3 fails:
  - boxscore_001 scored **0.100** (1/10 rows), below the 0.9750 floor.
  - The box score took the **unchanged baseline path** (`short_table`). P6 code did not run on it.
  - Its output hit the 8192-token cap (out = 8192), so only 1 row was returned.
  - The old 1.000 for boxscore_001 came from a dev-cache replay ($0 paid, `logs/P2_eval.md`). This is the first live box-score call with the cache off seen in these logs.
- **Applied:** `git checkout -- outputs/rentroll_001.json outputs/t12_001.json`. Outputs validate (exit 0, 8/8).
- **Reversible at $0:** if Hariom overrides, `eval_dev.py --reuse cbd8115/run1 --write-outputs --docs rentroll_001 t12_001` rebuilds the run-1 outputs from the saved run without new calls.
- **Spend:** $0.013947 for 10 Haiku calls (cap $0.08). RUNNING TOTAL **$0.493988**.

## Part D — evidence

Pre-checks:
```
worker-2 ... started (pipeline=baseline-v1, single_value_path=baseline, table_path=spec, cache_mode=off)
worker-1 ... started (pipeline=baseline-v1, single_value_path=baseline, table_path=spec, cache_mode=off)
uv run python scripts/dry_run.py --table-path spec  -> dry run PASSED (6 docs)
  t12_001 / rentroll_001 path=table_spec; boxscore_001 path=baseline why=short_table
```

Commands (as planned in `logs/P6_plan.md`):
```
eval_dev.py --docs rentroll_001 t12_001 --expect-live --run-index 1 --write-outputs --max-usd 0.025 --label p6-spec-r1 --report logs/eval_p6_run1.md
eval_dev.py --docs rentroll_001 t12_001 --expect-live --run-index 2 --max-usd 0.025 --label p6-spec-r2 --report logs/eval_p6_run2.md
eval_dev.py --docs rentroll_001 t12_001 --expect-live --run-index 3 --max-usd 0.025 --label p6-spec-r3 --report logs/eval_p6_run3.md
eval_dev.py --docs boxscore_001 --expect-live --run-index 1 --max-usd 0.005 --label p6-box --report logs/eval_p6_box.md
```
Every run: `all_live=True`, 0 replays, all results valid.

### Per run (source: `eval/history.jsonl` + `logs/eval_p6_run*.md`, `logs/eval_p6_box.md`)

| run | doc | score | path | rows pred/truth | calls | in / out tokens | cost $ | latency s |
|---|---|---|---|---|---|---|---|---|
| 1 | rentroll_001 | 0.9886 | table:ai | 325/325 | 1 | 8,951 / 531 | 0.00116 | 8.0 |
| 1 | t12_001 | 0.5485 | table:ai | 119/119 | 2 (repair) | 19,563 / 961 | 0.00244 | 8.0 |
| 2 | rentroll_001 | 0.9886 | table:ai | 325/325 | 1 | 8,951 / 531 | 0.00116 | 5.4 |
| 2 | t12_001 | 0.0940 | table:ai | 119/119 | 2 (repair) | 19,624 / 993 | 0.00246 | 6.6 |
| 3 | rentroll_001 | 0.9886 | table:ai | 325/325 | 1 | 8,951 / 531 | 0.00116 | 6.5 |
| 3 | t12_001 | 0.5485 | table:ai | 119/119 | 1 | 9,538 / 423 | 0.00117 | 3.0 |
| 1 | boxscore_001 | 0.1000 | baseline | 1/10 | 1 | 3,066 / **8,192** | 0.00440 | 23.7 |

### Checks of the chosen spec (run 1 only, from `metadata.extraction.table` in the run-1 outputs before the revert; runs 2–3 raw results sit under `cache/`, which I did not read)

| doc | chosen | rank | C1 unique / shape | C2 unexplained / lines | C3 matched / checked | C4 | C5 rows / total keys | filled | repaired |
|---|---|---|---|---|---|---|---|---|---|
| rentroll_001 | ai | 7.0 | 0.9848 / 1.0 ✓ | 21 / 3,047 ✓ | 335 / 357 ✓ | ✓ | 325 / 0 ✓ | 1.0 | no |
| t12_001 | ai | 6.0 | 1.0 / 1.0 ✓ | 0 / 141 ✓ | n/a (0 checked) | ✓ | 119 / 0 ✓ | 1.0 | yes (unknown keys) |

Line dispositions, run 1:
- rentroll_001: record 330 · child 2,345 · skipped total-like 339 · formula-sum 8 · section header 3 · header repeat 1 · unexplained 21. 5 duplicate keys (the first wins), leaving 325 rows.
- t12_001: record 119 · skipped no-amount 21 · section header 1.

## Free gate vs live

| doc | old (shipped) | free gate (heuristic, n=1) | live mean (AI spec, n=3) | live min / max |
|---|---|---|---|---|
| rentroll_001 | 0.1095 | 0.7191 | **0.9886** | 0.9886 / 0.9886 |
| t12_001 | 0.0458 | 0.0773 | **0.3970** | 0.0940 / 0.5485 |

- **Rent roll:** the AI spec uses `pick_by_label` and `key_matches_shape`. It removes the heuristic's 21 extra rows and fills the 2 fields the heuristic left null.
- **T12:** the model mapped line, amount and derived columns in runs 1 and 3, and only the key in run 2 (see "Where it fails").

## Spec choices

- `table:ai` in 6/6 table runs. The heuristic never won and no run fell back.
- t12_001 needed the one allowed repair in runs 1 and 2 (first answer had unknown spec keys). Run 3 was valid at the first try.

## Cost per doc vs old (old = P2 shipped run, `logs/P2_eval.md`, uncached $)

| doc | old $ | new $ (mean of 3) | old latency s | new latency s (mean) |
|---|---|---|---|---|
| rentroll_001 | 0.00971 | 0.00116 (−88%) | 26.8 | 6.6 |
| t12_001 | 0.00394 | 0.00202 (−49%) | 12.3 | 5.9 |
| boxscore_001 | 0.00951 (cache hit, $0 paid) | 0.00440 (runaway, 1 run) | 1.1 (cache) | 23.7 |

## Ship arithmetic (T-16b, pre-registered)

| condition | value | target | result |
|---|---|---|---|
| 1a rentroll_001 mean | 0.9886 | ≥ 0.0845 | PASS |
| 1b t12_001 mean | (0.5485 + 0.0940 + 0.5485) / 3 = 0.3970 | ≥ 0.0208 | PASS |
| 2 rentroll mean + t12 mean | 1.3856 (mean gain +0.6152) | ≥ 0.2553 | PASS |
| 3 boxscore_001 (1 run) | 0.1000 | ≥ 0.9750 | **FAIL** |

**Decision: NO SHIP.** Shipped default stays `EXTRACT_TABLE_PATH=baseline`. The 2 outputs were reverted. No config, outputs or docs change.

**For Hariom (not done, needs your call):** condition 3 failed on a path P6 did not change. Options:
1. Accept no ship.
2. Approve one more live boxscore_001 run (about $0.004–0.01; $0.066 cap left) as a new rule, and record it as a deviation.
3. Ship on conditions 1–2 and treat the box-score runaway as a separate baseline bug for P8b.

I did not re-run the box score: the rule said one run, and re-running until it passes would be fishing.

## Where it fails

1. **boxscore_001 baseline runaway (outside P6):** with the cache off, the short-table baseline call ran to the 8192 output-token cap and returned 1/10 rows. All 20 fields scored 0.10. The 20 cells it did return were all right, so the loss is truncation, not wrong values. The old 1.000 was a cache replay, so live stability of this call was never measured. P8b: find the cause of the runaway (repetition? max_tokens?) and whether a guard is needed.
2. **t12_001 run 2 (0.0940):** the repaired spec mapped only `gl_code`. `line_item`, the amounts and `months_with_activity` were all missed (119 each). The checks could not catch it: a key-only spec still passes C1, C2, C4 and C5, and its filled fraction (0 here) only matters against another candidate. The heuristic was also key-only (filled 0, 4 checks), so on a tie the AI spec wins. This is the open item from the plan (filled fraction counts fills, not correctness), seen live.
3. **t12_001 fields that stay low in every run:**
   - `property_name` is wrong in all 119 rows (the doc-field cell chosen is the wrong one).
   - `period_start` and `period_end` are null (`field_sources: none`): the grammar has no "date from a header cell" source.
   - `section` and `category` score 0.02 (117 missed): the section context or map reaches only 2 rows.
   - Ceiling with these 5 fields at 0: about 6/11 ≈ 0.55, which matches runs 1 and 3.
4. **rentroll_001 leftovers:**
   - `resident_name` and `balance` each have 22 hallucinated cells (values where the truth is null).
   - `monthly_rent` has 13 wrong cells and `monthly_other_charges` 6.

## SELF-AUDIT

1. **Steps:**
   - worker log checked;
   - dry run passed;
   - 3 × 2 table runs plus 1 box-score run, as planned;
   - ship rule applied;
   - outputs reverted; validate exit 0;
   - pytest 538 passed; ruff clean.
2. **Decisions not in the prompt:**
   - Run-1 checks were read from the `metadata.extraction.table` block of the run-1 outputs before the revert (`grep`, metadata lines only, value/text lines filtered out). Runs 2–3 checks are not reported because their raw results are under `cache/`.
   - I did not re-run the box score.
3. **Deviations:**
   - Runs 2, 3 and box are recorded with run id `cbd8115-dirty`: run 1's `--write-outputs` changed `outputs/`. `--allow-dirty` was not used, and eval_dev's clean-tree gate passed.
   - Otherwise none.
4. **Numbers:**
   - Scores: `eval/history.jsonl` `per_doc`, which is `tools/validate.py score()` via `eval_dev` (mean of per-field means); n = 3 per table doc, n = 1 for the box score.
   - Costs and tokens: eval_dev run output.
   - Old scores: `logs/P6_plan.md` (re-scored shipped outputs). Old costs: `logs/P2_eval.md`.
   - Checks: run-1 output metadata (n = 1).
5. **Tests:** 538 before, 0 new, 538 total passed (no code changed in S2).
6. **Frozen and outputs:**
   - `contract/`, `tools/validate.py` and `ASSIGNMENT.md` untouched.
   - `outputs/` back to the committed state; validate exit 0 (8/8).
7. **Held-out seal:** lease_003 and budget_001 were not opened or run.
8. **Safety:**
   - no keys or env read;
   - no sample values in this report (field names, counts, scores, column roles only);
   - no guard blocks;
   - stack not restarted or changed;
   - no commits.
9. **LLM calls / spend:** 10 Haiku calls (rentroll 3, t12 5, box 1, plus repairs counted in t12), **$0.013947** this session (0.003598 + 0.003620 + 0.002326 + 0.004403). **RUNNING TOTAL $0.480041 + $0.013947 = $0.493988.**
10. **Open items for P8b:**
    1. Box-score baseline runaway with the cache off (above). Decide whether condition 3 is retested.
    2. Winner rule: a key-only AI spec can tie or beat a key-only heuristic. Add a minimum filled fraction (e.g. a spec with filled = 0 counts as a hard fail when the field list has row-level fields), or take 2 AI samples.
    3. Grammar: a header-cell date source for period fields; t12 doc-field cell choice.
    4. Rent-roll null-truth hallucinations (22 per field on 2 fields).
    5. Field compiler types `resident_name` as integer (carried over from the plan).

## FINAL STOP — draft commit lines (PowerShell, one line each, no trailer)

```
git add eval/history.jsonl logs/eval_p6_run1.md logs/eval_p6_run2.md logs/eval_p6_run3.md logs/eval_p6_box.md; git commit -m "chore(process): P6 live eval history and run logs"
git add logs/P6_report.md; git commit -m "docs: P6 report (no ship: boxscore floor failed)"
```
