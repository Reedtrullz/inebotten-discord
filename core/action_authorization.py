"""Opaque capabilities for centrally confirmed destructive actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.intent_models import BotIntent
from core.message_context import ConversationKey


class PendingExecutionView(Protocol):
    def is_action_executing(
        self,
        key: ConversationKey,
        action_id: str,
        expected_intent: BotIntent,
        *,
        claim_id: str,
    ) -> bool: ...


_CAPABILITY_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class ClaimedActionAuthorization:
    """Unforgeable proof that one exact memory delete is executing."""

    _seal: object
    _key: ConversationKey
    _action_id: str
    _claim_id: str
    _intent: BotIntent

    def __init__(self, *args, **kwargs):
        del args, kwargs
        raise TypeError("claimed_authorization_is_opaque")


def issue_claimed_action_authorization(
    *,
    key: ConversationKey,
    action_id: str,
    claim_id: str,
    pending_actions: PendingExecutionView,
) -> ClaimedActionAuthorization:
    """Issue a capability only for a currently executing memory delete."""

    if not isinstance(claim_id, str) or not claim_id:
        raise ValueError("invalid_claim_id")
    if not pending_actions.is_action_executing(
        key,
        action_id,
        BotIntent.MEMORY_DELETE,
        claim_id=claim_id,
    ):
        raise ValueError("action_not_executing")
    capability = object.__new__(ClaimedActionAuthorization)
    object.__setattr__(capability, "_seal", _CAPABILITY_SEAL)
    object.__setattr__(capability, "_key", key)
    object.__setattr__(capability, "_action_id", action_id)
    object.__setattr__(capability, "_claim_id", claim_id)
    object.__setattr__(capability, "_intent", BotIntent.MEMORY_DELETE)
    return capability


def validate_claimed_action_authorization(
    capability: object,
    *,
    key: ConversationKey,
    pending_actions: PendingExecutionView,
) -> bool:
    """Validate the private seal and current live execution state."""

    if type(capability) is not ClaimedActionAuthorization:
        return False
    try:
        seal = capability._seal
        capability_key = capability._key
        action_id = capability._action_id
        claim_id = capability._claim_id
        intent = capability._intent
    except AttributeError:
        return False
    return bool(
        seal is _CAPABILITY_SEAL
        and capability_key == key
        and intent is BotIntent.MEMORY_DELETE
        and pending_actions.is_action_executing(
            key,
            action_id,
            BotIntent.MEMORY_DELETE,
            claim_id=claim_id,
        )
    )
