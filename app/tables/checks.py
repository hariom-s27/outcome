"""Free checks on an executed spec (P6 T-10). Each returns pass/fail + a number.

C1 key uniqueness (>= 0.98 unique) and shape conformity (>= 0.9 share of the dominant shape)
C2 coverage: unexplained lines <= 2% of the non-blank lines of the data range
C3 totals: where total lines (total word / SUM formula / equals-sum) carry a value in a column
   the spec reads, the records add up to it within 0.5% (>= 90% of those cells). A total may
   be a block subtotal, the sum of earlier subtotals, or a running grand total. Not
   applicable (None) when no such total exists.
C4 type fit: per mapped column (row fields; document-level cells are not columns), >= 0.9 of
   its non-empty source cells parse as the field type
C5 rows >= 1 and no record key contains a total-like word
Spec score = checks passed (C3 only when applicable). Hard fail = C1 or C5 failed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.tables.execute import Execution
from app.tables.profile import close, has_total_word, shape

UNIQUE_MIN = 0.98
SHAPE_MIN = 0.9
UNEXPLAINED_MAX = 0.02
TOTALS_MIN = 0.9
TYPE_FIT_MIN = 0.9
TOTAL_DISPS = ("skipped-total_like", "skipped-formula_sum_rows")


@dataclass
class Check:
    passed: bool | None  # None = not applicable
    value: float
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "value": round(self.value, 4), **self.detail}


def c1_keys(ex: Execution) -> Check:
    keys = ex.keys_seen
    if not keys:
        return Check(False, 0.0, {"keys": 0})
    unique = len(set(keys)) / len(keys)
    shapes = Counter(shape(k) for k in keys)
    share = shapes.most_common(1)[0][1] / len(keys)
    ok = unique >= UNIQUE_MIN and share >= SHAPE_MIN
    return Check(ok, min(unique, share), {"unique": round(unique, 4), "shape": round(share, 4)})


def c2_coverage(ex: Execution) -> Check:
    n = max(1, ex.region_lines)
    bad = ex.dispositions.get("unexplained", 0)
    share = bad / n
    return Check(share <= UNEXPLAINED_MAX, share, {"unexplained": bad, "lines": ex.region_lines})


def c3_totals(ex: Execution) -> Check:
    cols = ex.value_cols
    if not cols:
        return Check(None, 0.0, {"checked": 0})
    local: dict[str, float] = dict.fromkeys(cols, 0.0)
    local_n: dict[str, int] = dict.fromkeys(cols, 0)
    running: dict[str, float] = dict.fromkeys(cols, 0.0)
    running_n: dict[str, int] = dict.fromkeys(cols, 0)
    subs: dict[str, float] = dict.fromkeys(cols, 0.0)
    subs_n: dict[str, int] = dict.fromkeys(cols, 0)
    checked = matched = 0
    for ln, disp in ex.ordered:
        nums = ln.numeric
        if disp in ("record", "child"):
            for c in cols:
                if c in nums:
                    local[c] += nums[c]
                    local_n[c] += 1
                    running[c] += nums[c]
                    running_n[c] += 1
            continue
        if disp not in TOTAL_DISPS:
            continue
        for c in cols:
            if c not in nums:
                continue
            v = nums[c]
            checked += 1
            is_local = local_n[c] > 0 and close(v, local[c])
            is_subs = subs_n[c] > 1 and close(v, subs[c])
            is_run = running_n[c] > 0 and close(v, running[c]) and not is_local
            if is_local or is_subs or is_run:
                matched += 1
            if is_subs or is_run:
                running[c], running_n[c], subs[c], subs_n[c] = 0.0, 0, 0.0, 0
            else:
                subs[c] += v
                subs_n[c] += 1
            local[c], local_n[c] = 0.0, 0
    if checked == 0:
        return Check(None, 0.0, {"checked": 0})
    share = matched / checked
    return Check(share >= TOTALS_MIN, share, {"checked": checked, "matched": matched})


def c4_type_fit(ex: Execution) -> Check:
    worst = 1.0
    bad: dict[str, float] = {}
    for key, (ok, tried) in ex.parse.items():
        if tried == 0:
            continue
        share = ok / tried
        worst = min(worst, share)
        if share < TYPE_FIT_MIN:
            bad[key] = round(share, 3)
    return Check(not bad, worst, {"fields_below": dict(sorted(bad.items()))})


def c5_rows(ex: Execution) -> Check:
    rows = len(ex.records)
    totals = sum(1 for r in ex.records if has_total_word(r.key))
    return Check(rows >= 1 and totals == 0, float(rows), {"rows": rows, "total_keys": totals})


def run_checks(ex: Execution) -> dict[str, Check]:
    return {
        "C1": c1_keys(ex),
        "C2": c2_coverage(ex),
        "C3": c3_totals(ex),
        "C4": c4_type_fit(ex),
        "C5": c5_rows(ex),
    }


def spec_score(checks: dict[str, Check]) -> tuple[int, bool]:
    """(number of checks passed, hard fail)."""
    score = sum(1 for c in checks.values() if c.passed is True)
    hard = checks["C1"].passed is not True or checks["C5"].passed is not True
    return score, hard
