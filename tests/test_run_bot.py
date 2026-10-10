from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_bot as run_bot


def _bot_home(tmp_path: Path) -> Path:
    home = tmp_path / "bot-home"
    home.mkdir(mode=0o700)
    return home


def _allowlist_config(bot_home: Path) -> SimpleNamespace:
    return SimpleNamespace(
        BOT_DATA_HOME=str(bot_home),
        INVOCATION_MODE="allowlist",
        ALLOWED_USERS=["123"],
        ALLOWED_CHANNELS=["456"],
    )


def test_run_bot_requires_absolute_matching_private_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("BOT_DATA_HOME", raising=False)

    with pytest.raises(RuntimeError, match="HERMES_HOME"):
        run_bot._require_production_environment()

    monkeypatch.setenv("HERMES_HOME", "relative/bot-home")
    monkeypatch.setenv("BOT_DATA_HOME", "relative/bot-home")
    with pytest.raises(RuntimeError, match="HERMES_HOME"):
        run_bot._require_production_environment()

    bot_home = _bot_home(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(bot_home))
    monkeypatch.delenv("BOT_DATA_HOME", raising=False)
    with pytest.raises(RuntimeError, match="BOT_DATA_HOME"):
        run_bot._require_production_environment()

    monkeypatch.setenv("HERMES_HOME", str(Path.home() / ".hermes"))
    monkeypatch.setenv("BOT_DATA_HOME", str(Path.home() / ".hermes"))
    with pytest.raises(RuntimeError, match="default Hermes home"):
        run_bot._require_production_environment()

    monkeypatch.setenv("HERMES_HOME", str(bot_home))
    monkeypatch.setenv("BOT_DATA_HOME", str(bot_home))
    run_bot._require_production_environment()


def test_run_bot_composition_fails_closed_without_bot_token(tmp_path, monkeypatch):
    bot_home = _bot_home(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(bot_home))
    monkeypatch.setenv("BOT_DATA_HOME", str(bot_home))
    monkeypatch.delenv("BOT_DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    with pytest.raises(ValueError, match="BOT_DISCORD_TOKEN"):
        from core.bot_runner import BotRunner

        BotRunner.create(
            run_bot._production_monitor_factory,
            application_config=_allowlist_config(bot_home),
            environ={},
        )


def test_production_monitor_factory_composes_the_real_monitor(monkeypatch):
    config = SimpleNamespace()
    client = SimpleNamespace(config=config)
    connector = object()
    limiter = object()
    generator = object()
    monitor = SimpleNamespace()
    seen = {}

    def fake_connector(config_arg):
        seen["connector"] = config_arg
        return connector

    def fake_limiter(config_arg):
        seen["limiter"] = config_arg
        return limiter

    def fake_monitor(client_arg, **kwargs):
        seen["client"] = client_arg
        seen["connector"] = kwargs["hermes_connector"]
        seen["limiter"] = kwargs["rate_limiter"]
        seen["generator"] = kwargs["response_generator"]
        return monitor

    monkeypatch.setattr("ai.connector_factory.create_ai_connector", fake_connector)
    monkeypatch.setattr("core.rate_limiter.create_rate_limiter", fake_limiter)
    monkeypatch.setattr("ai.response_generator.create_response_generator", lambda: generator)
    monkeypatch.setattr("core.message_monitor.MessageMonitor", fake_monitor)

    result = run_bot._production_monitor_factory(client)

    assert result is monitor
    assert seen["client"] is client
    assert seen["connector"] is connector
    assert seen["limiter"] is limiter
    assert seen["generator"] is generator
