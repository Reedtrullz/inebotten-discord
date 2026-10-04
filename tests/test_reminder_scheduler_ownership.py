"""The scheduler and command handlers share the initialized reminder owner."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from cal_system import reminder_checker
from cal_system.reminder_manager import ReminderManager
from core.message_monitor import SelfbotClient


def client_for(monitor):
    return SimpleNamespace(monitor=monitor, get_channel=lambda _: None)


def test_checker_uses_monitor_manager(tmp_path, monkeypatch):
    owner = ReminderManager(tmp_path/'reminders.json')
    monitor = SimpleNamespace(calendar=SimpleNamespace(items={}), reminders=owner)
    # A second disk load is an ownership violation, even if the data matches.
    monkeypatch.setattr(ReminderManager, '_load_reminders', lambda _: pytest.fail('duplicate reminder load'))
    checker = SelfbotClient._create_reminder_checker(client_for(monitor), monitor)
    assert checker.reminders is owner
    assert checker.calendar is monitor.calendar


def test_checker_requires_initialized_monitor():
    with pytest.raises(RuntimeError, match='initialized monitor'):
        SelfbotClient._create_reminder_checker(client_for(None))


@pytest.mark.asyncio
async def test_next_scan_sees_create_edit_complete_and_delete(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2027, 1, 1, 8, 45, tzinfo=ZoneInfo('Europe/Oslo'))
    monkeypatch.setattr(reminder_checker, 'datetime', Clock)
    owner = ReminderManager(tmp_path/'reminders.json')
    monitor = SimpleNamespace(calendar=SimpleNamespace(items={}), reminders=owner)
    checker = SelfbotClient._create_reminder_checker(client_for(monitor))
    observed = []
    async def record(reminder, *_):
        observed.append((reminder['id'], reminder['text']))
    checker._send_reminder_remind = record
    identity = owner.add_reminder('guild', 'user', 'Tester', 'Ny', due_date='01.01.2027')
    await checker.check_upcoming_30min()
    assert observed == [(identity, 'Ny')]
    observed.clear()
    owner.edit_reminder('guild', 1, title='Endret')
    await checker.check_upcoming_30min()
    assert observed == [(identity, 'Endret')]
    observed.clear()
    owner.complete_reminder('guild', reminder_id=identity)
    await checker.check_upcoming_30min()
    assert observed == []
    deleted = owner.add_reminder('guild', 'user', 'Tester', 'Slettet', due_date='01.01.2027')
    owner.delete_reminder_by_id('guild', 1)
    await checker.check_upcoming_30min()
    assert observed == []
    assert deleted not in [r['id'] for r in checker.reminders.reminders['guild']]


@pytest.mark.asyncio
async def test_reconnect_does_not_construct_another_owner_or_checker(monkeypatch):
    from core import message_monitor
    constructions = []
    tasks = []
    class Monitor:
        def __init__(self, **_):
            constructions.append(self)
        async def setup(self):
            pass
        def _track_background_task(self, coroutine, name):
            tasks.append(name)
            coroutine.close()
            return SimpleNamespace(done=lambda: True)
    checker = SimpleNamespace(setup=AsyncMock(), start=AsyncMock())
    class Client:
        monitor = None
        console_server = None
        user = SimpleNamespace(id=1)
        guilds = []
        config = SimpleNamespace(MAX_MSGS_PER_SECOND=5, DAILY_QUOTA=10000)
        hermes = None
        rate_limiter = object()
        response_gen = object()
        _get_commit_hash = lambda self: 'test'
        _ensure_current_commit_hash = lambda self, value: value
        change_presence = AsyncMock()
        start_console = AsyncMock()
        _create_reminder_checker = lambda self, monitor: checker
    monkeypatch.setattr(message_monitor, 'MessageMonitor', Monitor)
    client = Client()
    await SelfbotClient.on_ready(client)
    await SelfbotClient.on_ready(client)
    assert len(constructions) == 1
    assert tasks == ['reminder-checker']
    assert checker.setup.await_count == 1
    assert client.reminder_checker is checker
