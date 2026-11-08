# DESIGN

## Problem

Turn a business document (PDF, scanned PDF, DOCX, XLSX or CSV) plus a field list the service
may never have seen into the fixed result format, with a citation and a confidence per value.
Hard gates: `docker compose up` + `/health`, and at least 80 % of documents VALID within 30
minutes with 10 in flight. A null answer scores better than a wrong one or a timeout.

## Architecture

```
client --POST /jobs--> api (FastAPI) --one transaction: job + file + event--> Postgres 17
                                                                                 |
         worker x2 (default) <--claim: FOR UPDATE SKIP LOCKED, lease 60 s, fence--+
           read document -> document map (text / cells / page images)
           -> model call(s) via LLM_BASE_URL -> code checks the JSON -> result row (terminal)
client --GET /jobs/{id}--> api --> result once terminal
```

One Python 3.12 image, three roles: **api**, **worker**, and **Postgres 17** as both the
database and the job queue. No Redis: `FOR UPDATE SKIP LOCKED` gives a correct queue with one
less moving part, and the job, its file and its event log commit in the same transaction.
Uploaded files are stored in a Postgres table and deleted once the job is terminal, so there
is no shared volume between api and worker.

## Key decisions with evidence (decision · why · number)

**Queue and crash safety**

| Decision | Why | Evidence |
|---|---|---|
| Claim with SKIP LOCKED + 60 s lease + 15 s heartbeat + fence token | a dead or frozen worker must not lose or duplicate a job | chaos run: SIGKILL'd worker's job re-claimed (fence 2) and finished once, 85 s after the kill; a paused worker's late write rejected (`logs/P1_chaos.txt`). P8a L2: re-claimed and terminal once, 66.4 s after the kill (see Load) |
| 2 worker replicas by default (W-1) | the scaling run doubled throughput from 1 to 2 workers | P8a L3: 11.3 → 23.4 → 30.7 jobs/min for 1/2/3 workers (`eval/load.jsonl`); graders can still `--scale` |
| Terminal statuses enforced in the DB (compare-and-set + trigger + one terminal event per job) | the contract says terminal never changes; code bugs should not be able to break that | trigger and unique-index tests |
| Deadline 1500 s from submission → `PARTIAL` with an all-null result | the harness gives 1800 s; a null answer beats a timeout (zero) | sweeper runs every 5 s in its own thread |
| A job claimed more than 3 times → `PARTIAL` all-null (poison job) | one bad document must not loop forever or block a worker | crash-loop and repeated-error tests |
| `PARTIAL` reason in `result.metadata.terminal_reason`; `error` only for `FAILED` | keeps `error` meaningful | |
| `429` + `Retry-After: 30` at 500 pending; `413` above 50 MB | back-pressure the harness understands | |
| `/health` 200 only if the DB answers `SELECT 1` within 1 s | "up" should mean "can accept jobs" | DB stopped → 503 in about 1.1 s |
| File type accepted if extension **or** content says PDF/DOCX/XLSX/CSV | refusing a supported file fails the document; a wrong extension should not | |
| Field list validated loosely (non-empty `fields` object) | unfamiliar field lists must work | |
| Logs carry job id, status, timings only | documents may be confidential | |
| Base images pinned tag@digest, multi-arch, no `platform:` | same build on the grader's machine (amd64 or arm64) | fresh clone: cold build 18 s, `up` → `/health` 200 in 5.6 s (P8a cold check: see `logs/P8a_report.md`) |

**Extraction: the baseline path (shipped)**

| Decision | Why | Evidence |
|---|---|---|
| Baseline: readers (text with page/cell addresses; scanned pages as JPEG) + one Haiku 5.5 call with all fields, code checks the JSON, null over guess | a cheap, honest floor to measure every later change against | DEV mean 0.599 (n = 6): single-value docs 0.70–1.00, big tables 0.05–0.11 (the model returns 6 of 119 and 36 of 325 rows); ≈ $0.0055/doc uncached (`logs/P2_eval.md`) |
| Proper readers, one document map (P3): XLSX/CSV rows with cell refs, merged/hidden/formula flags; DOCX XML walker (numbering, accepted tracked changes, text boxes, tables); PDF word → line → block model with callouts, header/footer tags and scan triage | the extractor should see the document's structure and exact addresses, not a flat dump | DEV mean 0.579 vs 0.599 (n = 6): om_001 0.948 vs 0.966, rentroll 0.006 vs 0.110 (P2's two rent-roll runs already ranged 0.009–0.110), others unchanged; P2 outputs kept (`logs/P3_eval.md`) |
| Models (P4): Haiku 5.5 for text and scans, locate-then-read for page choice, one call for all fields | best score per dollar among the listed models | 5 vision models on the 25-page scanned lease: Haiku locate-then-read 0.825 at $0.0057 vs Gemini 3.8 Flash 0.825 at $0.127. Field groups cost 2.3× for ±0.025. Noise spread 0.017 on om_001 and 0.025 on lease_002 (n = 4 each), so ≤ 0.025 counts as noise (`logs/P4_report.md`) |
| Haiku with `reasoning: {effort: none}` | its default is medium effort, billed as output | same score (1.000) on the pilot doc, 0 vs 3,964 reasoning tokens, $0.0095 vs $0.0108 |
| DOCX page numbers: pluggable method, default `none` (P3-27); LibreOffice not added (A-12) | DOCX has no pages; a wrong page is worse than none | the `estimate` method placed 0/20 locatable lease_002 citations on the exact page (13/20 within ±1); a slim LibreOffice image gave 23 pages and 0/20; the fuller-font build gave 20/20 but +474 MB, so it was not added |

**Cost guards**

| Decision | Why | Evidence |
|---|---|---|
| Per-document $ fuse, predicted before every call (P2-36) | the old cap only looked at money already spent, so one call could overshoot it 1.3× | input estimated high (1.5 chars/token, 2,600 tokens per image, +15%), whole call priced at the cliff rate when the estimate reaches it; trim the input, else skip → PARTIAL `doc_llm_cap`. Rent-roll re-run: estimate 79,469 vs real 57,118 tokens (1.39× high), $0.0097, fuse not needed |
| Input-size estimate calibrated per block type | chars/3.5 undercounted spreadsheet rows ~1.9×, so one rent-roll request sent 114k tokens and paid Haiku's 5× long-prompt price | rows 1.75, prose 2.6 chars/token; the re-run estimated 59,965 and sent 57,118 |
| Dev budget stop and response cache only in `compose.dev.yaml` | a grader's run must never stop on a dev budget or read a dev cache | `tests/test_shipped_config.py` (A-14) |

**The smart path: tested 3 times, not shipped**

- **P5 built:** a "smart" path for single-value field lists, behind
  `EXTRACT_SINGLE_VALUE_PATH` (default `baseline`). The model quotes evidence for each field,
  code checks the quote and normalises the value, and anything unproven becomes null. Scans
  use locate-then-read.
- **Ship rule (written before the paid runs):** switch only if the 3-doc mean of 3-run means
  is ≥ old mean + 0.025, and no doc's mean is more than 0.025 below its old score.
- **P5 numbers:** score = validate.py doc score, 3 live runs per doc, old = P2 outputs.
  lease_001 0.342 vs 0.700, lease_002 0.700 vs 0.775, om_001 0.908 vs 0.966. Mean 0.650 vs the
  0.8385 bar, so the default stays `baseline`. The main cause was that scan answers whose page
  reference could not be matched were nulled (`loc_unknown`: 25 of 40 lease_001 fields in
  run 1). $0.0446 for 10 doc-runs (`logs/P5_report.md`).
- **P5b checker fix:** the checker now compares meaning, not spelling: a page named in any
  form (must be a sent page), free text taken from the source span it found, list items checked
  one by one, numbers and dates parsed (the quoted number wins). Same ship rule.
- **P5b numbers:** 3 new live runs per doc, same definition. lease_001 0.593 (P5 0.342,
  old 0.700), lease_002 0.708 (0.700, 0.775), om_001 0.920 (0.908, 0.966). Mean 0.740 vs the
  0.8385 bar, so the default stays `baseline`. `loc_unknown` is now 0 in every run. 0
  hallucinations, $0.0403 for 9 doc-runs (`logs/P5b_report.md`).
- **Tables plan:** big tables need chunking (rentroll_001 returns 2–3 of 325 rows in one
  call); planned for P6.

**Confidence (P5-17, placeholder until calibrated):** a hand rule over how each value was
verified, not the model's own number. Exact quote with the value in it 0.90 · fuzzy quote 0.75 ·
computed from verified parts 0.80 · read from a page image 0.70 · null 0.60; the model saying
"low" −0.15; a lease expiration that disagrees with commencement + term −0.20; clipped to
[0.05, 0.95]. Not yet measured against accuracy.

## Evaluation method

Sample set split (D03): 6 development documents, 2 held out (one lease, and the only document
using the budget field list, to simulate an unseen field list). Prompts and rules are tuned on
the 6 only; the held-out 2 are scored once, at the end. Score = `tools/validate.py` `score()`
(strict match after normalisation); n is stated with every number; a difference of ≤ 0.025 is
noise (P4). Cost is counted as max(reported, computed), because one gateway reported $0.

**Known contamination (disclosed):** before the split was made, the planning chat read every
answer file while exploring the sample set, including the two held-out answers. Since the
split, no prompt, rule or description is tuned on them, the coding agent is blocked from
opening them (deny rules + a hook, verified in `logs/P1_lockcheck.md`), and the evaluation
script leaves them out until the final run. The held-out score is therefore close to, but not
strictly, an unseen-data score.

## Results

<!-- AUTO:results -->
| Pipeline | Path | Date | Docs | Runs | Mean score | Per document | All VALID |
|---|---|---|---|---|---|---|---|
| baseline-v1 | baseline | 2026-11-07 | 6 | 1 | **0.579** | boxscore_001 1.000, lease_001 0.700, lease_002 0.775, om_001 0.948, rentroll_001 0.006, t12_001 0.046 | yes |
| single-value-v1 | smart | 2026-11-08 | 3 | 3 | **0.740** | lease_001 0.592, lease_002 0.708, om_001 0.920 | yes |

Score = `tools/validate.py` `score()`: mean over documents of each document's mean of per-field means (strict match after normalisation). DEV documents only; the 2 held-out documents are not scored until the final run. Runs = live runs in the series (a doc's score is the mean over runs). Source: `eval/history.jsonl`, latest series per pipeline + path. Shipped default path: `baseline`.
<!-- /AUTO:results -->

## Cost

<!-- AUTO:cost -->
| Pipeline | Path | Runs | $/document (uncached) |
|---|---|---|---|
| baseline-v1 | baseline | 1 | $0.00492 |
| single-value-v1 | smart | 3 | $0.00448 |

Total spend of the 11 eval runs in `eval/history.jsonl`: $0.2133 (cost as the gateway billed it; spikes and pilots outside the eval script are in the phase reports). Uncached = a cached answer priced at the call that filled the cache, as a grader's run has no cache.
<!-- /AUTO:cost -->

All model spend by phase (from the phase reports):

| Phase | Spend |
|---|---|
| P1 skeleton | $0 (no model calls) |
| P2 baseline (pilot ×2 + DEV eval) | $0.098 (9 paid calls; one call crossed Haiku's 100k price cliff: $0.064) |
| P2 rent-roll re-run (P2-35) | $0.0097 (1 paid call; plus 1 boxscore re-submit answered from the dev cache, $0) |
| P3 readers (DEV re-run, om_001 debug call, om_001 re-run) | $0.0198 (6 paid calls) |
| P4 measurements (pilot + 4 spikes; max(reported, computed)) | $0.267 (45 paid calls) |
| P5 smart path (10 doc-runs) | $0.0446 (`logs/P5_report.md`) |
| P5b checker fix (9 doc-runs, 21 calls) | $0.0403 (`logs/P5b_report.md`) |
| P8a load, cold check, zip, docs | $0 (fake model only) |
| **Running total** | **$0.480041** (`logs/P5b_report.md`) |

## Load

<!-- AUTO:load -->
| Scenario | Workers | n | Terminal % | VALID % | p50 s | p95 s | max s | jobs/min | Lost | Dup | POST max s | 5xx | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | 1 | 20 | 100.0 | 100.0 | 52.15 | 63.95 | 65.47 | 11.04 | 0 | 0 | 0.297 | 0 | PASS |
| L2 | 2 | 10 | 100.0 | 100.0 | 13.44 | 53.74 | 77.55 | 7.74 | 0 | 0 | 0.234 | 0 | PASS |
| L3 | 1 | 20 | 100.0 | 100.0 | 52.98 | 65.22 | 65.45 | 11.29 | 0 | 0 | 0.235 | 0 | PASS |
| L3 | 2 | 20 | 100.0 | 100.0 | 23.59 | 28.74 | 30.66 | 23.39 | 0 | 0 | 0.218 | 0 | PASS |
| L3 | 3 | 20 | 100.0 | 100.0 | 16.63 | 24.65 | 24.75 | 30.65 | 0 | 0 | 0.282 | 0 | PASS |
| L4 (small) | 1 | 20 | 100.0 | 100.0 | 46.11 | 55.3 | 55.36 | 12.46 | 0 | 0 | 0.235 | 0 | PASS |

L2: a worker holding a lease was SIGKILLed; its job was claimed 2 times, ended SUCCESS with 1 terminal event(s), 66.44 s after the kill.

Throwaway stack with a fake LLM (seeded 1-6 s latency, ~8 % 429 with Retry-After), so times measure the queue and service, not real model latency. Time = submit to first poll that sees a terminal status (client clock, polls every 2 s). VALID = JobStatus shape + the frozen contract check. Lost/dup from the DB event log and a re-GET of every job. Source: `eval/load.jsonl`, latest line per scenario + workers (`scripts/load_test.py`). Code: 6f2da24-dirty.
<!-- /AUTO:load -->

These runs (P8a, fake model) are the evidence for the 2-worker default: throughput rose from
1 to 2 and 3 workers, no job was lost or duplicated, and a SIGKILLed worker's job finished
once after the lease ran out (`logs/P8a_load_report.md`).

## Where it fails

- **Big tables:** one call returns a handful of rows from a 325-row rent roll; rentroll_001
  and t12_001 score near 0 on the baseline.
- **Smart path (P5 lessons):** after the checker fix, what remains is mostly the model
  returning null (10–12 fields per lease) and short text or dates not inside their quote
  (4–6 per lease); computed fields with no parts (lease term) stay 0 (`logs/P5b_report.md`).
- **A value can pass the quote check and still be wrong:** the checker proves the value is
  in the quoted text, not that the model quoted the right passage. In the offline hybrid
  simulation (P5c, 3 runs per doc), 4 fields took a checked smart value that scored below the
  baseline's correct value, because the quote existed but was the wrong span
  (`logs/P5c_hybrid_sim.md`, per-field table).
- **Stuck parser (PR-65):** no separate parse timeout or killable child process; a hostile
  or huge file holds a worker slot until the job deadline ends it `PARTIAL`. Not seen in load
  runs (max slot time 12.6 s over 110 jobs).
- **Fuzzy list items** keep the model's spelling, not the matched source text.
- **DOCX page numbers:** LibreOffice not added (A-12), so DOCX citations carry no page.
- **Load numbers** use a fake model with 1-6 s replies; real latency is longer and is noted
  separately.

## Next steps

(filled in at the end)
