"""Bounded, inert calendar proposals; persistent inverses live with their items."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
import copy
import json
import secrets


@dataclass(frozen=True)
class MutationPreview:
    token: str
    revision: int
    expires_at: datetime
    effects: list[dict]


def actor_key(actor):
    if actor is None or not actor.user_id:
        raise PermissionError('actor_required')
    return [actor.user_id, actor.channel_id, actor.guild_id, actor.channel_kind]


def before_image(item):
    return copy.deepcopy({key: value for key, value in item.items() if key != '_undo_record'})


def validate_calendar_document(document):
    from utils.storage_contract import bucket_records
    from cal_system.recurrence import Occurrence, Series
    if not bucket_records('title', require_ids=True)(document):
        return False
    for items in document.values():
        for item in items:
            if 'series' in item:
                try:
                    series = Series.from_document(item['series'])
                    index = item.get('series_next_index', 0)
                    occurrences = item.get('occurrences', {})
                    history = item.get('series_history', [])
                    if (series.series_id != item['id'] or type(index) is not int or index < 0
                        or not isinstance(occurrences, dict) or len(occurrences) > 10000
                        or not isinstance(history, list) or len(history) > 64):
                        return False
                    for key, raw in occurrences.items():
                        occurrence = Occurrence.from_document(raw)
                        if key != occurrence.occurrence_id or occurrence.series_id != series.series_id:
                            return False
                    for record in history:
                        if (not isinstance(record, dict) or type(record.get('through_index')) is not int
                            or record['through_index'] < -1
                            or Series.from_document(record.get('series')).series_id != series.series_id):
                            return False
                except (ValueError, TypeError, KeyError, AttributeError):
                    return False
            elif any(key in item for key in ('series_next_index', 'occurrences', 'series_history')):
                return False
            remote_instances = item.get('google_instances')
            if remote_instances is not None and (not isinstance(remote_instances, list) or len(remote_instances) > 512
                or any(not isinstance(entry, dict) for entry in remote_instances)):
                return False
            truncated = item.get('google_instances_truncated', 0)
            if type(truncated) is not int or truncated < 0:
                return False
            operations = item.get('sync_operations', [])
            if not isinstance(operations, list) or len(operations) > 8:
                return False
            try:
                from cal_system.sync_outbox import SyncOperation, MAX_OPERATION_BYTES
                for raw in operations:
                    op = SyncOperation.from_document(raw)
                    if op.item_id != item['id'] or len(json.dumps(raw).encode()) > MAX_OPERATION_BYTES:
                        return False
            except (ValueError, TypeError, KeyError, AttributeError):
                return False
            if '_mutation_deleted' in item and type(item['_mutation_deleted']) is not bool:
                return False
            if '_local_sync_pending' in item and item['_local_sync_pending'] not in ('delete', 'update', 'create'):
                return False
            record = item.get('_undo_record')
            if record is None:
                continue
            if not isinstance(record, dict):
                return False
            before = record.get('before')
            actor = record.get('actor')
            try:
                expiry = datetime.fromisoformat(record['expires_at'])
                valid = (expiry.tzinfo is not None and isinstance(before, dict)
                    and before.get('id') == item['id'] and isinstance(before.get('title'), str)
                    and '_undo_record' not in before and isinstance(actor, list) and len(actor) == 4
                    and all(isinstance(actor[n], str) and actor[n] for n in (0, 1, 3))
                    and (actor[2] is None or isinstance(actor[2], str))
                    and type(record.get('revision')) is int and record['revision'] >= 1
                    and type(record.get('batch_size')) is int and 1 <= record['batch_size'] <= 256
                    and isinstance(record.get('token'), str) and len(record['token']) == 32)
                if not valid:
                    return False
            except (KeyError, TypeError, ValueError):
                return False
    return True


class PreviewCache:
    def __init__(self, clock, *, ttl=300, capacity=32, max_items=256, max_bytes=1048576):
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self.max_items, self.max_bytes = max_items, max_bytes
        self.entries = OrderedDict()

    def create(self, actor, scope_id, revision, operation, before, after):
        if not before or len(before) > self.max_items:
            raise ValueError('invalid_selection_size')
        if len(json.dumps([before, after], ensure_ascii=False).encode()) > self.max_bytes:
            raise ValueError('selection_too_large')
        token = secrets.token_urlsafe(18)
        expires = self.clock.now() + timedelta(seconds=self.ttl)
        effects = [{'item_id': a['id'], 'title': a['title'], 'operation': operation,
                    'before': copy.deepcopy(a), 'after': copy.deepcopy(b),
                    'remote_pending': bool(a.get('gcal_event_id'))}
                   for a, b in zip(before, after)]
        self.entries[token] = {'actor': actor_key(actor), 'scope': scope_id,
            'revision': revision, 'operation': operation, 'before': copy.deepcopy(before),
            'after': copy.deepcopy(after), 'expires': expires,
            'deadline': self.clock.monotonic() + self.ttl}
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
        return MutationPreview(token, revision, expires, effects)

    def get(self, actor, token):
        entry = self.entries.get(token)
        if entry is None:
            raise ValueError('preview_missing')
        if entry['actor'] != actor_key(actor):
            raise PermissionError('preview_actor_mismatch')
        if self.clock.monotonic() >= entry['deadline'] or self.clock.now() >= entry['expires']:
            self.entries.pop(token, None)
            raise ValueError('preview_expired')
        return copy.deepcopy(entry)
