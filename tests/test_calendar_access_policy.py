"""Invocation gates, explicit audience policies and preserving scope changes."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from core.request_context import RequestContext, request_scope
from cal_system.calendar_manager import CalendarManager


def actor(user='owner', channel='dm', kind='dm', guild=None):
    return RequestContext('request', user, channel, guild, 'no', channel_kind=kind)


def policies():
    from core.access_policy import AccessPolicy, ScopeRecord
    return AccessPolicy([
        ScopeRecord('shared', 'legacy_shared'),
        ScopeRecord('private:owner', 'private_user', owner_id='owner'),
        ScopeRecord('group:approved', 'approved_group', owner_id='owner', collaborator_ids=frozenset({'member'}),
                    channel_ids=frozenset({'approved'}), read_policy='members', write_policy='owner'),
    ], default_scope='shared')


@pytest.mark.parametrize('mode, users, channels, kind, user, channel, allowed', [
    ('legacy', [], [], 'guild', 'any', 'any', True),
    ('legacy', ['owner'], [], 'guild', 'other', 'any', False),
    ('legacy', ['owner'], ['approved'], 'guild', 'owner', 'other', False),
    ('legacy', ['owner'], ['approved'], 'dm', 'owner', 'other', True),
    ('legacy', ['owner'], ['approved'], 'group_dm', 'owner', 'other', True),
    ('allowlist', [], [], 'dm', 'owner', 'dm', False),
    ('allowlist', ['owner'], ['approved'], 'group_dm', 'owner', 'other', False),
    ('allowlist', ['owner'], ['approved'], 'group_dm', 'owner', 'approved', True),
    ('allowlist', ['owner'], ['approved'], 'dm', 'owner', 'dm', True),
])
def test_invocation_matrix_preserves_explicit_legacy_semantics(mode, users, channels, kind, user, channel, allowed):
    from core.access_policy import invocation_decision
    assert invocation_decision(actor(user, channel, kind), mode=mode, allowed_users=users, allowed_channels=channels).allowed is allowed


@pytest.mark.parametrize('scope, user, kind, channel, operation, allowed', [
    ('shared', 'outsider', 'guild', 'any', 'write', True),
    ('private:owner', 'owner', 'dm', 'dm', 'read', True),
    ('private:owner', 'owner', 'dm', 'dm', 'write', True),
    ('private:owner', 'outsider', 'dm', 'dm', 'read', False),
    ('private:owner', 'owner', 'guild', 'public', 'read', False),
    ('private:owner', 'owner', 'group_dm', 'public', 'write', False),
    ('group:approved', 'owner', 'guild', 'approved', 'write', True),
    ('group:approved', 'member', 'guild', 'approved', 'read', True),
    ('group:approved', 'member', 'guild', 'approved', 'write', False),
    ('group:approved', 'outsider', 'guild', 'approved', 'read', False),
    ('group:approved', 'owner', 'guild', 'other', 'read', False),
])
def test_scope_matrix(scope, user, kind, channel, operation, allowed):
    policy = policies()
    assert policy.authorize(actor(user, channel, kind), scope, operation).allowed is allowed
    assert policy.authorize(actor(), 'missing', 'read').allowed is False
    assert policy.authorize(actor(), 'shared', 'invented_operation').allowed is False


@pytest.mark.asyncio
async def test_new_private_scope_does_not_privatize_or_duplicate_legacy(tmp_path):
    path = tmp_path/'calendar.json'
    original = {'shared': [{'id': 'existing', 'title': 'Deliberately shared', 'date': '01.01.2027', 'completed': False}]}
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    policy = policies()
    policy.default_scope = 'private:owner'
    manager = CalendarManager(storage_path=path, access_policy=policy)
    await manager.setup()
    assert path.read_bytes() == before
    with request_scope(actor()):
        assert manager.get_upcoming('dm', days=500) == []
        item = manager.add_item('dm', 'owner', 'Owner', 'Private', '01.01.2027')
        assert item['scope_id'] == 'private:owner'
        preview = manager.preview_scope_migration('shared', 'private:owner')
        assert preview['item_ids'] == ['existing']
        assert preview['requires_confirmation'] is True
    assert manager.items['shared'] == original['shared']
    assert len(manager.items['private:owner']) == 1
    with request_scope(actor('outsider')):
        with pytest.raises(PermissionError):
            manager.get_upcoming('dm', days=500)
        with pytest.raises(PermissionError):
            manager.add_item('dm', 'outsider', 'Other', 'No', '01.01.2027')
    assert len(manager.items['private:owner']) == 1


def test_console_explains_audience_without_exposing_other_private_items(tmp_path, monkeypatch):
    from web_console.state_collector import collect_calendar_data
    from core.access_policy import AccessPolicy
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    policy = policies()
    path = tmp_path/'discord/data/calendar.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'private:owner': [{'id': 'secret', 'title': 'Private title', 'date': '01.01.2027'}], 'shared': []}))
    monitor = SimpleNamespace(access_policy=policy)
    result = collect_calendar_data(monitor, actor=actor('outsider'))
    assert 'Private title' not in repr(result)
    own = collect_calendar_data(monitor, actor=actor())
    assert 'Private title' in repr(own)
    assert own['scope_policy'][1]['owner_id'] == 'owner'
    assert own['scope_policy'][1]['read_policy'] == 'owner'
    # No unverified browser identity can acquire a private domain actor.
    assert 'Private title' not in repr(collect_calendar_data(monitor))


def test_setup_scope_settings_fail_closed_without_owner_or_group_audience():
    from core.config_schema import validate_settings
    assert validate_settings({'CALENDAR_MODE': 'private_user', 'CALENDAR_OWNER_ID': ''})
    assert validate_settings({'CALENDAR_MODE': 'approved_group', 'CALENDAR_GROUP_CHANNELS': ''})
    assert validate_settings({'CALENDAR_MODE': 'private_user', 'CALENDAR_OWNER_ID': '123'}) == []


@pytest.mark.asyncio
async def test_unregistered_named_scopes_never_become_legacy_shared(tmp_path, monkeypatch):
    from web_console.state_collector import collect_calendar_data
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    path = tmp_path/'discord/data/calendar.json'
    path.parent.mkdir(parents=True)
    records = {'private:former': [{'id': 'private', 'title': 'Private even after config change', 'date': '01.01.2027'}],
               'shared': [{'id': 'public', 'title': 'Shared', 'date': '01.01.2027'}]}
    path.write_text(json.dumps(records))
    original = path.read_bytes()
    manager = CalendarManager(storage_path=path)
    await manager.setup()
    assert path.read_bytes() == original
    assert manager.items == records
    assert 'Private even after config change' not in repr(collect_calendar_data())


def test_desktop_and_setup_can_explain_scope_without_credentials():
    from core.access_policy import describe_access_settings
    summary = describe_access_settings({'CALENDAR_MODE': 'private_user', 'CALENDAR_OWNER_ID': '123',
                                       'INVOCATION_MODE': 'allowlist', 'ALLOWED_USERS': '123',
                                       'DISCORD_USER_TOKEN': 'never-echo-this-fixture'})
    assert '123' in summary and 'privat' in summary.lower()
    assert 'direktemelding' in summary.lower()
    assert 'never-echo-this-fixture' not in summary


def test_scope_settings_reject_multiple_owner_ids():
    from core.config_schema import validate_settings
    assert validate_settings({'CALENDAR_MODE': 'private_user', 'CALENDAR_OWNER_ID': '123,456'})
