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


async def test_console_creates_timed_recurrence_and_completes_only_current_occurrence(daily):
    server, reminders, _, actor, _ = daily
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    payload = {'domain': 'reminder', 'operation': 'create', 'revision': data['revisions']['reminder'],
        'changes': {'text': 'Weekly task', 'due_date': '18.10.2026 05:01', 'recurrence': 'weekly'}}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 200
    status, _ = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 200
    with request_scope(actor):
        item = next(r for r in reminders.get_active_reminders(None) if r['text'] == 'Weekly task')
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    payload = {'domain': 'reminder', 'operation': 'complete', 'revision': data['revisions']['reminder'], 'item_id': item['id']}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 200 and preview['before']['recurrence'] == 'weekly'
    status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 200 and result['undo']['token']
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    row = next(r for r in data['reminders'] if r['id'] == item['id'])
    assert not row['completed'] and row['due_date'] == '25.10.2026 05:01'
    assert row['recurrence'] == 'weekly' and row['plan']['next_at'] == '2026-10-25T03:31:00+00:00'
    status, _ = await http_request(server, '/api/tasks/undo', method='POST', api_key=API_KEY, body={'token': result['undo']['token']})
    assert status == 200
    with request_scope(actor):
        restored = next(r for r in reminders.get_active_reminders(None) if r['id'] == item['id'])
        assert restored['due_date'] == '18.10.2026 05:01' and restored['series_next_index'] == 0


@pytest.mark.parametrize('changes', [{'text': 'Invalid', 'recurrence': 'weekly'},
    {'text': 'Invalid', 'due_date': '18.10.2026 05:01', 'recurrence': 'nonsense'}])
async def test_console_rejects_invalid_recurrence_before_writing(daily, changes):
    server, reminders, _, _, _ = daily
    before = reminders.storage_path.read_bytes()
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    payload = {'domain': 'reminder', 'operation': 'create', 'revision': data['revisions']['reminder'], 'changes': changes}
    status, _ = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 400 and reminders.storage_path.read_bytes() == before


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


async def test_console_snooze_uses_existing_delivery_channel_and_keeps_reminder(daily):
    from datetime import timedelta
    server, reminders, _, _, item_id = daily
    server.console_actor_channel_id = 'console'
    original = dict(reminders.reminders[SCOPE][0])
    before = reminders.clock.now('UTC')
    payload = {'domain': 'reminder', 'operation': 'snooze', 'revision': reminders._storage.revision, 'item_id': item_id}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 200
    status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 200 and result['ok']
    assert reminders.reminders[SCOPE][0] == original
    memory = server.monitor.user_memory
    assert memory.notification_profile(ACTOR, SCOPE).destination_id == '123'
    snoozes = memory.notification_snoozes(ACTOR, SCOPE)
    assert len(snoozes) == 1 and snoozes[0]['item_id'] == item_id
    from datetime import datetime
    assert before + timedelta(minutes=10) <= datetime.fromisoformat(snoozes[0]['due_at']) <= reminders.clock.now('UTC') + timedelta(minutes=10)
    status, data = await http_request(server, '/api/tasks', api_key=API_KEY)
    assert status == 200 and data['reminders'][0]['plan']['next_at'] == snoozes[0]['due_at']


async def test_console_snooze_rejects_changed_preview(daily):
    server, reminders, _, actor, item_id = daily
    payload = {'domain': 'reminder', 'operation': 'snooze', 'revision': reminders._storage.revision, 'item_id': item_id}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    assert status == 200
    with request_scope(actor):
        reminders.complete_reminder(None, reminder_id=item_id)
    status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
    assert status == 409 and result['error'] == 'revision_changed'
    assert server.monitor.user_memory.notification_snoozes(ACTOR, SCOPE) == []


@pytest.mark.parametrize('case', ['private_item', 'changes', 'no_destination'])
async def test_console_snooze_cannot_change_private_data_or_use_unapproved_destination(daily, case):
    server, reminders, _, actor, item_id = daily
    server.console_actor_channel_id = 'console'
    if case == 'private_item':
        item_id = reminders.reminders[SCOPE][1]['id']
    elif case == 'no_destination':
        with request_scope(actor), reminders._storage.transaction(write=True):
            reminders.reminders[SCOPE][0]['channel_id'] = 'console'
            reminders._save_reminders()
    payload = {'domain': 'reminder', 'operation': 'snooze', 'revision': reminders._storage.revision, 'item_id': item_id}
    if case == 'changes':
        payload['changes'] = {'text': 'Unexpected edit'}
    status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
    if case == 'no_destination':
        assert status == 200
        status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
        assert status == 400 and result['error'] == 'notification_destination_required'
    else:
        assert status == (403 if case == 'private_item' else 400)
    assert server.monitor.user_memory.notification_profile(ACTOR, SCOPE) is None
    assert server.monitor.user_memory.notification_snoozes(ACTOR, SCOPE) == []


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
        await service.undo(actor, undo['token'])
    server.monitor.calendar.access_policy = AccessPolicy([ScopeRecord('private:999', 'private_user', owner_id='999')], default_scope='private:999')
    with pytest.raises(PermissionError):
        service.items(actor)
    assert reminders.reminders[SCOPE][0]['completed']


@pytest.mark.parametrize('frequency', ['biweekly', 'monthly', 'yearly'])
@pytest.mark.parametrize('surface', ['discord', 'console'])
async def test_recurring_snooze_cancel_and_exact_undo(daily, frequency, surface):
    import copy
    from features.task_workspace import task_workspace
    server, reminders, _, actor, item_id = daily
    with request_scope(actor):
        reminders.edit_reminder(None, 1, recurrence=frequency)
    original = copy.deepcopy(reminders.reminders[SCOPE][0])
    service = task_workspace(server.monitor)
    async def action(operation):
        if surface == 'discord':
            return await service.reminder_action(actor, service.reminder_action_token(actor, item_id), operation)
        payload = {'domain': 'reminder', 'operation': operation, 'revision': reminders._storage.revision, 'item_id': item_id}
        status, preview = await http_request(server, '/api/tasks/preview', method='POST', api_key=API_KEY, body=payload)
        assert status == 200
        status, result = await http_request(server, '/api/tasks/apply', method='POST', api_key=API_KEY, body={'token': preview['token']})
        assert status == 200
        return result
    snoozed = await action('snooze')
    memory = server.monitor.user_memory
    plan = memory.notification_snoozes(ACTOR, SCOPE)
    assert len(plan) == 1 and snoozed['undo']['token']
    canceled = await action('cancel_snooze')
    assert memory.notification_snoozes(ACTOR, SCOPE) == []
    assert canceled['undo']['token'] and reminders.reminders[SCOPE][0] == original
    restored = await service.undo(actor, canceled['undo']['token'])
    assert restored['ok'] and memory.notification_snoozes(ACTOR, SCOPE) == plan
    assert reminders.reminders[SCOPE][0] == original
    snoozed = await action('snooze')
    await service.undo(actor, snoozed['undo']['token'])
    assert memory.notification_snoozes(ACTOR, SCOPE) == plan
    await action('cancel_snooze')
    with pytest.raises(ValueError, match='snooze_not_pending'):
        await service.reminder_action(actor, service.reminder_action_token(actor, item_id), 'cancel_snooze')


@pytest.mark.parametrize('change', ['actor', 'scope', 'reminder', 'memory', 'elapsed'])
async def test_snooze_undo_refuses_stale_or_unsafe_restoration(daily, change):
    from datetime import datetime, timedelta
    from features.task_workspace import task_workspace
    server, reminders, _, actor, item_id = daily
    service = task_workspace(server.monitor)
    await service.reminder_action(actor, service.reminder_action_token(actor, item_id), 'snooze')
    pending = server.monitor.user_memory.notification_snoozes(ACTOR, SCOPE)[0]
    result = await service.reminder_action(actor, service.reminder_action_token(actor, item_id), 'cancel_snooze')
    if change == 'actor':
        actor = RequestContext('other', '999', '123', None, 'no', 'dm')
    elif change == 'scope':
        from core.access_policy import AccessPolicy, ScopeRecord
        server.monitor.calendar.access_policy = AccessPolicy([ScopeRecord('private:999', 'private_user', owner_id='999')], default_scope='private:999')
    elif change == 'reminder':
        with request_scope(actor):
            reminders.complete_reminder(None, reminder_id=item_id)
    elif change == 'memory':
        await server.monitor.user_memory.get_user('999')
    else:
        from cal_system.event_schema import Clock
        reminders.clock = Clock(wall=lambda: datetime.fromisoformat(pending['due_at']) + timedelta(seconds=1))
    with pytest.raises((ValueError, PermissionError)):
        await service.undo(actor, result['undo']['token'])
    assert server.monitor.user_memory.notification_snoozes(ACTOR, SCOPE) == []


async def test_cancel_preview_rechecks_replaced_snooze(daily):
    from features.task_workspace import task_workspace
    server, reminders, _, actor, item_id = daily
    service = task_workspace(server.monitor)
    token = service.reminder_action_token(actor, item_id)
    await service.reminder_action(actor, token, 'snooze')
    payload = {'domain': 'reminder', 'operation': 'cancel_snooze', 'revision': reminders._storage.revision, 'item_id': item_id}
    preview = service.preview(actor, payload)
    await service.reminder_action(actor, token, 'snooze')
    pending = server.monitor.user_memory.notification_snoozes(ACTOR, SCOPE)
    with pytest.raises(ValueError, match='revision_changed'):
        await service.apply(actor, preview['token'])
    assert server.monitor.user_memory.notification_snoozes(ACTOR, SCOPE) == pending


async def test_cancel_without_snooze_does_not_enable_notifications(daily):
    from features.task_workspace import task_workspace
    server, _, _, actor, item_id = daily
    service = task_workspace(server.monitor)
    with pytest.raises(ValueError, match='snooze_not_pending'):
        await service.reminder_action(actor, service.reminder_action_token(actor, item_id), 'cancel_snooze')
    assert server.monitor.user_memory.notification_profile(ACTOR, SCOPE) is None
