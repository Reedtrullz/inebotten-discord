from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cal_system.event_schema import Clock
from cal_system.reminder_manager import ReminderManager, parse_reminder_command
from cal_system.recurrence import Series, occurrence_at
from features.reminder_handler import ReminderHandler


@pytest.mark.parametrize('phrase,rule', [('hver uke', 'weekly'), ('annenhver uke', 'biweekly'),
    ('hver dag', 'daily'), ('hver måned', 'monthly'), ('hvert år', 'yearly')])
def test_creation_extracts_explicit_recurrence_without_polluting_title(phrase, rule):
    parsed = parse_reminder_command(f'påminnelse Leveringstest 12.10.2027 kl 05:01 {phrase}')
    assert parsed['recurrence'] == rule
    assert parsed['text'] == 'Leveringstest'
    assert parsed['due_date'] == '12.10.2027 05:01'


def test_timed_weekly_completion_keeps_local_time_across_dst_and_restart(tmp_path):
    path = tmp_path / 'reminders.json'
    manager = ReminderManager(path)
    try:
        identity = manager.add_reminder('10', '7', 'Test', 'Weekly', '18.10.2026 05:01', recurrence='weekly')
        assert manager.complete_reminder('10', reminder_id=identity)[2] == '25.10.2026 05:01'
        record = manager.get_active_reminders('10')[0]
        assert record['due_date'] == '25.10.2026 05:01'
        series = Series.from_document(record['series'])
        next_occurrence = occurrence_at(series, 1)
        assert next_occurrence is not None
        assert next_occurrence.original_start.isoformat() == '2026-10-25T05:01:00+01:00'
        assert len(record['occurrences']) == 1
    finally:
        manager._storage.close()
    restored = ReminderManager(path)
    try:
        assert restored.complete_reminder('10', reminder_id=identity)[2] == '01.11.2026 05:01'
        assert restored.get_active_reminders('10')[0]['series_next_index'] == 2
    finally:
        restored._storage.close()


async def test_handler_creates_actual_timed_recurring_series(tmp_path):
    manager = ReminderManager(tmp_path / 'reminders.json', clock=Clock(wall=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc)))
    handler = ReminderHandler(SimpleNamespace(reminders=manager, rate_limiter=None, loc=None, client=None))
    async def send(*args, **kwargs):
        return None
    handler.send_response = send
    message = SimpleNamespace(content='@inebotten påminnelse Weekly 18.10.2026 kl 05:01 hver uke',
        guild=SimpleNamespace(id=10), channel=SimpleNamespace(id=20), author=SimpleNamespace(id=7, name='Test'))
    try:
        await handler.handle_reminder_create(message)
        record = manager.get_active_reminders('10')[0]
        assert record['recurrence'] == 'weekly'
        assert record['text'] == 'Weekly'
        assert manager.complete_reminder('10', reminder_id=record['id'])[2] == '25.10.2026 05:01'
    finally:
        manager._storage.close()


def test_recurring_creation_without_deadline_preserves_store(tmp_path):
    manager = ReminderManager(tmp_path / 'reminders.json')
    try:
        manager.add_reminder('10', '7', 'Test', 'Original')
        before = manager.storage_path.read_bytes()
        with pytest.raises(ValueError):
            manager.add_reminder('10', '7', 'Test', 'Undated', recurrence='weekly')
        assert manager.storage_path.read_bytes() == before
    finally:
        manager._storage.close()
