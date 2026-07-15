from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from core.action_authorization import issue_claimed_action_authorization
from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendResult,
)
from core.intent_models import BotIntent, IntentResult, IntentRisk
from core.message_context import ConversationKey
from core.pending_actions import PendingActionStore
from features.memory_handler import MemoryHandler
from tests.nlu_test_support import ready_confirmation


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Europe/Oslo"))
KEY = ConversationKey(1, 2, 3)


@pytest.fixture
def monitor():
    sender = SimpleNamespace(
        send_result=AsyncMock(
            return_value=MessageSendResult(DeliveryState.DELIVERED)
        )
    )
    return SimpleNamespace(
        rate_limiter=SimpleNamespace(),
        loc=SimpleNamespace(),
        client=SimpleNamespace(),
        discord_sender=sender,
        response_count=0,
        pending_actions=PendingActionStore(now_provider=lambda: NOW),
        user_memory=SimpleNamespace(
            format_user_memory_for_user=AsyncMock(return_value="minne"),
            export_user_memory=AsyncMock(return_value={"location": "Oslo"}),
            delete_user_memory_result=AsyncMock(return_value=True),
        ),
    )


@pytest.fixture
def message():
    return SimpleNamespace(
        author=SimpleNamespace(id=3, name="Reidar"),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=2),
    )


def _claimed_authorization(monitor):
    route = IntentResult(
        BotIntent.MEMORY_DELETE,
        0.99,
        {"memory": {"action": "delete"}},
        risk=IntentRisk.DESTRUCTIVE,
        requires_confirmation=True,
    )
    ready = ready_confirmation(
        monitor.pending_actions,
        KEY,
        route,
        "slett lagret brukerminne",
    )
    claimed = monitor.pending_actions.claim(KEY, ready.action_id)
    assert claimed is not None
    capability = issue_claimed_action_authorization(
        key=KEY,
        action_id=claimed.action_id,
        claim_id=claimed.claim_id,
        pending_actions=monitor.pending_actions,
    )
    return claimed, capability


@pytest.mark.asyncio
async def test_confirmed_payload_without_capability_cannot_delete(monitor, message):
    handler = MemoryHandler(monitor)

    outcome = await handler.handle_memory(
        message,
        {"action": "delete", "confirmed": True},
    )

    assert not outcome.ok
    assert outcome.error_code == "confirmation_required"
    monitor.user_memory.delete_user_memory_result.assert_not_awaited()
    monitor.discord_sender.send_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_live_capability_deletes_exactly_once(monitor, message):
    handler = MemoryHandler(monitor)
    _, capability = _claimed_authorization(monitor)

    outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=capability,
    )

    assert outcome.ok and outcome.mutated and outcome.response_sent
    monitor.user_memory.delete_user_memory_result.assert_awaited_once_with(3)
    monitor.discord_sender.send_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_memory_is_idempotent_success(monitor, message):
    monitor.user_memory.delete_user_memory_result.return_value = False
    handler = MemoryHandler(monitor)
    _, capability = _claimed_authorization(monitor)

    outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=capability,
    )

    assert outcome.ok and not outcome.mutated
    assert outcome.response_sent


@pytest.mark.asyncio
async def test_stale_capability_after_settlement_cannot_delete(monitor, message):
    handler = MemoryHandler(monitor)
    claimed, capability = _claimed_authorization(monitor)
    assert monitor.pending_actions.complete(KEY, claimed.action_id)

    outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=capability,
    )

    assert outcome.error_code == "confirmation_required"
    monitor.user_memory.delete_user_memory_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_capability_stays_stale_after_retry_reclaim(monitor, message):
    handler = MemoryHandler(monitor)
    first_claim, old_capability = _claimed_authorization(monitor)
    assert monitor.pending_actions.release_retryable(
        KEY,
        first_claim.action_id,
        DispatchOutcome.failure("storage_write_failed", retryable=True),
    )
    second_claim = monitor.pending_actions.claim(KEY, first_claim.action_id)
    assert second_claim is not None
    assert second_claim.claim_id != first_claim.claim_id

    old_outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=old_capability,
    )

    assert old_outcome.error_code == "confirmation_required"
    monitor.user_memory.delete_user_memory_result.assert_not_awaited()

    current_capability = issue_claimed_action_authorization(
        key=KEY,
        action_id=second_claim.action_id,
        claim_id=second_claim.claim_id,
        pending_actions=monitor.pending_actions,
    )
    current_outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=current_capability,
    )
    assert current_outcome.ok
    monitor.user_memory.delete_user_memory_result.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_cross_conversation_capability_cannot_delete(monitor, message):
    handler = MemoryHandler(monitor)
    _, capability = _claimed_authorization(monitor)
    message.channel.id = 999

    outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=capability,
    )

    assert outcome.error_code == "confirmation_required"
    monitor.user_memory.delete_user_memory_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_storage_failure_preserves_retryability(monitor, message):
    monitor.user_memory.delete_user_memory_result.side_effect = (
        ManagerMutationError("storage_write_failed", mutated=False)
    )
    handler = MemoryHandler(monitor)
    _, capability = _claimed_authorization(monitor)

    outcome = await handler.handle_memory(
        message,
        {"action": "delete"},
        authorization=capability,
    )

    assert not outcome.ok
    assert outcome.error_code == "storage_write_failed"
    assert outcome.retryable
    assert not outcome.mutated


@pytest.mark.asyncio
async def test_post_commit_manager_cancellation_preserves_mutation_truth(
    monitor,
    message,
):
    monitor.user_memory.delete_user_memory_result.side_effect = (
        ManagerMutationCancelled(
            "cancelled",
            mutated=True,
            retryable=False,
        )
    )
    handler = MemoryHandler(monitor)
    _, capability = _claimed_authorization(monitor)

    with pytest.raises(DispatchCancelled) as cancelled:
        await handler.handle_memory(
            message,
            {"action": "delete"},
            authorization=capability,
        )

    assert cancelled.value.outcome.mutated
    assert not cancelled.value.outcome.retryable
    monitor.discord_sender.send_result.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["view", "export"])
async def test_read_branches_return_delivery_aware_outcomes(
    monitor,
    message,
    action,
):
    outcome = await MemoryHandler(monitor).handle_memory(
        message,
        {"action": action},
    )

    assert outcome.ok and not outcome.mutated
    assert outcome.response_sent
    assert outcome.delivery_result.state is DeliveryState.DELIVERED
