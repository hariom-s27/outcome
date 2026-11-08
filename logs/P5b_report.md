# P5b report: checker fixes + re-run

## PLAIN SUMMARY

- **Fixed:** the checker now compares meaning, not spelling, by value type only.
  - Page references are accepted in any form (F-2), and free text comes from the source (F-3).
  - List items are checked one by one (F-4), and numbers and dates are parsed (F-6, F-7).
  - The quoted number wins over the model's (G-1). Lists given as strings are split, and empty
    lists are `model_null` (G-2).
  - Raw results are kept per run (F-8). 52 new tests on invented data.
- **Measured:** lease_001, lease_002 and om_001, 3 live runs each, with the same rule as P5.
  All 9 doc-runs were live, valid and had 0 hallucinations.
- **Result:** every doc improved on P5. The scanned lease went from 0.342 to **0.593**, and its
  page-reference failures dropped from 25 fields to 0 in every run. But the smart path is still
  below the old baseline on all three docs. Mean **0.740** vs the bar of 0.8385.
- **Decision: NOT shipped.** The default stays `baseline`, and the 3 run-1 outputs were restored
  (8/8 VALID).
- **What remains:** mostly model-side. The model returns null (10–12 fields per lease), and
  short-text / date values are not in their quote (4–6 per lease). These are P7 work, not
  checker spelling bugs.
- **Spend:** $0.040287 for 21 Haiku calls (cap $0.10). RUNNING TOTAL **$0.480041**.

## Diagnosis (Part A, counts only)

**Source.** In P5, runs 1–3 shared one raw folder (`<sha>-dirty`), so only **run 3's** jobs are
on disk. The smoke run (run 0, lease_002) is in a separate folder (`<sha>`). Run 1's codes
survive only as the totals in `logs/P5_report.md`, shown last below. Script:
`scripts/reason_counts.py` (prints reason codes, type buckets, counts only).

**Type buckets:** date (date/month/year), number, integer, percent, boolean, list, text
(text/free_text/code), computed (a computed candidate, any type).

### P5 run 3: reason code × type

**lease_001** (scan, 4 locate + 1 read; run 3 is the run where the page labels matched)

| reason | date | number | integer | percent | boolean | list | text | computed | total |
|---|---|---|---|---|---|---|---|---|---|
| ok | 4 | 2 |  | 1 |  | 1 | 6 | 1 | 15 |
| value_not_in_quote | 2 |  |  |  |  | 2 | 3 | 3 | 10 |
| model_null |  | 1 |  |  |  |  | 5 | 2 | 8 |
| false_unquoted |  |  |  |  | 3 |  |  |  | 3 |
| quote_missing |  | 1 |  |  |  |  |  | 1 | 2 |
| type_invalid |  |  |  |  |  | 2 |  |  | 2 |

**lease_002** (text, 1 call)

| reason | date | number | integer | percent | boolean | list | text | computed | total |
|---|---|---|---|---|---|---|---|---|---|
| ok | 3 | 2 |  |  |  | 3 | 8 | 2 | 18 |
| model_null | 2 | 1 |  | 1 |  |  | 3 | 2 | 9 |
| value_not_in_quote | 1 |  |  |  |  |  | 2 | 1 | 4 |
| false_unquoted |  |  |  |  | 3 |  |  |  | 3 |
| computed_fixed |  |  |  |  |  |  |  | 2 | 2 |
| type_invalid |  |  |  |  |  | 2 |  |  | 2 |
| quote_not_found |  |  |  |  |  |  | 1 |  | 1 |
| quote_missing |  | 1 |  |  |  |  |  |  | 1 |

**om_001** (mixed, 1 call)

| reason | date | number | integer | percent | boolean | list | text | computed | total |
|---|---|---|---|---|---|---|---|---|---|
| ok | 1 | 2 | 2 |  |  |  | 9 | 7 | 21 |
| model_null | 1 | 2 | 1 | 1 |  |  |  |  | 5 |
| value_not_in_quote |  |  |  |  |  | 1 | 1 |  | 2 |
| quote_not_found |  |  |  | 1 |  |  |  |  | 1 |

**lease_002 smoke (run 0)**: ok 16, value_not_in_quote 9 (text 5, computed 3, date 1),
model_null 9, false_unquoted 3, type_invalid 2 (list), quote_missing 1 (number).

### P5 run 1 (totals only, from `logs/P5_report.md`)

| Doc | ok | loc_unknown | model_null | value_not_in_quote | quote_missing | type_invalid | false_unquoted |
|---|---|---|---|---|---|---|---|
| lease_001 | 0 | 25 | 8 | 0 | 2 | 2 | 3 |
| lease_002 | 16 | 0 | 10 | 8 | 1 | 2 | 3 |
| om_001 | 23 | 0 | 5 | 1 | 0 | 0 | 0 |

### loc shapes

**Not recoverable for P5.** The raw jobs keep each field's reason and level, not the model's
`loc` strings. The DB ledger holds no response text (R23), and the dev cache was off. Part B
adds `metadata.extraction.loc_shapes`, which holds shape names and counts only (`[Page N]`,
`Page N`, `Page N of N`, `p. N`, `pN`, `N`, `block_id`, `empty`, `other`). The Part C runs
report it.

### What the counts say

1. **Scan page reference (lease_001 run 1):** 25 of 40 fields were `loc_unknown`. Run 3 had 0
   `loc_unknown` and 15 `ok`. So the same pipeline passes when the label form matches, which
   points to F-2.
2. **`value_not_in_quote`** is spread over text (3 + 2 + 1), list (2 + 0 + 1), computed
   (3 + 1 + 0) and date (2 + 1 + 0) in run 3. In the smoke run, 5 were text. No plain
   number field failed this way. These are the F-3 / F-4 / F-5 / F-7 cases.
3. **`type_invalid` on lists (2 per lease, every run):** the model's list did not normalise
   (an empty list is also coded `type_invalid`). This is outside F-2 … F-7 and not changed
   here; it is left for P7.
4. **`quote_missing` / `model_null`** are model-side (no quote or no value). A checker fix cannot
   recover them.

## Fixes (Part B, F-2 … F-8, by value type only)

| ID | Where | Change |
|---|---|---|
| F-2 | `single_value.page_label`, `cited_page`, `evidence` | A page number is read from `Page 3`, `[Page 3]`, `page 3`, `p. 3`, `p3`, `pg 3`, `3`, `[3]`, `Page 3 of 25`. It is accepted only if that page was sent. With 1 image sent and an empty loc, that page is used. An unreadable loc on a doc with images gives `page_not_sent`. A page the doc does not have stays `loc_unknown` |
| F-3 | `single_value.free_text_value` | `free_text` fields: the value is source text found by `find_quote`. First it looks for the model's value inside the matched span (snapped to words); otherwise it uses the whole span, label / cross-reference trimmed by `norm_text`. No round trip. Quote not found → null. Vision pages keep the model's value (there is no source text to snap to) |
| F-4 | `single_value.check_list`, `list_haystacks` | Each list item is checked on its own, against the cited block + ±2 neighbours, the blocks of a cited text page, or the transcription of a sent page. Text items: exact, then fuzzy ≥ 90 and ≥ 4 characters (`find_quote(min_chars=4)`). Number / date items: parsed compare. Verified items are kept in the model's order (`ok_partial` when some drop). `list_unverified` when none verify |
| F-5 | `check_computed` (unchanged) | Already verified each part and never required the final value in a quote. New tests pin this. No parts → a normal field of its type |
| F-6 | `normalise._close`, `_NUMERAL` | Number match uses the scorer tolerance max(0.01, 0.5 %). `.5` reads as 0.5 (it was read as 5). Number words (zero–nineteen, tens, hundred, thousand, "two (2)") were already parsed and now have tests |
| F-7 | `normalise._date_values(hinted_only)`, `_DMY`, `check_answer` | Every date in the quote is parsed. An ambiguous numeric date counts only as the reading the doc date-order hint picks, and as none without a hint. `1st of June, 2033` now parses. When the text gives no vote (scans), the vote is taken from the answer's own quotes |
| F-8 | `eval_dev.run_folder` | Raw jobs go to `<run_id>/run<index>/`. History lines carry `raw_dir`. `--reuse <run_id>/run<n>` reads a per-run folder back |
| F-11 | `scripts/reason_counts.py`, `metadata.extraction.loc_shapes` | Counts-only diagnosis tool, plus loc-shape counters |
| G-1 (Hariom, at STOP 1) | `normalise.source_value`, `verify.quoted_value` | The source wins: when a number passes within the tolerance, the output is the closest number the quote states, not the model's. This applies to single fields, number list items and computed parts (the code computes from the quoted parts). Dates match by equality, so the source date is the model's date. An integer field keeps the model's value if the quoted number is not whole |
| G-2 (Hariom, at STOP 1) | `check_field`, `norm_list` | A list returned as a string is split by the existing rule (line breaks, `;`, bullets, `\|`; never commas), then each item is checked as in F-4. An empty list, or one with only blank items, is `model_null` (it was `type_invalid`). Items that do not normalise stay `type_invalid` |

**Known limit (F-4 as specified):** a text item verified by the fuzzy step (≥ 90) keeps the
model's spelling, not the source span. In a test, an item with a stray 2-character suffix
passed fuzzy against a longer source line. A P7 option is to output the matched source span
for fuzzy items (the F-3 / G-1 "source wins" idea applied to text items).

No prompt text changed, so `PROMPT_VERSION` is the same as P5 and the dry-run estimates are
identical. No rule names a document, a field key or a value. Tests use invented widget fields
and invented values only.

### Part B checks

- `uv run ruff check .`: All checks passed. `ruff format --check .`: 111 files already formatted.
- `uv run pytest -q` (after G-1 / G-2): `445 passed, 1 warning, 95 subtests passed in 65.25s`.
  That is 393 before plus 52 new in `tests/test_checker_fixes.py` (47 F-tests, 5 G-tests).
  One P5 assertion was changed on purpose: 12,354 vs a quoted 12,345 now passes (within
  0.5 %), and 12,445 is the new negative. With G-1 the output value is 12345.
- `uv run pre-commit run --all-files`: all 7 hooks Passed.
- `uv run python scripts/dry_run.py --path smart`: dry run PASSED (6 docs). Estimates are
  unchanged from P5: lease_001 real $0.0072 (5 calls), lease_002 $0.0057, om_001 $0.0033.

Committed by Hariom at STOP 1: `ff35a09` (test), `0df40dd` (fix), `6db0488` (feat(eval)).

## Steps (Part C)

| Step | Command (abridged) | Result |
|---|---|---|
| Stack check | `docker compose ... logs worker \| grep started` | `single_value_path=smart, cache_mode=off`; stack not touched |
| Dry run | `scripts/dry_run.py --path smart` | PASSED, 6 docs |
| Run 1 | `eval_dev.py --docs lease_001 lease_002 om_001 --max-usd 0.033 --expect-live --run-index 1 --write-outputs --report logs/eval_p5b_run1.md` | mean 0.756, $0.013509, run id `6db0488`, raw `6db0488/run1` |
| Run 2 | same, `--run-index 2`, no `--write-outputs`, `--report logs/eval_p5b_run2.md` | mean 0.7308, $0.013312, raw `6db0488-dirty/run2` |
| Run 3 | same, `--run-index 3`, `--report logs/eval_p5b_run3.md` | mean 0.7336, $0.013466, raw `6db0488-dirty/run3` |
| Not shipped | `git checkout -- outputs/lease_001.json outputs/lease_002.json outputs/om_001.json` | outputs back to the P2 versions |
| Validate | `tools/validate.py outputs/ --schema-dir sample/schemas` | exit 0, 8 files |

- Each run passed the clean-tree gate ("clean tree") and the eval's own dry run.
- Each run had 0 replays (`--expect-live`), the same `prompt_version` `6f12c23c314c` and path
  `smart`.
- `loc_shapes` is present in every job, which shows the worker ran the committed checker code.

## Results (validate.py doc score; source `eval/history.jsonl`, last 3 lines)

| Doc | Old (P2) | P5 mean | Run 1 | Run 2 | Run 3 | **P5b mean** | Min | Max | Floor | Δ vs P5 | Δ vs old |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | 0.700 | 0.342 | 0.6119 | 0.5786 | 0.5869 | **0.5925** | 0.5786 | 0.6119 | 0.675 | +0.251 | −0.108 |
| lease_002 | 0.775 | 0.700 | 0.725 | 0.700 | 0.700 | **0.7083** | 0.700 | 0.725 | 0.750 | +0.008 | −0.067 |
| om_001 | 0.9655 | 0.908 | 0.931 | 0.9138 | 0.9138 | **0.9195** | 0.9138 | 0.931 | 0.9405 | +0.011 | −0.046 |

- Definition: score = mean of per-field means (`tools/validate.py score()`), n = 3 live runs per
  doc. Old = the P2 outputs (n = 1). P5 = `logs/P5_report.md` (n = 3).
- lease_001 scores are now fractional because lists earn partial F1 credit (F-4).
- Cost per run: lease_001 $0.0059–0.0060 (5 calls), lease_002 $0.0044–0.0046 (1 call), om_001
  $0.0030–0.0031 (1 call), the same as P5. Latency: lease_001 ~29 s, the others ~10–14 s.

### Per-field change (field names and scores only; mean of runs 1–3)

| Doc | Fields | Up vs old | Down vs old | Same | Up vs P5 | Down vs P5 |
|---|---|---|---|---|---|---|
| lease_001 | 40 | 5 | 8 | 27 | 16 | 0 |
| lease_002 | 40 | 2 | 4 | 34 | 1 | 0 |
| om_001 | 29 | 0 | 3 | 26 | 1 | 1 |

- **lease_001:**
  - **down vs old:** `permitted_use`, `lease_term_months`, `free_rent_months`,
    `expense_structure`, `base_year_expenses`, `base_year_taxes`, `renewal_options_count` (all
    runs 0); `building_address` (1/0/0).
  - **Up vs old:** `rent_schedule_start_dates`, `rent_schedule_end_dates` (0 → 0.57 each run),
    `rent_schedule_monthly_rent` (0 → 0.33/0/0.33), `total_base_rent`, `early_termination_right`
    (0 → 1 each run).
  - **Recovered vs P5:** 12 of the 13 fields that P5 got right only in run 3: `tenant_name`,
    `landlord_legal_name`, `property_name`, `premises`, `rentable_square_footage`,
    `pro_rata_share`, the four lease dates, `security_deposit_amount`, `broker_names`. The 13th,
    `building_address`, did not recover.
- **lease_002:**
  - **down vs old:** `lease_term_months`, `rent_schedule_annual_rent_per_rsf`,
    `electricity_provision`, `renewal_options_count` (all runs 0).
  - **Up vs old:** `expense_structure` (1 each run), `building_address` (1/0/0).
- **om_001:**
  - **down vs old:** `occupancy_pct` (1/1/0), `average_in_place_rent` (0/0/1), `unit_types`
    (1/0.5/0.5).
  - **Vs P5:** `unit_types` up, `average_in_place_rent` down.

## Reason codes per run (counts only; `scripts/reason_counts.py --run <raw dir>`)

| Doc | Run | ok | ok_partial | model_null | value_not_in_quote | quote_missing | quote_not_found | false_unquoted | part_unverified | list_unverified | loc_unknown | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lease_001 | 1 | 15 | 3 | 10 | 6 | 2 | 0 | 3 | 0 | 1 | 0 | 40 |
| lease_001 | 2 | 15 | 2 | 10 | 6 | 2 | 0 | 3 | 0 | 2 | 0 | 40 |
| lease_001 | 3 | 16 | 3 | 11 | 4 | 3 | 0 | 3 | 0 | 0 | 0 | 40 |
| lease_002 | 1 | 17 | 0 | 11 | 5 | 1 | 1 | 3 | 2 | 0 | 0 | 40 |
| lease_002 | 2 | 17 | 0 | 12 | 6 | 1 | 0 | 3 | 0 | 1 | 0 | 40 |
| lease_002 | 3 | 17 | 0 | 12 | 6 | 2 | 0 | 3 | 0 | 0 | 0 | 40 |
| om_001 | 1 | 23 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 29 |
| om_001 | 2 | 23 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 29 |
| om_001 | 3 | 23 | 0 | 5 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 29 |

**By type** (buckets as in the Diagnosis):

- **`value_not_in_quote`:**
  - lease_001: date 2 / 2 / 2, text 3 / 3 / 1, computed 1 / 1 / 1.
  - lease_002: date 1 / 1 / 1, text 3 / 4 / 4, computed 1 / 1 / 1.
  - `free_text` has no round trip after F-3, so these text cases are short `text` or `code`
    fields.
- **`model_null`, run 1:**
  - lease_001: number 1, list 2, text 5, computed 2.
  - lease_002: date 2, number 1, percent 1, list 2, text 3, computed 2.
  - om_001: date 1, number 2, integer 1, percent 1, computed 1.
  - The 2 list nulls per lease were `type_invalid` in P5. They are empty lists from the model,
    now coded `model_null` (G-2).
- **`ok_partial` / `list_unverified`:** list and computed-list buckets only (F-4 partial credit).
- **loc shapes:**
  - lease_001: `Page N` 25 / 25 / 23, `empty` 7 / 7 / 8.
  - lease_002: `block_id` 24 / 24 / 23, `empty` 6 / 6 / 7.
  - om_001: `block_id` 23 / 23 / 24.
  - No other shapes appeared.

## Ship decision (P5-22, applied exactly; rule and floors unchanged)

- **Means:**
  - lease_001 = (0.6119 + 0.5786 + 0.5869) / 3 = 1.7774 / 3 = **0.59247**
  - lease_002 = (0.725 + 0.700 + 0.700) / 3 = 2.125 / 3 = **0.70833**
  - om_001 = (0.931 + 0.9138 + 0.9138) / 3 = 2.7586 / 3 = **0.91953**
- **Mean test:** mean of the 3-run means = (0.59247 + 0.70833 + 0.91953) / 3 = 2.22033 / 3 =
  **0.74011**. The bar is old mean 0.8135 + 0.025 = **0.8385**. 0.74011 < 0.8385, so this test
  **fails**.
- **Floor test:** lease_001 0.592 < 0.675; lease_002 0.708 < 0.750; om_001 0.920 < 0.9405.
  **All three fail.**
- **Verdict: do not ship.**
  - The default stays `baseline` (`app/config.py` and `compose.yaml` unchanged).
  - The 3 run-1 outputs were restored with `git checkout --`.
  - `validate.py` exits 0 on 8 files. README is unchanged.

## Where it fails

1. **The checker is no longer the main cause.**
   - `loc_unknown` is 0 in all 9 doc-runs.
   - om_001 has no `value_not_in_quote` left.
   - The only `type_invalid` cases are gone (G-2).
   - The lease_001 collapse is fixed: 0.342 → 0.593, with no run below 0.578.
2. **Model nulls (`model_null`, 10–12 per lease, 5–6 on om_001).** This is the largest bucket.
   - The model answered null where the old baseline got the value: the lease_001 fields that
     are 0 in every run, and `renewal_options_count` on both leases.
   - It is a prompt or reading problem (P7): what the read prompt asks for, and the scan page
     choice. A checker fix cannot recover these.
3. **Short `text` / `code` and date values not in their quote** (`value_not_in_quote`, 4–6 per
   lease). After F-3 these are not `free_text`. Likely causes are a retyped name or address, or
   a date the quote states only in part.
   - This is not checked here: the per-field reason lookup was blocked and not retried (see
     SELF-AUDIT 3).
4. **Computed fields with no parts:** `lease_term_months` (both leases) and
   `rent_schedule_annual_rent_per_rsf` are still 0.
   - Without parts, the final value must be in the quote (F-5: normal field of its type), and a
     derived value usually is not.
   - Getting the model to return parts is a prompt change (P7).
5. **Run-to-run variance on om_001:** `occupancy_pct` and `average_in_place_rent` flip between
   runs, all `ok` or `model_null`. That is model variance on a 1-call doc.
6. **Known checker limit:** a fuzzy-verified text list item keeps the model's spelling (see
   Fixes).

## SELF-AUDIT

1. **Steps done:**
   - Part A diagnosis (run 3 + smoke on disk) and Part B F-2 … F-8 with tests;
   - G-1 / G-2 on Hariom's request at STOP 1;
   - Part C stack check, dry run, 3 × 3 live runs, per-run reason codes;
   - Part D ship rule, restore, validate, DESIGN lines, this report.
   - Evidence is in the tables above and in `logs/eval_p5b_run{1,2,3}.md`.
2. **Decisions not in the prompt:**
   - **Diagnosis on run 3, not run 1.** Run 1's raw jobs had been overwritten (shared folder,
     the bug F-8 fixes). [Alternative: none; run 1 survives only as totals.]
   - **loc shapes added as metadata.** P5 never stored `loc` strings, so they could not be
     diagnosed. [Alternative: no shape data.]
   - **F-3 narrowed.** The value is the model's value as found inside the source span, else the
     whole span (Hariom: OK). Vision free text keeps the model's value.
   - **F-7, no hint:** ambiguous numeric dates do not match (decision-table worst case). Scans
     vote the date order from the answer's quotes.
   - **G-1 also covers number list items and computed parts.**
   - **G-2:** blank list items are skipped in `norm_list`.
   - **A page that does not exist in the doc stays `loc_unknown`;** only an image page not sent
     is `page_not_sent`. This kept the P5 meaning of `loc_unknown` for text docs.
   - **Per-run cap $0.033** (3 × 0.033 ≤ $0.10). The script has no cumulative cap.
3. **Deviations:**
   - **Per-field reason lookup blocked.** A read-only `python -I` one-liner was meant to print
     reason codes for the regressed fields (doc id, field name, code; no values). The auto-mode
     classifier denied it.
     - I stopped and reported, per the rules, and did not try any other route.
     - Hariom chose to finish without it, so "where it fails" uses the reason × type tables and
       field names only.
   - **Run ids:** runs 2–3 are recorded as `6db0488-dirty`, because run 1 appended
     `eval/history.jsonl` and wrote `outputs/`. The code was at `6db0488` for all runs (the
     clean-tree gate passed each time).
4. **Numbers:**
   - scores: `eval/history.jsonl` (last 3 lines), n = 3 runs per doc;
   - old: P2, n = 1; P5: `logs/P5_report.md`, n = 3;
   - reason codes: each run's raw jobs (n = 1 job per doc per run), via `scripts/reason_counts.py`;
   - per-field: a scratchpad script that parses field names and scores from the eval reports.
5. **Tests:** 393 before → **445** after (52 new, 1 P5 assertion changed on purpose, 0 failures).
   No network, no key. No code changed in Parts C–D.
6. **Frozen items:** `contract/`, `tools/validate.py` and `ASSIGNMENT.md` are untouched.
   pre-commit "given files unchanged" Passed.
7. **Held-out seal:** lease_003 and budget_001 were not opened, run or scored. Their outputs are
   unchanged. `reason_counts.py` skips held-out ids.
8. **Safety:**
   - no commit or push by the agent; no keys; `.env` not opened;
   - no `cache/` path read or named with agent tools (scripts read raw jobs through
     `eval_dev.RUNS`);
   - one auto-mode deny (3 above), no guard blocks;
   - no `--allow-dirty` or `--skip-dry-run`;
   - no sample values in code, tests, report, DESIGN or messages; tests use invented widget data;
   - stack and env not changed.
9. **LLM calls:**
   - **Calls:** 21, all `anthropic/claude-haiku-5.5`, reasoning tokens 0. Per run: lease_001 5
     (4 locate + 1 read), lease_002 1, om_001 1.
   - **Tokens, run 1:** lease_001 37,324 in / 4,450 out; lease_002 31,025 / 2,893; om_001
     22,339 / 1,539. Runs 2–3 have the same inputs; outputs were 4,315 / 4,362, 2,640 / 2,663
     and 1,531 / 1,770.
   - **Cost:** reported = computed on every job. $0.013509 + $0.013312 + $0.013466 =
     **$0.040287**.
10. **Risks and open items for P6 / P7:**
    - model nulls on lease fields (prompt / page choice);
    - parts for computed fields;
    - `value_not_in_quote` on short text and dates (needs the per-field reason view, with
      Hariom's permission);
    - fuzzy list items should output source text;
    - the smart path stays behind the switch.

## RUNNING TOTAL

$0.439754 (after P5) + $0.040287 (P5b) = **$0.480041**.
