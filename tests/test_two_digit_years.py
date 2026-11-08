"""DR15 2-digit years (P5 D-3): fixed pivot 76 from config, never today's date.
00..76 -> 20xx, 77..99 -> 19xx; then the field's year range; a 2-digit year outside it flips
century once, else null. Invented dates only.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.extract import normalise as N
from app.extract.compile_fields import YEAR_RANGE_WIDE, compile_field
from app.extract.normalise import (
    TWO_DIGIT_PIVOT,
    DocHints,
    _year2,
    fit_year_range,
    norm_date,
    norm_month,
    normalise,
    round_trip,
)
from app.llm.models import ModelCatalog

US = DocHints(date_order="MDY")


@pytest.mark.parametrize(
    "yy, year",
    [("00", 2000), ("31", 2031), ("76", 2076), ("77", 1977), ("98", 1998), ("2031", 2031)],
)
def test_fixed_pivot_76(yy, year):
    assert _year2(yy) == year


def test_pivot_comes_from_config_and_matches_the_default():
    assert ModelCatalog.load().two_digit_pivot == TWO_DIGIT_PIVOT == 76
    assert DocHints().two_digit_pivot == 76
    with pytest.raises(ValueError):
        ModelCatalog.from_dict({**_raw_yaml(), "two_digit_year_pivot": 120})


def _raw_yaml():
    import yaml

    from app.llm.models import DEFAULT_MODELS_PATH

    return yaml.safe_load(DEFAULT_MODELS_PATH.read_text(encoding="utf-8"))


def test_window_never_reads_todays_date(monkeypatch):
    class FrozenFuture(dt.date):
        @classmethod
        def today(cls):
            return cls(2090, 1, 1)

    monkeypatch.setattr(N.dt, "date", FrozenFuture)
    assert _year2("80") == 1980 and _year2("76") == 2076


def test_a_configured_pivot_is_honoured():
    assert norm_date("06/30/80", hints=DocHints(date_order="MDY", two_digit_pivot=85))[0] == (
        "2080-06-30"
    )


def test_dates_use_the_window():
    assert norm_date("06/30/77", hints=US)[0] == "1977-06-30"
    assert norm_date("06/30/76", hints=US)[0] == "2076-06-30"
    assert norm_date("9-Jul-31", hints=US)[0] == "2031-07-09"
    assert norm_month("Sep-31", hints=US)[0] == "2031-09"


def test_out_of_range_flips_century_once():
    past = (1800, 2026)  # e.g. a 'date built' field
    assert norm_date("06/30/31", hints=US, year_range=past) == ("1931-06-30", "ok")
    assert norm_month("Sep-31", hints=US, year_range=past)[0] == "1931-09"
    assert norm_date("06/30/80", hints=US, year_range=(2050, 2100)) == ("2080-06-30", "ok")


def test_still_out_of_range_after_one_flip_is_null():
    assert norm_date("06/30/31", hints=US, year_range=(2040, 2050)) == (None, "year_out_of_range")


def test_four_digit_years_are_range_checked_but_never_flipped():
    assert norm_date("June 30, 2031", hints=US, year_range=(1800, 2026)) == (
        None,
        "year_out_of_range",
    )
    assert norm_date("June 30, 2031", hints=US, year_range=YEAR_RANGE_WIDE)[0] == "2031-06-30"


def test_fit_year_range_leap_day_flip_fails_safely():
    assert fit_year_range(dt.date(2032, 2, 29), True, (1800, 2026))[0] == dt.date(1932, 2, 29)
    assert fit_year_range(dt.date(2000, 2, 29), True, (1800, 1999)) == (None, "year_out_of_range")


def test_round_trip_accepts_the_flipped_century():
    assert round_trip("1931-06-30", "built 06/30/31", "date", hints=US)
    assert round_trip("2031-06-30", "built 06/30/31", "date", hints=US)
    assert not round_trip("1831-06-30", "built 06/30/31", "date", hints=US)


def test_compiler_sets_year_ranges():
    built = compile_field("date_built", {"name": "Date Built", "description": "When built."})
    assert built.type == "date" and built.year_range[0] == 1800
    exp = compile_field("expiration_date", {"name": "Expiration Date", "description": "End."})
    assert exp.year_range == YEAR_RANGE_WIDE
    rent = compile_field("monthly_rent", {"name": "Monthly Rent", "description": "Rent."})
    assert rent.year_range is None


def test_dispatcher_passes_the_range():
    assert normalise("06/30/31", "date", hints=US, year_range=(1800, 2026))[0] == "1931-06-30"
    assert normalise(["06/30/31"], "list", hints=US, item_type="date",
                     year_range=(1800, 2026))[0] == ["1931-06-30"]  # fmt: skip
