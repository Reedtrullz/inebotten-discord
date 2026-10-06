from __future__ import annotations

import importlib.util
import os
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


def test_discord_setup_uses_hidden_input_without_echoing_synthetic_token(monkeypatch, capsys):
    setup_module = _load_setup_module()
    synthetic_token = "synthetic-token-that-must-never-appear"
    calls = []

    def hidden_input(prompt):
        calls.append(prompt)
        return synthetic_token

    monkeypatch.setattr(setup_module.getpass, "getpass", hidden_input)
    monkeypatch.setattr(setup_module.os, "getenv", lambda *_args: "")

    assert setup_module.setup_discord() == synthetic_token
    captured = capsys.readouterr()
    assert calls
    assert synthetic_token not in captured.out + captured.err


def test_secret_prompt_fails_closed_when_hidden_input_is_unavailable(monkeypatch, capsys):
    setup_module = _load_setup_module()

    def visible_fallback(_prompt):
        setup_module.warnings.warn("synthetic hidden-input fallback", setup_module.getpass.GetPassWarning)
        raise AssertionError("visible fallback must not be reached")

    monkeypatch.setattr(setup_module.getpass, "getpass", visible_fallback)

    try:
        setup_module.get_secret("Synthetic secret", required=True)
    except RuntimeError as exc:
        assert "interactive terminal" in str(exc)
    else:
        raise AssertionError("secret input accepted a visible fallback")

    captured = capsys.readouterr()
    assert "synthetic hidden-input fallback" not in captured.out + captured.err


def test_generate_env_updates_existing_file_without_replacing_unknown_settings(monkeypatch, tmp_path):
    setup_module = _load_setup_module()
    path = Path(os.environ["HERMES_HOME"]) / "discord" / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# owned settings\nDISCORD_USER_TOKEN=old-synthetic-token\n"
        "ALLOWED_USERS=123,456\nCONSOLE_API_KEY=untouched-synthetic-console-key\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.chdir(tmp_path)

    setup_module.generate_env(
        "new-synthetic-token",
        {"AI_PROVIDER": "lm_studio", "HERMES_API_URL": "http://127.0.0.1:3000/api/chat"},
        {"GCAL_ENABLED": "False"},
    )

    result = path.read_text(encoding="utf-8")
    assert "DISCORD_USER_TOKEN=new-synthetic-token\n" in result
    assert "ALLOWED_USERS=123,456\n" in result
    assert "CONSOLE_API_KEY=untouched-synthetic-console-key\n" in result
    assert "# owned settings\n" in result
    assert not (tmp_path / ".env").exists()
