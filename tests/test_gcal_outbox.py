"""Durable external intent with synthetic provider acceptance and failure evidence."""
import asyncio
import copy
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.event_schema import Clock
from cal_system.google_calendar_manager import EventLookup
from core.request_context import RequestContext, request_scope


def actor():
    return RequestContext('r', '7', '9', None, 'no', 'dm')


def add(manager, **kw):
    return manager.add_item('shared', '7', 'Tester', 'Møte',
        (datetime.now() + timedelta(days=1)).strftime('%d.%m.%Y'), **kw)


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.remote = {}
        self.fail = None

    def is_configured(self):
        return True

    def list_upcoming_events(self, days=90):
        return list(self.remote.values())

    def get_event_outcome(self, event_id):
        if event_id not in self.remote:
            return EventLookup('unavailable', reason_code='ambiguous_404')
        return EventLookup.from_event(event_id, copy.deepcopy(self.remote[event_id]))

    def apply_sync_operation(self, operation):
        from cal_system.sync_outbox import RemoteMutation
        self.calls.append(copy.deepcopy(operation))
        if self.fail:
            return self.fail
        if operation.kind == 'delete':
            self.remote[operation.remote_id] = {'id': operation.remote_id, 'status': 'cancelled'}
            return RemoteMutation('acknowledged')
        event = {**copy.deepcopy(self.remote.get(operation.remote_id, {})), 'id': operation.remote_id, **copy.deepcopy(operation.payload), 'etag': f'etag-{len(self.calls)}'}
        event.setdefault('extendedProperties', {}).setdefault('private', {})['inebotten_operation_id'] = operation.operation_id
        self.remote[event['id']] = event
        return RemoteMutation('acknowledged', event)


@pytest.fixture
def manager(tmp_path):
    result = CalendarManager(tmp_path / 'calendar.json', gcal_manager=FakeProvider())
    yield result
    result._storage.close()


def operation(manager, item_id):
    return next(i for i in manager.items['shared'] if i['id'] == item_id)['sync_operations'][-1]


@pytest.mark.asyncio
async def test_local_create_and_intent_are_one_commit_before_remote_io(manager):
    item = add(manager)
    stored = json.loads(manager.storage_path.read_text())['document']['shared'][0]
    assert stored['id'] == item['id']
    assert stored['sync_operations'][0]['state'] == 'pending'
    assert manager.gcal.calls == []
    results = await manager.process_due(deadline=time.monotonic() + 2)
    assert results[0].state == 'synced'
    assert operation(manager, item['id'])['state'] == 'synced'


@pytest.mark.asyncio
async def test_failed_commit_prevents_create_and_preserves_local_before_image(manager, monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    monkeypatch.setattr(manager._storage, 'commit', lambda *_a, **_kw: StorageCommit(False, 'write_failed'))
    with pytest.raises(StorageMutationError):
        add(manager)
    assert manager.gcal.calls == []
    assert manager.items == {}


@pytest.mark.asyncio
async def test_crash_after_remote_acceptance_reconciles_exact_operation_without_recreate(manager, monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    item = add(manager)
    commit = manager._storage.commit
    calls = 0

    def fail_receipt(document, **kw):
        nonlocal calls
        calls += 1
        return commit(document, **kw) if calls == 1 else StorageCommit(False, 'write_failed')

    monkeypatch.setattr(manager._storage, 'commit', fail_receipt)
    with pytest.raises(StorageMutationError):
        await manager.process_due(deadline=time.monotonic() + 2)
    assert len(manager.gcal.calls) == 1
    assert operation(manager, item['id'])['state'] == 'unknown'
    manager._storage.close()
    restarted = CalendarManager(manager.storage_path, gcal_manager=manager.gcal)
    try:
        results = await restarted.process_due(deadline=time.monotonic() + 2)
        assert results[0].state == 'synced'
        assert len(manager.gcal.calls) == 1
    finally:
        restarted._storage.close()


@pytest.mark.asyncio
async def test_ambiguous_create_is_not_blindly_repeated(manager):
    from cal_system.sync_outbox import RemoteMutation
    manager.gcal.fail = RemoteMutation('unknown', reason_code='transport_lost')
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    await manager.process_due(deadline=time.monotonic() + 2)
    assert len(manager.gcal.calls) == 1
    assert operation(manager, item['id'])['state'] == 'unknown'


@pytest.mark.asyncio
async def test_slow_sync_keeps_heartbeat_and_blocks_second_provider_call(manager):
    entered, release = threading.Event(), threading.Event()
    real = manager.gcal.apply_sync_operation

    def slow(op):
        entered.set()
        assert release.wait(5)
        return real(op)

    manager.gcal.apply_sync_operation = slow
    item = add(manager)
    start = time.monotonic()
    pending = asyncio.create_task(manager.process_due(deadline=start + .05))
    assert await asyncio.to_thread(entered.wait, 1)
    beats = 0
    while not pending.done():
        await asyncio.sleep(.005)
        beats += 1
    results = await pending
    elapsed = time.monotonic() - start
    print(f'heartbeat receipt: deadline=.050s return={elapsed:.4f}s beats={beats} interval=.005s')
    assert elapsed < .5
    assert beats >= 3
    assert results[0].state == 'unknown'
    assert await manager.process_due(deadline=time.monotonic() + 1) == []
    release.set()
    await asyncio.sleep(.02)
    assert operation(manager, item['id'])['state'] == 'unknown'
    await manager.process_due(deadline=time.monotonic() + 2)
    assert len(manager.gcal.calls) == 1


@pytest.mark.asyncio
async def test_known_rejection_is_bounded_by_retry_budget(manager):
    from cal_system.sync_outbox import RemoteMutation
    manager.gcal.fail = RemoteMutation('retryable', retry_after_s=0, reason_code='rate_limited')
    item = add(manager)
    elapsed = [datetime.now(timezone.utc)]
    manager.clock = Clock(wall=lambda: elapsed[0])
    for _ in range(8):
        await manager.process_due(deadline=time.monotonic() + 2)
        elapsed[0] += timedelta(hours=1)
    assert operation(manager, item['id'])['state'] == 'failed'
    assert len(manager.gcal.calls) <= 6


@pytest.mark.asyncio
async def test_failed_update_survives_remote_pull_and_concurrent_remote_edit(manager):
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    linked = manager.items['shared'][0]
    remote_id = linked['gcal_event_id']
    manager.edit_item_by_id(item['id'], title='Lokal endring')
    manager.gcal.remote[remote_id]['summary'] = 'Ekstern endring'
    manager.gcal.remote[remote_id]['etag'] = 'etag-other'
    await manager.sync_from_gcal()
    assert manager.items['shared'][0]['title'] == 'Lokal endring'
    await manager.process_due(deadline=time.monotonic() + 2)
    assert operation(manager, item['id'])['state'] == 'conflict'
    assert manager.gcal.remote[remote_id]['summary'] == 'Ekstern endring'


@pytest.mark.asyncio
async def test_conflict_choice_is_reviewed_revision_bound_and_does_not_implicitly_win(manager):
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    manager.edit_item_by_id(item['id'], title='Lokal endring')
    remote_id = manager.items['shared'][0]['gcal_event_id']
    manager.gcal.remote[remote_id]['summary'] = 'Ekstern endring'
    manager.gcal.remote[remote_id]['etag'] = 'etag-other'
    await manager.process_due(deadline=time.monotonic() + 2)
    op = operation(manager, item['id'])
    proposal = manager.preview_sync_conflict(actor(), op['operation_id'], 'use_remote')
    assert proposal.effects[0]['local']['summary'] == 'Lokal endring'
    with request_scope(actor()):
        await manager.apply_sync_conflict(actor(), proposal.token, deadline=time.monotonic() + 2)
    assert manager.items['shared'][0]['title'] == 'Ekstern endring'
    assert operation(manager, item['id'])['state'] == 'synced'


@pytest.mark.asyncio
async def test_stop_after_acceptance_leaves_durable_unknown_and_reconciles(manager):
    entered, release = threading.Event(), threading.Event()
    real = manager.gcal.apply_sync_operation

    def accepted_then_slow(op):
        result = real(op)
        entered.set()
        assert release.wait(3)
        return result

    manager.gcal.apply_sync_operation = accepted_then_slow
    item = add(manager)
    task = asyncio.create_task(manager.process_due(deadline=time.monotonic() + 2))
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert operation(manager, item['id'])['state'] == 'unknown'
    assert await manager.process_due(deadline=time.monotonic() + 1) == []
    release.set()
    await manager._outbox.slot.task
    await manager.process_due(deadline=time.monotonic() + 2)
    assert operation(manager, item['id'])['state'] == 'synced'
    assert len(manager.gcal.calls) == 1


@pytest.mark.asyncio
async def test_matching_marker_does_not_overwrite_later_remote_edit(manager, monkeypatch):
    from cal_system.sync_outbox import RemoteMutation
    real = manager.gcal.apply_sync_operation

    def accepted_lost(op):
        real(op)
        manager.gcal.remote[op.remote_id]['summary'] = 'Senere ekstern endring'
        return RemoteMutation('unknown')

    monkeypatch.setattr(manager.gcal, 'apply_sync_operation', accepted_lost)
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    await manager.process_due(deadline=time.monotonic() + 2)
    assert operation(manager, item['id'])['state'] == 'conflict'
    assert len(manager.gcal.calls) == 1


async def conflict(manager):
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    manager.edit_item_by_id(item['id'], title='Lokalt')
    event = manager.gcal.remote[manager.items['shared'][0]['gcal_event_id']]
    event.update(summary='Eksternt', etag='new')
    event['attendees'] = [{'email': 'private@example.test'}]
    await manager.process_due(deadline=time.monotonic() + 2)
    return item, manager.preview_sync_conflict(actor(), operation(manager, item['id'])['operation_id'], 'use_local')


@pytest.mark.asyncio
async def test_conflict_reviews_are_actor_local_and_remote_revision_bound(manager):
    item, proposal = await conflict(manager)
    assert 'attendees' not in proposal.effects[0]['remote']
    with pytest.raises(PermissionError):
        await manager.apply_sync_conflict(RequestContext('r', '8', '9', None, 'no', 'dm'), proposal.token, deadline=time.monotonic() + 2)
    manager.edit_item_by_id(item['id'], title='Ny lokal endring')
    with pytest.raises(ValueError, match='revision_changed'):
        await manager.apply_sync_conflict(actor(), proposal.token, deadline=time.monotonic() + 2)
    conflict_id = next(op['operation_id'] for op in manager.items['shared'][0]['sync_operations'] if op['state'] == 'conflict')
    proposal = manager.preview_sync_conflict(actor(), conflict_id, 'use_local')
    manager.gcal.remote[manager.items['shared'][0]['gcal_event_id']]['etag'] = 'newer'
    with pytest.raises(ValueError, match='remote_revision_changed'):
        await manager.apply_sync_conflict(actor(), proposal.token, deadline=time.monotonic() + 2)
    assert len(manager.gcal.calls) == 1


@pytest.mark.asyncio
async def test_reviewed_local_choice_replaces_queued_updates_then_conditional_write(manager):
    item, proposal = await conflict(manager)
    await manager.apply_sync_conflict(actor(), proposal.token, deadline=time.monotonic() + 2)
    await manager.process_due(deadline=time.monotonic() + 2)
    assert manager.gcal.calls[-1].remote_version == 'new'
    assert manager.gcal.remote[manager.items['shared'][0]['gcal_event_id']]['summary'] == 'Lokalt'
    assert operation(manager, item['id'])['state'] == 'synced'


@pytest.mark.asyncio
async def test_linked_reminder_intent_uses_same_owner_and_never_creates_timed_task(tmp_path):
    from cal_system.reminder_manager import ReminderManager
    provider = FakeProvider()
    provider.remote['remote'] = {'id': 'remote', 'etag': 'v1', 'summary': 'Original',
        'start': {'date': '2027-01-01'}, 'end': {'date': '2027-01-02'}}
    manager = ReminderManager(tmp_path / 'reminders.json', gcal_manager=provider)
    try:
        local = manager.add_reminder('shared', '7', 'Tester', 'Original', gcal_event_id='remote')
        with manager._storage.transaction():
            manager.reminders['shared'][0]['_remote_etag'] = 'v1'
            manager._save_reminders()
        manager.edit_reminder('shared', 1, title='Ny tekst')
        assert provider.calls == []
        stored = json.loads(manager.storage_path.read_text())['document']['shared'][0]
        assert stored['sync_operations'][0]['item_id'] == local
        await manager.process_due(deadline=time.monotonic() + 2)
        assert provider.remote['remote']['summary'] == 'Ny tekst'
        manager.complete_reminder('shared', reminder_id=local)
        await manager.process_due(deadline=time.monotonic() + 2)
        assert provider.remote['remote']['summary'] == 'Ny tekst [FERDIG]'
        assert all(call.kind == 'update' and 'start' not in call.payload for call in provider.calls)
        manager.add_reminder('shared', '7', 'Tester', 'Uten tidsvarighet', due_date='02.01.2027')
        assert 'sync_operations' not in manager.reminders['shared'][-1]
    finally:
        manager._storage.close()


def test_corrupt_operation_metadata_is_read_only_and_preserved(tmp_path):
    path = tmp_path / 'calendar.json'
    manager = CalendarManager(path, gcal_manager=FakeProvider())
    add(manager)
    manager._storage.close()
    value = json.loads(path.read_text())
    value['document']['shared'][0]['sync_operations'][0]['state'] = 'made-up'
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    reopened = CalendarManager(path, gcal_manager=FakeProvider())
    try:
        assert reopened.storage_state.status == 'corrupt'
        assert path.read_bytes() == before
    finally:
        reopened._storage.close()


@pytest.mark.asyncio
async def test_conflict_handler_displays_both_versions_then_requires_exact_confirmation(manager):
    from unittest.mock import AsyncMock
    from features.calendar_handler import CalendarHandler
    from memory.localization import Localization
    item, _ = await conflict(manager)
    operation_id = operation(manager, item['id'])['operation_id']
    handler = CalendarHandler(SimpleNamespace(calendar=manager, nlp_parser=None,
        rate_limiter=None, loc=Localization(), client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(content=f'@inebotten synk konflikt {operation_id} google',
        guild=None, channel=SimpleNamespace(id='9'), author=SimpleNamespace(id='7', name='Tester'))
    with request_scope(actor()):
        await handler.handle_sync(message)
    review = handler.send_response.await_args.args[1]
    assert 'Lokalt' in review and 'Eksternt' in review
    assert operation_id in review and 'private@example.test' not in review
    assert manager.items['shared'][0]['title'] == 'Lokalt'
    token = next(reversed(manager._sync_conflicts))
    message.content = f'@inebotten bekreft synk {token}'
    with request_scope(actor()):
        await handler.handle_sync(message)
    assert manager.items['shared'][0]['title'] == 'Eksternt'
    assert operation(manager, item['id'])['state'] == 'synced'


@pytest.mark.asyncio
async def test_provider_pull_returns_late_without_overwriting_concurrent_local_change(manager):
    entered, release = threading.Event(), threading.Event()
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    real = manager.gcal.list_upcoming_events

    def slow(**kwargs):
        entered.set()
        assert release.wait(3)
        return real(**kwargs)

    manager.gcal.list_upcoming_events = slow
    pending = asyncio.create_task(manager.sync_from_gcal())
    assert await asyncio.to_thread(entered.wait, 1)
    manager.edit_item_by_id(item['id'], title='Mens Google leses')
    release.set()
    assert await pending == 0
    assert manager.items['shared'][0]['title'] == 'Mens Google leses'
    assert 'endret under Google' in manager.last_gcal_sync_error


@pytest.mark.asyncio
async def test_conditional_race_after_preflight_preserves_local_and_remote_versions(manager):
    from cal_system.sync_outbox import RemoteMutation
    item = add(manager)
    await manager.process_due(deadline=time.monotonic() + 2)
    manager.edit_item_by_id(item['id'], title='Lokalt')
    remote_id = manager.items['shared'][0]['gcal_event_id']

    def raced(op):
        manager.gcal.remote[remote_id].update(summary='Samtidig', etag='raced')
        return RemoteMutation('conflict', reason_code='remote_conflict')

    manager.gcal.apply_sync_operation = raced
    await manager.process_due(deadline=time.monotonic() + 2)
    assert operation(manager, item['id'])['state'] == 'conflict'
    assert operation(manager, item['id'])['conflict_remote']['etag'] == 'raced'
    assert manager.items['shared'][0]['title'] == 'Lokalt'


def test_full_outbox_refuses_new_mutation_preserving_previous_local_revision(manager):
    from utils.storage_contract import StorageMutationError
    item = add(manager)
    for i in range(7):
        manager.edit_item_by_id(item['id'], title=f'Edit {i}')
    before = manager.storage_path.read_bytes()
    with pytest.raises(StorageMutationError, match='outbox_full'):
        manager.edit_item_by_id(item['id'], title='Cannot silently discard an intent')
    assert manager.storage_path.read_bytes() == before
    assert manager.items['shared'][0]['title'] == 'Edit 6'


@pytest.mark.asyncio
async def test_edit_of_pending_create_queues_successor_update_not_second_create(manager):
    item = add(manager)
    proposal = manager.preview_mutation(actor(), 'shared', [item['id']], 'edit', manager._storage.revision,
        changes={'title': 'Redigert før opprettelse'})
    with request_scope(actor()):
        await manager.apply_preview(actor(), proposal.token)
        await manager.process_due(deadline=time.monotonic() + 2)
        await manager.process_due(deadline=time.monotonic() + 2)
    assert [call.kind for call in manager.gcal.calls] == ['create', 'update']
    assert len(manager.gcal.remote) == 1
    assert list(manager.gcal.remote.values())[0]['summary'] == 'Redigert før opprettelse'


@pytest.mark.asyncio
async def test_undo_cannot_discard_unresolved_remote_acceptance(manager):
    from cal_system.sync_outbox import RemoteMutation
    item = add(manager)
    manager.gcal.fail = RemoteMutation('unknown')
    await manager.process_due(deadline=time.monotonic() + 2)
    proposal = manager.preview_mutation(actor(), 'shared', [item['id']], 'edit', manager._storage.revision,
        changes={'title': 'Senere lokal endring'})
    applied = await manager.apply_preview(actor(), proposal.token)
    before = manager.storage_path.read_bytes()
    with pytest.raises(ValueError, match='remote_acceptance_unresolved'):
        await manager.undo_mutation(actor(), applied['undo_token'])
    assert manager.storage_path.read_bytes() == before
    assert manager.items['shared'][0]['sync_operations'][0]['state'] == 'unknown'
