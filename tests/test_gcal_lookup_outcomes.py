"""Unavailable remote evidence must never delete a local calendar item."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from googleapiclient.errors import HttpError
from cal_system.calendar_manager import CalendarManager
from cal_system.google_calendar_manager import GoogleCalendarManager


def error(status, reason='backendError', retry=None):
    response = {'status': str(status)}
    if retry:
        response['retry-after'] = retry
    return HttpError(SimpleNamespace(status=status, reason='synthetic', **{'get': response.get}),
                     json.dumps({'error': {'errors': [{'reason': reason}]}}).encode())


def local_item(remote='remote-1'):
    return dict(id='local-'+remote, title='Behold meg', date=(datetime.now()+timedelta(days=1)).strftime('%d.%m.%Y'),
                time='12:00', gcal_event_id=remote, completed=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [None, TimeoutError(), error(403), error(404, 'notFound'),
                                    error(429, 'rateLimitExceeded', '12'), error(500), [], {}, {'id': 'wrong'}])
async def test_none_timeout_and_permission_preserve_local_item(tmp_path, result):
    def lookup(_):
        if isinstance(result, Exception):
            raise result
        return result
    remote = SimpleNamespace(is_configured=lambda: True, list_upcoming_events=lambda **kw: [], get_event=lookup)
    manager = CalendarManager(storage_path=tmp_path/'calendar.json', gcal_manager=remote)
    before = local_item()
    manager.items = {manager.SHARED_KEY: [before.copy()]}
    assert await manager.sync_from_gcal() == 0
    after = manager.items[manager.SHARED_KEY][0]
    assert {key: after[key] for key in before} == before
    assert after['gcal_lookup_status'] == 'unavailable'
    assert after['gcal_lookup_checked_at']
    assert manager.last_gcal_sync_error
    assert json.loads((tmp_path/'calendar.json').read_text())["document"][manager.SHARED_KEY][0]['id'] == before['id']


@pytest.mark.asyncio
async def test_authoritative_cancel_removes_item(tmp_path):
    def lookup(event_id):
        return {'id': event_id, 'status': 'cancelled'} if event_id == 'gone' else None
    remote = SimpleNamespace(is_configured=lambda: True, list_upcoming_events=lambda **kw: [], get_event=lookup)
    manager = CalendarManager(storage_path=tmp_path/'calendar.json', gcal_manager=remote)
    manager.items = {manager.SHARED_KEY: [local_item('gone'), local_item('unknown')]}
    assert await manager.sync_from_gcal() == 1
    assert [item['id'] for item in manager.items[manager.SHARED_KEY]] == ['local-unknown']
    assert manager.last_gcal_sync_error


@pytest.mark.parametrize('result,status,reason', [
    ({'id': 'event', 'status': 'cancelled'}, 'cancelled', 'cancelled'),
    ({'id': 'event', 'status': 'confirmed', 'start': {'date': '2027-01-01'}}, 'live', 'ok'),
    (None, 'unavailable', 'malformed_response'),
    ({'id': 'wrong', 'status': 'cancelled'}, 'unavailable', 'malformed_response'),
    (error(404, 'notFound'), 'unavailable', 'notFound'),
    (error(410, 'deleted'), 'missing', 'deleted'),
    (error(410, 'fullSyncRequired'), 'unavailable', 'fullSyncRequired'),
    (error(403, 'forbidden'), 'unavailable', 'forbidden'),
    (error(429, 'rateLimitExceeded', '12'), 'unavailable', 'rateLimitExceeded'),
    (error(503), 'unavailable', 'backendError'),
    (TimeoutError(), 'unavailable', 'transport_error'),
])
def test_api_lookup_classifies_without_guessing(result, status, reason):
    manager = GoogleCalendarManager.__new__(GoogleCalendarManager)
    manager.enabled = True
    manager.calendar_id = 'primary'
    def execute():
        if isinstance(result, Exception):
            raise result
        return result
    service = SimpleNamespace(events=lambda: SimpleNamespace(get=lambda **kw: SimpleNamespace(execute=execute)))
    with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=SimpleNamespace(expired=False)), \
         patch('googleapiclient.discovery.build', return_value=service):
        outcome = manager.get_event_outcome('event')
    assert outcome.status == status
    assert outcome.reason_code == reason
    if reason == 'rateLimitExceeded':
        assert outcome.retry_after_s == 12
