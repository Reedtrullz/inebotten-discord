from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.event_schema import Clock
from cal_system.recurrence import Occurrence, Series, occurrence_at
from cal_system.reminder_manager import ReminderManager
from cal_system.natural_language_parser import NaturalLanguageParser
from features.reminder_handler import ReminderHandler


@pytest.fixture
def reminders(tmp_path):
    manager = ReminderManager(storage_path=tmp_path / 'reminders.json',
        clock=Clock(wall=lambda: datetime(2027, 1, 4, 12, tzinfo=timezone.utc)))
    yield manager
    manager._storage.close()


def test_rule_edit_preserves_history_identity_and_remaining_count(reminders):
    item_id = reminders.add_reminder('123', '7', 'Owner', 'Weekly task',
        due_date='04.01.2027', recurrence='weekly', end_count=3)
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] == '11.01.2027'
    before = reminders.get_active_reminders('123')[0]
    old_series = Series.from_document(before['series'])
    current = occurrence_at(old_series, 1)
    assert current is not None
    edited = reminders.edit_reminder('123', 1, recurrence='daily')
    assert edited['occurrences'] == before['occurrences']
    changed_series = Series.from_document(edited['series'])
    changed_current = occurrence_at(changed_series, 1)
    assert changed_current is not None and changed_current.occurrence_id == current.occurrence_id
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] == '12.01.2027'
    assert reminders.complete_reminder('123', reminder_id=item_id) == (True, 'Weekly task', None)
    saved = reminders.reminders['123'][0]
    assert saved['series_history'][0]['series'] == before['series']
    assert saved['occurrences'][current.occurrence_id]['state'] == 'completed'


def test_date_edit_reanchors_remaining_monthly_occurrences(reminders):
    item_id = reminders.add_reminder('123', '7', 'Owner', 'Monthly task',
        due_date='31.01.2027', recurrence='monthly', end_count=4)
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] == '28.02.2027'
    before = reminders.get_active_reminders('123')[0]
    edited = reminders.edit_reminder('123', 1, date='15.03.2027')
    assert edited['occurrences'] == before['occurrences']
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] == '15.04.2027'


@pytest.mark.parametrize('due, rule', [
    ('', 'daily'), ('11.10.2026', 'nonsense'),
])
def test_invalid_recurrence_edit_preserves_committed_reminder(reminders, due, rule):
    reminders.add_reminder('123', '7', 'Owner', 'Task', due_date=due)
    before = reminders.storage_path.read_bytes()
    revision, snapshot = reminders._storage.published_snapshot()
    with pytest.raises(ValueError):
        reminders.edit_reminder('123', 1, title='Uncommitted title', recurrence=rule)
    assert reminders.storage_path.read_bytes() == before
    assert reminders._storage.published_snapshot() == (revision, snapshot)
    assert reminders.get_active_reminders('123')[0]['text'] == 'Task'


def test_pending_occurrence_exception_requires_review_before_schedule_change(reminders):
    reminders.add_reminder('123', '7', 'Owner', 'Weekly task',
        due_date='04.01.2027', recurrence='weekly')
    document = reminders.reminders
    item = document['123'][0]
    series = Series.from_document(item['series'])
    pending = occurrence_at(series, 1)
    assert pending is not None
    item['occurrences'][pending.occurrence_id] = Occurrence(
        pending.occurrence_id, series.series_id, pending.original_start, 'skipped').to_document()
    reminders.reminders = document
    reminders._save_reminders()
    before = reminders.storage_path.read_bytes()
    with pytest.raises(ValueError):
        reminders.edit_reminder('123', 1, recurrence='daily')
    assert reminders.storage_path.read_bytes() == before


@pytest.mark.asyncio
async def test_handler_accepts_timed_recurrence_and_preserves_time(reminders):
    reminders.add_reminder('123', '7', 'Owner', 'Timed task', due_date='11.10.2026 18:45')
    sent = []
    handler = ReminderHandler(SimpleNamespace(reminders=reminders,
        rate_limiter=None, client=None, loc=SimpleNamespace(t=lambda key, **kwargs: key),
        nlp_parser=NaturalLanguageParser()))

    async def send(message, content: str, mention_author: bool = False):
        sent.append(content)
        return SimpleNamespace(id=1)

    handler.send_response = AsyncMock(side_effect=send)
    message = SimpleNamespace(content='@inebotten endre påminnelse 1 gjentakelse: daglig',
        guild=SimpleNamespace(id=123), channel=SimpleNamespace(id=456), author=SimpleNamespace(id=7))
    await handler.handle_reminder_list(message)
    sent.clear()
    await handler.handle_reminder_edit(message)
    assert len(sent) == 1 and 'reminder_edit_success' in sent[0]
    item = reminders.get_active_reminders('123')[0]
    assert item['recurrence'] == 'daily'
    assert reminders.complete_reminder('123', reminder_id=item['id'])[2] == '12.10.2026 18:45'


@pytest.mark.asyncio
async def test_handler_normalizes_norwegian_recurrence_edits(reminders):
    item_id = reminders.add_reminder('123', '7', 'Owner', 'Weekly task',
        due_date='04.01.2027', recurrence='weekly')
    handler = ReminderHandler(SimpleNamespace(reminders=reminders,
        rate_limiter=None, client=None, loc=SimpleNamespace(t=lambda key, **kwargs: key),
        nlp_parser=NaturalLanguageParser()))

    async def send(message, content: str, mention_author: bool = False):
        return SimpleNamespace(id=1)

    handler.send_response = AsyncMock(side_effect=send)
    message = SimpleNamespace(content='@inebotten endre påminnelse 1 gjentakelse: daglig',
        guild=SimpleNamespace(id=123), channel=SimpleNamespace(id=456), author=SimpleNamespace(id=7))
    await handler.handle_reminder_list(message)
    await handler.handle_reminder_edit(message)
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] == '05.01.2027'


@pytest.mark.parametrize('end', [{'end_count': 1}, {'end_date': '04.01.2027'}])
def test_last_recurrence_lists_and_retains_its_aware_completion(reminders, end):
    item_id = reminders.add_reminder('123', '7', 'Owner', 'Last occurrence',
        due_date='04.01.2027', recurrence='daily', **end)
    assert reminders.complete_reminder('123', reminder_id=item_id)[0] is True
    assert [item['id'] for item in reminders.get_completed_reminders('123', days=0)] == [item_id]
    assert 'Last occurrence' in reminders.format_reminders_list('123', show_completed=True)
    reminders.delete_old_completed('123', days=0)
    assert [item['id'] for item in reminders.reminders['123']] == [item_id]


def test_nonrecurring_completion_uses_the_injected_clock(reminders):
    item_id = reminders.add_reminder('123', '7', 'Owner', 'Task')
    reminders.complete_reminder('123', reminder_id=item_id)
    assert reminders.reminders['123'][0]['completed_at'] == '2027-01-04T13:00:00+01:00'


def test_mixed_completion_timestamps_use_one_retention_boundary(reminders):
    for title in ('Legacy boundary', 'UTC boundary', 'Expired', 'Unknown age'):
        reminders.add_reminder('123', '7', 'Owner', title)
    document = reminders.reminders
    stamps = ['2026-12-28T13:00:00', '2026-12-28T12:00:00+00:00',
              '2026-12-28T11:59:59+00:00', 'invalid']
    for item, stamp in zip(document['123'], stamps):
        item.update(completed=True, completed_at=stamp)
    reminders.reminders = document
    reminders._save_reminders()
    assert [item['text'] for item in reminders.get_completed_reminders('123')] == [
        'Legacy boundary', 'UTC boundary']
    before_stamps = {item['text']: item['completed_at'] for item in reminders.reminders['123']}
    reminders.delete_old_completed('123')
    assert [item['text'] for item in reminders.reminders['123']] == [
        'Legacy boundary', 'UTC boundary', 'Unknown age']
    assert all(item['completed_at'] == before_stamps[item['text']] for item in reminders.reminders['123'])


def test_retention_preserves_unresolved_remote_delete(reminders):
    reminders.add_reminder('123', '7', 'Owner', 'Remote task', gcal_event_id='remote-id')
    reminders.delete_reminder_by_id('123', 1)
    before = reminders.reminders
    reminders.delete_old_completed('123')
    assert reminders.reminders == before


def test_disabling_then_enabling_recurrence_preserves_history_and_count(reminders):
    item_id = reminders.add_reminder('123', '7', 'Owner', 'Task',
        due_date='04.01.2027', recurrence='weekly', end_count=3)
    reminders.complete_reminder('123', reminder_id=item_id)
    before = reminders.get_active_reminders('123')[0]
    disabled = reminders.edit_reminder('123', 1, recurrence='')
    assert not disabled.get('series') and disabled['occurrences'] == before['occurrences']
    reminders.edit_reminder('123', 1, recurrence='daily')
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] == '12.01.2027'
    assert reminders.complete_reminder('123', reminder_id=item_id)[2] is None
