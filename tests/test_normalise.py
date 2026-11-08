"""Normaliser + citation checker (P5-11, P5-12). Invented data only, no network."""

from __future__ import annotations

import pytest

from app.extract.normalise import (
    DocHints,
    add_months,
    extract_dates,
    norm_boolean,
    norm_code,
    norm_date,
    norm_integer,
    norm_list,
    norm_month,
    norm_number,
    norm_percent,
    norm_text,
    norm_year,
    normalise,
    round_trip,
    vote_date_order,
    words_to_int,
    year_words_to_int,
)
from app.extract.verify import find_quote, neighbour_ids, value_in_quote

US = DocHints(date_order="MDY")
EU_DATES = DocHints(date_order="DMY")
EU_NUMS = DocHints(decimal_comma=True)


# --- the 30 invented cases from the P5 brief --------------------------------------------------


@pytest.mark.parametrize(
    "n, text, hints, role, expect",
    [
        (1, "the 3rd day of June, 2019", None, None, "2019-06-03"),
        # brief cases 2, 4, 5, 6, 10: same shape, other invented dates (the brief's literal
        # dates collide with DEV answer values; the sample-value guard refuses them)
        (2, "this twenty-third day of May, two thousand thirty-one", None, None, "2031-05-23"),
        (3, "March 4, 19 87", None, None, "1987-03-04"),
        (4, "04/09/2031", US, None, "2031-04-09"),
        (5, "04/09/2031", EU_DATES, None, "2031-09-04"),
        (6, "14/08/2031", None, None, "2031-08-14"),
        (7, "06/30/98", None, None, "1998-06-30"),
        (8, "11/03/2024 - 11/10/2024", US, "end", "2024-11-10"),
        (10, "February 2032", None, "period_end", "2032-02-29"),
        (11, "June 2024", None, "start", None),
        (13, "2024-03-15T23:30:00-05:00", None, None, "2024-03-15"),
    ],
)
def test_brief_date_cases(n, text, hints, role, expect):
    value, reason = norm_date(text, hints=hints or DocHints(), role=role)
    assert value == expect, (n, reason)


@pytest.mark.parametrize(
    "n, text, expect",
    [(9, "February 2024", "2024-02"), (12, "T12 ending Sep-24", "2024-09")],
)
def test_brief_month_cases(n, text, expect):
    assert norm_month(text)[0] == expect, n


@pytest.mark.parametrize(
    "n, text, hints, expect",
    [
        (14, "(1,234)", None, -1234),
        (15, "1,234-", None, -1234),
        (16, "$(12,500.00)", None, -12500),
        (17, "approximately 2,450 RSF", None, 2450),
        (19, "Forty Thousand Dollars ($42,000.00)", None, None),
        (20, "$3.4M", None, 3_400_000),
        (21, "$1O,5OO", None, 10500),
        (22, "1.234,56 €", EU_NUMS, 1234.56),
        (23, "12,34,567", None, 1234567),
        (24, "$24.50 /RSF/yr", None, 24.5),
    ],
)
def test_brief_number_cases(n, text, hints, expect):
    value, reason = norm_number(text, hints=hints or DocHints())
    assert value == expect, (n, reason)


def test_brief_case_18_words_and_figures():
    # As written in the brief, the words say 42,000.50 ("Forty-Two Thousand and 50/100") and
    # the figures say 42,050.00: by the case-19 rule (words must equal figures) that is a
    # mismatch -> null. Reported in the STOP message. The consistent variants pass.
    brief = "Forty-Two Thousand and 50/100 Dollars ($42,050.00)"
    assert norm_number(brief) == (None, "words_numerals_mismatch")
    assert norm_number("Forty-Two Thousand Fifty and 00/100 Dollars ($42,050.00)")[0] == 42050
    assert norm_number("Forty-Two Thousand and 50/100 Dollars ($42,000.50)")[0] == 42000.5


def test_brief_case_17_is_flagged_hedged():
    assert norm_number("approximately 2,450 RSF") == (2450, "ok_hedged")


def test_brief_case_25_percent_as_printed():
    assert norm_percent("5.26%") == (5.26, "ok")


def test_brief_case_26_free_text_verbatim():
    text = "five percent (5%) of the overdue amount"
    assert norm_text(text) == (text, "ok")


@pytest.mark.parametrize("n, text, expect", [(27, "02134", "02134"), (28, "720-310", "720-310")])
def test_brief_code_cases(n, text, expect):
    assert norm_code(text) == (expect, "ok"), n


def test_brief_case_29_checkbox():
    assert norm_boolean("☒ Yes ☐ No") == (True, "ok")


def test_brief_case_30_hyphen_break_and_label():
    assert norm_text("per-\nmitted use: general office") == ("general office", "ok")


# --- dates: more edges -----------------------------------------------------------------------


def test_ambiguous_numeric_date_without_vote_is_null():
    assert norm_date("04/07/2022") == (None, "ambiguous_date")


def test_month_year_is_never_completed_without_period_end():
    assert norm_date("June 2024") == (None, "partial_date")
    assert norm_date("June 2024", role="end") == (None, "partial_date")


def test_date_without_year_is_not_a_date():
    assert norm_date("June 3") == (None, "no_date")


def test_range_without_role_is_unresolved():
    assert norm_date("January 1, 2030 through December 31, 2034") == (None, "range_unresolved")
    assert norm_date("January 1, 2030 through December 31, 2034", role="start")[0] == "2030-01-01"


def test_iso_and_named_forms():
    assert norm_date("2031-07-09")[0] == "2031-07-09"
    assert norm_date("9 July 2031")[0] == "2031-07-09"
    assert norm_date("July 9th, 2031")[0] == "2031-07-09"
    assert norm_date("09-Jul-31")[0] == "2031-07-09"


def test_invalid_calendar_date_is_rejected():
    assert norm_date("February 30, 2031")[0] is None


def test_vote_date_order():
    assert vote_date_order(["due 13/02/2030", "paid 25/03/2030", "04/05/2030"]) == "DMY"
    assert vote_date_order(["02/13/2030"]) == "MDY"
    assert vote_date_order(["04/05/2030"]) is None


def test_extract_dates_reading_order():
    kinds = [c.kind for c in extract_dates("From March 2030 to 04/05/2031 and 2032-01-02")]
    assert kinds == ["month", "amb", "date"]


def test_add_months_clips_to_month_end():
    import datetime as dt

    assert add_months(dt.date(2031, 1, 31), 1) == dt.date(2031, 2, 28)


def test_year_forms():
    assert norm_year("calendar year 2031") == (2031, "ok")
    assert norm_year("nineteen ninety-eight") == (1998, "ok")
    assert norm_year("2030 and 2031") == (None, "ambiguous_year")
    assert year_words_to_int("two thousand and five") == 2005
    assert words_to_int(["forty", "two", "thousand"]) == 42000


# --- numbers: more edges ---------------------------------------------------------------------


def test_scale_only_when_attached_to_money():
    assert norm_number("$12.5 million")[0] == 12_500_000
    assert norm_number("12m")[0] is None  # months? metres? not trusted


def test_two_different_numbers_are_ambiguous():
    assert norm_number("$1,200 or $1,300") == (None, "ambiguous_number")


def test_words_alone_and_numbers_passthrough():
    assert norm_number("twelve")[0] == 12
    assert norm_number(12345) == (12345, "ok")
    assert norm_number(True)[0] is None


def test_integer_rejects_fractions():
    assert norm_integer("3 spaces") == (3, "ok")
    assert norm_integer("2.5") == (None, "not_integer")


def test_ambiguous_decimal_comma_without_hint():
    assert norm_number("12,5") == (None, "ambiguous_separator")
    assert norm_number("12,5", hints=EU_NUMS)[0] == 12.5


def test_percent_prefers_the_percent_figure():
    assert norm_percent("5% of $1,000")[0] == 5


# --- booleans, codes, text, lists ------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expect",
    [("yes", True), ("No", False), ("[x] No [ ] Yes", False), (True, True), ("maybe", None)],
)
def test_booleans(value, expect):
    assert norm_boolean(value)[0] is expect


def test_code_from_number_stays_string():
    assert norm_code(214) == ("214", "ok")
    assert norm_code("Suite: 907E") == ("907E", "ok")


def test_text_trims_enumerator_and_crossref_keeps_wording():
    assert norm_text("(b) Example use only (see Section 12)")[0] == "Example use only"
    assert norm_text("stepped as per schedule")[0] == "stepped as per schedule"
    assert norm_text("J. Example Person")[0] == "J. Example Person"


def test_list_splits_on_structure_not_commas():
    value, reason = norm_list("Example Realty, Inc.\nSample Brokers LLC; Example Realty, Inc.")
    assert value == ["Example Realty, Inc.", "Sample Brokers LLC"] and reason == "ok"
    assert norm_list("") == ([], "ok")
    assert norm_list(["60", "x", "120"], item_type="integer") == ([60, 120], "item_dropped")


def test_dispatch_unknown_type_is_free_text():
    assert normalise("  Example  ", "mystery") == ("Example", "ok")


# --- round trip ------------------------------------------------------------------------------


def test_round_trip_numbers_dates_text():
    assert round_trip(42050, "Base Rent: $42,050.00 per year", "number")
    assert not round_trip(42500, "Base Rent: $42,050.00 per year", "number")
    assert round_trip(3_400_000, "asking $3.4M", "number")
    assert round_trip(5.26, "cap rate of 5.26%", "percent")
    assert round_trip("2031-07-09", "dated as of July 9, 2031", "date")
    assert not round_trip("2031-07-10", "dated as of July 9, 2031", "date")
    assert round_trip("2030-02-28", "period ending February 2030", "date")
    assert round_trip("2030-09", "T12 ending Sep-30", "month")
    assert round_trip(2031, "Base Year: calendar year 2031", "year")
    assert round_trip("907E", "Suite 907E, Example Tower", "code")
    assert not round_trip("07E", "Suite 907E, Example Tower", "code")
    assert round_trip("general office", "Permitted Use: general office and storage", "text")
    assert round_trip(False, "", "boolean") and not round_trip(True, "", "boolean")
    assert round_trip(
        ["2031-01-01", "2032-01-01"], "Jan 1, 2031; Jan 1, 2032", "list", item_type="date"
    )


# --- citation checker ------------------------------------------------------------------------

BLOCK = "Section 3. The Premises: Suite 410, Example Tower, containing 12,345 rentable square feet."


def test_quote_found_exact_returns_source_span():
    hit = find_quote("suite 410, EXAMPLE tower", BLOCK)
    assert hit and hit.kind == "exact" and hit.score == 100
    assert hit.span == "Suite 410, Example Tower" and BLOCK[hit.start : hit.end] == hit.span


def test_quote_found_with_curly_quotes_and_dashes():
    block = "Tenant’s share is 5–6 floors"
    hit = find_quote("Tenant's share is 5-6 floors", block)
    assert hit and hit.kind == "exact" and hit.span == block


def test_quote_found_fuzzy_snapped_to_words():
    hit = find_quote("containing 12,345 rentable sqare feet", BLOCK)
    assert hit and hit.kind == "fuzzy" and hit.score >= 90
    assert hit.span.startswith("containing") and "feet" in hit.span


def test_quote_absent_is_not_found():
    assert find_quote("Landlord shall provide sixty parking spaces", BLOCK) is None


def test_short_quote_never_fuzzy_and_word_bounded():
    assert find_quote("12", "Lease year 2012 begins") is None
    assert find_quote("410", BLOCK) is not None


def test_relocation_to_neighbour_block():
    neighbours = [("b0002", "unrelated text"), ("b0004", "Term: sixty (60) months")]
    hit = find_quote("sixty (60) months", "Rent is due monthly.", neighbours)
    assert hit and hit.relocated and hit.block_id == "b0004"


def test_elided_quote_matches_parts_in_order():
    hit = find_quote("The Premises ... 12,345 rentable", BLOCK)
    assert hit and hit.span.startswith("The Premises") and hit.span.endswith("rentable")


def test_neighbour_ids_nearest_first():
    ids = ["a", "b", "c", "d", "e"]
    assert neighbour_ids(ids, "c") == ["b", "d", "a", "e"]
    assert neighbour_ids(ids, "zz") == []


def test_value_in_quote_pass_and_fail():
    assert value_in_quote(12345, "containing 12,345 rentable square feet", "number")
    # P5b F-6: scorer tolerance max(0.01, 0.5 %): 12,354 is within it, 12,445 is not
    assert value_in_quote(12354, "containing 12,345 rentable square feet", "number")
    assert not value_in_quote(12445, "containing 12,345 rentable square feet", "number")
