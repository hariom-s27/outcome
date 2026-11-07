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

## What broke and how it was handled

- Schemathesis' "valid data must be accepted" check cannot pass against this contract (any
  string is a valid `schema` part, but invalid JSON must get 400), so that one check is off;
  the others run.

## With another week

(filled in at the end)
