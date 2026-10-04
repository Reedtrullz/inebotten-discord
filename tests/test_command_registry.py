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
        assert all(example in doc for example in spec.examples)


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
