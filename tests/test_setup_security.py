from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("inebotten_setup_under_test", ROOT / "setup.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clear_screen_does_not_call_os_system(monkeypatch, capsys):
    setup_module = _load_setup_module()

    def forbidden_system(command):
        raise AssertionError(f"os.system must not be called: {command}")

    monkeypatch.setattr(setup_module.os, "system", forbidden_system)

    setup_module.clear_screen()

    captured = capsys.readouterr()
    assert captured.out
