from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from features.base_handler import BaseHandler


class FakeHandler(BaseHandler):
    pass


@pytest.mark.asyncio
async def test_send_response_drops_when_rate_limiter_says_no():
    rate_limiter = SimpleNamespace(
        can_send=Mock(return_value=(False, "daily quota")),
        wait_if_needed=AsyncMock(return_value=True),
        record_sent=Mock(),
        record_failure=Mock(),
        record_dropped=Mock(),
    )
    monitor = SimpleNamespace(rate_limiter=rate_limiter, loc=object(), client=object())
    handler = FakeHandler(monitor)
    message = SimpleNamespace(channel=object(), reply=AsyncMock())

    result = await handler.send_response(message, "hei")

    assert result is None
    message.reply.assert_not_awaited()
    rate_limiter.record_dropped.assert_called_once()
    rate_limiter.record_sent.assert_not_called()


@pytest.mark.asyncio
async def test_send_response_waits_before_sending():
    rate_limiter = SimpleNamespace(
        can_send=Mock(return_value=(True, None)),
        wait_if_needed=AsyncMock(return_value=True),
        record_sent=Mock(),
        record_failure=Mock(),
    )
    monitor = SimpleNamespace(rate_limiter=rate_limiter, loc=object(), client=object(), response_count=0)
    handler = FakeHandler(monitor)
    sent = object()
    message = SimpleNamespace(channel=object(), reply=AsyncMock(return_value=sent))

    result = await handler.send_response(message, "hei")

    assert result is sent
    rate_limiter.wait_if_needed.assert_awaited_once()
    rate_limiter.record_sent.assert_called_once()
    assert monitor.response_count == 1
