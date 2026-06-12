from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import write_version


def _clear_commit_env(monkeypatch):
    monkeypatch.delenv("SOURCE_COMMIT", raising=False)
    monkeypatch.delenv("COMMIT_SHA", raising=False)


def test_resolve_commit_prefers_source_commit_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_COMMIT", "abc1234")
    monkeypatch.setenv("COMMIT_SHA", "def5678")

    commit, source = write_version.resolve_commit(tmp_path / "commit_hash.txt")

    assert commit == "abc1234"
    assert source == "SOURCE_COMMIT"


def test_resolve_commit_uses_git_when_env_missing(monkeypatch, tmp_path):
    _clear_commit_env(monkeypatch)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="d6f65a1\n", stderr="")

    monkeypatch.setattr(write_version.subprocess, "run", fake_run)

    commit, source = write_version.resolve_commit(tmp_path / "commit_hash.txt")

    assert commit == "d6f65a1"
    assert source == "git"


def test_resolve_commit_preserves_existing_file_when_git_unavailable(monkeypatch, tmp_path):
    _clear_commit_env(monkeypatch)
    commit_file = tmp_path / "commit_hash.txt"
    commit_file.write_text("1e3e532\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(write_version.subprocess, "run", fake_run)

    commit, source = write_version.resolve_commit(commit_file)

    assert commit == "1e3e532"
    assert source == str(commit_file)


def test_main_writes_resolved_commit(monkeypatch, tmp_path, capsys):
    _clear_commit_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COMMIT_SHA", "feed123")

    assert write_version.main() == 0

    assert Path("commit_hash.txt").read_text(encoding="utf-8") == "feed123"
    assert "feed123" in capsys.readouterr().out
