from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

import core.message_monitor as message_monitor_module
from cal_system.reminder_manager import ReminderManager
from core.dispatch_result import ExternalCommitState
from core.message_monitor import MessageMonitor, SelfbotClient
from core.mutation_coordinator import MutationCoordinator


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)


class FixedClock:
    def now(self):
        return NOW

    def epoch(self):
        return NOW.timestamp()


class DisabledGoogleCalendarManager:
    enabled = False

    def __init__(self, *, mutation_coordinator):
        self.mutation_coordinator = mutation_coordinator


class FakeChecker:
    def __init__(
        self,
        *,
        calendar_manager,
        reminder_manager,
        get_channel_func,
        clock,
        mutation_coordinator,
    ):
        self.calendar = calendar_manager
        self.reminders = reminder_manager
        self.get_channel = get_channel_func
        self.clock = clock
        self.mutation_coordinator = mutation_coordinator
        self.setup_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.running = False
        self.started = asyncio.Event()
        self.events: list[str] = []

    async def setup(self):
        self.setup_calls += 1

    async def start(self):
        self.start_calls += 1
        self.running = True
        self.events.append("started")
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.running = False
            self.events.append("cancelled")

    def stop(self):
        self.stop_calls += 1
        self.events.append("stop")
        self.running = False


def _build_monitor(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    import ai.conversational_responses as conversational_responses
    import cal_system.google_calendar_manager as google_calendar_manager
    import memory.conversation_context as conversation_context
    import memory.localization as localization
    import memory.user_memory as user_memory

    monkeypatch.setattr(user_memory, "_user_memory", None)
    monkeypatch.setattr(conversation_context, "_context_manager", None)
    monkeypatch.setattr(conversational_responses, "_generator", None)
    monkeypatch.setattr(localization, "_localization", None)
    monkeypatch.setattr(
        google_calendar_manager,
        "GoogleCalendarManager",
        DisabledGoogleCalendarManager,
    )

    clock = FixedClock()
    coordinator = MutationCoordinator()
    reminders = ReminderManager(
        tmp_path / "hermes" / "reminders.json",
        clock=clock,
        mutation_coordinator=coordinator,
    )
    client = SimpleNamespace(
        config=SimpleNamespace(
            DISCORD_EMAIL=None,
            DISCORD_TOKEN="test-token",
            CALENDAR_OWNER_NAME="Tester",
        ),
        get_channel=lambda channel_id: ("channel", channel_id),
    )
    created: list[FakeChecker] = []

    def checker_factory(**kwargs):
        checker = FakeChecker(**kwargs)
        created.append(checker)
        return checker

    monitor = MessageMonitor(
        client=client,
        hermes_connector=None,
        rate_limiter=SimpleNamespace(get_stats=lambda: {}),
        response_generator=SimpleNamespace(),
        reminder_clock=clock,
        reminder_manager=reminders,
        reminder_checker_factory=checker_factory,
    )
    assert len(created) == 1
    return monitor, reminders, clock, coordinator, created[0]


@pytest.mark.asyncio
async def test_monitor_owns_one_identity_graph_and_setup_is_idempotent(
    tmp_path,
    monkeypatch,
):
    monitor, reminders, clock, coordinator, checker = _build_monitor(
        tmp_path,
        monkeypatch,
    )
    monitor.calendar.setup = AsyncMock()
    monitor.user_memory.setup = AsyncMock()
    monitor.calendar.ensure_gcal_configured = AsyncMock(
        return_value=SimpleNamespace(
            ok=True,
            state=ExternalCommitState.UNCHANGED,
        )
    )

    async def initial_sync(*, reference_time):
        assert reference_time is NOW
        await asyncio.Event().wait()

    monitor.calendar.sync_from_gcal_result = initial_sync

    await asyncio.gather(monitor.setup(), monitor.setup())
    await asyncio.sleep(0)
    tasks = dict(monitor._tasks_by_name)
    try:
        assert monitor.reminders is reminders
        assert monitor.reminder_clock is clock
        assert monitor.mutation_coordinator is coordinator
        assert checker is monitor.reminder_checker
        assert checker.calendar is monitor.calendar
        assert checker.reminders is reminders
        assert checker.clock is clock
        assert checker.mutation_coordinator is coordinator
        assert monitor.reminder_checker_task is tasks["reminder-checker"]
        assert set(tasks) == {
            "initial-gcal-sync",
            "console-persistence",
            "reminder-checker",
        }
        assert monitor.calendar.setup.await_count == 1
        assert monitor.user_memory.setup.await_count == 1
        assert checker.setup_calls == 1
        assert checker.start_calls == 1
    finally:
        await monitor.close()


@pytest.mark.asyncio
async def test_named_task_tracker_reuses_live_task_and_closes_discarded_coroutine(
    tmp_path,
    monkeypatch,
):
    monitor, *_ = _build_monitor(tmp_path, monkeypatch)

    async def blocked():
        await asyncio.Event().wait()

    try:
        for name in (
            "initial-gcal-sync",
            "console-persistence",
            "reminder-checker",
        ):
            first = monitor._track_background_task(blocked(), name)
            discarded = blocked()
            duplicate = monitor._track_background_task(discarded, name)
            assert duplicate is first
            assert discarded.cr_frame is None
        assert len(monitor._background_tasks) == 3
        assert set(monitor._tasks_by_name) == {
            "initial-gcal-sync",
            "console-persistence",
            "reminder-checker",
        }
    finally:
        await monitor.close()


@pytest.mark.asyncio
async def test_old_done_callback_cannot_remove_newer_same_name_task(
    tmp_path,
    monkeypatch,
):
    monitor, *_ = _build_monitor(tmp_path, monkeypatch)
    old_gate = asyncio.Event()

    async def old_work():
        await old_gate.wait()

    async def new_work():
        await asyncio.Event().wait()

    old = monitor._track_background_task(old_work(), "replaceable")
    await asyncio.sleep(0)
    old_gate.set()
    await asyncio.sleep(0)
    assert old.done()

    replacement = monitor._track_background_task(new_work(), "replaceable")
    await asyncio.sleep(0)
    try:
        assert monitor._tasks_by_name["replaceable"] is replacement
        assert replacement in monitor._background_tasks
    finally:
        await monitor.close()


@pytest.mark.asyncio
async def test_close_stops_checker_before_cancellation_and_is_idempotent(
    tmp_path,
    monkeypatch,
):
    monitor, *_, checker = _build_monitor(tmp_path, monkeypatch)
    monitor.calendar.setup = AsyncMock()
    monitor.user_memory.setup = AsyncMock()
    monitor.calendar.ensure_gcal_configured = AsyncMock(
        return_value=SimpleNamespace(
            ok=False,
            state=ExternalCommitState.UNCHANGED,
        )
    )

    await monitor.setup()
    await checker.started.wait()
    owned_tasks = tuple(monitor._background_tasks)

    await monitor.close()
    await monitor.close()

    assert checker.stop_calls == 1
    assert checker.events.index("stop") < checker.events.index("cancelled")
    assert all(task.done() for task in owned_tasks)
    assert monitor._background_tasks == set()
    assert monitor._tasks_by_name == {}
    assert monitor.reminder_checker_task is None


@pytest.mark.asyncio
async def test_close_waits_for_in_flight_setup_then_settles_every_owned_task(
    tmp_path,
    monkeypatch,
):
    monitor, *_, checker = _build_monitor(tmp_path, monkeypatch)
    monitor.calendar.setup = AsyncMock()
    monitor.user_memory.setup = AsyncMock()
    monitor.calendar.ensure_gcal_configured = AsyncMock(
        return_value=SimpleNamespace(
            ok=False,
            state=ExternalCommitState.UNCHANGED,
        )
    )
    setup_entered = asyncio.Event()
    release_setup = asyncio.Event()

    async def blocked_checker_setup():
        checker.setup_calls += 1
        setup_entered.set()
        await release_setup.wait()

    checker.setup = blocked_checker_setup
    setup_task = asyncio.create_task(monitor.setup())
    await setup_entered.wait()
    close_task = asyncio.create_task(monitor.close())
    await asyncio.sleep(0)

    assert close_task.done() is False
    release_setup.set()
    await asyncio.gather(setup_task, close_task)

    assert monitor._closed is True
    assert monitor._background_tasks == set()
    assert monitor._tasks_by_name == {}
    assert monitor.reminder_checker_task is None
    assert checker.stop_calls == 1

    await monitor.close()
    assert checker.stop_calls == 1


@pytest.mark.asyncio
async def test_setup_after_close_is_a_noop_and_cannot_restart_owned_work(
    tmp_path,
    monkeypatch,
):
    monitor, *_, checker = _build_monitor(tmp_path, monkeypatch)
    monitor.calendar.setup = AsyncMock()
    monitor.user_memory.setup = AsyncMock()
    monitor.calendar.ensure_gcal_configured = AsyncMock()

    await monitor.close()
    await monitor.setup()

    monitor.calendar.setup.assert_not_awaited()
    monitor.user_memory.setup.assert_not_awaited()
    monitor.calendar.ensure_gcal_configured.assert_not_awaited()
    assert checker.setup_calls == 0
    assert checker.start_calls == 0
    assert checker.stop_calls == 1
    assert monitor._background_tasks == set()
    assert monitor._tasks_by_name == {}
    assert monitor.reminder_checker_task is None


@pytest.mark.asyncio
async def test_selfbot_runtime_is_retained_across_reconnect(monkeypatch):
    instances = []

    class FakeMonitor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.setup_calls = 0
            self.close_calls = 0
            self.reminder_checker_task = object()
            instances.append(self)

        async def setup(self):
            self.setup_calls += 1

        async def close(self):
            self.close_calls += 1

    class FakeConsole:
        def __init__(self):
            self.monitor = None
            self.stop_calls = 0

        async def stop(self):
            self.stop_calls += 1

    monkeypatch.setattr(message_monitor_module, "MessageMonitor", FakeMonitor)
    config = SimpleNamespace(console_enabled=False)
    client = SelfbotClient(config, None, object(), None, object())
    console = FakeConsole()

    async def start_console():
        client.console_server = console

    client.start_console = start_console

    first = await client._ensure_runtime_started()
    first_started_at = client.start_time
    first_task = first.reminder_checker_task
    second = await client._ensure_runtime_started()

    assert second is first
    assert len(instances) == 1
    assert first.setup_calls == 2
    assert first.reminder_checker_task is first_task
    assert client.start_time is first_started_at
    assert console.monitor is first
    assert not hasattr(client, "reminder_checker")
    assert not hasattr(client, "reminder_checker_task")
    assert not hasattr(SelfbotClient, "_create_reminder_checker")

    await client.close()
    assert first.close_calls == 1


@pytest.mark.asyncio
async def test_dashboard_uses_active_reminders_from_owned_manager(monkeypatch):
    active_reminders = [{"id": "same-manager", "text": "Ring legen"}]
    captured = {}

    class FakeWeatherAPI:
        async def get_weather(self, **kwargs):
            return None

        async def close(self):
            return None

    import features.weather_api as weather_api

    monkeypatch.setattr(weather_api, "METWeatherAPI", FakeWeatherAPI)
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.user_memory = SimpleNamespace(snapshot_user=lambda _user_id: None)
    monitor.reminder_clock = FixedClock()
    monitor.calendar = SimpleNamespace(
        get_upcoming=lambda guild_id, days, reference_time: []
    )
    monitor.reminders = SimpleNamespace(
        get_active_reminders=lambda guild_id: active_reminders
    )

    def generate_dashboard(**kwargs):
        captured.update(kwargs)
        return "dashboard"

    monitor.conv_gen = SimpleNamespace(generate_dashboard=generate_dashboard)

    result = await monitor._generate_dashboard(42, reference_time=NOW)

    assert result == "dashboard"
    assert captured["reminders"] is active_reminders
