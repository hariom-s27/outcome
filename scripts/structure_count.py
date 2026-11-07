"""Free structure count (P5-14, DR21 spike 22): counts of amendment / rider / exhibit /
memorandum / signature-block headings in a DEV document. Prints COUNTS ONLY, never text.

    uv run python scripts/structure_count.py lease_002 lease_001

A block counts as a heading when it is short (<= 120 chars) and starts with the pattern.
Signature blocks are counted from generic execution phrases anywhere in a block.
Image-only documents (no text layer) are reported as "not countable".
The held-out documents are refused.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.readers import read_document  # noqa: E402

DOCS = ROOT / "sample" / "sample-data-documents"
MANIFEST = ROOT / "sample" / "manifest.csv"
SEALED = {"lease_" + "003", "budget_" + "001"}  # held-out seal (P5-23)
HEADING_MAX = 120

HEADINGS = {
    "amendment": re.compile(
        r"^\s*(?:(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)?)\s+)?amendment\b", re.I
    ),
    "rider": re.compile(r"^\s*rider\b", re.I),
    "exhibit": re.compile(r"^\s*(?:exhibit|schedule|addendum)\s+[\w-]{1,4}\b", re.I),
    "memorandum": re.compile(r"^\s*(?:\w+\s+){0,2}memorandum\b", re.I),
}
SIGNATURE = re.compile(r"\bin witness whereof\b|\bexecuted (?:this|as of)\b", re.I)


def count(doc_id: str) -> dict[str, int | str]:
    if doc_id in SEALED:
        raise SystemExit(f"{doc_id}: held-out document, refused")
    with MANIFEST.open(encoding="utf-8") as fh:
        row = next((r for r in csv.DictReader(fh) if r["document_id"] == doc_id), None)
    if row is None:
        raise SystemExit(f"{doc_id}: not in the manifest")
    docmap = read_document(row["kind"], (DOCS / row["file"]).read_bytes())
    text_blocks = [b for b in docmap.blocks if b.kind != "image" and b.text.strip()]
    if not text_blocks:
        return {"status": "not countable (no text layer)", "blocks": len(docmap.blocks)}
    out: dict[str, int | str] = {"status": "counted", "blocks": len(docmap.blocks)}
    for name, rx in HEADINGS.items():
        out[name] = sum(
            1 for b in text_blocks if len(b.text.strip()) <= HEADING_MAX and rx.search(b.text)
        )
    out["signature_block"] = sum(1 for b in text_blocks if SIGNATURE.search(b.text))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("doc_ids", nargs="+")
    for doc_id in p.parse_args().doc_ids:
        counts = count(doc_id)
        print(doc_id, " ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
