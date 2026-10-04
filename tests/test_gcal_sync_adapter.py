"""Request-level custom-ID, conditional-write and error classification proof."""
import copy
import json
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from cal_system.google_calendar_manager import GoogleCalendarManager
from cal_system.sync_outbox import SyncOperation


@pytest.fixture
def adapter(monkeypatch):
    from google.oauth2.credentials import Credentials
    import googleapiclient.discovery
    monkeypatch.setattr(Credentials, 'from_authorized_user_file', Mock(return_value=SimpleNamespace(expired=False, valid=True)))
    request = SimpleNamespace(headers={}, execute=Mock(return_value={'id': 'ib0123456789abcdef', 'etag': 'accepted'}))
    events = SimpleNamespace(**{name: Mock(return_value=request) for name in ('insert', 'patch', 'delete')})
    service = SimpleNamespace(events=lambda: events, close=Mock())
    monkeypatch.setattr(googleapiclient.discovery, 'build', Mock(return_value=service))
    # Constructor bypassed: no configuration discovery or credential file reads.
    manager = object.__new__(GoogleCalendarManager)
    manager.enabled = True
    manager.calendar_id = 'synthetic-calendar'
    manager._token_path = lambda: '/synthetic-never-read'
    return manager, events, request, service


def op(kind):
    return SyncOperation('a' * 32, 'item', 1, kind, 'ib0123456789abcdef',
        'original-etag' if kind != 'create' else None, 'unknown', 1, None,
        {'summary': 'Møte', 'recurrence': [], 'extendedProperties': {'private': {'inebotten_operation_id': 'a' * 32}}}, 'shared')


@pytest.mark.parametrize('kind', ['create', 'update', 'delete'])
def test_custom_id_or_if_match_and_no_hidden_retries(adapter, kind):
    manager, events, request, service = adapter
    operation = op(kind)
    original = copy.deepcopy(operation.payload)
    result = manager.apply_sync_operation(operation)
    assert result.status == 'acknowledged'
    request.execute.assert_called_once_with(num_retries=0)
    if kind == 'create':
        assert events.insert.call_args.kwargs['body']['id'] == operation.remote_id
        assert 'If-Match' not in request.headers
    else:
        assert request.headers['If-Match'] == 'original-etag'
        if kind == 'update':
            assert events.patch.call_args.kwargs['body']['recurrence'] == []
    assert operation.payload == original
    service.close.assert_called_once()


@pytest.mark.parametrize('status,reason,expected', [
    (403, 'rateLimitExceeded', 'retryable'), (403, 'userRateLimitExceeded', 'retryable'),
    (403, 'forbidden', 'auth_error'), (401, 'authError', 'auth_error'),
    (429, 'rateLimitExceeded', 'retryable'), (400, 'badRequest', 'rejected'),
    (409, 'duplicate', 'conflict'), (412, 'conditionNotMet', 'conflict'),
    (500, 'backendError', 'unknown'), (404, 'notFound', 'unknown')])
def test_error_classification_does_not_reissue_uncertain_write(adapter, status, reason, expected):
    from googleapiclient.errors import HttpError
    import httplib2
    manager, events, request, service = adapter
    request.execute.side_effect = HttpError(httplib2.Response({'status': str(status), 'retry-after': '35'}),
        json.dumps({'error': {'errors': [{'reason': reason}]}}).encode())
    result = manager.apply_sync_operation(op('update'))
    assert result.status == expected
    if expected == 'retryable':
        assert result.retry_after_s == 35
    assert request.execute.call_count == 1
    service.close.assert_called_once()


def test_cleanup_failure_cannot_erase_acceptance_evidence(adapter):
    manager, _, _, service = adapter
    service.close.side_effect = RuntimeError('cleanup')
    assert manager.apply_sync_operation(op('create')).status == 'acknowledged'
