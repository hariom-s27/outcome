# Outcome DocExtract

Document extraction service for the Outcome take-home.
**Role applied for: AI/ML Developer.**

`POST /jobs` takes a document (PDF, DOCX, XLSX or CSV) and a field list, and returns a job id
at once. A worker fills a result in the fixed contract format (`contract/`), which
`GET /jobs/{job_id}` returns once the job is terminal.

> **Status: milestone M1 (skeleton).** The service, queue and crash safety are in place;
> every job returns a schema-valid **all-null** result (`PARTIAL`). Real extraction starts
> in the next phase. Design notes: [DESIGN.md](DESIGN.md).

## Run

Needs Docker (Compose v2). From the repo root:

```bash
cp .env.example .env        # then fill in LLM_BASE_URL and LLM_API_KEY
docker compose up -d --build
curl -s localhost:8080/health          # {"status":"ok",...} once the DB answers
```

Submit a document and poll it:

```bash
curl -s -F "file=@path/to/doc.pdf" -F "schema=<path/to/field_list.json" localhost:8080/jobs
curl -s localhost:8080/jobs/<job_id>
```

Optional header `X-Organization-Id` scopes a job to a tenant (another tenant gets 404).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY` | empty | all model calls go through these (worker only) |
| `JOB_DEADLINE_S` | 1500 | after this, a job ends `PARTIAL` with an all-null result |
| `MAX_PENDING` | 500 | `429` + `Retry-After: 30` when this many jobs wait |
| `LEASE_S` / `HEARTBEAT_S` | 60 / 15 | worker lease and heartbeat |
| `SWEEP_EVERY_S` | 5 | how often a worker checks deadlines and dead leases |

Scale workers with `docker compose up -d --scale worker=N`.

## Develop

```bash
uv sync                                   # Python 3.12 env from uv.lock
uv run pytest                             # needs Docker (Postgres testcontainer); no network, no key
uv run ruff check . && uv run ruff format --check .
uv run python scripts/make_outputs.py <doc_id> ...    # outputs/<doc>.json via the running service
uv run python tools/validate.py outputs/ --schema-dir sample/schemas
uv run python scripts/chaos_kill_worker.py            # kill/freeze a worker mid-job (~5 min)
```

`sample/` (the provided documents and answers) is not in the repository.

## Scores on the sample set

| Milestone | Valid outputs (`tools/validate.py`) | Mean score |
|---|---|---|
| M1 skeleton | 8/8 VALID | not scored: every value is null by design |
| M2 baseline (one Haiku 5.5 call per document) | 8/8 VALID | **0.599** on DEV, n = 6 · ≈ $0.0055 per document (uncached) |
| P3 proper readers, same one-call baseline | 8/8 VALID (P2 outputs kept) | 0.579 on DEV, n = 6 · ≈ $0.0049 per document (uncached) · lower than P2, so the P2 outputs stay |

Mean score = mean over documents of each document's mean of per-field means, as computed by
`tools/validate.py` `score()` (strict exact match after normalisation). Per-document numbers
and error counts: `logs/P2_eval.md`, `logs/P3_eval.md`; every run is appended to
`eval/history.jsonl`.
$/document is the uncached cost: a document answered from the dev cache is priced at the ledger
cost of the call that filled the cache, since a grader's run has no cache.

Scores are reported on the 6 development documents during the build; 2 documents are held
out until the final run (see DESIGN.md).

P4 model and method measurements (vision models, page method, noise floor, call grouping): [logs/P4_report.md](logs/P4_report.md).

## AI assistance

Built with Claude Code as a coding assistant; every design decision, review and commit is mine.
