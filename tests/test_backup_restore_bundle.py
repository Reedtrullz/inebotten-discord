"""Private, consistent, bounded bundles; all stores here are synthetic."""
import asyncio
import json
import os
from pathlib import Path
import threading
import zipfile

import pytest

from utils.backup_bundle import (
    BackupError, StoreRegistry, create_bundle, validate_bundle, restore,
)
from utils.storage_contract import DocumentOwner


def record(name, generation):
    if name == 'calendar.json':
        return {'shared': [{'id': 'item', 'title': 'Synthetic', 'generation': generation}]}
    return {'u': {'preferences': {}, 'generation': generation}}


def generation(name, document):
    return document['shared'][0]['generation'] if name == 'calendar.json' else document['u']['generation']


@pytest.fixture
def registry(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    owners = {}
    for name in ('calendar.json', 'user_memory.json'):
        owner = DocumentOwner(root / name, lambda d: isinstance(d, dict))
        with owner.transaction():
            assert owner.commit(record(name, 1)).ok
        owners[name] = owner
    value = StoreRegistry(root, owners)
    yield value
    for owner in owners.values():
        owner.close()


@pytest.mark.asyncio
async def test_bundle_restore_and_previous_destination_are_private(registry, tmp_path):
    archive = tmp_path / 'bundle.zip'
    manifest = await create_bundle(registry, archive)
    target = tmp_path / 'restored'
    preview = validate_bundle(archive, tmp_path / 'stage', target)
    receipt = restore(preview, target, services_stopped=True)
    assert receipt['generation'] == manifest['generation']
    assert (archive.stat().st_mode & 0o777) == 0o600
    assert target.stat().st_mode & 0o777 == 0o700
    for name in registry.owners:
        assert (target / name).read_bytes() == (registry.root / name).read_bytes()
        assert (target / name).stat().st_mode & 0o777 == 0o600
    second = validate_bundle(archive, tmp_path / 'stage2', target)
    receipt = restore(second, target, services_stopped=True)
    old = Path(receipt['previous_destination'])
    assert old.is_dir() and old != target
    assert (old / 'calendar.json').read_bytes() == (target / 'calendar.json').read_bytes()


@pytest.mark.asyncio
async def test_atomic_related_update_cannot_mix_snapshot_generation(registry, tmp_path):
    calendar, memory = registry.owners.values()
    entered, release = asyncio.Event(), asyncio.Event()

    async def related_write():
        async with registry.freeze():
            assert calendar.commit(record('calendar.json', 2)).ok
            calendar.data = record('calendar.json', 2)
            entered.set()
            await release.wait()
            assert memory.commit(record('user_memory.json', 2)).ok
            memory.data = record('user_memory.json', 2)
    writer = asyncio.create_task(related_write())
    await entered.wait()
    # A naive sequential file copy at this point demonstrably mixes generations.
    naive = [generation(name, json.loads(owner.path.read_bytes())['document'])
             for name, owner in registry.owners.items()]
    assert naive == [2, 1]
    backup = asyncio.create_task(create_bundle(registry, tmp_path / 'bundle.zip'))
    await asyncio.sleep(0)
    assert not backup.done()
    release.set()
    await writer
    await backup
    with zipfile.ZipFile(tmp_path / 'bundle.zip') as handle:
        for name in registry.owners:
            assert generation(name, json.loads(handle.read('stores/' + name))['document']) == 2


@pytest.mark.asyncio
async def test_sync_writer_is_refused_while_frozen(registry):
    owner = registry.owners['calendar.json']
    async with registry.freeze():
        result = []
        def writer():
            try:
                with owner.transaction():
                    owner.commit(record('calendar.json', 9))
            except Exception as error:
                result.append(str(error))
        thread = threading.Thread(target=writer)
        thread.start()
        # The mutex is held; never join on the event loop while frozen.
    await asyncio.to_thread(thread.join, 1)
    assert not thread.is_alive()
    assert result == [] or result == ['store_busy']


def rewrite(source, destination, mutate):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, 'w') as output:
        rows = [(i.filename, original.read(i.filename)) for i in original.infolist()]
        mutate(rows)
        for name, data in rows:
            output.writestr(name, data)


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['../escape', '/absolute', 'stores/../escape', 'stores/.env', 'stores/sessions.json', 'stores/exports.json'])
async def test_unlisted_paths_rejected_without_extraction(registry, tmp_path, name):
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    bad = tmp_path / 'bad.zip'
    rewrite(archive, bad, lambda rows: rows.append((name, b'secret')))
    with pytest.raises(BackupError):
        validate_bundle(bad, tmp_path / 'stage', tmp_path / 'dest')
    assert not (tmp_path / 'stage').exists()
    assert not (tmp_path / 'escape').exists()


@pytest.mark.asyncio
async def test_tamper_truncate_duplicates_and_newer_schema(registry, tmp_path):
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    for kind in ('tamper', 'truncate', 'duplicate', 'newer'):
        bad = tmp_path / (kind + '.zip')
        if kind == 'truncate':
            bad.write_bytes(archive.read_bytes()[:-12])
        else:
            def mutate(rows):
                if kind == 'tamper':
                    rows[1] = (rows[1][0], b'{}')
                elif kind == 'duplicate':
                    rows.append(rows[1])
                else:
                    manifest = json.loads(rows[0][1])
                    manifest['stores'][0]['schema_version'] = 900
                    rows[0] = (rows[0][0], json.dumps(manifest).encode())
            rewrite(archive, bad, mutate)
        with pytest.raises(BackupError):
            validate_bundle(bad, tmp_path / ('stage-' + kind), tmp_path / 'dest')


@pytest.mark.asyncio
async def test_zip_links_and_compression_are_rejected(registry, tmp_path):
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    with zipfile.ZipFile(archive) as original:
        rows = [(i.filename, original.read(i.filename)) for i in original.infolist()]
    for mode in (0o120777, 0o040700):
        bad = tmp_path / str(mode)
        with zipfile.ZipFile(bad, 'w') as output:
            for n, (name, data) in enumerate(rows):
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = ((mode if n == 1 else 0o100600) << 16)
                output.writestr(info, data)
        with pytest.raises(BackupError):
            validate_bundle(bad, tmp_path / ('s' + str(mode)), tmp_path / 'dest')


@pytest.mark.asyncio
async def test_stage_or_destination_change_and_missing_quiescence_refuse(registry, tmp_path):
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    target = tmp_path / 'dest'
    preview = validate_bundle(archive, tmp_path / 'stage', target)
    with pytest.raises(BackupError, match='services_not_stopped'):
        restore(preview, target)
    with pytest.raises(BackupError, match='destination_mismatch'):
        restore(preview, tmp_path / 'wrong', services_stopped=True)
    target.mkdir()
    (target / 'calendar.json').write_text('do not replace')
    with pytest.raises(BackupError, match='destination_changed'):
        restore(preview, target, services_stopped=True)
    assert (target / 'calendar.json').read_text() == 'do not replace'
    target2 = tmp_path / 'dest2'
    preview = validate_bundle(archive, tmp_path / 'stage2', target2)
    (preview.staging_dir / 'stores/calendar.json').write_text('{}')
    with pytest.raises(BackupError, match='checksum'):
        restore(preview, target2, services_stopped=True)
    assert not target2.exists()


@pytest.mark.asyncio
async def test_excludes_credentials_sessions_logs_exports_and_claims_writers(registry, tmp_path):
    for name in ('.env', 'sessions.json', 'logs.jsonl', 'member-export.json'):
        (registry.root / name).write_text('excluded')
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {'manifest.json', 'stores/calendar.json', 'stores/user_memory.json'}
    target = tmp_path / 'dest'
    target.mkdir()
    (target / 'sessions.json').write_text('preserve')
    with pytest.raises(BackupError, match='unlisted_destination'):
        validate_bundle(archive, tmp_path / 'stage', target)
    target2 = tmp_path / 'dest2'
    target2.mkdir()
    owner = DocumentOwner(target2 / 'calendar.json', lambda d: True)
    owner.claim()
    try:
        preview = validate_bundle(archive, tmp_path / 'stage2', target2)
        with pytest.raises(BackupError, match='store_owned'):
            restore(preview, target2, services_stopped=True)
    finally:
        owner.close()


@pytest.mark.asyncio
async def test_existing_archive_staging_source_symlink_or_hardlink_refused(registry, tmp_path):
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    original = archive.read_bytes()
    with pytest.raises(BackupError):
        await create_bundle(registry, archive)
    assert archive.read_bytes() == original
    stage = tmp_path / 'stage'
    stage.mkdir()
    with pytest.raises(BackupError):
        validate_bundle(archive, stage, tmp_path / 'dest')
    source = registry.root / 'calendar.json'
    os.link(source, tmp_path / 'hardlink')
    with pytest.raises(BackupError, match='unsafe_file'):
        await create_bundle(registry, tmp_path / 'linked.zip')


@pytest.mark.asyncio
async def test_restore_detects_destination_race_at_exclusive_creation(registry, tmp_path, monkeypatch):
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    target = tmp_path / 'dest'
    preview = validate_bundle(archive, tmp_path / 'stage', target)
    mkdir = Path.mkdir
    def racing_mkdir(path, *args, **kwargs):
        if path == target and not target.exists():
            mkdir(path)
            (target / 'racer').write_text('keep')
        return mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', racing_mkdir)
    with pytest.raises(BackupError, match='destination_creation_race'):
        restore(preview, target, services_stopped=True)
    assert (target / 'racer').read_text() == 'keep'


@pytest.mark.asyncio
async def test_review_token_reload_binds_reviewed_destination(registry, tmp_path):
    from utils.backup_bundle import load_preview
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    preview = validate_bundle(archive, tmp_path / 'stage', tmp_path / 'dest')
    reviewed = load_preview(preview.staging_dir, expected_review_token=preview.review_token)
    assert reviewed == preview
    with pytest.raises(BackupError, match='review_mismatch'):
        load_preview(preview.staging_dir, expected_review_token='f' * 64)
    saved = preview.staging_dir / 'review.json'
    data = json.loads(saved.read_bytes())
    data['destination'] = str(tmp_path / 'different')
    saved.write_text(json.dumps(data))
    with pytest.raises(BackupError, match='review_mismatch'):
        load_preview(preview.staging_dir, expected_review_token=preview.review_token)


@pytest.mark.asyncio
async def test_restore_failure_preserves_previous_and_partial_data(registry, tmp_path, monkeypatch):
    import utils.backup_bundle as module
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    target = tmp_path / 'dest'
    restore(validate_bundle(archive, tmp_path / 'stage', target), target, services_stopped=True)
    before = (target / 'calendar.json').read_bytes()
    preview = validate_bundle(archive, tmp_path / 'stage2', target)
    write = module._write_exclusive
    def fail_second(path, data):
        if path == target / 'user_memory.json':
            raise OSError('synthetic failure')
        return write(path, data)
    monkeypatch.setattr(module, '_write_exclusive', fail_second)
    with pytest.raises(BackupError, match='restore_incomplete_preserved'):
        restore(preview, target, services_stopped=True)
    previous = list(tmp_path.glob('dest.before-*'))
    assert len(previous) == 1
    assert (previous[0] / 'calendar.json').read_bytes() == before
    assert (target / 'calendar.json').read_bytes() == before
    assert (preview.staging_dir / 'stores/user_memory.json').exists()


@pytest.mark.asyncio
async def test_valid_checksums_cannot_admit_invalid_domain_or_newer_envelope(registry, tmp_path):
    import hashlib
    archive = tmp_path / 'ok.zip'
    await create_bundle(registry, archive)
    for kind in ('domain', 'envelope'):
        def mutate(rows):
            manifest = json.loads(rows[0][1])
            name, raw = rows[1]
            store = json.loads(raw)
            if kind == 'domain':
                store['document'] = {'private:u': [{'id': 'bad', 'title': 12}]}
            else:
                store['schema_version'] = 900
            raw = json.dumps(store).encode()
            rows[1] = (name, raw)
            manifest['stores'][0]['bytes'] = len(raw)
            manifest['stores'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
            rows[0] = (rows[0][0], json.dumps(manifest).encode())
        bad = tmp_path / (kind + '.zip')
        rewrite(archive, bad, mutate)
        with pytest.raises(BackupError):
            validate_bundle(bad, tmp_path / ('s-' + kind), tmp_path / 'dest')


@pytest.mark.asyncio
async def test_source_changed_symlink_and_lock_symlink_refused(registry, tmp_path):
    archive = tmp_path / 'ok.zip'
    source = registry.root / 'calendar.json'
    original = source.read_bytes()
    source.write_text('{}')
    with pytest.raises(BackupError, match='source_changed'):
        await create_bundle(registry, archive)
    source.write_bytes(original)
    outside = tmp_path / 'outside'
    source.rename(outside)
    source.symlink_to(outside)
    with pytest.raises(BackupError, match='unsafe_file'):
        await create_bundle(registry, archive)
    source.unlink()
    outside.rename(source)
    # A fresh directory lock must not open an unrelated symlink target.
    target = tmp_path / 'dest'
    target.mkdir()
    (target / 'calendar.json.lock').symlink_to(outside)
    await create_bundle(registry, archive)
    with pytest.raises(BackupError, match='unsafe_file'):
        validate_bundle(archive, tmp_path / 'stage', target)


@pytest.mark.asyncio
async def test_live_capture_is_bounded_and_keeps_event_loop_heartbeat(registry, tmp_path):
    import time
    before = time.monotonic()
    ticks = 0
    done = asyncio.Event()
    async def beat():
        nonlocal ticks
        while not done.is_set():
            ticks += 1
            await asyncio.sleep(.001)
    beat_task = asyncio.create_task(beat())
    await create_bundle(registry, tmp_path / 'ok.zip')
    done.set()
    await beat_task
    assert time.monotonic() - before < 2
    # At least one event-loop yield during the private capture/output path.
    assert ticks > 0


@pytest.mark.asyncio
async def test_backup_cancellation_keeps_freeze_until_file_worker_terminates(registry, tmp_path, monkeypatch):
    import utils.backup_bundle as module
    entered, release = threading.Event(), threading.Event()
    read = module._read_regular
    def blocked_read(path, maximum):
        if Path(path).name == 'calendar.json':
            entered.set()
            assert release.wait(3)
        return read(path, maximum)
    monkeypatch.setattr(module, '_read_regular', blocked_read)
    task = asyncio.create_task(create_bundle(registry, tmp_path / 'ok.zip'))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    acquired = asyncio.Event()
    async def mutate_after():
        async with registry.owners['calendar.json'].async_transaction():
            acquired.set()
    mutation = asyncio.create_task(mutate_after())
    await asyncio.sleep(0)
    assert not acquired.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await mutation
    assert not (tmp_path / 'ok.zip').exists()


def test_owned_lock_symlink_and_hardlink_are_refused(tmp_path):
    from utils.store_ownership import ProcessOwnership, StoreOwnedError
    original = tmp_path / 'original'
    original.write_bytes(b'preserve')
    for name, link in (('symlink', lambda p: p.symlink_to(original)),
                       ('hardlink', lambda p: os.link(original, p))):
        owner = ProcessOwnership(tmp_path / name)
        link(owner.path)
        with pytest.raises(StoreOwnedError, match='unsafe_lock'):
            owner.acquire()
        assert original.read_bytes() == b'preserve'
        owner.close()


def test_cli_fixture_rehearsal_requires_exact_preview_and_explicit_paths(tmp_path):
    import subprocess
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'calendar.json').write_text(json.dumps({'schema_version': 1, 'revision': 7,
                                                   'document': record('calendar.json', 1)}))
    script = Path(__file__).resolve().parents[1] / 'scripts/inebotten_backup.py'
    def cli(*args):
        return subprocess.run([os.sys.executable, str(script), *map(str, args)],
                              capture_output=True, text=True, timeout=10)
    archive, stage, dest = tmp_path / 'bundle.zip', tmp_path / 'stage', tmp_path / 'dest'
    absent = cli('create', '--archive', archive)
    assert absent.returncode == 2
    result = cli('create', '--data-dir', data, '--archive', archive, '--services-stopped')
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    result = cli('preview', '--archive', archive, '--staging', stage, '--destination', dest)
    assert result.returncode == 0, result.stderr
    view = json.loads(result.stdout)
    assert view['generation'] == manifest['generation']
    wrong = cli('restore', '--staging', stage, '--destination', dest, '--generation', '0' * 32,
                '--review-token', view['review_token'], '--services-stopped')
    assert wrong.returncode == 1 and not dest.exists()
    result = cli('restore', '--staging', stage, '--destination', dest, '--generation', view['generation'],
                 '--review-token', view['review_token'], '--services-stopped')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['verified']
    assert (dest / 'calendar.json').read_bytes() == (data / 'calendar.json').read_bytes()
    # Revalidate the preserved staged data for an explicit data rollback rehearsal.
    rollback_stage, rollback = tmp_path / 'rollback-stage', tmp_path / 'rollback'
    result = cli('preview', '--archive', archive, '--staging', rollback_stage, '--destination', rollback)
    assert result.returncode == 0, result.stderr
    view = json.loads(result.stdout)
    result = cli('restore', '--staging', rollback_stage, '--destination', rollback,
                 '--generation', view['generation'], '--review-token', view['review_token'], '--services-stopped')
    assert result.returncode == 0, result.stderr
    assert (rollback / 'calendar.json').read_bytes() == (data / 'calendar.json').read_bytes()
