"""Ordinary reminder prose must not authorize a store mutation."""
import pytest

from cal_system.reminder_manager import parse_reminder_command
from core.intent_router import BotIntent, IntentRouter
from tests.test_intent_router import DummyMonitor


@pytest.mark.parametrize('text', [
    'Forklar kort forskjellen på et møte og en påminnelse',
    'Explain the difference between a meeting and a reminder',
    'Hva betyr påminnelse?',
    'Jeg fikk en påminnelse om en avtale',
    'Forklar hva påminnelser er',
    'Hva betyr kommandoen "reminder buy milk"?',
])
def test_prose_about_reminders_stays_chat(text):
    assert parse_reminder_command(text) is None
    assert IntentRouter(DummyMonitor()).route(text, guild_id=123).intent == BotIntent.AI_CHAT


@pytest.mark.parametrize('command, title', [
    ('påminnelse Ring lege 20.06', 'Ring lege'),
    ('reminder Buy milk', 'Buy milk'),
    ('todo Ring lege', 'Ring lege'),
    ('Kan du legge til en påminnelse Ring lege', 'Ring lege'),
    ('Lag en påminnelse om å ringe lege', 'ringe lege'),
    ('påminnelse Les om påminnelser og todo-lister', 'Les om påminnelser og todo-lister'),
])
def test_explicit_creation_keeps_title_words(command, title):
    parsed = parse_reminder_command(command)
    assert parsed['action'] == 'add'
    assert parsed['text'] == title
    assert IntentRouter(DummyMonitor()).route(command, guild_id=123).intent == BotIntent.REMINDER_CREATE


@pytest.mark.asyncio
async def test_human_explanation_reaches_chat_without_touching_reminders(tmp_path):
    from collections import defaultdict
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cal_system.reminder_manager import ReminderManager
    from core.message_monitor import MessageMonitor
    from tests.test_ai_outcomes import FakeMessage, FakeRateLimiter

    reminders = ReminderManager(storage_path=tmp_path/'reminders.json')
    try:
        reminders.add_reminder('2', '7', 'Tester', 'Existing reminder')
        before = reminders.storage_path.read_bytes()
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.client = SimpleNamespace(user=SimpleNamespace(id=42), config=SimpleNamespace(
            INVOCATION_MODE='legacy', ALLOWED_USERS=[], ALLOWED_CHANNELS=[]))
        monitor.bot_name = 'inebotten'
        monitor.bot_mention = '@inebotten'
        monitor.processed_messages = []
        monitor.mention_count = monitor.error_count = 0
        monitor.intent_stats = defaultdict(lambda: {'count':0, 'low_confidence':0, 'errors':0})
        monitor.rate_limiter = FakeRateLimiter()
        monitor.loc = SimpleNamespace(detect_language=lambda _: 'no')
        monitor.intent_router = IntentRouter(DummyMonitor())
        monitor._send_ai_response = AsyncMock()
        monitor.handlers = {'reminders': SimpleNamespace(handle_reminder_create=AsyncMock())}
        await monitor.handle_message(FakeMessage(
            '@inebotten Forklar kort forskjellen på et møte og en påminnelse'))
        monitor._send_ai_response.assert_awaited_once()
        monitor.handlers['reminders'].handle_reminder_create.assert_not_awaited()
        assert reminders.storage_path.read_bytes() == before
    finally:
        reminders._storage.close()
