"""Versioned documents with explicit, preserving persistence outcomes."""
from __future__ import annotations

import copy
import asyncio
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
import hashlib
import threading
from dataclasses import dataclass
from functools import wraps
import inspect
import json
import os
from pathlib import Path
from typing import Callable, Literal

from utils.json_storage import write_json_atomic
from utils.store_ownership import ProcessOwnership, StoreOwnedError


@dataclass(frozen=True)
class StorageLoad:
    status: Literal['missing', 'valid', 'corrupt', 'unsupported']
    document: dict | None = None
    error_code: str | None = None
    legacy: bool = False
    revision: int = 0


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
    revision = value.get('revision', 0)
    if type(revision) is not int or revision < 0:
        return StorageLoad('corrupt', error_code='invalid_revision')
    return StorageLoad('valid', value['document'], revision=revision)


def commit_document(path: Path, document: dict, schema_version: int, *, writer=None, revision=0) -> StorageCommit:
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
        (writer or write_json_atomic)(path, {'schema_version': schema_version, 'revision': revision, 'document': document})
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


async def store_worker(function, *args, **kwargs):
    """Cancellation cannot release ownership while a file worker is writing."""
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await worker
        raise


def _task_identity():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


class DocumentOwner:
    """One writer, serialized private drafts, copied committed snapshots."""
    def __init__(self, path: Path, validator: Callable[[dict], bool], schema_version=1):
        self.path = Path(path)
        self.validator = validator
        self.schema_version = schema_version
        self.state = StorageLoad('missing')
        self.snapshot = {}
        self.revision = 0
        self._working = {}
        self._mutex = threading.RLock()
        self._publication_lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        self._async_active = False
        self._draft = ContextVar('store_draft', default=None)
        self._ownership = ProcessOwnership(self.path)
        self._owned = False
        self._fingerprint = None
        self.load()

    def _file_fingerprint(self):
        try:
            return hashlib.sha256(self.path.read_bytes()).digest()
        except OSError:
            return None

    def load(self) -> dict:
        with self._mutex:
            self.state = load_document(self.path, self.schema_version)
            if self.state.status == 'valid' and not self.validator(self.state.document):
                self.state = StorageLoad('corrupt', error_code='invalid_shape')
            with self._publication_lock:
                self.snapshot = copy.deepcopy(self.state.document or {}) if self.state.status == 'valid' else {}
                self._working = copy.deepcopy(self.snapshot)
                self.revision = self.state.revision
            self._fingerprint = self._file_fingerprint()
            return copy.deepcopy(self.snapshot)

    def require_writable(self):
        if self.state.status in ('corrupt', 'unsupported'):
            raise StorageMutationError('read_only_' + self.state.status)

    def claim(self):
        self.require_writable()
        if not self._owned:
            try:
                self._ownership.acquire()
            except StoreOwnedError as error:
                raise StorageMutationError('store_owned') from error
            self._owned = True
            if self._file_fingerprint() != self._fingerprint:
                self.load()
                self.require_writable()

    def _nested(self):
        draft = self._draft.get()
        return draft is not None and draft[0] is _task_identity() and draft[1] == threading.get_ident()

    @property
    def data(self):
        draft = self._draft.get()
        # to_thread propagates the transaction for copied worker inputs. A new
        # asyncio task must not inherit mutable access to its parent's draft.
        if draft is not None and (_task_identity() is None or self._nested()):
            return draft[2]
        with self._mutex:
            return copy.deepcopy(self._working)

    @data.setter
    def data(self, value):
        draft = self._draft.get()
        if draft is not None and (_task_identity() is None or self._nested()):
            copied = copy.deepcopy(value)
            draft[2].clear()
            draft[2].update(copied)
        else:
            with self._mutex:
                if self._async_active:
                    raise StorageMutationError('store_busy')
                self._working = copy.deepcopy(value)

    @contextmanager
    def transaction(self, *, write=True, asynchronous=False):
        if self._nested():
            yield True
            return
        with self._mutex:
            if self._async_active and not asynchronous and write:
                raise StorageMutationError('store_busy')
            self.require_writable()
            if write:
                self.claim()
            draft = copy.deepcopy(self._working)
            token = self._draft.set((_task_identity(), threading.get_ident(), draft))
            if asynchronous:
                self._async_active = True
            try:
                yield False
            except BaseException:
                if write:
                    self._working = self.rollback()
                raise
            else:
                if write:
                    self._working = copy.deepcopy(draft)
            finally:
                if asynchronous:
                    self._async_active = False
                self._draft.reset(token)

    @asynccontextmanager
    async def async_transaction(self, *, write=True):
        if self._nested():
            yield True
            return
        async with self._async_lock:
            with self.transaction(write=write, asynchronous=True) as nested:
                yield nested

    def commit(self, document: dict, *, writer=None) -> StorageCommit:
        # Worker inputs must be captured by the caller before scheduling.
        self.require_writable()
        self.claim()
        candidate = copy.deepcopy(document)
        if not self.validator(candidate):
            return StorageCommit(False, 'invalid_shape')
        result = commit_document(self.path, candidate, self.schema_version,
                                 writer=writer, revision=self.revision + 1)
        if result.ok:
            fingerprint = self._file_fingerprint()
            with self._publication_lock:
                self.snapshot = candidate
                self.revision += 1
                self.state = StorageLoad('valid', copy.deepcopy(candidate), revision=self.revision)
                self._fingerprint = fingerprint
        return result

    def rollback(self) -> dict:
        return self.published_snapshot()[1]

    def published_snapshot(self) -> tuple[int, dict]:
        with self._publication_lock:
            return self.revision, copy.deepcopy(self.snapshot)

    def close(self):
        self._ownership.close()
        self._owned = False


class VersionedJsonStore:
    """Revision-checked mutations of private copies, published after commit."""
    def __init__(self, path: Path, validator: Callable[[dict], bool], schema_version=1):
        self.owner = DocumentOwner(path, validator, schema_version)

    def snapshot(self) -> tuple[int, dict]:
        return self.owner.published_snapshot()

    async def mutate(self, expected_revision: int | None, change: Callable[[dict], dict]) -> tuple[int, dict]:
        async with self.owner.async_transaction():
            if expected_revision is not None and expected_revision != self.owner.revision:
                raise StorageMutationError('revision_conflict')
            candidate = change(copy.deepcopy(self.owner.data))
            result = await store_worker(self.owner.commit, copy.deepcopy(candidate))
            if not result.ok:
                raise StorageMutationError(result.error_code)
            self.owner.data = candidate
            return self.snapshot()

    def close(self):
        self.owner.close()


def writable_store(method):
    """Serialize manager operations; only the owner can access a live draft."""
    write = not method.__name__.startswith(('get_active', 'get_completed', 'get_upcoming', 'search_', 'export_', 'get_item'))
    if inspect.iscoroutinefunction(method):
        @wraps(method)
        async def asynchronous(self, *args, **kwargs):
            async with self._storage.async_transaction(write=write) as nested:
                result = await method(self, *args, **kwargs)
                return result if nested else copy.deepcopy(result)
        return asynchronous
    @wraps(method)
    def synchronous(self, *args, **kwargs):
        with self._storage.transaction(write=write) as nested:
            result = method(self, *args, **kwargs)
            return result if nested else copy.deepcopy(result)
    return synchronous
