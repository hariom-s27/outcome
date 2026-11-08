"""render_docs: block filling, run series, idempotence. Invented eval lines only."""

from __future__ import annotations

import json

import pytest

from scripts import render_docs as rd


def _hist(pipeline, path, run_index, per_doc, **kw):
    row = {
        "pipeline": pipeline,
        "path": path,
        "run_index": run_index,
        "per_doc": per_doc,
        "n_docs": len(per_doc),
        "mean_score": sum(per_doc.values()) / len(per_doc),
        "all_valid": True,
        "usd_per_doc": 0.001,
        "cost_usd": 0.002,
        "prompt_version": "pv1",
        "date": "2001-02-03T04:05:06Z",
        "aborted": None,
    }
    row.update(kw)
    return row


HISTORY = [
    _hist("pipe-a", "baseline", 1, {"doc_x": 0.5, "doc_y": 0.7}),
    _hist("pipe-a", "baseline", 1, {"doc_x": 0.6, "doc_y": 0.8}),
    _hist("pipe-b", "smart", 1, {"doc_x": 0.1}),  # older series, different docs
    _hist("pipe-b", "smart", 1, {"doc_x": 0.2, "doc_z": 0.4}),
    _hist("pipe-b", "smart", 2, {"doc_x": 0.4, "doc_z": 0.6}),
    _hist("pipe-b", "smart", 3, {"doc_x": 0.6, "doc_z": 0.8}),
]
LOAD = [
    {"scenario": "L1", "workers": 1, "n": 4, "p50_s": 9.0, "pass": False, "git_sha": "old"},
    {
        "scenario": "L1",
        "workers": 1,
        "n": 4,
        "completion_pct": 100.0,
        "valid_pct": 100.0,
        "p50_s": 1.5,
        "p95_s": 2.5,
        "max_s": 3.0,
        "throughput_per_min": 7.0,
        "lost": 0,
        "duplicates": 0,
        "post_max_s": 0.1,
        "http_5xx": 0,
        "pass": True,
        "git_sha": "abc1234",
    },
    {
        "scenario": "L2",
        "workers": 2,
        "n": 2,
        "lost": 0,
        "duplicates": 0,
        "http_5xx": 0,
        "pass": True,
        "git_sha": "abc1234",
        "recovery_s": 61.0,
        "killed_job_claims": 2,
        "killed_job_status": "SUCCESS",
        "killed_job_terminal_events": 1,
    },
]
DOC = (
    "intro\n<!-- AUTO:scores -->\nstale\n<!-- /AUTO:scores -->\nmiddle\n"
    "<!-- AUTO:load -->\n<!-- /AUTO:load -->\n<!-- AUTO:cost -->x<!-- /AUTO:cost -->\nend\n"
)


def test_latest_series_takes_whole_run_countdown():
    series = rd.latest_series(HISTORY)
    assert len(series[("pipe-a", "baseline")]) == 1  # run_index 1 only: the latest line
    smart = series[("pipe-b", "smart")]
    assert [r["run_index"] for r in smart] == [1, 2, 3]
    st = rd.series_stats(smart)
    assert st["per_doc"]["doc_x"] == pytest.approx(0.4)
    assert st["mean"] == pytest.approx(0.5)


def test_series_stops_at_changed_prompt_version():
    rows = [
        _hist("p", "smart", 1, {"d": 0.1}, prompt_version="old"),
        _hist("p", "smart", 2, {"d": 0.3}),
    ]
    assert len(rd.latest_series(rows)[("p", "smart")]) == 1


def test_aborted_lines_ignored():
    rows = [
        _hist("p", "baseline", 1, {"d": 0.9}),
        _hist("p", "baseline", 1, {"d": 0.1}, aborted="budget"),
    ]
    st = rd.series_stats(rd.latest_series(rows)[("p", "baseline")])
    assert st["mean"] == pytest.approx(0.9)


def test_render_fills_only_blocks_and_is_idempotent():
    once = rd.render_text(DOC, HISTORY, LOAD)
    assert once.startswith("intro\n<!-- AUTO:scores -->\n")
    assert "\nmiddle\n" in once and once.endswith("<!-- /AUTO:cost -->\nend\n")
    assert "stale" not in once
    assert "**0.700**" in once  # pipe-a latest: (0.6 + 0.8) / 2
    assert "**0.500**" in once  # pipe-b 3-run series
    assert "abc1234" in once and "| 9.0 |" not in once  # latest L1 line wins
    assert "61.0 s after the kill" in once
    assert rd.render_text(once, HISTORY, LOAD) == once


def test_unclosed_and_unknown_blocks_fail():
    with pytest.raises(SystemExit):
        rd.render_text("<!-- AUTO:scores -->\nno end\n", HISTORY, LOAD)
    with pytest.raises(SystemExit):
        rd.render_text("<!-- AUTO:nope -->\n<!-- /AUTO:nope -->\n", HISTORY, LOAD)


def test_empty_sources_render_placeholders():
    out = rd.render_text(DOC, [], [])
    assert "_No eval runs recorded yet._" in out and "_No load runs recorded yet._" in out


def test_main_check_and_write(tmp_path):
    hist = tmp_path / "h.jsonl"
    load = tmp_path / "l.jsonl"
    hist.write_text("".join(json.dumps(r) + "\n" for r in HISTORY), encoding="utf-8")
    load.write_text("".join(json.dumps(r) + "\n" for r in LOAD), encoding="utf-8")
    doc = tmp_path / "D.md"
    doc.write_text(DOC, encoding="utf-8")
    args = ["--history", str(hist), "--load", str(load), str(doc)]
    assert rd.main(["--check", *args]) == 1
    assert doc.read_text(encoding="utf-8") == DOC  # --check never writes
    assert rd.main(args) == 0
    first = doc.read_bytes()
    assert rd.main(args) == 0 and doc.read_bytes() == first
    assert rd.main(["--check", *args]) == 0
    assert b"\r\n" not in first


# --- P8b: the sealed final run and the cost-vs-accuracy chart -------------------------------------

FINAL = _hist(
    "pipe-a,pipe-c",
    "baseline+table:ai",
    90,
    {"doc_x": 0.9, "doc_h": 0.3},
    final=True,
    n_dev=1,
    dev_mean_score=0.9,
    held_out_per_doc={"doc_h": 0.3},
    path_per_doc={"doc_x": "table:ai", "doc_h": "baseline"},
    all_live=True,
    run_id="abc1234",
)


def test_final_run_is_never_part_of_a_series():
    series = rd.latest_series([*HISTORY, FINAL])
    assert all(not r.get("final") for s in series.values() for r in s)
    assert rd.latest_series([*HISTORY, FINAL]) == rd.latest_series(HISTORY)


def test_scores_and_cost_show_the_final_run_with_held_out_apart():
    text = rd.render_scores([*HISTORY, FINAL], [])
    assert "| doc_x | DEV | table:ai | 0.900 |" in text
    assert "| doc_h | held-out, scored once | baseline | 0.300 |" in text
    assert "DEV mean 0.900 (n = 1 documents, 1 run)" in text and "doc_h 0.300" in text
    assert "per document** (uncached, mean over 2 documents)" in rd.render_cost([FINAL], [])
    assert "Shipped default path" in rd.render_scores(HISTORY, [])  # no final: old table


def test_chart_points_complete_partial_configs_with_the_p2_baseline():
    from scripts import plot_cost_accuracy as pca

    hist = [
        _hist("b", "baseline", None, {"d1": 0.4, "d2": 0.6}, label="P2-36 x", usd_per_doc=0.004),
        _hist("s", "smart", 1, {"d1": 0.8}, label="P5b run1", usd_per_doc=0.002),
        _hist("s", "smart", 2, {"d1": 0.6}, label="P5b run2", usd_per_doc=0.002),
        {**FINAL, "per_doc": {"d1": 1.0, "d2": 0.8, "doc_h": 0.3}, "usd_per_doc": 0.001},
    ]
    pts = {p["label"]: p for p in pca.points(hist, {"d1": 0.5})}
    assert pts["baseline P2"]["score"] == pytest.approx(0.5)
    p5b = pts["smart P5b"]  # d1 = mean(0.8, 0.6), d2 from the baseline
    assert p5b["score"] == pytest.approx(0.65) and p5b["usd"] == pytest.approx(0.003)
    assert pts["hybrid sim P5c"]["usd"] == pytest.approx((0.006 + 0.004) / 2)
    assert pts["final (shipped)"]["score"] == pytest.approx(0.9)  # held-out never plotted


def test_hybrid_means_reads_the_bold_column(tmp_path):
    from scripts import plot_cost_accuracy as pca

    log = tmp_path / "sim.md"
    log.write_text(
        "| doc_001 | 0.1 | 0.2 | 0.3 | **0.2000** | 0.5 |\n| x | y |\n", encoding="utf-8"
    )
    assert pca.hybrid_means(log) == {"doc_001": 0.2}


# --- P9f: v1.1 blocks (invented runs and docs) ------------------------------------------------


def _v11_history(monkeypatch):
    monkeypatch.setattr(rd, "V11_BASE_RUNS", (1, 2, 3, 4))
    monkeypatch.setattr(rd, "V11_RUN", 9)
    return [
        _hist("p", "x", 1, {"d1": 0.4, "dh": 0.9}, held_out_per_doc={"dh": 0.9}),
        _hist("p", "x", 2, {"d1": 0.6}, set="dev"),
        _hist("p", "x", 3, {"s1": 0.2}, set="syn"),
        _hist("p", "x", 4, {"s1": 0.4}, set="syn"),
        _hist("p", "x", 9, {"d1": 0.8, "s1": 1.0}, set="all", usd_per_doc=0.002),
    ]


def test_v11_block_compares_base_and_shipped_run(monkeypatch):
    out = rd.render_v11(_v11_history(monkeypatch), [])
    assert "| d1 | DEV | 0.500 | 0.800 | +0.300 |" in out
    assert "| s1 | SYN | 0.300 | 1.000 | +0.700 |" in out
    assert "DEV+SYN (n = 2) 0.400 → **0.900**" in out
    assert "dh" not in out  # held-out never shown
    assert "SCAN_PAGE_METHOD=all" in out and "SPEC_RETRY_FEEDBACK=0" in out


def test_v11_block_without_the_run(monkeypatch):
    hist = _v11_history(monkeypatch)[:-1]
    assert rd.render_v11(hist, []).startswith("_No v1.1")


def test_gates_block_means_and_run_labels(monkeypatch):
    hist = _v11_history(monkeypatch)
    gate = ("Thing", "Z-0", (((1, 2), ("d1",)), ((3, 4), None)), (9,), None, "PASS", "src")
    monkeypatch.setattr(rd, "GATES", (gate,))
    out = rd.render_gates(hist, [])
    # base: d1 mean(0.4, 0.6) = 0.5, s1 mean(0.2, 0.4) = 0.3 -> 0.4; cand: (0.8 + 1.0) / 2
    assert "| Thing (Z-0) | 2 | 1, 2 + 3, 4 → 0.400 | 9 → **0.900** | PASS | src |" in out
    assert rd._runs_label((141, 142, 143)) == "141–143"
    assert rd._runs_label((90, 103, 101, 102)) == "90, 103, 101, 102"


def test_gates_block_refuses_a_missing_run(monkeypatch):
    gate = ("T", "Z", (((7,), None),), (9,), None, "PASS", "s")
    monkeypatch.setattr(rd, "GATES", (gate,))
    with pytest.raises(SystemExit):
        rd.render_gates(_v11_history(monkeypatch), [])


def test_final_def_labels_the_sealed_run_v10():
    assert "v1.0" in rd.FINAL_DEF and "no v1.1 held-out run" in rd.FINAL_DEF
