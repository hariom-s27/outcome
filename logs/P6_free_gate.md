# P6 Part B: free table gate ($0, no LLM calls)

Heuristic spec (header match, no model) -> executor on every line -> checks -> `eval_dev.score_doc` (tools/validate.py `score()`, mean of per-field means). Old = the shipped `outputs/<doc>.json` re-scored the same way (n = 1 each).

## Scores

| Doc | path applies | data lines | heuristic score | old score | delta | rows pred/truth | checks passed | filled | rank | hard fail | valid |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rentroll_001 | True (long_table) | 3048 | 0.7191 | 0.1095 | +0.6096 | 346/325 | 5 | 0.8571 | 6.7143 | False | True |
| t12_001 | True (long_table) | 141 | 0.0773 | 0.0458 | +0.0315 | 140/119 | 4 | 0.0000 | 4.0000 | False | True |

## Checks

| Doc | check | passed | value | detail |
|---|---|---|---|---|
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

- rentroll_001: key column A, header row found True, duplicates 5; child 2345, record 351, skipped-formula_sum_rows 8, skipped-header_repeat 1, skipped-section_header 3, skipped-total_like 340
- t12_001: key column A, header row found True, duplicates 0; record 140, skipped-section_header 1

## Per-field scores (field names only)

| Doc | field | heuristic source | heuristic | old |
|---|---|---|---|---|
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
