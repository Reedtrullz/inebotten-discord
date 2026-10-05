"""No account calls: delivery evidence, quota races and durable ambiguity."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.reminder_checker import ReminderChecker
from core.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_missing_destination_not_marked_sent(tmp_path):
    checker = ReminderChecker(get_channel_func=lambda _: None, storage_path=tmp_path/'log.json')
    await checker.setup()
    await checker._send_item_reminder({'id': 'one', 'title': 'Never delivered', 'user_id': 'u', 'channel_id': '123'}, 'now', 'nå')
    assert not checker._has_been_sent('one', 'now')
    assert checker.stats['now_sent'] == 0
    assert checker.sent_log['reminders_sent'] == {}


@pytest.mark.asyncio
async def test_concurrent_reservations_keep_existing_limits():
    from core.outbound_sender import OutboundSender
    accepted = []
    release = asyncio.Event()
    async def send(text, **kwargs):
        accepted.append(text)
        await release.wait()
        return SimpleNamespace(id=f'message-{text}')
    limiter = RateLimiter(max_per_second=2, daily_quota=2)
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), limiter)
    tasks = [asyncio.create_task(sender.send('123', str(i), delivery_key=str(i), deadline=time.monotonic()+.08)) for i in range(4)]
    await asyncio.sleep(.02)
    assert len(accepted) == 2
    assert limiter.get_stats()['total_sent'] == 0
    release.set()
    results = await asyncio.gather(*tasks)
    assert sum(r.status == 'delivered' for r in results) == 2
    assert limiter.get_stats()['sent_today'] == 2
    assert limiter.get_stats()['reserved'] == 0


@pytest.mark.asyncio
async def test_timeout_after_acceptance_is_unknown():
    from core.outbound_sender import OutboundSender
    accepted = []
    async def send(text, **kwargs):
        accepted.append(text)
        await asyncio.Event().wait()
    limiter = RateLimiter()
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), limiter)
    result = await sender.send('123', 'Maybe accepted', delivery_key='once', deadline=time.monotonic()+.01)
    assert result.status == 'unknown'
    assert result.message_id is None
    duplicate = await sender.send('123', 'Maybe accepted', delivery_key='once', deadline=time.monotonic()+.05)
    assert duplicate.status == 'unknown'
    assert len(accepted) == 1
    assert limiter.get_stats()['total_sent'] == 0
    assert limiter.get_stats()['sent_today'] == 1  # Conservatively consume unknown quota.


@pytest.mark.asyncio
async def test_shutdown_preserves_pending_delivery_state(tmp_path):
    from core.outbound_sender import OutboundSender
    entered = asyncio.Event()
    async def send(text, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), RateLimiter())
    path = tmp_path/'log.json'
    checker = ReminderChecker(storage_path=path, outbound_sender=sender)
    await checker.setup()
    task = asyncio.create_task(checker._send_item_reminder({'id': 'one', 'title': 'Pending', 'channel_id': '123'}, 'now', 'nå'))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = json.loads(path.read_text())['document']
    assert stored['deliveries']['one:now']['status'] == 'unknown'
    assert stored['reminders_sent'] == {}
    checker.close_storage()
    resumed = ReminderChecker(storage_path=path)
    await resumed.setup()
    await resumed._send_item_reminder({'id': 'one', 'title': 'Pending', 'channel_id': '123'}, 'now', 'nå')
    assert resumed.sent_log['deliveries']['one:now']['status'] == 'unknown'
    assert resumed.stats['now_sent'] == 0


@pytest.mark.asyncio
async def test_cancel_before_send_releases_reservation():
    from core.outbound_sender import OutboundSender
    limiter = RateLimiter(max_per_second=1, daily_quota=1)
    reservation = await limiter.reserve(time.monotonic()+1)
    send = AsyncMock(return_value=SimpleNamespace(id='remote-id'))
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), limiter)
    task = asyncio.create_task(sender.send('123', 'Not sent', delivery_key=None, deadline=time.monotonic()+5))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    limiter.release(reservation, attempted=False)
    assert limiter.get_stats()['reserved'] == 0
    assert limiter.get_stats()['sent_today'] == 0
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_remote_message_evidence_required_and_403_is_not_delivered():
    from core.outbound_sender import OutboundSender
    for response in [None, SimpleNamespace(id=None), object()]:
        sender = OutboundSender(lambda _: SimpleNamespace(send=AsyncMock(return_value=response)), RateLimiter())
        result = await sender.send('123', 'No evidence', delivery_key=None, deadline=time.monotonic()+1)
        assert result.status == 'unknown'
        assert sender.limiter.total_sent == 0
    class Forbidden(Exception):
        status = 403
    sender = OutboundSender(lambda _: SimpleNamespace(send=AsyncMock(side_effect=Forbidden())), RateLimiter())
    assert (await sender.send('123', 'Denied', delivery_key=None, deadline=time.monotonic()+1)).status == 'forbidden'
    assert sender.limiter.total_sent == 0


@pytest.mark.asyncio
async def test_429_honors_retry_after_and_deadline():
    from core.outbound_sender import OutboundSender
    class Throttled(Exception):
        status = 429
        retry_after = .03
    attempted = []
    async def send(text, **kwargs):
        attempted.append(time.monotonic())
        if len(attempted) == 1:
            raise Throttled()
        return SimpleNamespace(id='receipt')
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), RateLimiter())
    result = await sender.send('123', 'Retry', delivery_key='retry', deadline=time.monotonic()+.3)
    assert result.status == 'delivered' and result.message_id == 'receipt'
    assert attempted[1] - attempted[0] >= .025
    assert sender.limiter.total_sent == 1
    sender = OutboundSender(lambda _: SimpleNamespace(send=AsyncMock(side_effect=Throttled())), RateLimiter())
    result = await sender.send('123', 'Too late', delivery_key=None, deadline=time.monotonic()+.01)
    assert result.status == 'retryable' and result.retry_after_s == .03
    assert sender.limiter.daily_count == 0


@pytest.mark.asyncio
async def test_digest_is_not_marked_delivered_without_evidence(tmp_path):
    checker = ReminderChecker(storage_path=tmp_path/'log.json', get_channel_func=lambda _: None)
    await checker.setup()
    result = await checker._deliver('123', 'Digest', 'digest:g:c:today')
    assert result.status == 'dropped'
    assert checker.sent_log['digest_log'] == {}


@pytest.mark.asyncio
async def test_existing_safe_interval_is_reserved_monotonically():
    limiter = RateLimiter(max_per_second=5, daily_quota=10, safe_interval=.05)
    first = await limiter.reserve(time.monotonic()+1)
    before = time.monotonic()
    second = await limiter.reserve(time.monotonic()+1)
    assert time.monotonic() - before >= .045
    limiter.release(first, attempted=False)
    limiter.release(second, attempted=False)

@pytest.mark.asyncio
async def test_same_reply_allows_distinct_chunks_but_counts_duplicate_once():
    from features.base_handler import BaseHandler
    message = SimpleNamespace(id='incoming', channel=SimpleNamespace(id=123),
                              reply=AsyncMock(side_effect=[SimpleNamespace(id='first'), SimpleNamespace(id='second')]))
    monitor = SimpleNamespace(rate_limiter=RateLimiter(), loc=None, client=SimpleNamespace(), response_count=0)
    handler = BaseHandler(monitor)
    await handler.send_response(message, 'First chunk')
    await handler.send_response(message, 'Second chunk')
    await handler.send_response(message, 'First chunk')
    assert message.reply.await_count == 2
    assert monitor.response_count == 2
    assert monitor.rate_limiter.total_sent == 2


@pytest.mark.asyncio
async def test_definite_pre_send_cancellation_can_retry_same_key():
    from core.outbound_sender import OutboundSender
    limiter = RateLimiter(max_per_second=1, daily_quota=1)
    reservation = await limiter.reserve(time.monotonic()+1)
    remote = AsyncMock(return_value=SimpleNamespace(id='evidence'))
    sender = OutboundSender(lambda _: SimpleNamespace(send=remote), limiter)
    task = asyncio.create_task(sender.send('123', 'Not yet', delivery_key='key', deadline=time.monotonic()+1))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    limiter.release(reservation, attempted=False)
    retry = await sender.send('123', 'Not yet', delivery_key='key', deadline=time.monotonic()+1)
    assert retry.status == 'delivered'
    remote.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_acknowledgement_has_message_evidence(tmp_path):
    from core.outbound_sender import OutboundSender
    remote = AsyncMock(return_value=SimpleNamespace(id='actual-evidence'))
    checker = ReminderChecker(storage_path=tmp_path/'log.json', outbound_sender=OutboundSender(lambda _: SimpleNamespace(send=remote), RateLimiter()))
    await checker.setup()
    item = {'id': 'one', 'title': 'Delivered', 'channel_id': '123'}
    await checker._send_item_reminder(item, 'now', 'nå')
    await checker._send_item_reminder(item, 'now', 'nå')
    assert checker.stats['now_sent'] == 1
    assert checker.sent_log['deliveries']['one:now']['message_id'] == 'actual-evidence'
    assert checker.sent_log['reminders_sent']['one:now'] > 0
    remote.assert_awaited_once()


def test_safe_interval_longer_than_burst_window_is_preserved(monkeypatch):
    from core import rate_limiter
    clock = {'now': 100.0}
    monkeypatch.setattr(rate_limiter, 'time', SimpleNamespace(monotonic=lambda: clock['now']))
    limiter = RateLimiter(safe_interval=2)
    limiter.record_sent()
    clock['now'] = 101.1
    assert limiter.can_send()[0] is False
    clock['now'] = 102.0
    assert limiter.can_send()[0] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [False, True])
@pytest.mark.parametrize("with_attachment", [False, True])
async def test_untrusted_content_cannot_parse_discord_mentions(reply, with_attachment):
    from core.outbound_sender import Attachment, OutboundSender
    text = "ICS title @everyone @here <@123456789012345678> <@&123456789012345678>"
    remote = AsyncMock(return_value=SimpleNamespace(id="receipt"))
    channel = SimpleNamespace(id=123, send=remote)
    sender = OutboundSender(lambda _: channel, RateLimiter(safe_interval=0))
    files = (Attachment("review.json", "application/json", b"{}"),) if with_attachment else ()
    if reply:
        message = SimpleNamespace(id=456, channel=channel, reply=remote)
        result = await sender.reply(message, text, attachments=files)
    else:
        result = await sender.send("123", text, deadline=time.monotonic()+1, attachments=files)
    assert result.status == "delivered"
    assert remote.await_args.args[0] == text
    allowed = remote.await_args.kwargs.get("allowed_mentions")
    assert allowed is not None
    assert allowed.to_dict().get("parse") == []
    assert not allowed.replied_user


@pytest.mark.asyncio
async def test_legacy_text_transport_escapes_mentions_without_keyword_support():
    from core.outbound_sender import OutboundSender
    sent = []
    async def legacy(channel, text):
        sent.append((channel, text))
        return SimpleNamespace(id="receipt")
    sender = OutboundSender(lambda _: None, RateLimiter(safe_interval=0), send_channel_message=legacy)
    result = await sender.send("123", "@everyone <@&123456789012345678>", deadline=time.monotonic()+1)
    assert result.status == "delivered"
    assert sent[0][0] == 123
    assert "@everyone" not in sent[0][1] and "<@&123456789012345678>" not in sent[0][1]
