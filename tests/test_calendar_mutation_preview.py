"""Exact calendar identity, revision, actor and inverse-commit contracts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.calendar_manager import CalendarManager
from core.access_policy import AccessPolicy, ScopeRecord
from core.request_context import RequestContext, request_scope
from features.calendar_handler import CalendarHandler


@pytest.fixture
def actor():
    return RequestContext('r', '7', '9', None, 'no', 'dm')


@pytest.fixture
def manager(tmp_path):
    m = CalendarManager(tmp_path / 'calendar.json')
    yield m
    m._storage.close()


def add(manager, title='Møte', days=1, **kw):
    return manager.add_item('shared', '7', 'Tester', title,
        (datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y'), **kw)


def preview(manager, actor, items, operation='delete', **kw):
    return manager.preview_mutation(actor, 'shared', [i['id'] for i in items],
        operation, manager._storage.revision, **kw)


@pytest.mark.asyncio
async def test_equal_count_replacement_refuses_wrong_set(manager, actor):
    first = add(manager)
    proposal = preview(manager, actor, [first], 'clear')
    await manager.clear_calendar('shared')
    replacement = add(manager, 'Annet')
    with pytest.raises(ValueError, match='revision|changed'):
        await manager.apply_preview(actor, proposal.token)
    assert manager.get_upcoming('shared')[0]['id'] == replacement['id']


@pytest.mark.asyncio
async def test_preview_cannot_be_replayed_by_another_actor(manager, actor):
    proposal = preview(manager, actor, [add(manager)])
    outsider = RequestContext('r2', '8', '9', None, 'no', 'dm')
    with pytest.raises(PermissionError):
        await manager.apply_preview(outsider, proposal.token)
    assert len(manager.get_upcoming('shared')) == 1


@pytest.mark.asyncio
async def test_revoked_permission_is_checked_again_on_apply(manager, actor):
    manager.access_policy = AccessPolicy([ScopeRecord('group:test', 'approved_group',
        owner_id='8', collaborator_ids={'7'}, channel_ids={'9'})], default_scope='group:test')
    with request_scope(actor):
        item = add(manager)
        proposal = manager.preview_mutation(actor, 'group:test', [item['id']], 'delete', manager._storage.revision)
    manager.access_policy = AccessPolicy([ScopeRecord('group:test', 'approved_group',
        owner_id='8', channel_ids={'9'})], default_scope='group:test')
    with pytest.raises(PermissionError):
        await manager.apply_preview(actor, proposal.token)


@pytest.mark.asyncio
async def test_expired_preview_and_modified_public_effects_do_not_change_target(manager, actor):
    item = add(manager)
    proposal = preview(manager, actor, [item])
    proposal.effects[0]['item_id'] = 'forged'
    manager.clock = SimpleNamespace(now=lambda: datetime.now(timezone.utc) + timedelta(minutes=10),
        monotonic=lambda: 10**12)
    with pytest.raises(ValueError, match='expired'):
        await manager.apply_preview(actor, proposal.token)
    assert manager.get_upcoming('shared')[0]['id'] == item['id']


@pytest.mark.asyncio
async def test_local_inverse_survives_restart_and_is_one_use(manager, actor):
    item = add(manager)
    applied = await manager.apply_preview(actor, preview(manager, actor, [item]).token)
    assert manager.get_upcoming('shared') == []
    manager._storage.close()
    restarted = CalendarManager(manager.storage_path)
    try:
        await restarted.undo_mutation(actor, applied['undo_token'])
        assert restarted.get_upcoming('shared')[0]['id'] == item['id']
        with pytest.raises(ValueError):
            await restarted.undo_mutation(actor, applied['undo_token'])
    finally:
        restarted._storage.close()


@pytest.mark.asyncio
async def test_linked_delete_is_local_first_and_undo_does_not_promise_remote_identity(manager, actor):
    manager.gcal = SimpleNamespace(delete_event=AsyncMock())
    manager.gcal_enabled = True
    item = add(manager, gcal_event_id='external-1')
    applied = await manager.apply_preview(actor, preview(manager, actor, [item]).token)
    manager.gcal.delete_event.assert_not_called()
    assert applied['remote_pending']
    undone = await manager.undo_mutation(actor, applied['undo_token'])
    assert undone['remote_limitations']
    assert not manager.get_upcoming('shared')[0].get('gcal_event_id')


@pytest.mark.asyncio
async def test_failed_inverse_commit_preserves_deleted_snapshot(manager, actor, monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    item = add(manager)
    applied = await manager.apply_preview(actor, preview(manager, actor, [item]).token)
    monkeypatch.setattr(manager._storage, 'commit', lambda *_a, **_kw: StorageCommit(False, 'write_failed'))
    with pytest.raises(StorageMutationError):
        await manager.undo_mutation(actor, applied['undo_token'])
    assert manager.get_upcoming('shared') == []


def handler(manager):
    monitor = SimpleNamespace(calendar=manager, nlp_parser=None, loc=None,
        client=None, rate_limiter=None)
    result = CalendarHandler(monitor)
    result.send_response = AsyncMock()
    return result


def message(content):
    return SimpleNamespace(content=content, author=SimpleNamespace(id=7, name='Tester'),
        channel=SimpleNamespace(id=9), guild=None)


@pytest.mark.asyncio
async def test_displayed_index_does_not_follow_reordering(manager, actor):
    first = add(manager, 'Første', 2)
    h = handler(manager)
    with request_scope(actor):
        await h.handle_list(message('@inebotten kalender'))
        add(manager, 'Ny første', 1)
        await h.handle_delete(message('@inebotten slett 1'))
    assert any(i['id'] == first['id'] for i in manager.get_upcoming('shared'))
    assert 'endret' in h.send_response.await_args.args[1].lower()


@pytest.mark.asyncio
async def test_duplicate_titles_offer_stable_ids_without_mutation(manager, actor):
    first, second = add(manager), add(manager)
    h = handler(manager)
    with request_scope(actor):
        await h.handle_delete(message('@inebotten slett Møte'))
    text = h.send_response.await_args.args[1]
    assert first['id'][:8] in text and second['id'][:8] in text
    assert len(manager.get_upcoming('shared')) == 2


@pytest.mark.asyncio
async def test_expired_undo_refuses_without_restoring(manager, actor):
    applied = await manager.apply_preview(actor, preview(manager, actor, [add(manager)]).token)
    manager.clock = SimpleNamespace(now=lambda: datetime.now(timezone.utc) + timedelta(days=2),
        monotonic=lambda: 10**12)
    with pytest.raises(ValueError, match='expired'):
        await manager.undo_mutation(actor, applied['undo_token'])
    assert manager.get_upcoming('shared') == []


@pytest.mark.asyncio
async def test_public_preview_is_a_copy_and_forward_failure_keeps_token_usable(manager, actor, monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    item = add(manager)
    proposal = preview(manager, actor, [item], 'edit', changes={'title': 'Nytt'})
    proposal.effects[0]['after']['title'] = 'forged'
    commit = manager._storage.commit
    monkeypatch.setattr(manager._storage, 'commit', lambda *_a, **_kw: StorageCommit(False, 'write_failed'))
    with pytest.raises(StorageMutationError):
        await manager.apply_preview(actor, proposal.token)
    assert manager.get_upcoming('shared')[0]['title'] == 'Møte'
    monkeypatch.setattr(manager._storage, 'commit', commit)
    result = await manager.apply_preview(actor, proposal.token)
    assert manager.get_upcoming('shared')[0]['title'] == 'Nytt'
    await manager.undo_mutation(actor, result['undo_token'])
    assert manager.get_upcoming('shared')[0]['title'] == 'Møte'


@pytest.mark.asyncio
async def test_completed_entry_can_be_restored_and_undo_checks_actor(manager, actor):
    item = add(manager)
    applied = await manager.apply_preview(actor, preview(manager, actor, [item], 'complete').token)
    outsider = RequestContext('r2', '8', '9', None, 'no', 'dm')
    with pytest.raises(PermissionError):
        await manager.undo_mutation(outsider, applied['undo_token'])
    await manager.undo_mutation(actor, applied['undo_token'])
    assert manager.get_upcoming('shared')[0]['id'] == item['id']


@pytest.mark.asyncio
async def test_expired_inverse_is_physically_pruned_but_pending_remote_intent_remains(manager, actor):
    first = add(manager)
    linked = add(manager, 'Google', gcal_event_id='external')
    await manager.apply_preview(actor, preview(manager, actor, [first, linked]).token)
    from cal_system.event_schema import Clock
    manager.clock = Clock(wall=lambda: datetime.now(timezone.utc) + timedelta(days=2))
    await manager.prune_mutation_history()
    assert [item['id'] for item in manager.items['shared']] == [linked['id']]
    assert '_undo_record' not in manager.items['shared'][0]
    assert manager.items['shared'][0]['_local_sync_pending'] == 'delete'


def test_malformed_inverse_metadata_degrades_storage_without_rewriting(tmp_path):
    import json
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps({'shared': [{'id': 'i', 'title': 'Møte', '_undo_record': 'bad'}]}))
    original = path.read_bytes()
    bad = CalendarManager(path)
    assert bad.storage_state.status == 'corrupt'
    assert path.read_bytes() == original
    bad._storage.close()


def test_versioned_snapshot_is_one_publication_even_if_a_legacy_read_yields(tmp_path, monkeypatch):
    from utils.storage_contract import VersionedJsonStore
    store = VersionedJsonStore(tmp_path / 'snapshot.json', lambda d: isinstance(d, dict))
    store.owner.commit({'generation': 1})
    rollback = store.owner.rollback

    def interleaved_read():
        store.owner.commit({'generation': 2})
        return rollback()

    monkeypatch.setattr(store.owner, 'rollback', interleaved_read)
    revision, document = store.snapshot()
    assert revision == document['generation']
    store.close()


@pytest.mark.asyncio
async def test_confirmation_and_undo_route_to_domain_handler(manager, actor):
    from core.intent_router import BotIntent, IntentRouter
    from tests.test_message_monitor_routing import MessageMonitorRoutingTests
    monitor = MessageMonitorRoutingTests().make_monitor()
    router = IntentRouter(monitor)
    for command in ('bekreft', 'angre'):
        assert router.route(f'@inebotten {command} kalender ' + 'a' * 32, None).intent == BotIntent.CALENDAR_CLEAR


@pytest.mark.asyncio
async def test_missing_explicit_id_never_falls_back_to_a_title(manager, actor):
    add(manager, 'deadbeef')
    h = handler(manager)
    with request_scope(actor):
        await h.handle_delete(message('@inebotten slett #deadbeef'))
    assert 'bekreft kalender' not in h.send_response.await_args.args[1]
    assert not manager._previews.entries


@pytest.mark.asyncio
async def test_revision_change_between_selection_and_preview_refuses(manager, actor, monkeypatch):
    add(manager, 'Møte')
    h = handler(manager)
    original = manager.get_upcoming

    def interleaved_read(*args, **kwargs):
        items = original(*args, **kwargs)
        manager.edit_item_by_id(items[0]['id'], title='Endret etter valg')
        return items

    monkeypatch.setattr(manager, 'get_upcoming', interleaved_read)
    with request_scope(actor):
        await h.handle_delete(message('@inebotten slett Møte'))
    assert 'bekreft kalender' not in h.send_response.await_args.args[1]
    assert not manager._previews.entries


@pytest.mark.asyncio
async def test_confirmation_preserves_a_token_ending_in_punctuation(manager, actor, monkeypatch):
    token = 'a' * 23 + '-'
    monkeypatch.setattr('cal_system.mutation_preview.secrets.token_urlsafe', lambda _: token)
    h = handler(manager)
    with request_scope(actor):
        add(manager)
        await h.handle_clear(message('@inebotten tøm kalender'))
        await h.handle_clear(message('@inebotten bekreft kalender ' + token))
    assert manager.get_upcoming('shared') == []
