# DEV eval (baseline)

Run `cbd8115-dirty` · 2026-11-08T03:28:56Z · pipeline `table-spec-v1` · model `anthropic/claude-haiku-5.5` · p6-spec-r2

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rentroll_001 | SUCCESS | True | 0.989 | 325/325 | 19 | 0 | 44 | 0/0 | 0.00116 | 0.00116 | 5.4 |  |
| t12_001 | SUCCESS | True | 0.094 | 119/119 | 119 | 1067 | 0 | 0/0 | 0.00246 | 0.00246 | 6.6 |  |

**Mean score 0.541 over n = 2 DEV docs** · paid $0.00362 (computed $0.00362) · uncached $0.00362 · **$0.00181/doc uncached** · p50 latency 6.0 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| rentroll_001 | date | 927 | 0 | 0 | 0 |
| rentroll_001 | null | 373 | 0 | 0 | 44 |
| rentroll_001 | number | 2234 | 19 | 0 | 0 |
| rentroll_001 | text | 1928 | 0 | 0 | 0 |
| t12_001 | date | 0 | 0 | 238 | 0 |
| t12_001 | number | 0 | 0 | 476 | 0 |
| t12_001 | text | 123 | 119 | 353 | 0 |

## Per-field scores (field names only)

### rentroll_001 (0.989)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| resident_name | 0.93 | 0 | 0 | 22 |
| balance | 0.93 | 0 | 0 | 22 |
| monthly_rent | 0.96 | 13 | 0 | 0 |
| monthly_other_charges | 0.98 | 6 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| report_period | 1.00 | 0 | 0 | 0 |
| unit_number | 1.00 | 0 | 0 | 0 |
| unit_type_code | 1.00 | 0 | 0 | 0 |
| unit_square_feet | 1.00 | 0 | 0 | 0 |
| unit_status | 1.00 | 0 | 0 | 0 |
| market_rent | 1.00 | 0 | 0 | 0 |
| monthly_total_charges | 1.00 | 0 | 0 | 0 |
| deposit_held | 1.00 | 0 | 0 | 0 |
| move_in_date | 1.00 | 0 | 0 | 0 |
| lease_start_date | 1.00 | 0 | 0 | 0 |
| lease_end_date | 1.00 | 0 | 0 | 0 |
| expected_move_out_date | 1.00 | 0 | 0 | 0 |

### t12_001 (0.094)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 119 | 0 | 0 |
| period_start | 0.00 | 0 | 119 | 0 |
| period_end | 0.00 | 0 | 119 | 0 |
| line_item | 0.00 | 0 | 119 | 0 |
| amount_total | 0.00 | 0 | 119 | 0 |
| amount_first_month | 0.00 | 0 | 119 | 0 |
| amount_last_month | 0.00 | 0 | 119 | 0 |
| months_with_activity | 0.00 | 0 | 119 | 0 |
| section | 0.02 | 0 | 117 | 0 |
| category | 0.02 | 0 | 117 | 0 |
| gl_code | 1.00 | 0 | 0 | 0 |

