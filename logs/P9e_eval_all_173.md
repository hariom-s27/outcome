# DEV eval (baseline)

Run `662f00a-dirty` · 2026-11-08T18:00:08Z · pipeline `baseline-v1` · model `anthropic/claude-haiku-5.5` · P9e scan all run 3

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | SUCCESS | True | 0.850 | 1/1 | 6 | 0 | 0 | 0/0 | 0.00672 | 0.00672 | 24.2 |  scan_pages=all:25/25 |
| syn_lease_scan | SUCCESS | True | 0.925 | 1/1 | 3 | 0 | 0 | 0/0 | 0.00556 | 0.00556 | 15.6 |  scan_pages=all:15/15 |

**Mean score 0.887 over n = 2 DEV+SYN docs** · paid $0.01229 (computed $0.01229) · uncached $0.01229 · **$0.00614/doc uncached** · p50 latency 19.9 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| lease_001 | bool | 3 | 0 | 0 | 0 |
| lease_001 | date | 4 | 0 | 0 | 0 |
| lease_001 | list | 5 | 0 | 0 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 9 | 0 | 0 | 0 |
| lease_001 | text | 7 | 6 | 0 | 0 |
| syn_lease_scan | bool | 3 | 0 | 0 | 0 |
| syn_lease_scan | date | 4 | 0 | 0 | 0 |
| syn_lease_scan | list | 7 | 0 | 0 | 0 |
| syn_lease_scan | null | 5 | 0 | 0 | 0 |
| syn_lease_scan | number | 6 | 1 | 0 | 0 |
| syn_lease_scan | text | 12 | 2 | 0 | 0 |

## Per-field scores (field names only)

### lease_001 (0.850)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| electricity_provision | 0.00 | 1 | 0 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
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
| rent_schedule_start_dates | 1.00 | 0 | 0 | 0 |
| rent_schedule_end_dates | 1.00 | 0 | 0 | 0 |
| rent_schedule_monthly_rent | 1.00 | 0 | 0 | 0 |
| rent_schedule_annual_rent_per_rsf | 1.00 | 0 | 0 | 0 |
| total_base_rent | 1.00 | 0 | 0 | 0 |
| free_rent_months | 1.00 | 0 | 0 | 0 |
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
| early_termination_right | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |
| guarantor_name | 1.00 | 0 | 0 | 0 |
| broker_names | 1.00 | 0 | 0 | 0 |

### syn_lease_scan (0.925)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| total_base_rent | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| electricity_provision | 0.00 | 1 | 0 | 0 |
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
| rent_schedule_start_dates | 1.00 | 0 | 0 | 0 |
| rent_schedule_end_dates | 1.00 | 0 | 0 | 0 |
| rent_schedule_monthly_rent | 1.00 | 0 | 0 | 0 |
| rent_schedule_annual_rent_per_rsf | 1.00 | 0 | 0 | 0 |
| base_rent_escalation | 1.00 | 0 | 0 | 0 |
| free_rent_months | 1.00 | 0 | 0 | 0 |
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
| early_termination_right | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |
| right_to_sublet | 1.00 | 0 | 0 | 0 |
| guarantor_name | 1.00 | 0 | 0 | 0 |
| broker_names | 1.00 | 0 | 0 | 0 |
| late_fee | 1.00 | 0 | 0 | 0 |
| holdover_rent | 1.00 | 0 | 0 | 0 |

