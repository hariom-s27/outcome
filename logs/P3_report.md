# P3 report — proper readers, one document map, baseline re-run

Sessions: S1 free spikes (`logs/P3_spikes.md`), S2 readers + map + eval (this file).
Doc ids, field names, counts and scores only (D04, R31).

## PLAIN SUMMARY

- **Readers rebuilt.** XLSX/CSV, DOCX and PDF now all produce one *document map*: an ordered list
  of blocks with the same fields (`block_id, kind, text, address, page, flags`).
  - XLSX: two loads (cached values + formulas); hidden sheets/rows/columns, merged ranges and
    formulas without a cached value are flagged; keys with leading zeros and dates are shown as
    Excel displays them.
  - CSV: UTF-8 → UTF-16 (BOM) → cp1252; delimiter sniffed, comma fallback flagged.
  - DOCX: XML walker in body order with numbering labels, accepted view of tracked changes,
    text boxes (read once), content controls, tables (merged cells flagged), tab pseudo-tables,
    strike-through flagged, headers/footers tagged.
  - PDF: pdfplumber words → lines → blocks; boxed callouts kept whole, header/footer tagged,
    "fake bold" deduplicated, split numbers joined; scanned pages → grayscale JPEG.
- **DOCX pages default to "none".** The "estimate" method put 0/20 findable lease_002 citations on
  the exact page (13/20 within ±1), below the 80% gate. A slim LibreOffice image (A11) gave
  23 pages and 0/20; the fuller-font image from S1 gave 40 pages and 20/20. → P8 decision.
- **Token estimate per block kind** (rows 1.6, prose 2.66 chars/token): om_001 estimate 20,186 vs
  real 20,169 tokens.
- **Score: DEV mean 0.579 vs P2 0.599** (n = 6). Below P3-21's bar, so the **P2 outputs are kept**.
- **One bug found and fixed:** in the first P3 run om_001 fell to 0.172 (answer and repair both
  unparseable). New PDF blocks keep line breaks; a model copying a block verbatim into a JSON
  string can write a raw newline, which strict JSON rejects. Every block is now rendered on one
  line. om_001 re-run: 0.948.
- **Spend this phase $0.019822; RUNNING TOTAL $0.127749.**

## Where it got worse

| doc | P2 (`455cb6d-dirty`, best) | P3 final (`a97a79a-dirty`) | change |
|---|---|---|---|
| boxscore_001 | 1.000 | 1.000 | 0 |
| lease_001 | 0.700 | 0.700 | 0 |
| lease_002 | 0.775 | 0.775 | 0 |
| om_001 | 0.966 | 0.948 | −0.018 |
| t12_001 | 0.046 | 0.046 | 0 |
| **rentroll_001** | 0.110 | **0.006** | **−0.103** (> 0.05) |
| **mean** | **0.599** | **0.579** | −0.020 |

- rentroll_001: the model returned 2 of 325 rows (P2: 36). P2's two rent-roll runs already
  scored 0.009 and 0.110 with the same reader shape, so this is mostly run-to-run noise of the
  one-call baseline on a truncated 3,000-row sheet (60k-token cap; A8 work is P6, PR-01).
- om_001: −0.018 (2 wrong cells) after the fix; one sample, not investigated further.
- boxscore_001, lease_001 and t12_001 were answered from the dev cache: their prompts are
  byte-identical to P2's, so the readers changed nothing they send.

## SELF-AUDIT

### 1. Steps done (evidence)

| Part | Evidence |
|---|---|
| B XLSX/CSV readers | `app/readers/xlsx_reader.py`, `csv_reader.py`; tests below |
| C DOCX reader + page methods | `app/readers/docx_reader.py` (`docx_pages`, `PAGE_METHODS`); `scripts/spikes/a3b_docx_estimate.py` |
| C A11 slim LibreOffice | `scripts/spikes/a11_libreoffice_slim.py`; numbers in §4 |
| D PDF reader | `app/readers/pdf_reader.py` |
| E map, ratios, dump | `app/readers/base.py`, `config/models.yaml`, `app/llm/models.py` (`Estimate.kind_ratios`), `scripts/dump_docmap.py` → `logs/P3_docmaps.md` |
| STOP 1 | Hariom committed 54e11f0, b66a261, 76a3686, 2069779, a97a79a |
| F eval | `eval/history.jsonl` (2 P3 lines), `logs/P3_eval.md` |
| om_001 diagnosis + fix | `scripts/debug_one_doc.py`, `Block.render()` one-line, test `test_multiline_pdf_block_copied_verbatim_into_json_still_parses` (fails without the fix, passes with it) |
| eval tooling | `scripts/eval_dev.py` `--report` (default `logs/eval_latest.md`), `--reuse-from` |

### 2. Decisions not in the prompt

- **Block kinds** `row, table_row, paragraph, callout, image`; token class row (row, table_row),
  prose (paragraph, callout). Alternative: one "text" kind (loses the per-kind ratio).
- **Fuse gets per-kind chars** via a `kind_chars` argument through `projection`,
  `complete_json` and `chat`, so the pre-call fuse and the baseline cap use the same numbers.
  Alternative: guess classes from the message text (fragile).
- **Mixed-page threshold** image share > 30% (A6 used it); scan = < 50 chars and > 50% (P3-15).
- **PDF parse safety:** per-page fallback to pypdfium2 text (flag `layout_fallback`) on any
  layout error (error type counted in map meta), plus a 90 s whole-document layout budget.
  Not a hard, killable timeout (see §10, PR-71).
- **White text** flagged `invisible_text` (still sent); om_001 has 11 such blocks.
- **DOCX estimate without app.xml Pages** uses a page count from page size, margins and default
  font size; the in-segment position is character-proportional as specified.
- **lxml** used directly (already installed through python-docx), with
  `resolve_entities=False, no_network=True` for `docProps/app.xml`; no new dependency.
- **`DOCX_PAGE_METHOD`** passed to the worker in `compose.yaml` (default `none`) and documented in
  `.env.example`.
- **One-line block rendering** (`" / "` between lines) as the om_001 fix, in the prompt builder;
  the map keeps the line breaks.
- **`--reuse-from`** in eval_dev.py to run only om_001 live and re-score the other 5 saved results
  (Hariom's item 3 needed it; the script had no such mode).
- **Extra files read:** `app/llm/models.py`, `app/llm/client.py`, `app/worker.py`,
  `app/schema.sql` (llm_calls table), `tests/test_readers.py`, `tests/test_baseline.py`,
  `tests/test_eval_dev.py`, `compose.yaml`, `compose.dev.yaml`, `.env.example`,
  `scripts/spikes/a4_libreoffice.py`, `sample/manifest.csv` (om_001 row), `README.md`,
  `DESIGN.md` (score/spend sections).

### 3. Deviations

- `app/worker.py` was edited once with a short Python one-off, not Edit/Write (3 lines).
- DOCX commit subject shortened to fit 72 chars.
- The final eval history line is `a97a79a-dirty`, not a clean SHA: the om_001 fix was uncommitted
  at run time (item 3 ordered the re-run before the final commits). The first P3 run is clean
  (`a97a79a`, mean 0.450).
- `logs/P3_eval.md` holds the final run (om_001 live + 5 reused); the first run's per-doc numbers
  are in `eval/history.jsonl` and in this report.
- `logs/P2_eval.md` was overwritten by the first P3 run (eval_dev.py had the path hard-coded);
  restored with `git restore` (Hariom's item 1); fixed by `--report`.
- `git add -N` (intent-to-add) used so pre-commit checks untracked new files; `git stash` /
  `stash pop` used once to show the new test fails without the fix (no commit, no reset).
- Two guard blocks, both stopped and reported: `printenv` in a psql command (correct block), and
  a false positive on `cache\|` inside a grep pattern (**PR-70**).

### 4. Numbers with their source

| number | source |
|---|---|
| DEV mean 0.450 (first run), per-doc | `eval/history.jsonl` run `a97a79a` |
| DEV mean 0.579 (final), per-doc | `eval/history.jsonl` run `a97a79a-dirty`, `logs/P3_eval.md` |
| P2 mean 0.599 | `eval/history.jsonl` run `455cb6d-dirty` (second line) |
| $/doc uncached 0.00492 (final) | `logs/P3_eval.md` |
| estimate 0/20 exact, 13/20 ±1, 32 estimated pages, 21 hard breaks | `scripts/spikes/a3b_docx_estimate.py` output (cache/spikes) |
| A11: base 25 s / 395 MB; +slim LO 260 s / 872 MB (+478 MB, +235 s); 23 pages; 0/20; conversion 4 s | `scripts/spikes/a11_libreoffice_slim.py` output |
| block counts per doc | `logs/P3_docmaps.md` |
| om_001 debug: 199 blocks (195 paragraph, 3 callout, 1 image), est 20,186 vs real 20,169, finish stop, parse ok, no repair, 0 contract errors | `scripts/debug_one_doc.py` stdout |

A11 cold-build delta (+235 s) is far above A4's +45 s on the same host; network/apt mirror speed
is the likely cause, so P8 should re-time it on a cold machine.

### 5. Tests

- Before P3 S2: 178 (HEAD 9726292). New: 12 (test_readers 10 → 18 incl. parametrised,
  test_baseline 18 → 20, test_eval_dev +2). Final pytest: `190 passed, 1 warning,
  82 subtests passed in 29.98s`. Failures: 0. No network, no key (conftest blocks sockets).
- ruff check: all passed; ruff format: 77 files already formatted; pre-commit `--all-files`
  (new files intent-to-add): all 7 hooks Passed.

### 6. Frozen items, validity, fresh stack

- `contract/`, `tools/validate.py`, `ASSIGNMENT.md`, `sample/` untouched (pre-commit frozen-file
  hash check passed).
- `tools/validate.py outputs/ --schema-dir sample/schemas`: exit 0; single-file mode: 8/8 VALID.
- `outputs/` unchanged (P2 outputs kept, P3-21).
- `docker compose --env-file .env.example up -d` (blank LLM values): `/health` 200, worker log
  "LLM_API_KEY not set … (PARTIAL), R17" and `pipeline=stub`.

### 7. Held-out seal

- lease_003 / budget_001 never read; every new script refuses them in code. Answers were read
  only inside `a3b_docx_estimate.py` and `a11_libreoffice_slim.py` (counts printed) and by
  eval_dev.py's scorer.

### 8. Safety

- No commit, push, reset or rebase. `.env` not opened, no env value printed. No key in any file.
  Both guard blocks reported, not worked around. No sample or answer value in logs, tests or
  messages; tests use invented data.

### 9. LLM calls (all anthropic/claude-haiku-5.5, through LLM_BASE_URL)

| run | paid calls | tokens in / out | cost |
|---|---|---|---|
| DEV eval `a97a79a` (3 dev-cache hits at $0) | 4 (lease_002 1, om_001 2, rentroll 1) | 100,984 / 8,040 | $0.014118 |
| om_001 debug (fresh, cache off, $0.01 cap) | 1 | 20,169 / 1,695 | $0.002864 (computed) |
| om_001 re-run `a97a79a-dirty` | 1 | 20,287 / 1,615 | $0.002840 |
| **P3 total** | **6** | | **$0.019822** |

Reported = computed for both eval runs (eval_dev.py output); the debug call is computed from its
usage at the YAML price. Uncached $/doc (final run) 0.00492.
**RUNNING TOTAL = $0.107927 (P2, history) + $0.019822 = $0.127749** (DEV budget $8).

### 10. Risks and open items for P4

- **PR-70** guard false positive: `cache\` inside a grep pattern counts as a path into the cache.
- **PR-71** PDF parse has a soft time budget, no hard per-page timeout or process isolation
  (R20 asks for killable processes); a pdfminer hang would stall the job until the lease expires.
- **PR-72** om_001's first-run failure was diagnosed from its shape, not its raw text (no cache
  reads); one fresh call parsed fine. If unparseable answers recur, consider `strict=False` in
  the JSON parser as a second guard.
- **PR-01** (A8) rent-roll row recovery and the 60k cap: rentroll still 2/325 rows; P6.
- **PR-02** (A7) wrong cells are wording, not format: P5.
- DOCX page method: decide `libreoffice` at P8 with cold-machine timing; the font set changes
  the page count (23 vs 40 pages), so the fuller font set is the candidate.
- Temporary images still to remove: `docker image rm docextract-spike:lo-slim docextract-spike:base`.

### S1 summary (merged from `logs/P3_spikes.md`)

Spreadsheets clean (no uncached formulas, no hidden sheets); lease_002 has no page markers (A3
0%); lease_001 is a 25-page scan, 1600 px renders keep the detail; om_001 values all in the text
layer (no layout model); P2 wrong cells are wording; chars/token rows 1.78, prose 2.96; all
packages have aarch64 wheels.
