# DEV eval (baseline)

Run `a97a79a-dirty` · 2026-11-07T19:17:14Z · pipeline `baseline-v1` · model `anthropic/claude-haiku-5.5` · P3 readers + one-line block render (om_001 live, 5 reused from a97a79a)

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| boxscore_001 | SUCCESS | True | 1.000 | 10/10 | 0 | 0 | 0 | 0/0 | 0.00000 | 0.00951 | 0.6 |  |
| lease_001 | SUCCESS | True | 0.700 | 1/1 | 5 | 7 | 0 | 0/0 | 0.00000 | 0.00306 | 1.9 |  |
| lease_002 | SUCCESS | True | 0.775 | 1/1 | 8 | 0 | 1 | 0/0 | 0.00400 | 0.00400 | 11.7 |  |
| om_001 | SUCCESS | True | 0.948 | 1/1 | 2 | 0 | 0 | 0/0 | 0.00284 | 0.00284 | 11.5 |  |
| t12_001 | SUCCESS | True | 0.046 | 6/119 | 6 | 0 | 0 | 0/113 | 0.00000 | 0.00394 | 0.4 |  |
| rentroll_001 | SUCCESS | True | 0.006 | 2/325 | 0 | 0 | 0 | 0/323 | 0.00618 | 0.00618 | 9.1 |  |

**Mean score 0.579 over n = 6 DEV docs** · paid $0.01302 (computed $0.01302) · uncached $0.02953 · **$0.00492/doc uncached** · p50 latency 5.5 s · reasoning tokens 0

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| boxscore_001 | date | 10 | 0 | 0 | 0 |
| boxscore_001 | number | 160 | 0 | 0 | 0 |
| boxscore_001 | text | 30 | 0 | 0 | 0 |
| lease_001 | bool | 2 | 1 | 0 | 0 |
| lease_001 | date | 4 | 0 | 0 | 0 |
| lease_001 | list | 1 | 0 | 4 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 8 | 0 | 1 | 0 |
| lease_001 | text | 7 | 4 | 2 | 0 |
| lease_002 | bool | 3 | 0 | 0 | 0 |
| lease_002 | date | 3 | 1 | 0 | 0 |
| lease_002 | list | 5 | 0 | 0 | 0 |
| lease_002 | null | 11 | 0 | 0 | 1 |
| lease_002 | number | 5 | 1 | 0 | 0 |
| lease_002 | text | 4 | 6 | 0 | 0 |
| om_001 | list | 0 | 1 | 0 | 0 |
| om_001 | null | 5 | 0 | 0 | 0 |
| om_001 | number | 14 | 0 | 0 | 0 |
| om_001 | text | 8 | 1 | 0 | 0 |
| t12_001 | date | 12 | 0 | 0 | 0 |
| t12_001 | number | 24 | 0 | 0 | 0 |
| t12_001 | text | 24 | 6 | 0 | 0 |
| rentroll_001 | date | 7 | 0 | 0 | 0 |
| rentroll_001 | null | 1 | 0 | 0 | 0 |
| rentroll_001 | number | 14 | 0 | 0 | 0 |
| rentroll_001 | text | 12 | 0 | 0 | 0 |

## Per-field scores (field names only)

### boxscore_001 (1.000)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 1.00 | 0 | 0 | 0 |
| date | 1.00 | 0 | 0 | 0 |
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

### lease_001 (0.700)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| rent_schedule_start_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_end_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_monthly_rent | 0.00 | 0 | 1 | 0 |
| rent_schedule_annual_rent_per_rsf | 0.00 | 0 | 1 | 0 |
| total_base_rent | 0.00 | 0 | 1 | 0 |
| base_rent_escalation | 0.00 | 0 | 1 | 0 |
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
| free_rent_months | 1.00 | 0 | 0 | 0 |
| security_deposit_amount | 1.00 | 0 | 0 | 0 |
| letter_of_credit_required | 1.00 | 0 | 0 | 0 |
| expense_structure | 1.00 | 0 | 0 | 0 |
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

### lease_002 (0.775)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 1 | 0 | 0 |
| building_address | 0.00 | 1 | 0 | 0 |
| permitted_use | 0.00 | 1 | 0 | 0 |
| rent_commencement_date | 0.00 | 1 | 0 | 0 |
| total_base_rent | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 0 | 0 | 1 |
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
| base_rent_escalation | 1.00 | 0 | 0 | 0 |
| free_rent_months | 1.00 | 0 | 0 | 0 |
| security_deposit_amount | 1.00 | 0 | 0 | 0 |
| letter_of_credit_required | 1.00 | 0 | 0 | 0 |
| base_year_expenses | 1.00 | 0 | 0 | 0 |
| base_year_taxes | 1.00 | 0 | 0 | 0 |
| electricity_provision | 1.00 | 0 | 0 | 0 |
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

### om_001 (0.948)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| submarket | 0.00 | 1 | 0 | 0 |
| unit_types | 0.50 | 1 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| address | 1.00 | 0 | 0 | 0 |
| city | 1.00 | 0 | 0 | 0 |
| state | 1.00 | 0 | 0 | 0 |
| zip_code | 1.00 | 0 | 0 | 0 |
| county | 1.00 | 0 | 0 | 0 |
| broker_name | 1.00 | 0 | 0 | 0 |
| units | 1.00 | 0 | 0 | 0 |
| year_built | 1.00 | 0 | 0 | 0 |
| year_renovated | 1.00 | 0 | 0 | 0 |
| building_type | 1.00 | 0 | 0 | 0 |
| number_of_buildings | 1.00 | 0 | 0 | 0 |
| stories | 1.00 | 0 | 0 | 0 |
| rentable_sf | 1.00 | 0 | 0 | 0 |
| average_unit_sf | 1.00 | 0 | 0 | 0 |
| site_acres | 1.00 | 0 | 0 | 0 |
| parking_spaces | 1.00 | 0 | 0 | 0 |
| parking_ratio | 1.00 | 0 | 0 | 0 |
| asking_price | 1.00 | 0 | 0 | 0 |
| price_per_unit | 1.00 | 0 | 0 | 0 |
| asking_cap_rate | 1.00 | 0 | 0 | 0 |
| occupancy_pct | 1.00 | 0 | 0 | 0 |
| average_in_place_rent | 1.00 | 0 | 0 | 0 |
| market_rent | 1.00 | 0 | 0 | 0 |
| market_rent_psf | 1.00 | 0 | 0 | 0 |
| noi_t12 | 1.00 | 0 | 0 | 0 |
| noi_proforma | 1.00 | 0 | 0 | 0 |

### t12_001 (0.046)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 6 | 0 | 0 |
| period_start | 0.05 | 0 | 0 | 0 |
| period_end | 0.05 | 0 | 0 | 0 |
| gl_code | 0.05 | 0 | 0 | 0 |
| line_item | 0.05 | 0 | 0 | 0 |
| section | 0.05 | 0 | 0 | 0 |
| category | 0.05 | 0 | 0 | 0 |
| amount_total | 0.05 | 0 | 0 | 0 |
| amount_first_month | 0.05 | 0 | 0 | 0 |
| amount_last_month | 0.05 | 0 | 0 | 0 |
| months_with_activity | 0.05 | 0 | 0 | 0 |

### rentroll_001 (0.006)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.01 | 0 | 0 | 0 |
| report_period | 0.01 | 0 | 0 | 0 |
| unit_number | 0.01 | 0 | 0 | 0 |
| unit_type_code | 0.01 | 0 | 0 | 0 |
| unit_square_feet | 0.01 | 0 | 0 | 0 |
| unit_status | 0.01 | 0 | 0 | 0 |
| resident_name | 0.01 | 0 | 0 | 0 |
| market_rent | 0.01 | 0 | 0 | 0 |
| monthly_rent | 0.01 | 0 | 0 | 0 |
| monthly_other_charges | 0.01 | 0 | 0 | 0 |
| monthly_total_charges | 0.01 | 0 | 0 | 0 |
| deposit_held | 0.01 | 0 | 0 | 0 |
| balance | 0.01 | 0 | 0 | 0 |
| move_in_date | 0.01 | 0 | 0 | 0 |
| lease_start_date | 0.01 | 0 | 0 | 0 |
| lease_end_date | 0.01 | 0 | 0 | 0 |
| expected_move_out_date | 0.01 | 0 | 0 | 0 |

