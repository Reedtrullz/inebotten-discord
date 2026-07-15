from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.dispatch_result import DeliveryState
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
