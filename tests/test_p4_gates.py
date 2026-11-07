"""P4 Part 0 gates on invented data: clean-tree check (fake git), dry run (R-A), the eval gate,
the spike launcher's caps and mounts. No network, no key, no Docker."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_gates = _load("run_gates", "scripts/run_gates.py")
dry_run = _load("dry_run", "scripts/dry_run.py")
eval_dev = _load("eval_dev_p4", "scripts/eval_dev.py")
launch = _load("p4_launch", "scripts/spikes/p4_launch.py")


def fake_git(porcelain: str):
    def git(args: list[str]) -> str:
        assert args[0] in ("status", "rev-parse")
        return porcelain if args[0] == "status" else "abc1234\n"

    return git


# --- clean tree (PR-09) -------------------------------------------------------------------------


def test_clean_tree_passes():
    ok, msg = run_gates.clean_tree_gate(False, git=fake_git(""))
    assert ok and msg == "clean tree"


def test_dirty_code_refused_with_count_only():
    porcelain = " M app/x.py\n?? scripts/spikes/\n?? notes.txt\n"
    ok, msg = run_gates.clean_tree_gate(False, git=fake_git(porcelain))
    assert not ok
    assert "2 uncommitted code/config paths" in msg and "app/x.py" not in msg


def test_results_and_logs_do_not_count():
    porcelain = " M eval/history.jsonl\n?? logs/P4_plan.md\n?? eval/spikes.jsonl\n M README.md\n"
    ok, msg = run_gates.clean_tree_gate(False, git=fake_git(porcelain))
    assert ok and msg == "clean tree"


@pytest.mark.parametrize(
    "line",
    [
        " M app/api.py",
        "?? scripts/new.py",
        "?? config/models.yaml",
        " M tests/test_x.py",
        " M .claude/hooks/guard.py",
        " M compose.yaml",
        "?? compose.dev.yaml",
        " M Dockerfile",
        " M pyproject.toml",
        " M uv.lock",
        "R  logs/old.md -> scripts/moved.py",
    ],
)
def test_each_code_config_path_counts(line):
    assert run_gates.dirty_paths(fake_git(line + "\n")) == [line]


def test_dirty_tree_allowed_only_by_flag_and_said_so():
    ok, msg = run_gates.clean_tree_gate(True, git=fake_git("?? app/new.py\n"))
    assert ok and msg.startswith("DIRTY")


def test_head_sha_from_git():
    assert run_gates.head_sha(fake_git("")) == "abc1234"


# --- dry run (R-A) ------------------------------------------------------------------------------


@pytest.fixture
def invented_doc(tmp_path, monkeypatch):
    (tmp_path / "tiny.csv").write_text("item,amount\nalpha,10\nbeta,20\n", encoding="utf-8")
    schema = {"fields": {"amount": {"name": "Amount", "description": "an invented amount"}}}
    (tmp_path / "s.json").write_text(json.dumps(schema), encoding="utf-8")
    rows = {"doc_a": {"document_id": "doc_a", "file": "tiny.csv", "schema_name": "s"}}
    monkeypatch.setattr(dry_run, "DOCS", tmp_path)
    monkeypatch.setattr(dry_run, "SCHEMAS", tmp_path)
    monkeypatch.setattr(dry_run, "manifest", lambda: rows)
    monkeypatch.setattr(dry_run, "OUT_DIR", tmp_path / "out")
    return rows


def test_dry_run_ok_on_invented_csv(invented_doc):
    ok, recs = dry_run.run(["doc_a"])
    assert ok
    r = recs[0]
    assert r["file_type"] == "csv" and r["blocks"] >= 2 and r["fuse_tokens_est"] > 0
    assert r["images_sent"] == 0 and not r["truncated"]


def test_dry_run_fails_on_exception(invented_doc, tmp_path):
    (tmp_path / "tiny.csv").unlink()
    ok, recs = dry_run.run(["doc_a"])
    assert not ok and recs[0]["error"] == "FileNotFoundError"


def test_dry_run_fails_at_token_limit(invented_doc, monkeypatch):
    monkeypatch.setattr(dry_run, "TOKEN_LIMIT", 10)
    ok, recs = dry_run.run(["doc_a"])
    assert not ok and recs[0]["error"].startswith("estimate")


def test_dry_run_refuses_held_out_and_unknown(invented_doc):
    assert dry_run.run([sorted(dry_run.HELD_OUT)[0]])[0] is False
    assert dry_run.run(["nope"])[0] is False


def test_dry_run_main_exit_codes(invented_doc, tmp_path, monkeypatch, capsys):
    assert dry_run.main(["--docs", "doc_a"]) == 0
    monkeypatch.setattr(dry_run, "TOKEN_LIMIT", 10)
    assert dry_run.main(["--docs", "doc_a"]) == 1
    assert "FAILED" in capsys.readouterr().out
    assert list((tmp_path / "out").glob("*.json"))


# --- eval gate ----------------------------------------------------------------------------------


def test_eval_refuses_dirty_tree_before_any_http(monkeypatch):
    monkeypatch.setattr(eval_dev.run_gates, "dirty_paths", lambda git=None: ["?? x"])
    monkeypatch.setattr(eval_dev, "manifest", lambda: {"d1": {"schema_name": "s"}})
    monkeypatch.setattr(eval_dev, "call", lambda *a, **k: pytest.fail("no HTTP expected"))
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--docs", "d1"])
    assert eval_dev.main() == 2


def test_eval_refuses_failed_dry_run(monkeypatch):
    monkeypatch.setattr(eval_dev.dry_run, "run", lambda docs: (False, [{"doc": "d1", "ok": False}]))
    ok, gates = eval_dev.paid_run_gates(["d1"], False, False, git=fake_git(""))
    assert not ok and gates["dry_run"] == "failed"


def test_eval_gate_records_skips_and_dirty(monkeypatch):
    monkeypatch.setattr(eval_dev.dry_run, "run", lambda docs: pytest.fail("skipped"))
    ok, gates = eval_dev.paid_run_gates(["d1"], True, True, git=fake_git("?? app/x.py\n"))
    assert ok and gates == {"allow_dirty_used": True, "dry_run": "skipped"}
    summary = eval_dev.summarise([], "rid", "", None, gates)
    assert summary["dry_run"] == "skipped" and summary["allow_dirty_used"] is True


def test_eval_reuse_needs_no_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_dev, "paid_run_gates", lambda *a, **k: pytest.fail("no gate"))
    monkeypatch.setattr(eval_dev, "manifest", lambda: {"d1": {"schema_name": "s"}})
    monkeypatch.setattr(eval_dev, "RUNS", tmp_path)
    monkeypatch.setattr(
        eval_dev, "score_doc", lambda d, s, job: {"doc": d, "valid": False, "score": 0.0}
    )
    (tmp_path / "r1").mkdir()
    (tmp_path / "r1" / "d1.json").write_text('{"status": "FAILED"}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["eval_dev.py", "--reuse", "r1", "--docs", "d1",
                                      "--no-record"])  # fmt: skip
    assert eval_dev.main() == 0


# --- spike launcher -----------------------------------------------------------------------------


def test_launcher_total_cap(tmp_path):
    for name, spent, dry in (("a", 0.12, False), ("b", 0.05, False), ("c", 9.0, True)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "summary.json").write_text(
            json.dumps({"spent_usd": spent, "dry_run": dry}), encoding="utf-8"
        )
    spent = launch.spent_so_far(tmp_path)
    assert spent == pytest.approx(0.17)
    assert launch.capped(0.10, 0.30, spent) == pytest.approx(0.10)
    assert launch.capped(0.20, 0.30, spent) == pytest.approx(0.13)
    assert launch.capped(0.10, 0.30, 0.30) <= 0


def test_launcher_mounts_never_include_answers():
    cmd = launch.docker_cmd("b3", "abc-b3-x", 0.05, True, ["--repeats", "3"])
    joined = " ".join(cmd)
    assert "sample-data-output-validated" not in joined
    assert "-e LLM_CACHE_DIR=" in joined and cmd[-2:] == ["--repeats", "3"]
    assert "/srv/devdocs:ro" in joined and "/srv/scripts:ro" in joined


def test_launcher_refuses_dirty_tree(monkeypatch):
    monkeypatch.setattr(launch.run_gates, "dirty_paths", lambda git=None: ["?? x"])
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("no docker"))
    assert launch.main(["b1", "--max-usd", "0.01"]) == 2
