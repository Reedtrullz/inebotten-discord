"""Truthful dispatch outcomes for Discord profile mutations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    MessageSendCancelled,
    MessageSendResult,
)
from features.profile_handler import ProfileHandler


def make_handler(*, presence_error: Exception | None = None, delivery=None):
    change_presence = AsyncMock(
        side_effect=presence_error,
    )
    client = SimpleNamespace(
        config=SimpleNamespace(DISCORD_TOKEN="test-token"),
        change_presence=change_presence,
    )
    sender = SimpleNamespace(
        send_result=AsyncMock(
            return_value=delivery
            or MessageSendResult(DeliveryState.DELIVERED)
        )
    )
    monitor = SimpleNamespace(
        rate_limiter=SimpleNamespace(),
        loc=SimpleNamespace(),
        client=client,
        discord_sender=sender,
        response_count=0,
    )
    return ProfileHandler(monitor), change_presence, sender


@pytest.mark.asyncio
async def test_successful_profile_change_reports_committed_mutation():
    handler, change_presence, sender = make_handler()
    message = SimpleNamespace(content="status dnd")

    outcome = await handler.handle_profile_command(
        message,
        {"action": "status", "value": "dnd"},
    )

    assert outcome.ok is True
    assert outcome.mutated is True
    assert outcome.response_sent is True
    assert outcome.error_code is None
    assert outcome.delivery_result.state is DeliveryState.DELIVERED
    change_presence.assert_awaited_once()
    sender.send_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_profile_change_reports_failure_without_mutation():
    handler, change_presence, sender = make_handler(
        presence_error=RuntimeError("provider detail")
    )
    message = SimpleNamespace(content="status dnd")

    outcome = await handler.handle_profile_command(
        message,
        {"action": "status", "value": "dnd"},
    )

    assert outcome.ok is False
    assert outcome.mutated is False
    assert outcome.response_sent is True
    assert outcome.error_code == "commit_state_unknown"
    assert outcome.commit_unknown is True
    assert outcome.delivery_result.state is DeliveryState.DELIVERED
    change_presence.assert_awaited_once()
    sender.send_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_mutation_truth_survives_unknown_reply_delivery():
    handler, change_presence, _ = make_handler(
        delivery=MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    )
    message = SimpleNamespace(content="playing The Last of Us")

    outcome = await handler.handle_profile_command(
        message,
        {"action": "playing", "value": "The Last of Us"},
    )

    assert outcome.ok is True
    assert outcome.mutated is True
    assert outcome.response_sent is False
    assert outcome.delivery_result.state is DeliveryState.UNKNOWN
    change_presence.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "method", "args"),
    (
        ({"action": "status", "value": "online"}, "status", ("online",)),
        (
            {"action": "playing", "value": "CS2"},
            "activity",
            ("playing", "CS2"),
        ),
        (
            {"action": "watching", "value": "Netflix"},
            "activity",
            ("watching", "Netflix"),
        ),
    ),
)
async def test_profile_typed_dispatch_never_reparses_sentinel_content(
    payload, method, args
):
    handler, _, _ = make_handler()
    message = SimpleNamespace(content="SENTINEL MUST NEVER BE PARSED")
    expected = DispatchOutcome.success(mutated=True)
    handler.handle_status = AsyncMock(return_value=expected)
    handler.handle_activity = AsyncMock(return_value=expected)

    outcome = await handler.handle_profile_command(message, payload)

    assert outcome is expected
    if method == "status":
        handler.handle_status.assert_awaited_once_with(message, *args)
        handler.handle_activity.assert_not_awaited()
    else:
        handler.handle_activity.assert_awaited_once_with(message, *args)
        handler.handle_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {"action": "status", "value": "busy"},
        {"action": "playing", "value": ""},
        {"action": "watching", "value": "x" * 101},
    ),
)
async def test_invalid_profile_payload_never_changes_presence(payload):
    handler, change_presence, sender = make_handler()

    outcome = await handler.handle_profile_command(
        SimpleNamespace(content="SENTINEL"), payload
    )

    assert outcome.error_code == "invalid_payload"
    assert outcome.mutated is False
    assert outcome.commit_unknown is False
    change_presence.assert_not_awaited()
    sender.send_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_send_cancellation_carries_committed_presence_truth():
    handler, change_presence, _ = make_handler()
    delivery = MessageSendResult(DeliveryState.UNKNOWN, "send_task_cancelled")
    handler.send_response_result = AsyncMock(
        side_effect=MessageSendCancelled(delivery)
    )

    with pytest.raises(DispatchCancelled) as cancelled:
        await handler.handle_profile_command(
            SimpleNamespace(content="SENTINEL"),
            {"action": "watching", "value": "Netflix"},
        )

    assert cancelled.value.outcome == DispatchOutcome.success(
        mutated=True
    ).with_delivery(delivery)
    change_presence.assert_awaited_once()
    handler.send_response_result.assert_awaited_once()
