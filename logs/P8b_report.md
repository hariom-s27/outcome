# P8b — Session 2: sealed final run, final docs, final checks

## PLAIN SUMMARY

- **The sealed final run ran exactly once**: all 8 documents, shipped settings, cache off,
  run 90 on commit `c62ed30` (clean tree). Every call was live (0 replays). All 8 outputs
  are VALID (`tools/validate.py outputs/` exit 0).
- **DEV mean 0.801** (n = 6 documents, 1 run each), up from 0.599 for the P2 baseline.
  The gain comes from the table recipe on the long tables.
- **Held-out, scored once:** lease_003 **0.600**; budget_001 **0.013** (1 of 55 rows, one-call
  path). Nothing was changed after seeing these (Z-8).
- **Cost:** $0.020041 for the run, $0.00250 per document. **RUNNING TOTAL $0.567116.**
- **Load L1** re-run on the final code with the fake model: PASS (20/20 terminal, 0 lost,
  0 duplicates, 100 % VALID).
- **Docs:** README and DESIGN filled by script from the final run; new cost-vs-accuracy chart
  (`docs/cost_vs_accuracy.png`).
- **Two guard blocks this session, both reported** (see "Blocks").

## Final scores (sealed run 90, n = 1 run per document)

Score = `tools/validate.py` `score()`: a document's mean of per-field means.

| Document | Set | Path | Score | Rows pred/truth | Calls | $ |
|---|---|---|---|---|---|---|
| boxscore_001 | DEV | table:heuristic | 0.880 | 10/10 | 1 | 0.00088 |
| lease_001 | DEV | baseline | 0.650 | 1/1 | 1 | 0.00307 |
| lease_002 | DEV | baseline | 0.775 | 1/1 | 1 | 0.00401 |
| om_001 | DEV | baseline | 0.966 | 1/1 | 2 | 0.00392 |
| t12_001 | DEV | table:ai | 0.548 | 119/119 | 1 | 0.00117 |
| rentroll_001 | DEV | table:ai | 0.989 | 325/325 | 1 | 0.00116 |
| budget_001 | held-out, scored once | baseline | 0.013 | 1/55 | 1 | 0.00136 |
| lease_003 | held-out, scored once | baseline | 0.600 | 1/1 | 2 | 0.00448 |

- DEV mean = (0.880 + 0.650 + 0.775 + 0.966 + 0.548 + 0.989) / 6 = **0.801** (history
  `dev_mean_score` 0.8013).
- Mean over all 8 = 0.678 (history `mean_score` 0.6776); reported only for completeness.
- `output_flags`: none on any document. `scan_pages`: first on every document.
- Per-field detail (field names and counts only): `logs/eval_p8b_final.md`. Of that file I
  read only the boxscore_001 section (see "Blocks").

## What shipped

- `EXTRACT_TABLE_PATH=spec` (table recipe, P6b prompt wording per Z-17b),
  `SCAN_PAGE_METHOD=first`, `EXTRACT_SINGLE_VALUE_PATH=baseline`, 2 workers.
- Worker start lines before the run: `table_path=spec, scan_pages=first, cache_mode=off`
  (both workers).
- `outputs/`: all 8 files from run 90 (Z-7).

## Work this session

1. **eval_dev fix (before the run; committed by Hariom as 71c5850, c62ed30).**
   - Why: as written, `--final-sealed` could not run the held-out docs. Without `--docs` it
     ran the 6 DEV docs only, typing the held-out ids would hit the guard, and the dry-run
     gate refused held-out ids.
   - Change: `--final-sealed` with no `--docs` runs every manifest doc. The dry-run gate
     checks only the DEV docs. The history line now records `final`, `n_dev`,
     `dev_mean_score` and `held_out_per_doc`.
   - 4 tests added.
2. **Part C:**
   - Ran `eval_dev.py --final-sealed --expect-live --run-index 90 --write-outputs --max-usd 0.07
     --label p8b-final --report logs/eval_p8b_final.md` once.
   - Validated `outputs/` (exit 0, 8 files). History line appended (`final: true`).
3. **Chart (Z-9):**
   - `scripts/plot_cost_accuracy.py` (Pillow, already a dependency).
   - One point per config, each a 6-doc DEV mean. A config measured on fewer DEV docs is
     completed with the P2 baseline's per-doc score and $/doc.
   - Hybrid sim points are parsed from the committed `logs/P5c_hybrid_sim.md`; its $ is
     P5b + P2 (both calls).
   - The final point's $ is the run's 8-doc mean, because history has no per-doc $.
4. **render_docs:**
   - With a `final: true` line, `scores` / `results` show the sealed run (DEV and held-out
     apart), and `cost` shows its $/doc.
   - New `chart` block. The final line is never part of a run series.
   - 4 tests added.
5. **README / DESIGN:**
   - configuration (table path, scan page method);
   - scores from the final run;
   - the AI-assistance note (Claude for planning and review, Claude Code for implementation;
     corrections: the cache-replay catch, the two-digit-year window, guard false positives,
     the mis-set Z-17 bar);
   - DESIGN: table-recipe section, cost-vs-accuracy section, spend table to P8b, final
     "where it fails", next steps.
6. **Load L1:**
   - `scripts/load_test.py --scenarios L1` (own `loadtest` project, fake model, $0); line
     appended to `eval/load.jsonl`.
   - The script overwrites `logs/P8a_load_jobs.jsonl` / `logs/P8a_load_tables.md`. I copied
     this run's files to `logs/P8b_load_jobs.jsonl` / `logs/P8b_load_tables.md` and restored
     the P8a files with `git checkout --`.

## Where it fails (final; detail in DESIGN)

- **budget_001 (held-out, unseen field list): 0.013**, path `baseline`, 1/55 rows.
  INFERENCE: PDF table on the old path (recipes cover spreadsheets only). Its per-field
  section was not opened.
- **lease_003 (held-out): 0.600**, on the same path as the DEV leases (0.650 / 0.775 in this
  run).
- **Smart path tested 3 times, not shipped:** P5 0.650, P5b 0.740, P5c hybrid sim 0.8155 vs
  bar 0.8385.
- **A value can pass the quote check and still be wrong** (P5c: 4 fields).
- **Scanned leases see only the first pages** (8 of 25 for lease_001). Page choice was
  unstable (0.850 / 0.825 / 0.250, n = 3) and not shipped.
- **Box score:** `property_name` and `date` missed in all 10 rows in run 90 (read from the
  boxscore_001 section). `date` is null in all 5 live runs on the shipped prompt; scores were
  0.95, 0.95, 0.88, 0.88, 0.88. t12 period fields null. `parse` showed no live gain.
- **PDF and long tables on the old path** are cut off at the output cap (`truncated_output`,
  3 of 3 box runs).
- **Measure live:** a cache replay once stood in for a live score (box 1.000 vs 0.100 live).
- **Stuck parser:** no killable parse step; the deadline ends the job `PARTIAL`.
- **DOCX page numbers:** none provided.

## Blocks (guard hook; each stopped and reported)

1. **`.claude/` in a shell command.**
   - A read-only grep that named the guard file, combined with a grep of `scripts/`.
   - Blocked: shell commands may not touch `.claude/`. Nothing ran.
   - I then ran the `scripts/` grep alone (it was not the blocked part). I did not try to read
     the guard file in any form.
   - Hariom noted it and set the rule from then on: any block = full STOP, with no part of the
     command re-run.
2. **Sealed path.**
   - A read-only grep of `logs/eval_p8b_final.md` for the boxscore_001 and budget_001 sections.
   - Blocked: the command named a held-out id. Nothing ran.
   - Full STOP and report. Hariom chose option A: read only the boxscore_001 section, do not
     open the budget section, and tag the budget cause as INFERENCE.
   - The boxscore section was then printed with an `awk` range that names no held-out id.

## Spend

- Run 90: **$0.020041** (cap $0.07). Load L1, dry runs, tests: $0.
- Session total **$0.020041**.
- **RUNNING TOTAL $0.547075 + $0.020041 = $0.567116** (of $10).

## SELF-AUDIT

1. **Steps:**
   - Part C: worker check, dry run (6 DEV docs, passed), 1 sealed run, validate 8/8,
     history line.
   - Part D: render, chart, where it fails, README, L1, ruff / pytest / pre-commit, this
     report.
2. **Held-out discipline:**
   - lease_003 and budget_001 were opened only by `eval_dev.py --final-sealed`, once.
   - Their scores were printed by the script; I added no field-level reading of the budget.
   - No code or prompt change after the scores. The scripts changed afterwards are reporting
     only: `render_docs.py`, `plot_cost_accuracy.py`.
3. **Decisions not in the prompt:**
   - the eval_dev fix (approved and committed by Hariom before the run);
   - the composite rule for chart points;
   - saving the L1 logs as P8b copies and restoring P8a's;
   - `git add -N` (intent-to-add, no content staged) on the new files, so pre-commit
     `--all-files` scanned them.
4. **Numbers:**
   - Every score and $ is from the run-90 output / history line, or from committed reports
     (P2 to P8b part 1), as cited.
   - README / DESIGN blocks are rendered by script; `render_docs.py --check` reports up to
     date.
   - The budget cause is tagged INFERENCE.
5. **Checks:**
   - `uv run pytest`: 589 passed. Ruff check and format: clean.
   - `pre-commit run --all-files`: all passed.
   - `tools/validate.py outputs/ --schema-dir sample/schemas`: exit 0.
6. **Frozen files:** `contract/`, `tools/validate.py`, `ASSIGNMENT.md` untouched.
7. **Safety:**
   - no `.env`, `cache/` or answer files read by me;
   - no sample values in code, tests, docs or this report (doc ids, field names, counts,
     scores only);
   - no stack restarts or env changes (the L1 throwaway stack is the script's own project);
   - no commits.
