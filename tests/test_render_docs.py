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
