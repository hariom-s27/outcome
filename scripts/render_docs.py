"""Fill the measured blocks in README.md and DESIGN.md from eval/*.jsonl (P8a A-11).

    uv run python scripts/render_docs.py           # rewrite the blocks
    uv run python scripts/render_docs.py --check   # exit 1 if a block is out of date

Only the text between `<!-- AUTO:name -->` and `<!-- /AUTO:name -->` is replaced; everything
else is left byte for byte. Blocks:
  scores / results  latest run series per (pipeline, path) from eval/history.jsonl
  cost              $/doc of the same series + total eval spend recorded in history
  load              latest line per (scenario, workers) from eval/load.jsonl
A "run series" is the latest line of a group plus the lines just before it in that group that
continue its run_index count down to 1 with the same documents and prompt version (P5b's
3 live runs). The output has no clock time in it, so a second run changes nothing.
Numbers are computed here, never typed by hand. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "eval" / "history.jsonl"
LOAD = ROOT / "eval" / "load.jsonl"
DOCS = (ROOT / "README.md", ROOT / "DESIGN.md")
BLOCK_RE = re.compile(r"(<!-- AUTO:([a-z_]+) -->)(.*?)(<!-- /AUTO:\2 -->)", re.DOTALL)
START_RE = re.compile(r"<!-- AUTO:([a-z_]+) -->")

SCORE_DEF = (
    "Score = `tools/validate.py` `score()`: mean over documents of each document's mean of "
    "per-field means (strict match after normalisation). DEV documents only; the 2 held-out "
    "documents are not scored until the final run. Runs = live runs in the series (a doc's "
    "score is the mean over runs). Source: `eval/history.jsonl`, latest series per "
    "pipeline + path. Shipped default path: `baseline`."
)
LOAD_DEF = (
    "Throwaway stack with a fake LLM (seeded 1-6 s latency, ~8 % 429 with Retry-After), so "
    "times measure the queue and service, not real model latency. Time = submit to first poll "
    "that sees a terminal status (client clock, polls every 2 s). VALID = JobStatus shape + the "
    "frozen contract check. Lost/dup from the DB event log and a re-GET of every job. Source: "
    "`eval/load.jsonl`, latest line per scenario + workers (`scripts/load_test.py`)."
)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path.name}:{n}: bad JSON ({exc.msg})") from exc
    return rows


# ---------- history ----------


def group_key(row: dict) -> tuple[str, str]:
    return (str(row.get("pipeline") or "unknown"), str(row.get("path") or "baseline"))


def latest_series(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Per (pipeline, path): the latest line plus its earlier runs, oldest first."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row.get("aborted") or not row.get("n_docs"):
            continue
        groups.setdefault(group_key(row), []).append(row)
    out = {}
    for key, items in groups.items():
        last = items[-1]
        series = [last]
        want = int(last.get("run_index") or 1) - 1
        for row in reversed(items[:-1]):
            if want < 1:
                break
            same = (
                int(row.get("run_index") or 1) == want
                and set(row.get("per_doc") or {}) == set(last.get("per_doc") or {})
                and row.get("prompt_version") == last.get("prompt_version")
            )
            if not same:
                break
            series.insert(0, row)
            want -= 1
        out[key] = series
    return dict(sorted(out.items()))


def series_stats(series: list[dict]) -> dict:
    docs = sorted(series[-1].get("per_doc") or {})
    per_doc = {d: statistics.fmean(r["per_doc"][d] for r in series) for d in docs}
    return {
        "runs": len(series),
        "docs": docs,
        "per_doc": per_doc,
        "mean": statistics.fmean(per_doc.values()) if per_doc else 0.0,
        "all_valid": all(r.get("all_valid") for r in series),
        "usd_per_doc": statistics.fmean(float(r.get("usd_per_doc") or 0.0) for r in series),
        "date": str(series[-1].get("date") or "")[:10],
        "label": str(series[-1].get("label") or ""),
        "run_id": str(series[-1].get("run_id") or ""),
    }


def render_scores(history: list[dict], load: list[dict]) -> str:
    del load
    series = latest_series(history)
    if not series:
        return "_No eval runs recorded yet._"
    lines = [
        "| Pipeline | Path | Date | Docs | Runs | Mean score | Per document | All VALID |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (pipeline, path), s in series.items():
        st = series_stats(s)
        docs = ", ".join(f"{d} {v:.3f}" for d, v in st["per_doc"].items())
        lines.append(
            f"| {pipeline} | {path} | {st['date']} | {len(st['docs'])} | {st['runs']} | "
            f"**{st['mean']:.3f}** | {docs} | {'yes' if st['all_valid'] else 'no'} |"
        )
    lines += ["", SCORE_DEF]
    return "\n".join(lines)


def render_cost(history: list[dict], load: list[dict]) -> str:
    del load
    series = latest_series(history)
    if not series:
        return "_No eval runs recorded yet._"
    lines = [
        "| Pipeline | Path | Runs | $/document (uncached) |",
        "|---|---|---|---|",
    ]
    for (pipeline, path), s in series.items():
        st = series_stats(s)
        lines.append(f"| {pipeline} | {path} | {st['runs']} | ${st['usd_per_doc']:.5f} |")
    total = sum(float(r.get("cost_usd") or 0.0) for r in history)
    lines += [
        "",
        f"Total spend of the {len(history)} eval runs in `eval/history.jsonl`: ${total:.4f} "
        "(cost as the gateway billed it; spikes and pilots outside the eval script are in the "
        "phase reports). Uncached = a cached answer priced at the call that filled the cache, "
        "as a grader's run has no cache.",
    ]
    return "\n".join(lines)


# ---------- load ----------


def latest_load(rows: list[dict]) -> list[dict]:
    latest: dict[tuple[str, int], dict] = {}
    for row in rows:
        latest[(str(row.get("scenario")), int(row.get("workers") or 0))] = row
    return [latest[k] for k in sorted(latest)]


def _num(v: object, fmt: str = "{}") -> str:
    return "-" if v is None else fmt.format(v)


def render_load(history: list[dict], load: list[dict]) -> str:
    del history
    rows = latest_load(load)
    if not rows:
        return "_No load runs recorded yet._"
    lines = [
        "| Scenario | Workers | n | Terminal % | VALID % | p50 s | p95 s | max s | jobs/min "
        "| Lost | Dup | POST max s | 5xx | Pass |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        name = str(r.get("scenario"))
        if r.get("small_profile"):
            name += " (small)"
        lines.append(
            f"| {name} | {r.get('workers')} | {r.get('n')} | {_num(r.get('completion_pct'))} | "
            f"{_num(r.get('valid_pct'))} | {_num(r.get('p50_s'))} | {_num(r.get('p95_s'))} | "
            f"{_num(r.get('max_s'))} | {_num(r.get('throughput_per_min'))} | {r.get('lost')} | "
            f"{r.get('duplicates')} | {_num(r.get('post_max_s'))} | {r.get('http_5xx')} | "
            f"{'PASS' if r.get('pass') else 'FAIL'} |"
        )
    notes = []
    for r in rows:
        if r.get("recovery_s") is not None:
            notes.append(
                f"{r.get('scenario')}: a worker holding a lease was SIGKILLed; its job was "
                f"claimed {r.get('killed_job_claims')} times, ended "
                f"{r.get('killed_job_status')} with {r.get('killed_job_terminal_events')} "
                f"terminal event(s), {r.get('recovery_s')} s after the kill."
            )
    shas = sorted({str(r.get("git_sha")) for r in rows})
    lines += [""] + notes + ([""] if notes else [])
    lines.append(f"{LOAD_DEF} Code: {', '.join(shas)}.")
    return "\n".join(lines)


RENDERERS: dict[str, Callable[[list[dict], list[dict]], str]] = {
    "scores": render_scores,
    "results": render_scores,
    "cost": render_cost,
    "load": render_load,
}


def render_text(text: str, history: list[dict], load: list[dict]) -> str:
    starts = START_RE.findall(text)
    found = [m.group(2) for m in BLOCK_RE.finditer(text)]
    if starts != found:
        raise SystemExit(f"unclosed or nested AUTO block: starts {starts}, closed {found}")
    unknown = sorted(set(found) - set(RENDERERS))
    if unknown:
        raise SystemExit(f"unknown AUTO block(s): {unknown}")

    def fill(m: re.Match) -> str:
        body = RENDERERS[m.group(2)](history, load).strip("\n")
        return f"{m.group(1)}\n{body}\n{m.group(4)}"

    return BLOCK_RE.sub(fill, text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any block is out of date")
    ap.add_argument("--history", type=Path, default=HISTORY)
    ap.add_argument("--load", type=Path, default=LOAD)
    ap.add_argument("files", nargs="*", type=Path, default=list(DOCS))
    args = ap.parse_args(argv)
    history, load = read_jsonl(args.history), read_jsonl(args.load)
    stale = []
    for path in args.files:
        old = path.read_text(encoding="utf-8")
        new = render_text(old, history, load)
        if new == old:
            print(f"{path.name}: up to date")
            continue
        stale.append(path.name)
        if args.check:
            print(f"{path.name}: out of date")
        else:
            path.write_text(new, encoding="utf-8", newline="\n")
            print(f"{path.name}: updated")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
