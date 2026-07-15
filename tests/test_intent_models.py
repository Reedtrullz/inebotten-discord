"""Contracts for typed intent models and the exhaustive risk policy."""

from types import SimpleNamespace

import pytest

from core.intent_models import (
    ArbitrationDecision,
    BotIntent,
    CandidateRejection,
    IntentCandidate,
    IntentResult,
    IntentRisk,
    IntentSource,
    RejectionCode,
    RouteDiagnostics,
    RoutedIntent,
)
from core.intent_policy import BASE_INTENT_RISK, classify_intent_risk
from core.intent_router import BotIntent as RouterBotIntent
from core.message_context import (
    ConversationKey,
    conversation_key_from_message,
    routing_context_from_message,
    strip_leading_bot_invocation,
)


def test_router_reexports_exact_public_type():
    assert RouterBotIntent is BotIntent


def test_four_position_result_remains_compatible():
    result = IntentResult(BotIntent.HELP, 0.96, {}, "help_keyword")
    assert result.source is IntentSource.DETERMINISTIC
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


def test_all_added_control_intents_exist():
    assert {intent.value for intent in BotIntent} >= {
        "clarify",
        "birthday_create",
        "birthday_list",
        "action_confirm",
        "action_cancel",
        "action_select",
        "action_correct",
    }


def test_candidate_to_result_copies_shared_fields_only():
    candidate = IntentCandidate(
        BotIntent.CALENDAR_DELETE,
        0.98,
        20,
        order=112,
        payload={"target": "Møte"},
        reason="calendar_delete_keyword",
        risk=IntentRisk.DESTRUCTIVE,
        specificity=3,
        requires_confirmation=True,
    )
    assert candidate.to_result() == IntentResult(
        BotIntent.CALENDAR_DELETE,
        0.98,
        {"target": "Møte"},
        "calendar_delete_keyword",
        IntentSource.DETERMINISTIC,
        IntentRisk.DESTRUCTIVE,
        True,
    )


def test_every_intent_has_exactly_one_base_risk():
    assert set(BASE_INTENT_RISK) == set(BotIntent)


def test_diagnostics_defaults_are_not_shared():
    first = RouteDiagnostics()
    second = RouteDiagnostics()
    assert first.rejection_counts is not second.rejection_counts


def test_all_public_contracts_construct():
    candidate = IntentCandidate(BotIntent.HELP, 0.9, 1)
    rejection = CandidateRejection(candidate, RejectionCode.OTHER)
    decision = ArbitrationDecision(candidate, rejected=(rejection,))
    routed = RoutedIntent(candidate.to_result(), RouteDiagnostics())

    assert decision.selected is candidate
    assert routed.result.intent is BotIntent.HELP


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("status", IntentRisk.READ_ONLY),
        ("list", IntentRisk.READ_ONLY),
        ("suggest", IntentRisk.READ_ONLY),
        ("add", IntentRisk.ADDITIVE),
        ("edit", IntentRisk.MUTATING),
        ("remove", IntentRisk.DESTRUCTIVE),
    ],
)
def test_watchlist_action_risk_overrides(action, expected):
    payload = {"watchlist": {"action": action}}
    assert classify_intent_risk(BotIntent.WATCHLIST, payload) is expected


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("get", IntentRisk.READ_ONLY),
        ("save", IntentRisk.ADDITIVE),
    ],
)
def test_quote_action_risk_overrides(action, expected):
    payload = {"quote": {"action": action}}
    assert classify_intent_risk(BotIntent.QUOTE, payload) is expected


@pytest.mark.parametrize("intent,envelope", [(BotIntent.WATCHLIST, "watchlist"), (BotIntent.QUOTE, "quote")])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        pytest.param({"watchlist": "remove", "quote": "save"}, id="non-mapping"),
        pytest.param(
            {"watchlist": {"action": "launch"}, "quote": {"action": "launch"}},
            id="unknown-action",
        ),
    ],
)
def test_umbrella_intents_fail_closed(intent, envelope, payload):
    assert envelope not in payload or payload[envelope] != {"action": ""}
    assert classify_intent_risk(intent, payload) is IntentRisk.DESTRUCTIVE


def _discord_message(*, guild_id, channel_id=10, author_id=20, mentions=()):
    return SimpleNamespace(
        guild=None if guild_id is None else SimpleNamespace(id=guild_id),
        channel=SimpleNamespace(id=channel_id),
        author=SimpleNamespace(
            id=author_id,
            display_name="Testbruker",
            name="testbruker",
        ),
        mentions=list(mentions),
    )


def test_discord_conversation_key_uses_exact_guild_channel_and_author():
    guild = _discord_message(guild_id=1, channel_id=10, author_id=20)
    direct = _discord_message(guild_id=None, channel_id=11, author_id=20)

    assert conversation_key_from_message(guild) == ConversationKey(1, 10, 20)
    assert conversation_key_from_message(direct) == ConversationKey(None, 11, 20)


def test_routing_context_excludes_bot_and_deduplicates_target_mentions():
    bot = SimpleNamespace(id=999, display_name="Ine")
    target = SimpleNamespace(id=21, display_name="Målbruker")
    message = _discord_message(
        guild_id=1,
        mentions=(bot, target, target),
    )

    context = routing_context_from_message(message, bot_user_id=999)
    assert context.key == ConversationKey(1, 10, 20)
    assert context.author.user_id == 20
    assert [(item.user_id, item.display_name) for item in context.mentions] == [
        (21, "Målbruker")
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<@123> ja", "ja"),
        ("<@!123> nei", "nei"),
        ("@Inebotten, den andre", "den andre"),
        ("  @inebotten:   ok", "ok"),
        ("<@123><@456> ja", "<@456> ja"),
    ],
)
def test_strip_leading_invocation_removes_exactly_one_authorized_prefix(
    raw,
    expected,
):
    assert strip_leading_bot_invocation(raw, bot_user_id=123) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ja <@123>",
        "@annen ja",
        "@inebottenish ja",
        "hei\n<@123> ja",
        "<@456> ja",
    ],
)
def test_strip_leading_invocation_preserves_nonmatching_or_later_mentions(raw):
    assert strip_leading_bot_invocation(raw, bot_user_id=123) == raw
