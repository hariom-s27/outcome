"""Citation checker (P5-11): is the model's quote really in the cited block?

find_quote normalises both sides (NFKC, one quote / dash style, collapsed whitespace,
casefold), tries an exact match first (word-bounded), then a fuzzy match (rapidfuzz partial
ratio >= 90, only for quotes of >= 8 characters), and returns the SOURCE span it matched,
snapped to word boundaries, so a citation is always real document text. When the cited block
fails it tries the neighbour blocks the caller passes (nearest first) and reports the move.

value_in_quote checks the normalised value is one the quote states (normalise.round_trip).
No logging here: quotes are document text (R23).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from app.extract.normalise import NO_HINTS, DocHints, round_trip, source_value, unify

FUZZY_MIN_SCORE = 90.0
FUZZY_MIN_CHARS = 8
_ELLIPSIS = re.compile(r"\s*(?:\.\s*){3,}\s*|\s*…\s*")
_EDGE_PUNCT = " \t\r\n\"'“”‘’«»"


@dataclass(frozen=True)
class QuoteMatch:
    span: str  # the source text matched (snapped), what the citation will show
    start: int  # offsets into the block text the span came from
    end: int
    kind: str  # "exact" | "fuzzy"
    score: float  # 100 for exact
    block_id: str | None = None  # None = the cited block; else the neighbour it moved to

    @property
    def relocated(self) -> bool:
        return self.block_id is not None


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Comparison form of text plus, for each of its chars, the source index it came from."""
    out: list[str] = []
    idx: list[int] = []
    pending_space = False
    for i, ch in enumerate(text):
        piece = ch.casefold() if ch.isascii() else unify(ch).casefold()  # per char: keeps map
        for p in piece:
            if p.isspace():
                pending_space = bool(out)
                continue
            if pending_space:
                out.append(" ")
                idx.append(i)
                pending_space = False
            out.append(p)
            idx.append(i)
    return "".join(out), idx


def _norm(text: str) -> str:
    return _norm_with_map(text)[0]


def _snap(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen [start, end) to whole words of the source text."""
    while start > 0 and text[start - 1].isalnum() and text[start].isalnum():
        start -= 1
    while end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        end += 1
    return start, end


def _exact(q: str, hay: str) -> tuple[int, int] | None:
    """Word-bounded exact match of normalised q in normalised hay (so '12' never hits '2012')."""
    pat = re.escape(q)
    if q[:1].isalnum():
        pat = r"(?<![^\W_])" + pat
    if q[-1:].isalnum():
        pat = pat + r"(?![^\W_])"
    m = re.search(pat, hay)
    return (m.start(), m.end()) if m else None


def _match_one(quote: str, text: str, min_chars: int = FUZZY_MIN_CHARS) -> QuoteMatch | None:
    q = _norm(quote).strip(_EDGE_PUNCT)
    if not q or not text:
        return None
    hay, idx = _norm_with_map(text)
    if not hay:
        return None
    parts = [p.strip(_EDGE_PUNCT) for p in _ELLIPSIS.split(q)]
    parts = [p for p in parts if p]
    # exact (each part of an elided quote, in order)
    pos = 0
    spans: list[tuple[int, int]] = []
    for p in parts:
        hit = _exact(p, hay[pos:])
        if hit is None:
            spans = []
            break
        spans.append((pos + hit[0], pos + hit[1]))
        pos += hit[1]
    if spans:
        s, e = idx[spans[0][0]], idx[spans[-1][1] - 1] + 1
        return QuoteMatch(text[s:e], s, e, "exact", 100.0)
    # fuzzy: whole quote, long enough only
    if len(q) < min_chars:
        return None
    al = fuzz.partial_ratio_alignment(q, hay, score_cutoff=FUZZY_MIN_SCORE)
    if al is None or al.score < FUZZY_MIN_SCORE or al.dest_end <= al.dest_start:
        return None
    s, e = idx[al.dest_start], idx[al.dest_end - 1] + 1
    s, e = _snap(text, s, e)
    return QuoteMatch(text[s:e].strip(), s, e, "fuzzy", float(al.score))


def find_quote(
    quote: str,
    block_text: str,
    neighbours: Sequence[tuple[str, str]] = (),
    *,
    min_chars: int = FUZZY_MIN_CHARS,
) -> QuoteMatch | None:
    """Find quote in the cited block; else in neighbours [(block_id, text), ...] (the caller
    passes the +-2 blocks, nearest first). None when not found anywhere. min_chars: shortest
    quote the fuzzy step may try (list items use 4, P5b F-4)."""
    if not quote or not quote.strip():
        return None
    hit = _match_one(quote, block_text, min_chars)
    if hit is not None:
        return hit
    for block_id, text in neighbours:
        hit = _match_one(quote, text, min_chars)
        if hit is not None:
            return QuoteMatch(hit.span, hit.start, hit.end, hit.kind, hit.score, block_id)
    return None


def neighbour_ids(ids: Sequence[str], cited: str, radius: int = 2) -> list[str]:
    """Block ids within +-radius of the cited one, nearest first (-1, +1, -2, +2)."""
    try:
        i = list(ids).index(cited)
    except ValueError:
        return []
    out: list[str] = []
    for d in range(1, radius + 1):
        for j in (i - d, i + d):
            if 0 <= j < len(ids):
                out.append(ids[j])
    return out


def value_in_quote(
    value: Any,
    quote: str,
    type_: str,
    *,
    hints: DocHints = NO_HINTS,
    item_type: str = "text",
) -> bool:
    return round_trip(value, quote, type_, hints=hints, item_type=item_type)


def quoted_value(value: Any, quote: str, type_: str, *, hints: DocHints = NO_HINTS) -> Any:
    """P5b G-1: after value_in_quote passed, the value as the quote states it (source wins)."""
    return source_value(value, quote, type_, hints=hints)
