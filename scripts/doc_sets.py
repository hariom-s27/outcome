"""P9a D48: which documents a run uses. `dev` = sample/manifest.csv (unchanged); `syn` = the
invented SYN set in tests/fixtures/syn/ (scripts/make_syn.py); `all` = both.

DEV rows are exactly make_outputs.manifest() rows: no extra keys, so every DEV code path
(DOCS / row["file"], SCHEMAS / <schema>.json, the answer folder) is the one v1.0 used.
SYN rows carry their own paths under private keys (doc_path, schema_path, truth_path).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_outputs import DOCS, ROOT, SCHEMAS, manifest

SYN = ROOT / "tests" / "fixtures" / "syn"
SYN_DOCS = SYN / "documents"
SYN_ANSWERS = SYN / "answers"
SYN_SCHEMAS = SYN / "schemas"
TRUTH = ROOT / "sample" / "sample-data-output-validated"
SETS = ("dev", "syn", "all")


def syn_rows() -> dict[str, dict[str, str]]:
    with (SYN / "manifest.csv").open(newline="", encoding="utf-8") as f:
        rows = {r["document_id"]: dict(r) for r in csv.DictReader(f)}
    for doc_id, r in rows.items():
        own = SYN_SCHEMAS / f"{r['schema_name']}.json"
        r.update(
            set="syn",
            doc_path=str(SYN_DOCS / r["file"]),
            schema_path=str(own if own.exists() else SCHEMAS / f"{r['schema_name']}.json"),
            truth_path=str(SYN_ANSWERS / f"{doc_id}.json"),
        )
    return rows


def rows_for(set_name: str = "dev") -> dict[str, dict[str, str]]:
    if set_name not in SETS:
        raise ValueError(f"unknown set {set_name!r}; one of {', '.join(SETS)}")
    if set_name == "dev":
        return manifest()
    if set_name == "syn":
        return syn_rows()
    return {**manifest(), **syn_rows()}


def doc_path(row: dict[str, str]) -> Path:
    return Path(row["doc_path"]) if "doc_path" in row else DOCS / row["file"]


def schema_path(row: dict[str, str]) -> Path:
    return (
        Path(row["schema_path"])
        if "schema_path" in row
        else SCHEMAS / (f"{row['schema_name']}.json")
    )


def truth_path(doc_id: str, row: dict[str, str] | None = None) -> Path:
    return Path(row["truth_path"]) if row and "truth_path" in row else TRUTH / f"{doc_id}.json"


def set_of(doc_id: str) -> str:
    return "syn" if doc_id.startswith("syn_") else "dev"
