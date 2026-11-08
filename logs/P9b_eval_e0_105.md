# DEV eval (baseline)

Run `f043ea2` · 2026-11-08T15:01:26Z · pipeline `baseline-v1,table-spec-v1` · model `anthropic/claude-haiku-5.5` · P9b E0 E0_ROBUST=1 run 1

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| boxscore_001 | SUCCESS | True | 0.880 | 10/10 | 4 | 20 | 0 | 0/0 | 0.00175 | 0.00175 | 6.5 |  |
| lease_001 | SUCCESS | True | 0.650 | 1/1 | 6 | 8 | 0 | 0/0 | 0.00306 | 0.00306 | 13.1 |  |
| lease_002 | SUCCESS | True | 0.775 | 1/1 | 8 | 0 | 1 | 0/0 | 0.00404 | 0.00404 | 10.9 |  |
| om_001 | SUCCESS | True | 0.966 | 1/1 | 1 | 0 | 0 | 0/0 | 0.00286 | 0.00286 | 11.0 |  |
| t12_001 | SUCCESS | True | 0.548 | 119/119 | 119 | 472 | 0 | 0/0 | 0.00236 | 0.00236 | 6.2 |  |
| rentroll_001 | SUCCESS | True | 0.989 | 325/325 | 19 | 0 | 44 | 0/0 | 0.00116 | 0.00116 | 6.3 |  |
| syn_lease_text | SUCCESS | True | 0.850 | 1/1 | 6 | 0 | 0 | 0/0 | 0.00243 | 0.00243 | 12.1 |  |
| syn_lease_scan | SUCCESS | True | 0.150 | 1/1 | 1 | 33 | 0 | 0/0 | 0.00302 | 0.00302 | 10.6 |  |
| syn_lease_docx | SUCCESS | True | 0.900 | 1/1 | 4 | 0 | 0 | 0/0 | 0.00157 | 0.00157 | 8.7 |  |
| syn_budget_pdf | SUCCESS | True | 0.018 | 1/43 | 3 | 0 | 0 | 0/42 | 0.00095 | 0.00095 | 5.1 |  |
| syn_rentroll_pdf | SUCCESS | True | 0.033 | 1/30 | 0 | 0 | 0 | 0/29 | 0.00457 | 0.00457 | 24.9 |  flags=truncated_output |
| syn_rentroll_xlsx | SUCCESS | True | 1.000 | 24/24 | 0 | 0 | 0 | 0/0 | 0.00084 | 0.00084 | 3.5 |  |
| syn_boxscore_csv | SUCCESS | True | 0.950 | 7/7 | 7 | 0 | 0 | 0/0 | 0.00081 | 0.00081 | 3.0 |  |
| syn_loan_unseen | SUCCESS | True | 1.000 | 1/1 | 0 | 0 | 0 | 0/0 | 0.00064 | 0.00064 | 4.7 |  |

**Mean score 0.694 over n = 14 DEV+SYN docs** · paid $0.03005 (computed $0.03005) · uncached $0.03005 · **$0.00215/doc uncached** · p50 latency 7.6 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| boxscore_001 | date | 0 | 0 | 10 | 0 |
| boxscore_001 | number | 156 | 4 | 0 | 0 |
| boxscore_001 | text | 20 | 0 | 10 | 0 |
| lease_001 | bool | 2 | 1 | 0 | 0 |
| lease_001 | date | 4 | 0 | 0 | 0 |
| lease_001 | list | 1 | 0 | 4 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 7 | 0 | 2 | 0 |
| lease_001 | text | 6 | 5 | 2 | 0 |
| lease_002 | bool | 3 | 0 | 0 | 0 |
| lease_002 | date | 3 | 1 | 0 | 0 |
| lease_002 | list | 5 | 0 | 0 | 0 |
| lease_002 | null | 11 | 0 | 0 | 1 |
| lease_002 | number | 5 | 1 | 0 | 0 |
| lease_002 | text | 4 | 6 | 0 | 0 |
| om_001 | list | 1 | 0 | 0 | 0 |
| om_001 | null | 5 | 0 | 0 | 0 |
| om_001 | number | 14 | 0 | 0 | 0 |
| om_001 | text | 8 | 1 | 0 | 0 |
| t12_001 | date | 0 | 0 | 238 | 0 |
| t12_001 | number | 476 | 0 | 0 | 0 |
| t12_001 | text | 242 | 119 | 234 | 0 |
| rentroll_001 | date | 927 | 0 | 0 | 0 |
| rentroll_001 | null | 373 | 0 | 0 | 44 |
| rentroll_001 | number | 2234 | 19 | 0 | 0 |
| rentroll_001 | text | 1928 | 0 | 0 | 0 |
| syn_lease_text | bool | 3 | 0 | 0 | 0 |
| syn_lease_text | date | 4 | 0 | 0 | 0 |
| syn_lease_text | list | 7 | 0 | 0 | 0 |
| syn_lease_text | null | 2 | 0 | 0 | 0 |
| syn_lease_text | number | 11 | 1 | 0 | 0 |
| syn_lease_text | text | 7 | 5 | 0 | 0 |
| syn_lease_scan | bool | 0 | 0 | 3 | 0 |
| syn_lease_scan | date | 0 | 0 | 4 | 0 |
| syn_lease_scan | list | 1 | 0 | 6 | 0 |
| syn_lease_scan | null | 5 | 0 | 0 | 0 |
| syn_lease_scan | number | 0 | 1 | 6 | 0 |
| syn_lease_scan | text | 0 | 0 | 14 | 0 |
| syn_lease_docx | bool | 3 | 0 | 0 | 0 |
| syn_lease_docx | date | 4 | 0 | 0 | 0 |
| syn_lease_docx | list | 7 | 0 | 0 | 0 |
| syn_lease_docx | null | 7 | 0 | 0 | 0 |
| syn_lease_docx | number | 7 | 1 | 0 | 0 |
| syn_lease_docx | text | 8 | 3 | 0 | 0 |
| syn_budget_pdf | number | 6 | 3 | 0 | 0 |
| syn_budget_pdf | text | 5 | 0 | 0 | 0 |
| syn_rentroll_pdf | date | 3 | 0 | 0 | 0 |
| syn_rentroll_pdf | null | 1 | 0 | 0 | 0 |
| syn_rentroll_pdf | number | 7 | 0 | 0 | 0 |
| syn_rentroll_pdf | text | 6 | 0 | 0 | 0 |
| syn_rentroll_xlsx | date | 54 | 0 | 0 | 0 |
| syn_rentroll_xlsx | null | 49 | 0 | 0 | 0 |
| syn_rentroll_xlsx | number | 168 | 0 | 0 | 0 |
| syn_rentroll_xlsx | text | 137 | 0 | 0 | 0 |
| syn_boxscore_csv | date | 7 | 0 | 0 | 0 |
| syn_boxscore_csv | number | 112 | 0 | 0 | 0 |
| syn_boxscore_csv | text | 14 | 7 | 0 | 0 |
| syn_loan_unseen | date | 2 | 0 | 0 | 0 |
| syn_loan_unseen | null | 1 | 0 | 0 | 0 |
| syn_loan_unseen | number | 6 | 0 | 0 | 0 |
| syn_loan_unseen | text | 3 | 0 | 0 | 0 |

## Per-field scores (field names only)

### boxscore_001 (0.880)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 0 | 10 | 0 |
| date | 0.00 | 0 | 10 | 0 |
| percent_occupied | 0.80 | 2 | 0 | 0 |
| p_occ_wornonrev | 0.80 | 2 | 0 | 0 |
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
| percent_leased | 1.00 | 0 | 0 | 0 |
| p_trend | 1.00 | 0 | 0 | 0 |

### lease_001 (0.650)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| building_address | 0.00 | 1 | 0 | 0 |
| rent_schedule_start_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_end_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_monthly_rent | 0.00 | 0 | 1 | 0 |
| rent_schedule_annual_rent_per_rsf | 0.00 | 0 | 1 | 0 |
| total_base_rent | 0.00 | 0 | 1 | 0 |
| base_rent_escalation | 0.00 | 0 | 1 | 0 |
| free_rent_months | 0.00 | 0 | 1 | 0 |
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

### om_001 (0.966)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| submarket | 0.00 | 1 | 0 | 0 |
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
| unit_types | 1.00 | 0 | 0 | 0 |
| noi_t12 | 1.00 | 0 | 0 | 0 |
| noi_proforma | 1.00 | 0 | 0 | 0 |

### t12_001 (0.548)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 119 | 0 | 0 |
| period_start | 0.00 | 0 | 119 | 0 |
| period_end | 0.00 | 0 | 119 | 0 |
| section | 0.02 | 0 | 117 | 0 |
| category | 0.02 | 0 | 117 | 0 |
| gl_code | 1.00 | 0 | 0 | 0 |
| line_item | 1.00 | 0 | 0 | 0 |
| amount_total | 1.00 | 0 | 0 | 0 |
| amount_first_month | 1.00 | 0 | 0 | 0 |
| amount_last_month | 1.00 | 0 | 0 | 0 |
| months_with_activity | 1.00 | 0 | 0 | 0 |

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

### syn_lease_text (0.850)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| permitted_use | 0.00 | 1 | 0 | 0 |
| total_base_rent | 0.00 | 1 | 0 | 0 |
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| electricity_provision | 0.00 | 1 | 0 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
| tenant_name | 1.00 | 0 | 0 | 0 |
| landlord_legal_name | 1.00 | 0 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| building_address | 1.00 | 0 | 0 | 0 |
| premises | 1.00 | 0 | 0 | 0 |
| rentable_square_footage | 1.00 | 0 | 0 | 0 |
| pro_rata_share | 1.00 | 0 | 0 | 0 |
| lease_execution_date | 1.00 | 0 | 0 | 0 |
| lease_commencement_date | 1.00 | 0 | 0 | 0 |
| rent_commencement_date | 1.00 | 0 | 0 | 0 |
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
| late_fee | 1.00 | 0 | 0 | 0 |
| holdover_rent | 1.00 | 0 | 0 | 0 |

### syn_lease_scan (0.150)

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
| base_rent_escalation | 0.00 | 0 | 1 | 0 |
| free_rent_months | 0.00 | 0 | 1 | 0 |
| security_deposit_amount | 0.00 | 0 | 1 | 0 |
| letter_of_credit_required | 0.00 | 0 | 1 | 0 |
| expense_structure | 0.00 | 0 | 1 | 0 |
| electricity_provision | 0.00 | 0 | 1 | 0 |
| ti_allowance_total | 0.00 | 0 | 1 | 0 |
| renewal_option_exists | 0.00 | 0 | 1 | 0 |
| renewal_options_count | 0.00 | 1 | 0 | 0 |
| renewal_term_months | 0.00 | 0 | 1 | 0 |
| renewal_notice_months | 0.00 | 0 | 1 | 0 |
| early_termination_right | 0.00 | 0 | 1 | 0 |
| termination_fee_description | 0.00 | 0 | 1 | 0 |
| right_to_sublet | 0.00 | 0 | 1 | 0 |
| guarantor_name | 0.00 | 0 | 1 | 0 |
| late_fee | 0.00 | 0 | 1 | 0 |
| holdover_rent | 0.00 | 0 | 1 | 0 |
| pro_rata_share | 1.00 | 0 | 0 | 0 |
| base_year_expenses | 1.00 | 0 | 0 | 0 |
| base_year_taxes | 1.00 | 0 | 0 | 0 |
| parking_spaces | 1.00 | 0 | 0 | 0 |
| parking_monthly_charge | 1.00 | 0 | 0 | 0 |
| broker_names | 1.00 | 0 | 0 | 0 |

### syn_lease_docx (0.900)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| total_base_rent | 0.00 | 1 | 0 | 0 |
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| late_fee | 0.00 | 1 | 0 | 0 |
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
| right_to_sublet | 1.00 | 0 | 0 | 0 |
| guarantor_name | 1.00 | 0 | 0 | 0 |
| broker_names | 1.00 | 0 | 0 | 0 |
| holdover_rent | 1.00 | 0 | 0 | 0 |

### syn_budget_pdf (0.018)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| prior_year_reforecast | 0.00 | 1 | 0 | 0 |
| budget | 0.00 | 1 | 0 | 0 |
| budget_vs_reforecast_variance | 0.00 | 1 | 0 | 0 |
| property_name | 0.02 | 0 | 0 | 0 |
| property_rsf | 0.02 | 0 | 0 | 0 |
| budget_year | 0.02 | 0 | 0 | 0 |
| gl_code | 0.02 | 0 | 0 | 0 |
| line_item | 0.02 | 0 | 0 | 0 |
| section | 0.02 | 0 | 0 | 0 |
| prior_year_budget | 0.02 | 0 | 0 | 0 |
| reforecast_vs_prior_budget_variance | 0.02 | 0 | 0 | 0 |
| reforecast_vs_prior_budget_pct | 0.02 | 0 | 0 | 0 |
| budget_vs_reforecast_pct | 0.02 | 0 | 0 | 0 |
| explanation_of_variance | 0.02 | 0 | 0 | 0 |

### syn_rentroll_pdf (0.033)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.03 | 0 | 0 | 0 |
| report_period | 0.03 | 0 | 0 | 0 |
| unit_number | 0.03 | 0 | 0 | 0 |
| unit_type_code | 0.03 | 0 | 0 | 0 |
| unit_square_feet | 0.03 | 0 | 0 | 0 |
| unit_status | 0.03 | 0 | 0 | 0 |
| resident_name | 0.03 | 0 | 0 | 0 |
| market_rent | 0.03 | 0 | 0 | 0 |
| monthly_rent | 0.03 | 0 | 0 | 0 |
| monthly_other_charges | 0.03 | 0 | 0 | 0 |
| monthly_total_charges | 0.03 | 0 | 0 | 0 |
| deposit_held | 0.03 | 0 | 0 | 0 |
| balance | 0.03 | 0 | 0 | 0 |
| move_in_date | 0.03 | 0 | 0 | 0 |
| lease_start_date | 0.03 | 0 | 0 | 0 |
| lease_end_date | 0.03 | 0 | 0 | 0 |
| expected_move_out_date | 0.03 | 0 | 0 | 0 |

### syn_rentroll_xlsx (1.000)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 1.00 | 0 | 0 | 0 |
| report_period | 1.00 | 0 | 0 | 0 |
| unit_number | 1.00 | 0 | 0 | 0 |
| unit_type_code | 1.00 | 0 | 0 | 0 |
| unit_square_feet | 1.00 | 0 | 0 | 0 |
| unit_status | 1.00 | 0 | 0 | 0 |
| resident_name | 1.00 | 0 | 0 | 0 |
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

### syn_boxscore_csv (0.950)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 7 | 0 | 0 |
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

### syn_loan_unseen (1.000)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| lender_name | 1.00 | 0 | 0 | 0 |
| borrower_name | 1.00 | 0 | 0 | 0 |
| property_address | 1.00 | 0 | 0 | 0 |
| loan_amount | 1.00 | 0 | 0 | 0 |
| interest_rate_pct | 1.00 | 0 | 0 | 0 |
| closing_date | 1.00 | 0 | 0 | 0 |
| maturity_date | 1.00 | 0 | 0 | 0 |
| loan_term_months | 1.00 | 0 | 0 | 0 |
| amortization_years | 1.00 | 0 | 0 | 0 |
| monthly_payment | 1.00 | 0 | 0 | 0 |
| annual_debt_service | 1.00 | 0 | 0 | 0 |
| guarantor_name | 1.00 | 0 | 0 | 0 |

