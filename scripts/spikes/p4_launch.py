"""Start one paid P4 spike in the dev worker container (P4-07, P4-13), after the gates.

    uv run python scripts/spikes/p4_launch.py b1 --max-usd 0.01 -- --models \\
        anthropic/claude-haiku-5.5 --max-batches 1                       # pilot
    uv run python scripts/spikes/p4_launch.py b3 --max-usd 0.05 --no-cache

Host side, in order:
  1. clean tree (PR-09; --allow-dirty only with Hariom's yes) and the dry run of the spike's
     documents (R-A; --skip-dry-run only with Hariom's yes); both recorded in launch.json
  2. total cap (P4-13): spend of every earlier paid spike run under cache/spikes/ + this
     run's --max-usd must stay within --total-cap (default $0.35); the run's cap is cut to fit
  3. docker compose run --rm worker with mounts: scripts/ (ro), the DEV documents folder (ro),
     sample/schemas + sample/manifest.csv (ro, field lists) and cache/spikes/ (rw). The answers
     folder is never mounted. The key stays inside compose's env; nothing prints it.
Every paid number is tied to the commit in the run id: <short sha>-<spike>-<utc>.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dry_run  # noqa: E402
import run_gates  # noqa: E402

ROOT = HERE.parents[1]
SPIKES = ROOT / "cache" / "spikes"
SAMPLE = ROOT / "sample"
SPIKE_DOCS = {
    "b1": ["lease_001"],
    "b2": ["lease_001"],
    "b3": ["om_001", "lease_002", "rentroll_001"],
    "b4": ["lease_002", "om_001"],
}


def spent_so_far(spikes: Path = SPIKES) -> float:
    """$ of every earlier paid spike run (dry runs excluded)."""
    total = 0.0
    for summary in spikes.glob("*/summary.json"):
        data = json.loads(summary.read_text(encoding="utf-8"))
        if not data.get("dry_run"):
            total += float(data.get("spent_usd") or 0.0)
    return total


def capped(max_usd: float, total_cap: float, spent: float) -> float:
    """This run's cap so the P4 total stays within total_cap (<= 0: refuse)."""
    return round(min(max_usd, total_cap - spent), 6)


def docker_cmd(spike: str, run_id: str, max_usd: float, no_cache: bool, rest: list[str]):
    vol = [
        (ROOT / "scripts", "/srv/scripts:ro"),
        (SAMPLE / "sample-data-documents", "/srv/devdocs:ro"),
        (SAMPLE / "schemas", "/srv/schemas:ro"),
        (SAMPLE / "manifest.csv", "/srv/manifest.csv:ro"),
        (SPIKES, "/spikes"),
    ]
    cmd = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.dev.yaml", "run", "--rm"]
    if no_cache:
        cmd += ["-e", "LLM_CACHE_DIR="]
    for src, dst in vol:
        cmd += ["-v", f"{src}:{dst}"]
    cmd += ["worker", "python", f"scripts/spikes/p4_{spike}.py", "--run-id", run_id]
    cmd += ["--max-usd", str(max_usd)] + (["--no-cache"] if no_cache else []) + rest
    return cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spike", choices=sorted(SPIKE_DOCS))
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--total-cap", type=float, default=0.35, help="P4 total (P4-13, 8 Nov)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true", help="Hariom's yes only; recorded")
    ap.add_argument("--skip-dry-run", action="store_true", help="Hariom's yes only; recorded")
    argv = list(sys.argv[1:] if argv is None else argv)
    rest: list[str] = []
    if "--" in argv:  # everything after -- goes to the spike script unchanged
        cut = argv.index("--")
        argv, rest = argv[:cut], argv[cut + 1 :]
    args = ap.parse_args(argv)

    ok, msg = run_gates.clean_tree_gate(args.allow_dirty)
    print(msg)
    if not ok:
        return 2
    gates = {"allow_dirty_used": msg.startswith("DIRTY"), "dry_run": "skipped"}
    if not args.skip_dry_run:
        passed, recs = dry_run.run(SPIKE_DOCS[args.spike])
        gates["dry_run"] = "passed" if passed else "failed"
        print(f"dry run {gates['dry_run']} ({len(recs)} docs)")
        if not passed:
            print("refused: fix the dry-run failure first, or --skip-dry-run with Hariom's yes")
            return 2
    spent = spent_so_far()
    max_usd = capped(args.max_usd, args.total_cap, spent)
    print(f"P4 spent so far ${spent:.4f}; total cap ${args.total_cap}; this run cap ${max_usd}")
    if max_usd <= 0:
        print("refused: the P4 total cap is reached")
        return 2

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{run_gates.head_sha()}-{args.spike}-{stamp}"
    (SPIKES / run_id).mkdir(parents=True, exist_ok=True)
    launch = {"run_id": run_id, "max_usd": max_usd, "no_cache": args.no_cache, **gates,
              "spike_args": rest}  # fmt: skip
    (SPIKES / run_id / "launch.json").write_text(json.dumps(launch, indent=1), encoding="utf-8")
    print(f"run {run_id}")
    cmd = docker_cmd(args.spike, run_id, max_usd, args.no_cache, rest)
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
