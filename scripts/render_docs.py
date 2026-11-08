"""Fill the measured blocks in README.md and DESIGN.md from eval/*.jsonl (P8a A-11).

    uv run python scripts/render_docs.py           # rewrite the blocks
    uv run python scripts/render_docs.py --check   # exit 1 if a block is out of date

Only the text between `<!-- AUTO:name -->` and `<!-- /AUTO:name -->` is replaced; everything
else is left byte for byte. Blocks:
  scores / results  latest run series per (pipeline, path) from eval/history.jsonl
  cost              $/doc of the same series + total eval spend recorded in history
  load              latest line per (scenario, workers) from eval/load.jsonl
  chart             the points of docs/cost_vs_accuracy.png (scripts/plot_cost_accuracy.py)
  v11               v1.0 base runs vs the v1.1 full-set run, per document (P9f, V11_*)
  gates             each shipped v1.1 change: its gate runs vs its base runs (P9f, GATES)
Once a sealed final run exists (`final: true`, P8b), scores/results show that run (DEV and
held-out apart) and cost shows its $/doc; the final line is never part of a series.
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
# P9f: names may hold digits (`v11`); the old [a-z_]+ skipped such a block silently
BLOCK_RE = re.compile(r"(<!-- AUTO:([a-z0-9_]+) -->)(.*?)(<!-- /AUTO:\2 -->)", re.DOTALL)
START_RE = re.compile(r"<!-- AUTO:([a-z0-9_]+) -->")

SCORE_DEF = (
    "Score = `tools/validate.py` `score()`: mean over documents of each document's mean of "
    "per-field means (strict match after normalisation). DEV documents only; the 2 held-out "
    "documents are not scored until the final run. Runs = live runs in the series (a doc's "
    "score is the mean over runs). Source: `eval/history.jsonl`, latest series per "
    "pipeline + path. Shipped default path: `baseline`."
)
# P9f: the settings `docker compose up` ships in v1.1 (compose.yaml; tests/test_shipped_config.py)
SHIPPED_SETTINGS = (
    "`EXTRACT_TABLE_PATH=spec`, `PDF_TABLE_METHOD=grid`, `TABLE_CLEANUP=1`, `E0_ROBUST=1`, "
    "`SCAN_PAGE_METHOD=all`, `SPEC_RETRY_FEEDBACK=0`, single-value path `baseline`"
)
V10_SETTINGS = (
    "`EXTRACT_TABLE_PATH=spec`, `SCAN_PAGE_METHOD=first`, single-value path `baseline`; "
    "no E0, no PDF grid, no table cleanup"
)
FINAL_DEF = (
    "The sealed **v1.0** final run (P8b): all 8 sample documents, once, on the v1.0 settings "
    f"({V10_SETTINGS}), no response caching. It is the only run that scored the 2 held-out "
    "documents; no v1.1 held-out run exists (the gateway key expired). Score = `tools/validate.py` "
    "`score()`: a document's mean of per-field means (strict match after normalisation). "
    "Held-out documents were run and scored once, inside this run; nothing was changed "
    "after. n = 1 run per document; run-to-run spread from earlier repeats is in DESIGN "
    "(Where it fails). Source: the `final: true` line in `eval/history.jsonl`."
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
        if row.get("aborted") or not row.get("n_docs") or row.get("final"):
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


def final_run(history: list[dict]) -> dict | None:
    """The latest sealed final run (P8b Z-7: `final: true`, not aborted), if any."""
    rows = [r for r in history if r.get("final") and not r.get("aborted")]
    return rows[-1] if rows else None


def render_final(row: dict) -> str:
    held = row.get("held_out_per_doc") or {}
    paths = row.get("path_per_doc") or {}
    per_doc = row.get("per_doc") or {}
    dev = [d for d in per_doc if d not in held]
    lines = ["| Document | Set | Path | Score |", "|---|---|---|---|"]
    for d in dev:
        lines.append(f"| {d} | DEV | {paths.get(d, '-')} | {per_doc[d]:.3f} |")
    for d in held:
        lines.append(f"| {d} | held-out, scored once | {paths.get(d, '-')} | {held[d]:.3f} |")
    held_txt = ", ".join(f"{d} {v:.3f}" for d, v in held.items()) or "none"
    lines += [
        "",
        f"**DEV mean {float(row.get('dev_mean_score') or 0.0):.3f} (n = {row.get('n_dev')} "
        f"documents, 1 run)** · held-out (n = {len(held)}, scored once): {held_txt} · "
        f"all VALID: {'yes' if row.get('all_valid') else 'no'} · all calls live: "
        f"{'yes' if row.get('all_live') else 'no'} · "
        f"${float(row.get('usd_per_doc') or 0.0):.5f}/document uncached "
        f"(mean over the {row.get('n_docs')} documents) · run `{row.get('run_id')}` "
        f"run {row.get('run_index')}, {str(row.get('date') or '')[:10]}",
        "",
        FINAL_DEF,
    ]
    return "\n".join(lines)


def render_scores(history: list[dict], load: list[dict]) -> str:
    del load
    final = final_run(history)
    if final:
        return render_final(final)
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
    final = final_run(history)
    if final:
        total = sum(float(r.get("cost_usd") or 0.0) for r in history)
        return (
            f"Sealed v1.0 run {final.get('run_index')}: "
            f"**${float(final.get('usd_per_doc') or 0.0):.5f} per document** "
            f"(uncached, mean over {final.get('n_docs')} documents), "
            f"${float(final.get('cost_usd') or 0.0):.5f} for the whole run. "
            f"Total spend of the {len(history)} eval runs in `eval/history.jsonl`: "
            f"${total:.4f} (cost as the gateway billed it; spikes and pilots outside the eval "
            "script are in the phase reports). Uncached = a cached answer priced at the call "
            "that filled the cache, as a grader's run has no cache."
        )
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


def render_chart(history: list[dict], load: list[dict]) -> str:
    """The points of docs/cost_vs_accuracy.png (scripts/plot_cost_accuracy.py)."""
    del load
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import plot_cost_accuracy as pca

    pts = pca.points(history, pca.hybrid_means())
    if not pts:
        return "_No baseline run recorded yet._"
    return (
        pca.markdown(pts)
        + "\n\nEach point is a 6-document DEV mean: a config measured on fewer DEV documents "
        "is completed with the P2 baseline's score (and $) for the others. Hybrid sim = an "
        "offline re-score of the P5b runs (`logs/P5c_hybrid_sim.md`); its $ is both calls. "
        "The sealed v1.0 point's $ is run 90's mean over all 8 documents; v1.1 is in the "
        "v11 table (README). Held-out "
        "documents are not in the chart. Source: `scripts/plot_cost_accuracy.py`."
    )


# ---------- v1.1 (P9f) ----------

V11_BASE_RUNS = (90, 103, 101, 102)  # v1.0 base, n = 2 runs per doc (logs/P9a_report.md)
V11_RUN = 174  # last full set on the shipped v1.1 settings (logs/P9e_report.md)
# (change, decision, base parts [(runs, docs or None)], cand runs, docs or None, verdict, source)
GATES: tuple[tuple, ...] = (
    ("E0 robust parsing", "Z-34/Z-35", (((90, 103, 101, 102), None),), (105, 106), None,
     "PASS", "logs/P9b_report.md §4"),
    ("PDF table grid", "Z-47/Z-50", (((104, 105, 106), ("syn_budget_pdf", "syn_rentroll_pdf")),),
     (141, 142, 143), ("syn_budget_pdf", "syn_rentroll_pdf"), "PASS",
     "logs/P9c_report.md; full set run 144"),
    ("Table cleanup", "Z-59/Z-60",
     (((141, 142, 143), ("syn_budget_pdf", "syn_rentroll_pdf")),
      ((104, 105, 106), ("rentroll_001", "syn_rentroll_xlsx"))),
     (154, 155, 156), ("syn_budget_pdf", "syn_rentroll_pdf", "rentroll_001", "syn_rentroll_xlsx"),
     "PASS (targeted cells)", "logs/P9c_report.md; full set run 157"),
    ("All scan pages", "Z-56", (((104, 105, 106), ("lease_001", "syn_lease_scan")),),
     (171, 172, 173), ("lease_001", "syn_lease_scan"), "PASS", "logs/P9e_report.md; run 174"),
)  # fmt: skip


def _by_index(history: list[dict]) -> dict[int, dict]:
    """run_index -> the latest non-aborted line with that index."""
    out: dict[int, dict] = {}
    for r in history:
        if r.get("run_index") is not None and not r.get("aborted"):
            out[int(r["run_index"])] = r
    return out


def runs_per_doc(
    rows: dict[int, dict], runs: tuple[int, ...], docs: tuple[str, ...] | None = None
) -> dict[str, list[float]]:
    """Per doc, its scores over the given runs (held-out docs never included)."""
    acc: dict[str, list[float]] = {}
    for i in runs:
        if i not in rows:
            raise SystemExit(f"run {i} not in eval/history.jsonl")
        r = rows[i]
        held = r.get("held_out_per_doc") or {}
        for d, v in (r.get("per_doc") or {}).items():
            if d not in held and (docs is None or d in docs):
                acc.setdefault(d, []).append(float(v))
    return acc


def _runs_label(runs: tuple[int, ...]) -> str:
    """'141–143' for 3+ consecutive run indexes, else '90, 103, 101, 102'."""
    consecutive = list(runs) == list(range(runs[0], runs[0] + len(runs)))
    return f"{runs[0]}–{runs[-1]}" if consecutive and len(runs) > 2 else ", ".join(map(str, runs))


def _mean_of_doc_means(acc: dict[str, list[float]]) -> float:
    return statistics.fmean(statistics.fmean(v) for v in acc.values()) if acc else 0.0


def render_v11(history: list[dict], load: list[dict]) -> str:
    del load
    rows = _by_index(history)
    if V11_RUN not in rows:
        return "_No v1.1 full-set run recorded yet._"
    base = runs_per_doc(rows, V11_BASE_RUNS)
    cand = runs_per_doc(rows, (V11_RUN,))
    syn = {d for i in V11_BASE_RUNS if rows[i].get("set") == "syn" for d in rows[i]["per_doc"]}
    docs = [d for d in cand if d in base]
    lines = [
        "| Document | Set | v1.0 (n = 2) | v1.1 run 174 (n = 1) | Change |",
        "|---|---|---|---|---|",
    ]
    for d in docs:
        b, c = statistics.fmean(base[d]), cand[d][0]
        lines.append(f"| {d} | {'SYN' if d in syn else 'DEV'} | {b:.3f} | {c:.3f} | {c - b:+.3f} |")
    means = []
    for name, keep in (("DEV", lambda d: d not in syn), ("SYN", lambda d: d in syn),
                       ("DEV+SYN", lambda d: True)):  # fmt: skip
        sel = [d for d in docs if keep(d)]
        b = _mean_of_doc_means({d: base[d] for d in sel})
        c = _mean_of_doc_means({d: cand[d] for d in sel})
        means.append(f"{name} (n = {len(sel)}) {b:.3f} → **{c:.3f}**")
    r = rows[V11_RUN]
    lines += [
        "",
        " · ".join(means) + f" · v1.1 all VALID: {'yes' if r.get('all_valid') else 'no'} · "
        f"${float(r.get('usd_per_doc') or 0.0):.5f}/document · run `{r.get('run_id')}` "
        f"run {V11_RUN}, {str(r.get('date') or '')[:10]}",
        "",
        f"v1.1 = the shipped settings ({SHIPPED_SETTINGS}). v1.0 base = runs "
        f"{', '.join(map(str, V11_BASE_RUNS))} (sealed run 90 + run 103 for DEV, 101 + 102 for "
        "SYN; a doc's score is its mean over its 2 runs). SYN = 8 invented documents "
        "(`scripts/make_syn.py`). Held-out documents are in neither column. n = 1 for v1.1, so "
        "single-doc changes carry run-to-run noise (DESIGN, Where it fails). Source: "
        "`eval/history.jsonl` by run index.",
    ]
    return "\n".join(lines)


def render_gates(history: list[dict], load: list[dict]) -> str:
    del load
    rows = _by_index(history)
    lines = [
        "| Change (decision) | Docs | Base runs → mean | Gate runs → mean | Verdict | Source |",
        "|---|---|---|---|---|---|",
    ]
    for change, dec, base_parts, cand_runs, docs, verdict, src in GATES:
        base: dict[str, list[float]] = {}
        for runs, part_docs in base_parts:
            base.update(runs_per_doc(rows, runs, part_docs))
        cand = runs_per_doc(rows, cand_runs, docs)
        base_runs = " + ".join(_runs_label(r) for r, _ in base_parts)
        lines.append(
            f"| {change} ({dec}) | {len(cand)} | {base_runs} → {_mean_of_doc_means(base):.3f} | "
            f"{_runs_label(cand_runs)} → **{_mean_of_doc_means(cand):.3f}** | {verdict} | "
            f"{src} |"
        )
    lines += [
        "",
        "Mean = per-doc mean over the runs, then over the docs; DEV+SYN docs, held-out never. "
        "Each gate also checked VALID, hallucinations, $/doc and (scans) latency; the verdict "
        "is the one recorded in the source report. Not switched on: `SPEC_RETRY_FEEDBACK` "
        "(P9g; its live gate could not run, run 175 excluded: HTTP 401). Source: "
        "`eval/history.jsonl` by run index.",
    ]
    return "\n".join(lines)


RENDERERS: dict[str, Callable[[list[dict], list[dict]], str]] = {
    "scores": render_scores,
    "results": render_scores,
    "cost": render_cost,
    "load": render_load,
    "chart": render_chart,
    "v11": render_v11,
    "gates": render_gates,
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
