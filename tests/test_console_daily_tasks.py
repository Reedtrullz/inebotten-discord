from types import SimpleNamespace

import pytest

from cal_system.reminder_manager import ReminderManager
from features.poll_manager import PollManager
from memory.user_memory import UserMemory
from core.request_context import RequestContext, request_scope
from tests.test_console_calendar_workspace import workspace, http_request, API_KEY, ACTOR, SCOPE


@pytest.fixture
async def daily(workspace, tmp_path):
    server, calendar, actor = workspace
    reminders = ReminderManager(tmp_path / 'reminders.json', access_policy=calendar.access_policy, clock=calendar.clock)
    polls = PollManager(tmp_path / 'polls.json')
    memory = UserMemory(tmp_path / 'memory.json')
    server.console_actor_channel_id = '123'
    actor = server._console_actor()
    with request_scope(actor):
        item_id = reminders.add_reminder(None, ACTOR, 'Synthetic', 'My task', '13.10.2026 12:00', channel_id=123)
        reminders.add_reminder(None, '999', 'Other', 'Other private task', channel_id=123)
        poll = polls.create_poll('10', 'Lunch?', ['A', 'B'], 'Synthetic', ACTOR)
        polls.set_message_id('10', poll['id'], '900', '123')
    server.monitor = SimpleNamespace(calendar=calendar, reminders=reminders, poll=polls, user_memory=memory)
    try:
        yield server, reminders, polls, actor, item_id
    finally:
        await reminders._storage.aclose()
        await reminders._outbox.slot.close()
        polls.close_storage()
        memory._storage.close()


async def test_daily_workspace_filters_private_records_and_voter_ids(daily):
    server, reminders, polls, actor, item_id = daily
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    assert status == 200
    assert [item['text'] for item in data['reminders']] == ['My task']
    assert data['reminders'][0]['id'] == item_id
    assert data['polls'][0]['question'] == 'Lunch?'
    assert data['polls'][0]['options'][0]['votes'] == 0
    assert 'user_id' not in data['reminders'][0]
    server.console_actor_user_id = '999'
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    assert status == 403


async def test_daily_preview_apply_complete_undo_and_stale_rejection(daily):
    server, reminders, _, actor, item_id = daily
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    assert status == 200
    payload = {'domain': 'reminder', 'operation': 'complete', 'revision': data['revisions']['reminder'], 'item_id': item_id}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 200
    status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 200 and result['undo']['token']
    with request_scope(actor):
        assert next(r for r in reminders.reminders[SCOPE] if r['id'] == item_id)['completed'] is True
    status, _ = await http_request(server, '/api/tasks/undo', method='POST', api_key=API_KEY, body={'token': result['undo']['token']})
    assert status == 200 and not reminders.reminders[SCOPE][0]['completed']
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=dict(payload, revision=reminders._storage.revision))
    assert status == 200
    with request_scope(actor):
        reminders.edit_reminder(None, 1, title='Concurrent')
    status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 409 and result['error'] == 'revision_changed'
    assert reminders.reminders[SCOPE][0]['text'] == 'Concurrent'


async def test_daily_write_uses_existing_origin_and_auth_guards(daily):
    server, _, _, _, _ = daily
    status, _ = await http_request(server, '/api/tasks/preview', method='POST', body={}, api_key=API_KEY,
                                   headers=('Origin: https://attacker.invalid',))
    assert status == 403
    status, _ = await http_request(server, '/api/tasks', api_key='invalid')
    assert status == 401


async def test_default_console_channel_keeps_own_tasks_visible_and_can_pause(daily):
    server, _, _, _, item_id = daily
    server.console_actor_channel_id = 'console'
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    assert status == 200 and [row['id'] for row in data['reminders']] == [item_id]
    assert data['notification_available'] is False
    payload = {'domain': 'notification', 'operation': 'edit', 'revision': data['revisions']['notification'], 'changes': {'enabled': False}}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 200
    status, _ = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 200
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    assert status == 200 and data['notification']['enabled'] is False


async def test_direct_action_is_bound_to_owner_channel_and_record(daily):
    from features.task_workspace import task_workspace
    server, reminders, _, actor, item_id = daily
    service = task_workspace(server.monitor)
    token = service.reminder_action_token(actor, item_id)
    wrong = RequestContext('test', '999', '123', None, 'no', channel_kind='console')
    with pytest.raises(PermissionError):
        await service.reminder_action(wrong, token, 'complete')
    with request_scope(actor):
        reminders.edit_reminder(None, 1, title='Changed')
    with pytest.raises(ValueError, match='selection_changed'):
        await service.reminder_action(actor, token, 'complete')
    token = service.reminder_action_token(actor, item_id)
    await service.reminder_action(actor, token, 'complete')
    assert reminders.reminders[SCOPE][0]['completed']


async def test_snoozed_task_without_deadline_still_has_a_delivery_plan(daily):
    from features.task_workspace import task_workspace
    server, reminders, _, actor, item_id = daily
    with request_scope(actor):
        reminders.edit_reminder(None, 1, date='')
    service = task_workspace(server.monitor)
    await service.reminder_action(actor, service.reminder_action_token(actor, item_id), 'snooze')
    plan = service.items(actor)['reminders'][0]['plan']
    assert plan['next_at'] is not None and plan['destination_id'] == '123'
    assert 'Ingen frist' not in plan['message']


async def test_console_vote_changes_choice_without_requiring_poll_ownership(daily):
    from features.task_workspace import task_workspace
    server, _, polls, actor, _ = daily
    service = task_workspace(server.monitor)
    poll = next(iter(polls.polls['10'].values()))
    poll['created_by_id'] = '999'
    for choice in (1, 2):
        preview = service.preview(actor, {'domain': 'poll', 'operation': 'vote', 'item_id': poll['id'],
            'revision': polls._storage.revision, 'changes': {'option_index': choice}})
        await service.apply(actor, preview['token'])
    saved = polls.polls['10'][poll['id']]
    assert saved['options'][0]['votes'] == []
    assert saved['options'][1]['votes'] == [ACTOR]
    assert 'user_id' not in service.items(actor)['polls'][0]


async def test_console_deadline_can_be_cleared_and_empty_edits_are_rejected(daily):
    from features.task_workspace import task_workspace
    server, reminders, _, actor, item_id = daily
    service = task_workspace(server.monitor)
    payload = {'domain': 'reminder', 'operation': 'edit', 'item_id': item_id,
               'revision': reminders._storage.revision, 'changes': {}}
    with pytest.raises(ValueError, match='invalid_changes'):
        service.preview(actor, payload)
    preview = service.preview(actor, dict(payload, changes={'due_date': ''}))
    await service.apply(actor, preview['token'])
    assert reminders.reminders[SCOPE][0]['due_date'] is None


async def test_actions_and_undo_expire_and_recheck_revoked_scope(daily):
    from features.task_workspace import task_workspace
    from core.access_policy import AccessPolicy, ScopeRecord
    server, reminders, _, actor, item_id = daily
    service = task_workspace(server.monitor)
    token = service.reminder_action_token(actor, item_id)
    service.actions[token]['expires'] = 0
    with pytest.raises(ValueError, match='action_expired'):
        await service.reminder_action(actor, token, 'complete')
    token = service.reminder_action_token(actor, item_id)
    result = await service.reminder_action(actor, token, 'complete')
    undo = result['undo']
    assert undo is not None
    reminders._local_undo[undo['token']]['expires'] = 0
    with pytest.raises(ValueError, match='undo_expired'):
        service.undo(actor, undo['token'])
    server.monitor.calendar.access_policy = AccessPolicy([ScopeRecord('private:999', 'private_user', owner_id='999')], default_scope='private:999')
    with pytest.raises(PermissionError):
        service.items(actor)
    assert reminders.reminders[SCOPE][0]['completed']
