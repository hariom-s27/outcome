# P6 lean+ · Session 1 — PLAN (long tables: the AI writes a recipe, code copies every row)

## PLAIN SUMMARY

- **Built, behind a switch (default off):** a new path for long spreadsheet tables.
  - Code profiles the sheet.
  - Two recipes ("specs") are made: one from the model, one by header matching (no model).
  - Code runs both recipes on every line, and five free checks pick the winner.
  - Keys and values are copied from cells, with cell citations.
  - If no recipe passes, the job takes today's path.
- **Free gate ($0):** the no-model recipe alone takes **rentroll_001 from 0.1095 to 0.7191**. It passes all 5 checks; rows 346 against 325 in the answer file.
  - **t12_001 only moves 0.0458 → 0.0773.** Its column headers don't name the GL code or line columns, so only the key is mapped. T12 depends on the model's recipe.
- **Dry run:** 6/6 ok.
  - The 2 long tables take the new path (about 14k estimated input tokens, 1 call, est. $0.0015 per doc; worst case with a repair is $0.0049).
  - The box score stays on today's path (10 data lines, `short_table`).
- **S1 spend:** $0.00 (no LLM calls). Tests: 502 before → 538 now (+36), all passing.
- **Hariom at PLAN STOP:**
  - deviations 1–8 accepted;
  - **(a) new winner rule:** drop hard fails (C1 or C5); among the rest, rank = checks passed + 2 × filled fraction; ties go to the AI spec;
  - **(b) ship rule T-16b** replaces T-16.
  - Both are built and documented below.

## What was built

| File | What |
|---|---|
| `app/tables/profile.py` | Sheet profiler: lines per row, header-row candidates (2-row headers merged), blank-band regions, per-column profiles (header, type mix, distinct and blank ratio, vertical SUM count, dominant shape), per-line facts (numeric cells, total word, equals-sum-of-block, header repeat, blank). `preview()`: header block, header rows, up to 30 sampled lines (first 15, middle 10 starting before a block boundary, last 5) as `[Sheet!A12] value | …` with code-computed tags, column profiles, the sheet list, and parameters sheets as label/value pairs. |
| `app/tables/spec.py` | Closed grammar, validated by code. Unknown keys are invalid. `map_distinct` is accepted only when the field description lists its allowed values, and every mapped value must be one of them. |
| `app/tables/execute.py` | Applies a spec to every line in the data range.<br>- Each line gets a disposition: record / child / skipped-reason / unexplained.<br>- Children fold into the last record.<br>- Keys use display text; values go through the normaliser.<br>- R26: a blank or dash money cell is 0.<br>- Doc fields are read once and broadcast.<br>- First key wins; duplicates are counted.<br>- Citations look like `[Sheet!C12] text`; `source_locations` lists every cell used. |
| `app/tables/checks.py` | C1 keys unique ≥ 0.98 and shape ≥ 0.9 · C2 unexplained ≤ 2% · C3 totals within 0.5% on ≥ 90% of checked total cells · C4 type fit ≥ 0.9 per mapped column · C5 rows ≥ 1 and no total word in a key. Spec score = checks passed (C3 only when applicable). Hard fail = C1 or C5 fails. |
| `app/tables/heuristic.py` | No-model spec: rapidfuzz header match (abbreviations expanded, quoted header in the description = match, type-clash penalty, greedy 1:1); key = the most unique matching column; `record_start` key_nonempty; doc fields by label match in a parameters sheet or the header block. No pick_by_label / map_distinct / derived. |
| `app/pipeline/table_spec.py` | Runs only when `EXTRACT_TABLE_PATH=spec`, a primary field exists, the file is XLSX/CSV, and the profiled data region has > 60 lines.<br>- 1 Haiku call (JSON), plus ≤ 1 repair call carrying the validator's message.<br>- Executes the AI spec and the heuristic spec and runs the checks.<br>- **Winner rule (a):** hard-failed specs (C1 or C5) are dropped. The rest are ranked by `checks_passed + 2 × filled_fraction`, where filled fraction = row-level fields (not the primary, not document-level) with ≥ 1 non-null value ÷ row-level fields. Ties go to the AI spec.<br>- Both hard-fail → one baseline call (fallback).<br>- Any exception → logged as type and location → fallback.<br>- Metadata `extraction.table`: chosen spec, check results, lines by disposition, rows, calls. No cell text. |
| `app/config.py`, `app/worker.py`, `compose.yaml` | Switch `EXTRACT_TABLE_PATH = baseline \| spec`, default **baseline**. Shown in the worker start log line (`table_path=…`). Compose passes `${EXTRACT_TABLE_PATH:-baseline}`. |
| `app/readers/xlsx_reader.py` | Flags a cell holding a vertical `SUM`/`SUBTOTAL` formula with a cached value as `sum_formula=<ref>`. Row-wise SUMs are not flagged. Flags are never shown to a model. |
| `scripts/simulate_tables.py` | The free gate → `logs/P6_free_gate.md`. |
| `scripts/dry_run.py` | `--table-path spec`. |
| `scripts/eval_dev.py` | History `path` = `table:<ai\|heuristic\|fallback>` for table-path jobs. |

**Tests (copied from pytest, all PASSED):**
```
tests/test_tables.py::test_cell_helpers
tests/test_tables.py::test_vertical_sum_only
tests/test_tables.py::test_profile_header_preview_and_sample_cap
tests/test_tables.py::test_flat_table_with_total_row
tests/test_tables.py::test_unit_blocks_fold_children_and_pick_totals
tests/test_tables.py::test_reader_flags_vertical_sum_cells_only
tests/test_tables.py::test_gl_sections_subtotals_formulas_and_maps
tests/test_tables.py::test_map_distinct_needs_listed_allowed_values
tests/test_tables.py::test_parameters_sheet_label_value_and_heuristic_doc_fields
tests/test_tables.py::test_heuristic_spec_on_flat_table
tests/test_tables.py::test_header_repeat_mid_sheet_is_skipped
tests/test_tables.py::test_leading_zero_keys_are_copied_as_displayed
tests/test_tables.py::test_blank_and_dash_money_cells_are_zero_others_null
tests/test_tables.py::test_wrong_key_column_fails_c1_hard
tests/test_tables.py::test_spec_missing_records_fails_c3
tests/test_tables.py::test_unknown_spec_keys_are_invalid
tests/test_tables.py::test_no_amount_skip_drops_key_only_records
tests/test_tables.py::test_pipeline_ai_spec_chosen_and_schema_valid
tests/test_tables.py::test_pipeline_invalid_spec_then_repaired
tests/test_tables.py::test_pipeline_garbage_spec_heuristic_wins
tests/test_tables.py::test_pipeline_invalid_twice_gives_up_after_one_repair
tests/test_tables.py::test_pipeline_both_hard_fail_falls_back_to_baseline
tests/test_tables.py::test_winner_ai_fills_many_with_one_soft_fail_beats_heuristic_key_only   (a)
tests/test_tables.py::test_winner_equal_fills_more_checks_wins_and_ties_go_to_ai             (a)
tests/test_tables.py::test_winner_hard_fail_never_wins                                       (a)
tests/test_tables.py::test_winner_rule_on_a_sheet_ai_fills_more_despite_soft_fail             (a)
tests/test_tables.py::test_filled_fraction_ignores_primary_and_doc_level_fields              (a)
tests/test_tables.py::test_short_table_keeps_the_current_path
tests/test_tables.py::test_pdf_keeps_the_current_path
tests/test_tables.py::test_switch_routes_and_defaults_to_baseline
tests/test_tables.py::test_switch_from_env
tests/test_tables.py::test_switch_off_output_identical_on_long_table
tests/test_tables.py::test_results_pass_the_frozen_validator_with_schema_shape
tests/test_tables.py::test_plan_reports_path_tokens_and_cost
tests/test_tables.py::test_metadata_carries_no_cell_text
tests/test_shipped_config.py::test_table_path_defaults_to_baseline   (new)
538 passed (full-suite tail in "Verification after (a)/(b)" below)
```
- Every spreadsheet is invented and built in code with openpyxl. The SUM-formula fixture gets cached values written into the sheet XML.
- The "validate.py as a test" requirement is met by `test_results_pass_the_frozen_validator_with_schema_shape`. It uses the frozen `tools/validate.py` `validate_contract`, the same way the other tests do.

## Free-gate table (Part B, $0; source `logs/P6_free_gate.md`; n = 1 each)

| Doc | heuristic score | old score | delta | rows pred/truth | checks passed | filled fraction | rank (a) |
|---|---|---|---|---|---|---|---|
| rentroll_001 | **0.7191** | 0.1095 | +0.6096 | 346/325 | 5 (C1–C5) | 0.8571 (12/14) | 6.7143 |
| t12_001 | **0.0773** | 0.0458 | +0.0315 | 140/119 | 4 (C3 n/a) | 0.0000 (0/9) | 4.0000 |

- Under rule (a), the AI spec beats the heuristic when `checks + 2 × filled` is higher (ties go to the AI).
  - Rent roll: the AI wins only with all 5 checks and ≥ 12/14 fields filled (rank ≥ 6.71). With 4 checks its best possible rank is 4 + 2 × 1 = 6.00, below the heuristic's 6.71, so it loses.
  - T12: any AI spec with ≥ 4 checks and ≥ 1 filled row field wins, and so does 3 checks with ≥ 5/9 fields filled.

- Score = `tools/validate.py score()` via `eval_dev.score_doc` (mean of per-field means). Old = shipped `outputs/<doc>.json` re-scored by the same script.
- Rent roll:
  - 14 of 17 fields score 0.88–0.94. The ceiling is set by the 21 extra rows: `key_nonempty` also starts records at 21 non-unit keys.
  - `monthly_rent` and `monthly_total_charges` stay null (they need pick_by_label).
  - `monthly_other_charges` scores 0.14 (wrong column by header match).
  - `report_period` scores 0.00 (wrong cell).
- T12: only `gl_code` is mapped (0.85). The headers carry months, not field names.

## Dry-run table (`uv run python scripts/dry_run.py --table-path spec`)

| Doc | path | why | data lines | est. input tokens | calls (max) | est. $ realistic (fuse) | heuristic spec score |
|---|---|---|---|---|---|---|---|
| boxscore_001 | baseline | short_table | 10 | 4,388 (baseline) | 1 | (unchanged) | – |
| lease_001 | baseline | single_value | – | 30,021 (baseline) | – | – | – |
| lease_002 | baseline | single_value | – | 37,525 (baseline) | – | – | – |
| om_001 | baseline | single_value | – | 20,384 (baseline) | – | – | – |
| t12_001 | **table_spec** | long_table | 141 | 14,080 | 1 (2) | 0.0015 (0.0049) | 4 |
| rentroll_001 | **table_spec** | long_table | 3,048 | 14,285 | 1 (2) | 0.0015 (0.0049) | 5 |

`dry run PASSED (6 docs)`, no exceptions.
- The token estimate is the high-side fuse estimate (1.5 chars/token for non-block text). The fuse $ covers spec call + repair at `max_tokens` 2048.
- A fallback would add one baseline call (rent roll: about 60k-token cap, roughly $0.01).

## Paid plan (Session 2, cap $0.08 total)

Before: Hariom restarts with `LLM_CACHE_MODE=off` and `EXTRACT_TABLE_PATH=spec`; the worker log shows `table_path=spec, cache_mode=off`. Then `uv run python scripts/dry_run.py --table-path spec` must pass.

`--max-usd` applies per invocation, so the $0.08 cap is split:
```
uv run python scripts/eval_dev.py --docs rentroll_001 t12_001 --expect-live --run-index 1 --write-outputs --max-usd 0.025 --label p6-spec-r1 --report logs/eval_p6_run1.md
uv run python scripts/eval_dev.py --docs rentroll_001 t12_001 --expect-live --run-index 2 --max-usd 0.025 --label p6-spec-r2 --report logs/eval_p6_run2.md
uv run python scripts/eval_dev.py --docs rentroll_001 t12_001 --expect-live --run-index 3 --max-usd 0.025 --label p6-spec-r3 --report logs/eval_p6_run3.md
uv run python scripts/eval_dev.py --docs boxscore_001 --expect-live --run-index 1 --max-usd 0.005 --label p6-box --report logs/eval_p6_box.md
```
- Expected spend: about 6 × $0.0015 for spec calls + about $0.001 for the box score, so roughly $0.01–0.02. The worst case with repairs and fallbacks stays under the per-run caps.
- Per run, S2 records: score, `path` (`table:ai|heuristic|fallback`), checks from `extraction.table`, rows vs truth count, cost, latency.

## Ship rule T-16b (replaces T-16; Hariom at PLAN STOP, new evidence = free gate; old scores re-scored from the shipped outputs by `scripts/simulate_tables.py`)

**Ship** only if all three hold (3-run means, n = 3 per doc):
1. **No regression on either table doc:**
   - rentroll_001 mean ≥ 0.1095 − 0.025 = **0.0845**;
   - t12_001 mean ≥ 0.0458 − 0.025 = **0.0208**.
2. **Mean gain:** ((rentroll mean − 0.1095) + (t12 mean − 0.0458)) / 2 ≥ **+0.05**, i.e. rentroll mean + t12 mean ≥ **0.2553**.
3. **boxscore_001** (1 run) ≥ 1.0000 − 0.025 = **0.9750**.

Outputs come from run 1.
- **Ship:** shipped default `EXTRACT_TABLE_PATH=spec` (compose + shipped-config test), keep the run-1 outputs of the 2 docs, validate 8/8, render docs. Config, outputs and docs go in separate commits.
- **No ship:** `git checkout -- outputs/rentroll_001.json outputs/t12_001.json`.
- T-16's partial-ship clause is gone: T-16b judges the two docs together, with a per-doc no-regression floor.
- Free gate against T-16b (heuristic only, n = 1, not the decision): gains +0.6096 / +0.0315, mean +0.3205.

## Deviations (each is small and general; Hariom please confirm or strike)

1. **Grammar: `except_label` on a `col` fold `sum`.** It sums a block's labelled lines except the listed labels. "Sum of all charge lines other than X" can't be written with the listed rules. Without it the AI could only map such a field to a wrong single column.
2. **Grammar: a `no_amount` skip.** It skips a would-be record with no number outside its key cell. Some field-list descriptions say rows must "carry an amount"; the prompt tells the model to use it only then. It is never used by the heuristic.
3. **The heuristic skip list adds `section_header`** to the 4 listed skips. Label-only lines in the key column would otherwise become records and push C1 shape conformity below 0.9.
4. **Reader:** vertical SUM/SUBTOTAL cells are flagged `sum_formula=<ref>`. This is needed for the formula half of C3 and the `formula_sum_rows` skip. Existing reader tests are unchanged and pass.
5. **Normalising:**
   - a workbook-level MDY/DMY vote using the existing `vote_date_order`. Without it, ambiguous numeric dates were nulled; rent-roll date fields went from about 64% to 100% parsed;
   - a field typed only from nouns in its description keeps a text cell as text. Example: `resident_name` is typed integer by the compiler because its description mentions "units".
6. **C4 counts row-field columns only** ("per mapped column"); document-level cells are excluded.
7. **C3 details (judgement):**
   - a total matches a block subtotal, the sum of earlier subtotals, or a running total;
   - pass needs ≥ 90% of checked total cells, because totals such as NOI are not sums.
   - Confidence when the chosen AI spec failed C3 (soft) = 0.65; this value is not in the prompt.
8. **Tooling:** `dry_run.py --table-path`; `eval_dev.py` path label `table:<chosen>`.

## SELF-AUDIT

1. **Steps:**
   - Part A: profile / spec / execute / checks + tests.
   - Part B: heuristic + `simulate_tables.py` → `logs/P6_free_gate.md`.
   - Part C: prompt, pipeline, switch, dry run, this plan.
   - Evidence: the tables above and the pytest list.
2. **Decisions not in the prompt:** deviations 1–8, plus:
   - the header-merge rule (a 2-row header only when the upper row spans more than half the header and has no `label:` cells);
   - the region gap (3 blank rows);
   - the preview cell clip (40 chars);
   - the repair message text;
   - the realistic $ estimate (80% of the fuse tokens in, 700 out).
3. **Deviations:** see the list above. No paid run; no stack change.
4. **Numbers:** all from `logs/P6_free_gate.md` (`simulate_tables.py`, n = 1 per doc, scored by `eval_dev.score_doc`) and the dry-run output above. Test counts are from pytest.
5. **Tests:** 502 before → 36 new (35 in `tests/test_tables.py`, 1 in `tests/test_shipped_config.py`) → 538 passed.
6. **Frozen and outputs:**
   - `contract/`, `tools/validate.py`, `ASSIGNMENT.md` untouched (pre-commit frozen-hash guard passed).
   - `outputs/` not changed; `tools/validate.py outputs/ --schema-dir sample/schemas` exit 0 (8/8 valid).
7. **Held-out seal:** lease_003 and budget_001 were never opened. Scripts refuse them. budget_001 is a PDF and lease_003 single-value, so neither takes this path.
8. **Safety:**
   - no keys;
   - no sample values, sheet names or header texts in code, prompts, tests or logs (the reports print field names, scores, counts and column letters only);
   - the AI prompt example is an invented parts ledger;
   - rules are structural and generic;
   - no guard blocks;
   - stack untouched;
   - pre-commit passed on all tracked files and on the new files.
9. **LLM calls / spend:** 0 calls, $0.00 in S1. **RUNNING TOTAL $0.480041** (unchanged).
10. **Open items:**
    1. **Selection risk: resolved by rule (a)** (checks + 2 × filled fraction, hard fails dropped, ties go to the AI). Filled fraction counts fields with ≥ 1 non-null value, not correctness. An AI spec that fills a field from a wrong column still earns the fill points; C4 catches type clashes, but not a wrong column of the right type.
    2. Rent-roll heuristic: 21 extra rows (`key_nonempty`); `key_matches_shape` in an AI spec would remove them.
    3. P8b: the field compiler types `resident_name` as integer (description noun "units"); the baseline and smart paths are unaffected by the table fix.
    4. PDF tables (held-out budget) stay on the baseline (T-4).

## Verification after (a)/(b)

```
uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 138 files already formatted
uv run pytest -q               -> 538 passed, 1 warning, 95 subtests passed in 52.68s
uv run pre-commit run --all-files + --files <new files>  -> all hooks Passed
uv run python scripts/dry_run.py --table-path spec       -> dry run PASSED (6 docs); t12_001 and
    rentroll_001 path=table_spec (14,080 / 14,285 est. tokens, 1 call, est$ 0.0015), others baseline
uv run python tools/validate.py outputs/ --schema-dir sample/schemas  -> exit 0
```

## PLAN STOP — draft commit lines (PowerShell, one line each, no trailer, no file in two commits)

```
git add tests/test_tables.py tests/test_shipped_config.py; git commit -m "test: table profiler, spec grammar, executor, checks"
git add app/tables/__init__.py app/tables/profile.py app/tables/spec.py app/tables/execute.py app/tables/checks.py app/readers/xlsx_reader.py; git commit -m "feat: table profiler, spec grammar, executor and checks"
git add app/tables/heuristic.py scripts/simulate_tables.py; git commit -m "feat: heuristic table spec and free table simulation"
git add app/pipeline/table_spec.py app/config.py app/worker.py compose.yaml scripts/dry_run.py scripts/eval_dev.py; git commit -m "feat: AI table spec path behind a switch (default baseline)"
git add logs/P6_plan.md logs/P6_free_gate.md; git commit -m "chore(process): P6 plan and free gate"
```
