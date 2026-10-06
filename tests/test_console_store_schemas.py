"""Console reads must agree with current and supported legacy store envelopes."""
import json

import pytest

from web_console import state_collector


STORES = [
    ('calendar.json', 2, {'shared': [{'id': 'event-1', 'title': 'Canary meeting'}]}),
    ('reminders.json', 2, {'tester': [{'id': 'reminder-1', 'text': 'Canary reminder'}]}),
    ('polls.json', 3, {'guild': {'poll-1': {
        'id': 'poll-1', 'question': 'Canary?', 'status': 'active',
        'expires_at': '2027-01-01T12:00:00+00:00',
        'options': [{'text': 'Yes', 'votes': []}, {'text': 'No', 'votes': []}],
    }}}),
    ('user_memory.json', 4, {'tester': {'preferences': {'location': 'Oslo'}}}),
]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(state_collector, 'hermes_discord_data_path', lambda name: tmp_path / name)
    monkeypatch.setattr(state_collector, '_JSON_READ_ERRORS', {})
    return tmp_path


@pytest.mark.parametrize('name,current,document', STORES)
@pytest.mark.parametrize('envelope', ['current', 'legacy-v1', 'unenveloped'])
def test_console_displays_supported_stores_without_false_health_failure(
    isolated_data, name, current, document, envelope,
):
    path = isolated_data / name
    value = document if envelope == 'unenveloped' else {
        'schema_version': current if envelope == 'current' else 1,
        'revision': 3, 'document': document,
    }
    raw = json.dumps(value).encode()
    path.write_bytes(raw)

    assert state_collector._read_json_file(path, {}) == document
    assert state_collector._probe_json_files() == {}
    assert path.read_bytes() == raw


@pytest.mark.parametrize('name,current,document', STORES)
@pytest.mark.parametrize('invalid', ['future-schema', 'invalid-shape', 'invalid-json'])
def test_console_preserves_and_reports_unsupported_or_corrupt_stores(
    isolated_data, name, current, document, invalid,
):
    path = isolated_data / name
    raw = b'{' if invalid == 'invalid-json' else json.dumps({
        'schema_version': 99 if invalid == 'future-schema' else current,
        'document': document if invalid == 'future-schema' else {'broken': 42},
    }).encode()
    path.write_bytes(raw)

    assert state_collector._read_json_file(path, {}) == {}
    assert str(path) in state_collector._probe_json_files()
    assert path.read_bytes() == raw
