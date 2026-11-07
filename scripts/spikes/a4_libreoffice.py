"""A4 (spike 20, P3-08): cost of LibreOffice, run because A3 agreement < 90%.

1. Cold build (--no-cache) of the current Dockerfile and of a temporary copy with
   libreoffice-writer-nogui added (written to cache/spikes/lo/, never committed): build time
   and image size for both.
2. Free extra for P3-13: convert lease_002 to PDF in the +LO image (only that one file is
   mounted, read-only), then repeat A3's check with the PDF's real page breaks:
   agreement = cited text found on an answer page / fields with pages. Counts and names only.
"""

from __future__ import annotations

import subprocess
import time
from bisect import bisect_right

import pypdfium2 as pdfium
from _common import OUT_DIR, ROOT, Report, doc_path, truth, truth_entries
from a3_docx_pages import find, normalise

DOC = "lease_002"
BASE_TAG, LO_TAG = "docextract-spike:base", "docextract-spike:lo"
LO_STEP = (
    "RUN apt-get update && apt-get install -y --no-install-recommends "
    "libreoffice-writer-nogui fonts-liberation fonts-dejavu-core "
    "&& rm -rf /var/lib/apt/lists/*\n"
)


def build(dockerfile: str, tag: str) -> tuple[float, int]:
    t0 = time.monotonic()
    subprocess.run(
        ["docker", "build", "--no-cache", "-q", "-f", dockerfile, "-t", tag, "."],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )  # fmt: skip
    secs = time.monotonic() - t0
    size = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Size}}", tag],
        check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    return secs, int(size)


def main() -> None:
    rep = Report("a4_libreoffice")
    lo_dir = OUT_DIR / "lo"
    (lo_dir / "out").mkdir(parents=True, exist_ok=True)
    src = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    marker = "RUN useradd"
    if marker not in src:
        raise SystemExit("Dockerfile layout changed: no useradd step to insert before")
    lo_file = lo_dir / "Dockerfile"
    lo_file.write_text(src.replace(marker, LO_STEP + marker, 1), encoding="utf-8", newline="\n")

    t_base, s_base = build("Dockerfile", BASE_TAG)
    t_lo, s_lo = build(str(lo_file.relative_to(ROOT)), LO_TAG)
    mb = 1024 * 1024
    rep.sum(f"cold build: base {t_base:.0f} s, {s_base / mb:.0f} MB")
    rep.sum(
        f"cold build: +LibreOffice {t_lo:.0f} s, {s_lo / mb:.0f} MB "
        f"(+{(s_lo - s_base) / mb:.0f} MB, +{t_lo - t_base:.0f} s)"
    )

    pdf_out = lo_dir / "out" / "lease.pdf"
    pdf_out.unlink(missing_ok=True)
    t0 = time.monotonic()
    r = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-e", "HOME=/tmp", "--user", "0",
         "-v", f"{doc_path(DOC)}:/in/lease.docx:ro", "-v", f"{lo_dir / 'out'}:/out",
         LO_TAG, "soffice", "--headless", "--convert-to", "pdf", "--outdir", "/out",
         "/in/lease.docx"],
        capture_output=True, text=True,
    )  # fmt: skip
    conv = time.monotonic() - t0
    if r.returncode != 0 or not pdf_out.exists():
        rep.sum(f"conversion failed (exit {r.returncode}) after {conv:.0f} s")
        rep.close()
        return
    pdf = pdfium.PdfDocument(pdf_out)
    raw_parts, starts, n = [], [], 0
    for i in range(len(pdf)):
        tp = pdf[i].get_textpage()
        t = (tp.get_text_bounded() or "") + "\n"
        tp.close()
        if i:
            starts.append(n)
        raw_parts.append(t)
        n += len(t)
    pages = len(pdf)
    pdf.close()
    norm_doc, idx = normalise("".join(raw_parts))
    entry = truth_entries(truth(DOC))[0]
    total = found = match = 0
    wrong: list[str] = []
    offs: dict[int, int] = {}
    for field, rec in entry.items():
        if not isinstance(rec, dict) or rec.get("value") is None or not rec.get("page_numbers"):
            continue
        total += 1
        pos = find(norm_doc, str(rec.get("citation") or rec.get("value")))
        if pos < 0:
            continue
        found += 1
        page = 1 + bisect_right(starts, idx[pos])
        want = {int(p) for p in rec["page_numbers"] if isinstance(p, int | float)}
        if page in want:
            match += 1
        else:
            wrong.append(field)
            d = page - min(want)
            offs[d] = offs.get(d, 0) + 1
        rep.line(f"field={field} lo_page_ok={page in want}")
    rep.sum(
        f"{DOC} via LibreOffice: {pages} pages, conversion {conv:.0f} s (incl. container start)"
    )
    rep.sum(
        f"agreement={match}/{total}={match / max(total, 1):.0%} "
        f"(of found {match}/{max(found, 1)}); "
        f"wrong page: {', '.join(wrong) or '-'}; offsets {dict(sorted(offs.items()))}"
    )
    rep.close()


if __name__ == "__main__":
    main()
