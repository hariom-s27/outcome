"""A3b (P3-27): how well the DOCX "estimate" page method places cited text on lease_002.

Same matching as A3 (a3_docx_pages.normalise/find) but over the P3 reader's blocks: the cited
text is found in the concatenated body blocks and the block's estimated page is compared with
the answer's page_numbers. Inside the script only; printed: counts, field names, offsets.
Gate (P3-27): exact agreement >= 80% of the locatable citations -> default stays "estimate".
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter

from _common import ROOT, Report, doc_path, truth, truth_entries
from a3_docx_pages import find, normalise

from app.readers.docx_reader import read_docx  # noqa: E402  (path set by _common)

DOC = "lease_002"
GATE = 0.80


def main() -> None:
    assert ROOT.exists()
    rep = Report("a3b_docx_estimate")
    dm = read_docx(doc_path(DOC).read_bytes(), page_method="estimate")
    body = [b for b in dm.blocks if "header" not in b.flags and "footer" not in b.flags]
    starts, parts, pos = [], [], 0
    for b in body:
        starts.append(pos)
        parts.append(b.text + "\n")
        pos += len(b.text) + 1
    norm_doc, idx = normalise("".join(parts))
    rep.sum(
        f"{DOC}: blocks={len(dm.blocks)} body={len(body)} estimated pages={dm.meta['pages']} "
        f"app.xml Pages={dm.meta['app_pages']} hard breaks={dm.meta['page_breaks']}"
    )
    entry = truth_entries(truth(DOC))[0]
    total = found = exact = near = 0
    offsets: Counter = Counter()
    for field, rec in entry.items():
        if not isinstance(rec, dict) or rec.get("value") is None or not rec.get("page_numbers"):
            continue
        total += 1
        p = find(norm_doc, str(rec.get("citation") or rec.get("value")))
        if p < 0:
            rep.line(f"field={field} found=no")
            continue
        found += 1
        block = body[bisect_right(starts, idx[p]) - 1]
        pages = {int(x) for x in rec["page_numbers"] if isinstance(x, int | float)}
        off = min((block.page or 0) - t for t in pages)
        ok = block.page in pages
        exact += ok
        near += any(abs((block.page or 0) - t) <= 1 for t in pages)
        offsets[off if not ok else 0] += 1
        rep.line(f"field={field} found=yes exact={ok} offset={off}")
    share = exact / found if found else 0.0
    rep.sum(f"fields with pages={total} locatable={found}")
    rep.sum(f"exact={exact}/{found}={share:.0%} of locatable ({exact}/{total} of all)")
    rep.sum(f"within +-1 page={near}/{found}={near / max(found, 1):.0%} of locatable")
    rep.sum(f"offsets (estimate - truth): {dict(sorted(offsets.items()))}")
    verdict = "estimate" if share >= GATE else "none"
    rep.sum(f"gate {GATE:.0%} exact -> default DOCX_PAGE_METHOD = {verdict}")
    rep.close()


if __name__ == "__main__":
    main()
