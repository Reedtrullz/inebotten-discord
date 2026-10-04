"""Deliberate learning, provider filtering and bounded local retention."""
from datetime import datetime, timedelta, timezone
import pytest
from memory.user_memory import UserMemory
from memory.conversation_context import ConversationContext


@pytest.mark.asyncio
async def test_paused_learning_stores_no_topic_and_includes_no_prompt_memory(tmp_path):
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_location('u1', 'Trondheim')
    await memory.set_policy('u1', learning_enabled=False, allowed_provider_ids=['openrouter'], private_facts_enabled=True)
    await memory.update_last_interaction('u1', topic='Private conversation')
    assert await memory.build_prompt_memory('u1', 'openrouter', 'private:u1') == {}
    assert not memory.memory['u1']['last_topics']
    memory._storage.close()


@pytest.mark.asyncio
async def test_provider_and_scope_filter_are_applied_before_personalization(tmp_path):
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_location('u1', 'Trondheim')
    await memory.set_policy('u1', learning_enabled=True, allowed_provider_ids=['hermes'], private_facts_enabled=True)
    assert await memory.build_prompt_memory('u1', 'openrouter', 'private:u1') == {}
    private = await memory.build_prompt_memory('u1', 'hermes', 'private:u1')
    assert private['location'] == 'Trondheim'
    assert 'location' not in await memory.build_prompt_memory('u1', 'hermes', 'group:g')
    memory._storage.close()


@pytest.mark.asyncio
async def test_topic_expiry_preserves_explicit_facts_and_untimestamped_legacy_topics(tmp_path):
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    memory = UserMemory(tmp_path / 'memory.json', wall=lambda: now)
    await memory.set_location('u1', 'Oslo')
    await memory.set_policy('u1', learning_enabled=True, topic_retention_days=7, allowed_provider_ids=['hermes'])
    await memory.update_last_interaction('u1', topic='Fresh topic')
    with memory._storage.transaction():
        memory.memory['u1']['last_topics'] += ['Legacy unclassified']
        await memory._save_memory()
    now += timedelta(days=8)
    await memory.prune_topics()
    assert memory.memory['u1']['location'] == 'Oslo'
    assert memory.memory['u1']['last_topics'] == ['Legacy unclassified']
    assert 'Legacy unclassified' not in str(await memory.build_prompt_memory('u1', 'hermes', 'shared'))
    memory._storage.close()


def test_global_context_prune_removes_idle_channels_and_returns_copies():
    now = datetime(2026, 10, 4)
    context = ConversationContext(wall=lambda: now)
    context.add_message(1, 'u1', 'Name', 'Old')
    now += timedelta(hours=1)
    context.add_message(2, 'u2', 'Other', 'Fresh')
    assert 1 not in context.threads
    returned = context.get_channel_messages(2)
    returned[0]['content'] = 'Caller changed it'
    assert context.get_channel_messages(2)[0]['content'] == 'Fresh'


@pytest.mark.asyncio
async def test_self_delete_clears_all_own_transient_entries_and_preserves_others(tmp_path):
    context = ConversationContext()
    context.add_message(1, 'u1', 'One', 'Self')
    context.add_message(1, 'u2', 'Two', 'Other')
    context.add_message(2, None, 'Bot', 'Reply', is_bot=True, source_user_id='u1')
    memory = UserMemory(tmp_path / 'memory.json', conversation=context)
    await memory.set_location('u1', 'Oslo')
    await memory.set_location('u2', 'Trondheim')
    result = await memory.delete_local_memory('u1', include_transient=True)
    assert result['persistent_deleted'] and result['transient_deleted'] == 2
    assert 'u1' not in memory.memory and memory.memory['u2']['location'] == 'Trondheim'
    assert context.get_context(1) == 'Two: Other'
    assert context.get_context(2) == ''
    assert set(result['exclusions']) == {'backups', 'remote_providers', 'discord_messages'}
    memory._storage.close()


@pytest.mark.asyncio
async def test_router_fallback_cannot_receive_personalization_allowed_only_for_primary(tmp_path):
    from types import SimpleNamespace
    from core.message_monitor import MessageMonitor
    from core.request_context import RequestContext, request_scope
    memory = UserMemory(tmp_path / 'memory.json')
    context = ConversationContext()
    await memory.set_location('u1', 'Private place')
    await memory.set_policy('u1', learning_enabled=True, allowed_provider_ids=['openrouter'], private_facts_enabled=True)
    context.add_message(9, 'u1', 'One', 'Private history')
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.user_memory, monitor.conversation = memory, context
    monitor.hermes = SimpleNamespace(primary=SimpleNamespace(provider='openrouter'), fallback=SimpleNamespace(provider='hermes'))
    message = SimpleNamespace(author=SimpleNamespace(id='u1'))
    with request_scope(RequestContext('r', 'u1', '9', None, 'no', 'dm')):
        assert await monitor._provider_memory_context(message, 9) == ('', '')
    monitor.hermes = SimpleNamespace(provider='openrouter')
    with request_scope(RequestContext('r', 'u1', '9', None, 'no', 'dm')):
        facts, history = await monitor._provider_memory_context(message, 9)
    assert 'Private place' in facts and 'Private history' in history
    with request_scope(RequestContext('r', 'u1', '10', None, 'no', 'unknown')):
        facts, history = await monitor._provider_memory_context(message, 10)
    assert 'Private place' not in facts and history == ''
    memory._storage.close()


@pytest.mark.asyncio
async def test_memory_handler_deletion_reports_actual_local_surfaces_and_exclusions(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from features.memory_handler import MemoryHandler
    from memory.localization import Localization
    context = ConversationContext()
    context.add_message(9, 'u1', 'One', 'Remove this')
    memory = UserMemory(tmp_path / 'memory.json', conversation=context)
    await memory.set_location('u1', 'Oslo')
    handler = MemoryHandler(SimpleNamespace(user_memory=memory, rate_limiter=None, loc=Localization(), client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(author=SimpleNamespace(id='u1'))
    await handler.handle_memory(message, {'action': 'delete', 'confirmed': True})
    text = handler.send_response.await_args.args[1]
    assert 'midlertidige egne meldinger/svar: 1' in text
    assert 'sikkerhetskopier' in text and 'tidligere data hos AI-providere' in text
    assert context.get_context(9) == ''
    memory._storage.close()


def test_memory_controls_route_only_exact_commands_and_never_another_user():
    from types import SimpleNamespace
    from core.intent_router import IntentRouter
    router = IntentRouter(SimpleNamespace())
    for command, changes in [('minne læring av', {'learning_enabled': False}),
        ('minne del med lokal', {'allowed_provider_ids': ['hermes']}),
        ('minne behold tema 7 dager', {'topic_retention_days': 7})]:
        assert router._route_memory_command(command).payload['memory']['changes'] == changes
    assert router._route_memory_command('minne læring av for u2') is None


@pytest.mark.asyncio
async def test_actual_ai_dispatch_does_not_include_disallowed_personalization(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from core.message_monitor import MessageMonitor
    from ai.result_schema import AIResult
    from core.request_context import RequestContext, request_scope
    from tests.test_ai_outcomes import FakeMessage
    import ai.personality
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_location('7', 'PRIVATE_SAVED_LOCATION')
    await memory.set_policy('7', learning_enabled=True, allowed_provider_ids=['hermes'], private_facts_enabled=True)
    context = ConversationContext()
    context.add_message(100, '7', 'Tester', 'PRIVATE_RETAINED_HISTORY')
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.user_memory, monitor.conversation = memory, context
    captured = []

    async def provider(actor, prompt, *, deadline):
        captured.append(prompt)
        return AIResult('unavailable', None, 'openrouter', None)

    monitor.hermes = SimpleNamespace(provider='openrouter', generate_reply=provider)
    monitor.ResponseStyle = SimpleNamespace(CASUAL='casual')
    monitor.get_system_prompt = lambda **kwargs: str(kwargs)
    monitor.detect_search_intent = lambda _content: None
    monitor._send_response = AsyncMock()
    monkeypatch.setattr(ai.personality, 'get_personality', lambda: SimpleNamespace(respond_to_dialect=lambda _: None))
    message = FakeMessage('@inebotten forklar sorte hull')
    with request_scope(RequestContext('r', '7', str(message.channel.id), None, 'no', 'dm')):
        await monitor._send_ai_response(message)
    assert len(captured) == 1
    assert 'PRIVATE_' not in captured[0]
    assert 'forklar sorte hull' in captured[0]
    memory._storage.close()


@pytest.mark.asyncio
async def test_failed_persistent_delete_preserves_transient_entries(tmp_path, monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    context = ConversationContext()
    context.add_message(1, 'u1', 'One', 'Still retained until local commit succeeds')
    memory = UserMemory(tmp_path / 'memory.json', conversation=context)
    await memory.set_location('u1', 'Oslo')
    monkeypatch.setattr(memory._storage, 'commit', lambda *_a, **_kw: StorageCommit(False, 'write_failed'))
    with pytest.raises(StorageMutationError):
        await memory.delete_local_memory('u1', include_transient=True)
    assert memory.memory['u1']['location'] == 'Oslo'
    assert context.get_channel_messages(1)[0]['user_id'] == 'u1'
    memory._storage.close()


@pytest.mark.asyncio
async def test_saved_school_locality_is_used_only_in_verified_direct_messages(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from features.school_holidays_handler import SchoolHolidaysHandler
    from core.request_context import RequestContext, request_scope
    from memory.localization import Localization
    from tests.test_school_calendar_coverage import _freeze_today
    from datetime import date
    _freeze_today(monkeypatch, date(2026, 10, 4))
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_saved_fact('u1', 'school_locality', 'oslo')
    handler = SchoolHolidaysHandler(SimpleNamespace(user_memory=memory, rate_limiter=None, loc=Localization(), client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(content='skoleferie', author=SimpleNamespace(id='u1'))
    with request_scope(RequestContext('r', 'u1', '9', None, 'no', 'dm')):
        await handler.handle_school_holidays(message)
    assert 'Skoleferier – Oslo' in handler.send_response.await_args.args[1]
    with request_scope(RequestContext('r', 'u1', '10', 'guild', 'no', 'guild')):
        await handler.handle_school_holidays(message)
    assert 'Velg kommune' in handler.send_response.await_args.args[1]
    memory._storage.close()


@pytest.mark.asyncio
async def test_policy_revoked_while_prompt_is_prepared_drops_stale_facts(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.message_monitor import MessageMonitor
    from core.request_context import RequestContext, request_scope
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_location('u1', 'PRIVATE_PLACE')
    await memory.set_policy('u1', learning_enabled=True, allowed_provider_ids=['hermes', 'openrouter'], private_facts_enabled=True)
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.user_memory, monitor.conversation = memory, ConversationContext()
    monitor.hermes = SimpleNamespace(primary=SimpleNamespace(provider='openrouter'), fallback=SimpleNamespace(provider='hermes'))
    original = memory.build_prompt_memory

    async def revoke_between_routes(user_id, provider_id, scope_id):
        result = await original(user_id, provider_id, scope_id)
        if provider_id == 'openrouter':
            await memory.set_policy(user_id, private_facts_enabled=False)
        return result

    monkeypatch.setattr(memory, 'build_prompt_memory', revoke_between_routes)
    with request_scope(RequestContext('r', 'u1', '9', None, 'no', 'dm')):
        facts, _ = await monitor._provider_memory_context(SimpleNamespace(author=SimpleNamespace(id='u1')), 9)
    assert 'PRIVATE_PLACE' not in facts
    memory._storage.close()
