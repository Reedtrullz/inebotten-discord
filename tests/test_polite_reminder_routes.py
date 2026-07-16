"""Polite reminder frames produce one complete typed operation."""

import pytest

from cal_system.reminder_manager import parse_reminder_command
from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    "text",
    (
        "kan du opprette en påminnelse om å ringe legen i morgen kl 14?",
        "could you create a reminder to call the doctor tomorrow at 2 pm?",
    ),
)
def test_polite_reminder_create_routes_with_clean_payload(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.REMINDER_CREATE
    assert result.payload["reminder"]["action"] == "add"
    assert result.payload["reminder"]["time"] == "14:00"
    assert result.payload["reminder"]["due_date"] == "15.07.2026"
    assert result.payload["reminder"]["text"] in {
        "ringe legen",
        "call the doctor",
    }


@pytest.mark.parametrize(
    ("text", "intent", "action"),
    (
        ("kan du slette påminnelsen 1?", BotIntent.REMINDER_DELETE, "delete"),
        (
            "kan du fullføre påminnelsen 1?",
            BotIntent.REMINDER_COMPLETE,
            "complete",
        ),
        (
            "kan du markere påminnelsen 1 ferdig?",
            BotIntent.REMINDER_COMPLETE,
            "complete",
        ),
    ),
)
def test_polite_reminder_mutations_keep_the_visible_target(text, intent, action):
    result = build_production_router(
        EvalFixture.ACTIVE_REMINDER
    ).route_help_example(text)

    assert result.intent is intent
    assert result.payload == {
        "reminder": {"action": action, "number": 1}
    }


@pytest.mark.parametrize(
    "text",
    (
        "Ola sa kan du slette påminnelsen 1",
        "ikke slett påminnelsen 1",
        "kan du forklare hvordan man markerer en påminnelse ferdig?",
    ),
)
def test_inert_reminder_neighbors_never_mutate(text):
    result = build_production_router(
        EvalFixture.ACTIVE_REMINDER
    ).route_help_example(text)

    assert result.intent not in {
        BotIntent.REMINDER_DELETE,
        BotIntent.REMINDER_COMPLETE,
    }


def test_reminder_conflicting_plain_daypart_never_writes():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "minn meg på å ringe legen i morgen klokka 2 på kvelden"
    )

    assert result.intent is not BotIntent.REMINDER_CREATE


def test_english_reminder_daypart_is_temporal_not_payload_text():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "remind me to call the doctor tomorrow morning"
    )

    assert result.intent is BotIntent.REMINDER_CREATE
    assert result.payload["reminder"]["text"] == "call the doctor"
    assert result.payload["reminder"]["due_date"] == "15.07.2026"
    assert result.payload["reminder"]["time"] == "08:00"
