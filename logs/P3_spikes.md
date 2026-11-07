# P3 spikes — Session 1 (free measurements, $0, no LLM calls)

Scripts: `scripts/spikes/` (one per item; `_common.py` refuses held-out ids; answers read inside
scripts only). Full outputs: `cache/spikes/<name>.txt` (git-ignored). Below: summaries only —
doc ids, field names, column letters, counts. No document or answer values.

## PLAIN SUMMARY

- Spreadsheets are clean: no formulas without a cached value, no hidden sheets/rows; a few
  merged ranges. A simple "record starts where column A is filled" rule finds exactly the
  t12_001 row count (119/119) and over-counts rentroll_001 by 30 on its unit sheet (355 vs 325).
- lease_002 (DOCX) has **no** rendered page markers and its 22 section breaks do not match the
  answer pages (up to 33): marker-based page numbers agree on **0%** of fields. So A4 ran.
- LibreOffice gets every locatable citation on the right page (20/20; 69% of all 29 because 9
  citations are not verbatim text) for +474 MB image and +45 s cold build. P3-13 needs a call.
- lease_001 is a 25-page scan with no text layer; embedded page images are 200 DPI, so
  rendering at 1600 px gives the same information (no gain from extracting them).
- om_001: every non-null answer value (24/24) is findable in its cited page's text layer; no
  charts (0 curves), 192 rectangles on 15 pages; only page 1 is image-only.
- P2's 23 "wrong" cells are not formatting noise: 0 case/whitespace/punctuation-only, 10 other,
  6 numeric-looking strings, 4 different numbers, 2 truth-inside-prediction, 1 different date.
- Real chars/token: sheet rows ≈ 1.78, prose ≈ 2.96 (P2 used one 1.5 estimate).
- Every runtime package plus pdfplumber + pdfminer.six has a linux/aarch64 wheel (31/31).

## A1 — Formula cells (spike 9)

| doc | sheets | hidden sheets | formula cells | with cached value | without | merged ranges | hidden rows |
|---|---|---|---|---|---|---|---|
| rentroll_001 | 2 | 0 | 408 | 408 | 0 | 2 | 0 |
| t12_001 | 1 | 0 | 0 | 0 | 0 | 4 | 0 |

No hidden columns on any sheet (per-sheet detail in the full output). The `data_only` read
already sees every formula result on DEV; a formula-without-cache flag is still needed for
unseen files (P3-10) but has no DEV case.

## A2 — Embedded images vs rendering (spike 14)

| doc | pages | page kinds | sharper at 1600 px |
|---|---|---|---|
| lease_001 | 25 | 25 full-page images | same on 25 (native 2805 px long side, 200 DPI; render 114 DPI) |
| om_001 | 22 | 1 full-page image, 11 partial images, 10 no image | same 1, embedded 11, render 10 |

om_001 partial images have 187–274 DPI vs 145 DPI render: a crop would be sharper, but A6 shows
no answer value depends on image-only content. **Verdict: keep the P2 render path (P3-16);
embedded extraction gives no gain for scans and is not needed for om_001.**

## A3 — DOCX pages (spike 19, C16)

lease_002: `w:lastRenderedPageBreak` = 0, explicit page breaks = 0, section breaks = 22,
docProps/app.xml `Pages` = absent. Implied pages: rule A (rendered markers) = 1, rule B
(markers + page-type section breaks) = 22. Answer pages go up to 33.

Fields with page numbers: 29. Cited text found in the DOCX: 20 (not found: 9 — property_name,
lease_execution_date, lease_expiration_date, rent_schedule_start_dates, rent_schedule_end_dates,
rent_schedule_monthly_rent, rent_schedule_annual_rent_per_rsf, total_base_rent,
base_rent_escalation). **Agreement: rule A 0/29 = 0%, rule B 0/29 = 0%.** Rule B offsets
(computed − answer): −2 ×13, −3 ×1, −9 ×1, −10 ×1, −13 ×1, −15 ×2, −16 ×1.
The file was not saved by Word (no rendered markers, no Pages count), so markers cannot work.

## A4 — LibreOffice (spike 20)

Run because A3 < 90%. Temporary Dockerfile = current one + `libreoffice-writer-nogui`,
`fonts-liberation`, `fonts-dejavu-core` (under cache/, not committed). Cold builds (`--no-cache`,
base layer already pulled, x86_64 host):

| image | cold build | size |
|---|---|---|
| current | 27 s | 354 MB |
| + LibreOffice | 73 s | 828 MB (**+474 MB, +45 s**) |

Extra measurement (free, same image): lease_002 → PDF in the container (`--network none`, only
that file mounted read-only): 40 pages, 5 s including container start. Page of each cited text
in the PDF vs the answer: **20/29 = 69% overall, 20/20 = 100% of the citations found**; the
9 misses are the same 9 fields whose citation text is not verbatim in the document (A3), so
they are a text-matching limit, not a page error.

## A5 — Lease structure (spike 22)

- lease_002: 208 non-empty paragraphs; heading-like parts by type: exhibit 1, no
  summary/rider/amendment/memo headings found; signature blocks by "in witness whereof" or
  "By:" lines: 0; tracked changes: 0 insertions, 0 deletions, 0 moves; tables 0, text boxes 0,
  header/footer parts 9, no footnotes, no comments.
- lease_001: 25 pages, 25 without a text layer → scanned, no text layer (no OCR run).
- Heading rules are simple keyword rules; counts are a floor. Amendment handling (CD79–CD80)
  has no DEV case.

## A6 — OM layout (spike 24)

om_001: 22 pages — text 13, mixed (image area > 30%) 8, scan-like 1 (page 1: < 50 text chars,
image > 50%). Rectangles 192 on 15 pages; curved paths 0 on every page (no vector charts).
Non-null answer fields: **findable in the cited page's text layer 24, not findable 0**.
→ No layout model needed for om_001 (C19); triage thresholds of P3-15 put only page 1 on the
image path, and no answer depends on it.

## A7 — Scorer rules (PR-02)

How `score()` in tools/validate.py compares (plain words):

- **Null**: None, "", "null", "none", "n/a", "na", "-", "--" are null. Both null = right; one
  null = wrong (hallucination or miss).
- **Booleans**: true/false, or text yes/y/true and no/n/false (any case). Exact.
- **Numbers**: numbers, or text after removing `$ € £ ₹` and commas; `(x)` is negative; a
  trailing `%` is dropped **without dividing by 100** ("5%" = 5, not 0.05). Rounded to 2 dp;
  right if within max(0.01, 0.5% of the truth).
- **Dates**: text parsed with a fixed list of formats into an ISO date; exact date match.
- **Text**: lower-case, all punctuation removed, whitespace collapsed; then exact equality.
  **No fuzzy threshold** — any word difference is wrong.
- **Mixed kinds** (e.g. number vs text): equal only if their normalised forms print the same.
- **Lists**: F1 with one-to-one greedy matching using the scalar rules; a scalar prediction
  against a list truth counts as a one-item list.
- **Rows**: with a primary key in the schema, rows are matched by the normalised key (first
  duplicate wins); unmatched truth rows (missing) and unmatched predicted rows (extra) score 0
  on every field and stay in the averages. Without a key, rows match by position.
- Document score = mean over fields of each field's mean cell score.

P2 wrong cells (run `455cb6d-dirty`), 23 in total: other 10, number_format 6, number_value 4,
truth_in_pred 2, date_value 1; case_only 0, ws_punct_only 0, pred_in_truth 0.

| doc | fields (count × class) |
|---|---|
| t12_001 | property_name 6×number_format (one side a numeric-looking string) |
| rentroll_001 | market_rent 2×number_value, balance 1×number_value |
| lease_001 | electricity_provision, early_termination_right, right_to_sublet, late_fee, holdover_rent: 1×other each |
| lease_002 | property_name, building_address, right_to_sublet, late_fee, holdover_rent: 1×other each; permitted_use 1×truth_in_pred; rent_commencement_date 1×date_value; total_base_rent 1×number_value |
| om_001 | submarket 1×truth_in_pred |

→ Formatting-only fixes would win at most a handful of cells; text fields must match the
document's wording exactly (no paraphrase), which is a P5 prompt/normaliser concern.

## A8 — Table structure (PR-01)

| doc / sheet | header rows | data region | data / section / total / blank rows | record-start col | records vs answer rows |
|---|---|---|---|---|---|
| t12_001 #0 | 0 detected | rows 1–148 | 121 / 5 / 22 / 0 | A | 119 vs 119 |
| rentroll_001 #0 | 1 (row 7) | rows 8–3058 | 2706 / 2 / 340 / 3 | A | 355 vs 325 |
| rentroll_001 #1 | 0 | rows 1–22 | 17 / 2 / 1 / 2 | A | 17 (not a unit table) |

Column roles (guessed from values, counts = non-empty data cells):
- t12_001: A key(119), B key(119), C–R amount (≈100 each) — label/code columns then 16
  amount columns.
- rentroll_001 #0: A key(355), B label, C amount, D label, E key, F int, G code, H label(2681),
  I amount(2681), J–K amount, L–N date, O date(21), P key(2632), Q label(2631); S–AM a small
  side block of 14–23 rows (likely a summary table, not units).
- One record per unit spans many rows (charge lines in H/I/P/Q); column A marks the start.

→ Rule over-counts rentroll by 30 (≈9%) and the second sheet must not be read as units; the
S–AM side block and total rows need excluding (P5/P6 table spec, outside P3 scope per P3-26).

## A9 — Token ratios (PR-06)

| doc | kind | text chars (blocks / other) | tokens_in (P2) | chars/token | note |
|---|---|---|---|---|---|
| boxscore_001 | sheet | 2458 / 3394 | 0 | – | 0 model calls saved |
| lease_001 | prose | 0 / 7933 | 19106 | – | 8 images, truncated |
| lease_002 | prose | 74370 / 7541 | 27641 | 2.96 | clean |
| om_001 | prose | 28083 / 4378 | 17738 | (1.83) | 1 image inside |
| t12_001 | sheet | 34232 / 2922 | 21834 | 1.70 | clean |
| rentroll_001 | sheet | 100347 / 3284 | 57118 | 1.81 | truncated (prefix exact) |

Per kind (whole prompt incl. ~3–8k chars of instructions): **sheet rows 1.78 chars/token**
(2 docs), **prose 2.96** (1 doc). With the P3-18 10% margin: sheet 1.6, prose 2.65.
Only one clean prose doc — treat the prose number as provisional.

## A10 — ARM wheels (spike 25)

`uv export --no-hashes --no-dev` (1 Windows-only package skipped) + pdfplumber, pdfminer.six,
charset-normalizer, cryptography: **31 packages, 31 wheels for linux aarch64 / CPython 3.12**
(23 pure Python, 8 aarch64 binaries). No aarch64 wheel: none. pdfplumber 0.11.10 and
pdfminer.six 20260107 are pure Python.

## What Session 2 should do

- XLSX reader: openpyxl twice as P3-10; keep the formula-without-cache flag but expect none on DEV (A1); record merged ranges (A1: 2 and 4).
- CSV reader: stdlib csv as P3-11 (no new evidence needed).
- DOCX reader: XML walker (P3-12); A5 found no tracked changes, tables or text boxes on DEV, so tests must cover them with generated fixtures.
- DOCX pages (P3-13): markers fail (A3 0%) → STOP and decide with A4 numbers (A4: LibreOffice 20/20 on found citations, +474 MB, +45 s cold build, 5 s per conversion) — Hariom's call before S2 builds the DOCX page path.
- PDF reader: pypdfium2 + pdfplumber (P3-14, P3-22); arm64 is fine (A10).
- Page triage (P3-15): text < 50 chars and image > 50% puts only om_001 p1 and all lease_001 pages on the image path; no om_001 answer needs it (A6).
- Scan images (P3-16): keep the P2 1600 px render; embedded images are no sharper at that budget for full-page scans (A2).
- Token estimate (P3-18): sheet 1.6, prose 2.65 chars/token after the 10% margin (A9).
- Out of scope but measured: rentroll record rule over-counts by 30 and the S–AM side block (A8); wrong cells are wording, not format (A7).
