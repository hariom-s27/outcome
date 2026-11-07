"""A3 (spike 19, C16): DOCX page markers on lease_002 and how well they place cited text.

Counts w:lastRenderedPageBreak, explicit page breaks, section breaks and the Pages value in
docProps/app.xml. Two page rules over the accepted-changes text:
  A  "rendered": new page at each w:lastRenderedPageBreak
  B  "markers":  A plus explicit page breaks and next/odd/even-page section breaks (an explicit
                 break followed by a rendered break before any text counts once)
Then, inside the script only: for each non-null answer field with page_numbers, find its
citation text in the DOCX and compute the page; agreement = page in page_numbers.
Printed: counts and field names only.
"""

from __future__ import annotations

import io
import re
import zipfile
from bisect import bisect_right
from collections import Counter
from xml.etree import ElementTree as ET

from _common import Report, doc_path, truth, truth_entries

DOC = "lease_002"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PAGE_SECTIONS = {"nextPage", "oddPage", "evenPage"}


def walk(xml: bytes) -> dict:
    text: list[str] = []
    n_chars = 0
    starts_a: list[int] = []
    starts_b: list[int] = []
    pending_b = False
    counts = {"rendered": 0, "explicit": 0, "sections": 0, "ins": 0, "del": 0}
    in_del = 0
    for ev, el in ET.iterparse(io.BytesIO(xml), events=("start", "end")):
        tag = el.tag
        if ev == "start":
            if tag == W + "del":
                counts["del"] += 1
                in_del += 1
            elif tag == W + "ins":
                counts["ins"] += 1
            elif tag == W + "lastRenderedPageBreak":
                counts["rendered"] += 1
                starts_a.append(n_chars)
                if pending_b:
                    pending_b = False
                else:
                    starts_b.append(n_chars)
            elif tag == W + "br" and el.get(W + "type") == "page":
                counts["explicit"] += 1
                starts_b.append(n_chars)
                pending_b = True
            continue
        # end events
        if tag == W + "del":
            in_del -= 1
        elif tag == W + "t" and not in_del and el.text:
            text.append(el.text)
            n_chars += len(el.text)
            if el.text.strip():
                pending_b = False
        elif tag == W + "tab":
            text.append(" ")
            n_chars += 1
        elif tag == W + "p":
            text.append("\n")
            n_chars += 1
        elif tag == W + "pPr":
            sect = el.find(W + "sectPr")
            if sect is not None:
                counts["sections"] += 1
                typ = sect.find(W + "type")
                val = typ.get(W + "val") if typ is not None else "nextPage"
                if val in PAGE_SECTIONS:
                    starts_b.append(n_chars + 1)  # after this paragraph
                    pending_b = True
    return {"text": "".join(text), "starts_a": starts_a, "starts_b": starts_b, **counts}


def normalise(raw: str) -> tuple[str, list[int]]:
    out, idx = [], []
    for i, c in enumerate(raw):
        if c.isalnum():
            out.append(c.lower())
            idx.append(i)
        elif out and out[-1] != " ":
            out.append(" ")
            idx.append(i)
    return "".join(out), idx


def find(norm_doc: str, cite: str) -> int:
    n, _ = normalise(cite)
    n = n.strip()
    if not n:
        return -1
    for cand in (n, n[:60], n[-60:], n[:30]):
        cand = cand.strip()
        if len(cand) >= 12 and (pos := norm_doc.find(cand)) >= 0:
            return pos
    return -1


def main() -> None:
    rep = Report("a3_docx_pages")
    with zipfile.ZipFile(doc_path(DOC)) as z:
        info = walk(z.read("word/document.xml"))
        app = (
            z.read("docProps/app.xml").decode("utf-8") if "docProps/app.xml" in z.namelist() else ""
        )
    m = re.search(r"<Pages>(\d+)</Pages>", app)
    pages_app = int(m.group(1)) if m else None
    implied_a = len(info["starts_a"]) + 1
    implied_b = len(info["starts_b"]) + 1
    rep.sum(
        f"{DOC}: lastRenderedPageBreak={info['rendered']} explicit_page_breaks={info['explicit']} "
        f"section_breaks={info['sections']} app.xml Pages={pages_app}"
    )
    rep.sum(f"{DOC}: implied pages rule A (rendered)={implied_a}, rule B (markers)={implied_b}")

    norm_doc, idx = normalise(info["text"])
    entry = truth_entries(truth(DOC))[0]
    total = found = match_a = match_b = 0
    miss_a: list[str] = []
    not_found: list[str] = []
    off_b: Counter = Counter()
    truth_pages: set[int] = set()
    for field, rec in entry.items():
        if not isinstance(rec, dict) or rec.get("value") is None or not rec.get("page_numbers"):
            continue
        total += 1
        cite = rec.get("citation") or str(rec.get("value"))
        pos = find(norm_doc, str(cite))
        if pos < 0:
            not_found.append(field)
            rep.line(f"field={field} cited_text_found=no")
            continue
        found += 1
        raw_pos = idx[pos]
        pa = 1 + bisect_right(info["starts_a"], raw_pos)
        pb = 1 + bisect_right(info["starts_b"], raw_pos)
        pages = {int(p) for p in rec["page_numbers"] if isinstance(p, int | float)}
        ok_a, ok_b = pa in pages, pb in pages
        match_a += ok_a
        match_b += ok_b
        if not ok_a:
            miss_a.append(field)
        off_b[pb - min(pages)] += 1
        truth_pages.update(pages)
        rep.line(
            f"field={field} found=yes ruleA_ok={ok_a} ruleB_ok={ok_b} off_by={pa - min(pages)}"
        )
    if total:
        rep.sum(f"fields with pages={total} cited text found={found} not found={len(not_found)}")
        rep.sum(
            f"agreement rule A={match_a}/{total}={match_a / total:.0%} "
            f"(of found {match_a}/{max(found, 1)}); rule B={match_b}/{total}={match_b / total:.0%}"
        )
        rep.sum(
            "rule A wrong page (found): "
            + (", ".join(f for f in miss_a if f not in not_found) or "-")
        )
        rep.sum(f"cited text not found: {', '.join(not_found) or '-'}")
        rep.sum(
            f"rule B (computed - truth) offsets: {dict(sorted(off_b.items()))}; "
            f"max truth page={max(truth_pages, default=0)}"
        )
    rep.close()


if __name__ == "__main__":
    main()
