# P6b: free table gate (heuristic recipe, $0, no LLM calls)

Heuristic spec (header match, no model) -> executor on every line -> checks -> `eval_dev.score_doc` (tools/validate.py `score()`, mean of per-field means). Old = the shipped `outputs/<doc>.json` re-scored the same way (n = 1 each).

## Scores

| Doc | path applies | data lines | heuristic score | old score | delta | rows pred/truth | checks passed | filled | rank | hard fail | valid |
|---|---|---|---|---|---|---|---|---|---|---|---|
| boxscore_001 | True (table) | 10 | 0.9000 | 1.0000 | -0.1000 | 10/10 | 4 | 1.0000 | 6.0000 | False | True |
| rentroll_001 | True (table) | 3048 | 0.7191 | 0.1095 | +0.6096 | 346/325 | 5 | 0.8571 | 6.7143 | False | True |
| t12_001 | True (table) | 141 | 0.0773 | 0.0458 | +0.0315 | 140/119 | 4 | 0.0000 | 4.0000 | False | True |

## Checks

| Doc | check | passed | value | detail |
|---|---|---|---|---|
| boxscore_001 | C1 | True | 1.0 | unique=1.0, shape=1.0 |
| boxscore_001 | C2 | True | 0.0 | unexplained=0, lines=10 |
| boxscore_001 | C3 | None | 0.0 | checked=0 |
| boxscore_001 | C4 | True | 1.0 | fields_below={} |
| boxscore_001 | C5 | True | 10.0 | rows=10, total_keys=0 |
| rentroll_001 | C1 | True | 0.9402 | unique=0.9858, shape=0.9402 |
| rentroll_001 | C2 | True | 0.0 | unexplained=0, lines=3048 |
| rentroll_001 | C3 | True | 0.9475 | checked=362, matched=343 |
| rentroll_001 | C4 | True | 0.9565 | fields_below={} |
| rentroll_001 | C5 | True | 346.0 | rows=346, total_keys=0 |
| t12_001 | C1 | True | 1.0 | unique=1.0, shape=1.0 |
| t12_001 | C2 | True | 0.0 | unexplained=0, lines=141 |
| t12_001 | C3 | None | 0.0 | checked=0 |
| t12_001 | C4 | True | 1.0 | fields_below={} |
| t12_001 | C5 | True | 140.0 | rows=140, total_keys=0 |

## Lines by disposition

- boxscore_001: key column A, header row found True, duplicates 0; record 10
- rentroll_001: key column A, header row found True, duplicates 5; child 2345, record 351, skipped-formula_sum_rows 8, skipped-header_repeat 1, skipped-section_header 3, skipped-total_like 340
- t12_001: key column A, header row found True, duplicates 0; record 140, skipped-section_header 1

## Per-field scores (field names only)

| Doc | field | heuristic source | heuristic | old |
|---|---|---|---|---|
| boxscore_001 | admin | col O (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | avail | col L (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | avg_rent | col E (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | avg_sq_ft | col D (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | code | key | 1.00 | 1.00 |
| boxscore_001 | date | none | 0.00 | 1.00 |
| boxscore_001 | down | col N (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | model | col M (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | name | col B (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | notice_rented | col J (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | notice_unrented | col K (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | occ_no_notice | col G (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | p_occ_wornonrev | col Q (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | p_trend | col S (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | percent_leased | col R (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | percent_occupied | col P (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | property_name | none | 0.00 | 1.00 |
| boxscore_001 | units | col F (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | vacant_rented | col H (first_nonempty) | 1.00 | 1.00 |
| boxscore_001 | vacant_unrented | col I (first_nonempty) | 1.00 | 1.00 |
| rentroll_001 | balance | col J (first_nonempty) | 0.88 | 0.10 |
| rentroll_001 | deposit_held | col K (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | expected_move_out_date | col O (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | lease_end_date | col N (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | lease_start_date | col M (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | market_rent | col F (first_nonempty) | 0.94 | 0.10 |
| rentroll_001 | monthly_other_charges | col I (first_nonempty) | 0.14 | 0.11 |
| rentroll_001 | monthly_rent | none | 0.00 | 0.11 |
| rentroll_001 | monthly_total_charges | none | 0.00 | 0.11 |
| rentroll_001 | move_in_date | col L (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | property_name | doc | 0.94 | 0.11 |
| rentroll_001 | report_period | doc | 0.00 | 0.11 |
| rentroll_001 | resident_name | col E (first_nonempty) | 0.88 | 0.11 |
| rentroll_001 | unit_number | key | 0.94 | 0.11 |
| rentroll_001 | unit_square_feet | col C (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | unit_status | col D (first_nonempty) | 0.94 | 0.11 |
| rentroll_001 | unit_type_code | col B (first_nonempty) | 0.94 | 0.11 |
| t12_001 | amount_first_month | none | 0.00 | 0.05 |
| t12_001 | amount_last_month | none | 0.00 | 0.05 |
| t12_001 | amount_total | none | 0.00 | 0.05 |
| t12_001 | category | none | 0.00 | 0.05 |
| t12_001 | gl_code | key | 0.85 | 0.05 |
| t12_001 | line_item | none | 0.00 | 0.05 |
| t12_001 | months_with_activity | none | 0.00 | 0.05 |
| t12_001 | period_end | none | 0.00 | 0.05 |
| t12_001 | period_start | none | 0.00 | 0.05 |
| t12_001 | property_name | none | 0.00 | 0.00 |
| t12_001 | section | none | 0.00 | 0.05 |

## T-16b ship-rule targets (old scores re-scored from shipped outputs by this script)

- rentroll_001: old 0.1095 -> 3-run mean must be >= 0.0845 (no regression)
- t12_001: old 0.0458 -> 3-run mean must be >= 0.0208 (no regression)
- mean of the two gains >= +0.05, i.e. (rentroll mean + t12 mean) >= 0.2553
- boxscore_001: old 1.0000 -> must stay >= 0.9750
- free gate (heuristic only, n = 1) against T-16b: gains +0.6096 / +0.0315, mean +0.3205

## P6b reading (written by Claude, numbers from the tables above)

Command: `uv run python scripts/simulate_tables.py --docs boxscore_001 rentroll_001 t12_001 --title "..." --report logs/P6b_free_gate.md`

- **B-2 routing:** boxscore_001 now takes the recipe path (`applies = True (table)`, 10 data lines).
  Before P6b it took the baseline (`short_table`).
- **boxscore_001, heuristic recipe alone:** 0.9000 vs old 1.0000 (the old score is a cache
  replay, `logs/P6_report.md`). Rows 10/10, C1/C2/C4/C5 pass, C3 not applicable, no hard fail.
  18 of 20 fields score 1.00. The 2 misses are `date` and `property_name` (source `none`: the
  heuristic finds no label cell for them). These are document-level cells. The heuristic has no
  rule for them here, but the AI recipe can name them in `doc_fields`. The live runs in Part B
  will show whether the AI recipe or the B-4 merge fills them.
  The heuristic alone is 0.0750 below the 0.9750 floor, so the floor depends on the AI recipe.
- **No regression:** rentroll_001 0.7191 and t12_001 0.0773 are the same as the P6 free gate
  (`logs/P6_free_gate.md`). The heuristic builder did not change in P6b. Salvage, merge and
  retry only act when there is an AI spec, so a $0 run cannot exercise them.
- No LLM calls, $0.
