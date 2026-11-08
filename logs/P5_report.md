# P5 report: single-value smart path (Session 3: paid runs + ship decision)

## PLAIN SUMMARY

- **Measured:** the smart path on lease_001, lease_002 and om_001, 3 live runs each, plus 1
  smoke run. All 10 doc-runs were live (cache off, 0 replays) and valid.
- **Result:** the smart path scored **lower** than the shipped baseline on all three documents.
  Its mean was 0.650; the ship bar was 0.8385.
- **Decision: NOT shipped.** The default stays `baseline`, and `outputs/` is unchanged (8/8
  VALID).
- **Main cause:** on the scanned lease, the code could not match the model's page reference to
  a page it had sent. It nulled those answers (`loc_unknown`, 25 of 40 fields in run 1).
  - On the text lease, a second cause is that the value check rejects values that are in the
    quote in a different form (`value_not_in_quote`).
  - Both are checking-code problems, not model problems. They are reported here, not fixed (no
    fixes without Hariom).
- **Spend:** $0.044586 for 22 Haiku calls. RUNNING TOTAL is **$0.439754** (cap $0.15 for S3;
  used 30 %).

## Steps

| Step | Command (abridged) | Result |
|---|---|---|
| Stack check | `docker compose ... logs worker` | `single_value_path=smart, cache_mode=off`; stack not touched |
| Dry run | `scripts/dry_run.py --path smart` | PASSED, 6 docs, exit 0, same estimates as the plan |
| Smoke (run 0) | `eval_dev.py --docs lease_002 --max-usd 0.01 --expect-live --run-index 0` | 0.700, $0.004398, 1 call, 0 replays, valid |
| Run 1 | `... --docs lease_001 lease_002 om_001 --max-usd 0.045 --expect-live --run-index 1 --write-outputs` | mean 0.619, $0.013503 |
| Run 2 | same, `--run-index 2`, no `--write-outputs` | mean 0.607, $0.013276 |
| Run 3 | same, `--run-index 3` | mean 0.724, $0.013409 |
| Not shipped | `git checkout -- outputs/lease_001.json outputs/lease_002.json outputs/om_001.json` | outputs back to the P2 versions |
| Validate | `tools/validate.py outputs/ --schema-dir sample/schemas` | exit 0, 8 files |

Each paid run passed the clean-tree gate and the eval's own dry run. Each run wrote its report
to `logs/eval_p5_smoke.md` and `logs/eval_p5_run{1,2,3}.md`.

## Results (validate.py doc score; source `eval/history.jsonl` lines 5–8)

| Doc | Old (P2) | Run 1 | Run 2 | Run 3 | Mean | Min | Max | Floor | Δ mean vs old |
|---|---|---|---|---|---|---|---|---|---|
| lease_001 | 0.700 | 0.225 | 0.225 | 0.575 | **0.342** | 0.225 | 0.575 | 0.675 | −0.358 |
| lease_002 | 0.775 | 0.700 | 0.700 | 0.700 | **0.700** | 0.700 | 0.700 | 0.750 | −0.075 |
| om_001 | 0.9655 | 0.931 | 0.897 | 0.897 | **0.908** | 0.897 | 0.931 | 0.9405 | −0.057 |

The smoke run on lease_002 scored 0.700, the same as runs 1–3.

**Cost per run:** lease_001 $0.0059–0.0061 (5 calls), lease_002 $0.0044 (1 call), om_001 $0.0030
(1 call). The plan estimated $0.0072, $0.0057 and $0.0033, so all three came in at or under the
realistic estimate. Latency: lease_001 ~30 s, the others ~11 s.

## Ship decision (P5-22, applied exactly)

- Mean of the 3-run means = (0.34167 + 0.70000 + 0.90833) / 3 = **0.6500**.
  - Bar = old mean 0.8135 + 0.025 = **0.8385**.
  - 0.6500 < 0.8385, so this test **fails**.
- Floor test:
  - lease_001 0.342 < 0.675;
  - lease_002 0.700 < 0.750;
  - om_001 0.908 < 0.9405.
  - **All three fail.**
- **Verdict: do not ship.** The default stays `baseline` (`app/config.py`, `compose.yaml`
  unchanged). The 3 outputs were restored to the P2 versions, and README is unchanged.

## Per-field change vs old (field names and scores only; mean of runs 1–3 vs P2)

| Doc | Fields | Up | Down | Same |
|---|---|---|---|---|
| lease_001 | 40 | 2 | 20 | 18 |
| lease_002 | 40 | 1 | 4 | 35 |
| om_001 | 29 | 0 | 3 | 26 |

- **lease_001:**
  - **Down, all 3 runs 0:** `permitted_use`, `lease_term_months`, `free_rent_months`,
    `expense_structure`, `base_year_expenses`, `base_year_taxes`, `renewal_options_count`.
  - **Down, 0 / 0 / 1 (right only in run 3):** `tenant_name`, `landlord_legal_name`,
    `property_name`, `building_address`, `premises`, `rentable_square_footage`,
    `pro_rata_share`, `lease_execution_date`, `lease_commencement_date`,
    `rent_commencement_date`, `lease_expiration_date`, `security_deposit_amount`,
    `broker_names`.
  - **Up:** `early_termination_right` (0 → 1/1/1) and `total_base_rent` (0 → 0/0/1).
- **lease_002:**
  - **Down, all runs 0:** `lease_term_months`, `rent_schedule_annual_rent_per_rsf`,
    `electricity_provision`, `renewal_options_count`.
  - **Up:** `expense_structure` (0 → 1/1/1).
- **om_001:**
  - **Down:** `unit_types` (all runs 0), `occupancy_pct` (1/1/0), `average_in_place_rent`
    (1/0/1).
  - **Up:** none.

## Reason codes (counts only; run 1, from `metadata.extraction.reason_counts`)

| Doc | Mode | ok | loc_unknown | model_null | value_not_in_quote | quote_missing | type_invalid | false_unquoted |
|---|---|---|---|---|---|---|---|---|
| lease_001 | scan (4 locate + 1 read, 8 pages read) | 0 | 25 | 8 | 0 | 2 | 2 | 3 |
| lease_002 | text (1 call) | 16 | 0 | 10 | 8 | 1 | 2 | 3 |
| om_001 | mixed (1 call) | 23 | 0 | 5 | 1 | 0 | 0 | 0 |

No run used the fallback (`fallback = none` in all three run 1 jobs).

**Reason codes of the regressed fields (run 1):**
- **lease_001:** `loc_unknown` for `tenant_name`, `permitted_use`, `lease_term_months`,
  `expense_structure`, `base_year_expenses` and `base_year_taxes`; `quote_missing` for
  `free_rent_months` and `renewal_options_count`.
- **lease_002:** `value_not_in_quote` for `lease_term_months`,
  `rent_schedule_annual_rent_per_rsf` and `electricity_provision`; `quote_missing` for
  `renewal_options_count`.
- **om_001:** `value_not_in_quote` for `unit_types`. In run 1, `occupancy_pct` and
  `average_in_place_rent` were `ok` (they dropped in other runs).

Reason codes come from run 1 only. Run 1's results were in `outputs/` (written by the eval
script) before the restore. Runs 2 and 3 share run 1's raw-job folder in `cache/`, which agent
tools may not read, so their codes are not reported.

## Where it failed

1. **Scan page reference (`loc_unknown`, lease_001):** this is the dominant cause.
   - The read call answers, but its `loc` does not parse as one of the sent page labels, so
     every such field is nulled.
   - Run 3 (0.575) shows the same pipeline passing when the labels happen to match.
   - So this looks like a format mismatch between the read prompt and the `loc` parser, not a
     model reading failure. One way to fix it in P7: accept the other ways a page can be named
     (page index, `Image N`, a bare number), checked against the sent page list.
2. **Value-in-quote check too strict (`value_not_in_quote`, lease_002 and om_001):**
   - It hits computed or derived values (a term in months, a rent per RSF) and list-valued or
     free-text fields (`unit_types`, `electricity_provision`).
   - The model's value is not a literal span of its quote, so the check nulls it.
   - Computed fields without `parts` fall into this check (plan decision 2).
3. **`quote_missing` on count fields** (`renewal_options_count` on both leases): a count is often
   not printed as a number, so the quote does not hold the value.
4. **Not a cause:**
   - no hallucinations (0 in every run);
   - no fallbacks, cap stops or truncations;
   - cost and latency were within plan.

## PR status

| PR | Status |
|---|---|
| PR-02 (lease text fields) | **open.** Built; lease_002 text fields got worse (−0.075). Not shipped |
| PR-03 part 2 / PR-64 (scanned pages, locate-then-read) | **open.** Built and runs at plan cost; scored 0.342 because of `loc_unknown`. Not shipped |
| PR-72 (forgiving JSON parse) | **done in code** (S2), no failures to exercise in S3 (fallback none) |
| PR-74 (cost = max(reported, computed)) | **done.** Reported = computed on every S3 job |
| PR-75 (retry on truncated output) | **done in code** (S2); not triggered in S3 |
| PR-76 (re-check P4 winners on more docs) | **partly done.** Haiku locate-then-read on lease_001 is unstable in this pipeline (0.225–0.575, vs P4's 0.825); the cause is the checker, not the page choice. Re-check after the `loc` fix |

## SELF-AUDIT

1. **Steps done:**
   - stack check, dry run, smoke, runs 1–3;
   - ship rule, restore, validate, DESIGN lines, this report.
   - Evidence is in the tables above and in the `logs/eval_p5_*.md` files.
2. **Decisions not in the prompt:**
   - **Keeping run 1's outputs (Hariom's choice, asked mid-session).** `run_id` is the git
     SHA, so runs 1–3 share one raw-job folder, and `--reuse-from` run 1 was impossible after
     run 2. Run 1 used `--write-outputs`. When the rule failed, exactly those 3 files were
     restored with `git checkout --`. [Alternative: stop for a per-run folder fix.]
   - **Per-run cap of $0.045** (3 × 0.045 + smoke ≤ 0.139 < 0.15). [One cap for all runs: the
     script has no cumulative cap across invocations.]
   - **Separate report files per run** (`--report logs/eval_p5_*.md`) so earlier runs are not
     overwritten. [Default `logs/eval_latest.md`.]
   - **Reason codes read from `outputs/` with a `python -I` one-liner** that printed counts and
     codes only, no values. [Read tool: would have shown values.]
   - **Per-field comparison** by a scratchpad script that parses field names and scores from the
     P2 and P5 eval reports.
3. **Deviations:**
   - **Run ids:** runs 1–3 are recorded as `9d6608b-dirty`. `run_id()` marks a run dirty when
     any tracked file is modified, and the smoke had appended a line to `eval/history.jsonl`.
     The code gate ignores results files, and the code was at 9d6608b for every run.
   - **`--no-cache`:** the prompt says `--no-cache`, but that flag does not exist. The cache was
     off via `LLM_CACHE_MODE=off` (worker log), and `--expect-live` confirmed 0 replays.
4. **Numbers:**
   - scores come from `eval/history.jsonl` lines 5–8 and `logs/eval_p5_*.md` (validate.py doc
     score, n = 3 runs per doc + 1 smoke);
   - old scores come from history line 2 / `logs/P2_eval.md` (n = 1);
   - reason codes come from run 1 metadata (n = 1 run).
5. **Tests:**
   - `393 passed, 1 warning, 95 subtests passed in 54.18s`;
   - no code changed in S3 (before = after = 393, 0 new, 0 failures);
   - no network, no key.
6. **Frozen items:** `contract/`, `tools/validate.py` and `ASSIGNMENT.md` are untouched.
   validate.py exit 0 on all 8 outputs.
7. **Held-out seal:** lease_003 and budget_001 were not opened, run or scored. Their outputs are
   unchanged. DEV answers were read only by the host-side scorer in `eval_dev.py`.
8. **Safety:**
   - no commit, no push, no keys; `.env` not opened;
   - no `cache/` path read with agent tools;
   - no guard blocks;
   - no `--allow-dirty` or `--skip-dry-run`;
   - no sample values in the report, DESIGN or messages (field names, codes, scores and counts
     only);
   - the stack and env were not changed.
9. **LLM calls:**
   - **Calls:** 22, all `anthropic/claude-haiku-5.5`, reasoning tokens 0.
     - smoke: 1;
     - per run: lease_001 5 (4 locate + 1 read), lease_002 1, om_001 1.
   - **Tokens printed (smoke + run 1):**
     - smoke in 31,025 / out 2,590;
     - run 1: lease_001 37,324 / 4,637, lease_002 31,025 / 2,621, om_001 22,339 / 1,611.
     - Image tokens are not split out by the eval printout.
   - **Cost:** reported = computed on every job, so counted (max) = $0.004398 + $0.013503 +
     $0.013276 + $0.013409 = **$0.044586**.
   - **RUNNING TOTAL:** $0.395168 + $0.044586 = **$0.439754**.
10. **Risks and open items for P6 / P7:**
    - the `loc` parser on scans (PR-64, PR-76);
    - value-in-quote on derived, list and free-text fields (PR-02);
    - count fields with no printed number;
    - `run_id` per run index in `eval_dev.py`, so each run keeps its own raw folder;
    - the smart path stays behind the switch until a re-test clears P5-22.
