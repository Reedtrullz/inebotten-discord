"""Persistence failures must preserve bytes and never acknowledge a mutation."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_manager import ReminderManager
from memory.user_memory import UserMemory
from web_console.console_store import ConsoleStore


@pytest.mark.parametrize('raw', [b'{', b'[]', b'{"shared": "wrong"}'])
@pytest.mark.asyncio
async def test_corrupt_bytes_are_preserved(tmp_path, raw):
    path = tmp_path/'calendar.json'
    path.write_bytes(raw)
    manager = CalendarManager(storage_path=path)
    await manager.setup()
    assert manager.storage_state.status == 'corrupt'
    with pytest.raises(Exception, match='read_only'):
        manager.add_item('g', 'u', 'Tester', 'Never committed', '01.01.2027')
    assert path.read_bytes() == raw
    assert manager.items == {}


@pytest.mark.asyncio
async def test_save_failure_returns_failure(tmp_path, monkeypatch):
    manager = CalendarManager(storage_path=tmp_path/'calendar.json')
    await manager.setup()
    manager.add_item('g', 'u', 'Tester', 'Original', '01.01.2027')
    before = copy.deepcopy(manager.items)
    original = manager.storage_path.read_bytes()
    def fail(*_, **__):
        raise OSError('synthetic disk full')
    monkeypatch.setattr('cal_system.calendar_manager.write_json_atomic', fail)
    with pytest.raises(Exception, match='write_failed'):
        manager.edit_item_by_id(before['shared'][0]['id'], title='Uncommitted')
    assert manager.items == before
    assert manager.storage_path.read_bytes() == original


@pytest.mark.asyncio
async def test_newer_schema_is_read_only(tmp_path):
    path = tmp_path/'calendar.json'
    raw = json.dumps({'schema_version': 99, 'document': {'shared': []}}).encode()
    path.write_bytes(raw)
    manager = CalendarManager(storage_path=path)
    await manager.setup()
    assert manager.storage_state.status == 'unsupported'
    with pytest.raises(Exception, match='read_only'):
        manager.add_item('g', 'u', 'Tester', 'No downgrade', '01.01.2027')
    assert path.read_bytes() == raw


def test_contract_migrates_with_original_backup_and_refuses_downgrade(tmp_path):
    from utils.storage_contract import load_document, commit_document
    path = tmp_path/'store.json'
    original = b'{"unchanged": 42}\n'
    path.write_bytes(original)
    loaded = load_document(path, 1)
    assert loaded.status == 'valid'
    assert loaded.document == {'unchanged': 42}
    assert commit_document(path, {'unchanged': 43}, 1).ok
    assert path.with_name('store.json.legacy-v0.bak').read_bytes() == original
    assert load_document(path, 1).document == {'unchanged': 43}
    raw = path.read_bytes()
    assert not commit_document(path, {}, 0).ok
    assert path.read_bytes() == raw


@pytest.mark.asyncio
async def test_memory_write_failure_restores_previous_user(tmp_path, monkeypatch):
    memory = UserMemory(tmp_path/'memory.json')
    await memory.setup()
    await memory.set_location('u', 'Oslo')
    before = copy.deepcopy(memory.memory)
    def fail(*_, **__):
        raise OSError('synthetic')
    monkeypatch.setattr('memory.user_memory.write_json_atomic', fail)
    with pytest.raises(Exception, match='write_failed'):
        await memory.set_location('u', 'Bergen')
    assert memory.memory == before


def test_reminder_write_failure_restores_previous_reminder(tmp_path, monkeypatch):
    manager = ReminderManager(tmp_path/'reminders.json')
    manager.add_reminder('g', 'u', 'Tester', 'Original')
    before = copy.deepcopy(manager.reminders)
    def fail(*_, **__):
        raise OSError('synthetic')
    monkeypatch.setattr('cal_system.reminder_manager.write_json_atomic', fail)
    with pytest.raises(Exception, match='write_failed'):
        manager.edit_reminder('g', 1, title='Uncommitted')
    assert manager.reminders == before


def test_console_refuses_to_overwrite_unsupported_stats_or_corrupt_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    store = ConsoleStore()
    stats = b'{"version": 99, "intents": {}}'
    store._stats_file.write_bytes(stats)
    assert store.save_stats({'chat': {'count': 1}}, {}) is False
    assert store._stats_file.read_bytes() == stats
    sessions = b'['
    store._sessions_file.write_bytes(sessions)
    assert store.validate_session('untrusted') is False
    with pytest.raises(Exception, match='read_only'):
        store.create_session(60)
    assert store._sessions_file.read_bytes() == sessions
    assert store.health()['status'] == 'degraded'


@pytest.mark.asyncio
async def test_memory_handler_reports_save_failure_without_success():
    from features.memory_handler import MemoryHandler
    memory = SimpleNamespace(delete_user_memory=AsyncMock(side_effect=OSError('synthetic')))
    handler = MemoryHandler(SimpleNamespace(user_memory=memory, rate_limiter=None, loc=None, client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(author=SimpleNamespace(id='u'))
    await handler.handle_memory(message, {'action': 'delete', 'confirmed': True})
    assert handler.send_response.await_count == 1
    response = handler.send_response.await_args.args[1]
    assert 'Kunne ikke lagre' in response
    assert 'Ferdig' not in response

@pytest.mark.asyncio
async def test_calendar_create_commits_before_external_effect(tmp_path, monkeypatch):
    from features.calendar_handler import CalendarHandler
    from memory.localization import Localization
    remote = SimpleNamespace(create_event=lambda **_: pytest.fail('external create before local commit'))
    manager = CalendarManager(storage_path=tmp_path/'calendar.json', gcal_manager=remote)
    await manager.setup()
    handler = CalendarHandler(SimpleNamespace(calendar=manager, nlp_parser=None, rate_limiter=None, loc=Localization(), client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(guild=SimpleNamespace(id='g'), channel=SimpleNamespace(id='c'),
                              author=SimpleNamespace(id='u', name='Tester'))
    def fail(*_, **__):
        raise OSError('synthetic full disk')
    monkeypatch.setattr('cal_system.calendar_manager.write_json_atomic', fail)
    await handler.handle_calendar_item(message, {'title': 'Uncommitted', 'date': '01.01.2027'})
    assert handler.send_response.await_count == 2
    assert 'Kunne ikke lagre' in handler.send_response.await_args.args[1]
    assert manager.items == {}


@pytest.mark.parametrize('kind', ['reminder', 'memory'])
@pytest.mark.asyncio
async def test_other_owners_preserve_wrong_shape_and_newer_schema(tmp_path, kind):
    path = tmp_path/'store.json'
    for raw, status in [(b'{"u": []}' if kind == 'memory' else b'{"g": {}}', 'corrupt'),
                        (b'{"schema_version": 99, "document": {}}', 'unsupported')]:
        path.write_bytes(raw)
        if kind == 'memory':
            owner = UserMemory(path)
            await owner.setup()
            with pytest.raises(Exception, match='read_only'):
                await owner.set_location('u', 'Oslo')
        else:
            owner = ReminderManager(path)
            with pytest.raises(Exception, match='read_only'):
                owner.add_reminder('g', 'u', 'Tester', 'No write')
        assert owner.storage_state.status == status
        assert path.read_bytes() == raw

@pytest.mark.asyncio
async def test_valid_legacy_owner_migration_has_byte_preserving_receipt(tmp_path):
    original = b'{"old-guild": [{"id": "legacy", "title": "Behold", "date": "01.01.2027"}]}\n'
    path = tmp_path/'calendar.json'
    path.write_bytes(original)
    manager = CalendarManager(storage_path=path)
    await manager.setup()
    assert manager.items['shared'][0]['id'] == 'legacy'
    assert path.with_name('calendar.json.legacy-v0.bak').read_bytes() == original
    assert json.loads(path.read_text())['schema_version'] == 1
    restored = CalendarManager(storage_path=path)
    await restored.setup()
    assert restored.items == manager.items


def test_console_calendar_reader_exposes_unsupported_schema(tmp_path, monkeypatch):
    from web_console.state_collector import collect_calendar_data
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    path = tmp_path/'discord/data/calendar.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 99, "document": {}}')
    assert collect_calendar_data()['storage_status'] == 'degraded'
    assert collect_calendar_data()['storage_error'] == 'unsupported_schema'
