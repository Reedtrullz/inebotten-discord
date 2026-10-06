"""Ownership, copied worker inputs and serialization using synthetic stores."""
import asyncio
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_manager import ReminderManager
from memory.user_memory import UserMemory
from utils.storage_contract import StorageMutationError
from web_console.console_store import ConsoleStore


@pytest.mark.asyncio
async def test_barrier_updates_preserve_both_changes(tmp_path, monkeypatch):
    memory = UserMemory(tmp_path/'memory.json')
    await memory.set_location('u', 'Oslo')
    entered, release = threading.Event(), threading.Event()
    from memory.user_memory import write_json_atomic
    writes = []
    def paused_writer(path, document):
        writes.append(document)
        if len(writes) == 1:
            entered.set()
            assert release.wait(5)
        write_json_atomic(path, document)
    monkeypatch.setattr('memory.user_memory.write_json_atomic', paused_writer)
    first = asyncio.create_task(memory.set_location('u', 'Bergen'))
    assert await asyncio.to_thread(entered.wait, 5)
    second = asyncio.create_task(memory.add_interest('u', 'piano'))
    await asyncio.sleep(0)
    assert memory.memory['u']['location'] == 'Oslo', 'uncommitted state leaked'
    release.set()
    await asyncio.gather(first, second)
    persisted = json.loads(memory.storage_path.read_text())['document']['u']
    assert persisted['location'] == 'Bergen'
    assert persisted['interests'] == ['piano']
    assert writes[0]['document']['u']['interests'] == [], 'worker input mutated later'


def test_worker_sees_immutable_snapshot(tmp_path):
    reminders = ReminderManager(tmp_path/'reminders.json')
    reminders.add_reminder('g', 'u', 'Tester', 'Original')
    exported = reminders.get_active_reminders('g')
    exported[0]['text'] = 'External mutation'
    raw = reminders.reminders
    raw['g'][0]['text'] = 'Raw external mutation'
    assert reminders.get_active_reminders('g')[0]['text'] == 'Original'
    assert json.loads(reminders.storage_path.read_text())['document']['g'][0]['text'] == 'Original'


def test_second_process_refused_before_mutation(tmp_path):
    manager = ReminderManager(tmp_path/'reminders.json')
    manager.add_reminder('g', 'u', 'Tester', 'First writer')
    original = manager.storage_path.read_bytes()
    script = '''import sys
from cal_system.reminder_manager import ReminderManager
from utils.storage_contract import StorageMutationError
manager = ReminderManager(sys.argv[1])
try:
    manager.add_reminder('g', 'u', 'Tester', 'Second writer')
except StorageMutationError as error:
    assert str(error) == 'store_owned'
else:
    raise AssertionError('second writer accepted')
assert len(manager.reminders['g']) == 1
'''
    result = subprocess.run([os.sys.executable, '-c', script, str(manager.storage_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert manager.storage_path.read_bytes() == original


def test_interrupted_commit_keeps_old_or_new_document(tmp_path, monkeypatch):
    manager = ReminderManager(tmp_path/'reminders.json')
    manager.add_reminder('g', 'u', 'Tester', 'Original')
    original = manager.storage_path.read_bytes()
    def interrupted(*args, **kwargs):
        raise OSError('simulated interruption before replace')
    monkeypatch.setattr('utils.json_storage.os.replace', interrupted)
    with pytest.raises(StorageMutationError, match='write_failed'):
        manager.edit_reminder('g', 1, title='Never published')
    assert manager.storage_path.read_bytes() == original
    assert manager.get_active_reminders('g')[0]['text'] == 'Original'
    assert list(tmp_path.glob('.*.tmp')) == []


def test_console_merge_is_in_transaction(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    store = ConsoleStore()
    entered, release, second_read = threading.Event(), threading.Event(), threading.Event()
    original_writer = __import__('web_console.console_store', fromlist=['write_json_atomic']).write_json_atomic
    original_reader = store._load_stats_raw
    reads = 0
    def reader():
        nonlocal reads
        result = original_reader()
        reads += 1
        if reads == 1:
            entered.set()
            assert release.wait(5)
        else:
            second_read.set()
        return result
    def writer(path, document):
        original_writer(path, document)
    monkeypatch.setattr(store, '_load_stats_raw', reader)
    monkeypatch.setattr('web_console.console_store.write_json_atomic', writer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.save_stats, {'chat': {'count': 1}}, {})
        assert entered.wait(5)
        second = pool.submit(store.save_stats, {'chat': {'count': 1}}, {})
        second_read.wait(.1)  # New implementation holds the whole transaction lock.
        release.set()
        assert first.result(5) and second.result(5)
    assert store.load_intent_stats()['chat']['count'] == 2


@pytest.mark.asyncio
async def test_versioned_mutation_rejects_stale_revision_and_copies(tmp_path):
    from utils.storage_contract import VersionedJsonStore
    store = VersionedJsonStore(tmp_path/'document.json', lambda d: True)
    rev, before = store.snapshot()
    first_rev, _ = await store.mutate(rev, lambda d: {**d, 'a': {'value': 1}})
    first_snapshot = store.snapshot()[1]
    first_snapshot['a']['value'] = 99
    with pytest.raises(StorageMutationError, match='revision_conflict'):
        await store.mutate(rev, lambda d: {'lost': True})
    second_rev, result = await store.mutate(first_rev, lambda d: {**d, 'b': 2})
    assert second_rev > first_rev and before == {}
    assert result == {'a': {'value': 1}, 'b': 2}
    store.close()


@pytest.mark.asyncio
async def test_calendar_handler_persists_intent_then_worker_receipt_on_owned_record(tmp_path):
    import time
    from features.calendar_handler import CalendarHandler
    from memory.localization import Localization
    from tests.test_gcal_outbox import FakeProvider
    remote = FakeProvider()
    manager = CalendarManager(storage_path=tmp_path/'calendar.json', gcal_manager=remote)
    handler = CalendarHandler(SimpleNamespace(calendar=manager, nlp_parser=None, rate_limiter=None, loc=Localization(), client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(guild=SimpleNamespace(id='g'), channel=SimpleNamespace(id='c'), author=SimpleNamespace(id='u', name='Tester'))
    await handler.handle_calendar_item(message, {'title': 'Linked', 'date': '01.01.2027'})
    item = json.loads(manager.storage_path.read_text())['document']['shared'][0]
    assert item['gcal_event_id'] is None
    assert item['sync_operations'][0]['state'] == 'pending'
    assert remote.calls == []
    await manager.process_due(deadline=time.monotonic() + 2)
    item = json.loads(manager.storage_path.read_text())['document']['shared'][0]
    assert item['gcal_event_id'] == remote.calls[0].remote_id
    assert item['sync_operations'][0]['state'] == 'synced'
    assert item['_remote_etag'] == remote.remote[item['gcal_event_id']]['etag']
    manager._storage.close()

@pytest.mark.parametrize('after_replace', [False, True])
def test_process_exit_leaves_complete_document_and_releases_lock(tmp_path, after_replace):
    path = tmp_path/'reminders.json'
    old = {'g': [{'id': 'one', 'text': 'Original', 'completed': False, 'created_at': '2026-01-01T00:00:00'}]}
    path.write_text(json.dumps(old))
    script = '''import os, sys
from cal_system.reminder_manager import ReminderManager
import utils.json_storage as storage
manager = ReminderManager(sys.argv[1])
replace = storage.os.replace
def crash(source, destination):
    if sys.argv[2] == 'True':
        replace(source, destination)
    os._exit(73)
storage.os.replace = crash
manager.edit_reminder('g', 1, title='Committed')
'''
    result = subprocess.run([os.sys.executable, '-c', script, str(path), str(after_replace)], capture_output=True, timeout=10)
    assert result.returncode == 73
    from utils.storage_contract import load_document
    loaded = load_document(path, 2, upgrade_from=(1,))
    assert loaded.status == 'valid'
    assert loaded.document['g'][0]['text'] == ('Committed' if after_replace else 'Original')
    restarted = ReminderManager(path)
    restarted.edit_reminder('g', 1, title='Recovered')
    assert restarted.get_active_reminders('g')[0]['text'] == 'Recovered'


@pytest.mark.asyncio
async def test_cancelled_worker_finishes_before_releasing_transaction(tmp_path, monkeypatch):
    memory = UserMemory(tmp_path/'memory.json')
    await memory.set_location('u', 'Oslo')
    from memory.user_memory import write_json_atomic
    entered, release = threading.Event(), threading.Event()
    def paused_writer(path, document):
        entered.set()
        assert release.wait(5)
        write_json_atomic(path, document)
    monkeypatch.setattr('memory.user_memory.write_json_atomic', paused_writer)
    task = asyncio.create_task(memory.set_location('u', 'Bergen'))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert memory.memory['u']['location'] == 'Bergen'
    assert json.loads(memory.storage_path.read_text())['document']['u']['location'] == 'Bergen'
