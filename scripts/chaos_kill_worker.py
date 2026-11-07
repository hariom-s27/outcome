"""P1-16 kill-worker proof against the running compose stack. Writes logs/P1_chaos.txt.

Scenario A (kill):   2 workers, 3 jobs. SIGKILL the worker holding a lease. Expect every job
                     terminal exactly once; the killed job re-claimed with a higher fence.
Scenario B (freeze): docker pause the worker holding a lease until the other worker re-claims
                     and finishes it, then unpause. Expect the frozen worker's late write to be
                     rejected (job unchanged, "lease lost" in its log).

Uses invented data only; prints and logs job ids, statuses and events (metadata only).
Run:  uv run python scripts/chaos_kill_worker.py      (Docker running; takes ~4-5 minutes)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "P1_chaos.txt"
BASE = "http://localhost:8080"
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "scripts/chaos.compose.yaml"]

FIELD_LIST = {
    "name": "chaos_probe",
    "fields": {
        "probe_name": {"name": "Probe Name", "description": "Name of the probe."},
        "probe_count": {"name": "Probe Count", "description": "How many probes."},
    },
}
CSV = b"probe_name,probe_count\nalpha,1\n"

lines: list[str] = []


def say(msg: str = "") -> None:
    print(msg, flush=True)
    lines.append(msg)


def run(cmd: list[str], check: bool = True) -> str:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:4])} ...")
    return p.stdout


def psql(query: str) -> list[list[str]]:
    out = run(
        [*COMPOSE, "exec", "-T", "db", "psql", "-U", "docextract", "-d", "docextract", "-At"]
        + ["-F", "|", "-c", query]
    )
    return [ln.split("|") for ln in out.splitlines() if ln]


def http(method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, {}


def submit() -> str:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="probe.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n".encode()
        + CSV
        + b"\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="schema"\r\n\r\n'.encode()
        + json.dumps(FIELD_LIST).encode()
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    status, body = http(
        "POST",
        "/jobs",
        b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    if status != 202:
        raise RuntimeError(f"POST /jobs returned {status}")
    return body["job_id"]


def wait(pred, timeout: float, what: str, every: float = 1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = pred()
        if got:
            return got
        time.sleep(every)
    raise RuntimeError(f"timed out after {timeout:.0f}s waiting for {what}")


def worker_containers() -> list[str]:
    return run([*COMPOSE, "ps", "-q", "worker"]).split()


def holder_container(job_id: str) -> str | None:
    rows = psql(f"SELECT lease_owner FROM jobs WHERE id = '{job_id}' AND status = 'RUNNING'")
    if not rows or not rows[0][0]:
        return None
    host = rows[0][0].split(":")[0]
    return next((c for c in worker_containers() if c.startswith(host)), None)


def job_status(job_id: str) -> str:
    return http("GET", f"/jobs/{job_id}")[1].get("status", "?")


def report_job(job_id: str) -> dict:
    ev = psql(
        "SELECT event, coalesce(fence::text, ''), coalesce(split_part(worker, ':', 1), ''), "
        f"coalesce(reason, '') FROM job_events WHERE job_id = '{job_id}' ORDER BY id"
    )
    row = psql(f"SELECT status, fence, attempts FROM jobs WHERE id = '{job_id}'")[0]
    terminal = [e for e in ev if e[0] in ("SUCCESS", "PARTIAL", "FAILED")]
    say(f"  job {job_id}: status={row[0]} fence={row[1]} attempts={row[2]}")
    for e in ev:
        extra = f" reason={e[3]}" if e[3] else ""
        say(f"    {e[0]:<9} fence={e[1] or '-':<2} worker={e[2][:12] or '-'}{extra}")
    return {
        "status": row[0],
        "claims": sum(e[0] == "CLAIMED" for e in ev),
        "terminal_events": len(terminal),
        "fence": int(row[1]),
    }


def bring_up() -> None:
    run([*COMPOSE, "up", "-d", "--build", "--scale", "worker=2"])
    wait(lambda: http("GET", "/health")[0] == 200, 90, "/health 200")
    wait(lambda: len(worker_containers()) == 2, 30, "2 workers")


def scenario_kill() -> bool:
    say("== Scenario A: SIGKILL the worker holding a lease")
    jobs = [submit() for _ in range(3)]
    victim_job = wait(
        lambda: next((j for j in jobs if holder_container(j)), None), 30, "a RUNNING job"
    )
    victim = holder_container(victim_job)
    run(["docker", "kill", "--signal", "KILL", victim])
    t0 = time.monotonic()
    say(f"killed worker {victim[:12]} while it held job {victim_job}")
    wait(
        lambda: all(job_status(j) in ("SUCCESS", "PARTIAL", "FAILED") for j in jobs),
        240,
        "all jobs terminal",
        every=2.0,
    )
    say(f"all 3 jobs terminal {time.monotonic() - t0:.0f}s after the kill")
    stats = {j: report_job(j) for j in jobs}
    ok = all(s["terminal_events"] == 1 and s["status"] == "PARTIAL" for s in stats.values())
    ok &= stats[victim_job]["claims"] >= 2 and stats[victim_job]["fence"] >= 2
    say(
        f"Scenario A: {'PASS' if ok else 'FAIL'} (each job terminal once; killed job re-claimed "
        f"with fence {stats[victim_job]['fence']})"
    )
    return ok


def scenario_freeze() -> bool:
    say("")
    say("== Scenario B: freeze (docker pause) the lease holder, let the lease expire, unpause")
    run([*COMPOSE, "up", "-d", "--scale", "worker=2"])
    wait(lambda: len(worker_containers()) == 2, 30, "2 workers")
    job = submit()
    frozen = wait(lambda: holder_container(job), 30, "job RUNNING")
    run(["docker", "pause", frozen])
    say(f"paused worker {frozen[:12]} while it held job {job}")
    wait(
        lambda: job_status(job) in ("SUCCESS", "PARTIAL", "FAILED"),
        200,
        "other worker to finish the job",
        every=2.0,
    )
    before = psql(f"SELECT status, updated_at, md5(result::text) FROM jobs WHERE id = '{job}'")
    since = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    run(["docker", "unpause", frozen])
    say("job finished by the other worker; unpaused the frozen worker, waiting 25 s")
    time.sleep(25)
    after = psql(f"SELECT status, updated_at, md5(result::text) FROM jobs WHERE id = '{job}'")
    p = subprocess.run(
        ["docker", "logs", "--since", since, frozen], cwd=ROOT, capture_output=True, text=True
    )
    logs = p.stdout + p.stderr  # python logging writes to stderr
    lost = any(job in ln and ("lease lost" in ln or "abandoned" in ln) for ln in logs.splitlines())
    s = report_job(job)
    ok = before == after and s["terminal_events"] == 1 and s["claims"] >= 2 and lost
    say(
        f"job row unchanged after unpause: {before == after}; frozen worker logged lease lost: "
        f"{lost}"
    )
    say(f"Scenario B: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    say(f"P1 chaos run {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}")
    say("settings: lease 60 s, heartbeat 15 s, 2 workers, simulated work 20 s per job")
    say("")
    ok = False
    try:
        bring_up()
        ok = scenario_kill()
        ok = scenario_freeze() and ok
    except RuntimeError as exc:
        say(f"ERROR: {exc}")
    finally:
        # back to the shipped stack: 1 worker, no simulated work
        for c in worker_containers():
            subprocess.run(["docker", "unpause", c], cwd=ROOT, capture_output=True)
        run(["docker", "compose", "up", "-d", "--scale", "worker=1"], check=False)
        say("")
        say(f"OVERALL: {'PASS' if ok else 'FAIL'}")
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
