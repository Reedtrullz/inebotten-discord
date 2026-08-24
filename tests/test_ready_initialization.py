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
