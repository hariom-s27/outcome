"""P4 spike harness helpers on invented data: page batches, merge rules, field groups, page
choice, dry-run estimates and the host scorer's held-out refusal. No network, no key."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "spikes"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pc = _load("p4_common", "scripts/spikes/p4_common.py")
b2 = _load("p4_b2", "scripts/spikes/p4_b2.py")
score = _load("p4_score", "scripts/spikes/p4_score.py")
Block = pc.Block


def cell(v, cit="", conf=0.9):
    return {"value": v, "citation": cit, "confidence": conf}


FIELDS = {"a": {"name": "A"}, "b": {"name": "B"}, "c": {"name": "C"}, "d": {"name": "D"}}


def test_page_batches_cap_pages():
    blocks = [Block("image", f"Page {p}", "", p) for p in range(1, 11)]
    batches = pc.page_batches(blocks, 8)
    assert [len(b) for b in batches] == [8, 2]
    assert pc.batch_pages(batches[1]) == {9, 10}


def test_merge_batches_one_entry_rules():
    first = {1, 2, 3}
    second = {4, 5}
    r1 = [{"a": cell(5, "[Page 1] x"), "b": cell("x", "[Page 2] x"),
           "c": cell("p", "[Page 1] p"), "d": cell(None)}]  # fmt: skip
    r2 = [{"a": cell(None), "b": cell("y", "[Page 9] y"),
           "c": cell("q", "[Page 4] q"), "d": cell(None)}]  # fmt: skip
    merged, conflicts = pc.merge_batches([(r1, first), (r2, second), (None, {6})], FIELDS)
    m = merged[0]
    assert m["a"]["value"] == 5  # non-null wins
    assert m["b"]["value"] == "x"  # only x is cited on a page its batch saw
    assert m["c"]["value"] is None and conflicts == ["c"]  # both grounded, different
    assert m["d"] == pc.NULL_CELL


def test_merge_batches_equal_values_keep_highest_confidence():
    r1 = [{k: cell(1, "[Page 1] 1", 0.4) for k in FIELDS}]
    r2 = [{k: cell(1.0, "[Page 2] 1", 0.8) for k in FIELDS}]
    merged, conflicts = pc.merge_batches([(r1, {1}), (r2, {2})], FIELDS)
    assert merged[0]["a"]["confidence"] == 0.8 and not conflicts


def test_merge_batches_table_rows_by_key():
    fields = {"k": {"name": "K", "primary": True}, "v": {"name": "V"}}
    r1 = [{"k": cell("r1"), "v": cell(1, "[Page 1] 1")}]
    r2 = [{"k": cell("r1"), "v": cell(None)}, {"k": cell("r2"), "v": cell(2, "[Page 2] 2")}]
    merged, _ = pc.merge_batches([(r1, {1}), (r2, {2})], fields)
    assert sorted((e["k"]["value"], e["v"]["value"]) for e in merged) == [("r1", 1), ("r2", 2)]


def test_split_fields_order_and_row_key():
    fields = {"k": {"primary": True}, **{f"f{i}": {} for i in range(7)}}
    parts = pc.split_fields({"fields": fields}, 3)
    assert len(parts) == 3
    assert all(next(iter(p["fields"])) == "k" for p in parts)
    flat = [k for p in parts for k in p["fields"] if k != "k"]
    assert flat == [f"f{i}" for i in range(7)]


def test_merge_groups_one_entry_and_none():
    got = [[{"a": cell(1), "b": cell(2)}], None, [{"d": cell(4)}]]
    merged = pc.merge_groups(got, FIELDS)
    assert [merged[0][k]["value"] for k in "abcd"] == [1, 2, None, 4]
    assert pc.merge_groups([None, None], FIELDS) is None


def test_choose_pages_votes_and_limit():
    answers = [{"pages": {"a": [3, 1], "b": [3], "c": [99]}}, None, {"pages": {"d": [2, True]}}]
    assert b2.choose_pages(answers, seen={1, 2, 3}) == [1, 2, 3]
    many = [{"pages": {f"f{i}": [i] for i in range(1, 12)}}]
    assert len(b2.choose_pages(many, seen=set(range(1, 12)))) == 8


def test_thumbnail_long_side():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (1000, 1600), 255).save(buf, format="JPEG")
    t = pc.thumbnail(Block("image", "Page 1", "", 1, jpeg=buf.getvalue(), width=1000,
                           height=1600), 512)  # fmt: skip
    assert max(t.width, t.height) == 512 and t.jpeg


def test_dry_caller_estimates_without_a_client(tmp_path):
    rec = pc.Recorder(tmp_path, pc.ModelCatalog.load(), pc.Budget(0.01), dry=True)
    caller = pc.Caller(rec)
    caller.doc, caller.variant = "d", "v"
    fl = {"fields": {"amount": {"name": "Amount", "description": "invented"}}}
    blocks = [Block("paragraph", "Page 1", "invented text", 1)]
    assert pc.extract_call(caller, pc.HAIKU, fl, blocks, "pdf") is None
    line = rec.lines[0]
    assert line["status"] == "dry" and line["est_tokens_in"] > 0 and line["est_usd"] > 0
    assert (tmp_path / "calls.jsonl").exists()
    assert rec.totals("d", "v")["model_calls"] == 0
    assert rec.totals("d", "v")["est_tokens_in"] == line["est_tokens_in"]
    assert rec.totals("other", "v")["est_tokens_in"] == 0  # totals never mix documents


def test_realistic_image_tokens_are_bounded():
    assert pc.realistic_image_tokens(pc.HAIKU, 1236, 1600) <= 1600
    assert pc.realistic_image_tokens("google/gemini-3.8-flash", 1236, 1600) == 1120


def test_score_refuses_held_out(tmp_path):
    p = tmp_path / f"{sorted(score.HELD_OUT)[0]}__x.json"
    p.write_text(json.dumps({"status": "FAILED"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        score.score_file(p, {})
