# P4 report — Session 2 of 2 (pilot + paid spikes, measure only)

## PLAIN SUMMARY

P4 measured four things on the DEV documents. No shipped default changed (P4-14).
Spend this session was **$0.2674**. That counts every call at max(reported, computed), with
GLM priced at its computed rate. The approved total was $0.35.

- **B1 (vision bake-off):** Gemini 3.8 Flash scored highest on the 25-page scanned lease
  (0.825). Haiku 5.5 and GLM-5.3 Flash scored 0.800, which is one field fewer, at about 1/13
  of Gemini's cost.
- **B2 (page method):** locate-then-read on Haiku matched Gemini's score (0.825) at $0.0057,
  about 1/22 of Gemini's cost. It found the fields on 8 of the 25 pages. OCR text scored
  0.775, but local OCR took 768 s of wall time.
- **B3 (noise floor):** om_001 and lease_002 move by at most 0.017–0.025 between identical
  runs. That is one field on these 40-field lists. rentroll_001 scores about 0 on every run,
  because the shipped baseline returns 2–3 of 325 rows.
- **B4 (one call vs 3 groups):** grouping does not pay. It costs 2.3× as much, and the score
  change is ±0.025 (one field), inside the noise floor.

**For P5/P6:** keep Haiku 5.5 with one call for text documents. Use locate-then-read for
scanned PDFs. Treat a difference of ≤ 0.025 as noise. Count cost as max(reported, computed).
Table documents need row chunking, because no prompt or model choice fixes 2 of 325 rows.

## Runs (all from commit `68071bd`, except the pilot at `a6e43fd`; every tree was clean)

| Run id | Spike | Cap | Spent (ledger) | Spent max(rep, comp) | Stop |
|---|---|---|---|---|---|
| `a6e43fd-b1-20261107T214016Z` | pilot (B1, Haiku, 8 pages) | $0.01 | $0.0030 | $0.003045 | none |
| `68071bd-b1-20261107T214635Z` | B1 | $0.22 | $0.1627 | $0.178363 | none |
| `68071bd-b2-20261107T221743Z` | B2 (b, c) | $0.02 | $0.0114 | $0.011355 | none |
| `68071bd-b3-20261107T221851Z` | B3 | $0.06 (raised from 0.05, Hariom) | $0.0520 | $0.052049 | **max_usd** (last call) |
| `68071bd-b4-20261107T222122Z` | B4 | $0.03 | $0.0226 | $0.022607 | none |
| local OCR `ocr-lease_001` | B2 (c) input | — | $0 | $0 | — |
| **Session** | | $0.35 | **$0.2517** | **$0.267419** | |

The two spend columns differ for two reasons. The ledger takes the gateway's reported cost,
and GLM reported $0 (see "where it failed"). Qwen's computed cost is also above its reported
cost. Every line is in `eval/spikes.jsonl`: 21 lines, one per prediction.

## B1: vision bake-off (lease_001, scanned PDF, 25 pages, 40 fields; 4 batches of ≤ 8 pages per model; n = 1 run each)

| Model (requested = returned) | Score | Wrong / missed / halluc. | $ max(rep, comp) | $ reported / computed | Latency | Calls | Reasoning tok | Image tok/page* | JSON mode | Batch conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| google/gemini-3.8-flash | **0.825** | 2 / 5 / 0 | 0.126743 | 0.126743 / 0.126743 | 166 s | **5** (4 batches) | 18,656 | 896 | ok | 4 |
| anthropic/claude-haiku-5.5 | 0.800 | 4 / 4 / 0 | 0.009764† | 0.009764 / 0.009764 | 31 s† | 4 | 0 | 2,095 | ok | 3 |
| z-ai/glm-5.3-flash | 0.800 | 4 / 4 / 0 | 0.012341 | **0** / 0.012341 | 66 s | 4 | 2,217 | 1,767 | ok | 3 |
| openai/gpt-6-luna | 0.725 | 4 / 7 / 0 | 0.011144 | 0.011144 / 0.009799 | 84 s | 4 | 4,612 | 1,593 | ok | 6 |
| qwen/qwen3-vl-235b-a22b-instruct | 0.675 | 4 / 8 / **1** | 0.021415 | 0.018073 / 0.021415 | **682 s** | 4 | 0 | 1,246 | ok | 7 |
| Pilot: Haiku, first 8 pages only | 0.675 | 5 / 8 / 0 | 0.003045 | 0.003045 / 0.003045 | 14 s | 1 | 0 | 2,058 | ok | 0 |

\* Image tokens per page are a rough number: (prompt tokens − text characters ÷ 3) ÷ images.
They compare models on the same pages. They are not an exact per-image price.
† One of Haiku's 4 batches was answered from the dev cache, because it repeated the pilot
call. The run actually paid $0.00672. The table shows the uncached cost of all 4 calls. That
batch's latency is not a fresh measurement.

No model needed a repair call. Every model returned the id it was asked for. JSON mode was
accepted every time. No model hit the cap.

## B2: page method (lease_001, Haiku 5.5, n = 1 run each)

| Method | Score | Wrong / missed / halluc. | $ | Calls | Latency | Pages / images sent | Other |
|---|---|---|---|---|---|---|---|
| (a) batches of ≤ 8 + merge (B1 Haiku, reused, no new calls) | 0.800 | 4 / 4 / 0 | 0.009764 | 4 | 31 s | 25 pages | 3 batch conflicts |
| (b) locate-then-read | **0.825** | 5 / 2 / 0 | **0.005722** | 5 (4 locate + 1 read) | 32 s | 25 thumbnails + 8 full pages | ~636 tok/image across the 33 images |
| (c) local OCR text → Haiku | 0.775 | 8 / 1 / 0 | 0.005633 | 1 | 11 s + **768 s OCR** | 0 images; 67,385 OCR characters | OCR 5,659 CPU-s, 1,285 lines, 25 pages |

## B3: noise floor (Haiku 5.5 baseline as shipped, `--no-cache`, 3 identical runs per document)

| Doc | n | Scores | Mean | Spread | $ per run | Note |
|---|---|---|---|---|---|---|
| om_001 | 3 | 0.948 / 0.966 / 0.948 | 0.954 | **0.017** | 0.0028–0.0029 | one field moves |
| lease_002 | 3 | 0.825 / 0.825 / 0.825 | 0.825 | 0.000 | 0.0040 | the same 7 wrong each run |
| rentroll_001 | 3 (2 complete) | 0.006 / 0.009 / 0.000 | 0.005 | 0.009 | 0.0067–0.0156 | 2 and 3 of 325 rows; input truncated; r1 and r3 stopped at the 8,192 output-token limit; **r3's second call was skipped by the cap** (partial, output file not schema-valid) |

Counting B4's "one call" variant, which is the same baseline on the same documents, n rises
to 4. om_001 then has spread 0.017 (0.948 ×3, 0.966), and lease_002 has spread **0.025**
(0.825 ×3, 0.800 with 1 hallucinated field).

## B4: one call vs 3 field groups (Haiku 5.5, n = 1 per variant)

| Doc | Variant | Score | Wrong / missed / halluc. | $ | Calls | Latency | Tokens in |
|---|---|---|---|---|---|---|---|
| om_001 | one call | 0.948 | 2 / 0 / 0 | 0.002885 | 1 | 6.9 s | 20,287 |
| om_001 | 3 groups | 0.966 | 1 / 0 / 0 | 0.006749 | 3 | 11.7 s | 58,583 |
| lease_002 | one call | 0.800 | 7 / 0 / 1 | 0.003992 | 1 | 9.8 s | 26,956 |
| lease_002 | 3 groups | 0.775 | 8 / 0 / 1 | 0.008980 | 3 | 14.7 s | 76,474 |

Grouping sends the whole document 3 times, so it costs 2.3× as much and adds 5 s of
latency. The score change is +0.017 on om_001 and −0.025 on lease_002, inside the B3 noise
floor.

## Recommendations for P5/P6 (n = runs behind each number)

| Topic | Recommendation | Numbers behind it | n |
|---|---|---|---|
| Scan model | **Haiku 5.5** | 0.800 (batches) and 0.825 (locate) vs Gemini 0.825 at $0.127 (13–22× the cost). GLM ties Haiku at 0.800 but takes 66 s and reports $0. Luna scores 0.725. Qwen scores 0.675 with 1 hallucinated field and takes 682 s | 1 scanned doc, 1 run per model |
| Page method (scans) | **(b) locate-then-read** | 0.825 at $0.0057 and 32 s vs (a) 0.800 at $0.0098 and (c) 0.775 with 768 s of host OCR. Sends 8 of 25 pages at full size | 1 doc, 1 run per method |
| Call grouping | **One call** for all fields | Groups cost 2.3× (om_001) and 2.25× (lease_002). The score change (+0.017 / −0.025) is within the noise | 2 docs, 1 run per variant |
| Noise floor per doc | Treat **≤ 0.025** as noise on the 40-field docs | om_001 spread 0.017 (n = 4); lease_002 spread 0.025 (n = 4). rentroll_001 0.000–0.009 is not informative while 2–3 of 325 rows come back | 3 docs × 3 runs (+1 from B4) |
| Table docs | Chunk rows (P5/P6 design item, not measured here) | rentroll_001: 2–3 of 325 rows; input truncated (811 of 3,073 blocks); 2 of 3 runs hit the 8,192 output limit | 3 runs |
| Reasoning: Haiku 5.5 | keep `none` (shipped) | 0 reasoning tokens in all 29 Haiku calls; scores as above | 29 calls |
| Reasoning: GPT-6 Luna | lower the setting if Luna is ever used | 4,612 reasoning tokens over 4 calls, the lowest score of the 5 models | 4 calls |
| Reasoning: GLM-5.3 Flash | reasoning is mandatory; budget for it | 2,217 reasoning tokens over 4 calls | 4 calls |
| Reasoning: Gemini 3.8 Flash | if used: the lowest setting plus a larger output limit | 18,656 reasoning tokens over 5 calls; 1 call stopped at the output limit and was re-sent | 5 calls |
| Reasoning: Qwen3-VL instruct | none (no reasoning mode) | 0 reasoning tokens | 4 calls |
| Cost accounting | ledger and caps use **max(reported, computed)** | GLM reported $0 vs $0.0123 computed; Qwen reported 0.0181 vs 0.0214 computed; Luna reported 0.0111 vs 0.0098 computed | 12 calls |

## Where it failed

1. **GLM's gateway cost report is $0.** All 4 GLM calls reported a cost of 0, and the spike
   wrapper prefers a reported number over the computed one. So the launcher's P4 total missed
   **$0.012341**. The real session spend ($0.2674) is still under the $0.35 cap. A ledger that
   trusts a reported $0 can let a cap be passed without anyone seeing it.
2. **Gemini made one extra call and sent 8 extra images.** It made 5 calls for 4 batches and
   sent 33 images for 25 pages. One call ended with `finish_reason=length`: Gemini's reasoning
   used up the output budget (18,656 reasoning tokens over the run). That 8-page batch was sent
   again, without the `repair` purpose tag. The extra call is part of the $0.127.
3. **The B3 cap stopped the last item.** rentroll_001 run 3 hit the 8,192 output-token limit
   on its first call. Its second call was skipped by the run cap ($0.06). Its spike output
   file is not schema-valid. That is a spike file, not a service output; `outputs/` is
   unchanged.
4. **rentroll_001 cannot be measured with the baseline.** It returns 2–3 rows of 325 on every
   run, so its noise floor says nothing useful.
5. **Qwen3-VL latency was 682 s for 4 calls.** That alone rules it out for a worker with a
   per-job deadline.
6. **Local OCR is slow on CPU.** It took 768 s of wall time and 5,659 CPU-seconds for 25
   pages. Method (c) is not practical inside the job deadline as built.
7. **A guard block:** to find the B4 run id, I sent a command that listed the spike runs
   folder. `guard.py` blocked it ("touches cache/"). I stopped and reported it. Hariom approved
   scoring with the literal run id, which was already printed in B4's output.
8. **Cache hit in B1-Haiku:** batch 1 repeated the pilot call, so it came from the dev cache
   ($0 paid, no fresh latency). B1 did not run with `--no-cache`.
9. **The pilot's progress was not visible,** because its output was piped through
   `Select-Object -Last`, which holds every line until the end. Later runs streamed their
   output line by line.

## Deviations

- **Scorer extended before the paid runs** (`scripts/spikes/p4_score.py` `call_stats`, plus 2
  tests with invented data). The jsonl needed the per-call byproducts the brief asks for.
  Hariom committed it before Part C (`68071bd`).
- **B3 cap raised from $0.05 to $0.06** on Hariom's instruction. The total cap stayed at $0.35.
- **The DESIGN.md Spend table got a P4 row and a new running total,** in addition to the 3
  lines asked for, so the running total there stays true.

## Checks

- pytest: `231 passed, 1 warning, 95 subtests passed in 49.29s` (the existing starlette
  warning).
- ruff: `All checks passed!`; `92 files already formatted`.
- pre-commit `--all-files`: all 7 hooks `Passed`. The same with `--files eval/spikes.jsonl
  logs/P4_report.md DESIGN.md README.md`: all 7 `Passed`, including "no sample answer values
  in text".
- `tools/validate.py outputs/ --schema-dir sample/schemas`: exit 0. Single-file mode: 8/8
  `VALID` (boxscore 10 entries, t12 6, rentroll 36, the others 1). `outputs/` is unchanged
  in P4.

## SELF-AUDIT (CLAUDE.md hard rules)

1. `.env` / `.env.*`: not read, and no environment variable printed. The key stayed inside
   compose's environment.
2. Answers, `lease_003`, `budget_001`, `cache/`: not read with agent tools. The host scorer
   read the DEV answers inside its own process and printed counts and scores only. The answers
   folder was never mounted into a container. One command that listed the cache folder was
   blocked by the guard (where it failed, item 7). It read nothing.
3. Frozen files (`contract/`, `tools/validate.py`, `ASSIGNMENT.md`, `sample/`): not edited.
4. No `git commit`, `push`, `reset --hard` or `rebase` by the agent. Commit lines are drafted
   only.
5. No sample or answer value appears in any file, log, test or message. Only doc ids, scores,
   counts, tokens, $ and latency are used. `eval/spikes.jsonl` holds field names and numbers
   only.
6. Every LLM call went through the wrapper in the worker container, with `LLM_BASE_URL` /
   `LLM_API_KEY` from compose. Only listed model ids were used, and each returned model id
   matched the request.
7. The default test run is still offline with no key. The 2 new tests use invented
   `calls.jsonl` lines.
8. Logs and outputs carry metadata only: run ids, statuses, timings, tokens and $. OCR printed
   counts only.
9. No service job was run or changed. `outputs/*.json` are unchanged and valid (see Checks).
10. No dependency was added. RapidOCR ran in a temporary `uv run --with` environment and is
    not in `pyproject.toml`, `uv.lock` or the image. Only P4-table decisions were applied.
    `--allow-dirty` and `--skip-dry-run` were never used, and every run's tree was clean.

## RUNNING TOTAL

| | $ |
|---|---|
| Before P4 Session 2 | 0.127749 |
| This session (max(reported, computed); 45 paid calls + 1 cache hit) | 0.267419 |
| **Running total** | **0.395168** |
