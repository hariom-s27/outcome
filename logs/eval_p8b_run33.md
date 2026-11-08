# DEV eval (baseline)

Run `fc5e6f1-dirty` · 2026-11-08T05:48:40Z · pipeline `baseline-v1` · model `anthropic/claude-haiku-5.5` · p8b-locate-lease-r33

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | SUCCESS | True | 0.250 | 1/1 | 0 | 30 | 0 | 0/0 | 0.00550 | 0.00550 | 28.3 |  scan_pages=locate:located |

**Mean score 0.250 over n = 1 DEV docs** · paid $0.00550 (computed $0.00550) · uncached $0.00550 · **$0.00550/doc uncached** · p50 latency 28.3 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| lease_001 | bool | 3 | 0 | 0 | 0 |
| lease_001 | date | 0 | 0 | 4 | 0 |
| lease_001 | list | 0 | 0 | 5 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 1 | 0 | 8 | 0 |
| lease_001 | text | 0 | 0 | 13 | 0 |

## Per-field scores (field names only)

### lease_001 (0.250)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| tenant_name | 0.00 | 0 | 1 | 0 |
| landlord_legal_name | 0.00 | 0 | 1 | 0 |
| property_name | 0.00 | 0 | 1 | 0 |
| building_address | 0.00 | 0 | 1 | 0 |
| premises | 0.00 | 0 | 1 | 0 |
| rentable_square_footage | 0.00 | 0 | 1 | 0 |
| pro_rata_share | 0.00 | 0 | 1 | 0 |
| permitted_use | 0.00 | 0 | 1 | 0 |
| lease_execution_date | 0.00 | 0 | 1 | 0 |
| lease_commencement_date | 0.00 | 0 | 1 | 0 |
| rent_commencement_date | 0.00 | 0 | 1 | 0 |
| lease_expiration_date | 0.00 | 0 | 1 | 0 |
| lease_term_months | 0.00 | 0 | 1 | 0 |
| rent_schedule_start_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_end_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_monthly_rent | 0.00 | 0 | 1 | 0 |
| rent_schedule_annual_rent_per_rsf | 0.00 | 0 | 1 | 0 |
| total_base_rent | 0.00 | 0 | 1 | 0 |
| base_rent_escalation | 0.00 | 0 | 1 | 0 |
| free_rent_months | 0.00 | 0 | 1 | 0 |
| security_deposit_amount | 0.00 | 0 | 1 | 0 |
| expense_structure | 0.00 | 0 | 1 | 0 |
| base_year_expenses | 0.00 | 0 | 1 | 0 |
| base_year_taxes | 0.00 | 0 | 1 | 0 |
| electricity_provision | 0.00 | 0 | 1 | 0 |
| right_to_sublet | 0.00 | 0 | 1 | 0 |
| guarantor_name | 0.00 | 0 | 1 | 0 |
| broker_names | 0.00 | 0 | 1 | 0 |
| late_fee | 0.00 | 0 | 1 | 0 |
| holdover_rent | 0.00 | 0 | 1 | 0 |
| letter_of_credit_required | 1.00 | 0 | 0 | 0 |
| parking_spaces | 1.00 | 0 | 0 | 0 |
| parking_monthly_charge | 1.00 | 0 | 0 | 0 |
| ti_allowance_total | 1.00 | 0 | 0 | 0 |
| renewal_option_exists | 1.00 | 0 | 0 | 0 |
| renewal_options_count | 1.00 | 0 | 0 | 0 |
| renewal_term_months | 1.00 | 0 | 0 | 0 |
| renewal_notice_months | 1.00 | 0 | 0 | 0 |
| early_termination_right | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |

