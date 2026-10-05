#!/usr/bin/env python3
"""
Simple Calendar Manager for Inebotten
Everything is just a calendar item with a date
"""

import re
import uuid
import asyncio
import copy
from collections import OrderedDict
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
from zoneinfo import ZoneInfo

from cal_system.event_schema import EventTime, Clock
from cal_system.recurrence import Series, Occurrence, occurrence_at, series_from_item, parse_google_recurrence
from core.access_policy import AccessPolicy
from core.request_context import current_request
from cal_system.mutation_preview import PreviewCache, actor_key, before_image, validate_calendar_document
from cal_system.sync_outbox import SyncOutbox, SyncOwnerMixin, enqueue, payload_for_item, remote_evidence, remote_completion

from utils.json_storage import hermes_discord_data_path, write_json_atomic
from utils.storage_contract import DocumentOwner, StorageMutationError, writable_store, store_worker


class AwaitableDict(dict):
    """Dictionary result that can also be awaited by async handlers."""

    def __await__(self):
        async def _return():
            return self
        return _return().__await__()


class AwaitableValue:
    """Generic result wrapper that can be awaited without breaking sync callers."""

    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _return():
            return self.value
        return _return().__await__()

    def __bool__(self):
        return bool(self.value)

    def __iter__(self):
        return iter(self.value)

    def __getitem__(self, key):
        return self.value[key]

    def __repr__(self):
        return repr(self.value)


class CalendarDeleteResult(dict):
    """Structured delete result that still unpacks like the legacy tuples."""

    def __iter__(self):
        if self.get("bulk"):
            yield int(self.get("deleted_count", 0))
            yield list(self.get("deleted_titles", []))
        else:
            yield bool(self.get("success"))
            yield self.get("title")

    def __bool__(self):
        return bool(self.get("success") or int(self.get("deleted_count", 0)) > 0)

    def __getitem__(self, key):
        if isinstance(key, int):
            values = list(iter(self))
            return values[key]
        return super().__getitem__(key)


class CalendarManager(SyncOwnerMixin):
    """
    Manages calendar items - everything is just something happening on a date
    """

    def __init__(self, storage_path=None, gcal_manager=None, owner_email=None, owner_name=None, access_policy=None, clock=None, undo_retention_seconds=86400):
        if storage_path is None:
            storage_path = hermes_discord_data_path("calendar.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.gcal = gcal_manager
        self.gcal_enabled = gcal_manager is not None
        self.owner_email = owner_email
        self.owner_name = owner_name
        self.last_gcal_sync_error = None
        self.SHARED_KEY = "shared"
        self.clock = clock or Clock()
        if type(undo_retention_seconds) is not int or not 1 <= undo_retention_seconds <= 604800:
            raise ValueError('invalid_undo_retention')
        self.undo_retention_seconds = undo_retention_seconds
        self._previews = PreviewCache(self.clock)
        self.access_policy = access_policy or AccessPolicy()
        self._storage = DocumentOwner(self.storage_path, validate_calendar_document, schema_version=2, upgrade_from=(1,))
        self.items = self._storage.rollback()  # Will be transitioned to {self.SHARED_KEY: [...]}
        self._outbox = SyncOutbox(self)
        self._sync_conflicts = OrderedDict()

    def _queue_sync(self, item, kind, scope=None):
        if not self.gcal_enabled and not item.get('gcal_event_id') and not item.get('sync_operations'):
            return
        active = any(op['state'] != 'synced' for op in item.get('sync_operations', []))
        if kind != 'create' and not item.get('gcal_event_id') and not active:
            if kind == 'delete' or item.get('kind') == 'task':
                return
            kind = 'create'
        try:
            for op in item.get('sync_operations', []):
                if op['state'] == 'failed' and op['attempts'] == 0 and op['reason_code'] == 'explicit_event_time_required':
                    op.update(state='synced', reason_code='superseded_after_explicit_time')
            enqueue(item, kind, scope or item.get('scope_id') or self.scope_key(operation='write'))
            item.pop('sync_blocked', None)
        except ValueError:
            item['sync_blocked'] = 'explicit_event_time_required'
            if kind != 'create':
                raw = enqueue(item, kind, scope or item.get('scope_id') or self.scope_key(operation='write'),
                    payload={'summary': item['title']})
                raw.update(state='failed', reason_code='explicit_event_time_required')

    async def process_due(self, *, deadline):
        return await self._outbox.process_due(deadline=deadline)

    def sync_payload(self, item):
        return payload_for_item(item)

    def apply_remote_sync_fields(self, item, remote):
        if str(item.get('sync_blocked') or '').startswith('google_'):
            self.last_gcal_sync_error = 'Lokal gjentakelsesendring venter på avklart Google-synkronisering; innkommende data er ikke brukt.'
            return
        value = EventTime.from_google(remote)
        rules = remote.get('recurrence', [])
        parsed = parse_google_recurrence(rules, value)
        if parsed['supported'] and item.get('series'):
            incoming = Series(item['id'],value,parsed['rule'],parsed['end_count'],parsed['end_date']).to_document()
            if incoming != item['series'] and (item.get('occurrences') or item.get('series_next_index',0) or item.get('series_history')):
                # Index-based identities cannot be remapped onto a different
                # provider schedule without losing the meaning of exceptions.
                item['_remote_series_change_pending'] = {
                    'id': remote.get('id'), 'recurrence': list(rules),
                    'start': copy.deepcopy(remote.get('start')), 'end': copy.deepcopy(remote.get('end')),
                    'etag': remote.get('etag'),
                }
                item['sync_blocked'] = 'google_series_changed_requires_review'
                item['_recurrence_readonly'] = True
                item['recurrence_diagnostic'] = 'google_series_changed_requires_review'
                return
        item.update(value.fields())
        item['title'], item['completed'] = remote_completion(remote)
        item['description'] = remote.get('description', '')
        item['_remote_recurrence_raw'] = list(rules)
        item['recurrence_readable'] = parsed['readable']
        if parsed['supported']:
            old_index = item.get('series_next_index', 0)
            prior_series = item.get('series')
            series = Series(item['id'], value,
                parsed['rule'], parsed['end_count'], parsed['end_date']).to_document()
            item['recurrence'] = parsed['rule']['frequency']
            item['recurrence_day'] = parsed['rule'].get('weekdays', [None])[0]
            item['series'] = series
            item['series_next_index'] = old_index
            item.setdefault('occurrences', {})
            item.pop('_recurrence_readonly', None)
            item.pop('recurrence_diagnostic', None)
            current = self._next_occurrence(item, Series.from_document(series), old_index)
            if current:
                item['series_next_index'] = current[0]
                self._apply_occurrence_pointer(item, current[1])
            elif old_index == 0:
                self._apply_occurrence_pointer(item, occurrence_at(Series.from_document(series), 0))
            if prior_series and Series.from_document(prior_series).series_id != item['id']:
                item['series_migration'] = {'status': 'series_identity_repaired', 'recovered_before_anchor': False}
        else:
            item['recurrence'] = None
            item['_recurrence_readonly'] = bool(rules)
            item['recurrence_diagnostic'] = parsed['reason_code'] if rules else None
            if rules and item.get('series'):
                item['unsupported_series_snapshot'] = copy.deepcopy(item['series'])
            else:
                item.pop('series', None)
                item.pop('series_next_index', None)
                item.pop('occurrences', None)
                item.pop('series_history', None)

    def _advance_occurrence(self, item, state):
        series = self._ensure_series(item)
        index = item.get('series_next_index', 0)
        occurrence = occurrence_at(series, index)
        if occurrence is None:
            item['completed'] = True
            return None
        self._save_occurrence(item, occurrence, state=state)
        next_occurrence = self._next_occurrence(item, series, index + 1)
        item['series_next_index'] = next_occurrence[0] if next_occurrence else index + 1
        if next_occurrence:
            self._apply_occurrence_pointer(item, next_occurrence[1])
            item['completed'] = False
        else:
            item['completed'] = True
        if item.get('gcal_event_id') or item.get('sync_operations'):
            item['sync_blocked'] = 'google_occurrence_scope_requires_remote_review'
        return next_occurrence

    def _recurring_edit(self, item, changes, effect_ids, effect_scopes):
        changes = {key: value for key, value in dict(changes or {}).items() if value is not None}
        edit_scope = changes.pop('edit_scope', None)
        if edit_scope not in ('this', 'future', 'series'):
            raise ValueError('recurrence_edit_scope_required')
        series = self._ensure_series(item)
        index = item.get('series_next_index', 0)
        occurrence = occurrence_at(series, index)
        if occurrence is None:
            raise ValueError('recurrence_has_no_pending_occurrence')
        effect_ids[item['id']] = occurrence.occurrence_id
        effect_scopes[item['id']] = edit_scope
        if edit_scope == 'this':
            allowed = {'title', 'date', 'time', 'description', 'duration_minutes', 'kind', 'timezone', 'fold'}
            if set(changes) - allowed:
                raise ValueError('unsupported_this_occurrence_edit')
            saved = self._occurrence_records(item).get(occurrence.occurrence_id)
            if saved and saved.original_start != occurrence.original_start:
                raise ValueError('occurrence_exception_identity_mismatch')
            override = dict((saved.override if saved else occurrence.override) or {})
            for key, value in changes.items():
                if key == 'date':
                    value = self._normalize_date_format(value)
                override[key] = value
            updated = self._save_occurrence(item, occurrence, state='planned', override=override)
            self._apply_occurrence_pointer(item, updated)
            if item.get('gcal_event_id') or item.get('sync_operations'):
                item['sync_blocked'] = 'google_occurrence_scope_requires_remote_review'
        else:
            scheduling_change = any(key in changes for key in ('date', 'time', 'recurrence', 'timezone', 'kind', 'duration_minutes', 'fold'))
            if scheduling_change or 'end_count' in changes or 'end_date' in changes:
                # A new schedule cannot silently redefine an already reviewed
                # pending exception. Keep its original identity and bytes.
                if any(saved.original_start >= occurrence.original_start
                       for saved in self._occurrence_records(item).values()):
                    raise ValueError('pending_occurrence_exceptions_require_review')
            if edit_scope == 'future' and item.get('gcal_event_id'):
                item['sync_blocked'] = 'google_this_and_following_requires_two_remote_operations'
            elif item.get('gcal_event_id'):
                item['sync_blocked'] = 'google_recurrence_scope_requires_remote_review'
            previous = series.to_document()
            self._apply_item_updates(item, **{key: value for key, value in changes.items()
                if key in {'title', 'date', 'time', 'recurrence', 'description', 'duration_minutes', 'kind', 'timezone', 'fold'}})
            if scheduling_change or edit_scope == 'future':
                anchor = (EventTime.from_item(item).validate_local() if scheduling_change
                          else replace(series.anchor_time, local_date=occurrence.original_start.date()))
                rule = {'frequency': item.get('recurrence') or series.rule['frequency'],
                    **({'weekday': item.get('rrule_day') or item.get('recurrence_day')}
                       if item.get('rrule_day') or item.get('recurrence_day') else {})}
                end_count = changes.get('end_count', series.end_count)
                if end_count is not None and 'end_count' in changes:
                    if type(end_count) is not int or end_count < 1:
                        raise ValueError('invalid_recurrence_end_count')
                    if edit_scope == 'future':
                        end_count += index
                    elif end_count <= index:
                        raise ValueError('recurrence_end_before_current')
                end_date = self._coerce_recurrence_end_date(changes.get('end_date', series.end_date))
                if len(item.get('series_history', [])) >= 64:
                    raise ValueError('recurrence_history_limit')
                item.setdefault('series_history', []).append({'series': previous,
                    'through_index': index - 1, 'scope': edit_scope})
                series = Series(series.series_id, anchor, rule, end_count, end_date, index)
                item['series'] = series.to_document()
                item['series_next_index'] = index
                current = self._next_occurrence(item, series, index)
                if current is None:
                    raise ValueError('recurrence_has_no_pending_occurrence')
                self._apply_occurrence_pointer(item, current[1])
            elif 'end_count' in changes or 'end_date' in changes:
                if changes.get('end_count') is not None and changes['end_count'] <= index:
                    raise ValueError('recurrence_end_before_current')
                end_date = self._coerce_recurrence_end_date(changes.get('end_date', series.end_date))
                if end_date is not None and end_date < occurrence.original_start.date():
                    raise ValueError('recurrence_end_precedes_current')
                series = Series(series.series_id, series.anchor_time, series.rule,
                    changes.get('end_count', series.end_count),
                    end_date, series.index_offset)
                item['series'] = series.to_document()
            item['completed'] = False

    def workflow_receipt(self, actor, scope_id, item_id, trigger_kind):
        from cal_system.workflow_receipts import publish
        return publish(self, actor, scope_id, item_id, trigger_kind)

    def _authorize_mutation(self, actor, scope_id):
        actor_key(actor)
        if not self.access_policy.authorize(actor, scope_id, 'write').allowed:
            raise PermissionError('scope_membership_required')

    def preview_mutation(self, actor, scope_id, item_ids, operation, expected_revision, *, changes=None):
        self._authorize_mutation(actor, scope_id)
        if operation not in ('delete', 'clear', 'edit', 'complete', 'skip'):
            raise ValueError('unsupported_mutation')
        if len(set(item_ids)) != len(item_ids):
            raise ValueError('duplicate_selection')
        if not item_ids or len(item_ids) > self._previews.max_items:
            raise ValueError('invalid_selection_size')
        with self._storage.transaction(write=False):
            if self._storage._async_active:
                raise StorageMutationError('store_busy')
            if expected_revision != self._storage.revision:
                raise ValueError('revision_changed')
            records = {item['id']: item for item in self.items.get(scope_id, [])
                       if not item.get('_mutation_deleted') and not item.get('delete_pending')}
            if any(item_id not in records for item_id in item_ids):
                raise ValueError('selection_changed')
            if operation == 'clear' and set(item_ids) != set(records):
                raise ValueError('selection_changed')
            before = [before_image(records[item_id]) for item_id in item_ids]
            after = copy.deepcopy(before)
            effect_ids = {}
            effect_scopes = {}
            for item in after:
                if item.get('_recurrence_readonly') and operation in ('edit', 'complete', 'skip'):
                    raise ValueError('unsupported_google_recurrence_readonly')
                if operation in ('delete', 'clear'):
                    item['_mutation_deleted'] = True
                    item['completed'] = True
                    if item.get('gcal_event_id'):
                        item['delete_pending'] = True
                elif operation == 'edit':
                    if item.get('recurrence') or item.get('series'):
                        self._recurring_edit(item, changes, effect_ids, effect_scopes)
                    else:
                        self._apply_item_updates(item, **(changes or {}))
                elif operation in ('complete', 'skip') and (item.get('recurrence') or item.get('series')):
                    series = self._ensure_series(item)
                    current = occurrence_at(series, item.get('series_next_index', 0))
                    effect_ids[item['id']] = current.occurrence_id if current else None
                    self._advance_occurrence(item, 'completed' if operation == 'complete' else 'skipped')
                else:
                    if operation == 'skip':
                        raise ValueError('skip_requires_recurring_item')
                    item['completed'] = True
                recurrence_remote_block = (item.get('recurrence') or item.get('series')) and operation in ('edit', 'complete', 'skip')
                if (self.gcal_enabled or item.get('gcal_event_id') or item.get('sync_operations')) and not recurrence_remote_block:
                    item['_local_sync_pending'] = 'delete' if operation in ('delete', 'clear') else 'update'
            self._previews.clock = self.clock
            proposal = self._previews.create(actor, scope_id, expected_revision, operation, before, after)
            after_by_id = {item['id']: item for item in after}
            for effect in proposal.effects:
                result = after_by_id[effect['item_id']]
                effect['remote_pending'] = bool(result.get('_local_sync_pending'))
                if result.get('sync_blocked'):
                    effect['remote_blocked'] = result['sync_blocked']
                if effect['item_id'] in effect_ids and effect_ids[effect['item_id']]:
                    effect['occurrence_id'] = effect_ids[effect['item_id']]
                if effect['item_id'] in effect_scopes:
                    effect['edit_scope'] = effect_scopes[effect['item_id']]
            return proposal

    @writable_store
    async def apply_preview(self, actor, token):
        self._previews.clock = self.clock
        entry = self._previews.get(actor, token)
        scope = entry['scope']
        self._authorize_mutation(actor, scope)
        if entry['revision'] != self._storage.revision:
            raise ValueError('revision_changed')
        records = {item['id']: item for item in self.items.get(scope, [])}
        if any(item['id'] not in records or before_image(records[item['id']]) != item for item in entry['before']):
            raise ValueError('selection_changed')
        undo_token = uuid.uuid4().hex
        expires = (self.clock.now() + timedelta(seconds=self.undo_retention_seconds)).isoformat()
        # Keep one bounded inverse batch per scope. Old local tombstones no longer
        # support undo; pending external deletes remain until reconciled by I11.
        kept = []
        selected = {item['id'] for item in entry['before']}
        for item in self.items.get(scope, []):
            item.pop('_undo_record', None)
            if item['id'] in selected or not item.get('_mutation_deleted') or item.get('_local_sync_pending'):
                kept.append(item)
        replacements = {}
        for before, after in zip(entry['before'], entry['after']):
            if after.get('_local_sync_pending'):
                self._queue_sync(after, after['_local_sync_pending'], scope)
            after['_undo_record'] = {'token': undo_token, 'actor': actor_key(actor),
                'revision': self._storage.revision + 1, 'expires_at': expires,
                'batch_size': len(entry['before']), 'before': before}
            replacements[after['id']] = after
        self.items[scope] = [replacements.get(item['id'], item) for item in kept]
        await self._save_data()
        self._previews.entries.pop(token, None)
        return {'applied_count': len(replacements), 'operation': entry['operation'],
                'undo_token': undo_token, 'undo_expires_at': expires,
                'remote_pending': any(item.get('_local_sync_pending') for item in replacements.values()),
                'remote_blocked': sorted({item.get('sync_blocked') for item in replacements.values() if item.get('sync_blocked')}),
                'items': [before_image(item) for item in replacements.values()]}

    @writable_store
    async def undo_mutation(self, actor, token):
        matches = [(scope, item) for scope, items in self.items.items() for item in items
                   if item.get('_undo_record', {}).get('token') == token]
        if not matches:
            raise ValueError('undo_missing')
        scope = matches[0][0]
        self._authorize_mutation(actor, scope)
        for item_scope, item in matches:
            record = item['_undo_record']
            if item_scope != scope or record['actor'] != actor_key(actor):
                raise PermissionError('undo_actor_mismatch')
            if self.clock.now() >= datetime.fromisoformat(record['expires_at']):
                raise ValueError('undo_expired')
            if record['revision'] != self._storage.revision or len(matches) != record['batch_size']:
                raise ValueError('revision_changed')
            if any(op['state'] in ('unknown', 'conflict') or op['attempts'] > 0 and op['state'] != 'synced'
                   for op in item.get('sync_operations', [])):
                raise ValueError('remote_acceptance_unresolved')
        replacements = {}
        remote_limitations = []
        for _, item in matches:
            restored = copy.deepcopy(item['_undo_record']['before'])
            if restored.get('gcal_event_id'):
                restored['remote_relink_required'] = True
                restored['remote_previous_id'] = restored['gcal_event_id']
                restored.pop('gcal_event_id', None)
                restored.pop('gcal_link', None)
                restored.pop('sync_operations', None)
                restored.pop('_local_sync_pending', None)
                remote_limitations.append('Bare lokal gjenoppretting: Google-tilstand og tidligere ID må avklares før ny kobling.')
            replacements[item['id']] = restored
        self.items[scope] = [replacements.get(item['id'], item) for item in self.items[scope]]
        await self._save_data()
        return {'restored_count': len(replacements), 'remote_limitations': remote_limitations}

    async def prune_mutation_history(self):
        # A clean/read-only store must not claim writer ownership for a no-op.
        if not any(item.get('_undo_record') and
                   self.clock.now() >= datetime.fromisoformat(item['_undo_record']['expires_at'])
                   for items in self.items.values() for item in items):
            return False
        return await self._prune_expired_mutations()

    @writable_store
    async def _prune_expired_mutations(self):
        """Drop expired inverse data; preserve unresolved external delete intent."""
        changed = False
        for scope, items in list(self.items.items()):
            kept = []
            for item in items:
                record = item.get('_undo_record')
                if record and self.clock.now() >= datetime.fromisoformat(record['expires_at']):
                    item.pop('_undo_record')
                    changed = True
                    if item.get('_mutation_deleted') and not item.get('_local_sync_pending'):
                        continue
                kept.append(item)
            self.items[scope] = kept
        if changed:
            await self._save_data()
        return changed

    def display_snapshot(self, scope_id, days=90):
        self.scope_key(scope_id, operation='read')
        revision, document = self._storage.published_snapshot()
        today = self.clock.now().date()
        cutoff = today + timedelta(days=days)
        items = []
        for stored_item in document.get(scope_id, []):
            item = self._project_occurrence_for_display(stored_item)
            if item.get('completed') or item.get('delete_pending') or item.get('_mutation_deleted'):
                continue
            try:
                day = datetime.strptime(item['date'], '%d.%m.%Y').date()
                if today <= day <= cutoff:
                    items.append(item)
            except (KeyError, ValueError, TypeError):
                continue
        return revision, sorted(items, key=lambda item: datetime.strptime(item['date'], '%d.%m.%Y'))[:10]

    def _project_occurrence_for_display(self, item):
        if not item.get('series') or item.get('_recurrence_readonly'):
            return copy.deepcopy(item)
        try:
            series = Series.from_document(item['series'])
            pending = self._next_occurrence(item, series, item.get('series_next_index', 0))
            if not pending:
                return copy.deepcopy(item)
            occurrence = pending[1]
            projected = copy.deepcopy(item)
            projected['occurrence_id'] = occurrence.occurrence_id
            projected['series_id'] = occurrence.series_id
            projected['original_start'] = occurrence.original_start.isoformat()
            projected['date'] = occurrence.original_start.strftime('%d.%m.%Y')
            if occurrence.override:
                for key in ('date', 'time', 'timezone', 'duration_minutes', 'fold', 'all_day',
                    'title', 'description', 'kind'):
                    if key in occurrence.override:
                        projected[key] = occurrence.override[key]
            return projected
        except (KeyError, TypeError, ValueError):
            return copy.deepcopy(item)

    def scope_key(self, guild_id=None, operation='read'):
        key = str(guild_id) if guild_id is not None and str(guild_id) in self.access_policy.scopes else self.access_policy.default_scope
        decision = self.access_policy.authorize(current_request(), key, operation)
        if not decision.allowed:
            raise PermissionError(decision.reason_code)
        return key

    def _scope_buckets(self, operation='read'):
        key = self.scope_key(operation=operation)
        return {bucket for bucket in self.items if bucket == key or (
            key == self.SHARED_KEY and bucket not in self.access_policy.scopes and not bucket.startswith(('private:', 'group:')))}

    def preview_scope_migration(self, source, target):
        actor = current_request()
        for scope in (source, target):
            if not self.access_policy.authorize(actor, scope, 'write').allowed:
                raise PermissionError('scope_membership_required')
        return {'source_scope': source, 'target_scope': target,
                'item_ids': [item['id'] for item in self.items.get(source, [])],
                'source_revision': self._storage.revision, 'requires_confirmation': True,
                'warnings': ['Dette er bare en forhåndsvisning; eksisterende data er ikke flyttet.']}

    def preview_item_time(self, item):
        return EventTime.from_item(item).preview()

    def ensure_gcal_configured(self):
        """Refresh or lazily initialize Google Calendar integration."""
        if self.gcal and self.gcal.is_configured():
            self.gcal_enabled = True
            return True

        try:
            from cal_system.google_calendar_manager import GoogleCalendarManager

            gcal = GoogleCalendarManager()
            if gcal.is_configured():
                self.gcal = gcal
                self.gcal_enabled = True
                return True
        except Exception as e:
            print(f"[CAL] Google Calendar init failed: {e}")

        self.gcal_enabled = False
        return False

    async def setup(self):
        """Async initialization and migration to shared calendar"""
        self.items = await self._load_data()
        if self._migrate_legacy_recurrences():
            await self._save_data()
        await self.prune_mutation_history()
        
        # Migration to shared calendar if multiple buckets exist or if only old guild-specific buckets exist
        keys = list(self.items.keys())
        if self.access_policy.default_scope == self.SHARED_KEY and not any(key.startswith(('private:', 'group:')) or key in self.access_policy.scopes and key != self.SHARED_KEY for key in keys) and self.items and (len(keys) > 1 or (len(keys) == 1 and keys[0] != self.SHARED_KEY)):
            print(f"[CAL] Migrating {len(keys)} channel-specific calendars to one grand shared calendar...")
            merged = []
            seen_ids = set()
            
            # Extract all items from all buckets
            for guild_id, guild_items in self.items.items():
                for item in guild_items:
                    if item.get("id") not in seen_ids:
                        merged.append(item)
                        seen_ids.add(item.get("id"))
            
            self.items = {self.SHARED_KEY: merged}
            await self._save_data()
            print(f"[CAL] Migration complete: {len(merged)} items moved to '{self.SHARED_KEY}'")
            
        print(f"[CAL] Calendar system initialized with {sum(len(v) for v in self.items.values())} items")

    @property
    def items(self):
        return self._storage.data

    @items.setter
    def items(self, value):
        self._storage.data = value

    @property
    def storage_state(self):
        return self._storage.state

    async def _load_data(self) -> Dict:
        return await asyncio.to_thread(self._storage.load)

    async def _save_data(self):
        result = await store_worker(self._storage.commit, copy.deepcopy(self.items), writer=write_json_atomic)
        if not result.ok:
            self.items = self._storage.rollback()
            raise StorageMutationError(result.error_code)

    def _save_data_sync(self):
        result = self._storage.commit(self.items, writer=write_json_atomic)
        if not result.ok:
            self.items = self._storage.rollback()
            raise StorageMutationError(result.error_code)

    @writable_store
    def add_item(
        self,
        guild_id,
        user_id,
        username,
        title,
        date_str,
        time_str=None,
        recurrence=None,
        recurrence_day=None,
        gcal_event_id=None,
        gcal_link=None,
        channel_id=None,
        kind=None, timezone="Europe/Oslo", all_day=None, duration_minutes=None, fold=None,
        end_count=None, end_date=None, rrule_day=None, description="",
    ):
        """Add a new item to the calendar"""
        date_str = self._normalize_date_format(date_str)
        raw_time = {'date': date_str, 'time': time_str, 'timezone': timezone,
                    'duration_minutes': duration_minutes, 'fold': fold}
        if kind is not None:
            raw_time['kind'] = kind
        if all_day is not None:
            raw_time['all_day'] = all_day
        event_time = EventTime.from_item(raw_time).validate_local()

        guild_key = self.scope_key(guild_id, operation='write')
        if guild_key not in self.items:
            self.items[guild_key] = []

        item = {
            "id": str(uuid.uuid4()),
            "scope_id": guild_key,
            "user_id": user_id,
            "username": username,
            "title": title,
            "description": description,
            "date": date_str,
            "time": time_str,
            "recurrence": recurrence,
            "recurrence_day": recurrence_day,
            "rrule_day": rrule_day,
            "created_at": datetime.now().isoformat(),
            "completed": False,
            "gcal_event_id": gcal_event_id,
            "gcal_link": gcal_link,
            "channel_id": str(channel_id) if channel_id else None,
        }

        item.update(event_time.fields())
        item["time_interpretation"] = event_time.preview()
        if recurrence:
            parsed_end_date = self._coerce_recurrence_end_date(end_date)
            series = Series(item["id"], event_time,
                {"frequency": recurrence, **({"weekday": rrule_day or recurrence_day} if (rrule_day or recurrence_day) else {})},
                end_count, parsed_end_date)
            item["series"] = series.to_document()
            item["series_next_index"] = 0
            item["occurrences"] = {}
        if self.gcal_enabled and not gcal_event_id and recurrence:
            item['sync_blocked'] = 'google_recurrence_create_requires_remote_review'
        elif self.gcal_enabled and not gcal_event_id:
            self._queue_sync(item, 'create', guild_key)
        self.items[guild_key].append(item)
        self._save_data_sync()
        return AwaitableDict(item)

    def _mark_delete_pending(self, item, error=None, now=None):
        now = now or datetime.now().isoformat()
        item["delete_pending"] = True
        item["delete_requested_at"] = item.get("delete_requested_at") or now
        item["delete_last_attempt_at"] = now
        item["delete_error"] = error or "Google Calendar deletion returned false"

    def _delete_from_gcal_or_mark_pending(self, item, *, now=None, context="delete"):
        if not item.get('gcal_event_id') and not any(op['state'] != 'synced' for op in item.get('sync_operations', [])):
            return True

        self._queue_sync(item, 'delete')
        self._mark_delete_pending(item, 'queued_remote_delete', now)
        return False

    def _delete_item_record(self, guild_key, item_id):
        self.items[guild_key] = [
            i for i in self.items.get(guild_key, []) if i.get("id") != item_id
        ]

    def _delete_one_item(self, guild_key, item_to_delete, *, now=None):
        title = item_to_delete.get("title", "Uten tittel")
        requested = CalendarDeleteResult(
            {
                "success": False,
                "title": title,
                "requested_count": 1,
                "deleted_count": 0,
                "deleted_titles": [],
                "pending_count": 0,
                "pending_titles": [],
                "pending_errors": {},
            }
        )

        if not self._delete_from_gcal_or_mark_pending(item_to_delete, now=now):
            requested["pending_count"] = 1
            requested["pending_titles"] = [title]
            requested["pending_errors"] = {title: item_to_delete.get("delete_error")}
            return requested

        self._delete_item_record(guild_key, item_to_delete.get("id"))
        requested["success"] = True
        requested["deleted_count"] = 1
        requested["deleted_titles"] = [title]
        return requested

    @writable_store
    def delete_item(self, guild_id, item_num):
        """Delete an item by its list number (ignoring guild_id for shared calendar)"""
        guild_key = self.scope_key(guild_id, operation='write')
        items = self.get_upcoming(guild_key, days=365)

        if item_num is not None and 1 <= item_num <= len(items):
            item_to_delete = items[item_num - 1]
            result = self._delete_one_item(guild_key, item_to_delete)
            self._save_data_sync()
            return AwaitableValue(result)

        return AwaitableValue(
            CalendarDeleteResult(
                {
                    "success": False,
                    "title": None,
                    "requested_count": 0,
                    "deleted_count": 0,
                    "deleted_titles": [],
                    "pending_count": 0,
                    "pending_titles": [],
                    "pending_errors": {},
                }
            )
        )

    @writable_store
    async def delete_item_by_title(self, guild_id, title_search):
        """Delete a single item by title matching (ignoring guild_id for shared calendar)"""
        guild_key = self.scope_key(guild_id, operation='write')
        if guild_key not in self.items:
            return False, None

        title_search = title_search.lower()
        for i, item in enumerate(self.items[guild_key]):
            if title_search in item["title"].lower():
                result = self._delete_one_item(guild_key, item)
                await self._save_data()
                return result

        return CalendarDeleteResult(
            {
                "success": False,
                "title": None,
                "requested_count": 0,
                "deleted_count": 0,
                "deleted_titles": [],
                "pending_count": 0,
                "pending_titles": [],
                "pending_errors": {},
            }
        )

    @writable_store
    async def delete_items_by_title(self, guild_id, title_search):
        """Delete multiple items by title matching (ignoring guild_id for shared calendar)"""
        guild_key = self.scope_key(guild_id, operation='write')
        if guild_key not in self.items:
            return CalendarDeleteResult(
                {
                    "bulk": True,
                    "success": False,
                    "requested_count": 0,
                    "deleted_count": 0,
                    "deleted_titles": [],
                    "pending_count": 0,
                    "pending_titles": [],
                    "pending_errors": {},
                }
            )

        title_search = title_search.lower()
        requested = []
        deleted_ids = set()
        deleted_titles = []
        pending_titles = []
        pending_errors = {}
        now = datetime.now().isoformat()

        for item in self.items[guild_key]:
            if title_search in item["title"].lower():
                requested.append(item)
                title = item.get("title", "Uten tittel")
                if self._delete_from_gcal_or_mark_pending(item, now=now, context="bulk delete"):
                    deleted_ids.add(item.get("id"))
                    deleted_titles.append(title)
                else:
                    pending_titles.append(title)
                    pending_errors[title] = item.get("delete_error")

        if requested:
            self.items[guild_key] = [
                item for item in self.items[guild_key]
                if item.get("id") not in deleted_ids
            ]
            await self._save_data()

        return CalendarDeleteResult(
            {
                "bulk": True,
                "success": bool(deleted_titles) and not pending_titles,
                "requested_count": len(requested),
                "deleted_count": len(deleted_titles),
                "deleted_titles": deleted_titles,
                "pending_count": len(pending_titles),
                "pending_titles": pending_titles,
                "pending_errors": pending_errors,
            }
        )

    @writable_store
    async def clear_calendar(self, guild_id):
        """Delete all items from the shared calendar (ignoring guild_id)"""
        guild_key = self.scope_key(guild_id, operation='write')
        if guild_key not in self.items or not self.items[guild_key]:
            return {
                "requested_count": 0,
                "deleted_count": 0,
                "failed_count": 0,
                "pending_titles": [],
            }

        items_to_delete = list(self.items[guild_key])
        deleted_ids = set()
        pending_titles = []
        now = datetime.now().isoformat()

        for item in items_to_delete:
            if not self._delete_from_gcal_or_mark_pending(item, now=now, context='clear'):
                pending_titles.append(item.get('title', 'Uten tittel'))
            else:
                deleted_ids.add(item.get('id'))

        self.items[guild_key] = [
            item for item in self.items[guild_key]
            if item.get("id") not in deleted_ids
        ]
        await self._save_data()

        return {
            "requested_count": len(items_to_delete),
            "deleted_count": len(deleted_ids),
            "failed_count": len(pending_titles),
            "pending_titles": pending_titles,
        }

    @writable_store
    def complete_item(self, guild_id, item_num=None, item_id=None):
        """Mark an item as complete (ignoring guild_id for shared calendar)"""
        guild_key = self.scope_key(guild_id, operation='write')
        items = self.get_upcoming(guild_key, days=365)

        if item_id:
            for item in items:
                if item.get("id") == item_id:
                    return AwaitableValue(self._process_completion_sync(guild_key, item))
            return AwaitableValue((False, None, None))

        if item_num is not None and 1 <= item_num <= len(items):
            item = items[item_num - 1]
            return AwaitableValue(self._process_completion_sync(guild_key, item))

        return AwaitableValue((False, None, None))

    @writable_store
    async def complete_item_by_title(self, guild_id, title_search):
        """Mark an item as complete by title matching (ignoring guild_id for shared calendar)"""
        guild_key = self.scope_key(guild_id, operation='write')
        items = self.get_upcoming(guild_key, days=365)

        title_search = title_search.lower()
        for item in items:
            if title_search in item["title"].lower():
                return await self._process_completion(guild_key, item)

        return False, None, None

    @writable_store
    async def complete_items_by_title(self, guild_id, title_search):
        """Mark multiple items as complete by title matching (ignoring guild_id for shared calendar)"""
        guild_key = self.scope_key(guild_id, operation='write')
        items = self.get_upcoming(guild_key, days=365)

        title_search = title_search.lower()
        count = 0
        completed_titles = []
        has_recurring = False

        for item in items:
            if title_search in item["title"].lower():
                success, title, next_date = await self._process_completion(guild_key, item)
                if success:
                    count += 1
                    completed_titles.append(title)
                    if next_date:
                        has_recurring = True

        return count, completed_titles, has_recurring

    @writable_store
    def edit_item(self, index, title=None, date=None, time=None, recurrence=None, description=None, duration_minutes=None, kind=None, timezone=None, fold=None, edit_scope=None):
        """Edit a calendar item by its list number (1-based, matching delete/complete patterns)"""
        guild_key = self.scope_key(operation='write')
        items = self.get_upcoming(guild_key, days=365)

        if index is None or not (1 <= index <= len(items)):
            raise ValueError(f"Ugyldig indeks: {index}")

        item = items[index - 1]
        if item.get('_recurrence_readonly'):
            raise ValueError('unsupported_google_recurrence_readonly')
        if item.get('recurrence') or item.get('series'):
            effect_ids, effect_scopes = {}, {}
            self._recurring_edit(item, {'title': title, 'date': date, 'time': time,
                'recurrence': recurrence, 'description': description, 'duration_minutes': duration_minutes,
                'kind': kind, 'timezone': timezone, 'fold': fold, 'edit_scope': edit_scope}, effect_ids, effect_scopes)
        else:
            self._apply_item_updates(item, title, date, time, recurrence, description, duration_minutes, kind, timezone, fold)
        if not (item.get('recurrence') or item.get('series')):
            self._queue_sync(item, 'update')
        self._save_data_sync()
        return AwaitableDict(item)

    @writable_store
    def edit_item_by_id(self, item_id, title=None, date=None, time=None, recurrence=None, description=None, duration_minutes=None, kind=None, timezone=None, fold=None, edit_scope=None):
        """Edit a calendar item by stable ID, including past/non-upcoming entries."""
        guild_key = self.scope_key(operation='write')
        for item in self.items.get(guild_key, []):
            if item.get("id") == item_id:
                if item.get('_recurrence_readonly'):
                    raise ValueError('unsupported_google_recurrence_readonly')
                if item.get('recurrence') or item.get('series'):
                    effect_ids, effect_scopes = {}, {}
                    self._recurring_edit(item, {'title': title, 'date': date, 'time': time,
                        'recurrence': recurrence, 'description': description, 'duration_minutes': duration_minutes,
                        'kind': kind, 'timezone': timezone, 'fold': fold, 'edit_scope': edit_scope}, effect_ids, effect_scopes)
                else:
                    self._apply_item_updates(item, title, date, time, recurrence, description, duration_minutes, kind, timezone, fold)
                if not (item.get('recurrence') or item.get('series')):
                    self._queue_sync(item, 'update')
                self._save_data_sync()
                return AwaitableDict(item)
        raise ValueError(f"Fant ikke kalenderoppføring med ID: {item_id}")

    @writable_store
    def attach_gcal_metadata(self, item_id, event_id, link):
        for item in self.items.get(self.scope_key(operation='write'), []):
            if item['id'] == item_id:
                item['gcal_event_id'] = event_id
                item['gcal_link'] = link
                self._save_data_sync()
                return AwaitableDict(item)
        raise ValueError('Fant ikke kalenderoppføringen')

    def _apply_item_updates(self, item, title=None, date=None, time=None, recurrence=None, description=None, duration_minutes=None, kind=None, timezone=None, fold=None):
        if title is not None:
            item["title"] = title
        if date is not None:
            item["date"] = self._normalize_date_format(date)
        if time is not None:
            item["time"] = time or None
            item['all_day'] = not bool(time)
        if date is not None or time is not None:
            item['fold'] = None
        for key, value in (('duration_minutes', duration_minutes), ('kind', kind), ('timezone', timezone), ('fold', fold)):
            if value is not None:
                item[key] = value
        if recurrence is not None:
            item["recurrence"] = recurrence
            item.pop("_remote_recurrence_raw", None)
            item.pop("_recurrence_readonly", None)
        if description is not None:
            item["description"] = description
        event_time = EventTime.from_item(item).validate_local()
        item.update(event_time.fields())

    def _sync_item_update_to_gcal(self, item):
        """Compatibility adapter: queue intent; never perform inline provider I/O."""
        self._queue_sync(item, 'update')

    @writable_store
    def search_items(self, query):
        """Search calendar items by title (case-insensitive substring match)"""
        guild_key = self.scope_key(operation='read')
        items = self.items.get(guild_key, [])

        query = query.lower()
        matching = [
            item for item in items
            if not item.get("delete_pending") and not item.get('_mutation_deleted') and query in item.get("title", "").lower()
        ]

        return matching

    def format_search_results(self, query):
        """Format calendar search results for Discord."""
        matches = self.search_items(query)
        if not matches:
            return f"🔎 Fant ingen kalenderoppføringer som matcher **{query}**."

        lines = [f"🔎 **Kalenderoppføringer som matcher \"{query}\":**"]
        upcoming_index_by_id = {
            item.get("id"): index
            for index, item in enumerate(self.get_upcoming(self.scope_key(operation='read'), days=365), 1)
        }
        for item in matches[:10]:
            time_str = f" kl. {item['time']}" if item.get("time") else ""
            status = "✅" if item.get("completed") else "📌"
            index = upcoming_index_by_id.get(item.get("id"))
            prefix = f"`#{item['id'][:8]}` "
            lines.append(f"{status} {prefix}{item.get('title', '')} — _{item.get('date', '')}{time_str}_")

        if len(matches) > 10:
            lines.append(f"\n… og {len(matches) - 10} til.")

        lines.append("\nBruk ID-en for å velge en bestemt oppføring; numre krever en fersk vist kalenderliste.")
        return "\n".join(lines)

    async def _process_completion(self, guild_key, item):
        """Internal helper to handle completion logic"""
        return self._process_completion_sync(guild_key, item)

    def _process_completion_sync(self, guild_key, item):
        if item.get('_recurrence_readonly'):
            raise ValueError('unsupported_google_recurrence_readonly')
        title = item['title']
        next_date = None
        if item.get('recurrence'):
            next_occurrence = self._advance_occurrence(item, 'completed')
            if next_occurrence:
                next_date = next_occurrence[1].original_start.strftime('%d.%m.%Y')
        else:
            item['completed'] = True
        if not (item.get('recurrence') and (item.get('gcal_event_id') or item.get('sync_operations'))):
            self._queue_sync(item, 'update', guild_key)
        self._save_data_sync()
        return True, title, next_date

    @staticmethod
    def _coerce_recurrence_end_date(value):
        if value is None or value == '':
            return None
        if type(value) is date:
            return value
        if not isinstance(value, str):
            raise ValueError('invalid_recurrence_end_date')
        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.strptime(value, '%d.%m.%Y').date()

    def _ensure_series(self, item, *, legacy=True):
        if item.get('series'):
            return Series.from_document(item['series'])
        series = series_from_item(item, legacy=legacy)
        item['series'] = series.to_document()
        item.setdefault('series_next_index', 0)
        item.setdefault('occurrences', {})
        if legacy:
            item['recurrence_migration'] = {
                'status': 'legacy_collapsed',
                'anchor_source': 'stored_current_date',
                'recovered_before_anchor': False,
                'legacy_advanced_count': item.get('completed_count'),
            }
        return series

    def _migrate_legacy_recurrences(self):
        changed = False
        document = self.items
        for bucket in document.values():
            for item in bucket:
                if item.get('recurrence') and not item.get('series'):
                    try:
                        self._ensure_series(item, legacy=True)
                    except (KeyError, TypeError, ValueError):
                        item['recurrence_migration'] = {
                            'status': 'unsupported_legacy_rule',
                            'recovered_before_anchor': False,
                            'raw_rule': item.get('_remote_recurrence_raw', item.get('recurrence')),
                        }
                        item['_recurrence_readonly'] = True
                    changed = True
        if changed:
            self.items = document
        return changed

    @staticmethod
    def _occurrence_records(item):
        records = item.get('occurrences', {})
        if not isinstance(records, dict):
            return {}
        return {key: Occurrence.from_document(value) for key, value in records.items()}

    def _save_occurrence(self, item, occurrence, *, state=None, override=None):
        prior = self._occurrence_records(item).get(occurrence.occurrence_id)
        if prior and prior.original_start != occurrence.original_start:
            raise ValueError('occurrence_exception_identity_mismatch')
        if override is None:
            override = occurrence.override if occurrence.override is not None else prior.override if prior else None
        updated = Occurrence(occurrence.occurrence_id, occurrence.series_id, occurrence.original_start,
            state or occurrence.state, override)
        records = item.setdefault('occurrences', {})
        if updated.occurrence_id not in records and len(records) >= 10000:
            raise ValueError('recurrence_exception_limit')
        records[updated.occurrence_id] = updated.to_document()
        return updated

    def _next_occurrence(self, item, series, index):
        exceptions = self._occurrence_records(item)
        while True:
            occurrence = occurrence_at(series, index)
            if occurrence is None:
                return None
            saved = exceptions.get(occurrence.occurrence_id)
            if saved is None or saved.state == 'planned':
                return index, saved or occurrence
            index += 1

    @staticmethod
    def _apply_occurrence_pointer(item, occurrence):
        local = occurrence.original_start
        value = occurrence.override or {}
        date_value = value.get('date')
        time_value = value.get('time')
        if date_value:
            item['date'] = date_value
        elif occurrence.original_start.tzinfo:
            item['date'] = local.strftime('%d.%m.%Y')
        if 'time' in value:
            item['time'] = time_value or None
        else:
            item['time'] = item.get('series', {}).get('anchor_time', {}).get('time')
        item['fold'] = value.get('fold')
        if 'timezone' in value:
            item['timezone'] = value['timezone']
        if 'duration_minutes' in value:
            item['duration_minutes'] = value['duration_minutes']
        if 'time' in value:
            item['all_day'] = not bool(value['time'])
        item.update(EventTime.from_item(item).validate_local().fields())

    def _calculate_next_date(self, current_date_str, recurrence):
        """Calculate next occurrence date with month-end safety"""
        try:
            current_date = datetime.strptime(current_date_str, "%d.%m.%Y")
            
            if recurrence == "daily":
                next_date = current_date + timedelta(days=1)
            elif recurrence == "weekly":
                next_date = current_date + timedelta(weeks=1)
            elif recurrence == "biweekly":
                next_date = current_date + timedelta(weeks=2)
            elif recurrence == "monthly":
                # Handle month transition safely
                year = current_date.year + (current_date.month // 12)
                month = (current_date.month % 12) + 1
                day = current_date.day
                
                # Clamp day to max days in next month
                import calendar as py_cal
                last_day = py_cal.monthrange(year, month)[1]
                next_date = datetime(year, month, min(day, last_day))
            elif recurrence == "yearly":
                try:
                    next_date = current_date.replace(year=current_date.year + 1)
                except ValueError:
                    # Feb 29 leap year case
                    next_date = current_date.replace(year=current_date.year + 1, day=28)
            else:
                return None
                
            return next_date.strftime("%d.%m.%Y")
        except Exception as e:
            print(f"[CALENDAR] Calendar parse error: {e}")
            return None

    async def sync_from_gcal(self, default_guild_id=None, default_channel_id=None, *, deadline=None):
        import time
        from cal_system.google_calendar_manager import EventLookup
        self.scope_key(operation='write')
        self.last_gcal_sync_error = None
        if not self.ensure_gcal_configured():
            self.last_gcal_sync_error = 'Google Calendar er ikke konfigurert eller koblet til ennå.'
            return 0
        deadline = deadline or time.monotonic() + 20
        revision = self._storage.revision
        document = self.items
        try:
            events = await self._outbox.slot.run(lambda: self.gcal.list_upcoming_events(days=90), deadline=deadline)
            if events is None:
                self.last_gcal_sync_error = 'Kunne ikke hente hendelser fra Google Calendar.'
                return 0
            if not isinstance(events, list):
                raise ValueError('invalid_event_list')
            seen = {key for event in events if isinstance(event, dict)
                    for key in (event.get('id'), event.get('recurringEventId')) if key}
            lookups = {}
            today = self.clock.now().date()
            scope_buckets = self._scope_buckets(operation='write')
            for scope, items in document.items():
                if scope not in scope_buckets:
                    continue
                for item in items:
                    remote_id = item.get('gcal_event_id')
                    if not remote_id or remote_id in seen or item.get('_local_sync_pending') or item.get('_undo_record'):
                        continue
                    try:
                        day = datetime.strptime(item['date'], '%d.%m.%Y').date()
                    except (KeyError, TypeError, ValueError):
                        continue
                    if today <= day <= today + timedelta(days=90) and len(lookups) < 16:
                        def lookup(remote_id=remote_id):
                            try:
                                if hasattr(self.gcal, 'get_event_outcome'):
                                    return self.gcal.get_event_outcome(remote_id)
                                return EventLookup.from_event(remote_id, self.gcal.get_event(remote_id))
                            except Exception as error:
                                try:
                                    return EventLookup.from_error(error)
                                except ImportError:
                                    return EventLookup('unavailable', reason_code='optional_google_dependency_missing')
                        try:
                            lookups[remote_id] = await self._outbox.slot.run(lookup, deadline=deadline)
                        except Exception:
                            lookups[remote_id] = EventLookup('unavailable', reason_code='lookup_deadline')
        except Exception:
            self.last_gcal_sync_error = 'Google-lesing er utilgjengelig eller fristen utløp; lokale oppføringer er bevart.'
            return 0
        return await self._apply_google_pull(events, lookups, revision, default_guild_id, default_channel_id)

    @staticmethod
    def _google_original_start(event, series):
        from zoneinfo import ZoneInfo
        raw = event.get('originalStartTime')
        if not isinstance(raw, dict):
            raise ValueError('missing_google_original_start')
        if raw.get('date'):
            day = date.fromisoformat(raw['date'])
            return datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo(series.anchor_time.timezone))
        instant = datetime.fromisoformat(raw['dateTime'].replace('Z', '+00:00'))
        if instant.tzinfo is None:
            raise ValueError('google_original_start_requires_offset')
        return instant.astimezone(ZoneInfo(series.anchor_time.timezone))

    @staticmethod
    def _google_occurrence_index(series, original_start):
        anchor = series.anchor_time.local_date
        target = original_start.date()
        frequency, interval = series.rule['frequency'], series.rule['interval']
        if target < anchor:
            return None
        if frequency == 'daily':
            relative = (target - anchor).days // interval
        elif frequency in ('weekly', 'biweekly'):
            relative = (target - anchor).days // (7 * interval)
        elif frequency == 'monthly':
            months = (target.year - anchor.year) * 12 + target.month - anchor.month
            relative = months // interval
        else:
            relative = (target.year - anchor.year) // interval
        center = series.index_offset + relative
        for index in range(max(series.index_offset, center - 2), center + 3):
            occurrence = occurrence_at(series, index)
            if occurrence is None:
                break
            if occurrence.original_start == original_start:
                return occurrence
        return None

    @staticmethod
    def _remote_instance_evidence(event):
        keys = ('id', 'recurringEventId', 'originalStartTime', 'status', 'summary', 'start', 'end', 'etag')
        return {key: copy.deepcopy(event[key]) for key in keys if key in event}

    def _preserve_google_instance(self, item, event):
        if item.get('_local_sync_pending') or str(item.get('sync_blocked') or '').startswith('google_'):
            self.last_gcal_sync_error = 'Lokal gjentakelsesendring er bevart; Google-forekomsten krever avklaring.'
            return False
        if not item.get('series') or item.get('_recurrence_readonly'):
            instances = item.setdefault('google_instances', [])
            evidence = self._remote_instance_evidence(event)
            changed = False
            if evidence.get('id') and all(row.get('id') != evidence['id'] for row in instances):
                if len(instances) < 512:
                    instances.append(evidence)
                else:
                    item['google_instances_truncated'] = item.get('google_instances_truncated', 0) + 1
                changed = True
            item['_recurrence_readonly'] = True
            item['recurrence_readable'] = item.get('recurrence_readable') or 'Utvidede Google-forekomster; hovedregelen ble ikke hentet.'
            if not item.get('recurrence_diagnostic'):
                item['recurrence_diagnostic'] = 'google_master_unavailable'
            return changed
        series = Series.from_document(item['series'])
        try:
            original_start = self._google_original_start(event, series)
            occurrence = self._google_occurrence_index(series, original_start)
        except (KeyError, TypeError, ValueError, OverflowError):
            occurrence = None
            original_start = None
        if occurrence is None:
            instances = item.setdefault('google_instances', [])
            evidence = self._remote_instance_evidence(event)
            if evidence.get('id') and len(instances) < 512 and all(row.get('id') != evidence['id'] for row in instances):
                instances.append(evidence)
            elif evidence.get('id') and all(row.get('id') != evidence['id'] for row in instances):
                item['google_instances_truncated'] = item.get('google_instances_truncated', 0) + 1
            item['_recurrence_readonly'] = True
            item['recurrence_diagnostic'] = 'google_instance_outside_supported_series'
            return True
        exceptions = self._occurrence_records(item)
        if event.get('status') == 'cancelled':
            saved = Occurrence(occurrence.occurrence_id, series.series_id, occurrence.original_start,
                'skipped', {'gcal_instance_id': event.get('id')})
            self._save_occurrence(item, saved)
            self._refresh_imported_current_occurrence(item, series, occurrence)
            return True
        try:
            remote_time = EventTime.from_google(event).validate_local()
        except (ValueError, KeyError, TypeError):
            return False
        override = {'gcal_instance_id': event.get('id')}
        if remote_time.local_date != occurrence.original_start.date():
            override['date'] = remote_time.local_date.strftime('%d.%m.%Y')
        if remote_time.local_time != occurrence.original_start.astimezone(
            ZoneInfo(series.anchor_time.timezone)).time().replace(tzinfo=None):
            override['time'] = remote_time.fields()['time']
        if remote_time.timezone != series.anchor_time.timezone:
            override['timezone'] = remote_time.timezone
        if remote_time.duration_minutes != series.anchor_time.duration_minutes:
            override['duration_minutes'] = remote_time.duration_minutes
        title = event.get('summary')
        if title and title != item.get('title'):
            override['title'] = title
        if event.get('description') is not None and event.get('description') != item.get('description', ''):
            override['description'] = event.get('description')
        if len(override) > 1:
            saved = Occurrence(occurrence.occurrence_id, series.series_id, occurrence.original_start,
                'planned', override)
            self._save_occurrence(item, saved)
            self._refresh_imported_current_occurrence(item, series, occurrence)
            return True
        exceptions.pop(occurrence.occurrence_id, None)
        item['occurrences'] = {key: value.to_document() for key, value in exceptions.items()}
        return False

    def _refresh_imported_current_occurrence(self, item, series, imported):
        index = item.get('series_next_index', 0)
        current = occurrence_at(series, index)
        if current is None or current.occurrence_id != imported.occurrence_id:
            return
        pending = self._next_occurrence(item, series, index)
        if pending:
            item['series_next_index'] = pending[0]
            item['completed'] = False
            self._apply_occurrence_pointer(item, pending[1])
        else:
            item['completed'] = True

    def _prepare_google_pull_events(self, events):
        groups = OrderedDict()
        masters = {event.get('id') for event in events if isinstance(event, dict)
            and event.get('id') and not event.get('recurringEventId') and event.get('recurrence')}
        for event in events:
            if isinstance(event, dict) and event.get('recurringEventId'):
                groups.setdefault(event['recurringEventId'], []).append(event)
        opaque = {}
        for master_id, instances in groups.items():
            if master_id in masters:
                continue
            source = next((row for row in instances if isinstance(row.get('start'), dict)), instances[0])
            synthetic = copy.deepcopy(source)
            synthetic['id'] = master_id
            synthetic.pop('recurringEventId', None)
            synthetic['recurrence'] = []
            if not synthetic.get('start') and isinstance(synthetic.get('originalStartTime'), dict):
                synthetic['start'] = copy.deepcopy(synthetic['originalStartTime'])
            synthetic['_expanded_without_master'] = True
            opaque[master_id] = instances
            masters.add(master_id)
            events.append(synthetic)
        prepared = [event for event in events if not (isinstance(event, dict)
            and event.get('recurringEventId') and event.get('recurringEventId') in opaque)]
        return sorted(prepared, key=lambda event: bool(event.get('recurringEventId'))), opaque

    @writable_store
    async def _apply_google_pull(self, gcal_events, lookups, expected_revision, default_guild_id=None, default_channel_id=None):
        """
        Pull events from Google Calendar and sync to local store
        """
        self.scope_key(operation='write')
        if expected_revision != self._storage.revision:
            self.last_gcal_sync_error = 'Kalenderen ble endret under Google-lesing. Ingen innkommende verdier er brukt; prøv en ny synkronisering.'
            return 0
        self._pull_lookups = lookups
        fallback_channel_id = default_channel_id

        added_count = 0
        updated_count = 0
        removed_count = 0

        # Build a map of canonical GCal IDs -> (guild_id, item) for quick lookup.
        # Recurring events arrive as expanded instances whose "id" differs per
        # occurrence, while "recurringEventId" points back to the master event.
        gcal_map = {}
        for guild_id, items in self.items.items():
            if guild_id not in self._scope_buckets(operation='write'):
                continue
            for item in items:
                if item.get("gcal_event_id"):
                    gcal_map[item["gcal_event_id"]] = (guild_id, item)

        for guild_id, items in self.items.items():
            if guild_id not in self._scope_buckets(operation='write'):
                continue
            for item in items:
                for operation in item.get('sync_operations', []):
                    if operation['kind'] == 'create' and operation.get('remote_id'):
                        gcal_map[operation['remote_id']] = (guild_id, item)
        existing_master_ids = set(gcal_map)
        self._gcal_baseline_changed = False
        gcal_events, opaque_instances = self._prepare_google_pull_events(list(gcal_events))
        seen_gcal_ids = set()
        updated_master_ids = set()
        for event in gcal_events:
            if not isinstance(event, dict):
                continue
            gcal_id = event.get("id")
            if not gcal_id:
                continue
            canonical_gcal_id = event.get("recurringEventId") or gcal_id
            if any(item.get('remote_relink_required') and item.get('remote_previous_id') in (gcal_id, canonical_gcal_id)
                   for bucket in self._scope_buckets(operation='write') for item in self.items.get(bucket, [])):
                self.last_gcal_sync_error = 'En lokalt gjenopprettet oppføring krever avklart Google-kobling før import.'
                continue
            seen_gcal_ids.add(gcal_id)
            seen_gcal_ids.add(canonical_gcal_id)
            is_recurring_instance = bool(event.get("recurringEventId"))
            if is_recurring_instance:
                matched = gcal_map.get(canonical_gcal_id)
                if matched:
                    _, root_item = matched
                    changed = self._preserve_google_instance(root_item, event)
                    if changed:
                        updated_count += 1
                    continue

            summary = event.get("summary", "Uten tittel")
            
            # Check if marked as completed in GCal
            gcal_completed = summary.endswith(" [FERDIG]")
            if gcal_completed:
                summary = summary.replace(" [FERDIG]", "").strip()

            start = event.get("start", {})
            
            try:
                remote_time = EventTime.from_google(event)
                remote_time.validate_local()
                date_str = remote_time.local_date.strftime('%d.%m.%Y')
                time_str = remote_time.fields()['time']
            except (ValueError, KeyError, TypeError):
                self.last_gcal_sync_error = 'En Google-oppføring har ugyldig dato/tid; lokal versjon er bevart.'
                continue

            # Extract creator information if available
            creator = event.get("creator", {})
            organizer = event.get("organizer", {})
            
            # Check for Discord metadata in extended properties first
            ext_props = event.get("extendedProperties", {}).get("private", {})
            gcal_username = ext_props.get("discord_username")
            gcal_user_id = ext_props.get("discord_user_id") or "gcal_sync"

            if not gcal_username or gcal_username.lower() == "inebotten":
                # Fallback to Display Name > Email > Default
                gcal_username = creator.get("displayName") or organizer.get("displayName")
                
                if not gcal_username or gcal_username.lower() == "inebotten":
                    email = creator.get("email") or organizer.get("email")
                    if email and self.owner_email and email.lower() == self.owner_email.lower() and self.owner_name:
                        gcal_username = self.owner_name
                    elif email and "@" in email:
                        gcal_username = email.split("@")[0]
                    else:
                        gcal_username = email or self.owner_name or "Google Calendar"
                
            # Final fallback if still empty or generic
            if not gcal_username or gcal_username.lower() in ["google calendar", "inebotten"]:
                gcal_username = self.owner_name or "Google Calendar"

            matched_gcal_key = canonical_gcal_id if canonical_gcal_id in gcal_map else None
            if matched_gcal_key is None and gcal_id in gcal_map:
                matched_gcal_key = gcal_id

            if matched_gcal_key:
                # Existing item, check for updates
                guild_id, item = gcal_map[matched_gcal_key]
                if (item.get('_local_sync_pending') or item.get('_mutation_deleted')
                    or str(item.get('sync_blocked') or '').startswith('google_')):
                    self.last_gcal_sync_error = 'Lokal endring venter på avklart Google-synkronisering; innkommende data er bevart uten overskriving.'
                    continue
                if event.get('etag') and item.get('_remote_etag') != event['etag']:
                    item['_remote_etag'] = event['etag']
                    item['_remote_baseline'] = remote_evidence(event)
                    self._gcal_baseline_changed = True
                if item.get('kind') == 'task':
                    self.last_gcal_sync_error = 'En koblet oppgave krever eksplisitt valg før remote arrangement endrer den.'
                    continue
                changed = False
                if event.get('recurrence'):
                    before_remote = copy.deepcopy(item)
                    self.apply_remote_sync_fields(item,event)
                    changed = item != before_remote
                    if str(item.get('sync_blocked') or '').startswith('google_'):
                        if changed:
                            updated_count += 1
                            updated_master_ids.add(canonical_gcal_id)
                        continue
                if item.get("gcal_event_id") != canonical_gcal_id:
                    item["gcal_event_id"] = canonical_gcal_id
                    changed = True
                
                if item["title"] != summary:
                    item["title"] = summary
                    changed = True
                if item["date"] != date_str:
                    item["date"] = date_str
                    changed = True
                if item.get("time") != time_str:
                    item["time"] = time_str
                    changed = True
                
                for key, value in remote_time.fields().items():
                    if item.get(key) != value:
                        item[key] = value
                        changed = True

                # Update username/user_id if it's currently generic and we found better info
                if item.get("username") == "Google Calendar" and gcal_username != "Google Calendar":
                    item["username"] = gcal_username
                    changed = True
                
                if item.get("user_id") == "gcal_sync" and gcal_user_id != "gcal_sync":
                    item["user_id"] = gcal_user_id
                    changed = True

                if not item.get("channel_id") and fallback_channel_id is not None:
                    item["channel_id"] = str(fallback_channel_id)
                    changed = True
                
                # Check if it was marked as completed in GCal
                if gcal_completed and not item.get("completed"):
                    item["completed"] = True
                    changed = True
            else:
                # New item from GCal
                guild_id = self.scope_key(operation='write')
                
                await self.add_item(
                    guild_id=guild_id,
                    user_id=gcal_user_id,
                    username=gcal_username,
                    title=summary,
                    date_str=date_str,
                    time_str=time_str,
                    gcal_event_id=canonical_gcal_id,
                    gcal_link=event.get("htmlLink"),
                    channel_id=fallback_channel_id,
                    kind=remote_time.kind, timezone=remote_time.timezone, all_day=remote_time.all_day,
                    duration_minutes=remote_time.duration_minutes, fold=remote_time.fold,
                )
                
                if event.get('etag'):
                    self.items[guild_id][-1]['_remote_etag'] = event['etag']
                    self.items[guild_id][-1]['_remote_baseline'] = remote_evidence(event)
                # If it was completed, mark it so (add_item defaults to False)
                if gcal_completed:
                    self.items[str(guild_id)][-1]["completed"] = True
                item = self.items[str(guild_id)][-1]
                gcal_map[canonical_gcal_id] = (guild_id, item)
                added_count += 1

            if event.get('recurrence'):
                before_series = copy.deepcopy(item.get('series'))
                before_recurrence = item.get('recurrence')
                before_raw = copy.deepcopy(item.get('_remote_recurrence_raw'))
                self.apply_remote_sync_fields(item, event)
                if matched_gcal_key and (before_series != item.get('series')
                    or before_recurrence != item.get('recurrence')
                    or before_raw != item.get('_remote_recurrence_raw')):
                    changed = True
            if event.get('_expanded_without_master'):
                item['recurrence'] = None
                item['_recurrence_readonly'] = True
                item['recurrence_readable'] = 'Google sendte utvidede forekomster, men hovedregelen var utilgjengelig.'
                item['recurrence_diagnostic'] = 'google_master_unavailable'
                item['google_instances'] = []
            if matched_gcal_key and changed:
                updated_count += 1
                updated_master_ids.add(canonical_gcal_id)

        for master_id, instances in opaque_instances.items():
            matched = gcal_map.get(master_id)
            if not matched:
                continue
            _, item = matched
            evidence = [self._remote_instance_evidence(event) for event in instances]
            known = {row.get('id') for row in item.get('google_instances', [])}
            additions = [row for row in evidence if row.get('id') not in known]
            if additions:
                available = max(0, 512 - len(item.get('google_instances', [])))
                item['google_instances'] = item.get('google_instances', []) + additions[:available]
                if len(additions) > available:
                    item['google_instances_truncated'] = item.get('google_instances_truncated', 0) + len(additions) - available
                    item['recurrence_diagnostic'] = 'google_instance_limit_reached'
                if not item.get('series'):
                    item['_recurrence_readonly'] = True
                    item['recurrence_readable'] = 'Google sendte utvidede forekomster, men hovedregelen var utilgjengelig.'
                    item['recurrence_diagnostic'] = 'google_master_unavailable'
                seen_gcal_ids.update(row.get('id') for row in evidence if row.get('id'))
                if master_id in existing_master_ids and master_id not in updated_master_ids:
                    updated_count += 1
                    updated_master_ids.add(master_id)

        removed_count = self._remove_missing_gcal_items(seen_gcal_ids, days=90)

        if added_count > 0 or updated_count > 0 or removed_count > 0 or self._gcal_lookup_changed or self._gcal_baseline_changed:
            await self._save_data()
            print(
                f"[CAL] Sync complete: {added_count} added, "
                f"{updated_count} updated, {removed_count} removed"
            )
        
        return added_count + updated_count + removed_count

    def _remove_missing_gcal_items(self, seen_gcal_ids, days=90):
        """Remove local GCal-backed items absent from Google inside the sync window."""
        today = self.clock.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
        cutoff = today + timedelta(days=days)
        removed_count = 0
        self._gcal_lookup_changed = False
        from cal_system.google_calendar_manager import EventLookup

        for guild_id, items in list(self.items.items()):
            if guild_id not in self._scope_buckets(operation='write'):
                continue
            kept_items = []
            for item in items:
                if item.get('_local_sync_pending') or item.get('_undo_record'):
                    kept_items.append(item)
                    continue
                gcal_id = item.get("gcal_event_id")
                if not gcal_id or gcal_id in seen_gcal_ids:
                    if gcal_id in seen_gcal_ids:
                        for key in ("gcal_lookup_status", "gcal_lookup_reason", "gcal_lookup_checked_at"):
                            if key in item:
                                item.pop(key)
                                self._gcal_lookup_changed = True
                    kept_items.append(item)
                    continue

                try:
                    item_date = datetime.strptime(item.get("date", ""), "%d.%m.%Y")
                except (TypeError, ValueError):
                    kept_items.append(item)
                    continue

                if not (today <= item_date <= cutoff):
                    kept_items.append(item)
                    continue

                outcome = getattr(self, '_pull_lookups', {}).get(gcal_id,
                    EventLookup('unavailable', reason_code='lookup_not_completed'))
                if not isinstance(outcome, EventLookup):
                    outcome = EventLookup('unavailable', reason_code='malformed_response')
                if outcome.status not in ("cancelled", "missing"):
                    if outcome.status == "unavailable":
                        item["gcal_lookup_status"] = outcome.status
                        item["gcal_lookup_reason"] = outcome.reason_code
                        item["gcal_lookup_checked_at"] = datetime.now(timezone.utc).isoformat()
                        self._gcal_lookup_changed = True
                        self.last_gcal_sync_error = "Google-oppslag kunne ikke bekreftes; lokale hendelser er beholdt."
                    else:
                        for key in ("gcal_lookup_status", "gcal_lookup_reason", "gcal_lookup_checked_at"):
                            if key in item:
                                item.pop(key)
                                self._gcal_lookup_changed = True
                    kept_items.append(item)
                    continue

                print(f"[CAL] Removed deleted GCal event locally: {item.get('title')}")
                removed_count += 1

            self.items[guild_id] = kept_items

        return removed_count

    @writable_store
    def get_upcoming(self, guild_id, days=30, include_completed=False):
        """
        Get upcoming calendar items (ignoring guild_id for shared calendar)
        """
        guild_key = self.scope_key(guild_id, operation='read')

        if guild_key not in self.items:
            return []

        today = self.clock.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
        cutoff = today + timedelta(days=days)

        upcoming = []
        for item in self.items[guild_key]:
            if item.get("delete_pending") or item.get('_mutation_deleted'):
                continue
            if not include_completed and item.get("completed"):
                continue

            if item.get("date"):
                try:
                    item_date = datetime.strptime(item["date"], "%d.%m.%Y")
                    if include_completed or (today <= item_date <= cutoff):
                        upcoming.append(item)
                except Exception as e:
                    print(f"[CALENDAR] Calendar loop error: {e}")
                    continue

        # Sort by date
        upcoming.sort(key=lambda x: datetime.strptime(x["date"], "%d.%m.%Y"))
        return upcoming

    def format_list(self, guild_id, days=90, show_completed=False, footer=None, *, items=None):
        """
        Format calendar items for display (ignoring guild_id for shared calendar)
        """
        if items is None:
            items = self.get_upcoming(guild_id, days=days, include_completed=False)

        if not items:
            return None

        lines = ["📅 **Kalender:**"]

        for i, item in enumerate(items[:10], 1):
            time_str = f" kl. {item['time']}" if item.get("time") else ""

            if item.get("completed"):
                status_indicator = "✓"
            elif item.get("gcal_event_id") or item.get("gcal_link"):
                status_indicator = "📅"
            else:
                status_indicator = "📌"

            recurrence_str = ""
            if item.get("recurrence"):
                labels = {
                    "weekly": "uke",
                    "biweekly": "2uker",
                    "monthly": "mnd",
                    "yearly": "år",
                }
                if item.get("recurrence_day"):
                    recurrence_str = f" 🔄 {item['recurrence_day'][:3].lower()} {labels.get(item['recurrence'], '')}"
                else:
                    recurrence_str = f" 🔄 {labels.get(item['recurrence'], '')}"
                if item.get('occurrence_id'):
                    recurrence_str += f" · forekomst {item['occurrence_id'][:8]}"
                series = item.get('series') or {}
                end_count = series.get('end_count')
                end_date = series.get('end_date')
                if end_count:
                    recurrence_str += f" · {end_count} forekomster"
                elif end_date:
                    recurrence_str += f" · til {end_date}"
            elif item.get('_recurrence_readonly'):
                readable = str(item.get('recurrence_readable', 'regelen kan ikke tolkes')).replace('\n', ' ')[:180]
                recurrence_str = f" 🔒 Google-gjentakelse beholdt: {readable}"

            title_display = (
                f"~~{item['title']}~~" if item.get("completed") else item["title"]
            )
            
            creator_str = f" ({item.get('username', 'Ukjent')})"

            lines.append(
                f"{status_indicator} **{i}.** `#{item['id'][:8]}` {title_display} — _{item['date']}{time_str}_{creator_str}{recurrence_str}"
            )

        if show_completed:
            all_items = self.items.get(str(guild_id), [])
            completed = [i for i in all_items if i.get("completed")][:3]
            if completed:
                lines.append("\n✅ **Nylig fullført:**")
                for item in completed:
                    lines.append(f"  ✓ ~~{item['title']}~~")

        return "\n".join(lines)

    def format_single_item(self, item):
        """Format a single item for display"""
        time_str = f" kl. {item['time']}" if item.get("time") else ""

        lines = [
            f"✅ **Lagt til i kalenderen!**",
            "",
            f"📌 **{item['title']}**",
            f"📅 {item['date']}{time_str}",
            f"👤 Lagt til av: {item.get('username', 'Ukjent')}",
        ]

        meaning = EventTime.from_item(item)
        lines.append('📋 Oppgave med frist' if meaning.kind == 'task' else '📅 Heldagsarrangement' if meaning.all_day else f'🕘 Tidssone: {meaning.timezone}')
        if meaning.duration_minutes is not None:
            lines.append(f'Varighet: {meaning.duration_minutes} minutter')
        elif not meaning.all_day and meaning.kind == 'event':
            lines.append('Varighet er ikke valgt; oppføringen synkes ikke som et Google-arrangement før varigheten er avklart.')

        if str(item.get('sync_blocked') or '').startswith('google_'):
            lines.append('Google-endringen er ikke sendt; gjentakelsen må avklares eksternt.')

        if item.get("recurrence"):
            labels = {
                "weekly": "hver uke",
                "biweekly": "annenhver uke",
                "monthly": "hver måned",
                "yearly": "hvert år",
            }
            if item.get("recurrence_day"):
                lines.append(
                    f"🔄 Gjentas hver {item['recurrence_day']} ({labels.get(item['recurrence'], item['recurrence'])})"
                )
            else:
                lines.append(
                    f"🔄 Gjentas {labels.get(item['recurrence'], item['recurrence'])}"
                )
            series = item.get('series') or {}
            if series.get('end_count'):
                lines.append(f"Forekomstgrense: {series['end_count']}")
            elif series.get('end_date'):
                lines.append(f"Gjentar til og med: {series['end_date']}")
        elif item.get('_recurrence_readonly'):
            readable = str(item.get('recurrence_readable', '')).replace('\n', ' ')[:180]
            lines.append(f"🔒 Google-gjentakelse beholdt uten lokal omforming: {readable}")

        if item.get("gcal_link"):
            lines.append("")
            lines.append(f"📅 [Se i Google Calendar]({item['gcal_link']})")

        lines.append("")
        lines.append("— *Bruk `@inebotten kalender` for å se alt*")

        return "\n".join(lines)

    def _validate_date_format(self, date_str):
        """Validate DD.MM.YYYY format"""
        try:
            datetime.strptime(date_str, "%d.%m.%Y")
            return True
        except (ValueError, TypeError):
            return False

    def _normalize_date_format(self, date_str):
        """Normalize date-ish values to DD.MM.YYYY when possible."""
        if not isinstance(date_str, str):
            return date_str

        value = date_str.strip().replace("/", ".")
        if self._validate_date_format(value):
            return datetime.strptime(value, "%d.%m.%Y").strftime("%d.%m.%Y")

        match = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", value)
        if not match:
            return date_str

        day = int(match.group(1))
        month = int(match.group(2))
        year_value = match.group(3)
        if year_value is None:
            year = self.clock.now().year
        elif len(year_value) == 2:
            year = 2000 + int(year_value)
        else:
            year = int(year_value)

        try:
            return datetime(year, month, day).strftime("%d.%m.%Y")
        except ValueError:
            return date_str


if __name__ == "__main__":
    # Test
    print("=== Calendar Manager Test ===\n")

    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as tmp:
        storage_path = tmp.name
    manager = CalendarManager(storage_path=storage_path)

    # Add various items
    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Grillfest",
        date_str="28.03.2026",
        time_str="18:00",
    )
    print("Added: Grillfest")

    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Sende meldekort",
        date_str="04.04.2026",
        time_str="10:00",
        recurrence="biweekly",
        recurrence_day="lørdag",
    )
    print("Added: Sende meldekort (recurring)")

    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Kjøpe melk",
        date_str="29.03.2026",
    )
    print("Added: Kjøpe melk")

    print("\n--- Calendar ---")
    print(manager.format_list("test"))

    print("\n--- Complete item #2 ---")
    success, title, next_date = manager.complete_item("test", item_num=2)
    print(f"Completed: {title}, next: {next_date}")

    print("\n--- Calendar after ---")
    print(manager.format_list("test"))

    manager.storage_path.unlink(missing_ok=True)
