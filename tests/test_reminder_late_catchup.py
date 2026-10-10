#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from types import SimpleNamespace

from cal_system.event_schema import Clock
from cal_system.reminder_checker import ReminderChecker
from core.outbound_sender import OutboundSender
from core.rate_limiter import RateLimiter


FIXED_NOW = datetime(2026, 10, 10, 22, 30, tzinfo=timezone.utc)


def _oslo_due(minutes_ago):
    due = (FIXED_NOW - timedelta(minutes=minutes_ago)).astimezone(ZoneInfo("Europe/Oslo"))
    return due.strftime("%d.%m.%Y %H:%M")


def _checker(tmp_path, sent, reminders):
    async def send(text, **kwargs):
        sent.append(text)
        return SimpleNamespace(id="m1")

    checker = ReminderChecker(
        storage_path=tmp_path / "log.json",
        outbound_sender=OutboundSender(lambda _: SimpleNamespace(send=send), RateLimiter()),
        clock=Clock(wall=lambda: FIXED_NOW, monotonic=lambda: 1),
    )
    checker.reminders = SimpleNamespace(reminders=reminders, access_policy=None)
    return checker


@pytest.mark.asyncio
async def test_late_due_reminder_fires_within_catchup_window(tmp_path):
    reminder = {
        "id": "rem_late", "text": "teste",
        "due_date": _oslo_due(12), "channel_id": "123",
        "user_id": "7", "scope_id": "shared",
    }
    sent = []
    checker = _checker(tmp_path, sent, {"123": [reminder]})
    await checker.setup()

    await checker.check_event_now()

    assert len(sent) == 1
    assert "teste" in sent[0]


@pytest.mark.asyncio
async def test_late_due_reminder_does_not_fire_twice(tmp_path):
    reminder = {
        "id": "rem_late", "text": "teste",
        "due_date": _oslo_due(12), "channel_id": "123",
        "user_id": "7", "scope_id": "shared",
    }
    sent = []
    checker = _checker(tmp_path, sent, {"123": [reminder]})
    await checker.setup()

    await checker.check_event_now()
    await checker.check_event_now()

    assert len(sent) == 1


@pytest.mark.asyncio
async def test_older_than_catchup_window_stays_silent(tmp_path):
    reminder = {
        "id": "rem_old", "text": "gammel",
        "due_date": _oslo_due(90), "channel_id": "123",
        "user_id": "7", "scope_id": "shared",
    }
    sent = []
    checker = _checker(tmp_path, sent, {"123": [reminder]})
    await checker.setup()

    await checker.check_event_now()

    assert sent == []
