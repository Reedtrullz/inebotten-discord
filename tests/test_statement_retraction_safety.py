"""Fail-closed coverage for descriptive statements and same-turn retractions."""

from __future__ import annotations

import pytest

from ai.action_schema import ActionName
from core.action_bridge import ActionBridge
from core.eval_fixtures import EvalFixture
from core.intent_arbitration import arbitrate_candidates
from core.intent_models import (
    BotIntent,
    IntentCandidate,
    IntentRisk,
    RejectionCode,
)
from core.utterance import normalize_utterance
from core.utterance_semantics import SpeechAct, analyze_utterance
from tests.nlu_harness import build_production_router
from tests.nlu_test_support import bridge_context, proposal_for


@pytest.fixture(scope="module")
def production_router():
    return build_production_router(EvalFixture.MIXED_STATE)


@pytest.mark.parametrize(
    "text",
    (
        "Møte i morgen høres bra ut",
        "Meeting tomorrow sounds good",
        "Meeting tomorrow at 3pm is important",
        "Påminnelse 1 er viktig",
        "Reminder to call mom tomorrow sounds good",
        "Playing Minecraft sounds good",
        "Spiller Minecraft høres bra ut",
        "Meeting tomorrow will be fun",
        "Meeting tomorrow should be fine",
        "Meeting tomorrow works for me",
        "Meeting tomorrow got cancelled",
        "Meeting tomorrow isn't happening",
        "Møte i morgen passer for meg",
        "Møte i morgen fungerer fint",
        "Playing Minecraft will be fun",
        "Playing Minecraft works for me",
        "Playing Minecraft got boring",
        "Playing Minecraft isn't happening",
        "Reminder 1 will be important",
        "Reminder 1 works for me",
        "Reminder 1 got cancelled",
        "Reminder call mom tomorrow will be useful",
    ),
)
def test_descriptive_statements_never_authorize_deterministic_writes(
    production_router,
    text,
):
    semantics = analyze_utterance(normalize_utterance(text))
    result = production_router.route_help_example(text)

    assert semantics.speech_act is SpeechAct.STATEMENT
    assert semantics.reasons == ("statement_fallback",)
    assert semantics.allows_mutation is False
    assert result.intent is BotIntent.AI_CHAT
    assert result.reason == "unsafe_mutation_blocked"
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    (
        ("møte i morgen kl 14", BotIntent.CALENDAR_ITEM),
        ("meeting tomorrow at 3pm", BotIntent.CALENDAR_ITEM),
        ("meeting tonight", BotIntent.CALENDAR_ITEM),
        ("møte hver tirsdag kl 10", BotIntent.CALENDAR_ITEM),
        ("arrangement 17. mai kl 12:00", BotIntent.CALENDAR_ITEM),
        ("spiller Minecraft", BotIntent.PROFILE),
        ("playing Minecraft", BotIntent.PROFILE),
        ("jeg bor i Oslo", BotIntent.SET_LOCATION),
        ("I live in Oslo", BotIntent.SET_LOCATION),
    ),
)
def test_supported_terse_mutations_remain_intentional(
    production_router,
    text,
    expected_intent,
):
    semantics = analyze_utterance(normalize_utterance(text))
    result = production_router.route_help_example(text)

    assert semantics.allows_mutation is True
    assert result.intent is expected_intent
    assert result.risk is not IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    (
        (
            "lag møte i morgen med tittelen Høres bra ut",
            BotIntent.CALENDAR_ITEM,
        ),
        (
            "create meeting tomorrow named I Changed My Mind",
            BotIntent.CALENDAR_ITEM,
        ),
        (
            "remind me to watch Forget About It tomorrow",
            BotIntent.REMINDER_CREATE,
        ),
        ("playing No Actually", BotIntent.PROFILE),
        ("save quote Cancel That Please", BotIntent.QUOTE),
        ("save quote Scratch It", BotIntent.QUOTE),
        ("add Leave It to my watchlist", BotIntent.WATCHLIST),
    ),
)
def test_explicit_actions_keep_descriptive_and_retraction_words_as_payload(
    production_router,
    text,
    expected_intent,
):
    result = production_router.route_help_example(text)

    assert analyze_utterance(normalize_utterance(text)).allows_mutation is True
    assert result.intent is expected_intent
    assert result.risk is not IntentRisk.READ_ONLY


def test_deterministic_arbitration_enforces_false_allows_mutation():
    utterance = normalize_utterance("Meeting tomorrow sounds good")
    semantics = analyze_utterance(utterance)
    candidate = IntentCandidate(
        BotIntent.CALENDAR_ITEM,
        0.97,
        35,
        payload={"calendar_item": {"title": "Meeting", "days_offset": 1}},
        risk=IntentRisk.ADDITIVE,
        domain_terms=("meeting",),
        specificity=3,
    )

    decision = arbitrate_candidates(utterance, semantics, (candidate,))

    assert decision.selected is None
    assert decision.blocked is True
    assert [item.code for item in decision.rejected] == [
        RejectionCode.UNSAFE_SEMANTIC
    ]


@pytest.mark.parametrize(
    "text",
    (
        "create meeting tomorrow I changed my mind",
        "create meeting tomorrow but I changed my mind",
        "create meeting tomorrow sorry I changed my mind",
        "lag møte i morgen beklager jeg ombestemte meg",
        "lag møte i morgen beklager, jeg ombestemte meg",
        "create meeting tomorrow, forget about it",
        "create meeting tomorrow, scratch it",
        "create meeting tomorrow, leave it",
        "create meeting tomorrow, no actually",
        "create meeting tomorrow, cancel that please",
        "create meeting tomorrow, I no longer want that",
        "create meeting tomorrow, cancel it after all",
        "create meeting tomorrow, changed my mind about that",
        "create meeting tomorrow, forget it then",
        "create meeting tomorrow, scratch that please",
        "create meeting tomorrow, dropp den",
        "create meeting tomorrow, avlys det",
        "create meeting tomorrow, ombestemte meg om det",
        "create meeting tomorrow, glem det da",
    ),
)
def test_requested_terminal_retraction_forms_are_inert(
    production_router,
    text,
):
    result = production_router.route_help_example(text)

    assert analyze_utterance(normalize_utterance(text)).allows_mutation is False
    assert result.intent is BotIntent.AI_CHAT
    assert result.risk is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "text",
    (
        "create a meeting tomorrow, I changed my mind",
        "remind me to call mom tomorrow, but I changed my mind",
        "add Arrival to my watchlist, sorry I changed my mind",
        "close poll 1, forget about it",
        "save quote Stay curious, scratch it",
        "playing Minecraft, leave it",
        "I live in Oslo, no actually",
        "add my birthday 15.05, cancel that please",
    ),
)
def test_terminal_retractions_fail_closed_across_write_families(
    production_router,
    text,
):
    result = production_router.route_help_example(text)

    assert result.intent is BotIntent.AI_CHAT
    assert result.risk is IntentRisk.READ_ONLY
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    (
        ("playing I Changed My Mind", BotIntent.PROFILE),
        ("playing Leave It", BotIntent.PROFILE),
        ("save quote I Changed My Mind", BotIntent.QUOTE),
        ("save quote Leave It", BotIntent.QUOTE),
        ("save quote I No Longer Want That", BotIntent.QUOTE),
        ("save quote Forget It Then", BotIntent.QUOTE),
        ("save quote Dropp den", BotIntent.QUOTE),
        ("add Scratch It to my watchlist", BotIntent.WATCHLIST),
        (
            "create meeting tomorrow named I Changed My Mind",
            BotIntent.CALENDAR_ITEM,
        ),
    ),
)
def test_unmarked_title_shaped_retractions_remain_payload(
    production_router,
    text,
    expected_intent,
):
    result = production_router.route_help_example(text)

    assert result.intent is expected_intent
    assert result.risk is not IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    ("action", "slots", "text"),
    (
        (
            ActionName.CALENDAR_CREATE,
            {"title": "Meeting", "date": "15.07.2026"},
            "Meeting tomorrow got cancelled",
        ),
        (
            ActionName.REMINDER_CREATE,
            {"text": "call mom", "due_date": "15.07.2026"},
            "Reminder call mom tomorrow will be useful",
        ),
        (
            ActionName.PROFILE_PLAYING,
            {"value": "Minecraft"},
            "Playing Minecraft works for me",
        ),
    ),
)
def test_model_bridge_cannot_reopen_untrusted_statement_writes(
    action,
    slots,
    text,
):
    result = ActionBridge().to_result(
        proposal_for(action, slots, confidence=0.99),
        bridge_context(utterance=normalize_utterance(text)),
    )

    assert result is None
