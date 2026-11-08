"""make_zip on an invented temp git repo (no network, no real repo files)."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import make_zip as mz

FAKE_KEY = "sk-" + "or-" + "v1-" + "0123456789abcdef" * 2  # built at runtime: not a key


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    repo = tmp_path / "widgetrepo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8", newline="\n")
    _git(repo, "add", "-f", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


BASE = {
    "app/main.py": "print('widget')\n",
    ".env.example": "WIDGET_URL=\n",
    "tests/fixtures/widgets.csv": "widget,count\nsprocket,7\n",
}


def test_clean_repo_builds_rooted_zip(tmp_path, capsys):
    repo = _repo(tmp_path, BASE)
    out = tmp_path / "out" / mz.ZIP_NAME
    assert mz.main(["--repo", str(repo), "--out", str(out)]) == 0
    names = zipfile.ZipFile(out).namelist()
    assert "widgetrepo/app/main.py" in names
    assert "widgetrepo/.env.example" in names
    assert "widgetrepo/tests/fixtures/widgets.csv" in names
    assert "widgetrepo/.git/HEAD" in names
    assert all(n.startswith("widgetrepo/") for n in names)
    text = capsys.readouterr().out
    assert "checks passed" in text and "largest files" in text


def test_untracked_files_left_out(tmp_path):
    repo = _repo(tmp_path, {**BASE, ".gitignore": "secret.txt\n"})
    (repo / "secret.txt").write_text("hidden\n", encoding="utf-8")
    out = tmp_path / "z.zip"
    assert mz.main(["--repo", str(repo), "--out", str(out)]) == 0
    assert not any(n.endswith("secret.txt") for n in zipfile.ZipFile(out).namelist())


def test_dirty_tree_fails(tmp_path, capsys):
    repo = _repo(tmp_path, BASE)
    (repo / "app/main.py").write_text("changed\n", encoding="utf-8")
    out = tmp_path / "z.zip"
    assert mz.main(["--repo", str(repo), "--out", str(out)]) == 1
    assert "dirty" in capsys.readouterr().out
    assert not out.exists()


@pytest.mark.parametrize(
    "rel",
    [
        ".env",
        "config/.env.local",
        "sample/doc.txt",
        "cache/x.json",
        "_freshclone/a.txt",
        "dist/old.txt",
        ".venv/lib.py",
        "app/__pycache__/m.pyc",
        "docs/report.pdf",
        "data/sheet.xlsx",
        "notes/memo.docx",
        "data/table.csv",
    ],
)
def test_forbidden_paths_fail(tmp_path, capsys, rel):
    repo = _repo(tmp_path, {**BASE, rel: "invented\n"})
    out = tmp_path / "z.zip"
    assert mz.main(["--repo", str(repo), "--out", str(out)]) == 1
    assert rel in capsys.readouterr().out
    assert not out.exists()


def test_key_like_string_fails_without_printing_it(tmp_path, capsys):
    repo = _repo(tmp_path, {**BASE, "app/conf.py": f"x = 1\nKEY = '{FAKE_KEY}'\n"})
    out = tmp_path / "z.zip"
    assert mz.main(["--repo", str(repo), "--out", str(out)]) == 1
    text = capsys.readouterr().out
    assert "app/conf.py:2" in text
    assert FAKE_KEY not in text


def test_path_rule_edge_cases():
    assert mz.path_problem("tests/fixtures/deep/a.pdf") is None
    assert mz.path_problem("app/sample_values.py") is None  # name, not a sample/ folder


def test_size_limit_fails_and_removes_zip(tmp_path):
    repo = _repo(tmp_path, BASE)
    out = tmp_path / "z.zip"
    paths = mz.check(repo)
    with pytest.raises(mz.ZipCheckError, match="limit"):
        mz.build(repo, out, paths, max_bytes=10)
    assert not out.exists()
