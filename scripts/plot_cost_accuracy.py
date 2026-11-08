"""Cost-vs-accuracy chart (P8b Z-9): DEV score vs $/doc per pipeline config.

    uv run python scripts/plot_cost_accuracy.py            # writes docs/cost_vs_accuracy.png
    uv run python scripts/plot_cost_accuracy.py --print    # the points as a markdown table only

One point per config, every number computed from committed sources, never typed by hand:
  baseline P2      eval/history.jsonl, the P2-36 line (6 DEV docs, 1 run)
  smart P5 / P5b   the 3 live runs of each (3 single-value docs)
  hybrid sim P5c   logs/P5c_hybrid_sim.md "Hybrid mean" column (offline re-score of the P5b
                   runs + P2 baseline; both calls are paid, so $ = P5b + P2 per doc)
  table recipe P6b the 3 live runs (3 table docs)
  final            the sealed final run (`final: true`): score over the 6 DEV docs; $/doc is
                   the run's mean over all 8 docs (history keeps no per-doc $)
A config measured on k < 6 DEV docs is completed with the P2 baseline for the other docs
(score per doc; $ as P2's mean $/doc), so every point is a 6-doc DEV mean. Held-out docs are
never in the chart. $ = uncached $/doc (what a grader pays).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "eval" / "history.jsonl"
HYBRID_LOG = ROOT / "logs" / "P5c_hybrid_sim.md"
PNG = ROOT / "docs" / "cost_vs_accuracy.png"
HELD_OUT = frozenset({"lease_003", "budget_001"})  # D03; never plotted

# label -> predicate over a history line (selection by recorded labels, not by values)
CONFIGS: list[tuple[str, object]] = [
    ("baseline P2", lambda r: "P2-36" in str(r.get("label"))),
    ("smart P5", lambda r: str(r.get("label")).startswith("P5 S3 run")),
    ("smart P5b", lambda r: str(r.get("label")).startswith("P5b run")),
    ("table recipe P6b", lambda r: str(r.get("label")).startswith("p6b-spec-r")),
    ("final (shipped)", lambda r: r.get("final") is True),
]


def read_history(path: Path = HISTORY) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def hybrid_means(path: Path = HYBRID_LOG) -> dict[str, float]:
    """Per-doc 'Hybrid mean' (the bold cell) from the committed P5c table."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([a-z]+_\d{3})\s*\|(?:[^|]*\|){3}\s*\*\*([0-9.]+)\*\*\s*\|", line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def _runs_mean(rows: list[dict]) -> tuple[dict[str, float], float]:
    docs = sorted({d for r in rows for d in r.get("per_doc", {}) if d not in HELD_OUT})
    per_doc = {
        d: statistics.fmean(r["per_doc"][d] for r in rows if d in r.get("per_doc", {}))
        for d in docs
    }
    usd = statistics.fmean(float(r.get("usd_per_doc") or 0.0) for r in rows)
    return per_doc, usd


def points(history: list[dict], hybrid: dict[str, float] | None = None) -> list[dict]:
    """[{label, score, usd, docs_measured, runs}] as 6-doc DEV composites (see module doc)."""
    base_rows = [r for r in history if CONFIGS[0][1](r)]
    if not base_rows:
        return []
    base_doc, base_usd = _runs_mean(base_rows[-1:])
    dev = sorted(base_doc)
    out = []

    def add(label: str, per_doc: dict[str, float], usd_measured: float, runs: int) -> None:
        k = len([d for d in per_doc if d in base_doc])
        score = statistics.fmean(per_doc.get(d, base_doc[d]) for d in dev)
        usd = (k * usd_measured + (len(dev) - k) * base_usd) / len(dev)
        out.append({"label": label, "score": score, "usd": usd, "docs_measured": k, "runs": runs})

    for label, pred in CONFIGS:
        rows = [r for r in history if pred(r) and not r.get("aborted")]
        if not rows:
            continue
        if label == "baseline P2":
            rows = rows[-1:]
        per_doc, usd = _runs_mean(rows)
        add(label, per_doc, usd, len(rows))
        if label == "smart P5b" and hybrid:  # hybrid sim builds on the P5b runs + P2 baseline
            add("hybrid sim P5c", hybrid, usd + base_usd, len(rows))
    return out


def markdown(pts: list[dict]) -> str:
    lines = [
        "| Config | DEV score (6-doc) | $/doc uncached | DEV docs measured | Runs |",
        "|---|---|---|---|---|",
    ]
    for p in pts:
        lines.append(
            f"| {p['label']} | {p['score']:.3f} | ${p['usd']:.5f} | {p['docs_measured']} | "
            f"{p['runs']} |"
        )
    return "\n".join(lines)


def draw(pts: list[dict], path: Path = PNG) -> None:
    from PIL import Image, ImageDraw, ImageFont

    w, h, left, right, top, bottom = 960, 620, 90, 40, 80, 80
    img = Image.new("RGB", (w, h), "white")
    g = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=15)
    small = ImageFont.load_default(size=13)
    step = 0.001
    xmax = step * (int(max(p["usd"] for p in pts) * 1.1 / step) + 1)
    ymin, ymax = 0.4, 1.0

    def xy(usd: float, score: float) -> tuple[float, float]:
        x = left + usd / xmax * (w - left - right)
        y = top + (ymax - score) / (ymax - ymin) * (h - top - bottom)
        return x, y

    g.text((left, 12), "DEV score vs $/document (uncached), per pipeline config", "black", font)
    g.text((left, 36), "score = mean over the 6 DEV docs", "black", small)
    g.line([(left, top), (left, h - bottom), (w - right, h - bottom)], "black", 1)
    for i in range(7):  # y ticks 0.4 .. 1.0
        s = ymin + i * 0.1
        _, y = xy(0, s)
        g.line([(left - 5, y), (w - right, y)], (225, 225, 225), 1)
        g.text((left - 45, y - 8), f"{s:.1f}", "black", small)
    for i in range(int(round(xmax / step)) + 1):
        u = i * step
        x, _ = xy(u, ymin)
        g.line([(x, h - bottom), (x, h - bottom + 5)], "black", 1)
        g.text((x - 22, h - bottom + 10), f"${u:.3f}", "black", small)
    g.text((w // 2 - 120, h - 35), "$ per document (uncached, mean)", "black", font)
    for p in pts:
        x, y = xy(p["usd"], p["score"])
        final = p["label"].startswith("final")
        color = (200, 60, 30) if final else (40, 90, 170)
        g.ellipse([x - 6, y - 6, x + 6, y + 6], color)
        text = f"{p['label']} ({p['score']:.3f})"
        tw = g.textlength(text, font=small)
        tx, ty = x + 9, y - 9
        if x + tw + 12 > w - right:  # no room on the right: above the point, right-aligned
            tx, ty = x - tw + 6, y - 28
        if final:  # final sits next to the P6b point: label below
            ty = y + 8
        g.text((tx, ty), text, "black", small)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", action="store_true", help="print the points only, no PNG")
    args = ap.parse_args(argv)
    pts = points(read_history(), hybrid_means())
    if not pts:
        print("no baseline line in eval/history.jsonl")
        return 1
    print(markdown(pts))
    if not args.print:
        draw(pts)
        print(f"wrote {PNG.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
