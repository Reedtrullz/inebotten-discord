"""Catalogue parity and inert previews, using synthetic routing state."""
import copy
from types import SimpleNamespace

import pytest

from core.command_registry import COMMANDS, command_metadata, preview_route, validate_payload, command_reference
from core.intent_router import BotIntent, IntentRouter, IntentResult
from core.request_context import RequestContext, current_request
from tests.test_intent_router import DummyMonitor


def actor(kind='dm'):
    return RequestContext('preview', '7', '100', None, 'no', kind)


def test_every_intent_has_one_typed_binding_and_copy_safe_metadata():
    assert {s.intent for s in COMMANDS} == set(BotIntent)
    assert len(COMMANDS) == len(BotIntent)
    assert all(s.handler_name and s.examples and s.description and callable(s.payload_validator) for s in COMMANDS)
    first = command_metadata()
    first[0]['examples'].clear()
    assert command_metadata()[0]['examples']
    doc = command_reference()
    for spec in COMMANDS:
        assert spec.intent.value in doc
        assert all(example.replace('|', r'\|') in doc for example in spec.examples)


@pytest.mark.parametrize('intent,payload', [
    (BotIntent.POLL_VOTE, {'vote': 0}),
    (BotIntent.POLL_VOTE, {'vote': '1'}),
    (BotIntent.CALENDAR_ITEM, {'calendar_item': {'title': ['wrong']}}),
    (BotIntent.SEARCH, {'search': {'query': 9}}),
    (BotIntent.MEMORY_DELETE, {'memory': {'action': 'delete', 'user_id': 'someone'}}),
    (BotIntent.MEMORY_VIEW, {'memory': {'action': 'policy', 'changes': {'learning_enabled': 'yes'}}}),
    (BotIntent.SET_LOCATION, {'city': ''}),
    (BotIntent.CALENDAR_AUTH, {'auth_code': 99}),
    (BotIntent.HELP, {'handler_name': 'destroy'}),
])
def test_payload_rejection(intent, payload):
    with pytest.raises(ValueError):
        validate_payload(intent, payload)


def test_preview_reuses_router_precedence_without_provider_store_or_dispatch():
    monitor = DummyMonitor(active_polls=True, active_reminders=True)
    monitor.client = SimpleNamespace(config=SimpleNamespace(ALLOWED_USERS=[], ALLOWED_CHANNELS=[]))
    monitor.handlers = SimpleNamespace(__getattr__=lambda *_: pytest.fail('dispatched'))
    monitor.intent_stats = {'untouched': 5}
    monitor.search_manager = SimpleNamespace(search=lambda *_: pytest.fail('provider called'))
    before = copy.deepcopy(monitor.intent_stats)
    router = IntentRouter(monitor)
    for text in ('1', 'bot status', 'vis minnet mitt', 'søk på nett Oslo', 'hva skjer?', 'hjelp kalender'):
        expected = router.route(text, guild_id='100')
        result = preview_route(router, text, actor())
        assert result['intent'] == expected.intent.value
        assert result['confidence'] == expected.confidence
        assert result['reason'] == expected.reason
        assert result['dispatched'] is False
        assert result['required_policy']['mention_gate_required']
    assert monitor.intent_stats == before
    assert current_request() is None


def test_preview_threshold_invalid_payload_and_auth_code_redaction():
    router = IntentRouter(DummyMonitor())
    router.route = lambda *a, **kw: IntentResult(BotIntent.CALENDAR_ITEM, .86, {'calendar_item': {'title': 'A'}})
    result = preview_route(router, 'synthetic', actor())
    assert not result['accepted'] and result['validation'] == 'valid'
    router.route = lambda *a, **kw: IntentResult(BotIntent.POLL_VOTE, 1.0, {'vote': -1})
    result = preview_route(router, 'synthetic', actor())
    assert not result['accepted'] and result['validation'] == 'invalid_payload'
    assert result['fields'] == {}
    router.route = lambda *a, **kw: IntentResult(BotIntent.CALENDAR_AUTH, 1.0, {'auth_code': 'synthetic-secret'})
    result = preview_route(router, 'synthetic', actor())
    assert result['fields'] == {'auth_code': '[skjult]'}
    assert 'synthetic-secret' not in repr(result)


def test_preview_requires_actor_and_bounded_text():
    router = IntentRouter(DummyMonitor())
    for text, identity in [('test', None), ('x' * 4001, actor())]:
        with pytest.raises(ValueError):
            preview_route(router, text, identity)


def test_help_pages_cover_same_catalogue_and_are_bounded():
    from core.command_registry import command_help_pages
    pages = command_help_pages()
    text = '\n'.join(pages)
    assert all(len(page) <= 1700 for page in pages)
    for spec in COMMANDS:
        assert spec.examples[0] in text
        assert spec.description in text


@pytest.mark.asyncio
async def test_dispatch_uses_curated_binding_and_rejects_invalid_before_handler():
    from core.command_registry import dispatch_command
    from unittest.mock import AsyncMock
    status = AsyncMock()
    vote = AsyncMock()
    monitor = SimpleNamespace(_send_status_response=status, handlers={'polls': SimpleNamespace(handle_vote=vote)})
    message = object()
    await dispatch_command(monitor, message, IntentResult(BotIntent.STATUS, 1.0))
    status.assert_awaited_once_with(message)
    await dispatch_command(monitor, message, IntentResult(BotIntent.POLL_VOTE, 1.0, {'vote': 2}))
    vote.assert_awaited_once_with(message, 2)
    with pytest.raises(ValueError):
        await dispatch_command(monitor, message, IntentResult(BotIntent.POLL_VOTE, 1.0, {'vote': 0}))
    assert vote.await_count == 1


def test_router_public_preview_method_is_same_inert_contract():
    router = IntentRouter(DummyMonitor())
    assert router.preview_route('bot status', actor()) == preview_route(router, 'bot status', actor())


def test_console_reference_uses_the_complete_shared_catalogue():
    from html import escape
    from web_console.dashboard import render_commands_page
    html = render_commands_page()
    for spec in COMMANDS:
        assert escape(spec.examples[0]) in html
        assert escape(spec.description) in html


@pytest.mark.asyncio
async def test_monitor_rejects_invalid_payload_without_handler_or_ai_fallback():
    from core.message_monitor import MessageMonitor
    from unittest.mock import AsyncMock
    monitor = MessageMonitor.__new__(MessageMonitor)
    vote = AsyncMock()
    monitor.handlers = {'polls': SimpleNamespace(handle_vote=vote)}
    monitor._send_ai_response = AsyncMock()
    monitor._send_response = AsyncMock()
    await monitor._handle_intent(object(), IntentResult(BotIntent.POLL_VOTE, 1.0, {'vote': 0}))
    vote.assert_not_awaited()
    monitor._send_ai_response.assert_not_awaited()
    monitor._send_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_help_delivers_all_catalogue_pages_and_no_handwritten_parallel_list():
    from features.help_handler import HelpHandler
    from core.command_registry import command_help_pages
    from unittest.mock import AsyncMock
    handler = HelpHandler.__new__(HelpHandler)
    handler.send_response = AsyncMock()
    message = object()
    await handler.handle_help(message)
    assert tuple(c.args[1] for c in handler.send_response.await_args_list) == command_help_pages()


@pytest.mark.asyncio
async def test_real_store_preview_leaves_files_revisions_and_policy_unchanged(tmp_path):
    from datetime import datetime, timedelta
    from cal_system.calendar_manager import CalendarManager
    from cal_system.reminder_manager import ReminderManager
    from features.poll_manager import PollManager
    from memory.user_memory import UserMemory
    calendar = CalendarManager(tmp_path / 'calendar.json')
    reminders = ReminderManager(tmp_path / 'reminders.json')
    polls = PollManager(tmp_path / 'polls.json')
    memory = UserMemory(tmp_path / 'user_memory.json')
    owners = (calendar._storage, reminders._storage, polls._storage, memory._storage)
    try:
        calendar.add_item('shared', '7', 'Tester', 'Synthetic',
                          (datetime.now() + timedelta(days=1)).strftime('%d.%m.%Y'))
        reminders.add_reminder('100', '7', 'Tester', 'Synthetic')
        polls.create_poll('100', 'Synthetic?', ['A', 'B'], 'Tester', created_by_id='7')
        await memory.set_location('7', 'Oslo')
        monitor = DummyMonitor()
        monitor.calendar, monitor.reminders, monitor.poll, monitor.user_memory = calendar, reminders, polls, memory
        router = IntentRouter(monitor)
        before = tuple((owner.revision, owner.path.read_bytes()) for owner in owners)
        for text in ('slett Synthetic', 'ferdig påminnelse 1', '1', 'minne læring på', 'slett minnet mitt bekreft'):
            result = router.preview_route(text, actor())
            assert not result['dispatched']
        assert tuple((owner.revision, owner.path.read_bytes()) for owner in owners) == before
        assert memory.policy_for_user('7').learning_enabled is False
    finally:
        for owner in owners:
            owner.close()


@pytest.mark.asyncio
async def test_help_stops_after_failed_delivery():
    from features.help_handler import HelpHandler
    from unittest.mock import AsyncMock
    handler = HelpHandler.__new__(HelpHandler)
    handler.send_response = AsyncMock(return_value=None)
    await handler.handle_help(object())
    assert handler.send_response.await_count == 1


def test_catalogue_bindings_exist_on_actual_registered_handler_classes():
    import ast
    import importlib
    import inspect
    import textwrap
    from core.message_monitor import MessageMonitor
    tree = ast.parse(textwrap.dedent(inspect.getsource(MessageMonitor._register_handlers)))
    imports = {a.asname or a.name: (node.module, a.name)
               for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for a in node.names}
    assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                      and isinstance(node.value, ast.Dict))
    classes = {}
    for key, value in zip(assignment.value.keys, assignment.value.values):
        if isinstance(value.func, ast.Name):
            module, name = imports[value.func.id]
            classes[key.value] = getattr(importlib.import_module(module), name)
    for spec in COMMANDS:
        if spec.handler_name.startswith('_'):
            target = getattr(MessageMonitor, spec.handler_name)
        else:
            owner, name = spec.handler_name.split('.', 1)
            target = getattr(classes[owner], name)
        assert inspect.iscoroutinefunction(target), spec.intent.value
