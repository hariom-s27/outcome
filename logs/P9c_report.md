# P9c report: E4 PDF tables via line grid + recipe (Z-40..Z-49)

Branch `lab`. Stack: lab defaults, E0 on, `LAB_MODE=1`, `LLM_CACHE_MODE=off`, `PDF_TABLE_METHOD=grid`
(worker start line: `cache_mode=off, lab_mode=on, e0_robust=on, pdf_table=grid`). Code at `1b3f22f`.

## PLAIN SUMMARY

**Final state on lab (after Z-50, Z-59, Z-60):**
- **`PDF_TABLE_METHOD` default `grid`.**
  - Gate passed with Z-50: hallucinations counted on paired cells.
  - Full-set run 144 passed.
- **`TABLE_CLEANUP` default on.**
  - Targeted-fix gate passed (runs 154–156).
  - Z-60 cleared the run-157 t12 collapse: it happened before the cleanup ran (cleanup changed 0
    cells), and the same collapse occurs with cleanup off (run 164).
- **Results.** syn_budget_pdf and syn_rentroll_pdf both reach 1.000 with both switches on.
- **Residual risks.**
  - t12_001's recipe can collapse when E0's retry also fails.
  - The cleanup has one false-positive cell per t12 run.
- P9c spend $0.0884; lab ≈ $0.488.

The sections below record each step in order.

- **What changed.** A text-layer PDF table is now turned into a grid of lines and columns, a "virtual
  spreadsheet". It goes through the existing spreadsheet recipe path. The model names the columns
  once; code copies every row and writes every citation and page number. The switch is
  `PDF_TABLE_METHOD`, default `single` (v1.0).
- **Result.** On the two SYN PDF tables the grid recovers every row in all 3 live runs:
  - budget: 43/43 rows, score 0.016 → 0.987
  - rent roll: 30/30 rows, score 0.044 → 0.986
  - 1 LLM call per doc, about $0.0008/doc, no fallback
- **Gate: FAIL**, on one check. The rent roll has 7 hallucinated cells per run against 0 in the
  base. All 7 are `resident_name` on vacant units: code copies a placeholder word the PDF prints
  there, where the truth is null. The base had 0 hallucinations only because it returned 1 row.
- **Decision.** As pre-registered (Z-47):
  - no full `--set all` run
  - `PDF_TABLE_METHOD` stays `single` on lab
  - The switch ships off. Whether to amend the gate or add a placeholder rule is Hariom's call
    (see Decision).
- **Spend.** P9c $0.00496; lab total ≈ $0.405 of the $3 cap.

## Part 0 — cause check (Z-46; SYN metadata only, held-out docs never read)

From the history lines and committed eval reports (raw runs live under `cache/`, not opened).

| run | doc | route | rows | flags | $/doc | latency |
|---|---|---|---|---|---|---|
| 101 | syn_budget_pdf | baseline | 1/43 | none | 0.00096 | 5.3 s |
| 102 | syn_budget_pdf | baseline | 1/43 | none | 0.00088 | 4.8 s |
| 101 | syn_rentroll_pdf | baseline | 1/30 | truncated_output | 0.00457 | 24.5 s |
| 102 | syn_rentroll_pdf | baseline | 1/30 | truncated_output | 0.00457 | 26.7 s |

- **Rent roll: a cut-off.** The output hits the 8,192-token cap in 4 of 5 v1.0 runs (101, 102, 104,
  105). Run 106 was not cut off but still returned 2/30 rows.
- **Budget: not a cut-off.** No flag in any run (101, 102, 104–106). The P9a report records
  ≈ 660–820 output tokens against the 8,192 cap. The model stops after one row by itself; the
  reason is not visible from metadata.
- **Outcome.** The STOP rule ("neither doc cut off") was not met, so Part A was built. The grid
  route covers both causes, because the model writes no rows.

## Build (Part A, $0)

- [app/tables/pdf_grid.py](../app/tables/pdf_grid.py) builds the grid:
  - words (pdfplumber, already a dependency, Z-43) → physical lines with ids `P<page>L<nnn>` →
    segments
  - table header from the line scoring, with 2-row headers merged
  - repeated headers and page header/footer lines skipped
  - column bands from whitespace rivers; wrapped text joined to its row
  - output as `row` blocks of a virtual sheet `Table`, which `profile_blocks` and the spec path
    read unchanged
- `table_spec.extract(..., pdf_grid=...)` runs the existing spec path, then the Z-45 checks:
  - rows ≥ 1
  - unique normalised keys
  - completeness: every key-shaped grid line became a row
  - numeric fields parse
  - plus the output contract
- On a check failure: another already-built recipe that passes ($0), then one E0 spec call (only
  if E0 has not already made its call), then the v1.0 call for that job. Citations are rewritten
  to the contract's `[Page N] …` with `page_numbers`.
- The worker builds the grid only when the switch is `grid`, the field list is a table, and the
  PDF has no scanned page (Z-48). At `single` it passes nothing new: the v1.0 call exactly
  (shipped-config test plus `test_default_single_is_the_v1_call`).
- Tests: `tests/test_p9c.py`, 22 tests:
  - multi-page table with the header repeated
  - wrapped comment joined to its row
  - total line excluded
  - page footer skipped
  - 2-row header, and a label wider than its column
  - duplicate keys fail the checks
  - check failure → E0 retry → fallback `single`
  - no retry when E0 already made its call
  - default `single` makes the v1.0 call
  - switch parsing
  - scanned PDF keeps the v1.0 path
  - worker passes the grid only when switched on

  Full suite at STOP 1: 683 passed.

## Part B — live runs (Z-47)

Commands: `eval_dev.py --set syn --docs syn_budget_pdf syn_rentroll_pdf --expect-live --run-index
141|142|143 --max-usd 0.05`. All jobs live (`cache_mode=off`, 0 replays), all VALID.

### Per run: recipe used and checks

| run | doc | recipe used | LLM calls | checks failed | fallback v1.0 | score | rows p/t | $/doc |
|---|---|---|---|---|---|---|---|---|
| 141 | syn_budget_pdf | LLM recipe (`grid:ai`), first call | 1 | none | no | 0.987 | 43/43 | 0.00086 |
| 141 | syn_rentroll_pdf | LLM recipe (`grid:ai`), first call | 1 | none | no | 0.986 | 30/30 | 0.00081 |
| 142 | syn_budget_pdf | LLM recipe (`grid:ai`), first call | 1 | none | no | 0.987 | 43/43 | 0.00084 |
| 142 | syn_rentroll_pdf | LLM recipe (`grid:ai`), first call | 1 | none | no | 0.986 | 30/30 | 0.00081 |
| 143 | syn_budget_pdf | LLM recipe (`grid:ai`), first call | 1 | none | no | 0.987 | 43/43 | 0.00083 |
| 143 | syn_rentroll_pdf | LLM recipe (`grid:ai`), first call | 1 | none | no | 0.986 | 30/30 | 0.00081 |

- "checks failed: none" means the chosen recipe passed all four Z-45 checks plus the contract. A
  failure would have shown as another chosen name, an extra call, or `grid:fallback`.
- The checks of the unchosen candidates (no-call recipe, merge) are in job metadata under
  `cache/`, not read. No E0 retry and no no-call recipe were used in any run.

### Per doc (DR26 metrics; n = 3 runs each)

| doc | rows pred/truth | row recall | extra-row rate | key accuracy | score per run | LLM calls | fallback | $/doc (mean) |
|---|---|---|---|---|---|---|---|---|
| syn_budget_pdf | 43/43 | 1.00 | 0.00 | 1.00 | 0.987 / 0.987 / 0.987 | 1 | no | 0.00084 |
| syn_rentroll_pdf | 30/30 | 1.00 | 0.00 | 1.00 | 0.986 / 0.986 / 0.986 | 1 | no | 0.00081 |

- Row recall and extra-row rate come from the reports' extra/missing rows (0/0 in every run).
- Key accuracy = the primary field's per-field score (1.00; rows are aligned on it).
- Remaining errors per run (cells):
  - budget: `section` 8 wrong (field score 0.81)
  - rent roll: `resident_name` 7 hallucinated (field score 0.77)
  - every other field 1.00

### Gate arithmetic (Z-47 = Z-24 on declared docs; base runs 104–106, candidate 141–143)

`compare_runs.py --base 104 105 106 --cand 141 142 143 --docs syn_budget_pdf syn_rentroll_pdf`

| check | base | candidate | rule | result |
|---|---|---|---|---|
| mean_gain | 0.0299 | 0.9865 | ≥ base + 0.025 | pass (+0.9566) |
| no_dev_drop | — | — | no DEV doc −0.05 | pass (0 DEV docs in scope) |
| halluc | 0.0 | 7.0 | cand ≤ base | **FAIL** |
| usd_per_doc | 0.00223 | 0.00083 | ≤ $0.01 | pass |
| all_valid | — | 0 invalid | all valid | pass |
| collapses | 0 | 0 | cand ≤ base | pass |
| same_docs | 2 | 2 | same docs | pass |

Base per doc (mean over 104–106): budget 0.016, rent roll 0.044.

**VERDICT: FAIL** (exit 1).

### Z-50 re-gate (approved after the FAIL above; $0, same runs)

- Z-50 (a) changes how check 3 counts:
  - Hallucinations are counted only in **paired cells**: cells of matched rows that both base and
    candidate returned (rows matched in any base run and in any candidate run).
  - Totals are still reported.
- Implemented in `scripts/compare_runs.py` (`cell_outcomes`, `paired_halluc`); tested in
  `tests/test_p9c.py`.
- Command: `compare_runs.py --base 104 105 106 --cand 141 142 143 --docs syn_budget_pdf
  syn_rentroll_pdf`

| doc | paired rows | halluc paired (base → cand) | halluc total (base → cand) |
|---|---|---|---|
| syn_budget_pdf | 1 | 0.0 → 0.0 | 0.0 → 0.0 |
| syn_rentroll_pdf | 2 | 0.0 → 0.0 | 0.0 → 7.0 |

- `halluc` check: pass. Paired cand 0.0 vs base 0.0 (total 7.0 vs 0.0).
- All other checks as above. **VERDICT: PASS** (exit 0).
- Next per Z-50: one full `--set all` run with grid on (must-not-error). It waits for a clean tree:
  the Z-50 code must be committed first (PR-09).

### Full-set must-not-error run 144 (Z-50 step 2)

- Command: `eval_dev.py --set all --expect-live --run-index 144`. Grid on, cache off; 14 docs;
  $0.02482 ($0.00177/doc).
- All 14 jobs SUCCESS and VALID.
- Against the base mean (104–106), no doc dropped more than 0.05. Per-doc deltas:

| doc | base mean | 144 | delta |
|---|---|---|---|
| boxscore_001 | 0.927 | 0.880 | −0.047 |
| lease_001 | 0.642 | 0.625 | −0.017 |
| lease_002 | 0.775 | 0.750 | −0.025 |
| om_001 | 0.966 | 0.966 | 0.000 |
| rentroll_001 | 0.989 | 0.989 | 0.000 |
| t12_001 | 0.521 | 0.548 | +0.027 |
| syn_boxscore_csv | 0.950 | 0.950 | 0.000 |
| syn_budget_pdf | 0.016 | 0.987 | +0.971 |
| syn_lease_docx | 0.900 | 0.900 | 0.000 |
| syn_lease_scan | 0.150 | 0.150 | 0.000 |
| syn_lease_text | 0.867 | 0.850 | −0.017 |
| syn_loan_unseen | 1.000 | 1.000 | 0.000 |
| syn_rentroll_pdf | 0.044 | 0.986 | +0.943 |
| syn_rentroll_xlsx | 1.000 | 1.000 | 0.000 |

- Only the two PDF tables took the grid route.
- The largest drop, boxscore_001 (−0.047), is a CSV the grid cannot touch, and 0.880 equals that
  doc's own base minimum. Run-to-run noise.
- **Result: pass.** `PDF_TABLE_METHOD` default set to **`grid` on lab**: `app/config.py`,
  `compose.yaml` (`${PDF_TABLE_METHOD:-grid}`), shipped-config test, and the switch test in
  `tests/test_p9c.py`. `single` still gives the v1.0 call.

## Part C build — TABLE_CLEANUP (Z-51; $0, default off)

- `app/tables/cleanup.py` holds two general rules, applied to the spec path's final entries
  (XLSX/CSV and the PDF grid) after the recipe is chosen, so recipe choice and checks are
  unchanged:
  1. A non-key text field (text / free_text / code) whose **whole** cell is vacant, vacancy,
     unoccupied, n/a, none, tbd or a lone dash (any case) becomes null (citation "", null
     confidence). The row key is never nulled.
  2. A field filled by the `section_context` rule loses a trailing "(continued)" / "(cont.)" /
     "continued". The citation snippet stays verbatim.
- Switch: `TABLE_CLEANUP` (default off; 1/true/yes/on turns it on). Wired through config, the
  worker start line (`table_cleanup=`), compose.yaml (`${TABLE_CLEANUP:-0}`) and the
  shipped-config test.
- Off → the worker passes no kwarg and the entries are unchanged (tested). The v1.0 single-call
  path is never touched.
- Metadata `extraction.table.cleanup`: counts only (`placeholder_nulls`, `section_suffixes`).
- Tests: `tests/test_p9c_cleanup.py`, 40 tests on invented data:
  - whole-cell matching, including "Vacant since May" kept
  - marker stripping, including a leading "Continued …" kept
  - row key exempt
  - section rule only on section-label fields
  - spreadsheet path on and off
  - PDF grid path on and off
  - switch parsing
  - worker passes `cleanup` only when on
- Live runs (3 × rentroll_001, syn_rentroll_pdf, syn_rentroll_xlsx, syn_budget_pdf; cap $0.05)
  wait for the restart with `TABLE_CLEANUP=1`.

### Part C live runs 151–153 (TABLE_CLEANUP=1; Z-24 + Z-50 gate)

- Stack: `cache_mode=off, lab_mode=on, e0_robust=on, pdf_table=grid, table_cleanup=on`, code
  `6126ef4`.
- Command: `eval_dev.py --set all --docs rentroll_001 syn_rentroll_pdf syn_rentroll_xlsx
  syn_budget_pdf --expect-live --run-index 151|152|153`.
- All 12 jobs SUCCESS and VALID, 1 LLM call each, $0.00364 per run. All three runs gave
  identical scores.
- Base per doc (approved): grid runs 141–143 for syn_budget_pdf and syn_rentroll_pdf; runs
  104–106 for rentroll_001 and syn_rentroll_xlsx.
- compare_runs has no per-doc base selector, so the gate was computed by calling the unchanged
  `compare_runs.gate()` on that per-doc base (`.scratch/p9c_gate_mixed.py`).

| doc | base score | cand score | halluc before → after (mean/run) | paired halluc before → after |
|---|---|---|---|---|
| rentroll_001 | 0.989 | 0.989 | 44.0 → 44.0 | 44.0 → 44.0 (325 rows) |
| syn_budget_pdf | 0.987 | **1.000** | 0.0 → 0.0 (wrong `section` 8 → 0) | 0.0 → 0.0 (43 rows) |
| syn_rentroll_pdf | 0.986 | 0.986 | 7.0 → 7.0 | 7.0 → 7.0 (30 rows) |
| syn_rentroll_xlsx | 1.000 | 1.000 | 0.0 → 0.0 | 0.0 → 0.0 (24 rows) |

| check | result |
|---|---|
| mean_gain | **FAIL**: cand 0.9937 vs base 0.9904 (delta +0.0033; +0.025 needed) |
| no_dev_drop | pass (0) |
| halluc | pass: paired 51.0 vs 51.0 (total 51.0 vs 51.0) |
| usd_per_doc | pass ($0.00091) |
| all_valid / collapses / same_docs | pass |

**VERDICT: FAIL.** Per Z-52: no full-set run, `TABLE_CLEANUP` stays **off** (default unchanged).

**What happened per rule**

- **Rule 2 (continued labels) works.** On syn_budget_pdf, all 8 wrong `section` cells are fixed
  in every run (0.987 → 1.000).
- **Rule 1 (placeholders) never fired, because of an implementation gap.** The hallucinated cells
  are in `resident_name`.
  - That field compiles to type `integer`: its type comes only from a noun in its description (a
    weak type).
  - For weak types, the executor keeps a text cell as text (an existing, documented rule).
  - The cleanup only considered text-typed fields, so it skipped these cells.
  - Fix (not made; needs a yes): also apply rule 1 to weak-typed fields whose value is a string
    (`execute.weak_type`). It's a few lines plus a test.
- rentroll_001's other 22 hallucinated cells per run are in `balance` (numeric). Neither rule
  covers them.
- **The gate cannot pass for this kind of fix.** Even with rule 1 fixed, these near-ceiling docs
  gain about +0.01 on average (estimate):
  - syn_rentroll_pdf → ≈ 1.000
  - rentroll_001 → ≈ +0.004
  - syn_budget_pdf +0.013

  That is under the +0.025 mean_gain bar.
- Choices for Hariom:
  - (a) Keep off.
  - (b) A gate variant for cleanup-type switches, e.g. no score drop on any doc plus paired
    hallucinations strictly fewer, instead of +0.025.
  - (c) Fix rule 1, rerun, and accept the gate result whatever it is.

### Z-59 (c): placeholder rule fix + targeted-fix gate (build, $0)

- **Fix.** Rule 1 now also applies to weakly typed fields whose cell holds text: same lexicon,
  whole cell only, never the row key, never a number (`app/tables/cleanup.py`, using
  `execute.weak_type`).
- **Tests** (invented data, `tests/test_p9c_cleanup.py`):
  - a weak `integer` field holding "VACANT" / "Unoccupied" becomes null; a number in that field
    is kept; "Vacant from June" is kept
  - a strongly typed number field is never touched
  - a row key that is a placeholder is never nulled
  - spreadsheet path on and off
  - gate script: targeted-cell counter and rule logic
- **Gate.** Pre-registered by Hariom before runs 154–156 and implemented in
  `scripts/gate_cleanup.py`. Bases are fixed in code: grid runs 141–143 for the two PDF docs,
  runs 104–106 for rentroll_001 and syn_rentroll_xlsx.
  - (i) no declared doc's mean below its base mean
  - (ii) targeted error cells strictly fewer in total. A targeted cell is a mismatched cell in a
    matched row whose predicted text is a whole-cell placeholder where the truth is null, or
    carries a trailing continued-marker.
  - (iii) paired hallucinations ≤ base
  - all VALID
  - (iv) then one full `--set all` must-not-error run
- **Base targeted cells** (mean per run, measured by the script): syn_budget_pdf 8.0,
  syn_rentroll_pdf 7.0, rentroll_001 22.0, syn_rentroll_xlsx 0.0; total 37.0.
- **Sanity run** of the script on the old runs 151–153 (unfixed rule; not the gate's runs): 29.0
  vs 37.0, verdict PASS on the section fix alone. The gate applies only to runs 154–156.

### Z-59 live runs 154–156 (TABLE_CLEANUP=1, fixed rule; targeted-fix gate)

- Stack: `pdf_table=grid, table_cleanup=on`, code `cf62be9`. Workers started 17:17 UTC, after the
  fix commit.
- 12 jobs, all SUCCESS and VALID, 1 LLM call each; $0.00364 per run.
- Command: `scripts/gate_cleanup.py --cand 154 155 156`.

| doc | base score | 154–156 score | targeted cells before → after | halluc paired before → after | halluc total before → after |
|---|---|---|---|---|---|
| syn_budget_pdf | 0.987 | **1.000** | 8.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |
| syn_rentroll_pdf | 0.986 | **1.000** | 7.0 → 0.0 | 7.0 → 0.0 | 7.0 → 0.0 |
| rentroll_001 | 0.989 | 0.989 | 22.0 → 22.0 | 44.0 → 44.0 | 44.0 → 44.0 |
| syn_rentroll_xlsx | 1.000 | 1.000 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |

- (i) no doc below its base: pass. (ii) targeted 22.0 vs 37.0: pass. (iii) paired halluc 44.0 vs
  51.0: pass. All VALID. **Gate (i)–(iii): PASS.**
- **Counter caveat.** rentroll_001's 22 targeted cells are hallucinated `resident_name` cells
  (truth null) whose text ends in a continued-marker. Shown by field name and counts only.
  - The script counts any mismatched text with that marker as a "wrong section label", which is
    broader than the pre-registered wording.
  - They are 22 on both sides. Counted on section-label fields only, (ii) is 15 → 0, still a
    pass.
  - The cleanup correctly leaves them alone: they are not whole-cell placeholders and not
    section labels.

### Run 157: full set, must-not-error (iv)

- Command: `eval_dev.py --set all --expect-live --run-index 157`, cleanup on; $0.02615. All 14
  jobs SUCCESS and VALID.
- 13 docs were within 0.05 of their base mean. **t12_001 scored 0.094** against a base mean of
  0.521 (1,186 missed cells, 2 calls). **(iv) FAIL.**
- A metadata check via a scratch script reading `cache/` was blocked by the classifier → full
  STOP. Hariom then ruled `cache/` is never read (Z-60).
- Z-60 diagnosis from API job metadata (`GET /jobs/{id}`, whitelisted counts and reason codes):
  run 157's t12 job dropped a recipe entry (fill 0.2857). The E0 spec retry also gave fill
  0.2857, so the first recipe was kept.
  - **The cleanup changed 0 cells in that job.** The collapse happened before the cleanup ran.

### Z-60 (d): t12_001 on/off test (pre-registered rule; cap $0.015)

- **Rule:** cleanup is cleared if t12 collapses (score < half its base median = 0.5 × 0.548 =
  0.274) no more often with cleanup on than off, AND every on-collapse shows the low-fill recipe
  before cleanup ran.
- Metadata comes from the API job record, never `cache/`. Job ids come from worker logs (one t12
  job per run).

| run | cleanup | score | LLM calls | E0 reason | fill before → after | recipe used | cleanup counts (nulls / suffixes) | missed cells |
|---|---|---|---|---|---|---|---|---|
| 157 | on | **0.094** (collapse) | 2 | entries_dropped | 0.2857 → 0.2857 | LLM first recipe (kept) | 0 / 0 | 1186 |
| 161 | on | 0.548 | 2 | entries_dropped | 0.2857 → 1.0 | E0 retry | 1 / 0 | 473 |
| 162 | on | 0.548 | 1 | none | — (fill 1.0) | LLM first recipe | 1 / 0 | 473 |
| 163 | on | 0.548 | 1 | none | — (fill 1.0) | LLM first recipe | 1 / 0 | 473 |
| 164 | off | **0.080** (collapse) | 2 | entries_dropped | 0.2857 → 0.2857 | LLM first recipe (kept) | — | 1186 |
| 165 | off | 0.548 | 2 | entries_dropped | 0.2857 → 1.0 | E0 retry | — | 472 |
| 166 | off | 0.548 | 1 | none | — (fill 1.0) | LLM first recipe | — | 472 |

- Collapses: cleanup on 0/3 in this test (1/4 counting run 157); cleanup off 1/3. Not more
  often with cleanup on.
- The only on-collapse (157) shows the low-fill recipe chosen before the cleanup ran (cleanup
  changed 0 cells). The off-collapse (164) has the same signature.
- **Rule met → cleared.** `TABLE_CLEANUP` default **on (lab)**: `app/config.py` (default True;
  0/false/no/off turns it off), compose.yaml `${TABLE_CLEANUP:-1}`, shipped-config test, and the
  switch test in `tests/test_p9c_cleanup.py`.
- **Cleanup false positive on t12:** the placeholder rule nulls 1 t12 cell per run whose truth
  is not null (missed 472 → 473 with cleanup on, every run). Score unchanged to 3 dp.
- **Net effect per run:** on the declared docs, +15 cells fixed (8 section labels + 7
  placeholder hallucinations); on t12, −1 cell.
- Spend: $0.01059 (cap $0.015).

## Decision (before Z-50)

- As pre-registered: the full `--set all` must-not-error run was **not** made (Part B step 3 needs
  a pass).
- `PDF_TABLE_METHOD` stays **`single`** on lab; the code stays, switched off. No held-out run.
- For Hariom (not decided here):
  - **(a) Amend the gate.** The halluc check compares against a base that returned 1 row of 30.
    Any change that recovers rows meets more null-truth cells, so it can only pass with zero
    errors on all of them. A per-matched-row rate would be one option. This is a new decision and
    would be decided before any rerun.
  - **(b) A general placeholder rule.** For example: a non-key text cell that repeats one word on
    rows whose date and amount columns are empty → null. Re-test with the same gate.
  - **(c) Accept the FAIL.** Ship `single`.
- The rows are fixed either way. The open question is what the gate should count.

## Where it fails

- **Budget v1.0 was an early stop, not a cut-off.** The model returned one row and ended (~700
  output tokens, no truncation flag), unlike the rent roll, which hit the 8,192-token cap. The
  grid route avoids both, because the model never writes rows.
- **Vacant-unit placeholder** (7 halluc cells/run, rent roll): the recipe copies the printed
  placeholder in the resident column; the truth is null. This is the gate failure.
- **Section labels on later pages** (8 wrong cells/run, budget): `section` comes from the nearest
  label line. By the SYN generator's layout, a section label repeated at the top of a new page
  carries a "(continued)" suffix, which is copied. Inferred from the generator code, not checked
  cell by cell.
- **Layouts the grid cannot handle** (the job then falls back to v1.0, never worse):
  - no header line (≥ 3 mostly-text segments with numbers below) → `no_header`
  - columns closer than 0.6 em on lines with a single segment
  - with fewer than 10 band lines, one stray line across a column gap merges two columns (the
    checks catch this → fallback)
  - several different tables in one PDF: only one header signature is used
  - rotated pages
  - document-level fields read only from the first table page's lines above the header
- **t12_001 residual collapse risk (spreadsheet path, independent of the grid and the
  cleanup).** In 2 of 7 t12 jobs here (157, 164), the model's first recipe dropped an entry
  (fill 0.2857), and **E0's spec retry also failed** (fill 0.2857 again), so the low-fill recipe
  was kept: score ≈ 0.08–0.09. In 2 other jobs E0's retry rescued it (fill 1.0). E0 lowers the
  risk but does not remove it.
- **Cleanup false positive.** On t12 the placeholder rule nulls 1 cell per run whose truth is
  not null (−1 cell per run, score unchanged to 3 dp), against +15 cells fixed per run on the
  declared docs.
- **Hallucinations the cleanup does not touch.** rentroll_001 keeps 44 per run:
  - 22 `resident_name` cells ending in a continued-marker (not whole-cell placeholders)
  - 22 `balance` cells (numeric)
- **Scanned PDF tables** (Z-48): out of scope. Any page image keeps the v1.0 path, so hidden
  scanned tables still score about as v1.0 does.

## Spend

| item | $ |
|---|---|
| Part 0 + Part A | 0 |
| run 141 | 0.001675 |
| run 142 | 0.001645 |
| run 143 | 0.001642 |
| run 144 (full set, grid) | 0.02482 |
| runs 151–153 (Part C, cleanup) | 0.01092 (cap $0.05) |
| runs 154–156 (Z-59, fixed rule) | 0.01092 (cap $0.03) |
| run 157 (full set, cleanup on) | 0.02615 |
| runs 161–166 (Z-60, t12 on/off) | 0.01059 (cap $0.015) |
| **P9c total** | **0.08836** |
| lab running total | ≈ 0.488 ($0.40 before P9c, per Z-49; cap $3) |

## Deviations

- **Citations** use the contract's PDF form `[Page N] text` plus `page_numbers`, not
  `P2L014:C3`. Line ids stay in the grid's map (`row_line`, `cell_line()`).
- **Retry budget.** The check-driven retry is the E0 call (purpose `table_spec_e0`). It is skipped
  when E0 already retried for low fill, so there are at most 3 recipe calls, as on spreadsheets.
- **Candidate fallback ($0).** Before any retry, another already-built recipe that passes the
  checks is used. A contract failure counts as a failed check.
- **Full-set run not made**, because the gate failed (as the prompt orders).

## SELF-AUDIT

- [x] Default `single` reproduces v1.0; the shipped-config test proves it (plus the default-call
      test, and the dry runs `--set dev` and `--set syn` unchanged at default)
- [x] Grid rules are general (no doc-specific labels, keys or values)
- [x] Rows and citations are produced by code; the model only returns a recipe (≈ 400–515 output
      tokens)
- [x] Checks run; fallback to `single` on failure; never a FAILED job for a partial (all 6 jobs
      SUCCESS + VALID)
- [x] No held-out run or read; gate as pre-registered (FAIL reported as FAIL, no goalpost move)
- [x] Spend within cap ($0.00496 of $0.15); running total reported
- [x] No commits; no stack restarts or env changes by the agent; no `.env`, answers, held-out
      docs or `cache/` contents opened; scratch only in `.scratch/`
