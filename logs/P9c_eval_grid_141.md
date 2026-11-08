# DEV eval (baseline)

Run `1b3f22f` · 2026-11-08T16:18:52Z · pipeline `table-spec-v1` · model `anthropic/claude-haiku-5.5` · P9c grid run 1

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syn_budget_pdf | SUCCESS | True | 0.987 | 43/43 | 8 | 0 | 0 | 0/0 | 0.00086 | 0.00086 | 6.3 |  |
| syn_rentroll_pdf | SUCCESS | True | 0.986 | 30/30 | 0 | 0 | 7 | 0/0 | 0.00081 | 0.00081 | 3.9 |  |

**Mean score 0.987 over n = 2 SYN docs** · paid $0.00168 (computed $0.00168) · uncached $0.00168 · **$0.00084/doc uncached** · p50 latency 5.1 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| syn_budget_pdf | null | 18 | 0 | 0 | 0 |
| syn_budget_pdf | number | 385 | 0 | 0 | 0 |
| syn_budget_pdf | text | 191 | 8 | 0 | 0 |
| syn_rentroll_pdf | date | 77 | 0 | 0 | 0 |
| syn_rentroll_pdf | null | 43 | 0 | 0 | 7 |
| syn_rentroll_pdf | number | 210 | 0 | 0 | 0 |
| syn_rentroll_pdf | text | 173 | 0 | 0 | 0 |

## Per-field scores (field names only)

### syn_budget_pdf (0.987)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| section | 0.81 | 8 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| property_rsf | 1.00 | 0 | 0 | 0 |
| budget_year | 1.00 | 0 | 0 | 0 |
| gl_code | 1.00 | 0 | 0 | 0 |
| line_item | 1.00 | 0 | 0 | 0 |
| prior_year_budget | 1.00 | 0 | 0 | 0 |
| prior_year_reforecast | 1.00 | 0 | 0 | 0 |
| budget | 1.00 | 0 | 0 | 0 |
| reforecast_vs_prior_budget_variance | 1.00 | 0 | 0 | 0 |
| reforecast_vs_prior_budget_pct | 1.00 | 0 | 0 | 0 |
| budget_vs_reforecast_variance | 1.00 | 0 | 0 | 0 |
| budget_vs_reforecast_pct | 1.00 | 0 | 0 | 0 |
| explanation_of_variance | 1.00 | 0 | 0 | 0 |

### syn_rentroll_pdf (0.986)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| resident_name | 0.77 | 0 | 0 | 7 |
| property_name | 1.00 | 0 | 0 | 0 |
| report_period | 1.00 | 0 | 0 | 0 |
| unit_number | 1.00 | 0 | 0 | 0 |
| unit_type_code | 1.00 | 0 | 0 | 0 |
| unit_square_feet | 1.00 | 0 | 0 | 0 |
| unit_status | 1.00 | 0 | 0 | 0 |
| market_rent | 1.00 | 0 | 0 | 0 |
| monthly_rent | 1.00 | 0 | 0 | 0 |
| monthly_other_charges | 1.00 | 0 | 0 | 0 |
| monthly_total_charges | 1.00 | 0 | 0 | 0 |
| deposit_held | 1.00 | 0 | 0 | 0 |
| balance | 1.00 | 0 | 0 | 0 |
| move_in_date | 1.00 | 0 | 0 | 0 |
| lease_start_date | 1.00 | 0 | 0 | 0 |
| lease_end_date | 1.00 | 0 | 0 | 0 |
| expected_move_out_date | 1.00 | 0 | 0 | 0 |

