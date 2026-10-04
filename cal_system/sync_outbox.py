"""Same-document external intent, bounded worker and acceptance reconciliation."""
from __future__ import annotations
import asyncio
import copy
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import json
import math
import time
import uuid

from cal_system.event_schema import EventTime
from core.request_context import current_request
from utils.storage_contract import StorageMutationError, writable_store
from cal_system.mutation_preview import actor_key

STATES = {'pending', 'synced', 'conflict', 'failed', 'unknown'}
MAX_OPERATIONS = 8
MAX_ATTEMPTS = 6
MAX_OPERATION_BYTES = 131072


def remote_evidence(event):
    """Bounded editable projection; never retain attendees or unrelated metadata."""
    if not isinstance(event, dict):
        raise ValueError('invalid_remote_evidence')
    result = {key: copy.deepcopy(event[key]) for key in
        ('id', 'etag', 'status', 'summary', 'description', 'start', 'end', 'recurrence', 'htmlLink') if key in event}
    properties = event.get('extendedProperties', {})
    if not isinstance(properties, dict) or not isinstance(properties.get('private', {}), dict):
        raise ValueError('invalid_remote_properties')
    private = properties.get('private', {})
    result['extendedProperties'] = {'private': {key: private[key] for key in
        ('inebotten_operation_id', 'inebotten_completed') if key in private}}
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_OPERATION_BYTES // 2:
        raise ValueError('remote_evidence_too_large')
    return result


def remote_completion(event):
    flag = event.get('extendedProperties', {}).get('private', {}).get('inebotten_completed')
    completed = flag == 'true'
    title = event.get('summary', '')
    return (title.removesuffix(' [FERDIG]') if completed else title), completed


@dataclass(frozen=True)
class SyncOperation:
    operation_id: str
    item_id: str
    local_revision: int
    kind: str
    remote_id: str | None
    remote_version: str | None
    state: str
    attempts: int
    retry_at: datetime | None
    payload: dict
    scope_id: str
    reason_code: str = 'queued'
    conflict_remote: dict | None = None
    predecessor: str | None = None

    def __post_init__(self):
        if self.state not in STATES or self.kind not in ('create', 'update', 'delete'):
            raise ValueError('invalid_sync_operation')
        if type(self.attempts) is not int or self.attempts < 0 or type(self.local_revision) is not int or self.local_revision < 1:
            raise ValueError('invalid_sync_revision')
        if self.retry_at is not None and self.retry_at.tzinfo is None:
            raise ValueError('aware_retry_required')
        if not all(isinstance(value, str) and value and len(value) <= 1024
                   for value in (self.operation_id, self.item_id, self.scope_id)):
            raise ValueError('invalid_sync_identity')
        if not isinstance(self.payload, dict):
            raise ValueError('invalid_sync_payload')
        if self.conflict_remote is not None:
            if remote_evidence(self.conflict_remote) != self.conflict_remote:
                raise ValueError('invalid_conflict_evidence')
        if len(json.dumps(self.document(), ensure_ascii=False).encode()) > MAX_OPERATION_BYTES:
            raise ValueError('outbox_payload_too_large')
        for value in (self.remote_id, self.remote_version):
            if value is not None and (not isinstance(value, str) or not value or len(value) > 2048):
                raise ValueError('invalid_remote_identity')

    def document(self):
        value = asdict(self)
        value['retry_at'] = self.retry_at.isoformat() if self.retry_at else None
        return value

    @classmethod
    def from_document(cls, value):
        fields = copy.deepcopy(value)
        fields['retry_at'] = datetime.fromisoformat(fields['retry_at']) if fields.get('retry_at') else None
        return cls(**fields)


@dataclass(frozen=True)
class RemoteMutation:
    status: str
    event: dict | None = None
    reason_code: str = 'ok'
    retry_after_s: float | None = None

    def __post_init__(self):
        if self.status not in ('acknowledged', 'retryable', 'conflict', 'auth_error', 'rejected', 'unknown'):
            raise ValueError('invalid_remote_outcome')
        if self.retry_after_s is not None and (not math.isfinite(self.retry_after_s) or not 0 <= self.retry_after_s <= 3600):
            raise ValueError('invalid_retry_delay')


def payload_for_item(item):
    value = EventTime.from_item(item)
    start, end = value.google_times()
    payload = {'summary': item['title'] + (' [FERDIG]' if item.get('completed') else ''),
               'start': start, 'end': end, 'description': item.get('description', ''),
               'extendedProperties': {'private': {'inebotten_completed': 'true' if item.get('completed') else 'false'}}}
    frequency = {'daily': 'DAILY', 'weekly': 'WEEKLY', 'biweekly': 'WEEKLY;INTERVAL=2',
                 'monthly': 'MONTHLY', 'yearly': 'YEARLY'}.get(item.get('recurrence'))
    payload['recurrence'] = ['RRULE:FREQ=' + frequency] if frequency else item.get('_remote_recurrence_raw', [])
    return payload


def enqueue(item, kind, scope_id, *, payload=None):
    """Mutate only the caller's private draft; caller commits intent with data."""
    operations = item.setdefault('sync_operations', [])
    active = [op for op in operations if op['state'] != 'synced']
    if len(active) >= MAX_OPERATIONS:
        raise StorageMutationError('outbox_full')
    # Keep unresolved history and the latest successful receipt, never evict an
    # ambiguous operation to make room for another side effect.
    operations[:] = ([op for op in operations if op['state'] == 'synced'][-1:] + active)[-MAX_OPERATIONS:]
    if len(operations) >= MAX_OPERATIONS:
        operations[:] = active
    revision = item.get('local_revision', 0) + 1
    nonce = uuid.uuid4().hex
    remote_id = item.get('gcal_event_id')
    if kind == 'create':
        remote_id = 'ib' + uuid.uuid4().hex
    elif remote_id is None:
        remote_id = next((op['remote_id'] for op in active if op['kind'] == 'create'), None)
    body = payload if payload is not None else ({} if kind == 'delete' else payload_for_item(item))
    body = copy.deepcopy(body)
    if kind != 'delete':
        body.setdefault('extendedProperties', {}).setdefault('private', {})['inebotten_operation_id'] = nonce
    operation = SyncOperation(nonce, item['id'], revision, kind, remote_id,
        item.get('_remote_etag'), 'pending', 0, None, body, scope_id,
        predecessor=active[-1]['operation_id'] if active else None)
    document = operation.document()
    if len(json.dumps(document, ensure_ascii=False).encode()) > MAX_OPERATION_BYTES:
        raise StorageMutationError('outbox_payload_too_large')
    operations.append(document)
    item['local_revision'] = revision
    item['_local_sync_pending'] = kind
    return document


class ExternalSlot:
    """At most one live provider thread, including work past its caller deadline."""
    def __init__(self):
        self.task = None

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    async def run(self, function, *args, deadline):
        if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise ValueError('invalid_deadline')
        if self.busy or deadline <= time.monotonic():
            raise TimeoutError('provider_busy_or_deadline')
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self.task = task
        # Consume failures even when a caller has stopped awaiting the thread.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        done, _ = await asyncio.wait({task}, timeout=max(0, deadline - time.monotonic()))
        if not done or time.monotonic() >= deadline:
            raise TimeoutError('provider_deadline')
        return task.result()


class SyncOutbox:
    def __init__(self, manager):
        self.manager = manager
        self.slot = ExternalSlot()
        self.running = False

    def _due(self):
        manager = self.manager
        for scope, items in manager.items.items():
            if not manager._sync_scope_allowed(scope):
                continue
            for item in items:
                for raw in item.get('sync_operations', []):
                    op = SyncOperation.from_document(raw)
                    if op.state == 'synced':
                        continue
                    if (op.state not in ('failed', 'conflict') or op.state == 'conflict' and not op.conflict_remote) and (op.retry_at is None or op.retry_at <= manager.clock.now()):
                        yield op
                    break  # Preserve order within each item.

    async def process_due(self, *, deadline):
        if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise ValueError('invalid_deadline')
        if self.running or self.slot.busy or not self.manager.gcal_enabled:
            return []
        self.running = True
        results = []
        try:
            for op in list(self._due())[:8]:
                if time.monotonic() >= deadline:
                    break
                if op.state in ('unknown', 'conflict'):
                    results.append(await self._reconcile(op, deadline))
                    continue
                if op.attempts >= MAX_ATTEMPTS:
                    results.append(await self.manager._update_sync_operation(op.operation_id,
                        state='failed', reason_code='retry_exhausted'))
                    continue
                if op.kind != 'create':
                    try:
                        remote = await self.slot.run(self.manager.gcal.get_event_outcome, op.remote_id, deadline=deadline)
                    except Exception:
                        results.append(await self._delay(op, 'preflight_unavailable'))
                        continue
                    if remote.status in ('cancelled', 'missing') and op.kind == 'delete':
                        results.append(await self.manager._update_sync_operation(op.operation_id, state='synced', reason_code='confirmed_absent'))
                        continue
                    if remote.status != 'live':
                        results.append(await self._delay(op, 'preflight_unavailable'))
                        continue
                    if not op.remote_version or remote.event.get('etag') != op.remote_version:
                        results.append(await self.manager._update_sync_operation(op.operation_id,
                            state='conflict', reason_code='remote_version_changed', conflict_remote=remote.event))
                        continue
                # Persist uncertainty BEFORE attempting an external mutation.
                started = await self.manager._update_sync_operation(op.operation_id,
                    state='unknown', attempts=op.attempts + 1, reason_code='request_in_flight')
                try:
                    response = await self.slot.run(self.manager.gcal.apply_sync_operation, started, deadline=deadline)
                except Exception:
                    response = RemoteMutation('unknown', reason_code='transport_uncertain')
                if not isinstance(response, RemoteMutation):
                    response = RemoteMutation('unknown', reason_code='invalid_provider_contract')
                if response.status == 'acknowledged':
                    event = response.event
                    if started.kind != 'delete' and (not isinstance(event, dict)
                        or event.get('id') != started.remote_id or not event.get('etag')
                        or event.get('extendedProperties', {}).get('private', {}).get('inebotten_operation_id') != started.operation_id
                        or not payload_matches(started.payload, event)):
                        results.append(await self.manager._update_sync_operation(started.operation_id,
                            state='unknown', reason_code='invalid_acceptance_evidence'))
                    else:
                        results.append(await self.manager._update_sync_operation(started.operation_id,
                            state='synced', reason_code='acknowledged', accepted_event=event))
                elif response.status == 'retryable':
                    results.append(await self._delay(started, response.reason_code, response.retry_after_s, increment=False))
                else:
                    event = response.event
                    if response.status == 'conflict' and not event:
                        try:
                            lookup = await self.slot.run(self.manager.gcal.get_event_outcome, started.remote_id, deadline=deadline)
                            event = lookup.event if lookup.status == 'live' else None
                        except Exception:
                            pass
                    state = {'conflict': 'conflict', 'auth_error': 'failed', 'rejected': 'failed', 'unknown': 'unknown'}[response.status]
                    results.append(await self.manager._update_sync_operation(started.operation_id,
                        state=state, reason_code=response.reason_code, conflict_remote=event))
            return results
        finally:
            self.running = False

    async def _delay(self, op, reason, retry_after=None, *, increment=True):
        attempts = op.attempts + int(increment)
        delay = max(5 * 2 ** min(attempts, 8), retry_after or 0)
        return await self.manager._update_sync_operation(op.operation_id,
            state='failed' if attempts >= MAX_ATTEMPTS else 'pending', attempts=attempts,
            reason_code='retry_exhausted' if attempts >= MAX_ATTEMPTS else reason,
            retry_at=(self.manager.clock.now() + timedelta(seconds=min(delay, 3600))).isoformat())

    async def _reconcile(self, op, deadline):
        try:
            remote = await self.slot.run(self.manager.gcal.get_event_outcome, op.remote_id, deadline=deadline)
        except Exception:
            remote = None
        if remote is not None and remote.status in ('missing', 'cancelled') and op.kind == 'delete':
            return await self.manager._update_sync_operation(op.operation_id, state='synced', reason_code='confirmed_absent')
        if remote is not None and remote.status == 'live':
            marker = remote.event.get('extendedProperties', {}).get('private', {}).get('inebotten_operation_id')
            if marker == op.operation_id and remote.event.get('etag') and payload_matches(op.payload, remote.event):
                return await self.manager._update_sync_operation(op.operation_id,
                    state='synced', reason_code='acceptance_reconciled', accepted_event=remote.event)
            return await self.manager._update_sync_operation(op.operation_id,
                state='conflict', reason_code='acceptance_not_proven', conflict_remote=remote.event)
        # A bare 404 does not establish whether the write was ever accepted.
        return await self.manager._update_sync_operation(op.operation_id,
            state='unknown', reason_code='acceptance_unresolved',
            retry_at=(self.manager.clock.now() + timedelta(seconds=30)).isoformat())


def payload_matches(payload, event):
    """Receipt marker proves acceptance, while editable values detect later edits."""
    for key in ('summary', 'description', 'recurrence'):
        if key in payload and payload[key] != event.get(key, [] if key == 'recurrence' else ''):
            return False
    if payload.get('extendedProperties', {}).get('private', {}).get('inebotten_completed') != event.get('extendedProperties', {}).get('private', {}).get('inebotten_completed'):
        return False
    if 'start' not in payload:
        return True
    try:
        return EventTime.from_google(payload).fields() == EventTime.from_google(event).fields()
    except (KeyError, ValueError, TypeError):
        return False


class SyncOwnerMixin:
    """Owned metadata shared by calendar and legacy linked reminder records."""
    def sync_summary(self):
        result = {state: 0 for state in STATES}
        result['conflict_ids'] = []
        for scope, items in self.items.items():
            if not self._sync_scope_allowed(scope):
                continue
            for item in items:
                for raw in item.get('sync_operations', []):
                    result[raw['state']] += 1
                    if raw['state'] == 'conflict':
                        result['conflict_ids'].append(raw['operation_id'])
        return result

    def _sync_scope_allowed(self, scope):
        key = scope if scope in self.access_policy.scopes or scope.startswith(('private:', 'group:')) else 'shared'
        return self.access_policy.authorize(current_request(), key, 'write').allowed

    @writable_store
    async def _update_sync_operation(self, operation_id, *, accepted_event=None, **changes):
        for scope, items in self.items.items():
            for item in items:
                for raw in item.get('sync_operations', []):
                    if raw['operation_id'] != operation_id:
                        continue
                    if not self._sync_scope_allowed(scope):
                        raise PermissionError('scope_membership_required')
                    raw.update(changes)
                    if raw.get('conflict_remote'):
                        raw['conflict_remote'] = remote_evidence(raw['conflict_remote'])
                    if accepted_event:
                        item['gcal_event_id'] = accepted_event['id']
                        item['gcal_link'] = accepted_event.get('htmlLink')
                        item['_remote_etag'] = accepted_event['etag']
                        item['_remote_baseline'] = remote_evidence(accepted_event)
                        for successor in item['sync_operations']:
                            if successor.get('predecessor') == operation_id and successor['attempts'] == 0:
                                successor['remote_id'] = accepted_event['id']
                                successor['remote_version'] = accepted_event['etag']
                    if all(op['state'] == 'synced' for op in item['sync_operations']):
                        item.pop('_local_sync_pending', None)
                        if raw['kind'] == 'delete' and not item.get('_undo_record'):
                            self.items[scope] = [value for value in items if value['id'] != item['id']]
                    await self._save_data()
                    return SyncOperation.from_document(raw)
        raise ValueError('operation_missing')

    def preview_sync_conflict(self, actor, operation_id, choice):
        with self._storage.transaction(write=False):
            if self._storage._async_active:
                raise StorageMutationError('store_busy')
            return self._preview_sync_conflict(actor, operation_id, choice)

    def _preview_sync_conflict(self, actor, operation_id, choice):
        from cal_system.mutation_preview import MutationPreview
        if choice not in ('use_local', 'use_remote'):
            raise ValueError('invalid_conflict_choice')
        for scope, items in self.items.items():
            for item in items:
                for raw in item.get('sync_operations', []):
                    if raw['operation_id'] != operation_id:
                        continue
                    self._authorize_mutation(actor, scope)
                    remote = raw.get('conflict_remote')
                    if raw['state'] != 'conflict' or not remote or not remote.get('etag'):
                        raise ValueError('conflict_evidence_required')
                    token = uuid.uuid4().hex
                    expiry = self.clock.now() + timedelta(minutes=5)
                    local = self.sync_payload(item) if not item.get('_mutation_deleted') else {'delete': True}
                    effects = [{'operation_id': operation_id, 'choice': choice,
                        'local': local, 'remote': remote_evidence(remote),
                        'pending_operation_ids': [op['operation_id'] for op in item['sync_operations'] if op['state'] != 'synced']}]
                    self._sync_conflicts[token] = {'actor': actor_key(actor), 'scope': scope,
                        'revision': self._storage.revision, 'operation_id': operation_id,
                        'remote_id': raw['remote_id'], 'remote_etag': remote['etag'],
                        'choice': choice, 'expiry': expiry, 'deadline': self.clock.monotonic() + 300}
                    while len(self._sync_conflicts) > 32:
                        self._sync_conflicts.popitem(last=False)
                    return MutationPreview(token, self._storage.revision, expiry, effects)
        raise ValueError('operation_missing')

    async def apply_sync_conflict(self, actor, token, *, deadline):
        proposal = self._sync_conflicts.get(token)
        if not proposal:
            raise ValueError('preview_missing')
        if proposal['actor'] != actor_key(actor):
            raise PermissionError('preview_actor_mismatch')
        self._authorize_mutation(actor, proposal['scope'])
        if self.clock.now() >= proposal['expiry'] or self.clock.monotonic() >= proposal['deadline']:
            raise ValueError('preview_expired')
        remote = await self._outbox.slot.run(self.gcal.get_event_outcome, proposal['remote_id'], deadline=deadline)
        if remote.status != 'live' or remote.event.get('etag') != proposal['remote_etag']:
            raise ValueError('remote_revision_changed')
        result = await self._apply_sync_conflict(actor, proposal, remote.event)
        self._sync_conflicts.pop(token, None)
        return result

    @writable_store
    async def _apply_sync_conflict(self, actor, proposal, remote):
        scope = proposal['scope']
        self._authorize_mutation(actor, scope)
        if proposal['actor'] != actor_key(actor):
            raise PermissionError('preview_actor_mismatch')
        if self.clock.now() >= proposal['expiry'] or self.clock.monotonic() >= proposal['deadline']:
            raise ValueError('preview_expired')
        if proposal['revision'] != self._storage.revision:
            raise ValueError('revision_changed')
        for item in self.items.get(scope, []):
            raw = next((op for op in item.get('sync_operations', [])
                        if op['operation_id'] == proposal['operation_id']), None)
            if raw is None:
                continue
            if raw['state'] != 'conflict':
                raise ValueError('conflict_changed')
            for other in item['sync_operations']:
                if other is not raw and other['state'] != 'synced':
                    other.update(state='synced', reason_code='superseded_reviewed_choice')
            item['_remote_etag'] = remote['etag']
            item['_remote_baseline'] = remote_evidence(remote)
            if proposal['choice'] == 'use_remote':
                self.apply_remote_sync_fields(item, remote)
                for key in ('_mutation_deleted', 'delete_pending', '_local_sync_pending'):
                    item.pop(key, None)
                raw.update(state='synced', reason_code='reviewed_remote_choice')
            else:
                # The reviewed local choice is the current local state, including
                # a deletion queued after the original conflicting edit.
                raw['kind'] = 'delete' if item.get('_mutation_deleted') or item.get('delete_pending') else 'update'
                raw.update(state='pending', attempts=0, retry_at=None,
                    remote_version=remote['etag'], conflict_remote=None, reason_code='reviewed_local_choice',
                    payload={} if raw['kind'] == 'delete' else self.sync_payload(item))
                if raw['kind'] != 'delete':
                    raw['payload'].setdefault('extendedProperties', {}).setdefault('private', {})['inebotten_operation_id'] = raw['operation_id']
            await self._save_data()
            return SyncOperation.from_document(raw)
        raise ValueError('operation_missing')
