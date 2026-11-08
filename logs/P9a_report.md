# P9a report — lab setup: SYN set, `--set`, D49 gate, v1.0 baseline

Branch `lab`. Part A commits: `f0bb69a`, `4fcf9d1`, `91a11dc`, `a1b87f4`. Part B runs 101–103 at `a1b87f4`.
Doc ids, field names, counts, scores and $ only (D04, R31).

## PLAIN SUMMARY

- **Part A:** I built an invented SYN set of 8 documents (`scripts/make_syn.py`, `tests/fixtures/syn/`).
  - The generator is deterministic: identical bytes across two builds.
  - All 8 answers are VALID, and the set passes the sample-values guard.
  - `eval_dev.py` and `dry_run.py` gained `--set dev|syn|all`; the default DEV path is unchanged.
  - `compare_runs.py` applies the D49 gate.
- **Part B:** I ran three live v1.0 baseline runs with the shipped settings and `cache_mode=off`: SYN ×2 (runs 101, 102) and DEV ×1 (run 103). Together with the committed run 90, every document now has n = 2 baseline runs.
- **Baseline means (n = 2 runs per doc):**
  - **DEV 0.6969** over 6 docs.
  - **SYN 0.6137** over 8 docs.
  - **DEV+SYN 0.6494** over 14 docs. A candidate needs **≥ 0.6744** to pass the gain check.
- **SYN is not easier than DEV.** The pooled SYN mean is 0.083 *lower* than DEV. Most of the gap comes from three SYN docs where v1.0 fails almost completely:
  - the 15-page scan: v1.0 sends only the first 8 pages, and the form is on pages 9–14;
  - the budget PDF: v1.0 returns 1 row of 43;
  - the rent-roll PDF: v1.0 returns 1 row of 30, and the output is cut off at the token limit.
- **DEV run-to-run noise is large.** om_001 moved by 0.794 between run 90 and run 103, and t12_001 by 0.454. Both swings are far bigger than the gate's 0.025 gain and 0.05 drop limits (see Risks).
- **Spend:** $0.043786 for Part B; Part A cost $0. The running total is now **$0.610902**, within the $0.10 cap for this phase.

## D49 gate thresholds, as coded in `scripts/compare_runs.py`

| constant / check | value | rule |
|---|---|---|
| `GATE_MIN_GAIN` | **0.025** | cand mean (DEV+SYN, per-doc mean over runs, then over docs) ≥ base mean + 0.025 (−1e-9 tolerance) |
| `GATE_MAX_DEV_DROP` | **0.05** | no DEV doc's cand − base < −0.05 (SYN docs are not checked) |
| hallucinations | **≤ base total** | Σ over docs of mean hallucinated cells per run, cand ≤ base (+1e-9 tolerance) |
| `GATE_MAX_USD_PER_DOC` | **0.01** | cand mean uncached $/doc over every cand run × doc ≤ $0.01 |
| all valid | **0 invalid** | every cand output VALID |
| same docs | **0 one-sided** | both sides cover the same documents, else FAIL |

Base for P9b: `--base 90 103 101 102` → mean **0.6494**, so a candidate needs ≥ **0.6744**. The hallucination limit is ≤ **45.5**.

## Baseline per doc and per run

All outputs were VALID in every run. Held-out documents in run 90 are skipped and never opened.

### DEV (run 90 = committed P8b sealed run; run 103 = this phase)

| doc | run 90 | run 103 | mean | spread | halluc / run (mean) | missed (mean) | rows p/t | $/doc |
|---|---|---|---|---|---|---|---|---|
| boxscore_001 | 0.880 | 0.950 | 0.915 | 0.070 | 0.0 | 15.0 | 10/10 | 0.00088 |
| lease_001 | 0.650 | 0.625 | 0.637 | 0.025 | 0.0 | 7.5 | 1/1 | 0.00308 |
| lease_002 | 0.775 | 0.725 | 0.750 | 0.050 | 1.5 | 0.0 | 1/1 | 0.00406 |
| om_001 | 0.966 | 0.172 | 0.569 | **0.794** | 0.0 | 12.0 | 1/1 | 0.00392 |
| rentroll_001 | 0.989 | 0.989 | 0.989 | 0.000 | 44.0 | 0.0 | 325/325 | 0.00116 |
| t12_001 | 0.548 | 0.094 | 0.321 | **0.454** | 0.0 | 829.0 | 119/119 | 0.00119 |
| **DEV mean** | **0.8013** | **0.5925** | **0.6969** | | **45.5** | | | **0.00238** |

Run 103 on om_001 ended PARTIAL (`llm_unusable`, 2 calls), but its output is still VALID. On t12_001 in run 103, all 119 rows matched but 1,186 cells came back null.

### SYN (runs 101, 102)

| doc | run 101 | run 102 | mean | spread | halluc / run (mean) | missed (mean) | rows p/t | $/doc |
|---|---|---|---|---|---|---|---|---|
| syn_boxscore_csv | 0.950 | 0.950 | 0.950 | 0.000 | 0.0 | 0.0 | 7/7 | 0.00081 |
| syn_budget_pdf | 0.017 | 0.013 | 0.015 | 0.004 | 0.0 | 0.0 | 1/43 | 0.00092 |
| syn_lease_docx | 0.900 | 0.900 | 0.900 | 0.000 | 0.0 | 0.0 | 1/1 | 0.00159 |
| syn_lease_scan | 0.150 | 0.150 | 0.150 | 0.000 | 0.0 | 33.0 | 1/1 | 0.00302 |
| syn_lease_text | 0.850 | 0.875 | 0.863 | 0.025 | 0.0 | 0.0 | 1/1 | 0.00233 |
| syn_loan_unseen | 1.000 | 1.000 | 1.000 | 0.000 | 0.0 | 0.0 | 1/1 | 0.00064 |
| syn_rentroll_pdf | 0.033 | 0.031 | 0.032 | 0.002 | 0.0 | 0.0 | 1/30 | 0.00457 |
| syn_rentroll_xlsx | 1.000 | 1.000 | 1.000 | 0.000 | 0.0 | 0.0 | 24/24 | 0.00083 |
| **SYN mean** | **0.6125** | **0.6150** | **0.6137** | | **0.0** | | | **0.00184** |

Pooled baseline mean $/doc: $0.00207 over 14 docs.

### SYN vs DEV difficulty

- **Pooled:** SYN 0.6137 − DEV 0.6969 = **−0.0832**. SYN is harder for v1.0, not easier.
- **Run 103 alone:** DEV 0.5925, so SYN is +0.021 above DEV. The DEV figure depends heavily on which DEV run is used, because of the om_001 and t12_001 swings.
- **Shape of the scores:** SYN is bimodal. Four docs score ≥ 0.90 and three score ≤ 0.15. Those three low scores are the room a P9b candidate has to improve on.

## Where v1.0 fails on SYN

Same pattern in both runs. Counts are fields scoring below 1.0, excluding fields where both runs scored 1.0.

| doc | fields < 1.0 | which / why |
|---|---|---|
| syn_lease_scan | 34 of 40 (the 6 right are the 5 null-truth fields and the empty-list broker field) | every non-null field. `scan_pages=first` sends 8 of 15 pages (dry run: `images=8/15 truncated=True`); the form is on pages 9–14 and the rider on page 15, so the model never sees them (Z-20 design). |
| syn_rentroll_pdf | 17 of 17 | every field. 1 row of 30 returned; output hit the 8,192-token cap (`flags=truncated_output`) both runs. |
| syn_budget_pdf | 14 of 14 | every field. 1 row of 43 returned (≈ 660–820 output tokens), so 42 rows are missing. |
| syn_lease_text | 6 (run 101) / 5 (run 102) | premises, base_rent_escalation, expense_structure, electricity_provision, right_to_sublet; plus total_base_rent in run 101 |
| syn_lease_docx | 4 | total_base_rent, base_rent_escalation, expense_structure, late_fee |
| syn_boxscore_csv | 1 | property_name (all 7 rows; see note) |
| syn_loan_unseen, syn_rentroll_xlsx | 0 | — |

**Note on the answers.** The SYN free-text answers use my own wording, and scoring compares them exactly. So some lease-text "wrong" cells may be fair paraphrases rather than real errors. One likely case: the box-score header prints the property with a phase suffix, but the answer gives the name without it. These are limits of the SYN answers, not proven v1.0 errors. I have not changed any answer after seeing a score.

## Spend

| run | set | raw_dir | $ (uncached) | mean |
|---|---|---|---|---|
| 101 | syn | `a1b87f4/run101` | 0.014786 | 0.6125 |
| 102 | syn | `a1b87f4-dirty/run102` | 0.014626 | 0.6150 |
| 103 | dev | `a1b87f4-dirty/run103` | 0.014374 | 0.5925 |
| **Part B total** | | | **0.043786** | |

The running total went from $0.567116 to **$0.610902**. The phase cap is $0.10, and no run came near the $0.20 pilot threshold. My estimate before the runs was ≈ $0.04, from run 90 and the dry-run token counts.

## Evidence

- **Worker start lines** before the runs: `pipeline=baseline-v1, single_value_path=baseline, table_path=spec, scan_pages=first, cache_mode=off`. These are the same settings as P8b.
- **Dry runs:** `--set syn` passed (8 docs) and DEV passed (6 docs).
- **Live runs:** each paid run printed `clean tree` and `dry run passed`. Every job made live calls (`replays=0`, `cache_mode=off`) and was run with `--expect-live`. I did not use `--write-outputs`, so `outputs/` is untouched.
- **Run reports:** `logs/P9a_eval_syn_101.md`, `logs/P9a_eval_syn_102.md`, `logs/P9a_eval_dev_103.md`. History lines carry `"set"`.
- **Part A checks:**
  - regenerate + `--check`: identical bytes;
  - 8/8 SYN answers VALID;
  - sample-values guard passed on attempt 3;
  - ruff passed; pytest 612 passed;
  - pre-commit 7/7 on all files and on the new files; guard unittest 12 OK.

## Deviations

1. **Sample-values guard.** It took 3 attempts, with Z-19, Z-20, Z-21 and Z-22 all approved on the way. The SYN budget kept 43 rows; the fallback that would drop one row was not used. I re-ran the unchanged check twice after attempt 1, to count flags and get line numbers. Those runs printed only file:line and field.
2. **Raw-dir names.** Runs 102 and 103 have `-dirty` in their raw_dir. The reason is that run 101 appended to the tracked `eval/history.jsonl`. The paid-run gate exempts `eval/` and `logs/` and printed `clean tree`, and the code was unchanged at `a1b87f4`.
3. **Report heading.** The SYN run reports are headed "DEV eval (baseline)". Only the mean line uses the set label. This is cosmetic, and I have not changed it in this phase.
4. **Blocked commands.** Claude Code's built-in safety check refused one command in Part A (an `rm` on a scratchpad path), so nothing in it ran. No `rm`/`del` was used after that. The project guard blocked nothing in this phase after Z-18.

## Risks for P9b

- **Noise on DEV is bigger than the gate's margins.** om_001 and t12_001 moved by 0.794 and 0.454 between two v1.0 runs.
  - With n = 2 per side, the "no DEV drop > 0.05" check can fail on noise alone.
  - The +0.025 gain can also be met or missed on noise alone.
  - D49 is fixed, so I have not changed it. Hariom may want n ≥ 3 candidate runs, or to note this when reading any verdict.
- **rentroll_001 sets the hallucination limit.** It produces 44 of the base total of 45.5. A candidate that changes rent-roll handling moves the hallucination check almost by itself.

## SELF-AUDIT

- [x] All new behaviour is off by default; the DEV dry run is unchanged. A test checks this: DEV rows equal `manifest()`, and DEV paths equal the v1.0 paths.
- [x] SYN is built from field lists and invented data only; no sample file was opened. The SYN schema is my own invented field list.
- [x] Every SYN answer is VALID, and the generator is deterministic (identical bytes, checked twice).
- [x] The gate implements D49 exactly. The thresholds are listed above, and tests cover the pass case plus each single-condition failure.
- [x] Spend is within the cap: $0.043786 this phase, running total $0.610902.
- [x] No held-out id in any command, anchor or file I wrote. The HELD_OUT line is unchanged (hash-compared against HEAD without printing it).
- [x] No `.env`, answer file, held-out document or `cache/` content was opened with my own tools. Scripts read the answers and printed scores only.
- [x] No commits, no stack restart, no env change, no `rm`/`del` after the denial.
