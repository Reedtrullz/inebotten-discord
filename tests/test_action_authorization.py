from __future__ import annotations

from unittest.mock import Mock

import pytest

from core.action_authorization import (
    ClaimedActionAuthorization,
    issue_claimed_action_authorization,
    validate_claimed_action_authorization,
)
from core.intent_models import BotIntent
from core.message_context import ConversationKey


KEY = ConversationKey(1, 2, 3)
CLAIM_ID = "claim-1"


def test_claimed_authorization_constructor_is_opaque():
    with pytest.raises(TypeError, match="claimed_authorization_is_opaque"):
        ClaimedActionAuthorization()


def test_issuer_requires_current_memory_delete_execution():
    store = Mock()
    store.is_action_executing.return_value = False

    with pytest.raises(ValueError, match="action_not_executing"):
        issue_claimed_action_authorization(
            key=KEY,
            action_id="action-1",
            claim_id=CLAIM_ID,
            pending_actions=store,
        )

    store.is_action_executing.assert_called_once_with(
        KEY,
        "action-1",
        BotIntent.MEMORY_DELETE,
        claim_id=CLAIM_ID,
    )


def test_capability_is_bound_to_exact_key_action_and_live_state():
    executing = {("action-1", CLAIM_ID, KEY)}
    store = Mock()
    store.is_action_executing.side_effect = (
        lambda key, action_id, intent, *, claim_id: (
            intent is BotIntent.MEMORY_DELETE
            and (action_id, claim_id, key) in executing
        )
    )
    capability = issue_claimed_action_authorization(
        key=KEY,
        action_id="action-1",
        claim_id=CLAIM_ID,
        pending_actions=store,
    )

    assert validate_claimed_action_authorization(
        capability,
        key=KEY,
        pending_actions=store,
    )
    assert not validate_claimed_action_authorization(
        capability,
        key=ConversationKey(1, 2, 4),
        pending_actions=store,
    )

    executing.clear()
    assert not validate_claimed_action_authorization(
        capability,
        key=KEY,
        pending_actions=store,
    )


def test_dataclass_shaped_forgery_is_rejected():
    store = Mock()
    store.is_action_executing.return_value = True
    forged = Mock(
        _key=KEY,
        _action_id="action-1",
        _intent=BotIntent.MEMORY_DELETE,
    )

    assert not validate_claimed_action_authorization(
        forged,
        key=KEY,
        pending_actions=store,
    )
    store.is_action_executing.assert_not_called()


def test_uninitialized_real_capability_is_rejected_without_raising():
    store = Mock()
    store.is_action_executing.return_value = True
    forged = object.__new__(ClaimedActionAuthorization)

    assert not validate_claimed_action_authorization(
        forged,
        key=KEY,
        pending_actions=store,
    )
    store.is_action_executing.assert_not_called()
