"""XLSX -> every sheet, one row block per non-empty row, refs Sheet!A1 (P3-10).

openpyxl loads the workbook twice: cached values (data_only) and formulas. A formula with no
cached value stays null and is flagged formula_no_cache=<ref> (no recalculation, A1). Hidden
sheets/rows/columns are kept and flagged; merged ranges keep the value at the top-left cell
and record the range as a flag on that row. Number formats render keys and dates as Excel
displays them (leading zeros kept); everything else is the plain value.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile

from app.readers.base import Block, DocMap, ReaderError, cell_text, number_blocks, row_block

ZERO_PAD = re.compile(r"^0+$")
_DATE_TOKEN = re.compile(
    r"yyyy|yy|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|am/pm|a/p|\.0+|[^a-z]|[a-z]", re.IGNORECASE
)
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _strip_format(fmt: str) -> str:
    fmt = fmt.split(";")[0]
    fmt = re.sub(r"\[[^\]]*\]", "", fmt)  # [$-409], [Red], [h]
    fmt = re.sub(r'"[^"]*"', lambda m: m.group(0)[1:-1], fmt)  # quoted literals
    fmt = re.sub(r"\\(.)", r"\1", fmt)  # escaped characters
    return fmt.replace("_)", "").replace("*", "")


def format_date(value: dt.date | dt.datetime, fmt: str) -> str | None:
    """A date as its Excel number format shows it; None when the format is not understood."""
    tokens = _DATE_TOKEN.findall(_strip_format(fmt))
    if not tokens or not any(t.lower().startswith(("y", "d")) for t in tokens):
        return None
    has_time = isinstance(value, dt.datetime)
    out: list[str] = []
    for i, tok in enumerate(tokens):
        low = tok.lower()
        prev = next((t.lower() for t in reversed(tokens[:i]) if t.strip(" /-:,.")), "")
        nxt = next((t.lower() for t in tokens[i + 1 :] if t.strip(" /-:,.")), "")
        minute = low in ("m", "mm") and (prev.startswith("h") or nxt.startswith("s"))
        if low == "yyyy":
            out.append(f"{value.year:04d}")
        elif low == "yy":
            out.append(f"{value.year % 100:02d}")
        elif low == "mmmm":
            out.append(_MONTHS[value.month - 1])
        elif low == "mmm":
            out.append(_MONTHS[value.month - 1][:3])
        elif low in ("mm", "m") and not minute:
            out.append(f"{value.month:02d}" if low == "mm" else str(value.month))
        elif low == "dddd":
            out.append(_DAYS[value.weekday()])
        elif low == "ddd":
            out.append(_DAYS[value.weekday()][:3])
        elif low == "dd":
            out.append(f"{value.day:02d}")
        elif low == "d":
            out.append(str(value.day))
        elif low in ("hh", "h", "ss", "s", "m", "mm", "am/pm", "a/p") or low.startswith(".0"):
            if not has_time:
                return None
            v: dt.datetime = value  # type: ignore[assignment]
            if low in ("hh", "h"):
                ampm = any(t.lower() in ("am/pm", "a/p") for t in tokens)
                hour = (v.hour % 12 or 12) if ampm else v.hour
                out.append(f"{hour:02d}" if low == "hh" else str(hour))
            elif low in ("m", "mm"):
                out.append(f"{v.minute:02d}" if low == "mm" else str(v.minute))
            elif low in ("ss", "s"):
                out.append(f"{v.second:02d}" if low == "ss" else str(v.second))
            elif low in ("am/pm", "a/p"):
                out.append("AM" if v.hour < 12 else "PM")
            else:
                return None
        elif low.isalpha():
            return None  # a letter code we do not know: let the caller use ISO
        else:
            out.append(tok)
    return "".join(out).strip()


def display_text(value: object, fmt: str | None) -> str:
    """Keys and dates as displayed; every other value as plain text."""
    fmt = fmt or "General"
    if isinstance(value, dt.datetime | dt.date) and fmt != "General":
        shown = format_date(value, fmt)
        if shown:
            return shown
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and float(value).is_integer()
        and value >= 0
    ):
        core = _strip_format(fmt).strip()
        if ZERO_PAD.match(core):
            return str(int(value)).zfill(len(core))
    return cell_text(value)


def _hidden_columns(ws) -> set[int]:
    hidden: set[int] = set()
    for dim in ws.column_dimensions.values():
        if dim.hidden and dim.min and dim.max:
            hidden.update(range(dim.min - 1, dim.max))
    return hidden


def _is_formula(cell) -> bool:
    return cell.data_type == "f" or type(cell.value).__name__ in (
        "ArrayFormula",
        "DataTableFormula",
    )


def read_xlsx(content: bytes) -> DocMap:
    import openpyxl  # heavy import, only in the worker path

    try:
        wb_v = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        wb_f = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, TypeError) as exc:
        raise ReaderError(f"xlsx reader: {type(exc).__name__}") from exc
    blocks: list[Block] = []
    counts = {"sheets": 0, "hidden_sheets": 0, "merged_ranges": 0, "formula_no_cache": 0}
    try:
        for ws_v, ws_f in zip(wb_v.worksheets, wb_f.worksheets, strict=True):
            counts["sheets"] += 1
            sheet_flags: list[str] = []
            if ws_f.sheet_state != "visible":
                sheet_flags.append("hidden_sheet")
                counts["hidden_sheets"] += 1
            merged_at: dict[int, list[str]] = {}
            for rng in ws_f.merged_cells.ranges:
                merged_at.setdefault(rng.min_row, []).append(f"merged={rng.coord}")
                counts["merged_ranges"] += 1
            hidden_cols = _hidden_columns(ws_f)
            max_row = max(ws_v.max_row, ws_f.max_row)
            max_col = max(ws_v.max_column, ws_f.max_column)
            rows_v = ws_v.iter_rows(min_row=1, max_row=max_row, max_col=max_col)
            rows_f = ws_f.iter_rows(min_row=1, max_row=max_row, max_col=max_col)
            for n, (row_v, row_f) in enumerate(zip(rows_v, rows_f, strict=True), start=1):
                flags = list(sheet_flags)
                cells: list[tuple[int, str]] = []
                for i, (cv, cf) in enumerate(zip(row_v, row_f, strict=True)):
                    if _is_formula(cf) and cv.value is None:
                        flags.append(f"formula_no_cache={cf.coordinate}")
                        counts["formula_no_cache"] += 1
                        cells.append((i, ""))
                        continue
                    text = display_text(cv.value, cv.number_format)
                    if text and i in hidden_cols and "hidden_column" not in flags:
                        flags.append("hidden_column")
                    cells.append((i, text))
                if ws_f.row_dimensions[n].hidden if n in ws_f.row_dimensions else False:
                    flags.append("hidden_row")
                flags.extend(merged_at.get(n, []))
                b = row_block(ws_v.title, n, cells, tuple(flags))
                if b is not None:
                    blocks.append(b)
    finally:
        wb_v.close()
        wb_f.close()
    return DocMap("xlsx", number_blocks("X", blocks), counts)
