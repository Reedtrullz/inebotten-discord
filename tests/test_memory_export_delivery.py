"""Synthetic snapshots only: private exports must arrive complete or be refused."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.command_registry import validate_payload, CommandPayloadError
from core.intent_router import BotIntent
from core.outbound_sender import OutboundSender
from core.rate_limiter import RateLimiter
from features.memory_handler import MemoryHandler


class PrivateChannel:
    def __init__(self, recipient=7):
        self.id = 70
        self.recipient = SimpleNamespace(id=recipient)
        self.sent = []

    async def send(self, content, **kwargs):
        files = kwargs.get('files', [])
        self.sent.append((content, [(f.filename, f.fp.read()) for f in files]))
        return SimpleNamespace(id=len(self.sent))


def fixture(monkeypatch, *, private=True, data=None, dm=None):
    import discord
    monkeypatch.setattr(discord, 'DMChannel', PrivateChannel)
    channel = PrivateChannel() if private else SimpleNamespace(id=80)
    message = SimpleNamespace(id=123, channel=channel, guild=None if private else SimpleNamespace(id=8),
                              author=SimpleNamespace(id=7, create_dm=AsyncMock(return_value=dm)))
    memory = SimpleNamespace(export_user_memory=AsyncMock(return_value=data or {'note': 'ø' * 3000}))
    quota = RateLimiter(safe_interval=0)
    monitor = SimpleNamespace(user_memory=memory, rate_limiter=quota, loc=None,
                              client=SimpleNamespace(get_channel=lambda _: channel), response_count=0)
    monitor.outbound = OutboundSender(monitor.client.get_channel, quota)
    handler = MemoryHandler(monitor)
    handler.send_response = AsyncMock()
    return handler, message, memory, monitor


def test_complete_export_exceeding_old_message_limit(monkeypatch):
    handler, message, memory, monitor = fixture(monkeypatch)
    asyncio.run(handler.handle_memory(message, {'action': 'export'}))
    content, files = message.channel.sent[0]
    assert len(files) == 1
    assert files[0][0].endswith('.json')
    assert json.loads(files[0][1]) == memory.export_user_memory.return_value
    assert 'ø' * 20 not in content
    memory.export_user_memory.assert_awaited_once_with(7)
    assert monitor.response_count == 1


def test_group_export_refuses_before_snapshot_or_dm_lookup(monkeypatch):
    handler, message, memory, _ = fixture(monkeypatch, private=False)
    asyncio.run(handler.handle_memory(message, {'action': 'export'}))
    memory.export_user_memory.assert_not_awaited()
    message.author.create_dm.assert_not_awaited()
    assert 'privat' in handler.send_response.call_args.args[1].lower()


def test_explicit_private_destination_delivers_only_there(monkeypatch):
    dm = PrivateChannel()
    handler, message, memory, monitor = fixture(monkeypatch, private=False, dm=dm)
    asyncio.run(handler.handle_memory(message, {'action': 'export', 'private': True}))
    assert json.loads(dm.sent[0][1][0][1]) == memory.export_user_memory.return_value
    assert monitor.response_count == 1
    handler.send_response.assert_not_awaited()


@pytest.mark.parametrize('recipient', [None, 99])
def test_missing_or_wrong_private_destination_never_falls_back(monkeypatch, recipient):
    dm = None if recipient is None else PrivateChannel(recipient)
    handler, message, memory, _ = fixture(monkeypatch, private=False, dm=dm)
    asyncio.run(handler.handle_memory(message, {'action': 'export', 'private': True}))
    memory.export_user_memory.assert_not_awaited()
    if dm:
        assert not dm.sent
    assert 'Kunne ikke' in handler.send_response.call_args.args[1]


def test_export_byte_cap_refuses_complete_payload_without_truncation(monkeypatch):
    handler, message, _, monitor = fixture(monkeypatch, data={'note': 'ø' * (1024 * 1024)})
    asyncio.run(handler.handle_memory(message, {'action': 'export'}))
    assert not message.channel.sent
    assert monitor.response_count == 0
    assert 'stor' in handler.send_response.call_args.args[1]


def test_failed_private_delivery_has_no_success_or_public_payload(monkeypatch):
    dm = PrivateChannel()
    dm.send = AsyncMock(side_effect=OSError('synthetic failure'))
    handler, message, _, monitor = fixture(monkeypatch, private=False, dm=dm)
    asyncio.run(handler.handle_memory(message, {'action': 'export', 'private': True}))
    assert monitor.response_count == 0
    assert 'JSON' not in handler.send_response.call_args.args[1]
    assert '✅' not in handler.send_response.call_args.args[1]
    assert dm.send.await_count == 1  # Unknown acknowledgement is never blindly retried.


@pytest.mark.parametrize('extra', [{'user_id': 9}, {'target_user': 9}, {'private': 'yes'}])
def test_cross_user_and_untyped_payload_refused(monkeypatch, extra):
    handler, message, memory, _ = fixture(monkeypatch)
    asyncio.run(handler.handle_memory(message, {'action': 'export', **extra}))
    memory.export_user_memory.assert_not_awaited()
    with pytest.raises(CommandPayloadError):
        validate_payload(BotIntent.MEMORY_EXPORT, {'memory': {'action': 'export', **extra}})


def test_attachment_identity_buffers_and_shared_quota(monkeypatch):
    from core.outbound_sender import Attachment
    handler, message, _, monitor = fixture(monkeypatch)
    async def run():
        for body in (b'{"v":1}', b'{"v":2}', b'{"v":2}'):
            result = await monitor.outbound.reply(message, 'export', attachments=(Attachment('memory.json', 'application/json', body),))
            assert result.status == 'delivered'
        assert len(message.channel.sent) == 2
        assert [row[1][0][1] for row in message.channel.sent] == [b'{"v":1}', b'{"v":2}']
        assert monitor.rate_limiter.get_stats()['total_sent'] == 2
    asyncio.run(run())


def test_text_only_fallback_cannot_drop_attachment():
    from core.outbound_sender import Attachment
    fallback = AsyncMock()
    sender = OutboundSender(lambda _: None, RateLimiter(safe_interval=0), send_channel_message=fallback)
    result = asyncio.run(sender.send('70', 'export', deadline=time.monotonic() + 1,
                                    attachments=(Attachment('memory.json', 'application/json', b'{}'),)))
    assert result.status == 'dropped'
    fallback.assert_not_awaited()


def test_attachment_retry_rewinds_and_closes_every_buffer(monkeypatch):
    from core.outbound_sender import Attachment
    class Throttled(Exception):
        status = 429
        retry_after = 0
    streams = []
    async def send(content, *, files, **kwargs):
        streams.append(files[0].fp)
        assert files[0].fp.read() == b'{"complete":true}'
        if len(streams) == 1:
            raise Throttled()
        return SimpleNamespace(id='receipt')
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), RateLimiter(safe_interval=0))
    result = asyncio.run(sender.send('70', 'export', deadline=time.monotonic() + 2,
        attachments=(Attachment('memory.json', 'application/json', b'{"complete":true}'),)))
    assert result.status == 'delivered'
    assert len(streams) == 2 and all(stream.closed for stream in streams)
    assert sender.limiter.get_stats()['total_sent'] == 1


def test_real_snapshot_export_copies_only_actor_record(tmp_path):
    from memory.user_memory import UserMemory
    path = tmp_path / 'memory.json'
    original = {'7': {'saved_fact': 'ø' * 3000, 'interests': ['synthetic']},
                '9': {'saved_fact': 'other-user-only'}}
    path.write_text(json.dumps(original))
    memory = UserMemory(path)
    snapshot = asyncio.run(memory.export_user_memory(7))
    assert snapshot == original['7']
    assert len(json.dumps(snapshot)) > 1800
    snapshot['interests'].append('changed copy')
    assert memory.memory['7']['interests'] == ['synthetic']
    assert memory.memory['9'] == original['9']
    memory._storage.close()


def test_group_dm_is_not_a_private_export_destination(monkeypatch):
    import discord
    handler, message, memory, _ = fixture(monkeypatch)
    group_type = type('SyntheticGroup', (), {})
    monkeypatch.setattr(discord, 'GroupChannel', group_type)
    message.channel = group_type()
    message.channel.id = 81
    asyncio.run(handler.handle_memory(message, {'action': 'export'}))
    memory.export_user_memory.assert_not_awaited()


def test_explicit_private_export_routes_with_typed_choice():
    from core.intent_router import IntentRouter
    from tests.test_intent_router import DummyMonitor
    result = IntentRouter(DummyMonitor()).route('eksporter minnet mitt privat', guild_id='8')
    assert result.intent == BotIntent.MEMORY_EXPORT
    assert result.payload['memory'] == {'action': 'export', 'private': True}
    assert validate_payload(result.intent, result.payload) == result.payload
