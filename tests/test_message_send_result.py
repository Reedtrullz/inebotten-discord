import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

import core.send_receipt as send_receipt_module
from core.dispatch_result import (
    DeliveryState,
    MessageSendCancelled,
    MessageSendResult,
    SEND_ERROR_CODES,
)
from core.send_receipt import (
    DiscordSendCoordinator,
    SendReceipt,
    capture_send_receipt,
)
from features.base_handler import BaseHandler


class FakeHandler(BaseHandler):
    pass


def _rate_limiter(*, wait_result=True):
    return SimpleNamespace(
        wait_if_needed=AsyncMock(return_value=wait_result),
        record_sent=Mock(),
        record_failure=Mock(),
        record_dropped=Mock(),
    )


def _guild_message(*, reply=None, channel_id=42):
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel_id),
        reply=reply or AsyncMock(),
    )


def _handler(sender, *, rate_limiter=None):
    limiter = rate_limiter or _rate_limiter()
    monitor = SimpleNamespace(
        rate_limiter=limiter,
        discord_sender=sender,
        loc=object(),
        client=object(),
        response_count=0,
    )
    return FakeHandler(monitor), monitor


class _Response:
    reason = "bounded-test"
    headers = {}

    def __init__(self, status):
        self.status = status


@pytest.mark.asyncio
async def test_coordinator_marks_normal_return_delivered_and_hardens_kwargs(
    monkeypatch,
):
    limiter = _rate_limiter()
    sentinel_mentions = object()
    monkeypatch.setattr(
        discord.AllowedMentions,
        "none",
        staticmethod(lambda: sentinel_mentions),
    )
    message = _guild_message()

    result = await DiscordSendCoordinator(limiter).send_result(
        message,
        "hei",
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    message.reply.assert_awaited_once_with(
        "hei",
        mention_author=False,
        allowed_mentions=sentinel_mentions,
        suppress_embeds=True,
    )
    limiter.record_sent.assert_called_once_with()
    limiter.record_failure.assert_not_called()
    limiter.record_dropped.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_uses_direct_dm_adapter_without_reply(
    monkeypatch,
):
    class FakeDMChannel:
        def __init__(self):
            self.id = 91
            self.send = AsyncMock()

    class FakeGroupChannel:
        pass

    monkeypatch.setattr(discord, "DMChannel", FakeDMChannel)
    monkeypatch.setattr(discord, "GroupChannel", FakeGroupChannel)
    sentinel_mentions = object()
    monkeypatch.setattr(
        discord.AllowedMentions,
        "none",
        staticmethod(lambda: sentinel_mentions),
    )
    channel = FakeDMChannel()
    message = SimpleNamespace(channel=channel, reply=AsyncMock())

    result = await DiscordSendCoordinator(
        _rate_limiter()
    ).send_result(message, "hei")

    assert result.state is DeliveryState.DELIVERED
    channel.send.assert_awaited_once_with(
        "hei",
        allowed_mentions=sentinel_mentions,
        suppress_embeds=True,
    )
    message.reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "text", "error_code"),
    (
        (_guild_message(), "", "empty"),
        (SimpleNamespace(channel=None), "hei", "missing_channel"),
        (_guild_message(channel_id=0), "hei", "invalid_channel"),
        (
            SimpleNamespace(channel=SimpleNamespace(id=42)),
            "hei",
            "missing_adapter",
        ),
    ),
)
async def test_coordinator_rejects_pre_attempt_failures_without_quota(
    message,
    text,
    error_code,
):
    limiter = _rate_limiter()

    result = await DiscordSendCoordinator(limiter).send_result(
        message,
        text,
    )

    assert result == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        error_code,
    )
    limiter.wait_if_needed.assert_not_awaited()
    limiter.record_sent.assert_not_called()
    limiter.record_failure.assert_not_called()
    limiter.record_dropped.assert_not_called()


@pytest.mark.asyncio
async def test_quota_exhaustion_is_definite_and_records_drop():
    limiter = _rate_limiter(wait_result=False)
    message = _guild_message()

    result = await DiscordSendCoordinator(limiter).send_result(
        message,
        "hei",
    )

    assert result == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "daily_quota",
    )
    message.reply.assert_not_awaited()
    limiter.record_dropped.assert_called_once_with()
    limiter.record_sent.assert_not_called()
    limiter.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_forbidden_is_definite_failure_and_does_not_reserve_quota():
    forbidden = discord.errors.Forbidden(_Response(403), "secret detail")
    limiter = _rate_limiter()
    message = _guild_message(reply=AsyncMock(side_effect=forbidden))

    result = await DiscordSendCoordinator(limiter).send_result(
        message,
        "hei",
    )

    assert result == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "forbidden",
    )
    message.reply.assert_awaited_once()
    limiter.record_failure.assert_called_once_with()
    limiter.record_sent.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_code", "failure_kwargs"),
    (
        (
            discord.errors.HTTPException(
                _Response(429),
                "secret HTTP detail",
            ),
            "http",
            {"is_rate_limit": True},
        ),
        (TimeoutError("secret timeout detail"), "timeout", {}),
        (RuntimeError("secret transport detail"), "transport", {}),
    ),
)
async def test_uncertain_attempts_reserve_quota_and_use_finite_codes(
    failure,
    error_code,
    failure_kwargs,
):
    limiter = _rate_limiter()
    message = _guild_message(reply=AsyncMock(side_effect=failure))

    result = await DiscordSendCoordinator(limiter).send_result(
        message,
        "hei",
    )

    assert result == MessageSendResult(
        DeliveryState.UNKNOWN,
        error_code,
    )
    assert result.error_code in SEND_ERROR_CODES
    assert "secret" not in repr(result)
    limiter.record_sent.assert_called_once_with()
    limiter.record_failure.assert_called_once_with(**failure_kwargs)
    limiter.record_dropped.assert_not_called()


@pytest.mark.asyncio
async def test_one_shared_coordinator_serializes_two_handler_admissions():
    limiter = _rate_limiter()
    active_attempts = 0
    maximum_attempts = 0

    async def reply(*_args, **_kwargs):
        nonlocal active_attempts, maximum_attempts
        active_attempts += 1
        maximum_attempts = max(maximum_attempts, active_attempts)
        await asyncio.sleep(0)
        active_attempts -= 1

    coordinator = DiscordSendCoordinator(limiter)
    handler, monitor = _handler(coordinator, rate_limiter=limiter)
    other_handler = FakeHandler(monitor)

    first, second = await asyncio.gather(
        handler.send_response_result(
            _guild_message(reply=AsyncMock(side_effect=reply)),
            "en",
        ),
        other_handler.send_response_result(
            _guild_message(reply=AsyncMock(side_effect=reply)),
            "to",
        ),
    )

    assert first.state is DeliveryState.DELIVERED
    assert second.state is DeliveryState.DELIVERED
    assert maximum_attempts == 1
    assert limiter.wait_if_needed.await_count == 2
    assert limiter.record_sent.call_count == 2
    assert monitor.response_count == 2
    assert handler.monitor.discord_sender is other_handler.monitor.discord_sender


@pytest.mark.parametrize(
    ("observed", "expected"),
    (
        (
            (
                MessageSendResult(DeliveryState.DELIVERED),
                MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "forbidden",
                ),
            ),
            MessageSendResult(DeliveryState.UNKNOWN, "partial_send"),
        ),
        (
            (
                MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "forbidden",
                ),
                MessageSendResult(DeliveryState.DELIVERED),
            ),
            MessageSendResult(DeliveryState.UNKNOWN, "partial_send"),
        ),
        (
            (
                MessageSendResult(DeliveryState.UNKNOWN, "http"),
                MessageSendResult(DeliveryState.DELIVERED),
            ),
            MessageSendResult(DeliveryState.UNKNOWN, "http"),
        ),
    ),
)
def test_send_receipt_aggregation_is_order_safe(observed, expected):
    receipt = SendReceipt()
    for result in observed:
        receipt.observe(result)
    assert receipt.result == expected


class _SequenceSender:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    async def send_result(self, _message, _content):
        self.calls += 1
        return next(self.results)


@pytest.mark.asyncio
async def test_base_handler_records_each_result_once_in_shared_receipt(
    monkeypatch,
):
    delivered = MessageSendResult(DeliveryState.DELIVERED)
    refused = MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "forbidden",
    )
    sender = _SequenceSender((delivered, refused))
    handler, monitor = _handler(sender)
    observed = []
    original = send_receipt_module.record_send_result

    def record_once(result):
        observed.append(result)
        original(result)

    monkeypatch.setattr(
        send_receipt_module,
        "record_send_result",
        record_once,
    )
    with capture_send_receipt() as receipt:
        assert await handler.send_response_result(object(), "en") == delivered
        assert await handler.send_response_result(object(), "to") == refused

    assert sender.calls == 2
    assert observed == [delivered, refused]
    assert receipt.result == MessageSendResult(
        DeliveryState.UNKNOWN,
        "partial_send",
    )
    assert monitor.response_count == 1


@pytest.mark.asyncio
async def test_task_local_receipts_do_not_cross_concurrent_dispatches():
    delivered = MessageSendResult(DeliveryState.DELIVERED)
    unknown = MessageSendResult(DeliveryState.UNKNOWN, "http")
    sender = _SequenceSender((delivered, unknown))
    handler, _ = _handler(sender)

    async def run(content):
        with capture_send_receipt() as receipt:
            await handler.send_response_result(object(), content)
            return receipt.result

    first, second = await asyncio.gather(run("en"), run("to"))

    assert {first, second} == {delivered, unknown}


class _BlockingSender:
    def __init__(self, result):
        self.result = result
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.calls = 0
        self.owned_tasks = []

    async def send_result(self, _message, _content):
        self.calls += 1
        self.owned_tasks.append(asyncio.current_task())
        self.entered.set()
        await self.release.wait()
        self.finished.set()
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    (
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "forbidden",
        ),
        MessageSendResult(DeliveryState.UNKNOWN, "http"),
    ),
)
async def test_outer_cancellation_settles_one_owned_send_before_carrier(
    terminal,
):
    sender = _BlockingSender(terminal)
    handler, monitor = _handler(sender)
    with capture_send_receipt() as receipt:
        outer = asyncio.create_task(
            handler.send_response_result(object(), "hei")
        )
        await sender.entered.wait()
        outer.cancel()
        await asyncio.sleep(0)
        sender.release.set()
        with pytest.raises(MessageSendCancelled) as raised:
            await outer

    assert raised.value.result == terminal
    assert sender.calls == 1
    assert sender.finished.is_set()
    assert len(sender.owned_tasks) == 1
    assert sender.owned_tasks[0].done()
    assert receipt.result == terminal
    assert monitor.response_count == (
        1 if terminal.state is DeliveryState.DELIVERED else 0
    )


@pytest.mark.asyncio
async def test_repeated_outer_cancellation_still_settles_same_send_once():
    terminal = MessageSendResult(DeliveryState.DELIVERED)
    sender = _BlockingSender(terminal)
    handler, monitor = _handler(sender)
    outer = asyncio.create_task(
        handler.send_response_result(object(), "hei")
    )
    await sender.entered.wait()

    outer.cancel()
    for _ in range(20):
        await asyncio.sleep(0)
        if outer.cancelling() == 0:
            break
    assert not outer.done()
    outer.cancel()
    for _ in range(20):
        await asyncio.sleep(0)
        if outer.cancelling() == 0:
            break
    assert not outer.done()
    sender.release.set()

    with pytest.raises(MessageSendCancelled) as raised:
        await outer
    assert raised.value.result == terminal
    assert sender.calls == 1
    assert sender.owned_tasks[0].done()
    assert monitor.response_count == 1


class _SelfCancellingSender:
    async def send_result(self, _message, _content):
        asyncio.current_task().cancel()
        await asyncio.sleep(0)


class _ExceptionalSender:
    async def send_result(self, _message, _content):
        raise RuntimeError("secret child exception")


class _InvalidResultSender:
    async def send_result(self, _message, _content):
        return object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender", "error_code"),
    (
        (_SelfCancellingSender(), "send_task_cancelled"),
        (_ExceptionalSender(), "send_task_exception"),
        (_InvalidResultSender(), "send_task_exception"),
    ),
)
async def test_child_failures_become_bounded_unknown(sender, error_code):
    handler, monitor = _handler(sender)
    with capture_send_receipt() as receipt:
        result = await handler.send_response_result(object(), "hei")

    assert result == MessageSendResult(
        DeliveryState.UNKNOWN,
        error_code,
    )
    assert receipt.result == result
    assert monitor.response_count == 0


@pytest.mark.asyncio
async def test_non_async_sender_adapter_fails_closed_without_attempt_retry():
    sender = SimpleNamespace(
        send_result=Mock(
            return_value=MessageSendResult(DeliveryState.DELIVERED)
        )
    )
    handler, monitor = _handler(sender)
    message = object()
    with capture_send_receipt() as receipt:
        result = await handler.send_response_result(message, "hei")

    assert result == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "missing_adapter",
    )
    sender.send_result.assert_called_once_with(message, "hei")
    assert receipt.result == result
    assert monitor.response_count == 0


@pytest.mark.asyncio
async def test_future_returning_sender_adapter_is_rejected_before_await():
    future = asyncio.get_running_loop().create_future()
    future.set_result(MessageSendResult(DeliveryState.DELIVERED))
    sender = SimpleNamespace(send_result=Mock(return_value=future))
    handler, monitor = _handler(sender)

    result = await handler.send_response_result(object(), "hei")

    assert result == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "missing_adapter",
    )
    assert monitor.response_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    (
        (MessageSendResult(DeliveryState.DELIVERED), True),
        (
            MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "forbidden",
            ),
            None,
        ),
        (MessageSendResult(DeliveryState.UNKNOWN, "http"), None),
    ),
)
async def test_legacy_send_response_projects_only_definite_delivery(
    result,
    expected,
):
    handler, _ = _handler(_SequenceSender((result,)))
    assert await handler.send_response(object(), "hei") is expected
