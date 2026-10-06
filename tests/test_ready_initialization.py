"""Offline READY initialization retry regression tests."""

from types import SimpleNamespace

import pytest

from core import message_monitor


@pytest.mark.asyncio
async def test_failed_monitor_setup_is_not_published(monkeypatch):
    class Candidate:
        def __init__(self, **_kwargs):
            pass

        async def setup(self):
            raise RuntimeError("setup failed")

        async def close(self):
            return None

    class Client:
        monitor = None
        console_server = None
        user = SimpleNamespace(id=1)
        guilds = []
        config = SimpleNamespace(MAX_MSGS_PER_SECOND=5, DAILY_QUOTA=10_000)
        hermes = None
        rate_limiter = object()
        response_gen = object()

        def _get_commit_hash(self):
            return "test"

        def _ensure_current_commit_hash(self, commit):
            return commit

        async def change_presence(self, **_kwargs):
            return None

    monkeypatch.setattr(message_monitor, "MessageMonitor", Candidate)
    client = Client()
    with pytest.raises(RuntimeError, match="setup failed"):
        await message_monitor.SelfbotClient.on_ready(client)
    assert client.monitor is None


@pytest.mark.asyncio
async def test_failed_reminder_setup_closes_unpublished_monitor(monkeypatch):
    closed = False

    class Candidate:
        def __init__(self, **_kwargs):
            pass

        async def setup(self):
            return None

        async def close(self):
            nonlocal closed
            closed = True

    class Reminder:
        async def setup(self):
            raise RuntimeError("reminder setup failed")

    class Client:
        monitor = None
        console_server = None
        user = SimpleNamespace(id=1)
        guilds = []
        config = SimpleNamespace(MAX_MSGS_PER_SECOND=5, DAILY_QUOTA=10_000)
        hermes = None
        rate_limiter = object()
        response_gen = object()

        def _get_commit_hash(self):
            return "test"

        def _ensure_current_commit_hash(self, commit):
            return commit

        async def change_presence(self, **_kwargs):
            return None

        def _create_reminder_checker(self, _monitor):
            return Reminder()

    monkeypatch.setattr(message_monitor, "MessageMonitor", Candidate)
    client = Client()
    with pytest.raises(RuntimeError, match="reminder setup failed"):
        await message_monitor.SelfbotClient.on_ready(client)
    assert client.monitor is None
    assert closed


@pytest.mark.asyncio
async def test_cancelled_monitor_setup_closes_unpublished_candidate(monkeypatch):
    import asyncio
    entered = asyncio.Event()
    calls = []
    class Candidate:
        def __init__(self, **kwargs):
            pass
        async def setup(self):
            entered.set()
            await asyncio.Future()
        async def close(self):
            calls.append('closed')
    class Client:
        monitor = console_server = hermes = None
        rate_limiter = response_gen = object()
        user = SimpleNamespace(id=1)
        guilds = []
        config = SimpleNamespace(MAX_MSGS_PER_SECOND=5, DAILY_QUOTA=10000)
        def _get_commit_hash(self):
            return 'synthetic'
        def _ensure_current_commit_hash(self, value):
            return value
        async def change_presence(self, **kwargs):
            pass
    monkeypatch.setattr(message_monitor, 'MessageMonitor', Candidate)
    client = Client()
    task = asyncio.create_task(message_monitor.SelfbotClient.on_ready(client))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.monitor is None
    assert calls == ['closed']
