import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.dispatch_result import (
    DeliveryState,
    MessageSendCancelled,
    MessageSendResult,
)
from core.send_receipt import DiscordSendCoordinator
from features.base_handler import BaseHandler


class FakeHandler(BaseHandler):
    pass


def _rate_limiter(*, wait_result=True, sync_wait=False):
    wait = (
        Mock(return_value=wait_result)
        if sync_wait
        else AsyncMock(return_value=wait_result)
    )
    return SimpleNamespace(
        wait_if_needed=wait,
        record_sent=Mock(),
        record_failure=Mock(),
        record_dropped=Mock(),
    )


def _handler(rate_limiter):
    monitor = SimpleNamespace(
        rate_limiter=rate_limiter,
        discord_sender=DiscordSendCoordinator(rate_limiter),
        loc=object(),
        client=object(),
        response_count=0,
    )
    return FakeHandler(monitor), monitor


def _message(*, reply=None):
    return SimpleNamespace(
        channel=SimpleNamespace(id=42),
        reply=reply or AsyncMock(),
    )


@pytest.mark.asyncio
async def test_send_response_drops_when_admission_refuses_send():
    rate_limiter = _rate_limiter(wait_result=False)
    handler, monitor = _handler(rate_limiter)
    message = _message()

    result = await handler.send_response(message, "hei")

    assert result is None
    message.reply.assert_not_awaited()
    rate_limiter.record_dropped.assert_called_once_with()
    rate_limiter.record_sent.assert_not_called()
    rate_limiter.record_failure.assert_not_called()
    assert monitor.response_count == 0


@pytest.mark.asyncio
async def test_send_response_waits_once_and_projects_delivered_to_true():
    rate_limiter = _rate_limiter()
    handler, monitor = _handler(rate_limiter)
    message = _message()

    result = await handler.send_response(
        message,
        "hei",
        mention_author=True,
    )

    assert result is True
    rate_limiter.wait_if_needed.assert_awaited_once_with()
    rate_limiter.record_sent.assert_called_once_with()
    rate_limiter.record_failure.assert_not_called()
    assert monitor.response_count == 1
    assert message.reply.await_args.kwargs["mention_author"] is False


@pytest.mark.asyncio
async def test_send_response_result_exposes_quota_truth():
    rate_limiter = _rate_limiter(wait_result=False)
    handler, _ = _handler(rate_limiter)

    result = await handler.send_response_result(_message(), "hei")

    assert result.state is DeliveryState.NOT_DELIVERED
    assert result.error_code == "daily_quota"


@pytest.mark.asyncio
async def test_send_response_accepts_legacy_sync_wait_adapter():
    rate_limiter = _rate_limiter(sync_wait=True)
    handler, monitor = _handler(rate_limiter)

    result = await handler.send_response(_message(), "hei")

    assert result is True
    rate_limiter.wait_if_needed.assert_called_once_with()
    rate_limiter.record_sent.assert_called_once_with()
    assert monitor.response_count == 1


@pytest.mark.asyncio
async def test_send_response_without_injected_sender_fails_closed():
    rate_limiter = _rate_limiter()
    monitor = SimpleNamespace(
        rate_limiter=rate_limiter,
        loc=object(),
        client=object(),
        response_count=0,
    )
    handler = FakeHandler(monitor)
    message = _message()

    result = await handler.send_response_result(message, "hei")

    assert result.state is DeliveryState.NOT_DELIVERED
    assert result.error_code == "missing_adapter"
    message.reply.assert_not_awaited()
    rate_limiter.wait_if_needed.assert_not_called()


@pytest.mark.asyncio
async def test_base_handler_records_one_successful_outbound():
    rate_limiter = _rate_limiter()
    handler, monitor = _handler(rate_limiter)
    monitor.record_outbound = Mock()
    message = _message()

    assert await handler.send_response(message, "ett svar") is True

    monitor.record_outbound.assert_called_once_with(message, "ett svar")


@pytest.mark.asyncio
async def test_base_handler_without_recorder_stays_compatible():
    rate_limiter = _rate_limiter()
    handler, monitor = _handler(rate_limiter)

    assert not hasattr(monitor, "record_outbound")
    assert await handler.send_response(_message(), "ett svar") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,error_code",
    (
        (DeliveryState.NOT_DELIVERED, "forbidden"),
        (DeliveryState.UNKNOWN, "transport"),
    ),
)
async def test_base_handler_non_delivery_is_not_recorded_or_true(
    state,
    error_code,
):
    rate_limiter = _rate_limiter()
    handler, monitor = _handler(rate_limiter)
    monitor.discord_sender.send_result = AsyncMock(
        return_value=MessageSendResult(state, error_code)
    )
    monitor.record_outbound = Mock()

    assert await handler.send_response(_message(), "ett svar") is None

    monitor.record_outbound.assert_not_called()
    assert monitor.response_count == 0


@pytest.mark.asyncio
async def test_outbound_recording_failure_preserves_delivery_truth():
    rate_limiter = _rate_limiter()
    handler, monitor = _handler(rate_limiter)
    monitor.record_outbound = Mock(side_effect=RuntimeError("history failed"))

    result = await handler.send_response_result(_message(), "ett svar")

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    assert monitor.response_count == 1
    monitor.record_outbound.assert_called_once()


class _CancellationSettlementSender:
    def __init__(self, terminal):
        self.terminal = terminal
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def send_result(self, _message, _content):
        self.entered.set()
        await self.release.wait()
        return self.terminal


@pytest.mark.asyncio
async def test_delivered_cancellation_records_outbound_once_before_reraise():
    rate_limiter = _rate_limiter()
    sender = _CancellationSettlementSender(
        MessageSendResult(DeliveryState.DELIVERED)
    )
    monitor = SimpleNamespace(
        rate_limiter=rate_limiter,
        discord_sender=sender,
        loc=object(),
        client=object(),
        response_count=0,
        record_outbound=Mock(),
    )
    handler = FakeHandler(monitor)
    message = _message()

    outer = asyncio.create_task(
        handler.send_response_result(message, "ett svar")
    )
    await sender.entered.wait()
    outer.cancel()
    await asyncio.sleep(0)
    sender.release.set()

    with pytest.raises(MessageSendCancelled) as raised:
        await outer

    assert raised.value.result == MessageSendResult(DeliveryState.DELIVERED)
    monitor.record_outbound.assert_called_once_with(message, "ett svar")
    assert monitor.response_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    (
        MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
        MessageSendResult(DeliveryState.UNKNOWN, "transport"),
    ),
)
async def test_non_delivered_cancellation_never_records_outbound(terminal):
    rate_limiter = _rate_limiter()
    sender = _CancellationSettlementSender(terminal)
    monitor = SimpleNamespace(
        rate_limiter=rate_limiter,
        discord_sender=sender,
        loc=object(),
        client=object(),
        response_count=0,
        record_outbound=Mock(),
    )
    handler = FakeHandler(monitor)

    outer = asyncio.create_task(
        handler.send_response_result(_message(), "ett svar")
    )
    await sender.entered.wait()
    outer.cancel()
    await asyncio.sleep(0)
    sender.release.set()

    with pytest.raises(MessageSendCancelled) as raised:
        await outer

    assert raised.value.result == terminal
    monitor.record_outbound.assert_not_called()
    assert monitor.response_count == 0
