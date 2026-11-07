"""A8 (PR-01): table structure of t12_001 and rentroll_001, by simple rules (no LLM).

Per sheet: header row(s), data region, section rows (one text cell, no numbers), total rows
(a text cell containing "total"), blank rows inside the region, column roles
(key / label / amount / date / code / int) and a record-start rule: the leftmost non-numeric
column with values; a record starts on each data row where it is non-empty.
Compared with the answer row count. Printed: counts, column letters, roles. No header text.
"""

from __future__ import annotations

import datetime as dt

import openpyxl
from _common import Report, doc_path, truth, truth_entries

from app.readers.base import column_letter

DOCS = ("t12_001", "rentroll_001")


def is_num(x: object) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def is_text(x: object) -> bool:
    return isinstance(x, str) and bool(x.strip())


def nonempty(row: list) -> list[int]:
    return [i for i, x in enumerate(row) if x is not None and str(x).strip() != ""]


def find_header(grid: list[list]) -> tuple[int, int]:
    """(first header row index, number of header rows); (-1, 0) if none."""
    for r in range(min(len(grid), 40)):
        cells = nonempty(grid[r])
        if len(cells) < 3 or sum(is_text(grid[r][i]) for i in cells) / len(cells) < 0.7:
            continue
        nxt = [grid[k] for k in range(r + 1, min(r + 6, len(grid)))]
        if any(any(is_num(x) for x in row) for row in nxt):
            n = 1
            while (
                r - n >= 0
                and len(nonempty(grid[r - n])) >= 2
                and all(is_text(grid[r - n][i]) for i in nonempty(grid[r - n]))
            ):
                n += 1
            return r - n + 1, n
    return -1, 0


def role(vals: list) -> str:
    n = len(vals)
    nums = [x for x in vals if is_num(x)]
    dates = [x for x in vals if isinstance(x, dt.date | dt.datetime)]
    texts = [x for x in vals if is_text(x)]
    uniq = len({str(x) for x in vals}) / n
    if len(dates) / n >= 0.6:
        return "date"
    if len(nums) / n >= 0.6:
        if all(float(x).is_integer() for x in nums) and max(abs(x) for x in nums) < 10000:
            return "int" if uniq < 0.9 else "key"
        return "amount"
    if len(texts) / n >= 0.6:
        if uniq >= 0.9:
            return "key"
        if max(len(str(x)) for x in texts) <= 8:
            return "code"
        return "label"
    return "mixed"


def analyse(ws, rep: Report, tag: str) -> int:
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    h0, hn = find_header(grid)
    last = max((i for i, r in enumerate(grid) if nonempty(r)), default=-1)
    start = h0 + hn if h0 >= 0 else 0
    blank = section = total = 0
    data_rows: list[list] = []
    for r in range(start, last + 1):
        cells = nonempty(grid[r])
        if not cells:
            blank += 1
            continue
        if any(is_text(grid[r][i]) and "total" in grid[r][i].lower() for i in cells):
            total += 1
            continue
        if len(cells) == 1 and is_text(grid[r][cells[0]]):
            section += 1
            continue
        data_rows.append(grid[r])
    ncols = max((len(r) for r in data_rows), default=0)
    roles: dict[str, str] = {}
    for c in range(ncols):
        vals = [r[c] for r in data_rows if c < len(r) and r[c] is not None and str(r[c]).strip()]
        if vals:
            roles[column_letter(c)] = f"{role(vals)}({len(vals)})"
    start_col = next(
        (
            c
            for c in range(ncols)
            if column_letter(c) in roles
            and roles[column_letter(c)].split("(")[0] in ("key", "label", "code")
        ),
        None,
    )
    records = (
        sum(1 for r in data_rows if start_col < len(r) and r[start_col] is not None)
        if start_col is not None
        else 0
    )
    rep.sum(
        f"{tag}: header rows={hn} at row {h0 + 1 if h0 >= 0 else '-'}; data region rows "
        f"{start + 1}-{last + 1}; data={len(data_rows)} section={section} total={total} "
        f"blank={blank}; record-start col="
        f"{column_letter(start_col) if start_col is not None else '-'}"
        f" -> records={records}"
    )
    rep.sum(f"{tag}: roles {' '.join(f'{k}={v}' for k, v in roles.items())}")
    return records


def main() -> None:
    rep = Report("a8_table_structure")
    for d in DOCS:
        wb = openpyxl.load_workbook(doc_path(d), data_only=True)
        found = 0
        for si, ws in enumerate(wb.worksheets):
            found += analyse(ws, rep, f"{d} sheet#{si}")
        rep.sum(f"{d}: records by rule={found} vs answer rows={len(truth_entries(truth(d)))}")
    rep.close()


if __name__ == "__main__":
    main()
