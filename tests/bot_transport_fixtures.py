"""Synthetic real-domain fixtures for the clean optional bot profile."""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio


class SyntheticOutbound:
    async def reply(self, message, text, *, mention_author=False, attachments=()):
        message.responses.append(text)
        return SimpleNamespace(status="delivered", reason_code="remote_message", message=message)


class SyntheticMessage:
    def __init__(self, content="", *, user_id="42", channel_id="70", guild_id="60"):
        self.id = "8001"
        self.content = content
        self.author = SimpleNamespace(id=user_id, name="fixture-user")
        self.channel = SimpleNamespace(id=channel_id)
        self.guild = SimpleNamespace(id=guild_id)
        self.responses = []


@pytest_asyncio.fixture
async def bot_domain_handlers(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    from cal_system.natural_language_parser import NaturalLanguageParser
    from cal_system.reminder_manager import ReminderManager
    from core.access_policy import AccessPolicy
    from core.request_context import RequestContext
    from features.calendar_handler import CalendarHandler
    from features.poll_manager import PollManager
    from features.polls_handler import PollsHandler
    from features.reminder_handler import ReminderHandler
    from memory.localization import Localization

    policy = AccessPolicy()
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json", access_policy=policy)
    reminders = ReminderManager(storage_path=tmp_path / "reminders.json", access_policy=policy)
    polls = PollManager(storage_path=tmp_path / "polls.json")
    monitor = SimpleNamespace(
        calendar=calendar,
        reminders=reminders,
        poll=polls,
        nlp_parser=NaturalLanguageParser(),
        rate_limiter=SimpleNamespace(),
        loc=Localization(),
        client=SimpleNamespace(),
        outbound=SyntheticOutbound(),
        response_count=0,
    )
    handlers = SimpleNamespace(
        calendar=CalendarHandler(monitor),
        reminders=ReminderHandler(monitor),
        polls=PollsHandler(monitor),
        monitor=monitor,
        actor=RequestContext("fixture-request", "42", "70", "60", "no", "guild"),
    )
    await calendar.setup()
    try:
        yield handlers
    finally:
        await calendar._outbox.slot.close()
        await reminders._outbox.slot.close()
        await calendar._storage.aclose()
        await reminders._storage.aclose()
        polls.close_storage()
