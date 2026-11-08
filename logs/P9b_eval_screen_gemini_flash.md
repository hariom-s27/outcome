# DEV eval (baseline)

Run `1a88495-dirty` · 2026-11-08T15:39:15Z · pipeline `baseline-v1` · model `google/gemini-3.8-flash` · P9b screen gemini-flash+E0

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | SUCCESS | True | 0.700 | 1/1 | 3 | 9 | 0 | 0/0 | 0.01273 | 0.01273 | 23.2 |  |
| lease_002 | SUCCESS | True | 0.800 | 1/1 | 5 | 3 | 0 | 0/0 | 0.01528 | 0.01528 | 15.0 |  |
| om_001 | SUCCESS | True | 0.966 | 1/1 | 1 | 0 | 0 | 0/0 | 0.01753 | 0.01753 | 16.2 |  |
| syn_lease_text | SUCCESS | True | 0.975 | 1/1 | 1 | 0 | 0 | 0/0 | 0.01689 | 0.01689 | 34.5 |  |
| syn_lease_docx | SUCCESS | True | 0.900 | 1/1 | 4 | 0 | 0 | 0/0 | 0.01231 | 0.01231 | 14.8 |  |
| syn_loan_unseen | SUCCESS | True | 1.000 | 1/1 | 0 | 0 | 0 | 0/0 | 0.00381 | 0.00381 | 8.9 |  |

**Mean score 0.890 over n = 6 DEV+SYN docs** · paid $0.07857 (computed $0.07857) · uncached $0.07857 · **$0.01310/doc uncached** · p50 latency 15.6 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| lease_001 | bool | 3 | 0 | 0 | 0 |
| lease_001 | date | 3 | 1 | 0 | 0 |
| lease_001 | list | 1 | 0 | 4 | 0 |
| lease_001 | null | 6 | 0 | 0 | 0 |
| lease_001 | number | 8 | 0 | 1 | 0 |
| lease_001 | text | 7 | 2 | 4 | 0 |
| lease_002 | bool | 3 | 0 | 0 | 0 |
| lease_002 | date | 4 | 0 | 0 | 0 |
| lease_002 | list | 4 | 0 | 1 | 0 |
| lease_002 | null | 12 | 0 | 0 | 0 |
| lease_002 | number | 4 | 1 | 1 | 0 |
| lease_002 | text | 5 | 4 | 1 | 0 |
| om_001 | list | 1 | 0 | 0 | 0 |
| om_001 | null | 5 | 0 | 0 | 0 |
| om_001 | number | 14 | 0 | 0 | 0 |
| om_001 | text | 8 | 1 | 0 | 0 |
| syn_lease_text | bool | 3 | 0 | 0 | 0 |
| syn_lease_text | date | 4 | 0 | 0 | 0 |
| syn_lease_text | list | 7 | 0 | 0 | 0 |
| syn_lease_text | null | 2 | 0 | 0 | 0 |
| syn_lease_text | number | 12 | 0 | 0 | 0 |
| syn_lease_text | text | 11 | 1 | 0 | 0 |
| syn_lease_docx | bool | 3 | 0 | 0 | 0 |
| syn_lease_docx | date | 4 | 0 | 0 | 0 |
| syn_lease_docx | list | 7 | 0 | 0 | 0 |
| syn_lease_docx | null | 7 | 0 | 0 | 0 |
| syn_lease_docx | number | 8 | 0 | 0 | 0 |
| syn_lease_docx | text | 7 | 4 | 0 | 0 |
| syn_loan_unseen | date | 2 | 0 | 0 | 0 |
| syn_loan_unseen | null | 1 | 0 | 0 | 0 |
| syn_loan_unseen | number | 6 | 0 | 0 | 0 |
| syn_loan_unseen | text | 3 | 0 | 0 | 0 |

## Per-field scores (field names only)

### lease_001 (0.700)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| premises | 0.00 | 1 | 0 | 0 |
| lease_execution_date | 0.00 | 1 | 0 | 0 |
| rent_schedule_start_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_end_dates | 0.00 | 0 | 1 | 0 |
| rent_schedule_monthly_rent | 0.00 | 0 | 1 | 0 |
| rent_schedule_annual_rent_per_rsf | 0.00 | 0 | 1 | 0 |
| total_base_rent | 0.00 | 0 | 1 | 0 |
| base_rent_escalation | 0.00 | 0 | 1 | 0 |
| electricity_provision | 0.00 | 0 | 1 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
| guarantor_name | 0.00 | 0 | 1 | 0 |
| holdover_rent | 0.00 | 0 | 1 | 0 |
| tenant_name | 1.00 | 0 | 0 | 0 |
| landlord_legal_name | 1.00 | 0 | 0 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| building_address | 1.00 | 0 | 0 | 0 |
| rentable_square_footage | 1.00 | 0 | 0 | 0 |
| pro_rata_share | 1.00 | 0 | 0 | 0 |
| permitted_use | 1.00 | 0 | 0 | 0 |
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
| early_termination_right | 1.00 | 0 | 0 | 0 |
| termination_fee_description | 1.00 | 0 | 0 | 0 |
| broker_names | 1.00 | 0 | 0 | 0 |
| late_fee | 1.00 | 0 | 0 | 0 |

### lease_002 (0.800)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 1 | 0 | 0 |
| building_address | 0.00 | 1 | 0 | 0 |
| permitted_use | 0.00 | 1 | 0 | 0 |
| total_base_rent | 0.00 | 1 | 0 | 0 |
| security_deposit_amount | 0.00 | 0 | 1 | 0 |
| right_to_sublet | 0.00 | 1 | 0 | 0 |
| broker_names | 0.00 | 0 | 1 | 0 |
| late_fee | 0.00 | 0 | 1 | 0 |
| tenant_name | 1.00 | 0 | 0 | 0 |
| landlord_legal_name | 1.00 | 0 | 0 | 0 |
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
| base_rent_escalation | 1.00 | 0 | 0 | 0 |
| free_rent_months | 1.00 | 0 | 0 | 0 |
| letter_of_credit_required | 1.00 | 0 | 0 | 0 |
| expense_structure | 1.00 | 0 | 0 | 0 |
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
| holdover_rent | 1.00 | 0 | 0 | 0 |

### om_001 (0.966)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 1 | 0 | 0 |
| address | 1.00 | 0 | 0 | 0 |
| city | 1.00 | 0 | 0 | 0 |
| state | 1.00 | 0 | 0 | 0 |
| zip_code | 1.00 | 0 | 0 | 0 |
| county | 1.00 | 0 | 0 | 0 |
| submarket | 1.00 | 0 | 0 | 0 |
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

### syn_lease_text (0.975)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
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
| expense_structure | 1.00 | 0 | 0 | 0 |
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
| late_fee | 1.00 | 0 | 0 | 0 |
| holdover_rent | 1.00 | 0 | 0 | 0 |

### syn_lease_docx (0.900)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| premises | 0.00 | 1 | 0 | 0 |
| base_rent_escalation | 0.00 | 1 | 0 | 0 |
| expense_structure | 0.00 | 1 | 0 | 0 |
| late_fee | 0.00 | 1 | 0 | 0 |
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
| total_base_rent | 1.00 | 0 | 0 | 0 |
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

