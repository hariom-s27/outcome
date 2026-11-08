# DEV eval (baseline)

Run `a1b87f4` · 2026-11-08T14:16:19Z · pipeline `baseline-v1,table-spec-v1` · model `anthropic/claude-haiku-5.5` · P9a baseline v1.0 SYN run 1

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syn_lease_text | SUCCESS | True | 0.850 | 1/1 | 6 | 0 | 0 | 0/0 | 0.00235 | 0.00235 | 13.2 |  |
| syn_lease_scan | SUCCESS | True | 0.150 | 1/1 | 1 | 33 | 0 | 0/0 | 0.00302 | 0.00302 | 11.1 |  |
| syn_lease_docx | SUCCESS | True | 0.900 | 1/1 | 4 | 0 | 0 | 0/0 | 0.00160 | 0.00160 | 10.0 |  |
| syn_budget_pdf | SUCCESS | True | 0.017 | 1/43 | 4 | 0 | 0 | 0/42 | 0.00096 | 0.00096 | 5.3 |  |
| syn_rentroll_pdf | SUCCESS | True | 0.033 | 1/30 | 0 | 0 | 0 | 0/29 | 0.00457 | 0.00457 | 24.5 |  flags=truncated_output |
| syn_rentroll_xlsx | SUCCESS | True | 1.000 | 24/24 | 0 | 0 | 0 | 0/0 | 0.00084 | 0.00084 | 3.5 |  |
| syn_boxscore_csv | SUCCESS | True | 0.950 | 7/7 | 7 | 0 | 0 | 0/0 | 0.00081 | 0.00081 | 3.6 |  |
| syn_loan_unseen | SUCCESS | True | 1.000 | 1/1 | 0 | 0 | 0 | 0/0 | 0.00064 | 0.00064 | 4.1 |  |

**Mean score 0.613 over n = 8 SYN docs** · paid $0.01479 (computed $0.01479) · uncached $0.01479 · **$0.00185/doc uncached** · p50 latency 7.6 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
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
| syn_budget_pdf | number | 5 | 4 | 0 | 0 |
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

### syn_lease_text (0.850)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| premises | 0.00 | 1 | 0 | 0 |
| total_base_rent | 0.00 | 1 | 0 | 0 |
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| electricity_provision | 0.00 | 1 | 0 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
| tenant_name | 1.00 | 0 | 0 | 0 |
| landlord_legal_name | 1.00 | 0 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| building_address | 1.00 | 0 | 0 | 0 |
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

### syn_budget_pdf (0.017)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| prior_year_reforecast | 0.00 | 1 | 0 | 0 |
| budget | 0.00 | 1 | 0 | 0 |
| budget_vs_reforecast_variance | 0.00 | 1 | 0 | 0 |
| budget_vs_reforecast_pct | 0.00 | 1 | 0 | 0 |
| property_name | 0.02 | 0 | 0 | 0 |
| property_rsf | 0.02 | 0 | 0 | 0 |
| budget_year | 0.02 | 0 | 0 | 0 |
| gl_code | 0.02 | 0 | 0 | 0 |
| line_item | 0.02 | 0 | 0 | 0 |
| section | 0.02 | 0 | 0 | 0 |
| prior_year_budget | 0.02 | 0 | 0 | 0 |
| reforecast_vs_prior_budget_variance | 0.02 | 0 | 0 | 0 |
| reforecast_vs_prior_budget_pct | 0.02 | 0 | 0 | 0 |
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

