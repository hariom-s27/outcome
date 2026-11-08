# DEV eval (baseline)

Run `a1b87f4-dirty` · 2026-11-08T14:19:23Z · pipeline `baseline-v1,table-spec-v1` · model `anthropic/claude-haiku-5.5` · P9a baseline v1.0 DEV run

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| boxscore_001 | SUCCESS | True | 0.950 | 10/10 | 0 | 10 | 0 | 0/0 | 0.00087 | 0.00087 | 4.0 |  |
| lease_001 | SUCCESS | True | 0.625 | 1/1 | 8 | 7 | 0 | 0/0 | 0.00309 | 0.00309 | 14.7 |  |
| lease_002 | SUCCESS | True | 0.725 | 1/1 | 9 | 0 | 2 | 0/0 | 0.00412 | 0.00412 | 11.1 |  |
| om_001 | PARTIAL | True | 0.172 | 1/1 | 0 | 24 | 0 | 0/0 | 0.00392 | 0.00392 | 17.4 | llm_unusable |
| t12_001 | SUCCESS | True | 0.094 | 119/119 | 0 | 1186 | 0 | 0/0 | 0.00122 | 0.00122 | 3.7 |  |
| rentroll_001 | SUCCESS | True | 0.989 | 325/325 | 19 | 0 | 44 | 0/0 | 0.00116 | 0.00116 | 5.9 |  |

**Mean score 0.593 over n = 6 DEV docs** · paid $0.01437 (computed $0.01437) · uncached $0.01437 · **$0.00240/doc uncached** · p50 latency 8.5 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| boxscore_001 | date | 0 | 0 | 10 | 0 |
| boxscore_001 | number | 160 | 0 | 0 | 0 |
| boxscore_001 | text | 30 | 0 | 0 | 0 |
| lease_001 | bool | 2 | 1 | 0 | 0 |
| lease_001 | date | 4 | 0 | 0 | 0 |
| lease_001 | list | 1 | 0 | 4 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 7 | 0 | 2 | 0 |
| lease_001 | text | 5 | 7 | 1 | 0 |
| lease_002 | bool | 3 | 0 | 0 | 0 |
| lease_002 | date | 3 | 1 | 0 | 0 |
| lease_002 | list | 5 | 0 | 0 | 0 |
| lease_002 | null | 10 | 0 | 0 | 2 |
| lease_002 | number | 5 | 1 | 0 | 0 |
| lease_002 | text | 3 | 7 | 0 | 0 |
| om_001 | list | 0 | 0 | 1 | 0 |
| om_001 | null | 5 | 0 | 0 | 0 |
| om_001 | number | 0 | 0 | 14 | 0 |
| om_001 | text | 0 | 0 | 9 | 0 |
| t12_001 | date | 0 | 0 | 238 | 0 |
| t12_001 | number | 0 | 0 | 476 | 0 |
| t12_001 | text | 123 | 0 | 472 | 0 |
| rentroll_001 | date | 927 | 0 | 0 | 0 |
| rentroll_001 | null | 373 | 0 | 0 | 44 |
| rentroll_001 | number | 2234 | 19 | 0 | 0 |
| rentroll_001 | text | 1928 | 0 | 0 | 0 |

## Per-field scores (field names only)

### boxscore_001 (0.950)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| date | 0.00 | 0 | 10 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| code | 1.00 | 0 | 0 | 0 |
| name | 1.00 | 0 | 0 | 0 |
| avg_sq_ft | 1.00 | 0 | 0 | 0 |
| avg_rent | 1.00 | 0 | 0 | 0 |
| units | 1.00 | 0 | 0 | 0 |
| occ_no_notice | 1.00 | 0 | 0 | 0 |
| vacant_rented | 1.00 | 0 | 0 | 0 |
| vacant_unrented | 1.00 | 0 | 0 | 0 |
| notice_rented | 1.00 | 0 | 0 | 0 |
| notice_unrented | 1.00 | 0 | 0 | 0 |
| avail | 1.00 | 0 | 0 | 0 |
| model | 1.00 | 0 | 0 | 0 |
| down | 1.00 | 0 | 0 | 0 |
| admin | 1.00 | 0 | 0 | 0 |
| percent_occupied | 1.00 | 0 | 0 | 0 |
| p_occ_wornonrev | 1.00 | 0 | 0 | 0 |
| percent_leased | 1.00 | 0 | 0 | 0 |
| p_trend | 1.00 | 0 | 0 | 0 |

### lease_001 (0.625)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| building_address | 0.00 | 1 | 0 | 0 |
| rent_schedule_start_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_end_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_monthly_rent | 0.00 | 0 | 1 | 0 |
| rent_schedule_annual_rent_per_rsf | 0.00 | 0 | 1 | 0 |
| total_base_rent | 0.00 | 0 | 1 | 0 |
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
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

### lease_002 (0.725)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 1 | 0 | 0 |
| building_address | 0.00 | 1 | 0 | 0 |
| permitted_use | 0.00 | 1 | 0 | 0 |
| rent_commencement_date | 0.00 | 1 | 0 | 0 |
| total_base_rent | 0.00 | 1 | 0 | 0 |
| base_rent_escalation | 0.00 | 0 | 0 | 1 |
| expense_structure | 0.00 | 0 | 0 | 1 |
| electricity_provision | 0.00 | 1 | 0 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
| late_fee | 0.00 | 1 | 0 | 0 |
| holdover_rent | 0.00 | 1 | 0 | 0 |
| tenant_name | 1.00 | 0 | 0 | 0 |
| landlord_legal_name | 1.00 | 0 | 0 | 0 |
| premises | 1.00 | 0 | 0 | 0 |
| rentable_square_footage | 1.00 | 0 | 0 | 0 |
| pro_rata_share | 1.00 | 0 | 0 | 0 |
| lease_execution_date | 1.00 | 0 | 0 | 0 |
| lease_commencement_date | 1.00 | 0 | 0 | 0 |
| lease_expiration_date | 1.00 | 0 | 0 | 0 |
| lease_term_months | 1.00 | 0 | 0 | 0 |
| rent_schedule_start_dates | 1.00 | 0 | 0 | 0 |
| rent_schedule_end_dates | 1.00 | 0 | 0 | 0 |
| rent_schedule_monthly_rent | 1.00 | 0 | 0 | 0 |
| rent_schedule_annual_rent_per_rsf | 1.00 | 0 | 0 | 0 |
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

### t12_001 (0.094)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 0 | 119 | 0 |
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

