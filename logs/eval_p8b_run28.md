# DEV eval (baseline)

Run `fc5e6f1-dirty` · 2026-11-08T05:43:28Z · pipeline `baseline-v1` · model `anthropic/claude-haiku-5.5` · p8b-old-lease-r28

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | SUCCESS | True | 0.650 | 1/1 | 6 | 8 | 0 | 0/0 | 0.00308 | 0.00308 | 18.3 |  |

**Mean score 0.650 over n = 1 DEV docs** · paid $0.00308 (computed $0.00308) · uncached $0.00308 · **$0.00308/doc uncached** · p50 latency 18.3 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| lease_001 | bool | 2 | 1 | 0 | 0 |
| lease_001 | date | 4 | 0 | 0 | 0 |
| lease_001 | list | 1 | 0 | 4 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 7 | 0 | 2 | 0 |
| lease_001 | text | 6 | 5 | 2 | 0 |

## Per-field scores (field names only)

### lease_001 (0.650)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| rent_schedule_start_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_end_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_monthly_rent | 0.00 | 0 | 1 | 0 |
| rent_schedule_annual_rent_per_rsf | 0.00 | 0 | 1 | 0 |
| total_base_rent | 0.00 | 0 | 1 | 0 |
| base_rent_escalation | 0.00 | 0 | 1 | 0 |
| free_rent_months | 0.00 | 0 | 1 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| electricity_provision | 0.00 | 1 | 0 | 0 |
| early_termination_right | 0.00 | 1 | 0 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
| guarantor_name | 0.00 | 0 | 1 | 0 |
| late_fee | 0.00 | 1 | 0 | 0 |
| holdover_rent | 0.00 | 1 | 0 | 0 |
| tenant_name | 1.00 | 0 | 0 | 0 |
| landlord_legal_name | 1.00 | 0 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| building_address | 1.00 | 0 | 0 | 0 |
| premises | 1.00 | 0 | 0 | 0 |
| rentable_square_footage | 1.00 | 0 | 0 | 0 |
| pro_rata_share | 1.00 | 0 | 0 | 0 |
| permitted_use | 1.00 | 0 | 0 | 0 |
| lease_execution_date | 1.00 | 0 | 0 | 0 |
| lease_commencement_date | 1.00 | 0 | 0 | 0 |
| rent_commencement_date | 1.00 | 0 | 0 | 0 |
| lease_expiration_date | 1.00 | 0 | 0 | 0 |
| lease_term_months | 1.00 | 0 | 0 | 0 |
| security_deposit_amount | 1.00 | 0 | 0 | 0 |
| letter_of_credit_required | 1.00 | 0 | 0 | 0 |
| base_year_expenses | 1.00 | 0 | 0 | 0 |
| base_year_taxes | 1.00 | 0 | 0 | 0 |
| parking_spaces | 1.00 | 0 | 0 | 0 |
| parking_monthly_charge | 1.00 | 0 | 0 | 0 |
| ti_allowance_total | 1.00 | 0 | 0 | 0 |
| renewal_option_exists | 1.00 | 0 | 0 | 0 |
| renewal_options_count | 1.00 | 0 | 0 | 0 |
| renewal_term_months | 1.00 | 0 | 0 | 0 |
| renewal_notice_months | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |
| broker_names | 1.00 | 0 | 0 | 0 |

