import copy
import json
import secrets
import time
from functools import wraps
from typing import Any

from cal_system.mutation_preview import actor_key
from core.request_context import current_request, request_scope


def _records(document):
    return {(bucket, item['id']): (index, item) for bucket, rows in document.items()
            for index, item in enumerate(rows.values() if isinstance(rows, dict) else rows)}


def reversible(method):
    @wraps(method)
    def perform(manager, *args, **kwargs):
        actor = current_request()
        before = copy.deepcopy(manager._storage.data) if actor else None
        result = method(manager, *args, **kwargs)
        if actor is None or before is None:
            return result
        old, new = _records(before), _records(manager._storage.data)
        changed = [key for key in old if old[key][1] != new.get(key, (None, None))[1]]
        if len(changed) != 1:
            return result
        key = changed[0]
        item = old[key][1]
        if (str(item.get('user_id', item.get('created_by_id'))) != actor.user_id
                or item.get('gcal_event_id') or item.get('_planning') or item.get('sync_operations')
                or len(json.dumps(item).encode()) > 65536):
            return result
        entries = getattr(manager, '_local_undo', {})
        now = time.monotonic()
        entries = {token: entry for token, entry in entries.items() if entry['expires'] > now}
        entries[secrets.token_urlsafe(18)] = {'actor': actor_key(actor), 'key': key,
            'index': old[key][0], 'before': copy.deepcopy(item),
            'after': copy.deepcopy(new.get(key, (None, None))[1]),
            'revision': manager._storage.revision, 'expires': now + 300}
        while len(entries) > 32:
            entries.pop(next(iter(entries)))
        manager._local_undo = entries
        return result
    return perform


def undo_hint(manager, actor) -> dict[str, Any] | None:
    if actor is None:
        return None
    for token, entry in reversed(list(getattr(manager, '_local_undo', {}).items())):
        if (entry['actor'] == actor_key(actor) and entry['expires'] > time.monotonic()
                and entry['revision'] == manager._storage.revision):
            return {'token': token, 'expires_in_seconds': max(0, int(entry['expires'] - time.monotonic())),
                    'message': 'Angrer bare lokal oppføring. Sendte varsler og publiserte meldinger beholdes.'}
    return None


def undo_change(manager, actor, token) -> dict[str, Any]:
    entry = getattr(manager, '_local_undo', {}).get(token)
    if not entry or entry['expires'] <= time.monotonic():
        raise ValueError('undo_expired')
    if entry['actor'] != actor_key(actor):
        raise PermissionError('undo_actor_mismatch')
    with request_scope(actor), manager._storage.transaction(write=True):
        bucket, item_id = entry['key']
        if hasattr(manager, '_scope_bucket'):
            manager._scope_bucket(bucket, 'write')
        if manager._storage.revision != entry['revision']:
            raise ValueError('revision_changed')
        document = manager._storage.data
        existing = _records(document).get(entry['key'], (None, None))[1]
        if existing != entry['after']:
            raise ValueError('selection_changed')
        restored = copy.deepcopy(entry['before'])
        rows = document[bucket]
        if isinstance(rows, dict):
            restored['revision'] = max(restored.get('revision', 0), (existing or {}).get('revision', 0)) + 1
            rows[item_id] = restored
        elif existing is None:
            rows.insert(min(entry['index'], len(rows)), restored)
        else:
            rows[next(n for n, item in enumerate(rows) if item['id'] == item_id)] = restored
        manager._storage.data = document
        (manager._save_polls if isinstance(rows, dict) else manager._save_reminders)()
    manager._local_undo.pop(token)
    return {'ok': True, 'item_id': item_id, 'message': 'Lokal oppføring gjenopprettet. Sendte meldinger er ikke trukket tilbake.'}
