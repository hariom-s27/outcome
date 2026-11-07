"""A2 (spike 14): embedded images vs a 1600 px render, per page.

For each page: embedded image count, largest image native pixels, its effective DPI on the
page, its page-area coverage, and the DPI of a 1600 px long-side render. Verdict at an equal
1600 px budget:
  full-page image (coverage >= 90%): same information; embedded avoids one resample when its
    native long side <= 1600, otherwise both are a downscale -> "same"
  partial image with effective DPI > render DPI: a crop of the embedded image shows that
    region sharper -> "embedded"
  else -> "render"
"""

from __future__ import annotations

from collections import Counter

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from _common import Report, doc_path

DOCS = ("lease_001", "om_001")
LONG = 1600


def main() -> None:
    rep = Report("a2_images")
    for d in DOCS:
        pdf = pdfium.PdfDocument(doc_path(d))
        verdicts: Counter = Counter()
        kinds: Counter = Counter()
        longs: list[int] = []
        dpis: list[float] = []
        for i in range(len(pdf)):
            page = pdf[i]
            w_pt, h_pt = page.get_size()
            render_dpi = LONG / (max(w_pt, h_pt) / 72)
            imgs = [o for o in page.get_objects(max_depth=3) if o.type == raw.FPDF_PAGEOBJ_IMAGE]
            best = None
            for o in imgs:
                px_w, px_h = o.get_px_size()
                bounds = o.get_bounds() if hasattr(o, "get_bounds") else o.get_pos()
                left, bottom, right, top = bounds
                bw, bh = max(right - left, 1e-6), max(top - bottom, 1e-6)
                cover = min(1.0, (bw * bh) / (w_pt * h_pt))
                dpi = min(px_w / (bw / 72), px_h / (bh / 72))
                if best is None or px_w * px_h > best[0] * best[1]:
                    best = (px_w, px_h, dpi, cover)
            if best is None:
                verdict, kind = "render", "no_image"
            elif best[3] >= 0.9:
                verdict, kind = "same", "full_page_image"
            elif best[2] > render_dpi:
                verdict, kind = "embedded", "partial_image"
            else:
                verdict, kind = "render", "partial_image"
            verdicts[verdict] += 1
            kinds[kind] += 1
            if best:
                longs.append(max(best[0], best[1]))
                dpis.append(best[2])
            desc = (
                f"largest={best[0]}x{best[1]} eff_dpi={best[2]:.0f} cover={best[3]:.0%}"
                if best
                else "largest=-"
            )
            rep.line(
                f"{d} p{i + 1} images={len(imgs)} {desc} render_dpi={render_dpi:.0f} "
                f"kind={kind} sharper={verdict}"
            )
            page.close()
        rep.sum(f"{d}: pages={len(pdf)} kinds={dict(kinds)} sharper={dict(verdicts)}")
        if longs:
            rep.sum(
                f"{d}: largest-image native long side min/max={min(longs)}/{max(longs)} px, "
                f"eff DPI min/max={min(dpis):.0f}/{max(dpis):.0f}, render DPI={render_dpi:.0f}"
            )
        pdf.close()
    rep.close()


if __name__ == "__main__":
    main()
