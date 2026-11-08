# DEV eval (baseline)

Run `1a88495-dirty` · 2026-11-08T15:39:37Z · pipeline `baseline-v1` · model `-` · P9b screen sonnet ceiling DEV+E0

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | PARTIAL | True | 0.150 | 1/1 | 0 | 34 | 0 | 0/0 | 0.00000 | 0.00000 | 0.9 | doc_llm_cap |
| lease_002 | PARTIAL | True | 0.300 | 1/1 | 0 | 28 | 0 | 0/0 | 0.00000 | 0.00000 | 0.9 | doc_llm_cap |
| om_001 | PARTIAL | True | 0.172 | 1/1 | 0 | 24 | 0 | 0/0 | 0.00000 | 0.00000 | 3.6 | doc_llm_cap |

**Mean score 0.207 over n = 3 DEV+SYN docs** · paid $0.00000 (computed $0.00000) · uncached $0.00000 · **$0.00000/doc uncached** · p50 latency 0.9 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| lease_001 | bool | 0 | 0 | 3 | 0 |
| lease_001 | date | 0 | 0 | 4 | 0 |
| lease_001 | list | 0 | 0 | 5 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 0 | 0 | 9 | 0 |
| lease_001 | text | 0 | 0 | 13 | 0 |
| lease_002 | bool | 0 | 0 | 3 | 0 |
| lease_002 | date | 0 | 0 | 4 | 0 |
| lease_002 | list | 0 | 0 | 5 | 0 |
| lease_002 | null | 12 | 0 | 0 | 0 |
| lease_002 | number | 0 | 0 | 6 | 0 |
| lease_002 | text | 0 | 0 | 10 | 0 |
| om_001 | list | 0 | 0 | 1 | 0 |
| om_001 | null | 5 | 0 | 0 | 0 |
| om_001 | number | 0 | 0 | 14 | 0 |
| om_001 | text | 0 | 0 | 9 | 0 |

## Per-field scores (field names only)

### lease_001 (0.150)

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
| letter_of_credit_required | 0.00 | 0 | 1 | 0 |
| expense_structure | 0.00 | 0 | 1 | 0 |
| base_year_expenses | 0.00 | 0 | 1 | 0 |
| base_year_taxes | 0.00 | 0 | 1 | 0 |
| electricity_provision | 0.00 | 0 | 1 | 0 |
| renewal_option_exists | 0.00 | 0 | 1 | 0 |
| renewal_options_count | 0.00 | 0 | 1 | 0 |
| early_termination_right | 0.00 | 0 | 1 | 0 |
| right_to_sublet | 0.00 | 0 | 1 | 0 |
| guarantor_name | 0.00 | 0 | 1 | 0 |
| broker_names | 0.00 | 0 | 1 | 0 |
| late_fee | 0.00 | 0 | 1 | 0 |
| holdover_rent | 0.00 | 0 | 1 | 0 |
| parking_spaces | 1.00 | 0 | 0 | 0 |
| parking_monthly_charge | 1.00 | 0 | 0 | 0 |
| ti_allowance_total | 1.00 | 0 | 0 | 0 |
| renewal_term_months | 1.00 | 0 | 0 | 0 |
| renewal_notice_months | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |

### lease_002 (0.300)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| tenant_name | 0.00 | 0 | 1 | 0 |
| landlord_legal_name | 0.00 | 0 | 1 | 0 |
| property_name | 0.00 | 0 | 1 | 0 |
| building_address | 0.00 | 0 | 1 | 0 |
| premises | 0.00 | 0 | 1 | 0 |
| rentable_square_footage | 0.00 | 0 | 1 | 0 |
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
| free_rent_months | 0.00 | 0 | 1 | 0 |
| security_deposit_amount | 0.00 | 0 | 1 | 0 |
| letter_of_credit_required | 0.00 | 0 | 1 | 0 |
| electricity_provision | 0.00 | 0 | 1 | 0 |
| renewal_option_exists | 0.00 | 0 | 1 | 0 |
| renewal_options_count | 0.00 | 0 | 1 | 0 |
| early_termination_right | 0.00 | 0 | 1 | 0 |
| right_to_sublet | 0.00 | 0 | 1 | 0 |
| broker_names | 0.00 | 0 | 1 | 0 |
| late_fee | 0.00 | 0 | 1 | 0 |
| holdover_rent | 0.00 | 0 | 1 | 0 |
| pro_rata_share | 1.00 | 0 | 0 | 0 |
| base_rent_escalation | 1.00 | 0 | 0 | 0 |
| expense_structure | 1.00 | 0 | 0 | 0 |
| base_year_expenses | 1.00 | 0 | 0 | 0 |
| base_year_taxes | 1.00 | 0 | 0 | 0 |
| parking_spaces | 1.00 | 0 | 0 | 0 |
| parking_monthly_charge | 1.00 | 0 | 0 | 0 |
| ti_allowance_total | 1.00 | 0 | 0 | 0 |
| renewal_term_months | 1.00 | 0 | 0 | 0 |
| renewal_notice_months | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |
| guarantor_name | 1.00 | 0 | 0 | 0 |

### om_001 (0.172)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 0 | 1 | 0 |
| address | 0.00 | 0 | 1 | 0 |
| city | 0.00 | 0 | 1 | 0 |
| state | 0.00 | 0 | 1 | 0 |
| zip_code | 0.00 | 0 | 1 | 0 |
| county | 0.00 | 0 | 1 | 0 |
| submarket | 0.00 | 0 | 1 | 0 |
| broker_name | 0.00 | 0 | 1 | 0 |
| units | 0.00 | 0 | 1 | 0 |
| year_built | 0.00 | 0 | 1 | 0 |
| building_type | 0.00 | 0 | 1 | 0 |
| number_of_buildings | 0.00 | 0 | 1 | 0 |
| stories | 0.00 | 0 | 1 | 0 |
| rentable_sf | 0.00 | 0 | 1 | 0 |
| average_unit_sf | 0.00 | 0 | 1 | 0 |
| site_acres | 0.00 | 0 | 1 | 0 |
| parking_spaces | 0.00 | 0 | 1 | 0 |
| parking_ratio | 0.00 | 0 | 1 | 0 |
| occupancy_pct | 0.00 | 0 | 1 | 0 |
| average_in_place_rent | 0.00 | 0 | 1 | 0 |
| market_rent | 0.00 | 0 | 1 | 0 |
| market_rent_psf | 0.00 | 0 | 1 | 0 |
| unit_types | 0.00 | 0 | 1 | 0 |
| noi_proforma | 0.00 | 0 | 1 | 0 |
| year_renovated | 1.00 | 0 | 0 | 0 |
| asking_price | 1.00 | 0 | 0 | 0 |
| price_per_unit | 1.00 | 0 | 0 | 0 |
| asking_cap_rate | 1.00 | 0 | 0 | 0 |
| noi_t12 | 1.00 | 0 | 0 | 0 |

