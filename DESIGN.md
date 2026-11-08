# DESIGN

## Problem

The service turns a business document (PDF, scanned PDF, DOCX, XLSX or CSV) and a field list it
may never have seen into the fixed result format, with a citation and a confidence per value.
The hard gates are `docker compose up` + `/health`, and at least 80 % of documents VALID within
30 minutes with 10 in flight. A null answer scores better than a wrong one or a timeout.

## Architecture

```
client --POST /jobs--> api (FastAPI) --one transaction: job + file + event--> Postgres 17
         worker x2 <--claim: FOR UPDATE SKIP LOCKED, lease 60 s, heartbeat 15 s, fence--+
           read document -> document map (text / cells / page images, with addresses)
           -> model call(s) via LLM_BASE_URL -> code checks the JSON -> result (terminal)
client --GET /jobs/{id}--> api --> result once terminal
```

Postgres is both the database and the queue. There is no Redis, so the job, its file and its
event log commit together. Terminal statuses are enforced in the DB with a compare-and-set, a
trigger, and one terminal event per job. A job ends `PARTIAL` with an all-null result after
1500 s or after 3 claims. `/health` returns 200 only if `SELECT 1` answers within 1 s. Logs
carry metadata only.

## Key decisions with evidence

| Decision | Evidence (n, source) |
|---|---|
| Lease + heartbeat + fence token | A SIGKILLed worker's job was re-claimed and finished once, 66.4 s after the kill (P8a L2). A paused worker's late write was rejected (`logs/P1_chaos.txt`) |
| 2 workers by default | 11.3 → 23.4 → 30.7 jobs/min for 1 / 2 / 3 workers (P8a L3, fake model, `eval/load.jsonl`) |
| Haiku 5.5, one call for all fields, `reasoning: none` | Best score per $ of 5 vision models on the 25-page scan: 0.825 at $0.0057 vs 0.825 at $0.127. Field groups cost 2.3× for ±0.025 (`logs/P4_report.md`) |
| Table recipe (`EXTRACT_TABLE_PATH=spec`): the model writes a column → field map from a preview, code runs it over every row | One call cannot return 325 rows (the baseline returned 2–36). rentroll_001 0.93–0.99 vs 0.006–0.110 (3 live runs, `logs/P6b_report.md`) |
| Per-document $ fuse, predicted before each call | Estimates run high (1.39× on the rent roll), so one call can never overshoot the cap |
| Dev budget stop + response store only in `compose.dev.yaml` | Pinned by `tests/test_shipped_config.py` |
| Smart (evidence-checked) path **not shipped** | 3 tries under the bar of 0.8385: 0.650, 0.740, hybrid 0.8155 (3 live runs per doc, `logs/P5b_report.md`) |

Confidence is a hand rule over how each value was verified (exact quote 0.90 … null 0.60),
clipped to [0.05, 0.95]. It is not calibrated.

## What changed in v1.1 and the gate each passed

Rule: nothing goes default-on without a live gate. A gate is pre-registered and run 3 times on
the docs the change targets: VALID, no doc drop > 0.05, hallucinations ≤ base, ≤ $0.01/doc.
Cleanup used a targeted-cell variant. After that, one must-not-error run covers the full set.

<!-- AUTO:gates -->
| Change (decision) | Docs | Base runs → mean | Gate runs → mean | Verdict | Source |
|---|---|---|---|---|---|
| E0 robust parsing (Z-34/Z-35) | 14 | 90, 103, 101, 102 → 0.649 | 105, 106 → **0.695** | PASS | logs/P9b_report.md §4 |
| PDF table grid (Z-47/Z-50) | 2 | 104–106 → 0.030 | 141–143 → **0.986** | PASS | logs/P9c_report.md; full set run 144 |
| Table cleanup (Z-59/Z-60) | 4 | 141–143 + 104–106 → 0.990 | 154–156 → **0.997** | PASS (targeted cells) | logs/P9c_report.md; full set run 157 |
| All scan pages (Z-56) | 2 | 104–106 → 0.396 | 171–173 → **0.896** | PASS | logs/P9e_report.md; run 174 |

Mean = per-doc mean over the runs, then over the docs; DEV+SYN docs, held-out never. Each gate also checked VALID, hallucinations, $/doc and (scans) latency; the verdict is the one recorded in the source report. Not switched on: `SPEC_RETRY_FEEDBACK` (P9g; its live gate could not run, run 175 excluded: HTTP 401). Source: `eval/history.jsonl` by run index.
<!-- /AUTO:gates -->

<!-- AUTO:v11 -->
| Document | Set | v1.0 (n = 2) | v1.1 run 174 (n = 1) | Change |
|---|---|---|---|---|
| boxscore_001 | DEV | 0.915 | 0.950 | +0.035 |
| lease_001 | DEV | 0.637 | 0.825 | +0.188 |
| lease_002 | DEV | 0.750 | 0.775 | +0.025 |
| om_001 | DEV | 0.569 | 0.948 | +0.379 |
| t12_001 | DEV | 0.321 | 0.548 | +0.226 |
| rentroll_001 | DEV | 0.989 | 0.989 | +0.000 |
| syn_lease_text | SYN | 0.863 | 0.875 | +0.012 |
| syn_lease_scan | SYN | 0.150 | 0.925 | +0.775 |
| syn_lease_docx | SYN | 0.900 | 0.900 | +0.000 |
| syn_budget_pdf | SYN | 0.015 | 1.000 | +0.985 |
| syn_rentroll_pdf | SYN | 0.032 | 1.000 | +0.968 |
| syn_rentroll_xlsx | SYN | 1.000 | 1.000 | +0.000 |
| syn_boxscore_csv | SYN | 0.950 | 0.950 | +0.000 |
| syn_loan_unseen | SYN | 1.000 | 1.000 | +0.000 |

DEV (n = 6) 0.697 → **0.839** · SYN (n = 8) 0.614 → **0.956** · DEV+SYN (n = 14) 0.649 → **0.906** · v1.1 all VALID: yes · $0.00217/document · run `662f00a-dirty` run 174, 2026-11-08

v1.1 = the shipped settings (`EXTRACT_TABLE_PATH=spec`, `PDF_TABLE_METHOD=grid`, `TABLE_CLEANUP=1`, `E0_ROBUST=1`, `SCAN_PAGE_METHOD=all`, `SPEC_RETRY_FEEDBACK=0`, single-value path `baseline`). v1.0 base = runs 90, 103, 101, 102 (sealed run 90 + run 103 for DEV, 101 + 102 for SYN; a doc's score is its mean over its 2 runs). SYN = 8 invented documents (`scripts/make_syn.py`). Held-out documents are in neither column. n = 1 for v1.1, so single-doc changes carry run-to-run noise (DESIGN, Where it fails). Source: `eval/history.jsonl` by run index.
<!-- /AUTO:v11 -->

<!-- AUTO:cost -->
Sealed v1.0 run 90: **$0.00250 per document** (uncached, mean over 8 documents), $0.02004 for the whole run. Total spend of the 77 eval runs in `eval/history.jsonl`: $0.8558 (cost as the gateway billed it; spikes and pilots outside the eval script are in the phase reports). Uncached = a cached answer priced at the call that filled the cache, as a grader's run has no cache.
<!-- /AUTO:cost -->

## Evaluation method

The sample set was split (D03) into 6 DEV documents and 2 held out: one lease, and the only
budget field list, to stand in for an unseen field list. Tuning used DEV plus 8 invented SYN
documents. The held-out 2 were scored once, in the sealed v1.0 run 90 (README). Score =
`tools/validate.py` `score()`. n is given with every number, and ≤ 0.025 is treated as noise
(P4). **Disclosed:** the planning chat read every answer file, held-out included, before the
split. Since then the coding agent has been blocked from them (`logs/P1_lockcheck.md`).

## Where it fails

- **Held-out, v1.0 only:** the budget scored 0.013 (1 of 55 rows, on the one-call path) and the
  lease 0.600. v1.1's PDF grid targets exactly that budget failure, but it was never run on the
  held-out set.
- **t12_001: 0.548 in 17 of the 23 recipe-era runs that scored it** (P6 run 1 → run 174).
  The rest are 0.094 (runs 2, 103, 157), 0.157 (27), 0.466 (106) and 0.08 (164). Run 175 is
  excluded (HTTP 401).
  Header-only dates (period, week) stay null. The box-score `date` is null in every live run.
- **Run-to-run noise is large at n = 1:** om_001 moved 0.794 between runs 90 and 103
  (`logs/P9a_report.md`). The v1.1 gains on single docs in run 174 carry this noise; the gated
  means (n = 3) do not.
- **Scans:** v1.1 sends every page up to 40. Scanned tables keep the v1.0 one-call path, which
  gets cut off at the output cap (box score: 1 of 10 rows, in 3 of 3 live runs).
- **A value can pass the quote check and still be wrong:** the quote can exist but be the wrong
  span (4 fields in the P5c simulation).
- **No separate parse timeout:** a hostile file holds a worker slot until the deadline. DOCX
  citations carry no page (LibreOffice was not added: +474 MB).

## What we could not finish (gateway key expired at the deadline)

- **P9g live test:** `SPEC_RETRY_FEEDBACK` is built and unit-tested but ships **off**. Its gate
  run 175 got HTTP 401, so it is excluded.
- **v1.1 held-out run:** the held-out numbers above are v1.0's.
- **v1.1 load test:** load evidence is v1.0 with a fake model (L1 20/20 terminal, 0 lost;
  README). v1.1 scans take about 30 s instead of about 13 s (p50, runs 171–173).
- **v1.1 `outputs/`:** the files are from run 90 (v1.0). Source per file:
  `logs/P9f_outputs.md`.

## Next steps

Gate P9g live, run v1.1 once on the held-out set, add recipes for scanned tables, make the
parse step killable, and calibrate confidence.
