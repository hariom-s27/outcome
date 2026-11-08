# P9b report — collapse diagnosis, E0 robust parsing, noise-proof gate, model bake-off

Branch `lab`. Decisions used: Z-23..Z-30 (plan), Z-31 (config edit by Edit tool), Z-32 (compose.dev
edit kept), Z-33/Z-34 (E0 + its gate), Z-35 (E0 default on), Z-36 (base = Haiku+E0 runs 104-106),
Z-37 (pilot scope, B cap $0.12), Z-38 (gemini kept in C), Z-39 (latency rule).
Doc ids, field names, counts, scores, $ and ms only (D04, R31). Every number is from a live run
(`--expect-live`, `cache_mode=off`) recorded in `eval/history.jsonl`, with n stated.

## PLAIN SUMMARY

- **Why v1.0 collapsed (run 103):**
  - **om_001:** Haiku's first reply was sometimes JSON that would not parse, and v1.0 relied on one repair call that fails about half the time.
  - **t12_001:** the AI table spec sometimes came back with an unknown key; the entry was dropped, row fill fell to 2/7, and the existing retry only fires at fill 0.
- **E0 fixes both** (per-field salvage + one re-call for single-value docs; one more spec call on low fill or a dropped spec entry). It passed its gate on 2 full runs (0 collapses, all VALID, no doc > 0.05 below the v1.0 median, $0.00196/doc) and is now **on by default on lab** (Z-35).
  - Over the 3 Haiku+E0 runs (104-106) om_001 scored 0.966 every time (v1.0 median 0.569) and t12_001 0.548/0.548/0.466 (v1.0 median 0.321).
- **Model bake-off on the 6 declared single-value docs, all with E0:** no candidate beats Haiku by the gate.
  - **luna** is the best cheap model: 0.867 vs Haiku 0.858 (n = 3 runs each). That is +0.008, inside the noise and below the +0.025 bar, and it hallucinates slightly more (1.33 vs 1.00 cells per run).
  - **glm-5.3-flash:** 0.854 (n = 3).
  - **gemini-3.8-flash** scored highest (0.890, n = 1) but costs $0.0131/doc, above the $0.01 limit.
  - **deepseek** cannot read scans (text-only), so lease_001 is n/a.
  - **qwen** is about 6× slower than Haiku.
  - **Sonnet was not measured:** the per-document $ fuse ($0.05) blocks every Sonnet call before it is sent.
- **Decision: Haiku stays the single-value model** (`SV_MODEL` default unchanged). `outputs/` unchanged.
- **Spend:** P9b $0.356 of the $1.20 cap. Project running total **$0.966972**.

## 1. Collapse diagnosis (Z-23; metadata and ledger rows only)

| | om_001 run 90 | om_001 run 103 | t12_001 run 90 | t12_001 run 103 |
|---|---|---|---|---|
| status / reason | SUCCESS | PARTIAL `llm_unusable` | SUCCESS | SUCCESS |
| null cells / rows | 5/29, 1 | 29/29, 1 | 472/1309, 119 | 1186/1309, 119 |
| calls (purpose) | extract + repair | extract + repair | table_spec | table_spec |
| extract finish / tokens out | stop / 1656 | stop / 1652 | stop / 423 | stop / 524 |
| repair finish / tokens out | stop / 1769 | stop / 1775 | - | - |
| json_repaired | true | false | - | - |
| spec entries dropped (kind) | - | - | 0 | 1 ("unknown keys") |
| row-level fill of chosen spec | - | - | 1.0 | 0.2857 |

These were the same in both runs, so not the cause: model string returned, reasoning `none`, tokens in, latency (within about 1 s), cache off, path.

- **om_001:** the first reply ended normally (`stop`) but did not parse in 3 of 9 saved runs; the repair rescued 1 of the 3. Why the reply is malformed is not visible in metadata. The baseline path did not use the client's per-member salvage (`baseline.py`, `client.py`).
- **t12_001:** the unknown top-level key was dropped by `salvage_spec` (`app/tables/spec.py:264-266`). The B-5 retry fires only at fill 0 (`table_spec.py:433` at the time). Fill was ≤ 0.43 in 3 of 11 saved table-path runs.

## 2. Citation audit (Z-26, read-only)

- **Shipped single-value path:** the model's value and citation are kept as returned. The citation is never looked up in the document. Confidence is the model's number, clamped to [0, 1]. The citation is blanked only for a null value (`app/pipeline/baseline.py`, `_clean_field`).
- **Smart path (off):** nulls an unverified value (`single_value.py`: `quote_not_found`, `part_unverified`).
- **Table path:** code builds citations from cell addresses, so they cannot fail.

## 3. Error buckets, v1.0 (Z-26)

Cells in matched rows, as correct / omission (truth set, we null) / hallucination (truth null, we fill) / wrong.
Format-only means "equal after percent-scale or same-digits reading". It was **0 in every doc and run.**

| doc | run 90 | run 103 | | doc | run 101 | run 102 |
|---|---|---|---|---|---|---|
| boxscore_001 | 176/20/0/4 | 190/10/0/0 | | syn_lease_text | 34/0/0/6 | 35/0/0/5 |
| lease_001 | 26/8/0/6 | 25/7/0/8 | | syn_lease_scan | 6/33/0/1 | 6/33/0/1 |
| lease_002 | 31/0/1/8 | 29/0/2/9 | | syn_lease_docx | 36/0/0/4 | 36/0/0/4 |
| om_001 | 28/0/0/1 | 5/24/0/0 | | syn_budget_pdf | 10/0/0/4 (+42 missing rows) | 8/0/0/6 (+42) |
| t12_001 | 718/472/0/119 | 123/1186/0/0 | | syn_rentroll_pdf | 17/0/0/0 (+29) | 16/0/0/1 (+29) |
| rentroll_001 | 5462/0/44/19 | 5462/0/44/19 | | syn_rentroll_xlsx | 408/0/0/0 | 408/0/0/0 |
| | | | | syn_boxscore_csv | 133/0/0/7 | 133/0/0/7 |
| | | | | syn_loan_unseen | 12/0/0/0 | 12/0/0/0 |

rentroll_001's 44 hallucinations per run: `resident_name` 22 and `balance` 22, identical in runs 90 and 103.

## 4. E0 robust parsing (Z-33, Z-34, Z-35)

**What it does:**
- **Single-value lists:**
  - The client's per-member salvage runs on the single entry's fields before the repair call, so a broken field costs only that field.
  - If the result is still unusable (`llm_unusable` only), one fresh extraction call follows.
  - The first usable result is kept.
- **Table spec:** one more spec call when row fill < 0.5 or a spec entry was dropped. The higher fill is kept; it replaces B-5.
- **Metadata:** `e0` / `table.e0` hold counts and reason codes only.

**Offline replay ($0):** 1 stored raw extraction reply (om_001), which parsed strictly, so 0 rescues. The dev response cache was not read: its bodies cannot be tied to a document.

**Z-34 gate, runs 105-106** (Haiku, E0 on, `--set all`, 14 docs each; v1.0 median from runs 90/103 DEV and 101/102 SYN, n = 2):

| check | result |
|---|---|
| 0 collapses in 105/106 | **pass**: 0 (v1.0 had 2) |
| all VALID | **pass**: 28/28 |
| no doc > 0.05 below v1.0 median | **pass**: worst single run boxscore_001 −0.035 |
| $/doc ≤ $0.01 | **pass**: $0.00196 |

**E0 events live (counts):**
- runs 104-106 (42 jobs): om_001 salvage rescued 1 (run 106, 0 fields lost); t12_001 spec retry 1 (run 105, fill 0.4286 → 1.0, retry kept); boxscore_001 spec retry 1 (run 105, a doc-field entry dropped, first kept).
- Parts B-D:
  - luna lease_002 recall rescued 1 (run 131: first answer unusable, the re-call usable);
  - deepseek syn_lease_docx salvage rescued 1 (run 123);
  - every other single-value job `none_needed`.

**Z-24 base (Haiku+E0), per doc:**

| doc | 104 | 105 | 106 |
|---|---|---|---|
| lease_001 | 0.625 | 0.650 | 0.650 |
| lease_002 | 0.775 | 0.775 | 0.775 |
| om_001 | 0.966 | 0.966 | 0.966 |
| syn_lease_text | 0.875 | 0.850 | 0.875 |
| syn_lease_docx | 0.900 | 0.900 | 0.900 |
| syn_loan_unseen | 1.000 | 1.000 | 1.000 |

The undeclared docs are in `logs/P9b_eval_base_104.md` and `logs/P9b_eval_e0_105.md` / `_106.md`.

## 5. Bake-off (Parts B-D)

**Setup:**
- Same prompt, docs, scorer and E0 for every arm; only the model changes, through the `debug_model` part on a `LAB_MODE=1` stack.
- `eval_dev` refuses a job that did not report the requested model.
- Reasoning set to off where the snapshot allows it (luna none), else the lowest listed effort (glm, gemini: low). deepseek and qwen send no reasoning parameter (theirs is off).
- `max_tokens` 8192 for all. No `type:"file"` parts.
- **Declared docs (before Part C):** lease_001, lease_002, om_001 (DEV); syn_lease_text, syn_lease_docx, syn_loan_unseen (SYN). syn_lease_scan was excluded (Z-25).

**Definitions:**
- Score: `tools/validate.py score()` per doc; means are over docs of per-doc means over runs.
- Buckets: cells summed over all runs.
- $/doc: uncached, max(reported, computed), mean over jobs.
- Latency: job latency per doc; p50/p95 over all jobs.
- Collapse: a run's doc score < 0.5 × that doc's Haiku+E0 median (runs 104-106).

### 5.1 Pilot (om_001 + syn_lease_text, n = 1 run each)

| model | images | max tokens_out | finish | errors | $/doc |
|---|---|---|---|---|---|
| gpt-6-luna | yes | 1,777 | stop ×2 | 0 | 0.00190 |
| glm-5.3-flash | yes | 1,758 | stop ×2 | 0 | 0.00224 |
| deepseek-v3.2 | no (text-only; image skipped by design) | 2,054 | stop ×2 | 0 | 0.00301 |
| qwen3-vl-235b | yes | 2,411 | stop ×2 | 0 | 0.00612 |
| gemini-3.8-flash | yes | 3,212 | stop ×2 | 0 | 0.01641 |

"images = yes" means om_001's one page image was accepted (HTTP 200, `ok`). It says nothing about how well the model reads images.

### 5.2 Screen + confirm, declared docs

| model | runs (n/doc) | DEV mean | SYN mean | all mean | correct / omission / halluc / wrong | halluc per run | $/doc | p50 / p95 latency | non-SUCCESS | retries (transient) | collapses |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **haiku (base)** | 104-106 (3) | 0.7941 | 0.9222 | **0.8581** | 502/23/3/75 | 1.00 | 0.00243 | 10.7 s / 13.7 s | 0 | 0 | 0 |
| gpt-6-luna | 121, 131, 132 (3) | 0.7968 | 0.9361 | **0.8665** | 508/18/4/73 | 1.33 | 0.00229 | 15.0 s / 33.5 s | 0 | 2 (`error_in_200`) | 0 |
| glm-5.3-flash | 122, 133, 134 (3) | 0.7941 | 0.9139 | **0.8540** | 506/23/5/69 | 1.67 | 0.00250 | 10.1 s / 32.2 s | 0 | 2 (`connect_error`) | 0 |
| deepseek-v3.2 | 123 (1) | 0.6500 | 0.9433 | 0.7967 | 151/34/0/16 | 0.00 | 0.00227 | 25.6 s / 59.5 s | 1 (`model_no_vision`) | 0 | 1 |
| qwen3-vl-235b | 124 (1) | 0.7917 | 0.8861 | 0.8389 | 167/7/2/25 | 2.00 | 0.00593 | 59.5 s / 73.7 s | 0 | 0 | 0 |
| gemini-3.8-flash | 125 (1) | 0.8218 | 0.9583 | **0.8901** | 175/12/0/14 | 0.00 | 0.01309 | 15.6 s / 31.6 s | 0 | 0 | 0 |
| sonnet-5.5 (DEV) | 126 (1) | not measured | - | - | - | - | $0 (no call) | - | 3 (`doc_llm_cap`) | 0 | (3, n/a) |

**Per-doc mean scores:**

| doc | haiku | luna | glm | deepseek | qwen | gemini |
|---|---|---|---|---|---|---|
| lease_001 | 0.642 | 0.642 | 0.642 | 0.150 (n/a: scan) | 0.575 | 0.700 |
| lease_002 | 0.775 | 0.783 | 0.775 | 0.800 | 0.800 | 0.800 |
| om_001 | 0.966 | 0.966 | 0.966 | 1.000 | 1.000 | 0.966 |
| syn_lease_text | 0.867 | 0.908 | 0.917 | 0.905 | 0.925 | 0.975 |
| syn_lease_docx | 0.900 | 0.900 | 0.908 | 0.925 | 0.900 | 0.900 |
| syn_loan_unseen | 1.000 | 1.000 | 0.917 | 1.000 | 0.833 | 1.000 |

**Per-doc min over 3 runs:**
- luna: lease_002 0.750, others = mean.
- glm: lease_001 0.600, others = mean.
- Haiku: lease_001 0.625, syn_lease_text 0.850.

**Notes:**
- **lease_001 is page images only.** deepseek returns `model_no_vision` there by design: PARTIAL, VALID, 0 calls, never a failed job.
- **Sonnet.** The per-doc fuse projects 8,192 output tokens × $10/M ≈ $0.08 per call, more than `LLM_MAX_USD_PER_DOC` = $0.05, so `doc_llm_cap` fires before any call. All 3 jobs were still VALID. The ceiling is therefore unmeasured, and D52's "Sonnet as escalation" is impossible under the shipped per-doc cap.

### 5.3 Gate (Z-24 + Z-39), declared docs, base = runs 104-106

Top 2 with $/doc ≤ $0.01 by screen mean: luna (0.869 in run 121) and glm (0.868 in run 122).

| check | luna (121, 131, 132) | glm (122, 133, 134) |
|---|---|---|
| mean ≥ base + 0.025 | **FAIL**: 0.8665 vs 0.8581 (+0.0083) | **FAIL**: 0.8540 vs 0.8581 (−0.0042) |
| no DEV doc drop > 0.05 | pass (0) | pass (0) |
| hallucinations ≤ base | **FAIL**: 1.3 vs 1.0 | **FAIL**: 1.7 vs 1.0 |
| $/doc ≤ $0.01 | pass ($0.00229) | pass ($0.00250) |
| all VALID | pass | pass |
| collapses ≤ base | pass (0 vs 0) | pass (0 vs 0) |
| p50 ≤ 2 × Haiku p50 (Z-39) | pass (15.0 s vs 21.4 s limit) | pass (10.1 s vs 21.4 s) |
| **verdict** | **FAIL** | **FAIL** |

Not needed, since no candidate passed: the full DEV+SYN must-not-error run with a winner, and the `SV_MODEL` default change.

### 5.4 Same-wrong count, luna vs glm (Z-26 / DR23)

Run k of one model vs run k of the other, declared docs, 3 pairs: 603 paired cells.

| | cells |
|---|---|
| both wrong, same normalised value | 20 |
| both wrong, both null (both omitted) | 18 |
| both wrong, different values | 40 |
| only one wrong | 36 |

- Of the 78 cells where both are wrong, **38 (49%) agree**: same value or both null. An agreement check between these two models (P9d) cannot flag those.
- It would flag 76 cells: the 40 different-value cells plus the 36 one-wrong cells.

## 6. Decision

- **Haiku stays** the single-value model; the `SV_MODEL` default is unchanged.
- E0 is on by default (Z-35); that was its own gate.
- `outputs/` unchanged; the final run is P9f.

## 7. Pareto note (declared docs, accuracy vs $/doc, for DESIGN)

- **Frontier, cheap tier:** luna (0.867 @ $0.00229).
  - Haiku (0.858 @ $0.00243) and glm (0.854 @ $0.00250) are within run noise of it.
  - Haiku keeps the lead on hallucinations and p95 latency (13.7 s vs 33.5 s).
- **Frontier, upper tier:** gemini-3.8-flash (0.890 @ $0.0131, n = 1): +0.03 for 5.4× the cost. It is above the $0.01/doc limit, so it is only usable as a targeted escalation, not as the default.
- **Off the frontier:**
  - qwen (0.839 @ $0.00593, about 6× slower);
  - deepseek (0.797 @ $0.00227, no vision: fails scans).
- **Sonnet:** not on the chart (unmeasured; blocked by the per-doc fuse).

## 8. Where it fails

- **Scans.** lease_001 (images only) stays around 0.64 for every vision model, and syn_lease_scan stays at 0.150 because v1.0 sends only the first 8 pages (P9e).
- **PDF tables.** syn_budget_pdf returns 1 of 43 rows and syn_rentroll_pdf 1-2 of 30 rows (cut off at the token limit) in every run (P9c).
- **t12_001 spec variance.** Run 106 chose a first spec that kept 140 rows against 119 (0.466) with no E0 trigger. E0 catches dropped entries and low fill, not extra rows.
- **rentroll_001.** 44 hallucinated cells per run in 2 fields set the hallucination budget.
- **Unverified citations.** The single-value path never checks a citation against the document (§2).
- **Sonnet escalation (D52)** cannot run under `LLM_MAX_USD_PER_DOC` = $0.05 without a cap change.
- **Small n.** Gate verdicts rest on n = 3 runs per side and 6 docs. Screen-only models are n = 1.

## 9. Spend

| part | runs | $ (uncached) |
|---|---|---|
| A, A2 | none (offline) | 0 |
| E0 gate | 105, 106 | 0.054800 |
| B | 104; pilot 111-115 | 0.087290 |
| C | 121-125; 126 (Sonnet, no call) | 0.157080 |
| D | 131, 132 (luna); 133, 134 (glm) | 0.056900 |
| **P9b total** | | **0.356070** (cap $1.20; parts: B ≤ 0.12, C ≤ 0.60, D ≤ 0.40) |

Project running total: $0.610902 (end of P9a) → **$0.966972**. Lab spend (cap $3): **$0.4001**.

## 10. Deviations

1. **Guard block (Part A).** A Bash heredoc writing env-reading code was blocked. Work stopped; Z-31 approved Edit-tool edits for that code.
2. **Scope added by approval:** E0 (Z-33/34), E0 default on (Z-35), Haiku+E0 as the base (Z-36), latency rule (Z-39).
3. **Sonnet ceiling not measured** (per-doc fuse). Measuring it needs a stack env change (a higher `LLM_MAX_USD_PER_DOC`) by Hariom and about $0.22.
4. **Image support** = the provider accepted the request, not read quality.
5. **Raw-dir names** carry `-dirty` after the first run of a session (history line appended); code unchanged at the commit named.

## SELF-AUDIT

- [x] Collapse diagnosis used metadata only; no value printed anywhere (scratch scripts whitelist keys; bake-off prints counts).
- [x] Defaults reproduce v1.0 except E0, which is on by approved decision Z-35. `SV_MODEL` default = Haiku; `LAB_MODE` absent and off in the shipped config (test); dry runs `--set dev` / `--set syn` passed.
- [x] Gate thresholds unchanged (0.025 / 0.05 / halluc ≤ / $0.01 / VALID, test-asserted); affected docs declared before Part C; 3 runs per side; collapse rule applied.
- [x] No `type:"file"` parts; only allowed models; the non-vision model never failed a job (`model_no_vision` PARTIAL, VALID).
- [x] Same prompt, docs, scorer and E0 for every model; no doc cherry-picking.
- [x] Spend within every cap; running total reported.
- [x] No `.env`, answer file, held-out document or `cache/` content opened with my own tools; no held-out id typed; no commits, no stack restarts, no env changes, no rm/del.
