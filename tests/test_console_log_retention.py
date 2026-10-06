"""Bounded read/retention receipts using generated log files only."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from web_console.console_store import ConsoleStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    value = ConsoleStore(max_log_bytes=16384, log_retention_days=7)
    yield value
    value.close()


def test_large_tail_reads_a_budget_not_whole_file(store, monkeypatch):
    line = json.dumps({'ts': datetime.now(timezone.utc).isoformat(), 'line': 'synthetic ' + 'x' * 200}).encode() + b'\n'
    store._logs_file.write_bytes(line * 10000)
    # Current readlines behavior consumes every byte even for a short tail.
    assert len(store._logs_file.read_bytes()) > 2000000
    actual_read = []
    original = store._diagnostic_logs._open

    class MeasuredFile:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, count=-1):
            assert 0 <= count <= 8192
            data = self.handle.read(count)
            actual_read.append(len(data))
            return data

    monkeypatch.setattr(store._diagnostic_logs, '_open', lambda *args: MeasuredFile(original(*args)))
    page = store.read_log_page(None, max_bytes=8192, filters={})
    assert sum(actual_read) == page['bytes_read']
    assert page['bytes_read'] <= 8192
    assert page['records'] and page['next_cursor'] and page['truncated']
    assert all('ts' in row and 'level' in row and 'component' in row and 'outcome' in row for row in page['records'])


def test_filtered_cursor_pagination_and_rotation_staleness(store):
    for n in range(150):
        store.append_record(level='ERROR' if n % 2 else 'INFO', component='console',
                            outcome='failed' if n % 2 else 'success', line=f'synthetic {n}')
    first = store.read_log_page(None, max_bytes=4096, filters={'level': 'ERROR'})
    assert first['records'] and all(row['level'] == 'ERROR' for row in first['records'])
    second = store.read_log_page(first['next_cursor'], max_bytes=4096, filters={'level': 'ERROR'})
    assert not set(r['line'] for r in first['records']) & set(r['line'] for r in second['records'])
    with pytest.raises(ValueError):
        store.read_log_page(first['next_cursor'], max_bytes=4096, filters={'level': 'INFO'})
    for n in range(1000):
        store.append_record(level='INFO', component='console', outcome='success', line='more ' + str(n))
    with pytest.raises(ValueError, match='stale_cursor'):
        store.read_log_page(first['next_cursor'], max_bytes=4096, filters={'level': 'ERROR'})


def test_retention_total_bytes_age_and_private_modes(store):
    for n in range(1000):
        store.append_logs(['synthetic ' + str(n) + 'x' * 300])
    paths = list(store._data_dir.glob('logs*.jsonl'))
    assert sum(path.stat().st_size for path in paths) <= store.max_log_bytes
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in paths)
    for path in paths:
        if path != store._logs_file:
            path.unlink()
    expired = datetime.now(timezone.utc) - timedelta(days=8)
    store._logs_file.write_text(json.dumps({'ts': expired.isoformat(), 'line': 'expired synthetic'}) + '\n')
    assert store.read_log_page(None, max_bytes=4096, filters={})['records'] == []


def test_direct_persistence_redacts_credentials_and_prompt_member_content(store):
    store.append_logs(['OPENROUTER_API_KEY=synthetic-secret',
                       '[MONITOR] _send_ai_response called for message: PRIVATE_PROMPT',
                       '[MONITOR] Mention detected from PRIVATE_MEMBER in DM',
                       'members: PRIVATE_MEMBER_LIST'])
    raw = b''.join(p.read_bytes() for p in store._data_dir.glob('logs*.jsonl'))
    for private in (b'synthetic-secret', b'PRIVATE_PROMPT', b'PRIVATE_MEMBER', b'PRIVATE_MEMBER_LIST'):
        assert private not in raw


def test_malformed_and_oversized_records_are_bounded_and_cursor_is_not_a_path(store):
    store._logs_file.write_bytes(b'not-json\n' + b'X' * 40000 + b'\n' +
                                json.dumps({'line': 'last synthetic', 'ts': datetime.now(timezone.utc).isoformat()}).encode() + b'\n')
    page = store.read_log_page(None, max_bytes=4096, filters={})
    assert [r['line'] for r in page['records']] == ['last synthetic']
    assert page['bytes_read'] <= 4096
    with pytest.raises(ValueError):
        store.read_log_page('/etc/passwd', max_bytes=4096, filters={})
    with pytest.raises(ValueError):
        store.read_log_page(None, max_bytes=99999999, filters={})


def test_age_cleanup_on_write_preserves_recent_rows_and_separate_audit(store):
    expired = datetime.now(timezone.utc) - timedelta(days=8)
    recent = datetime.now(timezone.utc)
    store._logs_file.write_text('\n'.join(json.dumps({'ts': ts.isoformat(), 'line': line})
                                        for ts, line in ((expired, 'expired synthetic'), (recent, 'recent synthetic'))) + '\n')
    audit = store._data_dir / 'audit.jsonl'
    audit.write_text('synthetic independent audit')
    store.append_logs(['new synthetic'])
    raw = store._logs_file.read_text()
    assert 'expired synthetic' not in raw
    assert 'recent synthetic' in raw
    assert audit.read_text() == 'synthetic independent audit'


def test_writer_ownership_and_symlink_logs_are_refused(store, tmp_path):
    store.append_logs(['first synthetic'])
    other = ConsoleStore(max_log_bytes=16384)
    before = store._logs_file.read_bytes()
    other.append_logs(['second writer synthetic'])
    assert store._logs_file.read_bytes() == before
    assert 'store_owned' in other.health()['last_error']
    other.close()
    store.close()
    store._logs_file.unlink()
    outside = tmp_path / 'outside'
    outside.write_text('preserve synthetic')
    store._logs_file.symlink_to(outside)
    with pytest.raises(ValueError, match='unsafe_log_file'):
        store.read_log_page(None, max_bytes=4096, filters={})
    assert outside.read_text() == 'preserve synthetic'


def test_rotated_cursor_rejects_reused_file_identity(store, monkeypatch):
    from types import SimpleNamespace
    from web_console import log_store
    for n in range(18):
        store.append_record(line=f"old-generation-{n}", component="fixture")
    page = store.read_log_page(None, max_bytes=1024, filters={})
    cursor = page["next_cursor"]
    old_state = store._diagnostic_logs._decode(cursor, {})
    assert len(old_state["files"]) == 1
    old_identity, old_offset = old_state["files"][0]
    old_dev, old_ino = map(int, old_identity.split(":")[:2])
    for n in range(1000):
        store.append_record(line=f"new-generation-{n}", component="fixture")
    for n in range(100):
        if store._logs_file.stat().st_size >= old_offset:
            break
        store.append_record(line=f"new-tail-{n}", component="fixture")
    assert store._logs_file.stat().st_size >= old_offset
    for path in store._data_dir.glob('logs.*.jsonl'):
        path.unlink()
    replacement = store._logs_file.stat()
    original_info = store._diagnostic_logs._info
    original_fstat = log_store.os.fstat
    def reused_identity(info):
        values = {name:getattr(info,name) for name in dir(info) if name.startswith('st_')}
        values.update(st_dev=old_dev, st_ino=old_ino)
        return SimpleNamespace(**values)
    monkeypatch.setattr(store._diagnostic_logs, '_info', lambda path: reused_identity(original_info(path)))
    def fstat(fd):
        info = original_fstat(fd)
        return reused_identity(info) if (info.st_dev,info.st_ino)==(replacement.st_dev,replacement.st_ino) else info
    monkeypatch.setattr(log_store.os,'fstat',fstat)
    with pytest.raises(ValueError,match='stale_cursor'):
        store.read_log_page(cursor,max_bytes=1024,filters={})


def test_cursor_survives_append_and_moving_live_segment(store):
    for n in range(18):
        store.append_record(line=f"snapshot-{n}",component="fixture")
    first = store.read_log_page(None,max_bytes=1024,filters={})
    assert first['next_cursor']
    for n in range(30):
        store.append_record(line=f"later-{n}",component="fixture")
    rows = first['records'][:]
    cursor = first['next_cursor']
    for _ in range(10):
        page = store.read_log_page(cursor,max_bytes=1024,filters={})
        rows.extend(page['records'])
        cursor = page['next_cursor']
        if cursor is None:break
    assert cursor is None
    assert {row['line'] for row in rows}=={f"snapshot-{n}" for n in range(18)}
    assert len(rows)==18
    assert len(store._diagnostic_logs._generations)<=4
