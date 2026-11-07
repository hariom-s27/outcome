"""A1 (spike 9): formula cells with / without cached values, merged ranges, hidden parts.
Counts per sheet only (sheet index, not sheet names)."""

from __future__ import annotations

import openpyxl
from _common import Report, doc_path

DOCS = ("rentroll_001", "t12_001")


def main() -> None:
    rep = Report("a1_formulas")
    for d in DOCS:
        p = doc_path(d)
        wf = openpyxl.load_workbook(p, data_only=False)
        wv = openpyxl.load_workbook(p, data_only=True)
        tot = {"formula": 0, "cached": 0, "no_cache": 0, "merged": 0, "hidden_rows": 0}
        hidden_sheets = 0
        for si, ws in enumerate(wf.worksheets):
            wsv = wv.worksheets[si]
            f = cached = nocache = 0
            for row in ws.iter_rows():
                for c in row:
                    if c.data_type == "f" or (isinstance(c.value, str) and c.value.startswith("=")):
                        f += 1
                        if wsv[c.coordinate].value is None:
                            nocache += 1
                        else:
                            cached += 1
            hrows = sum(1 for dim in ws.row_dimensions.values() if dim.hidden)
            hcols = [k for k, dim in ws.column_dimensions.items() if dim.hidden]
            merged = len(ws.merged_cells.ranges)
            hidden_sheets += ws.sheet_state != "visible"
            rep.line(
                f"{d} sheet#{si} state={ws.sheet_state} dims={ws.dimensions} formulas={f} "
                f"cached={cached} no_cache={nocache} merged={merged} hidden_rows={hrows} "
                f"hidden_cols={','.join(hcols) or '-'}"
            )
            tot["formula"] += f
            tot["cached"] += cached
            tot["no_cache"] += nocache
            tot["merged"] += merged
            tot["hidden_rows"] += hrows
        rep.sum(
            f"{d}: sheets={len(wf.worksheets)} hidden_sheets={hidden_sheets} "
            f"formulas={tot['formula']} cached={tot['cached']} no_cache={tot['no_cache']} "
            f"merged={tot['merged']} hidden_rows={tot['hidden_rows']}"
        )
    rep.close()


if __name__ == "__main__":
    main()
