from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

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


class _StubOutbound:
    def close(self):
        pass

    async def aclose(self):
        pass


class _FakeOwnedResources:
    def __init__(self):
        self.closers = []

    def add(self, name, closer):
        self.closers.append(closer)


class _RecordingMonitor:
    def __init__(self, client, **kwargs):
        self.client = client
        self._owned_resources = _FakeOwnedResources()
        self.seen = kwargs
        self.setup_calls = 0
        self.closed = False
        self.calendar = object()
        self.reminders = object()
        self.user_memory = object()
        self.daily_digest = object()
        self.outbound = _StubOutbound()
        self.background_tasks = []

    async def setup(self):
        self.setup_calls += 1

    async def close(self):
        for closer in self._owned_resources.closers:
            closer()
        self.closed = True

    def _track_background_task(self, coro, name):
        task = asyncio.create_task(coro, name=name)
        self.background_tasks.append(task)
        return task


def test_production_monitor_factory_composes_the_real_monitor(monkeypatch):
    config = SimpleNamespace()
    client = SimpleNamespace(config=config)
    connector = object()
    limiter = object()
    generator = object()
    seen = {}

    def fake_connector(config_arg):
        seen["connector"] = config_arg
        return connector

    def fake_limiter(config_arg):
        seen["limiter"] = config_arg
        return limiter

    class FakeMonitor(_RecordingMonitor):
        def __init__(self, client_arg, **kwargs):
            super().__init__(client_arg, **kwargs)
            seen["client"] = client_arg
            seen["connector"] = kwargs["hermes_connector"]
            seen["limiter"] = kwargs["rate_limiter"]
            seen["generator"] = kwargs["response_generator"]

    monkeypatch.setattr("ai.connector_factory.create_ai_connector", fake_connector)
    monkeypatch.setattr("core.rate_limiter.create_rate_limiter", fake_limiter)
    monkeypatch.setattr("ai.response_generator.create_response_generator", lambda: generator)
    monkeypatch.setattr("core.message_monitor.MessageMonitor", FakeMonitor)

    result = run_bot._production_monitor_factory(client)

    assert isinstance(result, FakeMonitor)
    assert seen["client"] is client
    assert seen["connector"] is connector
    assert seen["limiter"] is limiter
    assert seen["generator"] is generator


@pytest.mark.asyncio
async def test_production_monitor_setup_starts_and_closes_reminder_scheduler(monkeypatch):
    client = SimpleNamespace(config=SimpleNamespace(), get_channel=lambda channel_id: channel_id)
    created_checkers: list[_TrialChecker] = []
    health: list[bool] = []

    class _TrialChecker:
        started = False

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.setup_calls = 0
            self.storage_closed = False
            created_checkers.append(self)

        async def setup(self):
            self.setup_calls += 1

        async def start(self):
            _TrialChecker.started = True

        def close_storage(self):
            self.storage_closed = True

    class FakeMonitor(_RecordingMonitor):
        def record_scheduler_iteration(self, successful):
            health.append(successful)

    monkeypatch.setattr("core.message_monitor.MessageMonitor", FakeMonitor)
    monkeypatch.setattr("cal_system.reminder_checker.ReminderChecker", _TrialChecker)
    monkeypatch.setattr("ai.connector_factory.create_ai_connector", lambda config: object())
    monkeypatch.setattr("core.rate_limiter.create_rate_limiter", lambda config: object())
    monkeypatch.setattr("ai.response_generator.create_response_generator", lambda: object())

    monitor = cast(_RecordingMonitor, cast(object, run_bot._production_monitor_factory(client)))
    await monitor.setup()

    checker = created_checkers[0]
    assert monitor.setup_calls == 1
    assert checker.setup_calls == 1
    assert checker.kwargs["calendar_manager"] is monitor.calendar
    assert checker.kwargs["reminder_manager"] is monitor.reminders
    assert checker.kwargs["get_channel_func"](70) == 70
    assert checker.kwargs["outbound_sender"] is monitor.outbound
    assert checker.kwargs["user_memory"] is monitor.user_memory
    assert checker.kwargs["daily_digest"] is monitor.daily_digest
    checker.kwargs["health_callback"](True)
    assert health == [True]

    task = monitor.background_tasks[0]
    await asyncio.gather(task, return_exceptions=True)
    assert _TrialChecker.started is True
    assert task.done()
    await monitor.close()
    assert checker.storage_closed
    assert monitor.closed


@pytest.mark.asyncio
async def test_production_monitor_setup_failure_closes_scheduler_and_monitor(monkeypatch):
    client = SimpleNamespace(config=SimpleNamespace(), get_channel=lambda channel_id: channel_id)
    created_checkers: list[_FailingChecker] = []

    class _FailingChecker:
        def __init__(self, **kwargs):
            self.storage_closed = False
            created_checkers.append(self)

        async def setup(self):
            raise RuntimeError("checker setup failed")

        def close_storage(self):
            self.storage_closed = True

    monkeypatch.setattr("core.message_monitor.MessageMonitor", _RecordingMonitor)
    monkeypatch.setattr("cal_system.reminder_checker.ReminderChecker", _FailingChecker)
    monkeypatch.setattr("ai.connector_factory.create_ai_connector", lambda config: object())
    monkeypatch.setattr("core.rate_limiter.create_rate_limiter", lambda config: object())
    monkeypatch.setattr("ai.response_generator.create_response_generator", lambda: object())

    monitor = cast(_RecordingMonitor, cast(object, run_bot._production_monitor_factory(client)))
    with pytest.raises(RuntimeError, match="checker setup failed"):
        await monitor.setup()

    assert monitor.closed
    assert created_checkers[0].storage_closed
