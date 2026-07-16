"""Typed deterministic routing for bounded Discord profile commands."""

from __future__ import annotations

import pytest

from core.intent_models import BotIntent, IntentRisk
from features.profile_commands import parse_profile_command
from tests.nlu_harness import build_production_router
from core.eval_fixtures import EvalFixture


@pytest.mark.parametrize(
    ("text", "payload"),
    (
        ("status online", {"action": "status", "value": "online"}),
        ("spiller CS2", {"action": "playing", "value": "CS2"}),
        ("ser på Netflix", {"action": "watching", "value": "Netflix"}),
        (
            "kan du sette statusen til idle?",
            {"action": "status", "value": "idle"},
        ),
        (
            "could you set my status to dnd?",
            {"action": "status", "value": "dnd"},
        ),
        (
            "kan du sette aktiviteten til å spille CS2?",
            {"action": "playing", "value": "CS2"},
        ),
        (
            "could you set activity to watching Netflix?",
            {"action": "watching", "value": "Netflix"},
        ),
    ),
)
def test_profile_routes_keep_typed_operation_and_value(text, payload):
    adapter = build_production_router(EvalFixture.EMPTY)

    result = adapter.route_help_example(text)

    assert result.intent is BotIntent.PROFILE
    assert result.payload == {"profile": payload}
    assert result.risk is IntentRisk.MUTATING
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "text",
    (
        "status busy",
        "jeg spiller CS2",
        "spiller",
        "ser på",
        "status online i går",
        "hva betyr status online?",
        "spiller " + "x" * 101,
        "kan du ikke sette statusen til idle?",
        "Ola sa kan du sette statusen til idle",
        "kan du forklare hvordan man setter statusen til idle?",
    ),
)
def test_profile_parser_rejects_unbounded_or_conversational_neighbors(text):
    assert parse_profile_command(text) is None


def test_profile_parser_strips_only_the_literal_bot_invocation():
    assert parse_profile_command("@inebotten spiller Life is Strange") == {
        "action": "playing",
        "value": "Life is Strange",
    }
    assert parse_profile_command("<@42> spiller Life is Strange") is None
