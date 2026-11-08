"""P9a D48: write the SYN set, 8 invented test documents with exact invented answers.

    uv run python scripts/make_syn.py            # writes tests/fixtures/syn/
    uv run python scripts/make_syn.py --check    # build into a temp folder, compare bytes

Every value below is invented for this file. It is built only from the field lists
(sample/schemas/*.json: names + descriptions) and general CRE knowledge; no sample document
or answer file is read. The answers are exact by construction: each document is rendered
from the same Python data that becomes its answer.

Deterministic: fixed seed, no timestamps (PDF info dict has no dates; DOCX/XLSX zip entries
and core properties carry a fixed date). Running it twice gives identical bytes.

Writes, under tests/fixtures/syn/:
  manifest.csv                      document_id,file,schema_name,kind,notes
  documents/<id>.<ext>              the 8 documents
  answers/<id>.json                 contract output shape plus top-level "schema"/"document"
  schemas/syn_loan_summary.json     the invented unseen field list

Libraries: stdlib (PDF writer below), Pillow (scan pages), python-docx, openpyxl. All three
are already runtime dependencies; no new package is needed.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import filecmp
import io
import json
import random
import re
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "syn"
SEED = 9091
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)
FIXED_ISO = "2020-01-01T00:00:00Z"

# --------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------


def money(x: float) -> str:
    return f"{x:,.2f}"


def signed_money(x: float) -> str:
    return f"-{abs(x):,.2f}" if x < 0 else f"{x:,.2f}"


def pct_text(x: float | None) -> str:
    return "N/A" if x is None else f"{x:.2f}%"


def iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def us(d: dt.date) -> str:
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def long_date(d: dt.date) -> str:
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"


def ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def day_month_year(d: dt.date) -> str:
    return f"the {ordinal(d.day)} day of {calendar.month_name[d.month]}, {d.year}"


def add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(start: dt.date, end_inclusive: dt.date) -> int:
    nxt = end_inclusive + dt.timedelta(days=1)
    return (nxt.year - start.year) * 12 + (nxt.month - start.month)


def field(value: Any) -> dict[str, Any]:
    return {"value": value, "citation": "", "confidence": 1.0}


def answer(schema: str, doc_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": schema,
        "document": doc_id,
        "entries": [{k: field(v) for k, v in e.items()} for e in entries],
        "metadata": {"model_calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                     "latency_ms": 0, "synthetic": True},
    }  # fmt: skip


# --------------------------------------------------------------------------------------------
# a minimal PDF writer (text layer with the standard fonts, or full-page JPEG scans)
# --------------------------------------------------------------------------------------------

_HELV = (
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 556 556 "
    "556 556 556 556 278 278 584 584 584 556 1015 667 667 722 722 667 611 778 722 278 500 667 "
    "556 833 722 778 667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 333 556 "
    "556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556 333 500 278 556 500 722 "
    "500 500 500 334 260 334 584"
)
HELV_W = {chr(32 + i): int(w) for i, w in enumerate(_HELV.split())}
FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Courier"}


def text_width(s: str, size: float, font: str = "F1") -> float:
    if font == "F3":
        return 0.6 * size * len(s)
    k = 1.06 if font == "F2" else 1.0
    return sum(HELV_W.get(c, 556) for c in s) * size / 1000 * k


def wrap(s: str, width: float, size: float, font: str = "F1") -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        cand = f"{cur} {word}".strip()
        if cur and text_width(cand, size, font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines or [""]


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Page:
    def __init__(self, w: float, h: float) -> None:
        self.w, self.h = w, h
        self.ops: list[str] = []
        self.images: list[tuple[str, bytes, int, int]] = []

    def text(self, x: float, y: float, s: str, size: float = 10, font: str = "F1") -> None:
        s = s.encode("latin-1", "replace").decode("latin-1")
        self.ops.append(f"BT /{font} {size:g} Tf {x:.2f} {y:.2f} Td ({_esc(s)}) Tj ET")

    def right(self, xr: float, y: float, s: str, size: float = 10, font: str = "F1") -> None:
        self.text(xr - text_width(s, size, font), y, s, size, font)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5) -> None:
        self.ops.append(f"{width:g} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def image(self, jpeg: bytes, px_w: int, px_h: int) -> None:
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, jpeg, px_w, px_h))
        self.ops.append(f"q {self.w:g} 0 0 {self.h:g} 0 0 cm /{name} Do Q")


def write_pdf(pages: list[Page], path: Path, title: str) -> None:
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    def stream(dict_items: str, data: bytes) -> bytes:
        return (
            f"<< {dict_items} /Length {len(data)} >>\nstream\n".encode() + data + (b"\nendstream")
        )

    catalog = add(b"")  # placeholder, filled at the end
    pages_id = add(b"")
    font_ids = {
        k: add(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{v} /Encoding /WinAnsiEncoding >>".encode()
        )
        for k, v in FONTS.items()
    }
    fonts = " ".join(f"/{k} {i} 0 R" for k, i in font_ids.items())
    kids = []
    for p in pages:
        xobj = []
        for name, jpeg, pw, ph in p.images:
            iid = add(
                stream(
                    f"/Type /XObject /Subtype /Image /Width {pw} /Height {ph} "
                    "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode",
                    jpeg,
                )
            )
            xobj.append(f"/{name} {iid} 0 R")
        content = zlib.compress("\n".join(p.ops).encode("latin-1"), 9)
        cid = add(stream("/Filter /FlateDecode", content))
        res = f"/Font << {fonts} >>" + (f" /XObject << {' '.join(xobj)} >>" if xobj else "")
        kids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {p.w:g} {p.h:g}] "
                f"/Resources << {res} >> /Contents {cid} 0 R >>".encode()
            )
        )
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objs[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    ).encode()
    info = add(f"<< /Title ({_esc(title)}) /Producer (make_syn.py) >>".encode())

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(out.getvalue())


class Flow:
    """Top-down text flow over portrait Letter pages with automatic page breaks."""

    def __init__(self, header: str | None = None, w: float = 612, h: float = 792) -> None:
        self.w, self.h, self.header = w, h, header
        self.margin = 72
        self.pages: list[Page] = []
        self.new_page()

    def new_page(self) -> None:
        self.page = Page(self.w, self.h)
        self.pages.append(self.page)
        self.y = self.h - self.margin
        n = len(self.pages)
        if self.header:
            self.page.text(self.margin, self.h - 40, self.header, 8)
        self.page.right(self.w - self.margin, 40, f"Page {n}", 8)

    def need(self, height: float) -> None:
        if self.y - height < self.margin:
            self.new_page()

    def para(self, s: str, size: float = 10.5, font: str = "F1", indent: float = 0,
             after: float = 6) -> None:  # fmt: skip
        lead = size * 1.35
        for ln in wrap(s, self.w - 2 * self.margin - indent, size, font):
            self.need(lead)
            self.page.text(self.margin + indent, self.y - size, ln, size, font)
            self.y -= lead
        self.y -= after

    def heading(self, s: str, size: float = 12) -> None:
        self.need(size * 4)
        self.y -= 4
        self.para(s, size, "F2", after=4)


# --------------------------------------------------------------------------------------------
# 1. syn_lease_text: ~8-page text PDF lease with a rent-changing amendment
# --------------------------------------------------------------------------------------------


def lease_text() -> tuple[list[Page], dict]:
    rsf = 7420
    execution, commence = dt.date(2040, 3, 14), dt.date(2040, 5, 15)
    expire = dt.date(2045, 5, 14)
    orig = [18550.00, 19106.50, 19679.70, 20270.08, 20878.18]
    amended = {3: 19950.00, 4: 20400.00}  # First Amendment replaces periods 4 and 5
    starts = [add_months(commence, 12 * i) for i in range(5)]
    ends = [add_months(s, 12) - dt.timedelta(days=1) for s in starts]
    rents = [amended.get(i, r) for i, r in enumerate(orig)]
    per_rsf = [round(r * 12 / rsf, 2) for r in rents]
    v = {
        "tenant_name": "Brightwater Analytics, LLC",
        "landlord_legal_name": "Corvane Tower Owner LP",
        "property_name": "Corvane Tower",
        "building_address": "4800 Linden Ridge Parkway, Ashford, OH 43991",
        "premises": "Suite 1150",
        "rentable_square_footage": rsf,
        "pro_rata_share": 2.35,
        "permitted_use": "general office use and related lawful purposes",
        "lease_execution_date": iso(execution),
        "lease_commencement_date": iso(commence),
        "rent_commencement_date": iso(commence),
        "lease_expiration_date": iso(expire),
        "lease_term_months": months_between(commence, expire),
        "rent_schedule_start_dates": [iso(s) for s in starts],
        "rent_schedule_end_dates": [iso(e) for e in ends],
        "rent_schedule_monthly_rent": rents,
        "rent_schedule_annual_rent_per_rsf": per_rsf,
        "total_base_rent": round(sum(r * 12 for r in rents), 2),
        "base_rent_escalation": "set annual step-ups per the rent table",
        "free_rent_months": 0,
        "security_deposit_amount": 30000.00,
        "letter_of_credit_required": False,
        "expense_structure": "base year 2040",
        "base_year_expenses": 2040,
        "base_year_taxes": 2040,
        "electricity_provision": "separately metered and billed to Tenant",
        "parking_spaces": 18,
        "parking_monthly_charge": 95.00,
        "ti_allowance_total": 222600.00,
        "renewal_option_exists": True,
        "renewal_options_count": 1,
        "renewal_term_months": [60],
        "renewal_notice_months": [12],
        "early_termination_right": False,
        "termination_fee_description": None,
        "right_to_sublet": "with Landlord's consent, not unreasonably withheld",
        "guarantor_name": None,
        "broker_names": ["Halverson Realty Partners", "Kestrel Commercial Advisors"],
        "late_fee": "5% of the overdue amount",
        "holdover_rent": "175% of the Base Rent in effect at expiration",
    }

    f = Flow(header="Corvane Tower - Office Lease - Brightwater Analytics, LLC")
    f.heading("OFFICE LEASE", 16)
    f.para(
        f'THIS OFFICE LEASE (this "Lease") is made and entered into as of '
        f"{long_date(execution)}, by and between CORVANE TOWER OWNER LP, a Delaware limited "
        f'partnership ("Landlord"), and BRIGHTWATER ANALYTICS, LLC, an Ohio limited liability '
        f'company ("Tenant").'
    )
    f.para(
        "Landlord and Tenant agree to the terms below. Capitalized terms have the meanings "
        "given in this Lease. The Exhibits attached to this Lease form part of it."
    )
    f.heading("ARTICLE 1 - PREMISES")
    f.para(
        "1.1 Landlord leases to Tenant the space known as Suite 1150 on the eleventh floor "
        '(the "Premises") of the office building commonly known as Corvane Tower (the '
        '"Building"), located at 4800 Linden Ridge Parkway, Ashford, OH 43991.'
    )
    f.para(
        f"1.2 The Premises contain {rsf:,} rentable square feet. The Building contains "
        "315,700 rentable square feet. Tenant's Proportionate Share is 2.35%, being the ratio of "
        "the rentable area of the Premises to the rentable area of the Building."
    )
    f.para(
        "1.3 The rentable area figures above are stipulated for all purposes of this Lease and "
        "shall not be remeasured during the Term."
    )
    f.heading("ARTICLE 2 - TERM")
    f.para(
        f'2.1 The term of this Lease (the "Term") shall commence on {us(commence)} (the '
        f'"Commencement Date") and, unless sooner terminated, shall end at midnight on '
        f'{day_month_year(expire)} (the "Expiration Date").'
    )
    f.para(
        "2.2 Tenant's obligation to pay Base Rent begins on the Commencement Date. No period "
        "of free or abated Base Rent is granted under this Lease."
    )
    for i in range(3):
        f.para(
            f"2.{i + 3} Tenant shall have access to the Premises before the Commencement Date "
            "for installation of furniture, fixtures and cabling, provided Tenant's contractors "
            "carry the liability cover required by Article 11 and coordinate with the Building "
            "manager. Such early access shall be subject to all terms of this Lease except "
            "the payment of Base Rent."
        )
    f.heading("ARTICLE 3 - USE")
    f.para(
        "3.1 Tenant shall use the Premises for general office use and related lawful purposes "
        "and for no other purpose without Landlord's prior written consent."
    )
    f.para(
        "3.2 Tenant shall comply with all laws, the Building rules and regulations attached as "
        "Exhibit C, and the reasonable requirements of Landlord's insurers."
    )
    f.new_page()
    f.heading("ARTICLE 4 - BASE RENT")
    f.para(
        "4.1 Tenant shall pay Base Rent in monthly installments in advance on the first day of "
        "each calendar month, without demand, deduction or set-off. Base Rent shall rise by "
        "set annual step-ups as shown in the rent table below."
    )
    f.need(140)
    p, x0 = f.page, f.margin
    cols = [x0, x0 + 150, x0 + 300, x0 + 400]
    f.y -= 14
    for c, h in zip(cols, ["Period", "Monthly Base Rent", "Annual Base Rent", "Per RSF / Yr"],
                    strict=True):  # fmt: skip
        p.text(c, f.y, h, 9.5, "F2")
    f.y -= 6
    p.line(x0, f.y, f.w - f.margin, f.y)
    for i in range(5):
        f.y -= 15
        r, ann = orig[i], orig[i] * 12
        p.text(cols[0], f.y, f"{us(starts[i])} - {us(ends[i])}", 9.5)
        p.right(cols[1] + 90, f.y, f"${money(r)}", 9.5)
        p.right(cols[2] + 80, f.y, f"${money(ann)}", 9.5)
        p.right(cols[3] + 60, f.y, f"${round(r * 12 / rsf, 2):.2f}", 9.5)
    f.y -= 20
    f.para(
        "4.2 Base Rent for any partial month shall be prorated on a daily basis. All payments "
        "shall be made to Landlord at the address Landlord designates in writing."
    )
    f.para(
        "4.3 If any installment of Rent is not received within five (5) days after its due "
        "date, Tenant shall pay a late charge equal to 5% of the overdue amount."
    )
    f.heading("ARTICLE 5 - OPERATING EXPENSES AND TAXES")
    f.para(
        "5.1 Tenant shall pay Tenant's Proportionate Share of the amount by which Operating "
        "Expenses for each calendar year exceed Operating Expenses for the Base Year. For "
        "Operating Expenses the Base Year is calendar year 2040."
    )
    f.para(
        "5.2 Tenant shall likewise pay Tenant's Proportionate Share of the amount by which the "
        "property taxes levied on the Building for each calendar year exceed the property taxes "
        "levied for calendar year 2040."
    )
    f.para(
        "5.3 Landlord shall deliver an annual statement of actual Operating Expenses and Real "
        "Estate Taxes within one hundred twenty (120) days after the end of each calendar year. "
        "Tenant may audit such statement once per year on thirty (30) days' notice."
    )
    f.heading("ARTICLE 6 - POWER, WATER AND BUILDING SERVICES")
    f.para(
        "6.1 Electricity to the Premises shall be separately metered and billed to Tenant. "
        "Tenant shall pay the utility provider directly for all electricity consumed."
    )
    f.para(
        "6.2 Landlord shall furnish heating, ventilation and air conditioning during Building "
        "hours of 8:00 a.m. to 6:00 p.m. on business days. After-hours service is available at "
        "Landlord's then-current hourly rate."
    )
    f.new_page()
    f.heading("ARTICLE 7 - TENANT'S CASH DEPOSIT")
    f.para(
        "7.1 On execution of this Lease Tenant shall deposit with Landlord the sum of "
        "$37,100.00 in cash, to be held as a guarantee of Tenant's performance. No letter of "
        "credit shall be required under this Lease."
    )
    f.para(
        "7.2 Landlord may apply the cash deposit to cure any default of Tenant. Tenant "
        "shall restore the deposit within ten (10) days after notice of any application."
    )
    f.heading("ARTICLE 8 - PARKING")
    f.para(
        "8.1 Landlord shall make available to Tenant eighteen (18) unreserved parking spaces "
        "in the Building garage at a charge of $95.00 per space per month during the Term."
    )
    f.heading("ARTICLE 9 - ALTERATIONS AND IMPROVEMENTS")
    f.para(
        "9.1 Landlord shall provide a tenant improvement allowance of $222,600.00 toward the "
        "cost of Tenant's initial improvements, as more fully described in the Work Letter "
        "attached as Exhibit B."
    )
    f.para(
        "9.2 Tenant shall not make structural alterations without Landlord's prior written "
        "consent. Non-structural alterations costing less than $10,000 in any year need only "
        "prior notice."
    )
    f.heading("ARTICLE 10 - ASSIGNMENT AND SUBLETTING")
    f.para(
        "10.1 Tenant may sublet or assign this Lease with Landlord's consent, not unreasonably "
        "withheld. Any request shall include the proposed transferee's financial statements."
    )
    f.para(
        "10.2 Landlord shall respond to a complete request within fifteen (15) business days. "
        "Fifty percent of any net sublease profit shall be paid to Landlord."
    )
    f.new_page()
    f.heading("ARTICLE 11 - LIABILITY COVER AND INDEMNITY")
    for _ in range(3):
        f.para(
            "Tenant shall keep in force a commercial general liability policy with limits of not "
            "less than $2,000,000 per occurrence, naming Landlord and its managing agent as "
            "additional insureds, together with an all-risk policy covering Tenant's personal "
            "property at full replacement cost. Each party waives claims against the other to "
            "the extent the loss is covered by an all-risk policy."
        )
    f.heading("ARTICLE 12 - RENEWAL OPTION")
    f.para(
        "12.1 Tenant shall have one (1) option to extend the Term for a period of sixty (60) "
        "months on the terms of this Lease, at the then fair market rent."
    )
    f.para(
        "12.2 Tenant shall exercise the option by written notice given not less than twelve "
        "(12) months before the Expiration Date. The option is personal to the original Tenant."
    )
    f.heading("ARTICLE 13 - SURRENDER AND HOLDING OVER")
    f.para(
        "13.1 If Tenant remains in possession after the Expiration Date, Tenant shall pay rent "
        "at 175% of the Base Rent in effect at expiration for each month or part thereof."
    )
    f.new_page()
    f.heading("ARTICLE 14 - BROKERS")
    f.para(
        "14.1 Each party represents that it dealt with no broker in connection with this Lease "
        "other than Halverson Realty Partners, representing Landlord, and Kestrel Commercial "
        "Advisors, representing Tenant. Landlord shall pay both brokers under separate "
        "agreements."
    )
    f.heading("ARTICLE 15 - GENERAL PROVISIONS")
    for _ in range(4):
        f.para(
            "This Lease shall be governed by the laws of the State of Ohio. Notices shall be in "
            "writing and delivered by courier or certified mail to the addresses set out on the "
            "signature page. If any provision is held invalid, the remainder of this Lease "
            "shall not be affected. Time is of the essence of every provision."
        )
    f.para("IN WITNESS WHEREOF, the parties have executed this Lease as of the date first "
           "written above.")  # fmt: skip
    f.para("LANDLORD: CORVANE TOWER OWNER LP    By: ______________________")
    f.para("TENANT: BRIGHTWATER ANALYTICS, LLC    By: ______________________")
    f.new_page()
    f.heading("EXHIBIT C - BUILDING RULES AND REGULATIONS", 13)
    for k, rule in enumerate(
        [
            "Sidewalks, entrances, elevators and stairways shall not be obstructed.",
            "No sign shall be placed on any exterior window without Landlord's written consent.",
            "Deliveries of furniture and bulky items shall be made through the freight elevator.",
            "Tenant shall not install additional locks without providing keys to Landlord.",
            "Bicycles shall be stored only in the bicycle room on the garage level.",
            "Smoking is prohibited throughout the Building and within 25 feet of any entrance.",
            "Tenant shall keep corridor doors closed except when in use.",
            "Landlord may amend these rules on thirty (30) days' notice to all tenants.",
        ],
        1,
    ):
        f.para(
            f"{k}. {rule} Repeated or continuing violations may be treated as a default "
            "under the Lease after notice and a reasonable opportunity to cure."
        )
    f.new_page()
    f.heading("FIRST AMENDMENT TO OFFICE LEASE", 14)
    f.para(
        'This First Amendment (this "Amendment") is made as of 10/18/2042 between CORVANE '
        'TOWER OWNER LP ("Landlord") and BRIGHTWATER ANALYTICS, LLC ("Tenant") and amends '
        f'the Office Lease dated {long_date(execution)} (the "Lease").'
    )
    f.para(
        "1. Base Rent. Effective as of the dates below, the Base Rent schedule in Section 4.1 "
        "of the Lease is amended so that the monthly Base Rent for the following periods "
        "shall be:"
    )
    for i in sorted(amended):
        f.para(
            f"{us(starts[i])} through {us(ends[i])}: ${money(amended[i])} per month "
            f"(${per_rsf[i]:.2f} per rentable square foot per year).",
            indent=24,
        )
    f.para(
        "All other periods of the Base Rent schedule are unchanged. Base Rent continues to "
        "rise by the set annual step-ups shown in the rent table."
    )
    f.para(
        "2. Cash Deposit. The cash deposit required by Section 7.1 is reduced to "
        "$30,000.00. Landlord shall refund the excess to Tenant within thirty (30) days."
    )
    f.para(
        "3. Ratification. Except as amended above, the Lease remains in full force and effect "
        "and is ratified by the parties."
    )
    f.para("LANDLORD: CORVANE TOWER OWNER LP    By: ______________________")
    f.para("TENANT: BRIGHTWATER ANALYTICS, LLC    By: ______________________")
    return f.pages, v


# --------------------------------------------------------------------------------------------
# 2. syn_lease_scan: 6 scanned form pages (rendered images, slight rotation and noise)
# --------------------------------------------------------------------------------------------


def lease_scan_values() -> tuple[dict, dict[str, str]]:
    """-> (answer values, printed strings keyed by box label)."""
    rsf = 3180
    execution, commence = dt.date(2040, 1, 18), dt.date(2040, 2, 15)
    rent_start, expire = dt.date(2040, 4, 15), dt.date(2045, 2, 14)
    starts = [rent_start] + [add_months(dt.date(2041, 2, 15), 12 * i) for i in range(4)]
    ends = [dt.date(2041, 2, 14)] + [add_months(s, 12) - dt.timedelta(days=1) for s in starts[1:]]
    rents = [7950.00]
    for _ in range(4):
        rents.append(round(rents[-1] * 1.025, 2))
    months = [months_between(s, e) for s, e in zip(starts, ends, strict=True)]
    v = {
        "tenant_name": "Pell & Ostrander Dental Group, P.C.",
        "landlord_legal_name": "Marrow Creek Holdings, Inc.",
        "property_name": "Marrow Creek Medical Pavilion",
        "building_address": "215 Quarry Bend Road, Ellisport, WA 98477",
        "premises": "Suite 210",
        "rentable_square_footage": rsf,
        "pro_rata_share": None,
        "permitted_use": "dental and medical office",
        "lease_execution_date": iso(execution),
        "lease_commencement_date": iso(commence),
        "rent_commencement_date": iso(rent_start),
        "lease_expiration_date": iso(expire),
        "lease_term_months": months_between(commence, expire),
        "rent_schedule_start_dates": [iso(s) for s in starts],
        "rent_schedule_end_dates": [iso(e) for e in ends],
        "rent_schedule_monthly_rent": rents,
        "rent_schedule_annual_rent_per_rsf": [round(r * 12 / rsf, 2) for r in rents],
        "total_base_rent": round(sum(r * m for r, m in zip(rents, months, strict=True)), 2),
        "base_rent_escalation": "2.5% annually",
        "free_rent_months": 2,
        "security_deposit_amount": 19080.00,  # Rider No. 1 (last page) governs over the form
        "letter_of_credit_required": True,
        "expense_structure": "triple net",
        "base_year_expenses": None,
        "base_year_taxes": None,
        "electricity_provision": "separately metered",
        "parking_spaces": None,
        "parking_monthly_charge": None,
        "ti_allowance_total": 47700.00,
        "renewal_option_exists": True,
        "renewal_options_count": 2,
        "renewal_term_months": [60, 60],
        "renewal_notice_months": [9, 9],
        "early_termination_right": True,
        "termination_fee_description": "unamortized TI allowance plus 3 months Base Rent",
        "right_to_sublet": "not permitted without landlord consent",
        "guarantor_name": "Dr. Lena Ostrander",
        "broker_names": [],
        "late_fee": "10% of the overdue amount",
        "holdover_rent": "200% of the last monthly Base Rent",
    }
    sched = [
        (f"{us(s)} - {us(e)}", f"${money(r)}") for s, e, r in zip(starts, ends, rents, strict=True)
    ]
    return v, {"sched": sched, "execution": execution, "commence": commence,
               "rent_start": rent_start, "expire": expire}  # fmt: skip


def render_form_pages(v: dict, extra: dict) -> list[tuple[bytes, int, int]]:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1100, 1424  # ~130 dpi Letter
    label_font = ImageFont.load_default(size=18)
    value_font = ImageFont.load_default(size=24)
    title_font = ImageFont.load_default(size=32)
    body_font = ImageFont.load_default(size=22)
    rng = random.Random(SEED + 2)
    total = 1 + len(SCAN_BOILERPLATE) + 6 + 1

    def yesno(b: bool) -> str:
        return "[X] Yes   [ ] No" if b else "[ ] Yes   [X] No"

    pages_spec = [
        (
            "STANDARD COMMERCIAL LEASE - SUMMARY FORM  (Page 1 of 6)",
            [
                ("1. Date of Lease", long_date(extra["execution"])),
                ("2. Landlord (legal name)", v["landlord_legal_name"]),
                ("3. Tenant (legal name)", v["tenant_name"]),
                ("4. Building / Project Name", v["property_name"]),
                ("5. Building Street Address", v["building_address"]),
                ("6. Premises (suite / floor)", v["premises"]),
                ("7. Rentable Area of Premises (RSF)", f"{v['rentable_square_footage']:,}"),
                ("8. Tenant's Share of Building", ""),
            ],
        ),
        (
            "STANDARD COMMERCIAL LEASE - TERM  (Page 2 of 6)",
            [
                ("9. Permitted Use", v["permitted_use"]),
                ("10. Commencement Date", us(extra["commence"])),
                ("11. Rent Commencement Date", long_date(extra["rent_start"])),
                ("12. Expiration Date", us(extra["expire"])),
                ("13. Initial Term", "Sixty (60) months"),
                ("14. Free Rent", "Two (2) months of Base Rent abated (first two months)"),
            ],
        ),
        (
            "STANDARD COMMERCIAL LEASE - BASE RENT  (Page 3 of 6)",
            [
                (
                    "15. Base Rent Escalation",
                    "Base Rent increases 2.5% annually on each February 15",
                ),
                *[
                    (f"16.{i + 1} Rent Period / Monthly Base Rent", f"{p}    {r}")
                    for i, (p, r) in enumerate(extra["sched"])
                ],
            ],
        ),
        (
            "STANDARD COMMERCIAL LEASE - DEPOSIT & EXPENSES  (Page 4 of 6)",
            [
                ("17. Cash Deposit", "$15,900.00  (see Rider No. 1)"),
                ("18. Letter of Credit Required", yesno(True) + "   Amount: $23,850.00"),
                ("19. Operating Expenses", "Triple net: Tenant pays its share of all expenses"),
                ("20. Electricity", "Separately metered; Tenant pays utility directly"),
                ("21. Tenant Improvement Allowance", f"${money(v['ti_allowance_total'])}"),
                ("22. Late Charge", "10% of the overdue amount"),
            ],
        ),
        (
            "STANDARD COMMERCIAL LEASE - OPTIONS  (Page 5 of 6)",
            [
                ("23. Renewal Options", yesno(True) + "   Number of options: 2"),
                ("24. Length of each renewal term", "60 months each"),
                ("25. Renewal notice", "9 months prior written notice for each option"),
                ("26. Early Termination Right", yesno(True)),
                ("27. Termination Fee", v["termination_fee_description"]),
                ("28. Assignment / Subletting", "Not permitted without landlord consent"),
            ],
        ),
        (
            "STANDARD COMMERCIAL LEASE - OTHER TERMS  (Page 6 of 6)",
            [
                ("29. Holdover Rent", v["holdover_rent"]),
                ("30. Guarantor", v["guarantor_name"]),
                ("31. Brokers", "None"),
                ("32. Landlord signature", "/s/ authorized signatory"),
                ("33. Tenant signature", "/s/ authorized signatory"),
            ],
        ),
    ]

    def finish(img, n: int) -> tuple[bytes, int, int]:
        """Slight rotation plus coarse grain, like a photocopied page; deterministic."""
        angle = rng.choice([-0.7, -0.4, 0.3, 0.6, 0.8, -0.5])
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
        sw, sh = W // 3, H // 3
        grain = Image.frombytes("L", (sw, sh), random.Random(SEED + 10 + n).randbytes(sw * sh))
        img = Image.blend(img, grain.resize((W, H), Image.Resampling.BILINEAR), 0.06)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        return buf.getvalue(), W, H

    def new_page(title: str, n: int):
        img = Image.new("L", (W, H), 255)
        d = ImageDraw.Draw(img)
        d.text((80, 70), title, fill=20, font=title_font)
        d.line((80, 118, W - 80, 118), fill=40, width=3)
        d.text((W - 230, H - 60), f"Page {n} of {total}", fill=60, font=label_font)
        return img, d

    def text_page(title: str, paragraphs: list[str], n: int) -> tuple[bytes, int, int]:
        img, d = new_page(title, n)
        y = 145
        for para in paragraphs:
            line = ""
            for word in para.split():
                cand = f"{line} {word}".strip()
                if line and body_font.getlength(cand) > W - 160:
                    d.text((80, y), line, fill=20, font=body_font)
                    y, line = y + 31, word
                else:
                    line = cand
            d.text((80, y), line, fill=20, font=body_font)
            y += 31 + 16
        assert y < H - 80, f"scan text page {n} overflows"
        return finish(img, n)

    out = [text_page("LEASE AGREEMENT", SCAN_COVER, 1)]
    for i, (title, paras) in enumerate(SCAN_BOILERPLATE):
        out.append(text_page(title, paras, i + 2))
    for title, boxes in pages_spec:  # the filled-in form starts after page 8
        n = len(out) + 1
        img, d = new_page(title, n)
        y = 150
        for label, value in boxes:
            d.rectangle((80, y, W - 80, y + 84), outline=30, width=2)
            d.text((94, y + 7), label, fill=60, font=label_font)
            d.text((108, y + 38), value, fill=15, font=value_font)
            y += 102
        out.append(finish(img, n))
    out.append(text_page("RIDER NO. 1 TO LEASE", SCAN_RIDER, len(out) + 1))
    assert len(out) == total
    return out


SCAN_COVER = [
    "MEDICAL OFFICE LEASE AGREEMENT",
    "This Lease consists of the General Provisions on the following pages, the Summary Form "
    "that follows them, and any Rider attached at the end. If the Summary Form and the General "
    "Provisions conflict, the Summary Form controls; a Rider controls over both.",
    "Prepared from the Landlord's standard form. Blanks are completed on the Summary Form only.",
]
_ARTICLES = [
    "ARTICLE 1 - DEFINITIONS", "ARTICLE 2 - USE AND COMPLIANCE WITH LAWS",
    "ARTICLE 3 - UPKEEP OF THE PREMISES", "ARTICLE 4 - POLICIES OF COVER AND INDEMNITY",
    "ARTICLE 5 - CASUALTY AND CONDEMNATION", "ARTICLE 6 - DEFAULT AND REMEDIES",
    "ARTICLE 7 - SUBORDINATION, NOTICES AND GENERAL TERMS",
]  # fmt: skip
_CLAUSES = [
    "Capitalized terms used in this Lease have the meanings given on the Summary Form. "
    "References to Rent include Base Rent and all Additional Rent payable by Tenant.",
    "Tenant shall comply with all laws, ordinances and regulations applicable to its use of "
    "the Premises, including those governing medical waste, radiation equipment and patient "
    "privacy, at Tenant's sole cost.",
    "Landlord shall maintain the roof, foundation, structural elements and common areas of the "
    "Building. Tenant shall maintain the interior of the Premises in good order and repair.",
    "Tenant shall carry commercial general liability and errors-and-omissions policies in "
    "amounts reasonably required by Landlord and shall deliver certificates before occupancy.",
    "If the Premises are damaged by fire or other casualty, Landlord shall restore them within "
    "a reasonable time, and Rent shall abate in proportion to the area that cannot be used.",
    "If any part of the Building is taken by eminent domain so that the Premises cannot "
    "reasonably be used, either party may terminate this Lease by written notice.",
    "Tenant is in default if it fails to pay Rent within ten days after notice, or fails to "
    "cure any other breach within thirty days after notice. Landlord may then pursue any remedy "
    "available at law or in equity.",
    "This Lease is subordinate to any mortgage now or later placed on the Building, provided "
    "the mortgagee agrees not to disturb Tenant's possession while Tenant is not in default.",
    "Notices shall be in writing and delivered by hand, by overnight courier or by certified "
    "mail to the addresses of the parties as Landlord and Tenant may designate in writing.",
    "This Lease binds and benefits the parties and their permitted successors and assigns. "
    "Waiver of one breach is not a waiver of any later breach of the same or another term.",
]
SCAN_BOILERPLATE = [
    (title, [_CLAUSES[(i + k) % len(_CLAUSES)] for k in range(5)])
    for i, title in enumerate(_ARTICLES)
]
SCAN_RIDER = [
    "This Rider No. 1 is attached to and forms part of the Lease described in the Summary Form.",
    "1. Cash Deposit. Notwithstanding Item 17 of the Summary Form, the Cash Deposit held by "
    "Landlord is increased to $19,080.00, payable by Tenant on or before the Rent Commencement "
    "Date.",
    "2. Except as stated in this Rider, all terms of the Lease remain unchanged.",
    "Landlord: /s/ authorized signatory          Tenant: /s/ authorized signatory",
]


def lease_scan() -> tuple[list[Page], dict]:
    v, extra = lease_scan_values()
    pages = []
    for jpeg, w, h in render_form_pages(v, extra):
        p = Page(612, 792)
        p.image(jpeg, w, h)
        pages.append(p)
    return pages, v


# --------------------------------------------------------------------------------------------
# 3. syn_lease_docx: DOCX lease with one rent table
# --------------------------------------------------------------------------------------------


def lease_docx(path: Path) -> dict:
    import docx

    rsf = 12600
    execution, commence = dt.date(2040, 6, 12), dt.date(2040, 9, 15)
    rent_start, expire = dt.date(2041, 1, 15), dt.date(2045, 9, 14)
    starts = [rent_start, dt.date(2042, 9, 15), dt.date(2044, 9, 15)]
    ends = [dt.date(2042, 9, 14), dt.date(2044, 9, 14), expire]
    per_rsf = [25.00, 27.00, 29.00]
    rents = [round(rsf * p / 12, 2) for p in per_rsf]
    months = [months_between(s, e) for s, e in zip(starts, ends, strict=True)]
    v = {
        "tenant_name": "Quillfeather Learning Co.",
        "landlord_legal_name": "Saltmeadow Office Partners, L.L.C.",
        "property_name": None,
        "building_address": "77 Cobbler Street, Fenwick, NJ 07761",
        "premises": "3rd Floor",
        "rentable_square_footage": rsf,
        "pro_rata_share": 18.4,
        "permitted_use": "administrative and educational office use",
        "lease_execution_date": iso(execution),
        "lease_commencement_date": iso(commence),
        "rent_commencement_date": iso(rent_start),
        "lease_expiration_date": iso(expire),
        "lease_term_months": months_between(commence, expire),
        "rent_schedule_start_dates": [iso(s) for s in starts],
        "rent_schedule_end_dates": [iso(e) for e in ends],
        "rent_schedule_monthly_rent": rents,
        "rent_schedule_annual_rent_per_rsf": per_rsf,
        "total_base_rent": round(sum(r * m for r, m in zip(rents, months, strict=True)), 2),
        "base_rent_escalation": "set step-ups per the rent table",
        "free_rent_months": 4,
        "security_deposit_amount": 52500.00,
        "letter_of_credit_required": False,
        "expense_structure": "expense stop $11.50 per RSF",
        "base_year_expenses": None,
        "base_year_taxes": None,
        "electricity_provision": "included in Base Rent",
        "parking_spaces": 25,
        "parking_monthly_charge": None,
        "ti_allowance_total": None,
        "renewal_option_exists": False,
        "renewal_options_count": 0,
        "renewal_term_months": [],
        "renewal_notice_months": [],
        "early_termination_right": True,
        "termination_fee_description": "unamortized leasing costs plus six months of Base Rent",
        "right_to_sublet": "with landlord consent, which may be withheld in its sole discretion",
        "guarantor_name": None,
        "broker_names": ["Northgate Tenant Advisory"],
        "late_fee": "interest at 12% per annum",
        "holdover_rent": None,
    }
    d = docx.Document()
    d.core_properties.author = "make_syn"
    d.core_properties.created = dt.datetime(2020, 1, 1)
    d.core_properties.modified = dt.datetime(2020, 1, 1)
    d.core_properties.last_modified_by = "make_syn"
    d.core_properties.revision = 1
    d.add_heading("LEASE AGREEMENT", 0)
    paras = [
        f"This Lease Agreement is dated {long_date(execution)} between SALTMEADOW OFFICE "
        'PARTNERS, L.L.C., a New Jersey limited liability company ("Landlord"), and '
        'QUILLFEATHER LEARNING CO., a Delaware corporation ("Tenant").',
        (
            '1. Premises. Landlord leases to Tenant the entire 3rd Floor (the "Premises") of the '
            f"building at 77 Cobbler Street, Fenwick, NJ 07761, containing {rsf:,} rentable square "
            "feet. Tenant's share of the building is 18.40%."
        ),
        "2. Use. Tenant shall use the Premises for administrative and educational office use.",
        (
            f"3. Term. The term begins on {long_date(commence)} and ends on {long_date(expire)}. "
            f"Base Rent begins on {day_month_year(rent_start)}; Base Rent for the first four (4) "
            "months of the term is abated."
        ),
        (
            "4. Base Rent. Tenant shall pay monthly Base Rent according to the table below. Base "
            "Rent rises by the set step-ups shown in the rent table."
        ),
    ]
    for t in paras:
        d.add_paragraph(t)
    table = d.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for c, h in zip(table.rows[0].cells, ["Period", "Annual Rate per RSF", "Monthly Base Rent",
                                          "Months"], strict=True):  # fmt: skip
        c.text = h
    for s, e, p, r, m in zip(starts, ends, per_rsf, rents, months, strict=True):
        cells = table.add_row().cells
        cells[0].text = f"{us(s)} to {us(e)}"
        cells[1].text = f"${p:.2f}"
        cells[2].text = f"${money(r)}"
        cells[3].text = str(m)
    for t in [
        (
            "5. Operating Expenses. Tenant shall pay its share of Operating Expenses above an "
            "expense stop of $11.50 per RSF per year."
        ),
        "6. Electricity. Electricity for the Premises is included in Base Rent.",
        (
            "7. Cash Deposit. Tenant shall deposit $52,500.00 in cash with Landlord. No letter "
            "of credit is required."
        ),
        "8. Parking. Tenant may use 25 unreserved parking spaces in the surface lot.",
        (
            "9. Condition. Tenant accepts the Premises in its as-is condition and Landlord shall "
            "perform no work."
        ),
        (
            "10. Early Termination. Tenant may terminate this Lease effective as of the last day "
            "of the 36th month of the term on twelve months' notice, by paying a fee equal to "
            "unamortized leasing costs plus six months of Base Rent."
        ),
        (
            "11. Assignment. Tenant may sublet or assign only with landlord consent, which may be "
            "withheld in its sole discretion."
        ),
        (
            "12. Late Payment. Rent not paid when due bears interest at 12% per annum from the due "
            "date until paid."
        ),
        (
            "13. Brokers. Tenant was represented by Northgate Tenant Advisory. Landlord was not "
            "represented by a broker."
        ),
        "14. Entire Agreement. This Lease contains the entire agreement of the parties.",
    ]:
        d.add_paragraph(t)
    buf = io.BytesIO()
    d.save(buf)
    path.write_bytes(normalise_zip(buf.getvalue()))
    return v


# --------------------------------------------------------------------------------------------
# 4. syn_budget_pdf: 3-page budget variance report, ~45 GL rows, wrapped commentary
# --------------------------------------------------------------------------------------------

BUDGET_SECTIONS = [
    ("Rent Billings", ["Monthly Rent from Office Suites", "Monthly Rent from Street Shops",
                       "Rent Waived Under Lease Deals", "Rent from Lower-Level Lockers"]),
    ("Tenant Cost Pass-Throughs", ["Running Costs Billed Back", "Levy Share Billed Back",
                                   "Metered Power Rebilled"]),
    ("Sundry Building Income", ["Garage Ticket Sales", "Rooftop Antenna Rent",
                                "Charges on Overdue Rent"]),
    ("Custodial Costs", ["Nightly Custodial Crew", "Exterior Glass Washing",
                         "Restroom Paper Goods", "Daytime Porter Staff", "Carpet Shampooing"]),
    ("Building Upkeep", ["Lift Service Agreement", "Heating and Cooling Agreement",
                         "Heating and Cooling Fixes", "Pipe and Drain Fixes",
                         "Wiring and Lighting Fixes", "Roof Patching",
                         "Sprinkler and Alarm Testing"]),
    ("Power, Water and Fuel", ["Lobby and Hall Power", "Water and Drain Charges",
                               "Boiler Gas Charges", "Waste Hauling"]),
    ("Guarding and Access", ["Guard Staffing Hours", "Badge Reader Upkeep",
                             "Alarm Watch Service"]),
    ("Site Office Costs", ["Site Office Wages", "Stationery and Postage", "Phone and Data Lines",
                           "Tenant Events and Gifts", "Audit and Legal Bills"]),
    ("Policy Premiums", ["All-Risk Building Policy", "General Claims Policy"]),
    ("Property Levies", ["Annual County Levy", "Levy Appeal Advisors"]),
    ("Owner Oversight Fees", ["Site Operator Fee", "Owner's Rep Fee"]),
    ("Grounds Care", ["Lawn and Shrub Care", "Snow Plowing and Salt", "Seasonal Flower Beds"]),
]  # fmt: skip

COMMENTS = [
    "Contract rebid in Q2 at a lower monthly rate.",
    "Higher usage expected after the lobby renovation is completed in the spring.",
    "Reforecast reflects two new leases signed in the third quarter, partly offset by one "
    "early move-out on the fourth floor.",
    "Vendor change; new contract includes quarterly deep cleaning of all restrooms.",
    "No change expected.",
    "Rate increase of four percent per the amended service agreement, plus one additional "
    "inspection required by the city.",
    "One-time repair of the cooling tower fan motor in July did not recur in the budget year.",
    "Budget assumes a full year of the new garage operator at the higher daily rate.",
    "Premium rates rising across the market; renewal quote received from the broker in November.",
    "Assessment appeal is pending; budget holds the reforecast value flat.",
]


def budget_rows() -> tuple[dict, list[dict], list[tuple[str, list[dict]]]]:
    rng = random.Random(SEED + 4)
    header = {"property_name": "Halcyon Point Office Center", "property_rsf": 186450,
              "budget_year": 2042}  # fmt: skip
    rows, grouped = [], []
    for si, (section, items) in enumerate(BUDGET_SECTIONS):
        sec_rows = []
        revenue = si < 3
        for ii, item in enumerate(items):
            code = f"{(4 if revenue else 6) + si // 6}{si % 10}{ii + 1}0-{rng.randint(10, 99)}0"
            scale = rng.choice([1450, 6150, 17350, 43650, 117250]) * (8 if revenue else 1)
            pb = 0.0 if (si, ii) in {(0, 2), (2, 2)} else round(rng.uniform(0.6, 1.4) * scale, 0)
            rf = round(pb * rng.uniform(0.7, 1.3), 0) if pb else round(rng.uniform(0.3, 1) * scale)
            bd = round(rf * rng.uniform(0.85, 1.2), 0)
            v1 = round(rf - pb, 2)
            v2 = round(bd - rf, 2)
            p1 = round(v1 / pb * 100, 2) if pb else None
            p2 = round(v2 / rf * 100, 2) if rf else None
            comment = COMMENTS[rng.randrange(len(COMMENTS))] if rng.random() < 0.6 else None
            r = {**header, "gl_code": code, "line_item": item, "section": section,
                 "prior_year_budget": pb, "prior_year_reforecast": rf, "budget": bd,
                 "reforecast_vs_prior_budget_variance": v1,
                 "reforecast_vs_prior_budget_pct": p1,
                 "budget_vs_reforecast_variance": v2, "budget_vs_reforecast_pct": p2,
                 "explanation_of_variance": comment}  # fmt: skip
            sec_rows.append(r)
            rows.append(r)
        grouped.append((section, sec_rows))
    return header, rows, grouped


def budget_pdf() -> tuple[list[Page], dict]:
    header, rows, grouped = budget_rows()
    W, H = 792, 612
    size, lead = 7, 9.2
    # column right edges (numbers right-aligned), commentary column left edge + width
    x_code, x_item = 36, 82
    num_right = [300, 352, 404, 452, 492, 540, 580]
    x_comm, w_comm = 592, 164
    heads = ["2041 Budget", "2041 Reforecast", "2042 Budget", "Refcst vs Bud $",
             "Refcst vs Bud %", "Bud vs Refcst $", "Bud vs Refcst %"]  # fmt: skip
    pages: list[Page] = []
    total_pages = 3
    page: Page | None = None
    y = 0.0

    def start_page() -> None:
        nonlocal page, y
        page = Page(W, H)
        pages.append(page)
        page.text(36, H - 36, "Halcyon Point Office Center", 11, "F2")
        page.text(36, H - 50, "Budget Analysis Report - 2042 Budget vs 2041 Reforecast", 9)
        page.text(36, H - 62, "Property RSF: 186,450   Budget Year: 2042   Accrual basis", 8)
        page.right(W - 36, H - 36, f"Page {len(pages)} of {total_pages}", 8)
        y = H - 84
        page.text(x_code, y, "GL Code", size, "F2")
        page.text(x_item, y, "Line Item", size, "F2")
        for xr, h in zip(num_right, heads, strict=True):
            a, _, b = h.partition(" vs ")
            if b:
                page.right(xr, y + lead, a + " vs", size - 0.5, "F2")
                page.right(xr, y, b, size - 0.5, "F2")
            else:
                page.right(xr, y, h, size - 0.5, "F2")
        page.text(x_comm, y, "Explanation of Variance", size, "F2")
        y -= 4
        page.line(36, y, W - 36, y)
        y -= lead

    def fmt_num(x: float) -> str:
        return signed_money(x).replace(".00", "") if x == int(x) else signed_money(x)

    per_page = [16, 16, 99]  # detail rows per page (3 pages total)
    count, page_i = 0, 0
    start_page()
    for section, sec_rows in grouped:
        if count >= per_page[page_i]:
            page_i, count = page_i + 1, 0
            start_page()
        page.text(x_code, y, section, size + 0.5, "F2")
        y -= lead
        for r in sec_rows:
            if count >= per_page[page_i]:
                page_i, count = page_i + 1, 0
                start_page()
                page.text(x_code, y, f"{section} (continued)", size + 0.5, "F2")
                y -= lead
            comm = wrap(r["explanation_of_variance"] or "", w_comm, size)
            page.text(x_code, y, r["gl_code"], size)
            page.text(x_item, y, r["line_item"], size)
            vals = [
                fmt_num(r["prior_year_budget"]), fmt_num(r["prior_year_reforecast"]),
                fmt_num(r["budget"]), fmt_num(r["reforecast_vs_prior_budget_variance"]),
                pct_text(r["reforecast_vs_prior_budget_pct"]),
                fmt_num(r["budget_vs_reforecast_variance"]),
                pct_text(r["budget_vs_reforecast_pct"]),
            ]  # fmt: skip
            for xr, s in zip(num_right, vals, strict=True):
                page.right(xr, y, s, size)
            for k, ln in enumerate(comm):
                page.text(x_comm, y - k * lead, ln, size)
            y -= lead * max(1, len(comm))
            count += 1
        tot = [
            sum(r[k] for r in sec_rows)
            for k in ("prior_year_budget", "prior_year_reforecast", "budget")
        ]
        page.text(x_item, y, f"Total {section}", size, "F2")
        for xr, s in zip(num_right, [fmt_num(t) for t in tot], strict=False):
            page.right(xr, y, s, size, "F2")
        y -= lead * 1.4
    assert len(pages) == total_pages, len(pages)
    return pages, answer("budget_variance", "syn_budget_pdf", rows)


# --------------------------------------------------------------------------------------------
# 5./6. rent rolls: PDF (~30 units, 2 pages) and XLSX (report + parameters sheets)
# --------------------------------------------------------------------------------------------

UNIT_TYPES = {"A1": 640, "A2": 715, "B1": 980, "B2": 1065, "C1": 1290}
STATUS_MIX = ["Leased - current"] * 6 + ["Empty - available", "Leased - notice, unit re-let",
                                         "Empty - pre-leased", "Leased - notice given"]  # fmt: skip
FIRST = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Quinn", "Rowan", "Emerson", "Hollis",
         "Marlow", "Sutton", "Tatum", "Wren", "Darby", "Ellison", "Linden"]  # fmt: skip
LAST = ["Abernathy", "Coldwell", "Draycott", "Fairbanks", "Gilchrist", "Harrowgate",
        "Kittredge", "Lockhart", "Merriweather", "Penhallow", "Quarles", "Ravenscroft",
        "Stanhope", "Thistlewood", "Underhill", "Westover"]  # fmt: skip
OTHER_CHARGES = [("PARK", 45.0), ("PET", 35.0), ("TRASH", 14.0), ("STOR", 60.0),
                 ("WATER", 38.5)]  # fmt: skip


def rent_roll_units(prefix: str, n: int, period: dt.date, seed: int, prop: str) -> list[dict]:
    rng = random.Random(seed)
    units = []
    for i in range(n):
        floor = 1 + i // 10
        unit = f"{prefix}-{floor}{i % 10 + 1:02d}"
        code = rng.choice(list(UNIT_TYPES))
        sqft = UNIT_TYPES[code]
        status = rng.choice(STATUS_MIX)
        market = round(sqft * rng.choice([1.55, 1.6, 1.65, 1.7]) / 5) * 5.0
        vacant = status.startswith("Empty")
        charges: list[tuple[str, float]] = []
        if not vacant:
            charges.append(("RENT", market - rng.choice([0, 0, 25, 50, 75])))
            for code_c, amt in OTHER_CHARGES:
                if rng.random() < 0.35:
                    charges.append((code_c, amt))
        rent = sum(a for c, a in charges if c == "RENT")
        other = round(sum(a for c, a in charges if c != "RENT"), 2)
        move_in = lease_start = lease_end = move_out = None
        resident = None
        deposit = balance = 0.0
        if not vacant:
            resident = f"{rng.choice(LAST)}, {rng.choice(FIRST)}"
            move_in = dt.date(period.year - rng.randint(0, 2), rng.randint(1, 12), 1) + (
                dt.timedelta(days=rng.randint(10, 19))  # mid-month days
            )
            if move_in > period:
                move_in = move_in.replace(year=move_in.year - 1)
            lease_start = add_months(move_in, 12 * ((period - move_in).days // 365))
            if lease_start > period:
                lease_start = move_in
            lease_end = add_months(lease_start, 12) - dt.timedelta(days=1)
            deposit = rng.choice([250.0, 500.0, market])
            balance = rng.choice([0.0, 0.0, 0.0, round(rng.uniform(-300, 900), 2)])
            if "notice" in status:
                move_out = lease_end
        units.append({
            "property_name": prop, "report_period": f"{period.year}-{period.month:02d}",
            "unit_number": unit, "unit_type_code": code, "unit_square_feet": sqft,
            "unit_status": status, "resident_name": resident, "market_rent": market,
            "monthly_rent": rent, "monthly_other_charges": other,
            "monthly_total_charges": round(rent + other, 2), "deposit_held": deposit,
            "balance": balance, "move_in_date": iso(move_in),
            "lease_start_date": iso(lease_start), "lease_end_date": iso(lease_end),
            "expected_move_out_date": iso(move_out), "_charges": charges,
        })  # fmt: skip
    return units


def _d(s: str | None) -> str:
    return us(dt.date.fromisoformat(s)) if s else ""


def rentroll_pdf() -> tuple[list[Page], dict]:
    period = dt.date(2043, 10, 15)
    prop = "Juniper Hollow Apartments"
    units = rent_roll_units("J", 30, period, SEED + 5, prop)
    W, H = 792, 612
    size, lead = 7, 8.0
    cols = [(36, "Unit", "l"), (78, "Type", "l"), (130, "Sq Ft", "r"), (140, "Status", "l"),
            (248, "Resident", "l"), (365, "Market Rent", "r"), (385, "Charge", "l"),
            (468, "Amount", "r"), (520, "Deposit", "r"), (572, "Balance", "r"),
            (580, "Move-In", "l"), (630, "Lease Start", "l"), (680, "Lease End", "l"),
            (724, "Exp. Move-Out", "l")]  # fmt: skip
    pages: list[Page] = []
    page: Page | None = None
    y = 0.0

    def start_page() -> None:
        nonlocal page, y
        page = Page(W, H)
        pages.append(page)
        page.text(36, H - 36, prop, 11, "F2")
        page.text(36, H - 50, "Rent Roll Detail - Month: October 2043", 9)
        page.right(W - 36, H - 36, f"Page {len(pages)} of 2", 8)
        y = H - 74
        for x, h, al in cols:
            (page.right if al == "r" else page.text)(x, y, h, size, "F2")
        y -= 4
        page.line(36, y, W - 36, y)
        y -= lead

    def put(i: int, s: str) -> None:
        x, _, al = cols[i]
        (page.right if al == "r" else page.text)(x, y, s, size)

    start_page()
    for k, u in enumerate(units):
        if k == 15:
            start_page()
        put(0, u["unit_number"])
        put(1, u["unit_type_code"])
        put(2, f"{u['unit_square_feet']:,}")
        put(3, u["unit_status"])
        put(4, u["resident_name"] or "VACANT")
        put(5, money(u["market_rent"]))
        put(8, money(u["deposit_held"]))
        put(9, signed_money(u["balance"]))
        put(10, _d(u["move_in_date"]))
        put(11, _d(u["lease_start_date"]))
        put(12, _d(u["lease_end_date"]))
        put(13, _d(u["expected_move_out_date"]))
        for j, (c, a) in enumerate(u["_charges"]):  # first charge line shares the unit line
            if j:
                y -= lead
            put(6, c)
            put(7, money(a))
        y -= lead
        put(6, "Charge Total")
        put(7, money(u["monthly_total_charges"]))
        y -= lead * 1.4
        assert y > 30, "rent roll page overflow"
    return pages, answer("rent_roll_units", "syn_rentroll_pdf", strip_private(units))


def strip_private(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def rentroll_xlsx(path: Path) -> dict:
    from openpyxl import Workbook

    period = dt.date(2043, 8, 15)
    prop = "Copperleaf Commons"
    units = rent_roll_units("CL", 24, period, SEED + 6, prop)
    wb = Workbook()
    params = wb.active
    params.title = "Report Parameters"
    for row in [
        ["Report", "Rent Roll Detail"], ["Property", prop], ["Month", "08/2043"],
        ["Include Future Residents", "No"], ["Include Charge Detail", "Yes"],
        ["Sort By", "Unit"], ["Printed By", "make_syn"],
    ]:  # fmt: skip
        params.append(row)
    ws = wb.create_sheet("Rent Roll")
    ws.append([prop])
    ws.append(["Rent Roll Detail", None, None, "Month: August 2043"])
    ws.append([])
    ws.append(["Unit", "Unit Type", "Sq Ft", "Unit Status", "Resident", "Market Rent",
               "Charge Code", "Scheduled Charge", "Deposit", "Balance", "Move In",
               "Lease Start", "Lease End", "Expected Move Out"])  # fmt: skip

    def as_date(s: str | None):
        return dt.date.fromisoformat(s) if s else None

    for u in units:
        ws.append([u["unit_number"], u["unit_type_code"], u["unit_square_feet"],
                   u["unit_status"], u["resident_name"], u["market_rent"], None, None,
                   u["deposit_held"], u["balance"], as_date(u["move_in_date"]),
                   as_date(u["lease_start_date"]), as_date(u["lease_end_date"]),
                   as_date(u["expected_move_out_date"])])  # fmt: skip
        for c, a in u["_charges"]:
            ws.append([None, None, None, None, None, None, c, a])
        ws.append([None, None, None, None, None, None, "Charge Total",
                   u["monthly_total_charges"]])  # fmt: skip
    for row in ws.iter_rows(min_row=5):
        for cell in row[10:14]:
            if cell.value is not None:
                cell.number_format = "mm/dd/yyyy"
    wb.properties.creator = "make_syn"
    wb.properties.created = dt.datetime(2020, 1, 1)
    wb.properties.modified = dt.datetime(2020, 1, 1)
    buf = io.BytesIO()
    wb.save(buf)
    path.write_bytes(normalise_zip(buf.getvalue()))
    return answer("rent_roll_units", "syn_rentroll_xlsx", strip_private(units))


# --------------------------------------------------------------------------------------------
# 7. syn_boxscore_csv: CSV with a header block, an availability table and a totals row
# --------------------------------------------------------------------------------------------


def boxscore_csv(path: Path) -> dict:
    rng = random.Random(SEED + 7)
    prop = "Larkspur Flats"
    end = dt.date(2043, 10, 17)
    types = [("LF-S1", "Studio Classic", 512), ("LF-S2", "Studio Loft", 588),
             ("LF-A1", "One Bed Garden", 702), ("LF-A2", "One Bed Corner", 768),
             ("LF-B1", "Two Bed Terrace", 1044), ("LF-B2", "Two Bed Flex", 1121),
             ("LF-C1", "Three Bed Villa", 1386)]  # fmt: skip
    rows = []
    for code, name, sqft in types:
        units = rng.randint(20, 60)
        model = rng.choice([0, 0, 1])
        down = rng.choice([0, 0, 1])
        admin = rng.choice([0, 0, 0, 1])
        vr, vu = rng.randint(0, 3), rng.randint(0, 4)
        nr, nu = rng.randint(0, 2), rng.randint(0, 3)
        occ = units - (model + down + admin + vr + vu + nr + nu)
        occupied = occ + nr + nu
        r = {
            "property_name": prop, "date": iso(end), "code": code, "name": name,
            "avg_sq_ft": sqft, "avg_rent": round(sqft * rng.uniform(1.7, 2.1), 2),
            "units": units, "occ_no_notice": occ, "vacant_rented": vr,
            "vacant_unrented": vu, "notice_rented": nr, "notice_unrented": nu,
            "avail": vu + nu, "model": model, "down": down, "admin": admin,
            "percent_occupied": round(occupied / units * 100, 2),
            "p_occ_wornonrev": round((occupied + model + admin) / units * 100, 2),
            "percent_leased": round((occ + vr + nr) / units * 100, 2),
            "p_trend": round((occupied + vr - nu) / units * 100, 2),
        }  # fmt: skip
        rows.append(r)
    heads = [
        "Code",
        "Name",
        "Avg. Sq Ft.",
        "Avg. Rent",
        "Units",
        "Occupied (no notice)",
        "Vacant - Rented",
        "Vacant - Unrented",
        "On Notice - Rented",
        "On Notice - Unrented",
        "Avail",
        "Model",
        "Down",
        "Admin",
        "% Occ",
        "% Occ w/NonRev",
        "% Leased",
        "% Trend",
    ]
    keys = [
        "code",
        "name",
        "avg_sq_ft",
        "avg_rent",
        "units",
        "occ_no_notice",
        "vacant_rented",
        "vacant_unrented",
        "notice_rented",
        "notice_unrented",
        "avail",
        "model",
        "down",
        "admin",
        "percent_occupied",
        "p_occ_wornonrev",
        "percent_leased",
        "p_trend",
    ]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Box Score"])
    w.writerow([f"{prop} (Phase II)"])
    w.writerow([f"Period: {dt.date(2043, 10, 11).strftime('%m/%d/%Y')} - {us(end)}"])
    w.writerow([])
    w.writerow(["Availability"])
    w.writerow(heads)
    for r in rows:
        out = []
        for k in keys:
            x = r[k]
            if k.startswith("p") and isinstance(x, float):
                out.append(f"{x:.2f}%")
            elif k == "avg_rent":
                out.append(f"${x:,.2f}")
            else:
                out.append(x)
        w.writerow(out)
    tot_units = sum(r["units"] for r in rows)
    tot = (
        ["Totals", ""]
        + [
            round(sum(r["avg_sq_ft"] * r["units"] for r in rows) / tot_units),
            f"${sum(r['avg_rent'] * r['units'] for r in rows) / tot_units:,.2f}",
        ]
        + [sum(r[k] for r in rows) for k in keys[4:14]]
        + ["", "", "", ""]
    )
    w.writerow(tot)
    w.writerow([])
    w.writerow(["Resident Activity"])
    w.writerow(["Move-Ins", "Move-Outs", "Renewals", "Notices"])
    w.writerow([rng.randint(2, 9), rng.randint(1, 7), rng.randint(3, 12), rng.randint(1, 8)])
    path.write_bytes(buf.getvalue().encode("utf-8"))
    return answer("boxscore", "syn_boxscore_csv", rows)


# --------------------------------------------------------------------------------------------
# 8. syn_loan_unseen: 3-page loan summary against an invented unseen field list
# --------------------------------------------------------------------------------------------

LOAN_SCHEMA = {
    "name": "syn_loan_summary",
    "description": "Summary of a commercial mortgage loan from a loan summary or term sheet. One "
    "entry per document. Dates in YYYY-MM-DD. Money as plain numbers. Where the document does "
    "not state something, the value is null.",
    "fields": {
        "lender_name": {"name": "Lender", "description": "Full legal name of the lender exactly "
                        "as written."},
        "borrower_name": {"name": "Borrower", "description": "Full legal name of the borrower "
                          "exactly as written, including the entity suffix."},
        "property_address": {"name": "Property Address", "description": "Street address of the "
                             "mortgaged property, including city, state and ZIP where given."},
        "loan_amount": {"name": "Loan Amount", "description": "Original principal amount of the "
                        "loan, as a number."},
        "interest_rate_pct": {"name": "Interest Rate", "description": "Annual fixed interest "
                              "rate as a percentage number exactly as printed (6.5 for 6.5%)."},
        "closing_date": {"name": "Closing Date", "description": "The date the loan closed or "
                         "was funded."},
        "maturity_date": {"name": "Maturity Date", "description": "The date the loan matures "
                          "and all principal is due."},
        "loan_term_months": {"name": "Loan Term (months)", "description": "Length of the loan "
                             "term in whole months. Compute it from the dates if not stated."},
        "amortization_years": {"name": "Amortization (years)", "description": "Amortization "
                               "period in years, as a number."},
        "monthly_payment": {"name": "Monthly Payment", "description": "Scheduled monthly "
                            "payment of principal and interest, as a number."},
        "annual_debt_service": {"name": "Yearly Loan Payments", "description": "Total scheduled "
                                "principal and interest payments for one year, as a number. "
                                "Compute it as the monthly payment times 12 if not stated."},
        "guarantor_name": {"name": "Guarantor", "description": "Full name of any guarantor of "
                           "the loan. null if no guarantor is named."},
    },
}  # fmt: skip


def loan_pdf() -> tuple[list[Page], dict]:
    amount, rate_pct, years = 14_250_000.00, 5.875, 30
    closing, maturity = dt.date(2040, 2, 16), dt.date(2045, 2, 16)
    r, n = rate_pct / 100 / 12, years * 12
    mp = round(amount * r / (1 - (1 + r) ** -n), 2)
    v = {
        "lender_name": "Ridgeway Mutual Life Assurance Society",
        "borrower_name": "Tamsin Court Owner, LLC",
        "property_address": "1020 Tamsin Court, Brookvale, CO 80612",
        "loan_amount": amount,
        "interest_rate_pct": rate_pct,
        "closing_date": iso(closing),
        "maturity_date": iso(maturity),
        "loan_term_months": 60,
        "amortization_years": years,
        "monthly_payment": mp,
        "annual_debt_service": round(mp * 12, 2),
        "guarantor_name": None,
    }
    f = Flow(header="Tamsin Court - Loan Summary (confidential)")
    f.heading("LOAN SUMMARY", 16)
    f.para("Prepared for the investment committee. Figures are as of the closing date.")
    f.heading("1. Parties")
    f.para("Lender: Ridgeway Mutual Life Assurance Society, a Connecticut mutual life office.")
    f.para("Borrower: Tamsin Court Owner, LLC, a Colorado limited liability company formed as "
           "a single-purpose entity.")  # fmt: skip
    f.para("Property: a 212-unit garden apartment community at 1020 Tamsin Court, Brookvale, "
           "CO 80612, built in 2009 and renovated in 2021.")  # fmt: skip
    f.heading("2. Key Terms")
    for t in [
        f"Original principal amount: ${money(amount)}.",
        f"Interest rate: {rate_pct}% per annum, fixed for the full term.",
        f"Closing / funding date: {long_date(closing)}.",
        f"Maturity date: {us(maturity)}. The loan term is five (5) years.",
        f"Amortization: {years}-year schedule, with no interest-only period.",
        "Loan-to-value at closing: 61.5% of the appraised value.",
        "Minimum coverage ratio: 1.25x, measured as the property's cash flow from operations "
        "over the last twelve months divided by the loan payments due in that period, tested "
        "once a year.",
    ]:
        f.para(t, indent=12)
    f.heading("3. Prepayment")
    f.para("The loan is locked out from prepayment for the first two loan years. "
           "Thereafter it may be prepaid in whole with yield maintenance; the final six months "
           "are open at par.")  # fmt: skip
    f.new_page()
    f.heading("4. Payments")
    f.para(
        f"Borrower shall pay monthly installments of principal and interest of "
        f"${money(mp)} on the sixteenth day of each month, beginning on March 16, 2040 and "
        "continuing until the maturity date, when the entire unpaid balance is due."
    )
    f.para("Payments are calculated on a 30/360 basis. A late charge of 4% applies to any "
           "installment more than ten days past due.")  # fmt: skip
    f.heading("5. Reserves")
    for t in [
        "Tax and hazard-policy escrow: monthly deposits of one-twelfth of the annual amounts.",
        "Replacement reserve: $250 per unit per year, collected monthly.",
        "Deferred maintenance holdback at closing: $186,400, released on completion.",
    ]:
        f.para(t, indent=12)
    f.heading("6. Covenants")
    for _ in range(3):
        f.para("Borrower shall deliver quarterly operating statements and rent rolls within "
               "forty-five days after each quarter end, and annual audited statements within "
               "one hundred twenty days after each fiscal year end. Transfers of direct or "
               "indirect interests above 49% require Lender consent.")  # fmt: skip
    f.new_page()
    f.heading("7. Other Terms")
    for _ in range(3):
        f.para("The loan is non-recourse to Borrower subject to customary carve-outs for fraud, "
               "misapplication of funds, environmental indemnity and voluntary bankruptcy. "
               "Lender may assign or participate the loan without Borrower consent. The loan "
               "documents are governed by Colorado law.")  # fmt: skip
    f.heading("8. Committee Notes")
    f.para("Approved subject to receipt of the final title policy and the environmental "
           "report dated within ninety days of closing.")  # fmt: skip
    return f.pages, v


# --------------------------------------------------------------------------------------------
# deterministic zips and the driver
# --------------------------------------------------------------------------------------------


def normalise_zip(blob: bytes) -> bytes:
    """Rewrite an Office zip with fixed entry times and fixed core-property dates."""
    src = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = re.sub(
                    rb"(<dcterms:(created|modified)[^>]*>)[^<]*(</dcterms:\2>)",
                    lambda m: m.group(1) + FIXED_ISO.encode() + m.group(3),
                    data,
                )
            zi = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            dst.writestr(zi, data)
    return out.getvalue()


DOCS = [
    ("syn_lease_text", "pdf", "lease_abstraction",
     "8-page text lease; clauses spread across pages; amendment changes rent and deposit"),
    ("syn_lease_scan", "pdf", "lease_abstraction",
     "15 scanned pages (images only, slight rotation and grain); filled-in form on pages 9-14; "
     "rider on page 15 changes the deposit"),
    ("syn_lease_docx", "docx", "lease_abstraction", "DOCX lease with one rent table"),
    ("syn_budget_pdf", "pdf", "budget_variance",
     "3-page budget table; repeated header; subtotals; wrapped commentary column"),
    ("syn_rentroll_pdf", "pdf", "rent_roll_units", "30 unit blocks over 2 pages"),
    ("syn_rentroll_xlsx", "xlsx", "rent_roll_units",
     "parameters sheet first, report sheet second; unit blocks with charge lines"),
    ("syn_boxscore_csv", "csv", "boxscore", "header block, availability table, totals row"),
    ("syn_loan_unseen", "pdf", "syn_loan_summary",
     "3-page loan summary; unseen field list; one computed field; one absent field"),
]  # fmt: skip


def build(out: Path) -> list[Path]:
    docs_dir, ans_dir, sch_dir = out / "documents", out / "answers", out / "schemas"
    for d in (docs_dir, ans_dir, sch_dir):
        d.mkdir(parents=True, exist_ok=True)
    answers: dict[str, dict] = {}

    pages, v = lease_text()
    write_pdf(pages, docs_dir / "syn_lease_text.pdf", "Office Lease")
    answers["syn_lease_text"] = answer("lease_abstraction", "syn_lease_text", [v])
    pages, v = lease_scan()
    write_pdf(pages, docs_dir / "syn_lease_scan.pdf", "Scanned lease")
    answers["syn_lease_scan"] = answer("lease_abstraction", "syn_lease_scan", [v])
    v = lease_docx(docs_dir / "syn_lease_docx.docx")
    answers["syn_lease_docx"] = answer("lease_abstraction", "syn_lease_docx", [v])
    pages, a = budget_pdf()
    write_pdf(pages, docs_dir / "syn_budget_pdf.pdf", "Budget Analysis Report")
    answers["syn_budget_pdf"] = a
    pages, a = rentroll_pdf()
    write_pdf(pages, docs_dir / "syn_rentroll_pdf.pdf", "Rent Roll Detail")
    answers["syn_rentroll_pdf"] = a
    answers["syn_rentroll_xlsx"] = rentroll_xlsx(docs_dir / "syn_rentroll_xlsx.xlsx")
    answers["syn_boxscore_csv"] = boxscore_csv(docs_dir / "syn_boxscore_csv.csv")
    pages, v = loan_pdf()
    write_pdf(pages, docs_dir / "syn_loan_unseen.pdf", "Loan Summary")
    answers["syn_loan_unseen"] = answer("syn_loan_summary", "syn_loan_unseen", [v])

    (sch_dir / "syn_loan_summary.json").write_text(
        json.dumps(LOAN_SCHEMA, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for doc_id, a in answers.items():
        (ans_dir / f"{doc_id}.json").write_text(
            json.dumps(a, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    with (out / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["document_id", "file", "schema_name", "kind", "notes"])
        for doc_id, ext, schema, notes in DOCS:
            w.writerow([doc_id, f"{doc_id}.{ext}", schema, ext, notes])
    return sorted(p for p in out.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="build twice into temp folders and compare bytes")  # fmt: skip
    args = ap.parse_args(argv)
    if args.check:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            fa, fb = build(Path(a)), build(Path(b))
            rel_a = [p.relative_to(a) for p in fa]
            rel_b = [p.relative_to(b) for p in fb]
            same = rel_a == rel_b and all(
                filecmp.cmp(Path(a) / r, Path(b) / r, shallow=False) for r in rel_a
            )
            print(f"{len(rel_a)} files; identical bytes across two builds: {same}")
            return 0 if same else 1
    files = build(args.out)
    for p in files:
        print(f"{p.relative_to(ROOT).as_posix()}  {p.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
