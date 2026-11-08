# DESIGN

One page, kept current as the build goes. Status: **M1 skeleton** (service, queue, crash
safety; every job returns a valid all-null result). Extraction design follows from P2.

## Shape

One Python 3.12 image, three roles: **api** (FastAPI), **worker**, and **Postgres 17** as both
the database and the job queue. No Redis: Postgres `FOR UPDATE SKIP LOCKED` gives a correct
queue with one less moving part, and the job, its file and its event log commit in the same
transaction. Uploaded files are stored in a Postgres table and deleted once the job is
terminal, so there is no shared volume between api and worker. Workers scale with
`--scale worker=N`.

## Decisions so far (decision · why · number)

| Decision | Why | Evidence |
|---|---|---|
| Claim with SKIP LOCKED + 60 s lease + 15 s heartbeat + fence token | a dead or frozen worker must not lose or duplicate a job | chaos run: SIGKILL'd worker's job re-claimed (fence 2) and finished once, 85 s after the kill; a paused worker's late write rejected (`logs/P1_chaos.txt`) |
| Terminal statuses enforced in the DB (compare-and-set + trigger + one terminal event per job) | the contract says terminal never changes; code bugs should not be able to break that | trigger and unique-index tests |
| Deadline 1500 s from submission → `PARTIAL` with an all-null result | the harness gives 1800 s; a null answer beats a timeout (zero) | sweeper runs every 5 s in its own thread |
| A job claimed more than 3 times → `PARTIAL` all-null (poison job) | one bad document must not loop forever or block a worker | crash-loop and repeated-error tests |
| `PARTIAL` reason in `result.metadata.terminal_reason`; `error` only for `FAILED` | keeps `error` meaningful | |
| `429` + `Retry-After: 30` at 500 pending; `413` above 50 MB | back-pressure the harness understands | |
| `/health` 200 only if the DB answers `SELECT 1` within 1 s | "up" should mean "can accept jobs" | DB stopped → 503 in about 1.1 s |
| File type accepted if extension **or** content says PDF/DOCX/XLSX/CSV | refusing a supported file fails the document; a wrong extension should not | |
| Field list validated loosely (non-empty `fields` object) | unfamiliar field lists must work | |
| Logs carry job id, status, timings only | documents may be confidential | |
| Base images pinned tag@digest, multi-arch, no `platform:` | same build on the grader's machine (amd64 or arm64) | fresh clone: cold build 18 s, `up` → `/health` 200 in 5.6 s |
| Baseline: rough readers (text with page/cell addresses; scanned pages as JPEG) + one Haiku 5.5 call with all fields, code checks the JSON, null over guess | a cheap, honest floor to measure every later change against | DEV mean 0.599 (n = 6): single-value docs 0.70–1.00, big tables 0.05–0.11 (the model returns 6 of 119 and 36 of 325 rows); ≈ $0.0055/doc uncached (`logs/P2_eval.md`) |
| Per-document $ fuse, predicted before every call (P2-36) | the old cap only looked at money already spent, so one call could overshoot it 1.3× | input estimated high (1.5 chars/token, 2,600 tokens per image, +15%), whole call priced at the cliff rate when the estimate reaches it; trim the input, else skip → PARTIAL `doc_llm_cap`. Rent-roll re-run: estimate 79,469 vs real 57,118 tokens (1.39× high), $0.0097, fuse not needed |
| Proper readers, one document map (P3): XLSX/CSV rows with cell refs, merged/hidden/formula flags; DOCX XML walker (numbering, accepted tracked changes, text boxes, tables); PDF word → line → block model with callouts, header/footer tags and scan triage | the extractor should see the document's structure and exact addresses, not a flat dump | DEV mean 0.579 vs 0.599 (n = 6): om_001 0.948 vs 0.966, rentroll 0.006 vs 0.110 (P2's two rent-roll runs already ranged 0.009–0.110), others unchanged; P2 outputs kept (`logs/P3_eval.md`) |
| DOCX page numbers: pluggable method, default `none` (P3-27) | DOCX has no pages; a wrong page is worse than none | the `estimate` method placed 0/20 locatable lease_002 citations on the exact page (13/20 within ±1); a slim LibreOffice image gave 23 pages and 0/20 (the earlier, fuller-font build: 20/20, +474 MB), so it is decided at P8 |
| Haiku with `reasoning: {effort: none}` | its default is medium effort, billed as output | same score (1.000) on the pilot doc, 0 vs 3,964 reasoning tokens, $0.0095 vs $0.0108 |

**P4 measured (no default changed):** 5 vision models on the 25-page scanned lease, 3 page methods, the run-to-run noise on 3 documents, and one call vs 3 field groups (`logs/P4_report.md`).
**Winners:** Haiku 5.5 for scans, locate-then-read for page choice, and one call for all fields. A difference of ≤ 0.025 counts as noise. Cost is counted as max(reported, computed), because one gateway reported $0.
**Numbers:** Haiku locate-then-read 0.825 at $0.0057 vs Gemini 3.8 Flash 0.825 at $0.127. The noise spread is 0.017 on om_001 and 0.025 on lease_002 (n = 4 each). Field groups cost 2.3× for ±0.025. rentroll_001 returns 2–3 of 325 rows, so table documents need chunking.

**Confidence (P5-17, placeholder until P7 calibrates it):** a hand rule over how each value was
verified, not the model's own number. Exact quote with the value in it 0.90 · fuzzy quote 0.75 ·
computed from verified parts 0.80 · read from a page image 0.70 · null 0.60; the model saying
"low" −0.15; a lease expiration that disagrees with commencement + term −0.20; clipped to
[0.05, 0.95]. Not yet measured against accuracy.

**P5 built (not shipped):** a "smart" path for single-value field lists, behind `EXTRACT_SINGLE_VALUE_PATH` (default `baseline`). The model quotes evidence for each field, code checks the quote and normalises the value, and anything unproven becomes null. Scans use locate-then-read.
**Ship rule (written before the paid runs):** switch only if the 3-doc mean of 3-run means is ≥ old mean + 0.025, and no doc's mean is more than 0.025 below its old score.
**Numbers:** score = validate.py doc score, 3 live runs per doc, old = P2 outputs. lease_001 0.342 vs 0.700, lease_002 0.700 vs 0.775, om_001 0.908 vs 0.966. Mean 0.650 vs the 0.8385 bar, so the default stays `baseline`. The main cause is that scan answers whose page reference could not be matched were nulled (`loc_unknown`: 25 of 40 lease_001 fields in run 1). $0.0446 for 10 doc-runs (`logs/P5_report.md`).

## Evaluation honesty

Sample set split (D03): 6 development documents, 2 held out (one lease, and the only document
using the budget field list, to simulate an unseen field list). Prompts and rules are tuned on
the 6 only; the held-out 2 are scored once, at the end.

**Known contamination (disclosed):** before the split was made, the planning chat read every
answer file while exploring the sample set, including the two held-out answers. Since the
split, no prompt, rule or description is tuned on them, the coding agent is blocked from
opening them (deny rules + a hook, verified in `logs/P1_lockcheck.md`), and the evaluation
script leaves them out until the final run. The held-out score is therefore close to, but not
strictly, an unseen-data score.

## Spend

| Phase | Spend |
|---|---|
| P1 skeleton | $0 (no model calls) |
| P2 baseline (pilot ×2 + DEV eval) | $0.098 (9 paid calls; one call crossed Haiku's 100k price cliff: $0.064) |
| P2 rent-roll re-run (P2-35) | $0.0097 (1 paid call; plus 1 boxscore re-submit answered from the dev cache, $0) |
| P3 readers (DEV re-run, om_001 debug call, om_001 re-run) | $0.0198 (6 paid calls) |
| P4 measurements (pilot + 4 spikes; max(reported, computed)) | $0.267 (45 paid calls) |
| **Running total** | **$0.395** (61 paid calls) |

## What broke and how it was handled

- Schemathesis' "valid data must be accepted" check cannot pass against this contract (any
  string is a valid `schema` part, but invalid JSON must get 400), so that one check is off;
  the others run.
- The baseline's input-size estimate (chars/3.5) undercounted spreadsheet rows by ~1.9×, so
  one rent-roll request sent 114k tokens and paid Haiku's 5× long-prompt price. The estimate
  is now calibrated per block type (rows 1.75, prose 2.6 chars/token) and tested; the re-run
  estimated 59,965 and sent 57,118. A second, high-side estimate now guards the per-document
  $ cap before every call (P2-36).

## With another week

(filled in at the end)
