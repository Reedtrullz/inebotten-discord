from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest


def _schema():
    from core.config_schema import update_settings, validate_settings

    return update_settings, validate_settings


def test_unknown_keys_survive_setup(tmp_path: Path):
    path = tmp_path / ".env"
    original = (
        "# keep this comment\n"
        "DISCORD_USER_TOKEN=old-token-value\n"
        "AI_PROVIDER=lm_studio # user-selected provider\n"
        "ALLOWED_USERS=123,456\n"
        "CONSOLE_CF_ACCESS_ALLOWED_EMAILS=owner@example.test\n"
        "GOOGLE_CALENDAR_ID=private-calendar\n"
    )
    path.write_text(original, encoding="utf-8")
    path.chmod(0o600)

    update_settings, _ = _schema()
    update_settings(path, {"AI_PROVIDER": "openrouter", "DISCORD_USER_TOKEN": "new-token-value"})

    updated = path.read_text(encoding="utf-8")
    assert "# keep this comment\n" in updated
    assert "DISCORD_USER_TOKEN=new-token-value\n" in updated
    assert "AI_PROVIDER=openrouter # user-selected provider\n" in updated
    assert "ALLOWED_USERS=123,456\n" in updated
    assert "CONSOLE_CF_ACCESS_ALLOWED_EMAILS=owner@example.test\n" in updated
    assert "GOOGLE_CALENDAR_ID=private-calendar\n" in updated
    assert "DISCORD_USER_TOKEN=old-token-value\n" not in updated


def test_credentials_are_never_echoed(capsys):
    _, validate_settings = _schema()
    errors = validate_settings({
        "DISCORD_EMAIL": "synthetic@example.test",
        "DISCORD_PASSWORD": "synthetic-password-value",
        "OPENROUTER_API_KEY": "synthetic-api-key-value",
    })

    captured = capsys.readouterr()
    assert errors
    assert "synthetic@example.test" not in repr(errors) + captured.out + captured.err
    assert "synthetic-password-value" not in repr(errors) + captured.out + captured.err
    assert "synthetic-api-key-value" not in repr(errors) + captured.out + captured.err
    assert all(set(error) == {"field", "reason"} for error in errors)


def test_file_is_private_before_content(tmp_path: Path, monkeypatch):
    path = tmp_path / "new config" / ".env"
    original_fdopen = os.fdopen
    observed_modes: list[int] = []

    def checked_fdopen(fd, *args, **kwargs):
        observed_modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return original_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", checked_fdopen)
    update_settings, _ = _schema()
    update_settings(path, {"DISCORD_USER_TOKEN": "synthetic-token-value"})

    assert observed_modes and all(mode == 0o600 for mode in observed_modes)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_email_password_rejected_at_setup():
    _, validate_settings = _schema()
    errors = validate_settings({
        "DISCORD_EMAIL": "synthetic@example.test",
        "DISCORD_PASSWORD": "synthetic-password-value",
    })

    assert {error["field"] for error in errors} == {"DISCORD_EMAIL", "DISCORD_PASSWORD"}


def test_invalid_provider_is_rejected_without_returning_value():
    _, validate_settings = _schema()
    errors = validate_settings({"AI_PROVIDER": "synthetic-unsupported-provider"})

    assert errors == [{"field": "AI_PROVIDER", "reason": "unsupported value"}]
    assert "synthetic-unsupported-provider" not in repr(errors)


def test_explicit_hermes_has_no_project_fallback(tmp_path: Path, monkeypatch):
    from core.config import Config

    project = tmp_path / "project with spaces"
    hermes = tmp_path / "hermes home"
    project.mkdir()
    (project / ".env").write_text("DISCORD_USER_TOKEN=project-token\n", encoding="utf-8")
    (hermes / "discord").mkdir(parents=True)
    hermes_env = hermes / "discord" / ".env"
    hermes_env.write_text("DISCORD_USER_TOKEN=hermes-token\n", encoding="utf-8")
    hermes_env.chmod(0o600)
    monkeypatch.chdir(project)
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)

    config = Config.__new__(Config)
    config.load_env()

    assert config.env_file_loaded == str(hermes_env)
    assert os.environ["DISCORD_USER_TOKEN"] == "hermes-token"


def test_blank_explicit_hermes_never_uses_project_config(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    project_env = project / ".env"
    project_env.write_text("DISCORD_USER_TOKEN=project-token\n", encoding="utf-8")
    project_env.chmod(0o600)
    monkeypatch.chdir(project)
    monkeypatch.setenv("HERMES_HOME", "")
    existing_token = os.environ.get("DISCORD_USER_TOKEN")

    with pytest.raises(ValueError, match="HERMES_HOME"):
        from core.config_schema import settings_path
        settings_path()

    from core.config import Config
    config = Config.__new__(Config)
    config.load_env()
    assert config.env_file_loaded is None
    assert os.environ.get("DISCORD_USER_TOKEN") == existing_token


def test_config_rejects_email_password_without_echoing_values(capsys):
    from core.config import Config

    config = Config.__new__(Config)
    config.DISCORD_EMAIL = "synthetic@example.test"
    config.DISCORD_PASSWORD = "synthetic-password-value"

    with pytest.raises(ValueError) as error:
        config.validate()

    captured = capsys.readouterr()
    assert "synthetic@example.test" not in str(error.value) + captured.out + captured.err
    assert "synthetic-password-value" not in str(error.value) + captured.out + captured.err


def test_config_without_auth_reports_missing_token_without_name_error(capsys):
    from core.config import Config

    config = Config.__new__(Config)
    config.DISCORD_TOKEN = None
    config.DISCORD_EMAIL = None
    config.DISCORD_PASSWORD = None
    config.AI_PROVIDER = "lm_studio"
    config.HERMES_API_URL = "http://127.0.0.1:3000/api/chat"
    config.env_file_loaded = None
    config.CONSOLE_API_KEY_AUTO_GENERATED = False
    config.CONSOLE_AUTH_MODE = "api_key"

    config.validate()

    assert "DISCORD_USER_TOKEN" in capsys.readouterr().out


def test_auth_handler_rejects_non_token_auth_without_echoing_values(capsys):
    from core.auth_handler import AuthHandler

    class PasswordConfig:
        def get_auth_creds(self):
            return {
                "type": "password",
                "email": "synthetic@example.test",
                "password": "synthetic-password-value",
            }

    with pytest.raises(ValueError, match="Unsupported Discord authentication"):
        AuthHandler(PasswordConfig())

    captured = capsys.readouterr()
    assert "synthetic@example.test" not in captured.out + captured.err
    assert "synthetic-password-value" not in captured.out + captured.err


def test_failed_update_leaves_existing_settings_intact(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("DISCORD_USER_TOKEN=preserved-synthetic-token\n", encoding="utf-8")
    path.chmod(0o600)

    def fail_replace(*_args):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    update_settings, _ = _schema()
    with pytest.raises(OSError, match="synthetic replace failure"):
        update_settings(path, {"AI_PROVIDER": "openrouter"})

    assert path.read_text(encoding="utf-8") == "DISCORD_USER_TOKEN=preserved-synthetic-token\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_config_keeps_literal_credentials_without_env_interpolation(tmp_path, monkeypatch):
    from core.config_schema import update_settings
    from core.config import Config
    hermes = tmp_path/'hermes'
    path = hermes/'discord/.env'
    token = 'synthetic-${EXPANSION_PROBE}-token'
    update_settings(path, {'DISCORD_USER_TOKEN': token})
    monkeypatch.setenv('EXPANSION_PROBE', 'must-not-replace-token')
    monkeypatch.setenv('HERMES_HOME', str(hermes))
    monkeypatch.delenv('DISCORD_USER_TOKEN', raising=False)
    config = Config.__new__(Config)
    config.load_env()
    assert os.environ['DISCORD_USER_TOKEN'] == token


@pytest.mark.parametrize('settings, field', [
    ({'HERMES_API_URL': 'not-a-url'}, 'HERMES_API_URL'),
    ({'HERMES_API_URL': 'https://synthetic-user:synthetic-password@example.test/chat'}, 'HERMES_API_URL'),
    ({'OPENROUTER_MODEL': ''}, 'OPENROUTER_MODEL'),
])
def test_provider_fields_reject_invalid_values_without_echo(settings, field):
    _, validate_settings = _schema()
    errors = validate_settings(settings)
    assert any(error['field'] == field for error in errors)
    assert all(value not in repr(errors) for value in settings.values() if value)


def test_missing_openrouter_key_never_switches_provider(capsys):
    from core.config import Config
    config = Config.__new__(Config)
    config.DISCORD_TOKEN = 'synthetic-token'
    config.DISCORD_EMAIL = config.DISCORD_PASSWORD = None
    config.AI_PROVIDER = 'openrouter'
    config.OPENROUTER_API_KEY = None
    config.OPENROUTER_MODEL = 'synthetic/model'
    config.env_file_loaded = None
    config.CONSOLE_API_KEY_AUTO_GENERATED = False
    config.CONSOLE_AUTH_MODE = 'api_key'
    config.validate()
    assert config.AI_PROVIDER == 'openrouter'
    assert 'OPENROUTER_API_KEY' in capsys.readouterr().out


def test_settings_update_preserves_untouched_crlf_bytes(tmp_path):
    from core.config_schema import update_settings
    path = tmp_path/'.env'
    original = b'# keep CRLF\r\nUNKNOWN_SETTING=literal-value\r\nAI_PROVIDER=lm_studio\r\n'
    path.write_bytes(original)
    update_settings(path, {'AI_PROVIDER': 'openrouter'})
    assert path.read_bytes().startswith(b'# keep CRLF\r\nUNKNOWN_SETTING=literal-value\r\n')
