"""P9a (D48, D49): SYN generator, --set support, compare/gate. Invented data only; no HTTP."""

from __future__ import annotations

import filecmp
import importlib.util
import json
import sys

import pytest
from conftest import ROOT


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(ROOT / "scripts"))
make_syn = _load("make_syn")
doc_sets = _load("doc_sets")
eval_dev = _load("eval_dev")
dry_run = _load("dry_run")
compare_runs = _load("compare_runs")

SYN = ROOT / "tests" / "fixtures" / "syn"
HAVE_SAMPLE = (ROOT / "sample" / "schemas").is_dir() and (ROOT / "sample" / "manifest.csv").exists()


# --- generator -------------------------------------------------------------------------------


def test_generator_is_deterministic_and_matches_committed_fixtures(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fa, fb = make_syn.build(a), make_syn.build(b)
    rel = [p.relative_to(a) for p in fa]
    assert rel == [p.relative_to(b) for p in fb] and len(rel) == 18
    assert all(filecmp.cmp(a / r, b / r, shallow=False) for r in rel)
    assert all(filecmp.cmp(a / r, SYN / r, shallow=False) for r in rel)  # fixtures up to date


def test_syn_manifest_lists_eight_docs_with_files_and_answers():
    rows = doc_sets.syn_rows()
    assert len(rows) == 8 and all(d.startswith("syn_") for d in rows)
    for d, r in rows.items():
        assert (SYN / "documents" / r["file"]).exists()
        assert (SYN / "answers" / f"{d}.json").exists()


@pytest.mark.skipif(not HAVE_SAMPLE, reason="sample field lists absent (fresh clone)")
def test_every_syn_answer_is_contract_valid():
    v = eval_dev.validator()
    for d, r in doc_sets.syn_rows().items():
        ans = json.loads((SYN / "answers" / f"{d}.json").read_text(encoding="utf-8"))
        schema = json.loads(open(r["schema_path"], encoding="utf-8").read())
        assert ans["schema"] == r["schema_name"] and ans["document"] == d
        assert v.validate_contract(ans, schema) == [], d


def test_answers_carry_nulls_a_computed_field_and_percent_values():
    def vals(d):
        a = json.loads((SYN / "answers" / f"{d}.json").read_text(encoding="utf-8"))
        return [{k: f["value"] for k, f in e.items()} for e in a["entries"]]

    loan = vals("syn_loan_unseen")[0]
    assert loan["guarantor_name"] is None  # the one absent field
    assert loan["annual_debt_service"] == round(loan["monthly_payment"] * 12, 2)  # computed
    assert loan["interest_rate_pct"] > 1  # a percentage number, not a fraction
    for d in ("syn_lease_text", "syn_lease_scan", "syn_lease_docx"):
        assert any(v is None for v in vals(d)[0].values()), d
    budget = vals("syn_budget_pdf")
    assert any(r["reforecast_vs_prior_budget_pct"] is None for r in budget)  # printed N/A
    loan_schema = json.loads((SYN / "schemas" / "syn_loan_summary.json").read_text("utf-8"))
    assert set(loan_schema["fields"]) == set(loan) and len(loan) == 12


# --- --set support: DEV unchanged --------------------------------------------------------------


@pytest.mark.skipif(not HAVE_SAMPLE, reason="sample manifest absent (fresh clone)")
def test_dev_rows_are_exactly_the_sample_manifest():
    rows = doc_sets.rows_for("dev")
    assert rows == eval_dev.manifest()
    assert not any({"doc_path", "schema_path", "truth_path"} & set(r) for r in rows.values())


def test_dev_paths_are_the_v1_paths():
    row = {"document_id": "widget_doc", "file": "widget_doc.csv", "schema_name": "widgets"}
    assert eval_dev._doc_file(row) == eval_dev.DOCS / "widget_doc.csv"
    assert eval_dev._schema_file("widgets", row) == eval_dev.SCHEMAS / "widgets.json"
    assert eval_dev._schema_file("widgets", None) == eval_dev.SCHEMAS / "widgets.json"
    assert eval_dev._truth_file("widget_doc", row) == eval_dev.TRUTH / "widget_doc.json"
    assert dry_run._doc_file(row) == dry_run.DOCS / "widget_doc.csv"
    assert dry_run._schema_file(row) == dry_run.SCHEMAS / "widgets.json"


def test_syn_rows_use_their_own_paths():
    r = doc_sets.syn_rows()["syn_loan_unseen"]
    assert eval_dev._doc_file(r).parent == SYN / "documents"
    assert eval_dev._truth_file("syn_loan_unseen", r).parent == SYN / "answers"
    assert eval_dev._schema_file(r["schema_name"], r).parent == SYN / "schemas"


def test_unknown_set_is_refused():
    with pytest.raises(ValueError):
        doc_sets.rows_for("nope")


SCHEMA = {"fields": {"qty": {"name": "Qty", "description": "x"}}}


def _fake(monkeypatch, tmp_path, rows):
    (tmp_path / "s.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    for d in rows:
        (tmp_path / f"{d}.json").write_text(json.dumps({"entries": [{"qty": 1}]}), "utf-8")
    job = {"status": "SUCCESS", "result": {"entries": [{"qty": {"value": 1, "citation": "",
           "confidence": 1}}], "metadata": {"cost_usd": 0.001, "cache_mode": "off"}}}  # fmt: skip
    gates_calls: list[tuple] = []

    def gates(*a, **k):
        gates_calls.append((a, k))
        return True, {"dry_run": "passed"}

    monkeypatch.setattr(eval_dev, "SCHEMAS", tmp_path)
    monkeypatch.setattr(eval_dev, "TRUTH", tmp_path)
    monkeypatch.setattr(eval_dev, "paid_run_gates", gates)
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: (200, {}))
    monkeypatch.setattr(eval_dev, "submit_and_wait", lambda base, d, row: job)
    monkeypatch.setattr(eval_dev, "run_id", lambda: "abc1234")
    monkeypatch.setattr(eval_dev, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(eval_dev, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(eval_dev, "ROOT", tmp_path)
    return gates_calls


def test_dev_run_unchanged_and_history_line_carries_set_dev(monkeypatch, tmp_path):
    rows = {"widget_a": {"schema_name": "s", "file": "x"}}
    calls = _fake(monkeypatch, tmp_path, rows)
    monkeypatch.setattr(eval_dev, "manifest", lambda: rows)
    monkeypatch.setattr(eval_dev.doc_sets, "rows_for", lambda s: pytest.fail("dev uses manifest"))
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--report", str(tmp_path / "r.md")])
    assert eval_dev.main() == 0
    assert calls[0][1] == {}  # same positional call as v1.0, no set_name
    h = json.loads((tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert h["set"] == "dev" and h["per_doc"] == {"widget_a": 1.0}
    assert "DEV docs" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_syn_run_reads_syn_rows_and_records_set_syn(monkeypatch, tmp_path):
    row = {"schema_name": "s", "file": "x", "truth_path": str(tmp_path / "syn_widget.json")}
    rows = {"syn_widget": {**row, "schema_path": str(tmp_path / "s.json")}}
    calls = _fake(monkeypatch, tmp_path, rows)
    monkeypatch.setattr(eval_dev, "manifest", lambda: pytest.fail("syn never reads DEV rows"))
    monkeypatch.setattr(eval_dev.doc_sets, "rows_for", lambda s: rows)
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--set", "syn",
                                      "--report", str(tmp_path / "r.md")])  # fmt: skip
    assert eval_dev.main() == 0
    assert calls[0][1] == {"set_name": "syn"}
    h = json.loads((tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert h["set"] == "syn" and h["per_doc"] == {"syn_widget": 1.0}


def test_syn_refuses_write_outputs(monkeypatch):
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: pytest.fail("no HTTP expected"))
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--set", "syn", "--write-outputs"])
    with pytest.raises(SystemExit):
        eval_dev.main()


def test_dry_run_plans_every_syn_doc(monkeypatch, tmp_path):
    monkeypatch.setattr(dry_run, "OUT_DIR", tmp_path)
    if not HAVE_SAMPLE:
        pytest.skip("sample field lists absent (fresh clone)")
    ok, recs = dry_run.run(None, set_name="syn")
    assert ok and len(recs) == 8
    scan = next(r for r in recs if r["doc"] == "syn_lease_scan")
    assert scan["images_total"] == 15  # Z-20: >= 12 pages, form after page 8


# --- compare / gate (D49) ----------------------------------------------------------------------


def agg(score, halluc=0.0, usd=0.005, valid=True, n=2, set_="dev"):
    return {"set": set_, "n": n, "score": score, "halluc": halluc, "missed": 0.0,
            "rows_pred": 1, "rows_truth": 1, "usd": usd, "valid": valid}  # fmt: skip


BASE = {"widget_a": agg(0.60, 2), "widget_b": agg(0.70, 1), "syn_x": agg(0.40, 3, set_="syn")}


def test_gate_passes_on_a_clear_gain():
    cand = {"widget_a": agg(0.62, 2), "widget_b": agg(0.70, 1), "syn_x": agg(0.55, 2, set_="syn")}
    g = compare_runs.gate(BASE, cand)
    assert g["verdict"] == "PASS", g["checks"]


@pytest.mark.parametrize(
    "cand, failing",
    [
        ({"widget_a": agg(0.61, 2), "widget_b": agg(0.70, 1), "syn_x": agg(0.43, 3, set_="syn")},
         "mean_gain"),
        ({"widget_a": agg(0.54, 2), "widget_b": agg(0.75, 1), "syn_x": agg(0.70, 3, set_="syn")},
         "no_dev_drop"),
        ({"widget_a": agg(0.70, 3), "widget_b": agg(0.75, 1), "syn_x": agg(0.60, 3, set_="syn")},
         "halluc"),
        ({"widget_a": agg(0.70, 2, usd=0.03), "widget_b": agg(0.75, 1),
          "syn_x": agg(0.60, 3, set_="syn")}, "usd_per_doc"),
        ({"widget_a": agg(0.70, 2, valid=False), "widget_b": agg(0.75, 1),
          "syn_x": agg(0.60, 3, set_="syn")}, "all_valid"),
        ({"widget_a": agg(0.70, 2), "widget_b": agg(0.75, 1)}, "same_docs"),
    ],
)  # fmt: skip
def test_gate_fails_each_condition_alone(cand, failing):
    g = compare_runs.gate(BASE, cand)
    assert g["verdict"] == "FAIL"
    assert [k for k, (ok, _) in g["checks"].items() if not ok] == [failing]


def test_syn_doc_drop_is_not_a_dev_drop():
    cand = {"widget_a": agg(0.70, 2), "widget_b": agg(0.75, 1), "syn_x": agg(0.34, 3, set_="syn")}
    assert compare_runs.gate(BASE, cand)["checks"]["no_dev_drop"][0]


def test_resolve_last_match_wins_and_unknown_raises():
    hist = [{"run_index": 5, "raw_dir": "aaa/run5"}, {"run_index": 5, "raw_dir": "bbb/run5"}]
    got, notes = compare_runs.resolve(["5", "aaa/run5"], hist)
    assert [h["raw_dir"] for h in got] == ["bbb/run5", "aaa/run5"] and len(notes) == 1
    with pytest.raises(compare_runs.SelectorError):
        compare_runs.resolve(["6"], hist)


def test_run_records_skip_held_out_without_opening(tmp_path, monkeypatch):
    held = sorted(eval_dev.HELD_OUT)
    entry = {"run_index": 1, "raw_dir": "r/run1", "per_doc": {h: 0.5 for h in held}}
    opened: list[str] = []
    monkeypatch.setattr(compare_runs.eval_dev, "score_doc", lambda *a, **k: opened.append(a[0]))
    assert compare_runs.run_records(entry, {}, tmp_path) == [] and opened == []


def test_aggregate_means_over_runs():
    recs = [
        {
            "doc": "widget_a",
            "score": 0.5,
            "totals": {"hallucinated": 2, "missed": 1},
            "rows_predicted": 3,
            "rows_truth": 3,
            "cost_uncached_usd": 0.002,
            "valid": True,
        },
        {
            "doc": "widget_a",
            "score": 0.7,
            "totals": {"hallucinated": 0, "missed": 3},
            "rows_predicted": 3,
            "rows_truth": 3,
            "cost_uncached_usd": 0.004,
            "valid": True,
        },
    ]
    a = compare_runs.aggregate(recs)["widget_a"]  # fmt: skip
    assert a["n"] == 2 and abs(a["score"] - 0.6) < 1e-9 and a["halluc"] == 1 and a["missed"] == 2
    assert abs(a["usd"] - 0.003) < 1e-12 and a["valid"]
