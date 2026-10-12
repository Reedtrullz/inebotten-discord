from datetime import datetime, time

import pytest

from cal_system.event_schema import Clock
from cal_system.notification_preferences import NotificationProfile, next_delivery
from cal_system.reminder_manager import ReminderManager
from core.command_registry import command_help_pages
from tests.test_reminder_late_catchup import _checker, _oslo_due


async def test_due_reminder_has_one_alert_not_an_immediate_overdue_followup(tmp_path):
    sent = []
    item = {'id': 'one-alert', 'text': 'Synthetic', 'due_date': _oslo_due(0),
            'channel_id': '123', 'user_id': '7', 'completed': False}
    checker = _checker(tmp_path, sent, {'123': [item]})
    await checker.setup()
    try:
        await checker.check_event_now()
        await checker.check_event_passed()
        assert len(sent) == 1
    finally:
        checker.close_storage()


def test_last_reminder_page_does_not_offer_a_nonexistent_next_page(tmp_path):
    manager = ReminderManager(tmp_path / 'reminders.json')
    try:
        for n in range(9):
            manager.add_reminder(123, 7, 'Synthetic', f'Task {n}')
        last = manager.format_reminders_list(123, page=2)
        assert last is not None
        assert 'Neste:' not in last
        assert 'Forrige:' in last
        outside = manager.format_reminders_list(123, page=3)
        assert outside is not None and 'Ingen' in outside
    finally:
        manager._storage.close()


def test_notification_help_exposes_controls_instead_of_memory_commands():
    help_text = '\n'.join(command_help_pages(topic='varsler'))
    assert 'varsler stille 22:00-07:00' in help_text
    assert 'slumre #' in help_text
    assert 'vis minnet mitt' not in help_text
    assert all(len(page) <= 500 for page in command_help_pages(500, topic='varsler'))


def test_quiet_hours_can_defer_alert_until_after_deadline():
    profile = NotificationProfile(True, 'shared', '123', (0,), time(22), time(7))
    event = datetime.fromisoformat('2026-10-12T06:30:00+02:00')
    clock = Clock(wall=lambda: datetime.fromisoformat('2026-10-12T03:00:00+00:00'))
    assert next_delivery(profile, event, clock) == datetime.fromisoformat('2026-10-12T05:00:00+00:00')


@pytest.mark.parametrize('command,action', [
    ('ferdig påminnelse valg abcdefgh1234', 'task_action'),
    ('slumre valg abcdefgh1234', 'task_action'),
    ('endre påminnelse valg abcdefgh1234 tekst: Endret', 'task_action'),
    ('angre endring abcdefgh1234abcdefgh1234', 'task_undo'),
    ('varsler etterfrist 30', 'notification'),
    ('varsler etterfrist av', 'notification'),
])
def test_receipt_controls_use_validated_command_routing(command, action):
    from core.intent_router import IntentRouter
    from core.command_registry import validate_payload
    from tests.test_intent_router import DummyMonitor
    route = IntentRouter(DummyMonitor()).route(command, 123)
    assert route.intent.value == 'memory_view'
    payload = validate_payload(route.intent, route.payload)
    assert payload['memory']['action'] == action


def test_reminder_undo_restores_only_target_and_rejects_intervening_write(tmp_path):
    from core.request_context import RequestContext, request_scope
    from utils.local_undo import undo_change, undo_hint
    manager = ReminderManager(tmp_path / 'undo.json')
    actor = RequestContext('test', '7', '123', '123', 'no', channel_kind='guild')
    try:
        with request_scope(actor):
            first = manager.add_reminder(123, 7, 'Synthetic', 'First')
            other = manager.add_reminder(123, 7, 'Synthetic', 'Other')
            manager.complete_reminder(123, reminder_id=first)
            hint = undo_hint(manager, actor)
            assert hint is not None
            token = hint['token']
            undo_change(manager, actor, token)
            assert [r['id'] for r in manager.get_active_reminders(123)] == [first, other]
            manager.edit_reminder(123, 1, title='Changed')
            hint = undo_hint(manager, actor)
            assert hint is not None
            token = hint['token']
            manager.edit_reminder(123, 2, title='Newer other')
            with pytest.raises(ValueError, match='revision_changed'):
                undo_change(manager, actor, token)
            assert [r['text'] for r in manager.get_active_reminders(123)] == ['Changed', 'Newer other']
    finally:
        manager._storage.close()


@pytest.mark.parametrize('operation', ['edit', 'delete', 'close'])
def test_poll_undo_preserves_votes_and_is_actor_bound(tmp_path, operation):
    from core.request_context import RequestContext, request_scope
    from features.poll_manager import PollManager
    from utils.local_undo import undo_change, undo_hint
    manager = PollManager(tmp_path / 'poll-undo.json')
    actor = RequestContext('test', '7', '123', '123', 'no', channel_kind='guild')
    try:
        with request_scope(actor):
            poll = manager.create_poll(123, 'Pick?', ['A', 'B'], 'Synthetic', 7)
            manager.vote(123, poll['id'], 2, 9, 'Voter')
            if operation == 'edit':
                manager.edit_poll(123, poll['id'], 7, question='Changed?')
            elif operation == 'delete':
                manager.delete_poll(123, poll['id'], 7)
            else:
                manager.close_poll(123, poll['id'], 7)
            hint = undo_hint(manager, actor)
            assert hint is not None
            token = hint['token']
            outsider = RequestContext('test', '9', '123', '123', 'no', channel_kind='guild')
            with pytest.raises(PermissionError):
                undo_change(manager, outsider, token)
            undo_change(manager, actor, token)
            restored = manager.get_poll(123, poll['id'])
            assert restored is not None
            assert restored['question'] == 'Pick?' and restored['status'] == 'active'
            assert restored['options'][1]['votes'] == ['9']
    finally:
        manager.close_storage()


async def test_opt_in_overdue_delivery_is_delayed_once_and_receipt_actions_work(tmp_path):
    import re
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cal_system.calendar_manager import CalendarManager
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    from core.request_context import RequestContext, request_scope
    from memory.user_memory import UserMemory
    from features.task_workspace import task_workspace
    now = {'value': datetime.fromisoformat('2027-01-01T08:00:00+00:00')}
    clock = Clock(wall=lambda: now['value'])
    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json', clock=clock)
    manager = ReminderManager(tmp_path / 'reminders.json', clock=clock)
    memory = UserMemory(tmp_path / 'memory.json')
    actor = RequestContext('test', '7', '70', '123', 'no', channel_kind='guild')
    with request_scope(actor):
        item_id = manager.add_reminder(123, 7, 'Synthetic', 'Due task', '01.01.2027 09:00', channel_id=70)
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', (0,), overdue_minutes=30))
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered', message_id='receipt')))
    checker = ReminderChecker(calendar_manager=calendar, reminder_manager=manager, user_memory=memory,
        get_channel_func=lambda _: SimpleNamespace(), outbound_sender=sender, storage_path=tmp_path / 'sent.json', clock=clock)
    try:
        await checker.setup()
        await checker.check_notification_profiles()
        await checker.check_notification_profiles()
        assert sender.send.await_count == 1
        assert 'Fullfør:' in sender.send.call_args.args[1]
        now['value'] = datetime.fromisoformat('2027-01-01T08:01:00+00:00')
        await checker.check_notification_profiles()
        assert sender.send.await_count == 1
        now['value'] = datetime.fromisoformat('2027-01-01T08:30:00+00:00')
        await checker.check_notification_profiles()
        await checker.check_notification_profiles()
        assert sender.send.await_count == 2
        assert 'Fristen er passert' in sender.send.call_args.args[1]
        match = re.search(r'ferdig påminnelse valg ([\w-]{12})', sender.send.call_args.args[1])
        assert match is not None
        service = task_workspace(SimpleNamespace(calendar=calendar, reminders=manager, user_memory=memory, poll=None))
        await service.reminder_action(actor, match.group(1), 'complete')
        assert manager.reminders['123'][0]['id'] == item_id
        assert manager.reminders['123'][0]['completed']
    finally:
        checker.close_storage()
        await calendar._storage.aclose()
        await calendar._outbox.slot.close()
        await manager._storage.aclose()
        await manager._outbox.slot.close()
        memory._storage.close()


async def test_direct_snooze_plan_matches_delivery_and_suppresses_due_alert(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cal_system.calendar_manager import CalendarManager
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    from core.request_context import RequestContext, request_scope
    from memory.user_memory import UserMemory
    from features.task_workspace import task_workspace
    now = {'value': datetime.fromisoformat('2027-01-01T08:00:00+00:00')}
    clock = Clock(wall=lambda: now['value'])
    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json', clock=clock)
    manager = ReminderManager(tmp_path / 'reminders.json', clock=clock)
    memory = UserMemory(tmp_path / 'memory.json')
    actor = RequestContext('test', '7', '70', '123', 'no', channel_kind='guild')
    with request_scope(actor):
        item_id = manager.add_reminder(123, 7, 'Synthetic', 'Snooze me', '01.01.2027 09:00', channel_id=70)
    service = task_workspace(SimpleNamespace(calendar=calendar, reminders=manager, user_memory=memory, poll=None))
    await service.reminder_action(actor, service.reminder_action_token(actor, item_id), 'snooze')
    assert service.items(actor)['reminders'][0]['plan']['next_at'] == '2027-01-01T08:10:00+00:00'
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered', message_id='receipt')))
    checker = ReminderChecker(calendar_manager=calendar, reminder_manager=manager, user_memory=memory,
        get_channel_func=lambda _: SimpleNamespace(), outbound_sender=sender, storage_path=tmp_path / 'sent.json', clock=clock)
    try:
        await checker.setup()
        await checker.check_notification_profiles()
        sender.send.assert_not_awaited()
        now['value'] = datetime.fromisoformat('2027-01-01T08:10:00+00:00')
        await checker.check_notification_profiles()
        await checker.check_notification_profiles()
        assert sender.send.await_count == 1
        assert 'Slumret:' in sender.send.call_args.args[1] and 'Fullfør:' in sender.send.call_args.args[1]
        assert memory.notification_snoozes('7', 'shared') == []
    finally:
        checker.close_storage()
        await calendar._storage.aclose()
        await calendar._outbox.slot.close()
        await manager._storage.aclose()
        await manager._outbox.slot.close()
        memory._storage.close()


async def test_poll_last_page_has_only_a_previous_link(tmp_path):
    from unittest.mock import AsyncMock
    from features.polls_handler import PollsHandler
    from tests.test_human_interactions import monitor, message
    from features.poll_manager import PollManager
    manager = PollManager(tmp_path / 'pages.json')
    try:
        for n in range(9):
            manager.create_poll(123, f'Question {n}?', ['A', 'B'], 'Synthetic', 555)
        handler = PollsHandler(monitor(poll=manager))
        handler.send_response = AsyncMock()
        await handler.handle_poll_list(message('polls side 2'))
        text = handler.send_response.call_args.args[1]
        assert 'Forrige:' in text and 'Neste:' not in text
    finally:
        manager.close_storage()


async def test_completion_during_delivery_wait_invalidates_scheduled_alert(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cal_system.calendar_manager import CalendarManager
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    from core.request_context import RequestContext, request_scope
    from memory.user_memory import UserMemory
    clock = Clock(wall=lambda: datetime.fromisoformat('2027-01-01T08:00:00+00:00'))
    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json', clock=clock)
    manager = ReminderManager(tmp_path / 'reminders.json', clock=clock)
    memory = UserMemory(tmp_path / 'memory.json')
    actor = RequestContext('test', '7', '70', '123', 'no', channel_kind='guild')
    with request_scope(actor):
        item_id = manager.add_reminder(123, 7, 'Synthetic', 'Already complete', '01.01.2027 09:00', channel_id=70)
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', (0,)))
    async def send(*args, **kwargs):
        with request_scope(actor):
            manager.complete_reminder(123, reminder_id=item_id)
        assert kwargs['_can_dispatch']() is False
        return DeliveryResult('dropped', reason_code='authorization_changed')
    checker = ReminderChecker(calendar_manager=calendar, reminder_manager=manager, user_memory=memory,
        get_channel_func=lambda _: SimpleNamespace(), outbound_sender=SimpleNamespace(send=AsyncMock(side_effect=send)),
        storage_path=tmp_path / 'sent.json', clock=clock)
    try:
        await checker.setup()
        await checker.check_notification_profiles()
        assert all(receipt['status'] == 'dropped' for receipt in checker.sent_log['deliveries'].values())
    finally:
        checker.close_storage()
        await calendar._storage.aclose()
        await calendar._outbox.slot.close()
        await manager._storage.aclose()
        await manager._outbox.slot.close()
        memory._storage.close()
