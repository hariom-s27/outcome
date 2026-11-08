# P5c Part A: offline hybrid simulation ($0, no LLM calls)

Merge rule H-2: smart cell if non-null and reason in {computed_fixed, computed_ok, ok, ok_partial}; else the baseline cell (confidence 0.5 if non-null). Smart = P5b runs `6db0488/run1`, `6db0488-dirty/run2`, `6db0488-dirty/run3`; baseline = shipped `outputs/<doc>.json` (P2, n = 1). Score = `tools/validate.py score()` via `eval_dev.score_doc` (mean of per-field means).

## Scores

| Doc | Hybrid r1 | Hybrid r2 | Hybrid r3 | **Hybrid mean** | Old (baseline) | Smart (re-scored) mean | P5b smart mean | Floor |
|---|---|---|---|---|---|---|---|---|
| lease_001 | 0.7369 | 0.7036 | 0.6869 | **0.7091** | 0.7000 | 0.5925 | 0.5925 | 0.6750 |
| lease_002 | 0.8000 | 0.7750 | 0.7750 | **0.7833** | 0.7750 | 0.7083 | 0.7083 | 0.7500 |
| om_001 | 0.9655 | 0.9483 | 0.9483 | **0.9540** | 0.9655 | 0.9195 | 0.9195 | 0.9405 |

## Sources, hallucinations, validity (per run)

| Doc | Run | from smart | from baseline | baseline non-null | halluc. hybrid | halluc. smart | valid | smart reasons sent to baseline |
|---|---|---|---|---|---|---|---|---|
| lease_001 | 1 | 18 | 22 | 14 | 0 | 0 | True | false_unquoted 3, list_unverified 1, model_null 10, quote_missing 2, value_not_in_quote 6 |
| lease_001 | 2 | 17 | 23 | 14 | 0 | 0 | True | false_unquoted 3, list_unverified 2, model_null 10, quote_missing 2, value_not_in_quote 6 |
| lease_001 | 3 | 19 | 21 | 13 | 0 | 0 | True | false_unquoted 3, model_null 11, quote_missing 3, value_not_in_quote 4 |
| lease_002 | 1 | 17 | 23 | 13 | 1 | 0 | True | false_unquoted 3, model_null 11, part_unverified 2, quote_missing 1, quote_not_found 1, value_not_in_quote 5 |
| lease_002 | 2 | 17 | 23 | 13 | 1 | 0 | True | false_unquoted 3, list_unverified 1, model_null 12, quote_missing 1, value_not_in_quote 6 |
| lease_002 | 3 | 17 | 23 | 13 | 1 | 0 | True | false_unquoted 3, model_null 12, quote_missing 2, value_not_in_quote 6 |
| om_001 | 1 | 23 | 6 | 1 | 0 | 0 | True | model_null 6 |
| om_001 | 2 | 23 | 6 | 1 | 0 | 0 | True | model_null 6 |
| om_001 | 3 | 23 | 6 | 1 | 0 | 0 | True | model_null 5, quote_not_found 1 |

## Bar (P5-22, unchanged)

- Means: lease_001 = (0.7369 + 0.7036 + 0.6869) / 3 = 0.70913; lease_002 = (0.8000 + 0.7750 + 0.7750) / 3 = 0.78333; om_001 = (0.9655 + 0.9483 + 0.9483) / 3 = 0.95403
- Mean test: (0.70913 + 0.78333 + 0.95403) / 3 = **0.81550** vs bar 0.8385 -> FAIL
- Floor test: lease_001 0.7091 >= 0.675 (pass); lease_002 0.7833 >= 0.75 (pass); om_001 0.9540 >= 0.9405 (pass)
- **Verdict: FAIL**

## Per-field change vs old (field names only; mean over runs)

| Doc | field | old | hybrid mean | from smart (runs) |
|---|---|---|---|---|
| lease_001 | building_address | 1.00 | 0.33 | 3 |
| lease_001 | expense_structure | 1.00 | 0.67 | 1 |
| lease_001 | permitted_use | 1.00 | 0.00 | 3 |
| lease_001 | rent_schedule_end_dates | 0.00 | 0.57 | 3 |
| lease_001 | rent_schedule_monthly_rent | 0.00 | 0.22 | 2 |
| lease_001 | rent_schedule_start_dates | 0.00 | 0.57 | 3 |
| lease_001 | total_base_rent | 0.00 | 1.00 | 3 |
| lease_002 | building_address | 0.00 | 0.33 | 3 |
| om_001 | unit_types | 1.00 | 0.67 | 3 |
