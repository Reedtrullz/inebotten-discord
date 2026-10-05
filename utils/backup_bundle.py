"""Bounded private data bundles and explicit quiescent-directory restores.

OS locks protect cooperating writers. A backup generation means one frozen
snapshot cut; it does not imply unrelated store revision numbers are equal.
"""
from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager, ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid
import zipfile

from utils.storage_contract import DocumentOwner, StorageMutationError, load_document, store_worker
from utils.store_ownership import ProcessOwnership, StoreOwnedError

# Deliberately exclude configuration, tokens, sessions, logs, raw exports and
# legacy unowned stores. Never discover files by walking a personal directory.
STORE_SCHEMAS = {name: 1 for name in (
    'calendar.json', 'reminders.json', 'user_memory.json', 'polls.json', 'reminder_log.json',
)}
STORE_SCHEMAS.update({'calendar.json':2,'reminders.json':2,'polls.json':3})
STORE_UPGRADES = {'calendar.json': (1,), 'reminders.json': (1,), 'polls.json': (1,)}


def store_upgrade_versions(name):
    return tuple(version for version in STORE_UPGRADES.get(name, ()) if version < STORE_SCHEMAS[name])
MAX_STORE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 48 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024


class BackupError(RuntimeError):
    """Stable, content-free failure codes suitable for private local diagnostics."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _directory(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        if node.is_symlink():
            raise BackupError('unsafe_directory')
        if node.exists() and not node.is_dir():
            raise BackupError('unsafe_directory')
    return path


def _read_regular(path, maximum):
    try:
        before = Path(path).lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise BackupError('unsafe_file')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as handle:
            opened = os.fstat(handle.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise BackupError('file_changed')
            data = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
        if len(data) > maximum or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise BackupError('file_changed')
        return data
    except OSError as error:
        raise BackupError('file_read_failed') from error


class StoreRegistry:
    """Explicit initialized owners; mutations spanning owners use this same cut."""
    def __init__(self, root, owners):
        self.root = _directory(root)
        self.owners = dict(owners)
        if not self.owners or set(self.owners) - STORE_SCHEMAS.keys():
            raise BackupError('unlisted_store')
        if len({id(owner) for owner in self.owners.values()}) != len(self.owners):
            raise BackupError('duplicate_owner')
        for name, owner in self.owners.items():
            if (not isinstance(owner, DocumentOwner)
                    or owner.path.absolute() != self.root / name
                    or owner.schema_version != STORE_SCHEMAS[name]):
                raise BackupError('registry_mismatch')

    @asynccontextmanager
    async def freeze(self):
        # Match the normal owner async -> thread-mutex acquisition order.
        # No await involving provider I/O is permitted inside this cut.
        async with AsyncExitStack() as stack:
            try:
                for name in sorted(self.owners):
                    await stack.enter_async_context(self.owners[name].async_transaction())
                yield
            except StorageMutationError as error:
                raise BackupError(str(error)) from error

    def close(self):
        for owner in self.owners.values():
            owner.close()


def _validators():
    from cal_system.mutation_preview import validate_calendar_document
    from cal_system.reminder_manager import ReminderManager
    from features.poll_manager import validate_poll_document
    from memory.user_memory import validate_memory
    return {
        'calendar.json': validate_calendar_document,
        'reminders.json': ReminderManager._validate_document,
        'polls.json': validate_poll_document,
        'user_memory.json': validate_memory,
        'reminder_log.json': lambda d: all(isinstance(d.get(k, {}), dict)
                                         for k in ('reminders_sent', 'digest_log', 'deliveries')),
    }


def registry_for_directory(root):
    """CLI registry: only existing owned stores; stop services before using it."""
    root = _directory(root)
    owners = {}
    try:
        for name, validator in _validators().items():
            if (root / name).exists() or (root / name).is_symlink():
                _read_regular(root / name, MAX_STORE_BYTES)
                owners[name] = DocumentOwner(root / name, validator, schema_version=STORE_SCHEMAS[name],
                                            upgrade_from=store_upgrade_versions(name))
        return StoreRegistry(root, owners)
    except BaseException:
        for owner in owners.values():
            owner.close()
        raise


async def create_bundle(store_registry, destination):
    destination = Path(destination).absolute()
    _directory(destination.parent)
    if destination.parent == store_registry.root:
        raise BackupError('bundle_must_be_outside_store_directory')
    files, rows = {}, []
    async with store_registry.freeze():
        for name in sorted(store_registry.owners):
            owner = store_registry.owners[name]
            revision, document = owner.published_snapshot()
            if owner.path.exists():
                raw = await store_worker(_read_regular, owner.path, MAX_STORE_BYTES)
                # Claims reload stale unowned owners. An external uncooperative
                # edit after claim must not silently substitute another file.
                if _digest(raw) != (owner._fingerprint or b'').hex():
                    raise BackupError('source_changed')
            else:
                raw = _json({'schema_version': owner.schema_version,
                             'revision': revision, 'document': document})
            value = json.loads(raw)
            if 'schema_version' not in value:
                # Preserve legacy source bytes; normalize only the bundle copy.
                raw = _json({'schema_version': owner.schema_version,
                             'revision': revision, 'document': value})
            elif value['schema_version'] in owner.upgrade_from:
                # Export a validated upgraded snapshot without mutating the
                # source envelope or consuming its preserving migration backup.
                raw = _json({'schema_version': owner.schema_version,
                             'revision': revision, 'document': document})
            if len(raw) > MAX_STORE_BYTES:
                raise BackupError('store_too_large')
            files['stores/' + name] = raw
            row = {'name': name, 'schema_version': owner.schema_version,
                   'revision': revision, 'bytes': len(raw), 'sha256': _digest(raw)}
            _check_document(raw, row)
            rows.append(row)
    manifest = {'format_version': 1, 'generation': uuid.uuid4().hex,
                'created_at': datetime.now(timezone.utc).isoformat(), 'stores': rows,
                'exclusions': ['credentials', 'console_sessions', 'raw_logs', 'exports', 'unowned_stores']}
    # Disk output is outside the freeze, from the immutable captured cut.
    await store_worker(_write_bundle, destination, manifest, files)
    return manifest


def _write_bundle(destination, manifest, files):
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise BackupError('destination_exists_or_unwritable') from error
    try:
        with os.fdopen(descriptor, 'w+b') as output:
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
                for name, raw in {'manifest.json': _json(manifest), **files}.items():
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = 0o100600 << 16
                    archive.writestr(info, raw)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, ValueError) as error:
        raise BackupError('bundle_write_failed') from error


def _manifest(data):
    try:
        value = json.loads(data)
        if (not isinstance(value, dict) or value.get('format_version') != 1
                or not isinstance(value.get('generation'), str)
                or not re.fullmatch('[0-9a-f]{32}', value['generation'])
                or not isinstance(value.get('stores'), list)
                or not 1 <= len(value['stores']) <= len(STORE_SCHEMAS)):
            raise BackupError('invalid_manifest')
        names = set()
        for row in value['stores']:
            if (not isinstance(row, dict) or row.get('name') not in STORE_SCHEMAS
                    or row['name'] in names
                    or type(row.get('schema_version')) is not int
                    or row['schema_version'] not in (STORE_SCHEMAS[row['name']], *store_upgrade_versions(row['name']))
                    or type(row.get('revision')) is not int or row['revision'] < 0
                    or type(row.get('bytes')) is not int or not 1 <= row['bytes'] <= MAX_STORE_BYTES
                    or not isinstance(row.get('sha256'), str)
                    or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
                raise BackupError('unsupported_or_invalid_store')
            names.add(row['name'])
        return value
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise BackupError('invalid_manifest') from error


def _check_document(raw, row):
    if len(raw) != row['bytes'] or _digest(raw) != row['sha256']:
        raise BackupError('checksum_mismatch')
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
                or value.get('schema_version') != row['schema_version']
                or type(value.get('revision')) is not int or value['revision'] != row['revision']
                or not isinstance(value.get('document'), dict)):
            raise BackupError('invalid_document')
        if not _validators()[row['name']](value['document']):
            raise BackupError('invalid_store_document')
    except (ValueError, TypeError, RecursionError, AttributeError) as error:
        raise BackupError('invalid_document') from error


def _inventory(destination):
    destination = _directory(destination)
    if not destination.exists():
        return None
    state = destination.stat()
    files = []
    for path in sorted(destination.iterdir()):
        if path.name.endswith('.lock') and path.name[:-5] in STORE_SCHEMAS:
            _read_regular(path, MAX_MANIFEST_BYTES)
            continue
        if path.name not in STORE_SCHEMAS:
            raise BackupError('unlisted_destination')
        raw = _read_regular(path, MAX_STORE_BYTES)
        loaded = load_document(path, STORE_SCHEMAS[path.name], upgrade_from=store_upgrade_versions(path.name))
        if loaded.status != 'valid':
            raise BackupError('read_only_destination')
        metadata = path.stat()
        files.append((path.name, metadata.st_dev, metadata.st_ino, _digest(raw)))
    return (state.st_dev, state.st_ino, tuple(files))


@dataclass(frozen=True)
class RestorePreview:
    staging_dir: Path
    destination: Path
    generation: str
    schema_versions: tuple
    checksums: tuple
    warnings: tuple
    _manifest_hash: str
    _stage_identity: tuple
    _destination_inventory: tuple | None

    @property
    def review_token(self):
        return _digest(_json(_preview_record(self)))


def _preview_record(preview):
    return {'format_version': 1, 'staging_dir': str(preview.staging_dir),
            'destination': str(preview.destination), 'generation': preview.generation,
            'schema_versions': preview.schema_versions, 'checksums': preview.checksums,
            'warnings': preview.warnings, 'manifest_hash': preview._manifest_hash,
            'stage_identity': preview._stage_identity,
            'destination_inventory': preview._destination_inventory}


def load_preview(staging_dir, *, expected_review_token):
    stage = _directory(staging_dir)
    raw = _read_regular(stage / 'review.json', MAX_MANIFEST_BYTES)
    try:
        record = json.loads(raw)
        if _digest(_json(record)) != expected_review_token or record.get('format_version') != 1:
            raise BackupError('review_mismatch')
        inventory = record['destination_inventory']
        if inventory is not None:
            inventory = (inventory[0], inventory[1], tuple(tuple(row) for row in inventory[2]))
        preview = RestorePreview(Path(record['staging_dir']), Path(record['destination']), record['generation'],
                                 tuple(tuple(row) for row in record['schema_versions']),
                                 tuple(tuple(row) for row in record['checksums']), tuple(record['warnings']),
                                 record['manifest_hash'], tuple(record['stage_identity']), inventory)
        if preview.staging_dir != stage or preview.review_token != expected_review_token:
            raise BackupError('review_mismatch')
        _stage_files(preview)
        return preview
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, AttributeError) as error:
        raise BackupError('invalid_review') from error


def validate_bundle(archive, staging_dir, destination):
    staging_dir, destination = _directory(staging_dir), _directory(destination)
    if staging_dir == destination or destination in staging_dir.parents or staging_dir in destination.parents:
        raise BackupError('overlapping_stage_destination')
    target_inventory = _inventory(destination)
    # Open a bounded immutable archive snapshot. Never extractall; unknown files,
    # duplicate names, compressed/encrypted rows and nonregular types are refused.
    raw_archive = _read_regular(archive, MAX_BUNDLE_BYTES)
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(raw_archive)) as bundle:
            infos = bundle.infolist()
            names = [i.filename for i in infos]
            if (not 2 <= len(infos) <= len(STORE_SCHEMAS) + 1
                    or len(set(names)) != len(names) or 'manifest.json' not in names):
                raise BackupError('invalid_archive_members')
            for info in infos:
                mode = info.external_attr >> 16
                if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1
                        or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                        or info.file_size > (MAX_MANIFEST_BYTES if info.filename == 'manifest.json' else MAX_STORE_BYTES)):
                    raise BackupError('unsafe_archive_member')
            manifest_bytes = bundle.read('manifest.json')
            manifest = _manifest(manifest_bytes)
            expected = {'stores/' + row['name'] for row in manifest['stores']}
            if set(names) != expected | {'manifest.json'}:
                raise BackupError('unlisted_archive_member')
            files = {}
            for row in manifest['stores']:
                data = bundle.read('stores/' + row['name'])
                _check_document(data, row)
                files[row['name']] = data
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as error:
        raise BackupError('invalid_archive') from error
    try:
        staging_dir.mkdir(mode=0o700)
    except OSError as error:
        raise BackupError('staging_exists_or_unwritable') from error
    try:
        (staging_dir / 'stores').mkdir(mode=0o700)
        for name, data in {'manifest.json': manifest_bytes, **{'stores/' + n: d for n, d in files.items()}}.items():
            _write_exclusive(staging_dir / name, data)
    except BaseException:
        # Only our exclusively created stage; no personal directory cleanup.
        shutil.rmtree(staging_dir)
        raise
    state = staging_dir.stat()
    preview = RestorePreview(staging_dir, destination, manifest['generation'],
                          tuple((r['name'], r['schema_version']) for r in manifest['stores']),
                          tuple((r['name'], r['sha256']) for r in manifest['stores']),
                          ('Privat data. Gjenoppretting sletter ikke sikkerhetskopier eller eksterne kopier.',
                           'Stopp alle tjenester og lesere før gjenoppretting. Låsene beskytter bare samarbeidende skrivere.'),
                          _digest(manifest_bytes), (state.st_dev, state.st_ino), target_inventory)
    _write_exclusive(staging_dir / 'review.json', _json(_preview_record(preview)))
    return preview


def _write_exclusive(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _stage_files(preview):
    stage = _directory(preview.staging_dir)
    state = stage.stat()
    if (state.st_dev, state.st_ino) != preview._stage_identity:
        raise BackupError('staging_changed')
    data = _read_regular(stage / 'manifest.json', MAX_MANIFEST_BYTES)
    if _digest(data) != preview._manifest_hash:
        raise BackupError('manifest_changed')
    manifest = _manifest(data)
    if manifest['generation'] != preview.generation:
        raise BackupError('generation_mismatch')
    if set(p.name for p in stage.iterdir()) != {'stores', 'manifest.json', 'review.json'}:
        raise BackupError('staging_changed')
    store_dir = _directory(stage / 'stores')
    if set(p.name for p in store_dir.iterdir()) != {r['name'] for r in manifest['stores']}:
        raise BackupError('staging_changed')
    files = {}
    for row in manifest['stores']:
        raw = _read_regular(store_dir / row['name'], MAX_STORE_BYTES)
        _check_document(raw, row)
        files[row['name']] = raw
    return files


def _recheck_destination(preview, destination):
    try:
        current = _inventory(destination)
    except BackupError as error:
        raise BackupError('destination_changed') from error
    if current != preview._destination_inventory:
        raise BackupError('destination_changed')


def restore(preview, expected_destination, *, services_stopped=False):
    if not services_stopped:
        raise BackupError('services_not_stopped')
    destination = _directory(expected_destination)
    if destination != preview.destination:
        raise BackupError('destination_mismatch')
    files = _stage_files(preview)
    _recheck_destination(preview, destination)
    previous = None
    with ExitStack() as stack:
        def claim(path):
            lock = ProcessOwnership(path)
            try:
                lock.acquire()
            except StoreOwnedError as error:
                raise BackupError('store_owned') from error
            stack.callback(lock.close)
        # One restore coordinator in the parent, plus all current writer locks.
        claim(destination.parent / ('.' + destination.name + '.restore'))
        if destination.exists():
            for name in sorted(STORE_SCHEMAS):
                claim(destination / name)
            _recheck_destination(preview, destination)
            previous = destination.with_name(destination.name + '.before-' + uuid.uuid4().hex)
            if previous.exists():
                raise BackupError('previous_destination_exists')
            os.rename(destination, previous)
            os.chmod(previous, 0o700)
        try:
            # Exclusive creation cannot overwrite a concurrent empty directory.
            destination.mkdir(mode=0o700)
        except OSError as error:
            # Preserve old destination and any raced destination for explicit
            # recovery. Never delete/overwrite the racer's evidence.
            raise BackupError('destination_creation_race') from error
        try:
            for name in sorted(STORE_SCHEMAS):
                claim(destination / name)
            for name, raw in files.items():
                _write_exclusive(destination / name, raw)
            for name, raw in files.items():
                if _read_regular(destination / name, MAX_STORE_BYTES) != raw:
                    raise BackupError('restore_verification_failed')
        except (OSError, BackupError) as error:
            # Partial destination and previous generation remain recoverable.
            raise BackupError('restore_incomplete_preserved') from error
    return {'generation': preview.generation, 'destination': str(destination),
            'previous_destination': str(previous) if previous else None,
            'checksums': dict(preview.checksums), 'verified': True}
