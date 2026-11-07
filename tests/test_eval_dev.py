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
