# Outcome DocExtract

Document extraction service for the Outcome take-home.
**Role applied for: AI/ML Developer.**

## What it does

`POST /jobs` takes a document (PDF, DOCX, XLSX or CSV) and a field list (JSON), and returns a
job id at once. A worker reads the document, asks a model for the fields, checks the answer in
code and stores a result in the fixed contract format (`contract/`). `GET /jobs/{job_id}`
returns it once the job is terminal (`SUCCESS`, `PARTIAL` or `FAILED`). Every job ends
terminal with a schema-valid answer, even when a worker crashes or the model is unreachable.
Design and evidence: [DESIGN.md](DESIGN.md).

## How to run

Needs Docker (Compose v2). From the repo root:

```bash
cp .env.example .env        # fill in LLM_BASE_URL and LLM_API_KEY (or export them in the shell)
docker compose up -d --build
curl -s localhost:8080/health          # {"status":"ok",...} once the DB answers
```

The api listens on **port 8080**. All model calls go through `LLM_BASE_URL` / `LLM_API_KEY`.
Without a key the service still starts and every job still ends terminal with a valid answer.

Submit a document and poll it:

```bash
curl -s -F "file=@path/to/doc.pdf" -F "schema=<path/to/field_list.json" localhost:8080/jobs
curl -s localhost:8080/jobs/<job_id>
```

Optional header `X-Organization-Id` scopes a job to a tenant (another tenant gets 404).
Two workers start by default; change it with `docker compose up -d --scale worker=N`.

## Configuration

`compose.yaml` passes only the variables marked "compose"; it has no `env_file`, and the LLM
variables use the `${VAR:-}` form, so an unset variable is empty, never an error. A test
(`tests/test_shipped_config.py`) pins these shipped settings.

| Variable | Default | Set via | Meaning |
|---|---|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY` | empty | compose (worker) | all model calls go through these |
| worker replicas | 2 | compose `deploy.replicas` | `--scale worker=N` overrides it |
| `JOB_DEADLINE_S` | 1500 | compose | after this, a job ends `PARTIAL` with an all-null result |
| `MAX_PENDING` | 500 | compose | `429` + `Retry-After: 30` when this many jobs wait |
| `LEASE_S` / `HEARTBEAT_S` | 60 / 15 | compose | worker lease and heartbeat |
| `SWEEP_EVERY_S` | 5 | compose | how often a worker checks deadlines and dead leases |
| `EXTRACT_SINGLE_VALUE_PATH` | `baseline` | compose (worker) | `smart` turns on the evidence-checked path (measured, not shipped) |
| `DOCX_PAGE_METHOD` | `none` | compose (worker) | DOCX has no pages; `estimate` guesses them |
| `APP_VERSION` | `dev` | compose | shown by `/health` |
| `LLM_MAX_CONCURRENCY` | 4 | code default | model calls in flight per worker |
| `LLM_MAX_CALLS_PER_DOC` / `LLM_MAX_USD_PER_DOC` | 8 / 0.05 | code default | per-document call and $ fuse |
| `LLM_REQUEST_TIMEOUT_S` | 120 | code default | per HTTP attempt |

Dev-only settings (`DEV_BUDGET_USD`, the response cache) live in `compose.dev.yaml` and are
never part of the shipped stack.

## Scores on the sample set

<!-- AUTO:scores -->
| Pipeline | Path | Date | Docs | Runs | Mean score | Per document | All VALID |
|---|---|---|---|---|---|---|---|
| baseline-v1 | baseline | 2026-11-07 | 6 | 1 | **0.579** | boxscore_001 1.000, lease_001 0.700, lease_002 0.775, om_001 0.948, rentroll_001 0.006, t12_001 0.046 | yes |
| single-value-v1 | smart | 2026-11-08 | 3 | 3 | **0.740** | lease_001 0.592, lease_002 0.708, om_001 0.920 | yes |

Score = `tools/validate.py` `score()`: mean over documents of each document's mean of per-field means (strict match after normalisation). DEV documents only; the 2 held-out documents are not scored until the final run. Runs = live runs in the series (a doc's score is the mean over runs). Source: `eval/history.jsonl`, latest series per pipeline + path. Shipped default path: `baseline`.
<!-- /AUTO:scores -->

The shipped `outputs/` files for the DEV documents come from the P2 baseline run (0.599 on
DEV, n = 6, `logs/P2_eval.md`); the P3 re-run of the same baseline scored lower, so the P2
files were kept. Per-run detail: `logs/P2_eval.md`, `logs/P3_eval.md`, `logs/P5_report.md`,
`logs/P5b_report.md`.

## Load results

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

Detail and method: [logs/P8a_load_report.md](logs/P8a_load_report.md).

## Outputs

`outputs/<document>.json`: one result per sample document (8 files), each the job's `result`
plus `schema` and `document` keys. They are produced through the running service by
`uv run python scripts/make_outputs.py <doc_id> ...` and checked with
`uv run python tools/validate.py outputs/ --schema-dir sample/schemas` (exit 0 = all valid).
`sample/` (the provided documents and answers) is not in the repository.

## Develop

```bash
uv sync                                   # Python 3.12 env from uv.lock
uv run pytest                             # needs Docker (Postgres testcontainer); no network, no key
uv run ruff check . && uv run ruff format --check .
uv run python scripts/render_docs.py      # refresh the measured blocks in README/DESIGN
uv run python scripts/load_test.py        # load + chaos test on a throwaway stack, fake LLM
uv run python scripts/make_zip.py         # submission zip with safety checks (clean tree)
```

## Known limitations

- **Big tables:** the one-call baseline returns only a few rows of a large rent roll or
  operating statement (scores near 0 on those two DEV documents). Table documents need
  chunking.
- **DOCX page numbers:** none. A DOCX has no pages, and the LibreOffice renderer that could
  place them was not added (image size, start-up time).
- **Smart path not shipped:** the evidence-checked path scored below the baseline in 3 live
  runs per document, so it stays behind a switch.
- **A stuck parser** (a hostile or huge file) is bounded only by the job deadline, which ends
  the job `PARTIAL`; there is no separate parse timeout.
- **Load numbers use a fake model** (1-6 s replies); real model latency is longer.
- **Held-out set:** the planning chat saw the held-out answers before the split (see DESIGN).

## AI assistance

Built with Claude Code as a coding assistant. Every design decision, review and commit is
mine. How it was used:

- **Workflow:** each phase had a written plan and a decision table that I approved before
  any code. The agent implemented only approved rows, wrote tests first where listed, and
  stopped at fixed points for my review. I wrote every commit.
- **Guard rails:** deny rules and a pre-tool hook kept the agent away from secrets, the
  answer files and the held-out documents. When a guard blocked it, the agent stopped and
  reported instead of finding another route.
- **Corrections I made (examples):**
  - P5b: the checker kept the model's number when a quote matched within tolerance; I had it
    output the number the source states instead, and treat an empty list as a null answer.
  - P5b: I narrowed the free-text rule to "the model's value as found inside the source span,
    else the span".
  - P8a: I set the small-machine memory limit to 3 GB to fit the Docker VM, and made 2 workers
    the shipped default after the scaling run.
  - Throughout: drafted commit messages carry no AI trailer; the agent never commits.
