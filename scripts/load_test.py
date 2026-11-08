"""P8a load + chaos test against the throwaway load stack (A-3 ... A-8). $0: fake LLM only.

    uv run python scripts/load_test.py                 # L1 L2 L3 L4, then `down -v`
    uv run python scripts/load_test.py --scenarios L1  # one scenario

Every compose command is `docker compose -p loadtest --env-file tests/load/loadtest.env
-f compose.yaml -f compose.loadtest.yaml ...`: own project, own db volume, api on :18080, a
fake key, a fake LLM container. The main stack (project docextract, :8080) is never touched.

Scenarios (A-5):
  L1  graders' shape: 10 clients in flight, each POST /jobs then GET every 2 s to terminal;
      20 jobs cycling over the 6 DEV docs; 1 worker (the shipped default).
  L2  chaos: 2 workers, 10 jobs; ~10 s in, SIGKILL the worker holding a lease, then start it
      again. Every job must still end terminal exactly once.
  L3  scaling: 1, 2, 3 workers, 20 jobs each; throughput and p50/p95.
  L4  small machine: worker cpus 2 / mem_limit 3g (tests/load/compose.small.yaml), 1 worker,
      one L1 run.

Only the 6 DEV docs are sent; held-out ids are refused. Prints and writes metadata only
(doc ids, job ids, statuses, timings, counts): never document content or field values.
Outputs: eval/load.jsonl (one line per scenario), logs/P8a_load_jobs.jsonl (one line per job),
logs/P8a_load_tables.md (the report tables).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_dev import HELD_OUT  # noqa: E402
from make_outputs import DOCS, ROOT, SCHEMAS, TERMINAL, manifest, multipart  # noqa: E402

from app.contract_check import contract_errors  # noqa: E402

BASE = "http://localhost:18080"
ENV_FILE = "tests/load/loadtest.env"
COMPOSE = ["docker", "compose", "-p", "loadtest", "--env-file", ENV_FILE]
FILES = ["-f", "compose.yaml", "-f", "compose.loadtest.yaml"]
SMALL = ["-f", "tests/load/compose.small.yaml"]

IN_FLIGHT = 10
POLL_S = 2.0
MAX_JOB_S = 1800.0  # gate: every doc within 30 minutes
POST_LIMIT_S = 2.0  # A-6
VALID_MIN_PCT = 80.0  # gate
SLOT_FLAG_S = 60.0  # A-8 / PR-65: a job holding a worker slot longer than this is flagged
KILL_AFTER_S = 10.0  # L2

JOB_KEYS = {"job_id", "status", "created_at", "updated_at"}
JOB_OPTIONAL = {"stage", "result", "error"}
RESULT_KEYS = {"entries", "metadata"}
STARTED_RE = re.compile(r"started \(pipeline=(\S+), single_value_path=(\w+), cache_mode=(\w+)\)")

EVAL_OUT = ROOT / "eval" / "load.jsonl"
JOBS_OUT = ROOT / "logs" / "P8a_load_jobs.jsonl"
TABLES_OUT = ROOT / "logs" / "P8a_load_tables.md"


# --- documents -----------------------------------------------------------------------------------


def refuse_held_out(doc_ids: list[str]) -> None:
    sealed = [d for d in doc_ids if d in HELD_OUT]
    if sealed:
        raise SystemExit(f"refused: held-out documents are sealed ({len(sealed)} requested)")


def dev_docs(requested: list[str] | None = None) -> list[tuple[str, dict[str, str]]]:
    rows = manifest()
    if requested:
        refuse_held_out(requested)
        missing = [d for d in requested if d not in rows]
        if missing:
            raise SystemExit(f"unknown doc ids: {missing}")
        ids = list(requested)
    else:
        ids = [d for d in rows if d not in HELD_OUT]
    refuse_held_out(ids)  # belt and braces: never send a sealed doc
    return [(d, rows[d]) for d in ids]


# --- pure maths / checks (unit-tested) ---------------------------------------------------------


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile (numpy's default method); None for no values."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def throughput_per_min(n: int, wall_s: float) -> float:
    return 0.0 if wall_s <= 0 else n * 60.0 / wall_s


def result_valid(status: str | None, body: dict[str, Any], field_list: dict[str, Any]) -> bool:
    """JobStatus shape (contract/openapi.yaml) + output.schema.json top level + the frozen
    validator's validate_contract for SUCCESS / PARTIAL. FAILED carries no result -> False."""
    if status not in TERMINAL or not isinstance(body, dict):
        return False
    if not JOB_KEYS <= body.keys() or body.keys() - JOB_KEYS - JOB_OPTIONAL:
        return False
    if body.get("status") != status or "stage" in body:
        return False
    if status == "FAILED":
        return False
    result = body.get("result")
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        return False
    return not contract_errors(result, field_list)


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


def summarize(
    scenario: str,
    workers: int,
    records: list[dict[str, Any]],
    wall_s: float,
    terminal_events: dict[str, int],
    sha: str = "",
) -> dict[str, Any]:
    """One eval/load.jsonl line from per-job records and DB terminal-event counts."""
    accepted = [r for r in records if r["job_id"]]
    terminal = [r for r in accepted if r["status"] in TERMINAL]
    times = [r["terminal_s"] for r in terminal]
    n = len(records)
    dup = sum(1 for r in accepted if terminal_events.get(r["job_id"], 0) > 1)
    dup += sum(1 for r in accepted if r.get("changed_after_terminal"))
    by_doc: dict[str, list[float]] = defaultdict(list)
    for r in terminal:
        by_doc[r["doc_id"]].append(r["terminal_s"])
    statuses: dict[str, int] = defaultdict(int)
    for r in records:
        statuses[r["status"] or "none"] += 1
    posts_429 = sum(r["post_429s"] for r in records)
    return {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": sha,
        "scenario": scenario,
        "workers": workers,
        "n": n,
        "submitted": len(accepted),
        "terminal": len(terminal),
        "completion_pct": _r(100.0 * len(terminal) / n if n else 0.0, 1),
        "valid_pct": _r(100.0 * sum(r["valid"] for r in records) / n if n else 0.0, 1),
        "statuses": dict(sorted(statuses.items())),
        "p50_s": _r(percentile(times, 50)),
        "p95_s": _r(percentile(times, 95)),
        "max_s": _r(max(times) if times else None),
        "lost": len(accepted) - len(terminal) + (n - len(accepted)),
        "duplicates": dup,
        "throughput_per_min": _r(throughput_per_min(len(terminal), wall_s)),
        "wall_s": _r(wall_s, 1),
        "post_max_s": _r(max((r["post_s"] for r in records), default=None), 3),
        "post_429s": posts_429,
        "post_429_without_retry_after": sum(r["post_429_no_ra"] for r in records),
        "http_5xx": sum(r["http_5xx"] for r in records),
        "slot_over_60s": sum(1 for r in accepted if (r.get("slot_s") or 0) > SLOT_FLAG_S),
        "slot_max_s": _r(max((r.get("slot_s") or 0 for r in accepted), default=None)),
        "per_doc": {
            d: {
                "n": len(v),
                "p50_s": _r(percentile(v, 50)),
                "p95_s": _r(percentile(v, 95)),
                "max_s": _r(max(v)),
            }
            for d, v in sorted(by_doc.items())
        },
    }


def criteria(s: dict[str, Any]) -> dict[str, bool]:
    """A-6 pass criteria for one scenario (scaling is checked across L3 runs)."""
    return {
        "100% terminal": s["completion_pct"] == 100.0,
        "0 lost": s["lost"] == 0,
        "0 duplicates": s["duplicates"] == 0,
        ">= 80% VALID": s["valid_pct"] >= VALID_MIN_PCT,
        "every job < 1800 s": s["max_s"] is not None and s["max_s"] < MAX_JOB_S,
        "POST < 2 s": s["post_max_s"] is not None and s["post_max_s"] < POST_LIMIT_S,
        "no 5xx": s["http_5xx"] == 0,
        "429s carry Retry-After": s["post_429_without_retry_after"] == 0,
    }


# --- docker / http -------------------------------------------------------------------------------


def compose(args: list[str], small: bool = False, check: bool = True) -> str:
    cmd = [*COMPOSE, *FILES, *(SMALL if small else []), *args]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"compose {' '.join(args[:3])} failed ({p.returncode}): {tail}")
    return p.stdout


def psql(query: str) -> list[list[str]]:
    out = compose(
        ["exec", "-T", "db", "psql", "-U", "docextract", "-d", "docextract", "-At", "-F", "|"]
        + ["-c", query]
    )
    return [ln.split("|") for ln in out.splitlines() if ln]


def http(method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, {}, dict(e.headers or {})
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, {}, {}


def wait_until(pred, timeout: float, what: str, every: float = 1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = pred()
        if got:
            return got
        time.sleep(every)
    raise RuntimeError(f"timed out after {timeout:.0f}s waiting for {what}")


def worker_containers(small: bool = False) -> list[str]:
    return compose(["ps", "-q", "worker"], small=small).split()


def started_lines(small: bool = False) -> list[tuple[str, str, str]]:
    logs = compose(["logs", "--no-log-prefix", "worker"], small=small)
    return STARTED_RE.findall(logs)


def stack_up(workers: int, small: bool = False, build: bool = False) -> tuple[str, str, str]:
    args = ["up", "-d", "--scale", f"worker={workers}"]
    compose(args + (["--build"] if build else []), small=small)
    wait_until(lambda: http("GET", "/health")[0] == 200, 120, "/health 200 on :18080")
    wait_until(lambda: len(worker_containers(small)) == workers, 60, f"{workers} workers")
    wait_until(lambda: len(started_lines(small)) >= workers, 60, "worker start lines")
    line = started_lines(small)[-1]
    if line[2] != "off" or line[1] != "baseline":
        raise RuntimeError(f"load stack is not the shipped config: {line}")
    return line


def git_sha() -> str:
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    return f"{sha}-dirty" if dirty else sha


# --- jobs ----------------------------------------------------------------------------------------


def run_job(doc_id: str, row: dict[str, str]) -> dict[str, Any]:
    schema_text = (SCHEMAS / f"{row['schema_name']}.json").read_text(encoding="utf-8")
    field_list = json.loads(schema_text)
    body, ctype = multipart(DOCS / row["file"], schema_text)
    rec: dict[str, Any] = {
        "doc_id": doc_id,
        "kind": row["kind"],
        "job_id": None,
        "status": None,
        "valid": False,
        "post_code": None,
        "post_s": None,
        "post_429s": 0,
        "post_429_no_ra": 0,
        "http_5xx": 0,
        "terminal_s": None,
    }
    t0 = time.monotonic()
    while True:
        p0 = time.monotonic()
        code, job, hdrs = http("POST", "/jobs", body, {"Content-Type": ctype})
        rec["post_s"] = max(rec["post_s"] or 0.0, time.monotonic() - p0)
        rec["post_code"] = code
        rec["http_5xx"] += code >= 500
        if code != 429:
            break
        rec["post_429s"] += 1
        ra = {k.lower(): v for k, v in hdrs.items()}.get("retry-after")
        rec["post_429_no_ra"] += ra is None
        time.sleep(float(ra) if ra and ra.isdigit() else 30)
    if code != 202:
        return rec
    rec["job_id"] = job["job_id"]
    while time.monotonic() - t0 < MAX_JOB_S:
        code, job, _ = http("GET", f"/jobs/{rec['job_id']}")
        rec["http_5xx"] += code >= 500
        if code == 200 and job.get("status") in TERMINAL:
            rec["_terminal_at"] = time.monotonic()
            rec["terminal_s"] = rec["_terminal_at"] - t0
            rec["status"] = job["status"]
            rec["valid"] = result_valid(job["status"], job, field_list)
            rec["_fingerprint"] = json.dumps(job, sort_keys=True)
            return rec
        time.sleep(POLL_S)
    return rec


def run_batch(docs: list[tuple[str, dict[str, str]]], n: int) -> tuple[list[dict], float]:
    plan = [docs[i % len(docs)] for i in range(n)]
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=IN_FLIGHT) as pool:
        records = list(pool.map(lambda d: run_job(*d), plan))
    return records, time.monotonic() - t0


def recheck(records: list[dict]) -> None:
    """Terminal statuses never change: GET each job again and compare the whole body."""
    for r in records:
        if not r["job_id"] or "_fingerprint" not in r:
            continue
        code, job, _ = http("GET", f"/jobs/{r['job_id']}")
        r["changed_after_terminal"] = code != 200 or json.dumps(job, sort_keys=True) != r.pop(
            "_fingerprint"
        )


def db_facts(job_ids: list[str]) -> tuple[dict[str, int], dict[str, float], dict[str, int]]:
    """Per job: terminal event count, seconds from the last claim to the terminal event
    (the worker slot time, A-8) and number of claims."""
    if not job_ids:
        return {}, {}, {}
    ids = ",".join(f"'{j}'" for j in job_ids)
    rows = psql(
        "SELECT job_id, "
        "count(*) FILTER (WHERE event IN ('SUCCESS','PARTIAL','FAILED')), "
        "count(*) FILTER (WHERE event = 'CLAIMED'), "
        "coalesce(extract(epoch FROM max(at) FILTER (WHERE event IN "
        "('SUCCESS','PARTIAL','FAILED'))) - extract(epoch FROM max(at) FILTER "
        "(WHERE event = 'CLAIMED')), -1) "
        f"FROM job_events WHERE job_id IN ({ids}) GROUP BY job_id"
    )
    terminal = {r[0]: int(r[1]) for r in rows}
    claims = {r[0]: int(r[2]) for r in rows}
    slot = {r[0]: float(r[3]) for r in rows if float(r[3]) >= 0}
    return terminal, slot, claims


def holder_container(job_ids: list[str]) -> tuple[str, str] | None:
    if not job_ids:
        return None
    ids = ",".join(f"'{j}'" for j in job_ids)
    rows = psql(
        f"SELECT id, lease_owner FROM jobs WHERE id IN ({ids}) AND status = 'RUNNING' "
        "AND lease_owner IS NOT NULL LIMIT 1"
    )
    if not rows:
        return None
    host = rows[0][1].split(":")[0]
    cid = next((c for c in worker_containers() if c.startswith(host)), None)
    return (rows[0][0], cid) if cid else None


# --- scenarios -----------------------------------------------------------------------------------


def finish_scenario(
    name: str, workers: int, records: list[dict], wall: float, sha: str, extra: dict | None = None
) -> dict[str, Any]:
    recheck(records)
    ids = [r["job_id"] for r in records if r["job_id"]]
    terminal, slot, claims = db_facts(ids)
    for r in records:
        if r["job_id"]:
            r["slot_s"] = round(slot.get(r["job_id"], 0.0), 2)
            r["claims"] = claims.get(r["job_id"], 0)
            r["terminal_events"] = terminal.get(r["job_id"], 0)
    s = summarize(name, workers, records, wall, terminal, sha)
    s["reclaimed_jobs"] = sum(1 for r in records if r.get("claims", 0) > 1)
    if extra:
        s.update(extra)
    s["criteria"] = criteria(s)
    s["pass"] = all(s["criteria"].values())
    with JOBS_OUT.open("a", encoding="utf-8", newline="\n") as f:
        for r in records:
            row = {k: v for k, v in r.items() if not k.startswith("_")}
            f.write(json.dumps({"scenario": name, "workers": workers, **row}) + "\n")
    print(
        f"{name} w={workers}: n={s['n']} terminal={s['terminal']} lost={s['lost']} "
        f"dup={s['duplicates']} valid={s['valid_pct']}% p50={s['p50_s']} p95={s['p95_s']} "
        f"max={s['max_s']} thr={s['throughput_per_min']}/min post_max={s['post_max_s']} "
        f"5xx={s['http_5xx']} pass={s['pass']}",
        flush=True,
    )
    return s


def scenario_plain(name, docs, workers, n, sha, small=False, build=False) -> dict[str, Any]:
    line = stack_up(workers, small=small, build=build)
    print(f"{name}: stack up, {workers} worker(s), start line {line}", flush=True)
    records, wall = run_batch(docs, n)
    return finish_scenario(name, workers, records, wall, sha, {"small_profile": small})


def scenario_chaos(docs, sha, n: int = 10, workers: int = 2) -> dict[str, Any]:
    stack_up(workers)
    box: dict[str, Any] = {}

    def load() -> None:
        box["records"], box["wall"] = run_batch(docs, n)

    t = threading.Thread(target=load, name="l2-load")
    t.start()
    time.sleep(KILL_AFTER_S)

    def find_holder():
        rows = psql(
            "SELECT id FROM jobs WHERE status = 'RUNNING' AND lease_owner IS NOT NULL "
            "AND created_at > now() - interval '5 minutes'"
        )
        return holder_container([r[0] for r in rows])

    victim_job, victim = wait_until(find_holder, 60, "a RUNNING job with a lease")
    subprocess.run(["docker", "kill", "--signal", "KILL", victim], capture_output=True, check=True)
    killed_at = time.monotonic()
    print(f"L2: killed worker {victim[:12]} holding job {victim_job}", flush=True)
    time.sleep(3)
    subprocess.run(["docker", "start", victim], capture_output=True, check=True)
    print("L2: killed worker started again", flush=True)
    t.join()
    records = box["records"]
    vr = next((r for r in records if r["job_id"] == victim_job), None)
    done_at = vr.get("_terminal_at") if vr else None
    extra = {
        "killed_job_status": vr["status"] if vr else "not_in_batch",
        # client clock: kill -> the killed job first seen terminal (2 s poll)
        "recovery_s": _r(done_at - killed_at) if done_at else None,
    }
    s = finish_scenario("L2", workers, records, box["wall"], sha, extra)
    if vr:
        s["killed_job_claims"] = vr.get("claims")
        s["killed_job_terminal_events"] = vr.get("terminal_events")
    s["criteria"]["killed job re-claimed and terminal once"] = bool(
        vr and vr.get("claims", 0) >= 2 and vr.get("terminal_events") == 1
    )
    s["pass"] = all(s["criteria"].values())
    return s


# --- report tables -------------------------------------------------------------------------------


def tables_md(results: list[dict[str, Any]]) -> str:
    out = [
        "| Scenario | Workers | n | Terminal | Lost | Dup | VALID % | p50 s | p95 s | max s "
        "| jobs/min | POST max s | POST 429 | 5xx | slot > 60 s | Pass |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in results:
        out.append(
            f"| {s['scenario']} | {s['workers']} | {s['n']} | {s['terminal']} | {s['lost']} | "
            f"{s['duplicates']} | {s['valid_pct']} | {s['p50_s']} | {s['p95_s']} | {s['max_s']} "
            f"| {s['throughput_per_min']} | {s['post_max_s']} | {s['post_429s']} | "
            f"{s['http_5xx']} | {s['slot_over_60s']} | {'PASS' if s['pass'] else 'FAIL'} |"
        )
    out += ["", "Per doc (submit -> terminal seconds, client clock, 2 s poll):", ""]
    out.append("| Scenario | Workers | Doc | Kind | n | p50 s | p95 s | max s |")
    out.append("|---|---|---|---|---|---|---|---|")
    kinds = {d: row["kind"] for d, row in manifest().items()}
    for s in results:
        for d, v in s["per_doc"].items():
            out.append(
                f"| {s['scenario']} | {s['workers']} | {d} | {kinds.get(d, '?')} | {v['n']} | "
                f"{v['p50_s']} | {v['p95_s']} | {v['max_s']} |"
            )
    out += ["", "Criteria:", ""]
    for s in results:
        failed = [k for k, ok in s["criteria"].items() if not ok]
        out.append(
            f"- {s['scenario']} w={s['workers']}: "
            + ("all passed" if not failed else "FAILED " + ", ".join(failed))
            + f" (statuses {s['statuses']})"
        )
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenarios", nargs="+", default=["L1", "L2", "L3", "L4"])
    ap.add_argument("--docs", nargs="+", default=None, help="DEV doc ids (default: all 6)")
    ap.add_argument("--n", type=int, default=20, help="jobs per L1/L3/L4 run")
    ap.add_argument("--keep", action="store_true", help="do not `down -v` at the end")
    a = ap.parse_args()
    docs = dev_docs(a.docs)
    sha = git_sha()
    print(f"load test {sha}: docs={[d for d, _ in docs]} scenarios={a.scenarios}", flush=True)
    results: list[dict[str, Any]] = []
    built = False
    try:
        for sc in a.scenarios:
            if sc == "L1":
                results.append(scenario_plain("L1", docs, 1, a.n, sha, build=not built))
            elif sc == "L2":
                if not built:
                    stack_up(2, build=True)
                results.append(scenario_chaos(docs, sha))
            elif sc == "L3":
                for w in (1, 2, 3):
                    results.append(scenario_plain("L3", docs, w, a.n, sha, build=not built))
                    built = True
            elif sc == "L4":
                results.append(scenario_plain("L4", docs, 1, a.n, sha, small=True, build=not built))
            else:
                raise SystemExit(f"unknown scenario {sc}")
            built = True
            with EVAL_OUT.open("a", encoding="utf-8", newline="\n") as f:
                for s in results[-(3 if sc == "L3" else 1) :]:
                    f.write(json.dumps(s) + "\n")
        l3 = [s for s in results if s["scenario"] == "L3"]
        if len(l3) >= 2:
            ok = l3[1]["throughput_per_min"] > l3[0]["throughput_per_min"]
            print(f"scaling 1 -> 2 workers: {'PASS' if ok else 'FAIL'}", flush=True)
        TABLES_OUT.write_text(tables_md(results), encoding="utf-8", newline="\n")
        print(f"wrote {TABLES_OUT.relative_to(ROOT)}", flush=True)
    finally:
        if not a.keep:
            compose(["down", "-v"], small=False, check=False)
            print("load stack down -v", flush=True)
    return 0 if results and all(s["pass"] for s in results) else 1


if __name__ == "__main__":
    sys.exit(main())
