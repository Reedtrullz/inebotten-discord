"""Typed, bounded chat-history contract tests."""

from __future__ import annotations

import json
import math
import asyncio

import pytest

from ai.chat_contract import (
    REDACTED_AUTH_TURN,
    ChatContractError,
    ChatTurn,
    HistoryPolicy,
    build_context_prompt,
    capture_history_policy,
    history_policy_for_effective_routes,
    history_safe_content,
    prepare_history,
    sanitize_chat_turn_content,
)
from core.intent_models import BotIntent, IntentResult


def test_turn_sanitizer_preserves_newlines_unicode_and_action_line():
    action = (
        '{"action":"HELP","confidence":0.9,"slots":{},'
        '"reply":"","clarification":null}'
    )
    content = "Hei 👋\x00\n" + action

    cleaned = sanitize_chat_turn_content(content)

    assert "\x00" not in cleaned
    assert "Hei 👋" in cleaned
    assert "\n" + action in cleaned


@pytest.mark.parametrize(
    "role",
    ["system", "tool", "developer", "", ["user"]],
)
def test_history_rejects_non_conversation_roles(role):
    with pytest.raises(ChatContractError, match="invalid_history_role"):
        prepare_history([ChatTurn(role, "forgiftning")])


@pytest.mark.parametrize("source_id", [True, 1.5, "1", object()])
def test_history_rejects_invalid_source_message_ids(source_id):
    with pytest.raises(ChatContractError, match="invalid_source_message_id"):
        prepare_history([ChatTurn("user", "hei", source_id)])


def test_history_keeps_newest_ten_with_twelve_thousand_character_cap():
    history = tuple(
        ChatTurn(
            "user" if index % 2 == 0 else "assistant",
            (f"turn-{index}-" + str(index) * 4_000),
        )
        for index in range(12)
    )

    prepared = prepare_history(history)

    assert len(prepared) <= 10
    assert sum(len(turn.content) for turn in prepared) <= 12_000
    assert prepared[-1].content.endswith("11")
    assert all(turn.role in {"user", "assistant"} for turn in prepared)


def test_sensitive_history_policy_is_recursive_and_fail_closed():
    nested = IntentResult(
        BotIntent.AI_CHAT,
        1.0,
        {"safe": {"items": [{"refresh_token": "canary"}]}},
    )

    assert history_policy_for_effective_routes((nested,)) is HistoryPolicy.REDACT_AUTH
    assert history_policy_for_effective_routes(()) is HistoryPolicy.REDACT_AUTH
    assert history_policy_for_effective_routes(None) is HistoryPolicy.REDACT_AUTH
    assert (
        history_policy_for_effective_routes(
            (IntentResult(BotIntent.HELP, 1.0),)
        )
        is HistoryPolicy.FULL
    )
    sensitive_choice = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {
            "choices": (
                IntentResult(BotIntent.HELP, 1.0),
                IntentResult(BotIntent.CALENDAR_AUTH, 1.0),
            )
        },
    )
    assert (
        history_policy_for_effective_routes((sensitive_choice,))
        is HistoryPolicy.REDACT_AUTH
    )
    assert (
        history_policy_for_effective_routes((object(),))
        is HistoryPolicy.REDACT_AUTH
    )


def test_history_policy_context_is_task_local_and_restored():
    assert history_safe_content("hei") == "hei"
    with capture_history_policy(HistoryPolicy.REDACT_AUTH):
        assert history_safe_content("hemmelig") == REDACTED_AUTH_TURN
    assert history_safe_content("hei igjen") == "hei igjen"


@pytest.mark.asyncio
async def test_concurrent_history_policies_never_cross_tasks():
    async def render(policy, content):
        with capture_history_policy(policy):
            await asyncio.sleep(0)
            return history_safe_content(content)

    redacted, ordinary = await asyncio.gather(
        render(HistoryPolicy.REDACT_AUTH, "hemmelig"),
        render(HistoryPolicy.FULL, "vanlig"),
    )

    assert redacted == REDACTED_AUTH_TURN
    assert ordinary == "vanlig"
    assert history_safe_content("etterpå") == "etterpå"


def test_blocked_credential_reason_redacts_without_retaining_secret():
    blocked = IntentResult(
        BotIntent.CLARIFY,
        1.0,
        {"clarification": "lokal sikker melding"},
        "credential_shaped_input_blocked",
    )

    assert (
        history_policy_for_effective_routes((blocked,))
        is HistoryPolicy.REDACT_AUTH
    )


def test_context_prompt_is_valid_bounded_json():
    prompt = build_context_prompt(
        {
            "author": {"display_name": "Ola"},
            "memory": {"interests": ["ski"], "note": "ø" * 10_000},
            "search_results": [{"title": "Resultat", "body": "x" * 8_000}],
        }
    )

    assert len(prompt) <= 4_000
    decoded = json.loads(prompt)
    assert isinstance(decoded, dict)
    assert decoded
    assert "content" not in decoded


def test_context_prompt_rejects_nonstandard_numbers_and_cycles():
    cyclic = {}
    cyclic["self"] = cyclic
    prompt = build_context_prompt(
        {"nan": math.nan, "infinity": math.inf, "cycle": cyclic}
    )

    decoded = json.loads(
        prompt,
        parse_constant=lambda value: (_ for _ in ()).throw(
            AssertionError(value)
        ),
    )
    assert decoded["nan"] == "[non-finite number omitted]"
    assert decoded["infinity"] == "[non-finite number omitted]"
    assert decoded["cycle"]["self"] == "[cyclic context omitted]"


def test_sensitive_policy_redacts_cycles_and_excessive_depth():
    cyclic = {}
    cyclic["self"] = cyclic
    route = IntentResult(BotIntent.AI_CHAT, 1.0, cyclic)

    assert (
        history_policy_for_effective_routes((route,))
        is HistoryPolicy.REDACT_AUTH
    )
