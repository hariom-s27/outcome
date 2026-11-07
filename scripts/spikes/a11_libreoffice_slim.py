"""A11 (P3-27, for P8): a slim LibreOffice layer, measured on a temporary image only.

Same method as A4 (build() reused): cold builds (--no-cache) of the current Dockerfile and of a
temporary copy (cache/spikes/lo_slim/, never committed) that adds
libreoffice-writer-nogui + fonts-liberation2 + fonts-crosextra-carlito + fonts-crosextra-caladea
with --no-install-recommends. Then lease_002 -> PDF inside that image (--network none, only
that file mounted read-only) and A3's page check. Prints counts only and the image rm line.
"""

from __future__ import annotations

import subprocess
import time
from bisect import bisect_right

import pypdfium2 as pdfium
from _common import OUT_DIR, ROOT, Report, doc_path, truth, truth_entries
from a3_docx_pages import find, normalise
from a4_libreoffice import BASE_TAG, build

DOC = "lease_002"
SLIM_TAG = "docextract-spike:lo-slim"
SLIM_STEP = (
    "RUN apt-get update && apt-get install -y --no-install-recommends "
    "libreoffice-writer-nogui fonts-liberation2 fonts-crosextra-carlito "
    "fonts-crosextra-caladea && rm -rf /var/lib/apt/lists/*\n"
)


def page_agreement(pdf_path) -> tuple[int, int, int, int, dict[int, int]]:
    pdf = pdfium.PdfDocument(pdf_path)
    parts, starts, n = [], [], 0
    for i in range(len(pdf)):
        page = pdf[i]
        tp = page.get_textpage()
        t = (tp.get_text_bounded() or "") + "\n"
        tp.close()
        page.close()
        if i:
            starts.append(n)
        parts.append(t)
        n += len(t)
    pages = len(pdf)
    pdf.close()
    norm_doc, idx = normalise("".join(parts))
    total = found = match = 0
    offs: dict[int, int] = {}
    for _field, rec in truth_entries(truth(DOC))[0].items():
        if not isinstance(rec, dict) or rec.get("value") is None or not rec.get("page_numbers"):
            continue
        total += 1
        pos = find(norm_doc, str(rec.get("citation") or rec.get("value")))
        if pos < 0:
            continue
        found += 1
        page_no = 1 + bisect_right(starts, idx[pos])
        want = {int(p) for p in rec["page_numbers"] if isinstance(p, int | float)}
        if page_no in want:
            match += 1
        else:
            d = page_no - min(want)
            offs[d] = offs.get(d, 0) + 1
    return pages, total, found, match, offs


def main() -> None:
    rep = Report("a11_libreoffice_slim")
    lo_dir = OUT_DIR / "lo_slim"
    (lo_dir / "out").mkdir(parents=True, exist_ok=True)
    src = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    marker = "RUN useradd"
    if marker not in src:
        raise SystemExit("Dockerfile layout changed: no useradd step to insert before")
    slim_file = lo_dir / "Dockerfile"
    slim_file.write_text(src.replace(marker, SLIM_STEP + marker, 1), encoding="utf-8", newline="\n")

    t_base, s_base = build("Dockerfile", BASE_TAG)
    t_slim, s_slim = build(str(slim_file.relative_to(ROOT)), SLIM_TAG)
    mb = 1024 * 1024
    rep.sum(f"cold build: base {t_base:.0f} s, {s_base / mb:.0f} MB")
    rep.sum(
        f"cold build: +slim LibreOffice {t_slim:.0f} s, {s_slim / mb:.0f} MB "
        f"(+{(s_slim - s_base) / mb:.0f} MB, +{t_slim - t_base:.0f} s)"
    )
    pdf_out = lo_dir / "out" / "lease.pdf"
    pdf_out.unlink(missing_ok=True)
    t0 = time.monotonic()
    r = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-e", "HOME=/tmp", "--user", "0",
         "-v", f"{doc_path(DOC)}:/in/lease.docx:ro", "-v", f"{lo_dir / 'out'}:/out",
         SLIM_TAG, "soffice", "--headless", "--convert-to", "pdf", "--outdir", "/out",
         "/in/lease.docx"],
        capture_output=True, text=True,
    )  # fmt: skip
    conv = time.monotonic() - t0
    if r.returncode != 0 or not pdf_out.exists():
        rep.sum(f"conversion failed (exit {r.returncode}) after {conv:.0f} s")
    else:
        pages, total, found, match, offs = page_agreement(pdf_out)
        rep.sum(f"{DOC} via slim LibreOffice: {pages} pages, conversion {conv:.0f} s")
        rep.sum(
            f"page agreement exact={match}/{found} of locatable ({match}/{total} of all); "
            f"offsets {dict(sorted(offs.items()))}"
        )
    rep.sum(f"remove after review: docker image rm {SLIM_TAG} {BASE_TAG}")
    rep.close()


if __name__ == "__main__":
    main()
