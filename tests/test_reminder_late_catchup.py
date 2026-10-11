#!/usr/bin/env python3
import asyncio
import json
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


def _checker(tmp_path, sent, reminders, *, message=None):
    async def send(text, **kwargs):
        sent.append(text)
        return message if message is not None else SimpleNamespace(id="m1")

    checker = ReminderChecker(
        storage_path=tmp_path / "log.json",
        outbound_sender=OutboundSender(lambda _: SimpleNamespace(send=send), RateLimiter()),
        clock=Clock(wall=lambda: FIXED_NOW, monotonic=lambda: 1),
    )
    checker.reminders = SimpleNamespace(reminders=reminders, access_policy=None)
    return checker


@pytest.mark.parametrize('kind', ['reminder', 'calendar'])
@pytest.mark.asyncio
async def test_now_notification_waits_until_due_then_sends_once(tmp_path, kind):
    due = FIXED_NOW.astimezone(ZoneInfo('Europe/Oslo'))
    item = {'id': 'deadline', 'text': 'Meeting', 'title': 'Meeting',
            'due_date': due.strftime('%d.%m.%Y %H:%M'), 'date': due.strftime('%d.%m.%Y'),
            'time': due.strftime('%H:%M'), 'channel_id': '123', 'user_id': '7'}
    sent = []
    checker = _checker(tmp_path, sent, {'123': [item]} if kind == 'reminder' else {})
    if kind == 'calendar':
        checker.calendar = SimpleNamespace(items={'shared': [item]}, access_policy=None)
    current = [FIXED_NOW - timedelta(seconds=40)]
    checker.clock = Clock(wall=lambda: current[0], monotonic=lambda: 1)
    await checker.setup()
    await checker.check_event_now()
    assert sent == []
    current[0] = FIXED_NOW
    await checker.check_event_now()
    await checker.check_event_now()
    assert len(sent) == 1 and 'nå:' in sent[0].casefold()


@pytest.mark.asyncio
async def test_due_delivery_receipt_does_not_copy_live_gateway_message(tmp_path):
    message = SimpleNamespace(id='m1', gateway_future=asyncio.get_running_loop().create_future())
    reminder = {'id': 'live-message', 'text': 'Meeting', 'due_date': _oslo_due(0),
                'channel_id': '123', 'user_id': '7'}
    sent = []
    checker = _checker(tmp_path, sent, {'123': [reminder]}, message=message)
    await checker.setup()
    await checker.check_event_now()
    await checker.check_event_now()
    assert len(sent) == 1 and checker.stats['now_sent'] == 1
    saved = json.loads((tmp_path / 'log.json').read_text())['document']
    assert saved['deliveries']['live-message:now']['message_id'] == 'm1'
    assert saved['deliveries']['live-message:now']['status'] == 'delivered'
    assert 'live-message:now' in saved['reminders_sent']
    checker.close_storage()
    restarted = _checker(tmp_path, sent, {'123': [reminder]}, message=message)
    await restarted.setup()
    await restarted.check_event_now()
    assert len(sent) == 1
    restarted.close_storage()


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


@pytest.mark.asyncio
async def test_reminder_created_inside_warning_window_skips_30min_ping(tmp_path):
    reminder = {
        "id": "rem_fresh", "text": "snart",
        "due_date": _oslo_due(-25), "channel_id": "123",
        "user_id": "7", "scope_id": "shared",
        "created_at": FIXED_NOW.isoformat(),
    }
    sent = []
    checker = _checker(tmp_path, sent, {"123": [reminder]})
    await checker.setup()

    await checker.check_upcoming_30min()

    assert sent == []


@pytest.mark.asyncio
async def test_reminder_created_before_warning_window_gets_30min_ping(tmp_path):
    reminder = {
        "id": "rem_aged", "text": "snart",
        "due_date": _oslo_due(-25), "channel_id": "123",
        "user_id": "7", "scope_id": "shared",
        "created_at": (FIXED_NOW - timedelta(minutes=40)).isoformat(),
    }
    sent = []
    checker = _checker(tmp_path, sent, {"123": [reminder]})
    await checker.setup()

    await checker.check_upcoming_30min()

    assert len(sent) == 1
    assert "25 minutter" in sent[0]


@pytest.mark.parametrize('kind', ['reminder', 'calendar'])
@pytest.mark.asyncio
async def test_created_40_minutes_before_due_warns_at_30_minutes(tmp_path, kind):
    due = (FIXED_NOW + timedelta(minutes=30)).astimezone(ZoneInfo('Europe/Oslo'))
    item = {'id': 'advance', 'text': 'Meeting', 'title': 'Meeting',
            'due_date': due.strftime('%d.%m.%Y %H:%M'), 'date': due.strftime('%d.%m.%Y'),
            'time': due.strftime('%H:%M'), 'channel_id': '123', 'user_id': '7',
            'created_at': (FIXED_NOW - timedelta(minutes=10)).isoformat()}
    sent = []
    checker = _checker(tmp_path, sent, {'123': [item]} if kind == 'reminder' else {})
    if kind == 'calendar':
        checker.calendar = SimpleNamespace(items={'shared': [item]}, access_policy=None)
    await checker.check_upcoming_30min()
    await checker.check_upcoming_30min()
    assert len(sent) == 1 and '30 minutter' in sent[0]


@pytest.mark.parametrize('created', [
    '2026-10-11T00:05:00', '2026-10-10T22:05:00+00:00',
    '2026-10-11T00:05:00+02:00',
])
@pytest.mark.asyncio
async def test_warning_uses_due_boundary_and_actual_remaining_minutes(tmp_path, created):
    reminder = {'id': 'late-scan', 'text': 'Meeting', 'due_date': _oslo_due(-9),
                'created_at': created, 'channel_id': '123', 'user_id': '7'}
    sent = []
    checker = _checker(tmp_path, sent, {'123': [reminder]})
    await checker.check_upcoming_30min()
    assert len(sent) == 1 and '9 minutter' in sent[0]


@pytest.mark.asyncio
async def test_created_on_warning_boundary_skips_lead_but_delivers_due_once(tmp_path):
    reminder = {'id': 'boundary', 'text': 'Meeting', 'due_date': _oslo_due(0),
                'created_at': (FIXED_NOW - timedelta(minutes=30)).isoformat(),
                'channel_id': '123', 'user_id': '7'}
    sent = []
    checker = _checker(tmp_path, sent, {'123': [reminder]})
    await checker.check_upcoming_30min()
    await checker.check_event_now()
    await checker.check_event_now()
    assert len(sent) == 1 and 'Nå:' in sent[0]
