"""PDF -> one text block per page (pypdfium2); a page with (almost) no text layer becomes a
grayscale JPEG (long side ~1600 px) for a vision model (R13). One page at a time.

Rough (P2-15): runs in the worker process; P3 moves rendering into killable child processes
with timeouts and memory caps (R20).
"""

from __future__ import annotations

import io

from app.readers.base import Block, ReaderError

MIN_TEXT_CHARS = 25  # fewer non-space characters than this = treat the page as a scan
IMAGE_LONG_SIDE = 1600
JPEG_QUALITY = 80


def _render_jpeg(page) -> tuple[bytes, int, int]:
    w_pt, h_pt = page.get_size()
    scale = IMAGE_LONG_SIDE / max(w_pt, h_pt, 1.0)
    bitmap = page.render(scale=scale, grayscale=True)
    try:
        img = bitmap.to_pil()
        if img.mode not in ("L", "RGB"):
            img = img.convert("L")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue(), img.width, img.height
    finally:
        bitmap.close()


def read_pdf(content: bytes) -> list[Block]:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as exc:
        raise ReaderError(f"pdf reader: {type(exc).__name__}") from exc
    blocks: list[Block] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded() or ""
                finally:
                    textpage.close()
                n = i + 1
                if len("".join(text.split())) >= MIN_TEXT_CHARS:
                    clean = "\n".join(" ".join(line.split()) for line in text.splitlines())
                    clean = "\n".join(line for line in clean.splitlines() if line)
                    blocks.append(Block("text", f"Page {n}", clean, page=n, unit="page"))
                else:
                    jpeg, w, h = _render_jpeg(page)
                    blocks.append(
                        Block(
                            "image", f"Page {n}", page=n, jpeg=jpeg, width=w, height=h, unit="page"
                        )
                    )
            finally:
                page.close()
    finally:
        pdf.close()
    return blocks
