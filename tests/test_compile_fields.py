"""Field compiler + single-value path rule (P5-04, P5-05). Invented field lists only."""

from __future__ import annotations

import pytest

from app.extract import compile_fields as cf
from app.extract.compile_fields import compile_fields, field_list_hash, is_single_value
from app.extract.normalise import TYPES


def f(name: str, description: str, **extra) -> dict:
    return {"name": name, "description": description, **extra}


INVENTED_LEASE = {
    "name": "invented_lease",
    "description": "One entry per document.",
    "fields": {
        "occupant": f("Occupant", "Legal name of the occupant exactly as written."),
        "signed_on": f("Signing Date", "Date the agreement was signed, in YYYY-MM-DD."),
        "money_start": f("Payment Start Date", "When payments begin."),
        "ends_on": f("Term End Date", "The date the term expires."),
        "term_len": f(
            "Term (months)",
            "Length of the term in whole months. Compute it if only the dates are given.",
        ),
        "floor_area": f("Floor Area", "Rentable floor area as a number."),
        "share_pct": f("Occupant Share", "Share of the building as a percentage number."),
        "monthly_amount": f("Monthly Payment", "Monthly payment amount."),
        "sum_amount": f("Total Payments", "Sum of all payments over the term, as a number."),
        "deposit": f("Deposit", "Cash deposit as a number. null if none."),
        "can_extend": f("Extension Option", "true if the occupant may extend, false otherwise."),
        "spaces": f("Parking Stalls", "How many stalls the occupant gets."),
        "base_year": f("Base Year (Costs)", "Base year for cost escalations."),
        "steps_start": f(
            "Schedule: Start Dates", "List of the start date of each payment period, in order."
        ),
        "steps_amount": f(
            "Schedule: Amounts", "List of the monthly payment for each period. Numbers only."
        ),
        "agents": f("Agents", "List of the agents named. Empty list if none."),
        "use_clause": f("Allowed Use", "The allowed use, as the agreement states it."),
        "escalation": f("Escalation", "How payments rise, in a short phrase, e.g. 'fixed'."),
        "suite": f("Space", "The suite or unit identifier only."),
        "mystery": f("Zorblax", "Qwerty uiop."),
    },
}

EXPECT_LEASE = {
    "occupant": "free_text",
    "signed_on": "date",
    "money_start": "date",
    "ends_on": "date",
    "term_len": "integer",
    "floor_area": "number",
    "share_pct": "percent",
    "monthly_amount": "number",
    "sum_amount": "number",
    "deposit": "number",
    "can_extend": "boolean",
    "spaces": "integer",
    "base_year": "year",
    "steps_start": "list",
    "steps_amount": "list",
    "agents": "list",
    "use_clause": "free_text",
    "escalation": "text",
    "suite": "code",
    "mystery": "free_text",
}

INVENTED_OM = {
    "name": "invented_om",
    "fields": {
        "asset_name": f("Asset Name", "Name of the asset."),
        "list_price": f("List Price", "Asking price."),
        "units": f("Units", "Number of units."),
        "built": f("Year Built", "Year the asset was built."),
        "occ": f("Occupancy", "Current occupancy."),
        "cap": f("Cap Rate", "In-place cap rate as printed."),
        "price_per_unit": f("Price per Unit", "Asking price per unit."),
        "postal": f("ZIP", "Postal code of the asset."),
        "statement_month": f("Statement Month", "Month of the operating statement."),
    },
}

EXPECT_OM = {
    "asset_name": "free_text",
    "list_price": "number",
    "units": "integer",
    "built": "year",
    "occ": "percent",
    "cap": "percent",
    "price_per_unit": "number",
    "postal": "code",
    "statement_month": "month",
}

INVENTED_TABLE = {
    "name": "invented_table",
    "fields": {
        "row_code": f("Row Code", "Identifier of the row.", primary=True),
        "row_amount": f("Row Amount", "Amount on the row as a number."),
        "as_of": f("As Of", "End date of the reporting period, in YYYY-MM-DD."),
    },
}


def test_invented_lease_types():
    specs = compile_fields(INVENTED_LEASE)
    assert list(specs) == list(INVENTED_LEASE["fields"])  # field-list order kept
    assert {k: s.type for k, s in specs.items()} == EXPECT_LEASE
    assert all(s.type in TYPES for s in specs.values())


def test_invented_om_types():
    assert {k: s.type for k, s in compile_fields(INVENTED_OM).items()} == EXPECT_OM


def test_list_item_types():
    specs = compile_fields(INVENTED_LEASE)
    assert specs["steps_start"].item_type == "date"
    assert specs["steps_amount"].item_type == "number"
    assert specs["agents"].item_type == "text"


def test_date_roles():
    lease = compile_fields(INVENTED_LEASE)
    assert lease["ends_on"].date_role == "end"
    assert lease["money_start"].date_role == "start"
    assert compile_fields(INVENTED_TABLE)["as_of"].date_role == "period_end"


def test_computed_candidates():
    specs = compile_fields(INVENTED_LEASE)
    assert specs["term_len"].computed and specs["sum_amount"].computed
    assert not specs["deposit"].computed and not specs["occupant"].computed


def test_null_and_format_rules():
    specs = compile_fields(INVENTED_LEASE)
    assert "null if none" in specs["deposit"].null_rule
    assert "false when the document is complete" in specs["can_extend"].null_rule
    assert "YYYY-MM-DD" in specs["signed_on"].format_rule
    assert "leading zeros" in specs["suite"].format_rule
    assert "Each item" in specs["steps_start"].format_rule


def test_path_rule():
    assert is_single_value(INVENTED_LEASE) is True
    assert is_single_value(INVENTED_OM) is True
    assert is_single_value(INVENTED_TABLE) is False
    assert compile_fields(INVENTED_TABLE)["row_code"].primary is True


@pytest.mark.parametrize(
    "field_list",
    [
        {},
        {"fields": None},
        {"fields": []},
        {"fields": {"x": None}},
        {"fields": {"x": "not a dict"}},
        {"fields": {"x": {"name": 7, "description": None}}},
        {"fields": {"x": {"primary": "true"}}},
        "garbage",
    ],
)
def test_odd_field_lists_never_crash(field_list):
    specs = compile_fields(field_list)
    assert all(s.type in TYPES for s in specs.values())
    assert isinstance(is_single_value(field_list), bool)


def test_odd_field_falls_back_to_free_text():
    specs = compile_fields({"fields": {"x": None, "y": {"name": "", "description": ""}}})
    assert specs["x"].type == "free_text" and specs["y"].type == "free_text"


def test_string_primary_marks_a_table():
    assert is_single_value({"fields": {"x": {"primary": "true"}}}) is False


def test_cache_by_field_list_hash():
    cf._cache.clear()
    a = compile_fields(INVENTED_OM)
    assert len(cf._cache) == 1
    b = compile_fields(INVENTED_OM)
    assert a == b and len(cf._cache) == 1
    a.pop("units")  # callers get a copy; the cache is not changed
    assert "units" in compile_fields(INVENTED_OM)
    assert field_list_hash(INVENTED_OM) != field_list_hash(INVENTED_LEASE)


def test_text_fields_are_never_computed():
    specs = compile_fields(
        {
            "fields": {
                "fee": f("Late Charge", "The late charge in a short phrase, e.g. '9% per annum'.")
            }
        }
    )
    assert specs["fee"].type == "text" and not specs["fee"].computed
