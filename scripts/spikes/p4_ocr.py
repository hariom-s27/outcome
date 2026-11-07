"""B2(c) local OCR (P4-09, D22): RapidOCR over the page images the reader renders, on the host,
in a TEMPORARY uv environment (never added to pyproject.toml, uv.lock or the Docker image):

    uv run --with rapidocr-onnxruntime python scripts/spikes/p4_ocr.py --run-id <id>

Writes cache/spikes/<run_id>/ocr/<doc>.json (page lines; git-ignored) for p4_b2.py method c.
Prints page / line / character counts and CPU seconds only (no text, R23).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p4_common as pc  # noqa: E402


def page_lines(engine, jpeg: bytes) -> list[str]:
    result, _ = engine(jpeg)
    boxes = result or []  # [[box (4 points), text, score], ...]; None when nothing found
    boxes.sort(key=lambda r: (round(min(p[1] for p in r[0]) / 12), min(p[0] for p in r[0])))
    return [str(r[1]) for r in boxes if str(r[1]).strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doc", default="lease_001")
    ap.add_argument("--run-id", help="default: ocr-<utc>")
    args = ap.parse_args()
    from rapidocr_onnxruntime import RapidOCR  # temporary env only (uv run --with)

    paths = pc.Paths.detect()
    doc = pc.load_doc(args.doc, paths)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"ocr-{stamp}"
    engine = RapidOCR()
    cpu0, wall0 = time.process_time(), time.monotonic()
    pages = [
        {"page": b.page, "lines": page_lines(engine, b.jpeg or b"")}
        for b in doc.blocks
        if b.kind == "image"
    ]
    cpu, wall = time.process_time() - cpu0, time.monotonic() - wall0
    out = paths.spikes / run_id / "ocr" / f"{doc.doc_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {"doc": doc.doc_id, "pages": pages, "cpu_seconds": round(cpu, 1),
            "wall_seconds": round(wall, 1)}  # fmt: skip
    out.write_text(json.dumps(data), encoding="utf-8")
    n_lines = sum(len(p["lines"]) for p in pages)
    n_chars = sum(len(x) for p in pages for x in p["lines"])
    print(
        f"ocr run={run_id} doc={doc.doc_id} pages={len(pages)} lines={n_lines} "
        f"chars={n_chars} cpu_s={cpu:.1f} wall_s={wall:.1f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
