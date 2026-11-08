# P9f Part B — outputs/ (Z-76), no LLM calls

## Result: fallback (b), all 8 outputs keep v1.0 unchanged

Z-76 (a) needed run 174's job ids, to fetch each DEV result with `GET /jobs/{job_id}`.
They are not available through any allowed route:
- `eval/history.jsonl` records scores per doc, not job ids. Run 174's line points to a raw folder
  under the dev run store, which the agent never reads (hard rule 2).
- `logs/P9e_report.md` and `logs/P9e_eval_full_174.md` have no job ids. A UUID search over `eval/`
  found 0 matches.
- The API has no list endpoint (`GET /health`, `POST /jobs`, `GET /jobs/{job_id}` only).
  Reading the database directly would not be "via our own API".

So the pre-approved fallback applied: **all 8 files unchanged**.
`git diff --stat v1.0 -- outputs/` is empty, and the last commit touching `outputs/` is `c01b567`.

## Per file

| File | Source run | Settings label | VALID |
|---|---|---|---|
| boxscore_001.json | sealed run 90 (P8b, `c01b567`) | v1.0 | VALID |
| lease_001.json | sealed run 90 | v1.0 | VALID |
| lease_002.json | sealed run 90 | v1.0 | VALID |
| om_001.json | sealed run 90 | v1.0 | VALID |
| rentroll_001.json | sealed run 90 | v1.0 | VALID |
| t12_001.json | sealed run 90 | v1.0 | VALID |
| held-out doc 1 (lease type) | sealed run 90 | v1.0 | VALID |
| held-out doc 2 (budget type) | sealed run 90 | v1.0 | VALID |

The validation was run with `uv run python tools/validate.py outputs/ --schema-dir sample/schemas`.
It exited 0. Single-file mode (`--schema`) printed VALID for each of the 8.

**Consequence for docs (Part C):** `outputs/` reflects v1.0 code, not the shipped v1.1 settings.
README must say so. The v1.1 scores for these docs come from run 174 (`eval/history.jsonl`);
those outputs were not reproducible offline. Values were never printed.
