"""Value normaliser (P5-12, DR15 rulebook). One function per value type.

Every function returns (value | None, reason_code). A rule that cannot be sure returns None
with a reason, never a guess: a wrong value costs more than a null (brief §4, R24).

Reason codes: ok, ok_hedged, empty, no_date, partial_date, ambiguous_date, range_unresolved,
no_month, no_year, ambiguous_year, no_number, ambiguous_number, ambiguous_separator,
words_numerals_mismatch, not_integer, unparseable, item_dropped, not_a_list.

`round_trip(value, quote, type)` re-reads the quote with the same parsers and checks the
normalised value is one of the values the quote states (R36: compare parsed values, not raw
substrings).

Rules are general (no document-specific keywords). Logs never carry values (R23); this module
does not log at all.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from dateutil.relativedelta import relativedelta
from rapidfuzz import fuzz

Result = tuple[Any, str]

TYPES = (
    "date",
    "month",
    "year",
    "number",
    "integer",
    "percent",
    "boolean",
    "list",
    "code",
    "text",
    "free_text",
)
DATE_ROLES = (None, "start", "end", "period_end")


@dataclass(frozen=True)
class DocHints:
    """Document-level facts the caller passes in (voted once per document)."""

    date_order: str | None = None  # "MDY" | "DMY" | None (no vote)
    decimal_comma: bool = False  # "1.234,56" style numbers


NO_HINTS = DocHints()

# --- shared text prep ------------------------------------------------------------------------

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")
_QUOTES = {
    **dict.fromkeys(map(ord, "‘’‚‛′´`"), "'"),
    **dict.fromkeys(map(ord, "“”„‟″"), '"'),
}
_SOFT = dict.fromkeys(map(ord, "­​‌‍﻿"), None)


def unify(text: str) -> str:
    """NFKC + one dash, one apostrophe, one double quote; zero-width chars removed."""
    return (
        unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_QUOTES).translate(_SOFT)
    )


def _squash(text: str) -> str:
    return " ".join(text.split())


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# --- number words ----------------------------------------------------------------------------

_UNITS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
}
_TENS = {
    w: 10 * i
    for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2)
}
_BIG = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_NUM_WORDS = {**_UNITS, **_TENS, "hundred": 100, **_BIG}
_ORD_FIX = {
    "first": "one",
    "second": "two",
    "third": "three",
    "fifth": "five",
    "eighth": "eight",
    "ninth": "nine",
    "twelfth": "twelve",
}


def words_to_int(tokens: list[str]) -> int | None:
    """Cardinal words -> int ("forty two thousand" -> 42000). None if any token is foreign."""
    total = current = 0
    seen = False
    for t in tokens:
        if t == "and":
            continue
        if t in _UNITS:
            current += _UNITS[t]
        elif t in _TENS:
            current += _TENS[t]
        elif t == "hundred":
            current = (current or 1) * 100
        elif t in _BIG:
            total += (current or 1) * _BIG[t]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def _word_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,-]+", text.lower()) if t]


def ordinal_words_to_int(text: str) -> int | None:
    """'twenty-first' -> 21, 'third' -> 3, '3rd' -> 3."""
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", text.strip().lower())
    if m:
        return int(m.group(1))
    toks = _word_tokens(text)
    if not toks:
        return None
    last = toks[-1]
    if last in _ORD_FIX:
        last = _ORD_FIX[last]
    elif last.endswith("ieth"):
        last = last[:-4] + "y"
    elif last.endswith("th"):
        last = last[:-2]
    return words_to_int([*toks[:-1], last])


def year_words_to_int(text: str) -> int | None:
    """'two thousand twenty-two' -> 2022; 'nineteen ninety-eight' -> 1998."""
    toks = [t for t in _word_tokens(text) if t != "and"]
    if not toks or any(t not in _NUM_WORDS for t in toks):
        return None
    if not any(t == "hundred" or t in _BIG for t in toks):
        chunks: list[int] = []  # two-digit chunks: "nineteen" | "ninety eight"
        i = 0
        while i < len(toks):
            v = _NUM_WORDS[toks[i]]
            if toks[i] in _TENS and i + 1 < len(toks) and 0 < _UNITS.get(toks[i + 1], 0) < 10:
                v += _UNITS[toks[i + 1]]
                i += 1
            chunks.append(v)
            i += 1
        if len(chunks) == 2 and 10 <= chunks[0] <= 99 and 0 <= chunks[1] <= 99:
            return chunks[0] * 100 + chunks[1]
        return None
    return words_to_int(toks)


# --- dates -----------------------------------------------------------------------------------

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MON = (
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?(?![a-z])"
)
_ORD = r"(?:st|nd|rd|th)?"
_LEGAL = re.compile(
    r"\b(?P<day>\d{1,2}"
    + _ORD
    + r"|[a-z]+(?:[- ][a-z]+)?)\s+day\s+of\s+"
    + _MON
    + r"[\s,]*(?:in\s+the\s+year\s+(?:of\s+)?)?(?P<year>\d{4}(?!\d)|[a-z]+(?:[\s-]+[a-z]+){0,5})"
)
_ISO = re.compile(r"\b(?P<year>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})(?!\d)")
_MDY = re.compile(
    r"\b" + _MON + r"\s*(?P<day>\d{1,2})" + _ORD + r"(?!\d)\s*,?\s*(?P<year>\d{4})(?!\d)"
)
_DMY = re.compile(
    r"\b(?P<day>\d{1,2})"
    + _ORD
    + r"(?:\s+day\s+of)?[\s-]*"
    + _MON
    + r"[\s,.-]*(?P<year>\d{4}|\d{2})(?!\d)"
)
_NUMERIC = re.compile(
    r"\b(?P<a>\d{1,2})(?P<sep>[/.-])(?P<b>\d{1,2})(?P=sep)(?P<year>\d{4}|\d{2})(?![\d])"
)
_MON_Y4 = re.compile(r"\b" + _MON + r"[\s,.'-]*(?P<year>\d{4})(?!\d)")
_MON_Y2 = re.compile(r"\b" + _MON + r"\s*['-]\s*(?P<year>\d{2})(?!\d)")
_NUM_MY = re.compile(r"\b(?P<m>\d{1,2})/(?P<year>\d{4})(?!\d)")
_ISO_MY = re.compile(r"\b(?P<year>\d{4})-(?P<m>\d{2})(?![\d-])")
_SPLIT_YEAR = re.compile(r"(,\s*)(1[89]|20)\s(\d{2})\b")  # "March 4, 19 87"


@dataclass(frozen=True)
class DateCand:
    start: int
    kind: str  # "date" | "month" | "amb"
    date: dt.date | None = None
    month: tuple[int, int] | None = None
    options: tuple[dt.date, ...] = ()  # "amb": (month-first reading, day-first reading)


def _year2(yy: str) -> int:
    n = int(yy)
    if len(yy) == 4:
        return n
    return 1900 + n if n >= 50 else 2000 + n


def _mon(name: str) -> int:
    return _MONTHS[name.lower().rstrip(".")[:3]]


def _mkdate(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _prep_dates(text: str) -> str:
    t = _squash(unify(text).casefold())
    return _SPLIT_YEAR.sub(r"\1\2\3", t)


def _mask(t: str, m: re.Match[str]) -> str:
    return t[: m.start()] + " " * (m.end() - m.start()) + t[m.end() :]


def extract_dates(text: str) -> list[DateCand]:
    """Every date / month-year / ambiguous numeric date stated in text, in reading order."""
    t = _prep_dates(text)
    out: list[DateCand] = []

    def scan(rx: re.Pattern[str], build: Callable[[re.Match[str]], DateCand | None]) -> None:
        nonlocal t
        for m in list(rx.finditer(t)):
            cand = build(m)
            if cand is not None:
                out.append(cand)
                t = _mask(t, m)

    def legal(m: re.Match[str]) -> DateCand | None:
        day = ordinal_words_to_int(m["day"])
        raw = m["year"]
        if raw.isdigit():
            year: int | None = int(raw)
        else:  # longest prefix of number words
            toks = _word_tokens(raw)
            k = 0
            while k < len(toks) and (toks[k] in _NUM_WORDS or toks[k] == "and"):
                k += 1
            year = year_words_to_int(" ".join(toks[:k])) if k else None
        if day is None or year is None:
            return None
        d = _mkdate(year, _mon(m["mon"]), day)
        return DateCand(m.start(), "date", date=d) if d else None

    def iso(m: re.Match[str]) -> DateCand | None:
        d = _mkdate(int(m["year"]), int(m["m"]), int(m["d"]))
        return DateCand(m.start(), "date", date=d) if d else None

    def named(m: re.Match[str]) -> DateCand | None:
        d = _mkdate(_year2(m["year"]), _mon(m["mon"]), int(m["day"]))
        return DateCand(m.start(), "date", date=d) if d else None

    def numeric(m: re.Match[str]) -> DateCand | None:
        a, b, y = int(m["a"]), int(m["b"]), _year2(m["year"])
        mdy, dmy = _mkdate(y, a, b), _mkdate(y, b, a)
        if mdy and dmy and mdy != dmy:
            return DateCand(m.start(), "amb", options=(mdy, dmy))
        d = mdy or dmy
        return DateCand(m.start(), "date", date=d) if d else None

    def month_year(m: re.Match[str]) -> DateCand | None:
        mon = _mon(m["mon"]) if "mon" in m.groupdict() and m["mon"] else int(m["m"])
        if not 1 <= mon <= 12:
            return None
        return DateCand(m.start(), "month", month=(_year2(m["year"]), mon))

    scan(_LEGAL, legal)
    scan(_ISO, iso)
    scan(_MDY, named)
    scan(_DMY, named)
    scan(_NUMERIC, numeric)
    scan(_MON_Y4, month_year)
    scan(_MON_Y2, month_year)
    scan(_NUM_MY, month_year)
    scan(_ISO_MY, month_year)
    return sorted(out, key=lambda c: c.start)


def vote_date_order(texts: Iterable[str]) -> str | None:
    """Document-level MDY/DMY vote from unambiguous numeric dates (13/07 = DMY, 07/13 = MDY).
    None when there is no vote or the vote is tied."""
    mdy = dmy = 0
    for text in texts:
        for m in _NUMERIC.finditer(_prep_dates(text)):
            a, b = int(m["a"]), int(m["b"])
            if a > 12 >= b:
                dmy += 1
            elif b > 12 >= a:
                mdy += 1
    if mdy == dmy:
        return None
    return "MDY" if mdy > dmy else "DMY"


def month_end(year: int, month: int) -> dt.date:
    return dt.date(year, month, 1) + relativedelta(months=1, days=-1)


def add_months(d: dt.date, months: int) -> dt.date:
    """Calendar month arithmetic (day clipped to the month's end). For computed fields."""
    return d + relativedelta(months=months)


def _resolve(c: DateCand, hints: DocHints) -> dt.date | None:
    if c.kind == "date":
        return c.date
    if c.kind == "amb" and hints.date_order in ("MDY", "DMY"):
        return c.options[0 if hints.date_order == "MDY" else 1]
    return None


def norm_date(value: Any, *, hints: DocHints = NO_HINTS, role: str | None = None) -> Result:
    """ISO date. role: start / end pick from a range; period_end lets a month-year mean the
    month's last day. A missing day / month / year is never filled from today (R24)."""
    if role not in DATE_ROLES:
        raise ValueError(f"unknown date role {role!r}")
    if _is_blank(value):
        return None, "empty"
    if isinstance(value, dt.datetime):
        return value.date().isoformat(), "ok"
    if isinstance(value, dt.date):
        return value.isoformat(), "ok"
    cands = extract_dates(str(value))
    if not cands:
        return None, "no_date"
    if len(cands) > 1:
        if role in ("end", "period_end"):
            cands = [cands[-1]]
        elif role == "start":
            cands = [cands[0]]
        else:
            got = {_resolve(c, hints) for c in cands}
            if len(got) != 1 or None in got:
                return None, "range_unresolved"
            cands = [cands[0]]
    c = cands[0]
    if c.kind == "month":
        if role == "period_end" and c.month:
            return month_end(*c.month).isoformat(), "ok"
        return None, "partial_date"
    d = _resolve(c, hints)
    if d is None:
        return None, "ambiguous_date"
    return d.isoformat(), "ok"


def norm_month(value: Any, *, hints: DocHints = NO_HINTS, role: str | None = None) -> Result:
    """'YYYY-MM' (only for fields that explicitly ask for a month; the compiler decides)."""
    if _is_blank(value):
        return None, "empty"
    cands = extract_dates(str(value))
    months: list[tuple[int, int] | None] = []
    for c in cands:
        if c.kind == "month":
            months.append(c.month)
        else:
            d = _resolve(c, hints)
            if d is None and c.kind == "amb" and c.options[0].year == c.options[1].year:
                months.append(None)  # month unknown without a date-order vote
            else:
                months.append((d.year, d.month) if d else None)
    if not months:
        return None, "no_month"
    if len(set(months)) > 1:
        if role in ("end", "period_end"):
            months = [months[-1]]
        elif role == "start":
            months = [months[0]]
        else:
            return None, "range_unresolved"
    if months[0] is None:
        return None, "ambiguous_date"
    y, m = months[0]
    return f"{y:04d}-{m:02d}", "ok"


_YEAR_TOKEN = re.compile(r"(?<!\d)(1[89]\d{2}|2[01]\d{2})(?!\d)")


def norm_year(value: Any, **_: Any) -> Result:
    if _is_blank(value):
        return None, "empty"
    if isinstance(value, int) and not isinstance(value, bool):
        return (value, "ok") if 1800 <= value <= 2199 else (None, "no_year")
    text = unify(str(value))
    years = {int(y) for y in _YEAR_TOKEN.findall(text)}
    if len(years) == 1:
        return years.pop(), "ok"
    if len(years) > 1:
        return None, "ambiguous_year"
    y = year_words_to_int(text)
    if y is not None and 1800 <= y <= 2199:
        return y, "ok"
    return None, "no_year"


# --- numbers ---------------------------------------------------------------------------------

_OCR_RUN = re.compile(r"(?<![A-Za-z])(?=[\dOoIl,.]*\d)[\dOoIl][\dOoIl,.]*(?![A-Za-z])")
_HEDGE = re.compile(
    r"\b(?:approx(?:imately|\.)?|about|around|circa|roughly|nearly|estimated|some)\b|~|±|\+/-",
    re.I,
)
_NUMERAL = re.compile(
    r"(?P<lpar>\()?\s*(?P<cur1>[$€£¥])?\s*(?P<lpar2>\()?\s*(?P<sign>[-+])?\s*(?P<cur2>[$€£¥])?"
    r"(?P<num>\d+(?:[.,]\d+)*)"
    r"(?:(?P<lscale>mm|bn|[kmb])(?![a-z0-9])|\s?(?P<wscale>thousand|million|billion)\b)?"
    r"(?P<rpar>\))?(?P<tminus>-(?!\d))?(?P<pct>\s?%|\s?percent\b|\s?per\s?cent\b)?"
    r"(?![A-Za-z\d])",
    re.I,
)
_SCALES = {"k": 1e3, "m": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}
_SCALES.update({"thousand": 1e3, "million": 1e6, "billion": 1e9})
_WORD_RUN = re.compile(r"[a-z]+(?:[\s,-]+[a-z]+)*", re.I)
_CENTS = re.compile(r"\s*(?:and\s+)?(\d{1,2})\s*/\s*100\b", re.I)
_PAIRED = re.compile(
    r"\s*(?:u\.?s\.?\s+)?(?:dollars?|usd|euros?|pounds?|percent|per\s?cent)?\s*\(([^()]*)\)", re.I
)


@dataclass(frozen=True)
class Numeral:
    value: float
    percent: bool = False


def _ocr_fix(text: str) -> str:
    return _OCR_RUN.sub(lambda m: m.group(0).translate(str.maketrans("OoIl", "0011")), text)


def parse_numeral(s: str, *, decimal_comma: bool = False) -> float | None:
    """'1,234.5' / '1.234,56' / '12,34,567' -> float. None when the separators are ambiguous."""
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    if "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s) and not (decimal_comma and s.count(",") == 1):
            return float(s.replace(",", ""))
        if re.fullmatch(r"\d{1,2}(,\d{2})+,\d{3}", s):  # Indian grouping
            return float(s.replace(",", ""))
        if decimal_comma and re.fullmatch(r"\d+,\d+", s):
            return float(s.replace(",", "."))
        return None
    if s.count(".") > 1:
        return float(s.replace(".", "")) if re.fullmatch(r"\d{1,3}(\.\d{3})+", s) else None
    if decimal_comma and re.fullmatch(r"\d{1,3}\.\d{3}", s):
        return float(s.replace(".", ""))
    try:
        return float(s)
    except ValueError:
        return None


def _numerals(text: str, hints: DocHints) -> tuple[list[Numeral], bool]:
    """Numerals in text -> values; second item True if a numeral had ambiguous separators."""
    out: list[Numeral] = []
    bad = False
    for m in _NUMERAL.finditer(text):
        v = parse_numeral(m["num"], decimal_comma=hints.decimal_comma)
        if v is None:
            bad = True
            continue
        has_cur = bool(m["cur1"] or m["cur2"])
        if m["lscale"] and has_cur:  # letter scale only when clearly money ($3.4M)
            v *= _SCALES[m["lscale"].lower()]
        elif m["lscale"]:
            continue  # "12m": months? metres? not a number we can trust
        if m["wscale"]:
            v *= _SCALES[m["wscale"].lower()]
        neg = (bool(m["lpar"] or m["lpar2"]) and bool(m["rpar"])) or m["sign"] == "-"
        if m["tminus"]:
            neg = True
        out.append(Numeral(-v if neg else v, percent=bool(m["pct"])))
    return out, bad


def _word_amounts(text: str, hints: DocHints) -> tuple[str, list[Numeral], list[Numeral], bool]:
    """Find amounts written in words. Returns (text with them masked, paired values, unpaired
    values, mismatch). Paired = words followed by the same amount in figures, the legal
    convention 'Forty Dollars ($40.00)'; the two must agree."""
    paired: list[Numeral] = []
    loose: list[Numeral] = []
    mismatch = False
    masked = text
    for m in _WORD_RUN.finditer(text):
        toks = re.split(r"[\s,-]+", m.group(0).lower())
        # longest run of number words inside this word run
        best: tuple[int, int] | None = None
        i = 0
        while i < len(toks):
            if toks[i] in _NUM_WORDS:
                j = i
                while j < len(toks) and (toks[j] in _NUM_WORDS or toks[j] == "and"):
                    j += 1
                while j > i and toks[j - 1] == "and":
                    j -= 1
                if best is None or j - i > best[1] - best[0]:
                    best = (i, j)
                i = j
            else:
                i += 1
        if best is None or not any(t in _UNITS or t in _TENS for t in toks[best[0] : best[1]]):
            continue  # a lone scale word ("12.5 million") belongs to the figure before it
        value = words_to_int(toks[best[0] : best[1]])
        if value is None:
            continue
        # span of the number words inside the original text
        span_text = m.group(0)
        words_re = r"[\s,-]+".join(re.escape(t) for t in toks[best[0] : best[1]])
        wm = re.search(words_re, span_text, re.I)
        if wm is None:
            continue
        start, end = m.start() + wm.start(), m.start() + wm.end()
        rest = text[end:]
        cents = _CENTS.match(rest)
        amount = float(value)
        if cents:
            amount += int(cents.group(1)) / 100
            end += cents.end()
            rest = text[end:]
        pm = _PAIRED.match(rest)
        if pm:
            figs, _ = _numerals(pm.group(1), hints)
            if figs:
                if any(abs(f.value - amount) > 0.005 for f in figs):
                    mismatch = True
                paired.append(Numeral(amount, percent=figs[0].percent))
                end += pm.end()
            else:
                loose.append(Numeral(amount))
        else:
            loose.append(Numeral(amount))
        masked = masked[:start] + " " * (end - start) + masked[end:]
    return masked, paired, loose, mismatch


def all_numbers(text: str, hints: DocHints = NO_HINTS) -> list[Numeral]:
    """Every number the text states (figures with sign / scale, amounts in words)."""
    t = _ocr_fix(unify(text))
    masked, paired, loose, _ = _word_amounts(t, hints)
    figs, _ = _numerals(masked, hints)
    return [*paired, *figs, *loose]


def _as_number(v: float) -> int | float:
    return int(v) if float(v).is_integer() and abs(v) < 1e15 else v


def norm_number(
    value: Any, *, hints: DocHints = NO_HINTS, percent: bool = False, **_: Any
) -> Result:
    """JSON number. Currency / separators stripped, (1,234) and 1,234- negative, scale only
    when attached, words checked against figures. reason ok_hedged for 'approximately'."""
    if isinstance(value, bool):
        return None, "unparseable"
    if isinstance(value, int | float):
        return _as_number(float(value)), "ok"
    if _is_blank(value):
        return None, "empty"
    t = _ocr_fix(unify(str(value)))
    hedged = bool(_HEDGE.search(t))
    masked, paired, loose, mismatch = _word_amounts(t, hints)
    if mismatch:
        return None, "words_numerals_mismatch"
    masked = re.sub(r"\b\d{1,2}\s*/\s*100\b", " ", masked)
    figs, bad = _numerals(masked, hints)
    vals = paired + figs
    if percent and any(n.percent for n in vals):
        vals = [n for n in vals if n.percent]
    if not vals:
        if bad:
            return None, "ambiguous_separator"
        vals = loose
    distinct = {round(n.value, 6) for n in vals}
    if not distinct:
        return None, "no_number"
    if len(distinct) > 1:
        return None, "ambiguous_number"
    return _as_number(distinct.pop()), "ok_hedged" if hedged else "ok"


def norm_integer(value: Any, *, hints: DocHints = NO_HINTS, **_: Any) -> Result:
    v, reason = norm_number(value, hints=hints)
    if v is None:
        return None, reason
    if not float(v).is_integer():
        return None, "not_integer"
    return int(v), reason


def norm_percent(value: Any, *, hints: DocHints = NO_HINTS, **_: Any) -> Result:
    """The number as printed: '5.26%' -> 5.26 (never divided by 100)."""
    return norm_number(value, hints=hints, percent=True)


# --- booleans --------------------------------------------------------------------------------

_CHECKED = "☒☑✓✔✗✘■▣"
_MARK = re.compile(
    r"(?P<mark>["
    + _CHECKED
    + r"☐□]|\[\s*[xX✓✔]?\s*\]|\(\s*[xX✓✔]?\s*\))\s*(?P<label>yes|no|true|false)\b",
    re.I,
)
_TRUE = {"yes", "y", "true", "t", "1", "required", "included", "checked", "x"}
_FALSE = {"no", "n", "false", "f", "0", "none", "not required", "not included", "unchecked"}


def norm_boolean(value: Any, **_: Any) -> Result:
    if isinstance(value, bool):
        return value, "ok"
    if isinstance(value, int | float):
        return (bool(value), "ok") if value in (0, 1) else (None, "unparseable")
    if _is_blank(value):
        return None, "empty"
    t = unify(str(value))
    checked: set[bool] = set()
    for m in _MARK.finditer(t):
        mark = m["mark"]
        is_checked = mark in _CHECKED or bool(re.search(r"[xX✓✔]", mark))
        if is_checked:
            checked.add(m["label"].lower() in ("yes", "true"))
    if len(checked) == 1:
        return checked.pop(), "ok"
    if len(checked) > 1:
        return None, "unparseable"
    w = _squash(t.lower()).strip(" .")
    if w in _TRUE:
        return True, "ok"
    if w in _FALSE:
        return False, "ok"
    return None, "unparseable"


# --- codes and text --------------------------------------------------------------------------


def norm_code(value: Any, **_: Any) -> Result:
    """Identifiers (zip, suite, unit, GL account) stay strings; never turned into numbers."""
    if isinstance(value, bool) or _is_blank(value):
        return None, "empty"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    t = _trim_label(_squash(unify(str(value))))
    t = t.strip(" \"'").rstrip(".,;:")
    return (t, "ok") if t else (None, "empty")


_DEHYPHEN = re.compile(r"(\w)-[ \t]*\r?\n\s*(\w)")
# enumerators: "(a)", "a)", "iv)", "1.", "§ 4.2" (never "J." - that is an initial)
_ENUM = re.compile(r"^(?:\(\w{1,4}\)|\w{1,4}\)|\d{1,3}\.|§+\s*[\d.]+)\s+", re.I)
_LABEL = re.compile(r"^([A-Za-z][A-Za-z '/&-]{0,40}?)\s*:\s+(?=\S)")
# trailing cross-reference with an identifier: "(see Section 12)", ", pursuant to Exhibit B"
_XREF_LEAD = (
    r"(?:see|as\s+(?:set\s+forth|defined|described|provided)\s+in|pursuant\s+to"
    r"|in\s+accordance\s+with)"
)
_XREF_REF = (
    r"(?:section|article|exhibit|schedule|paragraph|rider|addendum|§)\s*"
    r"(?:\d[\w.()-]*|[a-z](?![a-z])|[ivxlc]+(?![a-z]))"
)
_XREF = re.compile(
    r"(?:[\s,;]*\(\s*(?:" + _XREF_LEAD + r"\s+)?" + _XREF_REF + r"\s*\)"
    r"|[\s,;]+" + _XREF_LEAD + r"\s+" + _XREF_REF + r")\s*\.?\s*$",
    re.I,
)


def _trim_label(t: str) -> str:
    m = _LABEL.match(t)
    if m and len(m.group(1).split()) <= 5 and not re.search(r"\d", m.group(1)):
        return t[m.end() :]
    return t


def norm_text(value: Any, **_: Any) -> Result:
    """Free text: the source wording with labels, enumerators and trailing cross-references
    trimmed; line-break hyphens joined. Wording is never rewritten."""
    if _is_blank(value):
        return None, "empty"
    if isinstance(value, bool | int | float):
        return str(value), "ok"
    t = _DEHYPHEN.sub(r"\1\2", unify(str(value)))
    t = _squash(t)
    for _ in range(2):
        before = t
        t = _ENUM.sub("", t)
        t = _trim_label(t)
        if t == before:
            break
    stripped = _XREF.sub("", t)
    if stripped.strip():  # never trim a value down to nothing
        t = stripped
    t = t.strip().rstrip(",;:").strip()
    return (t, "ok") if t else (None, "empty")


# --- lists -----------------------------------------------------------------------------------

_LIST_SPLIT = re.compile(r"\s*(?:\r?\n|;|•|·|\|)\s*")
_BULLET = re.compile(r"^(?:[-*–]\s+|\(?\w{1,3}[.)]\s+)")


def norm_list(
    value: Any, *, hints: DocHints = NO_HINTS, item_type: str = "text", role: str | None = None
) -> Result:
    """Split only on structural delimiters (line breaks, ';', bullets, '|'), never on commas
    (names contain them). Items normalised by item_type, deduplicated, order kept."""
    if value is None:
        return None, "empty"
    if isinstance(value, list | tuple):
        raw = list(value)
    elif isinstance(value, str):
        if not value.strip():
            return [], "ok"
        raw = [_BULLET.sub("", p) for p in _LIST_SPLIT.split(value) if p.strip()]
    else:
        return None, "not_a_list"
    fn = NORMALISERS["text" if item_type in ("list", "free_text") else item_type]
    out: list[Any] = []
    seen: set[str] = set()
    dropped = 0
    for item in raw:
        v, _r = fn(item, hints=hints, role=role)
        if v is None:
            dropped += 1
            continue
        key = str(v).casefold()
        if key not in seen:
            seen.add(key)
            out.append(v)
    if raw and not out:
        return None, "item_dropped"
    return out, "item_dropped" if dropped else "ok"


NORMALISERS: dict[str, Callable[..., Result]] = {
    "date": norm_date,
    "month": norm_month,
    "year": norm_year,
    "number": norm_number,
    "integer": norm_integer,
    "percent": norm_percent,
    "boolean": norm_boolean,
    "code": norm_code,
    "text": norm_text,
    "free_text": norm_text,
}


def normalise(
    value: Any,
    type_: str,
    *,
    hints: DocHints = NO_HINTS,
    role: str | None = None,
    item_type: str = "text",
) -> Result:
    """Dispatch by field type. Unknown types are treated as free text (never crash)."""
    if type_ == "list":
        return norm_list(value, hints=hints, item_type=item_type, role=role)
    fn = NORMALISERS.get(type_, norm_text)
    if type_ in ("date", "month"):
        return fn(value, hints=hints, role=role)
    return fn(value, hints=hints)


# --- round trip ------------------------------------------------------------------------------


def match_text(s: str) -> str:
    """Comparison form: unified, casefolded, whitespace collapsed."""
    return _squash(unify(s).casefold())


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.005, 1e-9 * abs(b))


def _date_values(quote: str) -> tuple[set[dt.date], set[tuple[int, int]]]:
    dates: set[dt.date] = set()
    months: set[tuple[int, int]] = set()
    for c in extract_dates(quote):
        if c.kind == "date" and c.date:
            dates.add(c.date)
        elif c.kind == "amb":
            dates.update(c.options)  # presence check: either reading may be the one
        elif c.kind == "month" and c.month:
            months.add(c.month)
    return dates, months


def round_trip(
    value: Any,
    quote: str,
    type_: str,
    *,
    hints: DocHints = NO_HINTS,
    item_type: str = "text",
) -> bool:
    """True when the normalised value is one of the values the quote itself states."""
    if value is None:
        return True  # nothing claimed
    q = quote or ""
    if type_ == "list":
        if not isinstance(value, list):
            return False
        return all(round_trip(v, q, item_type, hints=hints) for v in value)
    if type_ == "boolean":
        return value is False or bool(q.strip())  # R25: false needs no quote
    if type_ in ("number", "integer", "percent"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        return any(_close(n.value, float(value)) for n in all_numbers(q, hints))
    if type_ == "date":
        try:
            d = dt.date.fromisoformat(str(value))
        except ValueError:
            return False
        dates, months = _date_values(q)
        return d in dates or ((d.year, d.month) in months and d == month_end(d.year, d.month))
    if type_ == "month":
        m = re.fullmatch(r"(\d{4})-(\d{2})", str(value))
        if not m:
            return False
        ym = (int(m.group(1)), int(m.group(2)))
        dates, months = _date_values(q)
        return ym in months or any((d.year, d.month) == ym for d in dates)
    if type_ == "year":
        try:
            y = int(value)
        except (TypeError, ValueError):
            return False
        dates, months = _date_values(q)
        found = {int(t) for t in _YEAR_TOKEN.findall(unify(q))}
        return y in found or any(d.year == y for d in dates) or any(m[0] == y for m in months)
    if type_ == "code":
        v = match_text(str(value))
        if not v:
            return False
        pat = r"\s?".join(re.escape(ch) for ch in v.replace(" ", ""))  # "02 134" ~ "02134"
        return re.search(r"(?<![a-z0-9])" + pat + r"(?![a-z0-9])", match_text(q)) is not None
    # text / free_text / unknown
    v = match_text(str(value))
    hay = match_text(_DEHYPHEN.sub(r"\1\2", unify(q)))
    if not v:
        return False
    if v in hay:
        return True
    return len(v) >= 8 and fuzz.partial_ratio(v, hay) >= 90
