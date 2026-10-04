"""Versioned documents with explicit, preserving persistence outcomes."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import wraps
import inspect
import json
import os
from pathlib import Path
from typing import Callable, Literal

from utils.json_storage import write_json_atomic


@dataclass(frozen=True)
class StorageLoad:
    status: Literal['missing', 'valid', 'corrupt', 'unsupported']
    document: dict | None = None
    error_code: str | None = None
    legacy: bool = False


@dataclass(frozen=True)
class StorageCommit:
    ok: bool
    error_code: str | None = None


class StorageMutationError(RuntimeError):
    """A mutation was not committed; callers must not report success."""


def load_document(path: Path, schema_version: int) -> StorageLoad:
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return StorageLoad('missing')
    except OSError:
        return StorageLoad('corrupt', error_code='read_failed')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return StorageLoad('corrupt', error_code='invalid_json')
    if not isinstance(value, dict):
        return StorageLoad('corrupt', error_code='invalid_shape')
    if 'schema_version' not in value:
        return StorageLoad('valid', value, legacy=True)
    version = value.get('schema_version')
    if type(version) is not int or not isinstance(value.get('document'), dict):
        return StorageLoad('corrupt', error_code='invalid_envelope')
    if version != schema_version:
        return StorageLoad('unsupported', error_code='unsupported_schema')
    return StorageLoad('valid', value['document'])


def commit_document(path: Path, document: dict, schema_version: int, *, writer=None) -> StorageCommit:
    """Back up a legacy document before first migration; refuse unsafe inputs."""
    path = Path(path)
    current = load_document(path, schema_version)
    if current.status in ('corrupt', 'unsupported'):
        return StorageCommit(False, 'read_only_' + current.status)
    if not isinstance(document, dict):
        return StorageCommit(False, 'invalid_shape')
    try:
        if current.legacy:
            original = path.read_bytes()
            backup = path.with_name(path.name + '.legacy-v0.bak')
            try:
                descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if backup.read_bytes() != original:
                    return StorageCommit(False, 'backup_conflict')
            else:
                with os.fdopen(descriptor, 'wb') as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
        (writer or write_json_atomic)(path, {'schema_version': schema_version, 'document': document})
        return StorageCommit(True)
    except (OSError, TypeError, ValueError):
        return StorageCommit(False, 'write_failed')


def bucket_records(field: str, *, require_ids: bool = False):
    def validate(document):
        return all(isinstance(records, list) and all(
            isinstance(record, dict) and isinstance(record.get(field), str)
            and (not require_ids or (isinstance(record.get('id'), str) and bool(record['id'])))
            and ('id' not in record or isinstance(record['id'], str))
            for record in records) for records in document.values())
    return validate


def user_records(document):
    return all(isinstance(user, dict)
               and isinstance(user.get('preferences', {}), dict)
               and isinstance(user.get('interests', []), list)
               and isinstance(user.get('last_topics', []), list)
               for user in document.values())


class DocumentOwner:
    """Last committed snapshot and degraded state for one manager's store."""
    def __init__(self, path: Path, validator: Callable[[dict], bool], schema_version=1):
        self.path = path
        self.validator = validator
        self.schema_version = schema_version
        self.state = StorageLoad('missing')
        self.snapshot = {}
        self.load()

    def load(self) -> dict:
        self.state = load_document(self.path, self.schema_version)
        if self.state.status == 'valid' and not self.validator(self.state.document):
            self.state = StorageLoad('corrupt', error_code='invalid_shape')
        self.snapshot = copy.deepcopy(self.state.document or {}) if self.state.status == 'valid' else {}
        return copy.deepcopy(self.snapshot)

    def require_writable(self):
        if self.state.status in ('corrupt', 'unsupported'):
            raise StorageMutationError('read_only_' + self.state.status)

    def commit(self, document: dict, *, writer=None) -> StorageCommit:
        self.require_writable()
        if not self.validator(document):
            return StorageCommit(False, 'invalid_shape')
        result = commit_document(self.path, copy.deepcopy(document), self.schema_version, writer=writer)
        if result.ok:
            self.snapshot = copy.deepcopy(document)
            self.state = StorageLoad('valid', copy.deepcopy(document))
        return result

    def rollback(self) -> dict:
        return copy.deepcopy(self.snapshot)


def writable_store(method):
    """Reject a degraded store before mutations or external side effects."""
    if inspect.iscoroutinefunction(method):
        @wraps(method)
        async def asynchronous(self, *args, **kwargs):
            self._storage.require_writable()
            return await method(self, *args, **kwargs)
        return asynchronous
    @wraps(method)
    def synchronous(self, *args, **kwargs):
        self._storage.require_writable()
        return method(self, *args, **kwargs)
    return synchronous
