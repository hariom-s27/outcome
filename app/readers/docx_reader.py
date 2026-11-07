"""DOCX -> paragraphs and table rows in body order (P3-12, DR13).

python-docx opens the package (its parser does not resolve entities); an lxml walker reads
the body in order:
  - numbering labels computed from numbering.xml (direct numPr or the paragraph style's)
  - tracked changes in the accepted view: w:ins / w:moveTo kept, w:del / w:moveFrom dropped
  - content controls (w:sdt), hyperlinks, smart tags, custom XML: walked through
  - text boxes (w:txbxContent): their own blocks after the host paragraph, flag text_box
    (mc:AlternateContent: the Choice branch only, so a text box is read once)
  - tables: one table_row block per row, cells " | "; merged cells flagged merged_cell
  - tab-separated pseudo-tables (2+ inner tabs) stay one line, tabs shown as " | "
  - strike-through is formatting: the text is kept and the block flagged strike
  - headers and footers: kept, flagged header / footer (not dropped), page None

Pages (P3-27) come from a pluggable page method, `docx_pages(layout, method)`, chosen by
DOCX_PAGE_METHOD: "estimate" (proportional position x page count, explicit page breaks and
next-page section breaks start new pages; flag page_estimated) or "none" (page None, no
address). A "libreoffice" method can be registered in PAGE_METHODS without touching the
walker.
"""

from __future__ import annotations

import io
import math
import os
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

from app.readers.base import Block, DocMap, ReaderError, number_blocks

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
W = "{" + W_NS + "}"
MC = "{" + MC_NS + "}"

# P3-27 gate: "estimate" placed 0/20 locatable lease_002 citations on the exact page (13/20
# within +-1; gate 80% exact) -> default "none". DOCX_PAGE_METHOD=estimate still selects it.
DEFAULT_PAGE_METHOD = "none"
PAGE_TYPES = {"nextPage", "oddPage", "evenPage"}

SKIP = {W + "del", W + "moveFrom", W + "rPr", W + "pPr", W + "instrText", W + "delText"}
SKIP |= {MC + "Fallback", W + "tblPr", W + "tblGrid", W + "trPr", W + "tcPr", W + "sdtPr"}
SKIP |= {W + "sdtEndPr", W + "commentReference", W + "footnoteReference"}


# --- numbering -----------------------------------------------------------------------------------


def _roman(n: int) -> str:
    vals = [
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _letters(n: int) -> str:
    # Word: a..z, then aa..zz, then aaa..
    n = max(n, 1)
    return chr(97 + (n - 1) % 26) * ((n - 1) // 26 + 1)


def format_number(n: int, fmt: str) -> str:
    if fmt in ("lowerLetter",):
        return _letters(n)
    if fmt == "upperLetter":
        return _letters(n).upper()
    if fmt == "lowerRoman":
        return _roman(n)
    if fmt == "upperRoman":
        return _roman(n).upper()
    if fmt == "decimalZero":
        return f"{n:02d}"
    if fmt == "none":
        return ""
    return str(n)


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = "%1."
    legal: bool = False


class Numbering:
    """Label generator for numbered paragraphs (counters per abstract list)."""

    def __init__(self, numbering_el, styles_el) -> None:
        self.abstract: dict[str, dict[int, _Level]] = {}
        self.nums: dict[str, tuple[str, dict[int, int]]] = {}
        self.counters: dict[str, dict[int, int]] = {}
        self.started: set[str] = set()
        self.style_num: dict[str, tuple[str | None, int | None, str | None]] = {}
        if numbering_el is not None:
            for an in numbering_el.findall(W + "abstractNum"):
                levels = {}
                for lvl in an.findall(W + "lvl"):
                    lv = _Level()
                    if (s := lvl.find(W + "start")) is not None:
                        lv.start = _int(s.get(W + "val"), 1)
                    if (f := lvl.find(W + "numFmt")) is not None:
                        lv.fmt = f.get(W + "val") or "decimal"
                    if (t := lvl.find(W + "lvlText")) is not None:
                        lv.text = t.get(W + "val") or ""
                    lv.legal = lvl.find(W + "isLgl") is not None
                    levels[_int(lvl.get(W + "ilvl"), 0)] = lv
                self.abstract[an.get(W + "abstractNumId") or ""] = levels
            for num in numbering_el.findall(W + "num"):
                ref = num.find(W + "abstractNumId")
                overrides = {}
                for ov in num.findall(W + "lvlOverride"):
                    so = ov.find(W + "startOverride")
                    if so is not None:
                        overrides[_int(ov.get(W + "ilvl"), 0)] = _int(so.get(W + "val"), 1)
                aid = ref.get(W + "val") if ref is not None else ""
                self.nums[num.get(W + "numId") or ""] = (aid or "", overrides)
        if styles_el is not None:
            for st in styles_el.findall(W + "style"):
                sid = st.get(W + "styleId") or ""
                based = st.find(W + "basedOn")
                num_pr = st.find(f"{W}pPr/{W}numPr")
                nid = ilvl = None
                if num_pr is not None:
                    if (e := num_pr.find(W + "numId")) is not None:
                        nid = e.get(W + "val")
                    if (e := num_pr.find(W + "ilvl")) is not None:
                        ilvl = _int(e.get(W + "val"), 0)
                self.style_num[sid] = (
                    nid,
                    ilvl,
                    based.get(W + "val") if based is not None else None,
                )

    def _style_numpr(self, style: str | None) -> tuple[str | None, int]:
        seen = set()
        while style and style not in seen:
            seen.add(style)
            nid, ilvl, based = self.style_num.get(style, (None, None, None))
            if nid is not None:
                return nid, ilvl or 0
            style = based
        return None, 0

    def label(self, ppr) -> str:
        if ppr is None:
            return ""
        num_pr = ppr.find(W + "numPr")
        nid: str | None = None
        ilvl = 0
        if num_pr is not None:
            if (e := num_pr.find(W + "numId")) is not None:
                nid = e.get(W + "val")
            if (e := num_pr.find(W + "ilvl")) is not None:
                ilvl = _int(e.get(W + "val"), 0)
        if nid is None:
            ps = ppr.find(W + "pStyle")
            nid, ilvl = self._style_numpr(ps.get(W + "val") if ps is not None else None)
        if not nid or nid == "0" or nid not in self.nums:
            return ""
        aid, overrides = self.nums[nid]
        levels = self.abstract.get(aid, {})
        lv = levels.get(ilvl)
        if lv is None:
            return ""
        counters = self.counters.setdefault(aid, {})
        if nid not in self.started:
            self.started.add(nid)
            for k, v in overrides.items():
                counters[k] = v - 1
        counters[ilvl] = counters.get(ilvl, levels[ilvl].start - 1) + 1
        for deeper in [k for k in counters if k > ilvl]:
            del counters[deeper]
        if lv.fmt == "bullet":
            return "•"

        def repl(m: re.Match) -> str:
            k = int(m.group(1)) - 1
            lk = levels.get(k, _Level())
            n = counters.get(k, lk.start)
            return format_number(n, "decimal" if lv.legal else lk.fmt)

        return re.sub(r"%([1-9])", repl, lv.text).strip()


def _int(v: str | None, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


# --- walker --------------------------------------------------------------------------------


@dataclass
class RawBlock:
    kind: str  # paragraph | table_row
    text: str
    flags: list[str] = field(default_factory=list)
    body: bool = True  # False for header / footer parts
    break_before: bool = False  # explicit page break or next-page section break before it


@dataclass
class _Para:
    parts: list[str] = field(default_factory=list)
    strike: bool = False
    page_break_at: list[int] = field(default_factory=list)  # char positions of w:br page
    boxes: list = field(default_factory=list)  # w:txbxContent elements, in order


def _on(el) -> bool:
    """A w:strike / w:dstrike style toggle: present and not switched off."""
    return el is not None and (el.get(W + "val") or "true").lower() not in ("0", "false", "off")


class Walker:
    def __init__(self, numbering: Numbering) -> None:
        self.numbering = numbering
        self.out: list[RawBlock] = []
        self.pending_break = False

    def _emit(self, rb: RawBlock) -> None:
        if self.pending_break and rb.body:
            rb.break_before = True
            self.pending_break = False
        self.out.append(rb)

    # body level
    def body(self, el, flags: tuple[str, ...] = (), body: bool = True) -> None:
        for child in el:
            tag = child.tag
            if tag == W + "p":
                self.paragraph(child, flags, body)
            elif tag == W + "tbl":
                self.table(child, flags, body)
            elif tag in (W + "sdt", W + "customXml"):
                content = child.find(W + "sdtContent") if tag == W + "sdt" else child
                if content is not None:
                    self.body(content, flags, body)
            elif tag in (W + "ins", W + "moveTo"):
                self.body(child, flags, body)

    # paragraph text
    def _collect(self, el, para: _Para) -> None:
        for child in el:
            tag = child.tag
            if tag in SKIP:
                continue
            if tag == W + "t":
                para.parts.append(child.text or "")
            elif tag == W + "tab" and el.tag == W + "r":
                para.parts.append("\t")
            elif tag == W + "br":
                if child.get(W + "type") == "page":
                    para.page_break_at.append(sum(len(p) for p in para.parts))
                else:
                    para.parts.append(" ")
            elif tag == W + "cr":
                para.parts.append(" ")
            elif tag == W + "noBreakHyphen":
                para.parts.append("-")
            elif tag == W + "txbxContent":
                para.boxes.append(child)
            elif tag == W + "r":
                rpr = child.find(W + "rPr")
                if rpr is not None and (
                    _on(rpr.find(W + "strike")) or _on(rpr.find(W + "dstrike"))
                ):
                    before = sum(len(p) for p in para.parts)
                    self._collect(child, para)
                    if sum(len(p) for p in para.parts) > before:
                        para.strike = True
                else:
                    self._collect(child, para)
            elif tag == MC + "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    self._collect(choice, para)
            else:  # ins, moveTo, hyperlink, smartTag, sdt/sdtContent, fldSimple, drawing, …
                self._collect(child, para)

    def paragraph(self, p, flags: tuple[str, ...], body: bool) -> None:
        ppr = p.find(W + "pPr")
        para = _Para()
        self._collect(p, para)
        raw = "".join(para.parts)
        label = self.numbering.label(ppr) if raw.strip() else ""
        text, tabbed = _clean_line(raw)
        fl = list(flags)
        if label:
            text = f"{label} {text}"
            fl.append("numbered")
        if tabbed:
            fl.append("tabbed")
        if para.strike:
            fl.append("strike")
        if ppr is not None and _on(ppr.find(W + "pageBreakBefore")) and body:
            self.pending_break = True
        if para.page_break_at and body and min(para.page_break_at) == 0:
            self.pending_break = True
        if text:
            self._emit(RawBlock("paragraph", text, fl, body))
        if para.page_break_at and body and max(para.page_break_at) > 0:
            self.pending_break = True
        for box in para.boxes:
            self.body(box, (*flags, "text_box"), body)
        sect = ppr.find(W + "sectPr") if ppr is not None else None
        if sect is not None and body:
            typ = sect.find(W + "type")
            if (typ.get(W + "val") if typ is not None else "nextPage") in PAGE_TYPES:
                self.pending_break = True

    def _cell_text(self, tc) -> str:
        sub = Walker(self.numbering)
        sub.body(tc)
        return " ".join(b.text for b in sub.out if b.text)

    def table(self, tbl, flags: tuple[str, ...], body: bool) -> None:
        for tr in _rows(tbl):
            cells: list[str] = []
            merged = False
            for tc in _cells(tr):
                tcpr = tc.find(W + "tcPr")
                if tcpr is not None:
                    span = tcpr.find(W + "gridSpan")
                    vm = tcpr.find(W + "vMerge")
                    if span is not None and _int(span.get(W + "val"), 1) > 1:
                        merged = True
                    if vm is not None:
                        merged = True
                        if (vm.get(W + "val") or "continue") == "continue":
                            continue  # value sits in the first cell of the vertical merge
                t = self._cell_text(tc)
                if t:
                    cells.append(t)
            if cells:
                fl = [*flags, "merged_cell"] if merged else list(flags)
                self._emit(RawBlock("table_row", " | ".join(cells), fl, body))


def _rows(tbl):
    for child in tbl:
        if child.tag == W + "tr":
            yield child
        elif child.tag in (W + "sdt", W + "customXml", W + "ins"):
            content = child.find(W + "sdtContent") if child.tag == W + "sdt" else child
            if content is not None:
                yield from _rows(content)


def _cells(tr):
    for child in tr:
        if child.tag == W + "tc":
            yield child
        elif child.tag in (W + "sdt", W + "customXml"):
            content = child.find(W + "sdtContent") if child.tag == W + "sdt" else child
            if content is not None:
                yield from _cells(content)


def _clean_line(raw: str) -> tuple[str, bool]:
    """Collapse whitespace; 2+ inner tabs = a pseudo-table row, shown as ' | ' separated."""
    inner = raw.strip().split("\t")
    segs = [" ".join(s.split()) for s in inner]
    segs = [s for s in segs if s]
    if len(segs) >= 3 and raw.strip().count("\t") >= 2:
        return " | ".join(segs), True
    return " ".join(segs), False


# --- pages (P3-27) -------------------------------------------------------------------------


@dataclass
class DocxLayout:
    """What a page method needs: body blocks with breaks, app.xml page count, page geometry."""

    blocks: list[RawBlock]
    app_pages: int | None = None
    chars_per_line: float = 95.0
    lines_per_page: float = 46.0


PageMethod = Callable[[DocxLayout], tuple[list[int | None], str]]


def _pages_none(layout: DocxLayout) -> tuple[list[int | None], str]:
    return [None] * len(layout.blocks), "none"


def _pages_estimate(layout: DocxLayout) -> tuple[list[int | None], str]:
    """Page = proportional character position within each hard-break segment."""
    body = [i for i, b in enumerate(layout.blocks) if b.body]
    segments: list[list[int]] = []
    for i in body:
        if not segments or layout.blocks[i].break_before:
            segments.append([])
        segments[-1].append(i)
    if not segments:
        return [None] * len(layout.blocks), "estimated"

    def chars(i: int) -> int:
        return len(layout.blocks[i].text) + 1

    def lines(i: int) -> float:
        return math.ceil(chars(i) / layout.chars_per_line) + 0.5  # + paragraph spacing

    seg_chars = [sum(chars(i) for i in s) for s in segments]
    if layout.app_pages and layout.app_pages >= len(segments):
        extra = layout.app_pages - len(segments)
        total = sum(seg_chars) or 1
        shares = [extra * c / total for c in seg_chars]
        seg_pages = [1 + math.floor(s) for s in shares]
        left = layout.app_pages - sum(seg_pages)
        order = sorted(range(len(shares)), key=lambda k: shares[k] - math.floor(shares[k]))
        for k in reversed(order[-left:] if left > 0 else []):
            seg_pages[k] += 1
    else:
        seg_pages = [
            max(1, math.ceil(sum(lines(i) for i in s) / layout.lines_per_page)) for s in segments
        ]
    pages: list[int | None] = [None] * len(layout.blocks)
    start = 1
    for seg, n_chars, n_pages in zip(segments, seg_chars, seg_pages, strict=True):
        offset = 0
        for i in seg:
            pages[i] = start + min(n_pages - 1, math.floor(offset / max(n_chars, 1) * n_pages))
            offset += chars(i)
        start += n_pages
    return pages, "estimated"


PAGE_METHODS: dict[str, PageMethod] = {"estimate": _pages_estimate, "none": _pages_none}


def page_method_name(method: str | None = None) -> str:
    name = (method or os.environ.get("DOCX_PAGE_METHOD") or DEFAULT_PAGE_METHOD).strip().lower()
    if name not in PAGE_METHODS:
        raise ReaderError(f"docx reader: unknown DOCX_PAGE_METHOD {name!r}")
    return name


def docx_pages(layout: DocxLayout, method: str | None = None) -> tuple[list[int | None], str]:
    """-> (page per block, page_source). The one interface every page method implements."""
    return PAGE_METHODS[page_method_name(method)](layout)


# --- package helpers -----------------------------------------------------------------------


def _safe_xml(data: bytes):
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(data, parser)


def _app_pages(content: bytes) -> int | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if "docProps/app.xml" not in z.namelist():
                return None
            root = _safe_xml(z.read("docProps/app.xml"))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.endswith("}Pages") and (el.text or "").isdigit():
            return int(el.text) or None
    return None


def _geometry(body_el, styles_el) -> tuple[float, float]:
    """(chars per line, lines per page) from the last section's page size/margins and the
    default font size. Letter, 1-inch margins, 11 pt when not stated."""
    w, h, top, bottom, left, right = 12240, 15840, 1440, 1440, 1440, 1440
    sect = body_el.find(W + "sectPr") if body_el is not None else None
    if sect is not None:
        if (sz := sect.find(W + "pgSz")) is not None:
            w, h = _int(sz.get(W + "w"), w), _int(sz.get(W + "h"), h)
        if (mg := sect.find(W + "pgMar")) is not None:
            top = abs(_int(mg.get(W + "top"), top))
            bottom = abs(_int(mg.get(W + "bottom"), bottom))
            left, right = _int(mg.get(W + "left"), left), _int(mg.get(W + "right"), right)
    half_points = 22
    if styles_el is not None:
        el = styles_el.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr/{W}sz")
        if el is not None:
            half_points = _int(el.get(W + "val"), half_points)
        for st in styles_el.findall(W + "style"):
            if st.get(W + "styleId") == "Normal":
                el = st.find(f"{W}rPr/{W}sz")
                if el is not None:
                    half_points = _int(el.get(W + "val"), half_points)
    pt = max(half_points / 2, 6.0)
    width_pt = max((w - left - right) / 20, 72.0)
    height_pt = max((h - top - bottom) / 20, 72.0)
    return width_pt / (0.5 * pt), height_pt / (1.25 * pt)


# --- reader --------------------------------------------------------------------------------


def walk_docx(content: bytes) -> DocxLayout:
    """Package -> DocxLayout (raw blocks in order: headers, body, footers)."""
    import docx  # python-docx

    try:
        document = docx.Document(io.BytesIO(content))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ReaderError(f"docx reader: {type(exc).__name__}") from exc
    part = document.part
    try:
        numbering_el = part.numbering_part.element
    except (KeyError, NotImplementedError):
        numbering_el = None
    try:
        styles_el = document.styles.element
    except (KeyError, NotImplementedError):
        styles_el = None
    numbering = Numbering(numbering_el, styles_el)
    body_el = document.element.body

    heads, foots = Walker(numbering), Walker(numbering)
    seen: set[int] = set()
    for rel in part.rels.values():
        if rel.is_external:
            continue
        kind = rel.reltype.rsplit("/", 1)[-1]
        if kind not in ("header", "footer") or id(rel.target_part) in seen:
            continue
        seen.add(id(rel.target_part))
        w = heads if kind == "header" else foots
        w.body(rel.target_part.element, (kind,), body=False)

    main = Walker(numbering)
    main.body(body_el)
    cpl, lpp = _geometry(body_el, styles_el)
    return DocxLayout(heads.out + main.out + foots.out, _app_pages(content), cpl, lpp)


def read_docx(content: bytes, page_method: str | None = None) -> DocMap:
    layout = walk_docx(content)
    pages, source = docx_pages(layout, page_method)
    blocks: list[Block] = []
    for rb, page in zip(layout.blocks, pages, strict=True):
        flags = list(rb.flags)
        if page is not None and source == "estimated":
            flags.append("page_estimated")
        address = f"Page {page}" if page is not None else ""
        blocks.append(Block(rb.kind, address, rb.text, page=page, flags=tuple(flags)))
    meta = {
        "page_source": source,
        "pages": max((p for p in pages if p is not None), default=None),
        "app_pages": layout.app_pages,
        "page_breaks": sum(1 for b in layout.blocks if b.break_before),
    }
    return DocMap("docx", number_blocks("D", blocks), meta)
