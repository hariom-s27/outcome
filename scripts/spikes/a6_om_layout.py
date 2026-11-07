"""A6 (spike 24): om_001 layout per page and whether answer values sit in the text layer.

Per page: text chars, image area % (sum of image boxes, capped at 100), rectangle-like paths
(lines only, <= 5 segments), curved paths, curve-heavy (chart) yes/no.
Inside the script only: for each non-null answer field, is the value findable in the text of
its cited page(s)? Printed: counts and field names only.
"""

from __future__ import annotations

import re
from collections import Counter

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from _common import Report, doc_path, truth, truth_entries

DOC = "om_001"
CURVE_HEAVY_SEGMENTS = 60


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w.%]", " ", s.lower())).strip()


def variants(v: object) -> list[str]:
    if isinstance(v, bool):
        return []
    if isinstance(v, int | float):
        x = float(v)
        out = {f"{x:,.0f}", f"{x:.0f}", f"{x:,.2f}", f"{x:.2f}", f"{x:,.1f}", f"{x:g}"}
        if abs(x) >= 1e6:
            out |= {f"{x / 1e6:.1f}", f"{x / 1e6:.2f}", f"{x / 1e6:g}"}
        if abs(x) < 1:
            out |= {f"{x * 100:.1f}", f"{x * 100:.2f}", f"{x * 100:g}"}
        return [norm(o) for o in out]
    return [norm(str(v))]


def findable(value: object, text: str) -> bool | None:
    vals = value if isinstance(value, list) else [value]
    checks = []
    for v in vals:
        vs = [x for x in variants(v) if x]
        if not vs:
            continue
        checks.append(any(x in text for x in vs))
    return all(checks) if checks else None


def page_shapes(page) -> tuple[float, int, int, int]:
    w, h = page.get_size()
    img_area = 0.0
    rects = curved = bez = 0
    for o in page.get_objects(max_depth=4):
        if o.type == raw.FPDF_PAGEOBJ_IMAGE:
            b = o.get_bounds() if hasattr(o, "get_bounds") else o.get_pos()
            img_area += max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        elif o.type == raw.FPDF_PAGEOBJ_PATH:
            n = raw.FPDFPath_CountSegments(o.raw)
            nb = sum(
                raw.FPDFPathSegment_GetType(raw.FPDFPath_GetPathSegment(o.raw, k))
                == raw.FPDF_SEGMENT_BEZIERTO
                for k in range(max(n, 0))
            )
            bez += nb
            if nb:
                curved += 1
            elif 0 < n <= 5:
                rects += 1
    return min(1.0, img_area / (w * h)), rects, curved, bez


def main() -> None:
    rep = Report("a6_om_layout")
    pdf = pdfium.PdfDocument(doc_path(DOC))
    texts: dict[int, str] = {}
    kinds: Counter = Counter()
    stats: Counter = Counter()
    for i in range(len(pdf)):
        page = pdf[i]
        tp = page.get_textpage()
        text = tp.get_text_bounded() or ""
        tp.close()
        chars = len("".join(text.split()))
        texts[i + 1] = norm(text)
        img, rects, curved, bez = page_shapes(page)
        chart = bez >= CURVE_HEAVY_SEGMENTS
        kind = ("scan_like" if chars < 50 and img > 0.5 else "mixed" if img > 0.3 else "text") + (
            "+chart" if chart else ""
        )
        kinds[kind] += 1
        stats["rects"] += rects
        stats["curved_paths"] += curved
        stats["max_bezier_on_a_page"] = max(stats["max_bezier_on_a_page"], bez)
        stats["pages_with_rects"] += rects > 0
        rep.line(
            f"p{i + 1} text_chars={chars} image_area={img:.0%} rects={rects} "
            f"curved_paths={curved} bezier_segments={bez} curve_heavy={'yes' if chart else 'no'}"
        )
        page.close()
    pdf.close()
    rep.sum(f"{DOC}: pages={len(texts)} page kinds={dict(kinds)}")
    rep.sum(f"{DOC}: shapes {dict(stats)}")
    low_text = [p for p, t in texts.items() if len(t.replace(" ", "")) < 50]
    rep.sum(f"{DOC}: pages with < 50 text chars: {low_text or '-'}")

    entry = truth_entries(truth(DOC))[0]
    yes = no = na = 0
    missing: list[str] = []
    for field, rec in entry.items():
        if not isinstance(rec, dict) or rec.get("value") in (None, []):
            continue
        pages = [int(p) for p in rec.get("page_numbers") or [] if isinstance(p, int | float)]
        text = " ".join(texts.get(p, "") for p in pages) if pages else " ".join(texts.values())
        r = findable(rec["value"], text)
        if r is None:
            na += 1
        elif r:
            yes += 1
        else:
            no += 1
            missing.append(field)
        rep.line(f"field={field} pages={len(pages)} findable={r}")
    rep.sum(f"non-null fields: findable in text={yes} not findable={no} n/a (bool)={na}")
    rep.sum(f"not findable: {', '.join(missing) or '-'}")
    rep.close()


if __name__ == "__main__":
    main()
