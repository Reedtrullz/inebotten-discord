"""Natural calendar-create frames keep clean, typed event payloads."""

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    ("text", "title", "time"),
    (
        (
            "kan du legge inn et møte i morgen klokka halv tre på "
            "ettermiddagen?",
            "Møte",
            "14:30",
        ),
        (
            "kan du legge inn et møte med Ola i morgen kvart over to på "
            "ettermiddagen?",
            "Møte med Ola",
            "14:15",
        ),
        (
            "kan du legge inn et møte i morgen kl 14.30?",
            "Møte",
            "14:30",
        ),
        ("legg til et møte i morgen kl 14.30", "Møte", "14:30"),
        ("opprett et møte i morgen kl 14.30", "Møte", "14:30"),
        ("kan du sette opp et møte i morgen kl 14:30", "Møte", "14:30"),
        ("kan du booke et møte i morgen kl 14:30", "Møte", "14:30"),
    ),
)
def test_polite_and_imperative_calendar_creates_are_canonical(
    text,
    title,
    time,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] == title
    assert result.payload["calendar_item"]["time"] == time
    assert result.payload["calendar_item"]["date"] == "15.07.2026"


def test_ambiguous_half_clock_calendar_create_requests_daypart():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "kan du legge inn et møte i morgen klokka halv tre?"
    )

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "calendar_time_ambiguous"
    assert result.requires_confirmation is False
    assert result.payload == {
        "clarification": (
            "Mener du tidspunktet om morgenen eller på ettermiddagen?"
        )
    }


def test_ambiguous_numeric_half_without_clock_cue_never_becomes_title_data():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "møte i morgen halv 3"
    )

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "calendar_time_ambiguous"
    assert "calendar_item" not in result.payload


def test_calendar_half_twelve_evening_is_exactly_2330():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "møte i morgen klokka halv tolv på kvelden"
    )

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] == "Møte"
    assert result.payload["calendar_item"]["time"] == "23:30"


def test_calendar_conflicting_plain_daypart_never_writes():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "møte i morgen klokka 2 på kvelden"
    )

    assert result.intent is not BotIntent.CALENDAR_ITEM


@pytest.mark.parametrize(
    "text",
    (
        "lag møte i morgen på morgenen",
        "lag møte i morgen tidlig",
    ),
)
def test_calendar_morning_context_is_temporal_not_title_data(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] == "Møte"
    assert result.payload["calendar_item"]["time"] == "08:00"
    assert result.payload["calendar_item"]["date"] == "15.07.2026"


@pytest.mark.parametrize(
    ("text", "time"),
    (
        ("meeting tomorrow morning", "08:00"),
        ("meeting tomorrow afternoon", "14:00"),
        ("meeting tomorrow evening", "19:00"),
        ("meeting tonight", "19:00"),
    ),
)
def test_english_calendar_dayparts_are_removed_from_the_title(text, time):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.CALENDAR_ITEM
    assert result.payload["calendar_item"]["title"] == "Meeting"
    assert result.payload["calendar_item"]["time"] == time


def test_conflicting_calendar_recurrences_request_clarification_without_write():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "lag møte hver uke og hver måned"
    )

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "calendar_recurrence_conflict"
    assert "calendar_item" not in result.payload


@pytest.mark.parametrize(
    ("text", "intent"),
    (
        ("kan du slette møtet med Ola?", BotIntent.CALENDAR_DELETE),
        ("kan du fullføre møtet med Ola?", BotIntent.CALENDAR_COMPLETE),
        (
            "kan du markere møtet med Ola ferdig?",
            BotIntent.CALENDAR_COMPLETE,
        ),
    ),
)
def test_polite_calendar_mutations_bind_one_existing_title(text, intent):
    result = build_production_router(
        EvalFixture.CALENDAR_TITLE_MEETING
    ).route_help_example(text)

    assert result.intent is intent
    assert result.payload == {"calendar_target": {"target": "møte med Ola"}}


@pytest.mark.parametrize(
    "text",
    (
        "Ola sa kan du slette møtet med Ola",
        "ikke slett møtet med Ola",
        "kan du forklare hvordan man markerer et møte ferdig?",
    ),
)
def test_calendar_mutation_explanations_and_negations_are_inert(text):
    result = build_production_router(
        EvalFixture.CALENDAR_TITLE_MEETING
    ).route_help_example(text)

    assert result.intent not in {
        BotIntent.CALENDAR_DELETE,
        BotIntent.CALENDAR_COMPLETE,
    }
