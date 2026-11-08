"""scripts/eval_dev.py: held-out seal and the error taxonomy, on invented data. No HTTP."""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from conftest import ROOT

_spec = importlib.util.spec_from_file_location("eval_dev", ROOT / "scripts" / "eval_dev.py")
eval_dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_dev)

SCHEMA = {
    "fields": {
        "sku": {"name": "SKU", "description": "x", "primary": True},
        "qty": {"name": "Qty", "description": "x"},
        "opened": {"name": "Opened", "description": "x"},
        "note": {"name": "Note", "description": "x"},
    }
}


def e(sku, qty, opened, note):
    return {
        "sku": {"value": sku},
        "qty": {"value": qty},
        "opened": {"value": opened},
        "note": {"value": note},
    }


def test_held_out_docs_are_refused_without_final_sealed(monkeypatch, capsys):
    sealed = sorted(eval_dev.HELD_OUT)[0]
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: pytest.fail("no HTTP expected"))
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--docs", sealed])
    assert eval_dev.main() == 2
    assert "refused" in capsys.readouterr().out


def test_report_goes_to_the_given_path_never_an_older_phase_report(tmp_path):
    assert eval_dev.REPORT.name == "eval_latest.md"  # default is not a phase report
    rec = {"doc": "widget_doc", "status": "SUCCESS", "valid": True, "score": 0.5}
    summary = eval_dev.summarise([rec], "abc1234", "invented", None)
    out = tmp_path / "logs" / "P9_eval.md"
    eval_dev.write_report([rec], summary, out)
    assert out.exists() and "widget_doc" in out.read_text(encoding="utf-8")
    assert not (tmp_path / "logs" / "eval_latest.md").exists()


def test_reuse_from_needs_live_docs(monkeypatch):
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: pytest.fail("no HTTP expected"))
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--reuse-from", "abc1234"])
    with pytest.raises(SystemExit):
        eval_dev.main()


def test_default_doc_list_never_includes_held_out():
    rows = {"d1": {}, "d2": {}, **{h: {} for h in eval_dev.HELD_OUT}}
    assert [d for d in rows if d not in eval_dev.HELD_OUT] == ["d1", "d2"]


def test_taxonomy_counts_by_kind_and_truth_type():
    truth = {
        "entries": [
            e("W-1", 3, "2031-04-05", None),
            e("W-2", 5, "2031-05-06", "fragile"),
            e("W-3", 1, None, None),
        ]
    }
    pred = {
        "entries": [
            e("W-1", 3, "2031-04-05", "invented note"),  # note hallucinated
            e("W-2", 6, None, "fragile"),  # qty wrong, opened missed
            e("W-9", 1, None, None),  # extra row; W-3 missing
        ]
    }
    tax = eval_dev.taxonomy(pred, truth, SCHEMA)
    assert tax["totals"] == {"right": 5, "wrong": 1, "missed": 1, "hallucinated": 1}
    assert tax["per_field_counts"]["qty"] == {"right": 1, "wrong": 1}
    assert tax["per_type"]["date"] == {"right": 1, "missed": 1}
    assert tax["per_type"]["null"] == {"hallucinated": 1}
    assert tax["extra_rows"] == 1 and tax["missing_rows"] == 1


def test_value_types():
    assert [eval_dev.value_type(v) for v in (3, "2031-01-02", True, "abc", None, [1])] == [
        "number",
        "date",
        "bool",
        "text",
        "null",
        "list",
    ]


def test_cache_hits_are_priced_uncached_for_dollars_per_doc():
    hit = {"doc": "d1", "score": 1.0, "cost_usd": 0.0, "cost_uncached_usd": 0.01}
    paid = {"doc": "d2", "score": 0.5, "cost_usd": 0.03}  # no cache hit: uncached = paid
    s = eval_dev.summarise([hit, paid], "rid", "", None)
    assert s["cost_usd"] == 0.03 and s["cost_uncached_usd"] == 0.04
    assert s["usd_per_doc"] == 0.02 and s["usd_per_doc_paid"] == 0.015


def test_score_doc_reads_the_uncached_cost(monkeypatch, tmp_path):
    meta = {"cost_usd": 0.0, "cost_uncached_usd": 0.0123, "cache_hits": 2}
    job = {"status": "SUCCESS", "result": {"entries": [], "metadata": meta}}
    schema = {"fields": SCHEMA["fields"]}
    (tmp_path / "s.json").write_text(json.dumps(schema), encoding="utf-8")
    (tmp_path / "d.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(eval_dev, "SCHEMAS", tmp_path)
    monkeypatch.setattr(eval_dev, "TRUTH", tmp_path)
    rec = eval_dev.score_doc("d", "s", job)
    assert rec["cost_usd"] == 0.0 and rec["cost_uncached_usd"] == 0.0123
    assert rec["replays"] == 2 and rec["path"] == "baseline"


# --- P5 D-1 / D-2: --expect-live and the new history fields ------------------------------------


def _job(cache_hits=0, path="smart", cost=0.001):
    meta = {"cost_usd": cost, "model_calls": 1, "cache_hits": cache_hits,
            "cache_mode": "off", "pipeline": "single-value-v1"}  # fmt: skip
    if path == "smart":
        meta["extraction"] = {"path": "smart", "cache_mode": "off", "cache_replays": cache_hits}
    return {"status": "SUCCESS", "result": {"entries": [], "metadata": meta}}


def _fake_run(monkeypatch, tmp_path, jobs: dict, argv: list[str]):
    rows = {d: {"schema_name": "s", "file": "x"} for d in jobs}
    (tmp_path / "s.json").write_text(json.dumps({"fields": SCHEMA["fields"]}), encoding="utf-8")
    for d in jobs:
        (tmp_path / f"{d}.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    scored: list[str] = []
    real_score = eval_dev.score_doc

    def score(doc_id, schema_name, job):
        scored.append(doc_id)
        return real_score(doc_id, schema_name, job)

    monkeypatch.setattr(eval_dev, "manifest", lambda: rows)
    monkeypatch.setattr(eval_dev, "paid_run_gates", lambda *a, **k: (True, {"dry_run": "passed"}))
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: (200, {}))
    monkeypatch.setattr(eval_dev, "submit_and_wait", lambda base, d, row: jobs[d])
    monkeypatch.setattr(eval_dev, "run_id", lambda: "abc1234")
    monkeypatch.setattr(eval_dev, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(eval_dev, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(eval_dev, "ROOT", tmp_path)  # the script prints HISTORY relative to it
    monkeypatch.setattr(eval_dev, "SCHEMAS", tmp_path)
    monkeypatch.setattr(eval_dev, "TRUTH", tmp_path)
    monkeypatch.setattr(eval_dev, "score_doc", score)
    report = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--docs", *jobs, "--report", str(report),
                                      *argv])  # fmt: skip
    return scored


def test_expect_live_refuses_to_score_a_replay(monkeypatch, tmp_path, capsys):
    jobs = {"d1": _job(), "d2": _job(cache_hits=1)}
    scored = _fake_run(monkeypatch, tmp_path, jobs, ["--expect-live"])
    assert eval_dev.main() == 3
    out = capsys.readouterr().out
    assert "refused" in out and "score=" not in out
    assert scored == [] and not (tmp_path / "history.jsonl").exists()


def test_live_run_records_path_cache_mode_run_index_prompt_version(monkeypatch, tmp_path):
    from app.pipeline.single_value import PROMPT_VERSION

    jobs = {"d1": _job(), "d2": _job(path="baseline")}
    scored = _fake_run(monkeypatch, tmp_path, jobs, ["--expect-live", "--run-index", "2"])
    assert eval_dev.main() == 0 and scored == ["d1", "d2"]
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    h = json.loads(lines[-1])
    assert h["path"] == "baseline+smart" and h["path_per_doc"] == {"d1": "smart", "d2": "baseline"}
    assert h["cache_mode"] == "off" and h["run_index"] == 2 and h["all_live"] is True
    assert h["prompt_version"] == PROMPT_VERSION and len(PROMPT_VERSION) == 12


def test_without_expect_live_a_replay_is_scored_but_not_all_live(monkeypatch, tmp_path):
    jobs = {"d1": _job(cache_hits=1)}
    scored = _fake_run(monkeypatch, tmp_path, jobs, [])
    assert eval_dev.main() == 0 and scored == ["d1"]
    h = json.loads((tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert h["all_live"] is False and h["run_index"] == 1


def test_history_is_append_only(monkeypatch, tmp_path):
    (tmp_path / "history.jsonl").write_text('{"old": 1}\n', encoding="utf-8")
    _fake_run(monkeypatch, tmp_path, {"d1": _job()}, [])
    assert eval_dev.main() == 0
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"old": 1}' and len(lines) == 2
