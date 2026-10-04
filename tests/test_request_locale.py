"""A locale belongs to one invocation, across awaits and handler reuse."""
import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core.intent_router import BotIntent
from features.base_handler import BaseHandler
from memory.localization import Localization
from tests import test_mention_gate


@pytest.mark.asyncio
async def test_interleaved_norwegian_english_keep_locale():
    monitor = test_mention_gate.MentionGateTests().make_monitor()
    monitor.loc = Localization()
    handler = BaseHandler(monitor)
    barrier = asyncio.Event()
    english_started = asyncio.Event()
    responses = {}
    class Handler:
        async def handle_help(self, message):
            if message.author.id == 7:
                barrier.set()
                await english_started.wait()
            else:
                await barrier.wait()
                english_started.set()
            await asyncio.sleep(0)
            responses[message.author.id] = handler.loc.t('no_events')
    monitor.handlers['help'] = Handler()
    monitor.intent_router = SimpleNamespace(route=lambda *_a, **_kw: SimpleNamespace(
        intent=BotIntent.HELP, payload={}, reason='test', confidence=1))
    norwegian = test_mention_gate.MentionGateTests().make_message('@inebotten hva hjelp', message_id=1)
    english = test_mention_gate.MentionGateTests().make_message('@inebotten what help', message_id=2)
    english.author = SimpleNamespace(id=8, name='Tester')
    await asyncio.gather(monitor.handle_message(norwegian), monitor.handle_message(english))
    assert responses[7] == '*Ingen kommende arrangementer*'
    assert responses[8] == '*No upcoming events*'
    assert monitor.loc.current_lang == 'no'


def test_translation_view_is_immutable_and_does_not_change_default():
    loc = Localization()
    view = loc.for_language('en')
    assert view.t('no_events') == '*No upcoming events*'
    assert loc.current_lang == 'no'
    with pytest.raises((FrozenInstanceError, AttributeError)):
        view.current_lang = 'no'
    with pytest.raises(TypeError):
        view.translations['no_events']['en'] = 'mutated'


@pytest.mark.asyncio
async def test_nested_scope_restores_parent_after_failure():
    from core.request_context import RequestContext, request_scope, current_request
    outer = RequestContext('outer', 'u', 'c', None, 'no')
    inner = RequestContext('inner', 'v', 'd', 'g', 'en')
    assert current_request() is None
    with request_scope(outer):
        with pytest.raises(RuntimeError):
            with request_scope(inner):
                await asyncio.sleep(0)
                assert current_request() == inner
                raise RuntimeError('synthetic')
        assert current_request() == outer
    assert current_request() is None


def test_translation_helper_does_not_mutate_shared_locale(monkeypatch):
    from memory import localization
    loc = Localization()
    monkeypatch.setattr(localization, '_localization', loc)
    monkeypatch.setattr(loc, 'set_language', lambda _: pytest.fail('shared locale changed'))
    assert localization.t('no_events', lang='en') == '*No upcoming events*'
    assert loc.current_lang == 'no'
