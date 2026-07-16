"""Natural school-holiday requests stay broad without stealing statements."""

from __future__ import annotations

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    "text",
    (
        "sommerferie Oslo",
        "høstferie Oslo",
        "haustferie Bergen",
        "school holidays Oslo",
        "winter holiday Oslo",
        "summer vacation Oslo",
        "fall break Oslo",
        "kan du vise skoleferiene i Tromsø?",
        "Can you show school holidays in Tromsø?",
        "could you show me school holidays in Oslo, please?",
        "could you show me school holidays in Oslo please",
        "kan du vise meg skoleferiene i Oslo takk?",
        "if you have time could you show me school holidays in Oslo",
        "could you if you have time show me school holidays in Oslo",
        "hvor lenge er det til sommerferien?",
        "when is summer vacation?",
        "when is summer vacation in Oslo?",
        "what are the school holiday dates?",
        "what are the school holidays in Oslo?",
        "what school holidays are there in Oslo?",
        "hva er skoleferiene i Oslo?",
        "which school holidays are there in Oslo?",
        "which school holidays are in Oslo?",
        "which school holidays does Oslo have?",
        "hvilke skoleferier har Oslo?",
        "show school holidays in Oslo",
    ),
)
def test_natural_school_holiday_requests_route_to_safe_handler(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SCHOOL_HOLIDAYS
    assert result.payload == {}


@pytest.mark.parametrize(
    "text",
    (
        "I loved summer vacation",
        "summer vacation was wonderful",
        "school holidays are too short",
        "sommerferien var fin",
        "vi snakket om høstferie i Oslo",
        "vi hadde en fin sommerferie i fjor",
        "høstferien var fin",
        "I loved my summer vacation photos",
        "winter break is a movie title",
        "summer vacation Oslo sounds great",
        "summer vacation Oslo sucks",
        "sommerferie Oslo høres fantastisk ut",
        "sommerferie Oslo suger",
        "høstferie Bergen virker fin",
        "school holidays Tromsø seem short",
        "winter break Oslo rocks",
        "why are school holidays too short?",
        "do you like summer vacation?",
        "what do you think about school holidays?",
        "how do school holidays affect families?",
        "why was summer vacation fun?",
        "how do I plan a summer vacation?",
        "where should I go for summer vacation?",
        "what are school holidays?",
        "when is Summer Vacation showing at the cinema?",
        "when is the movie Summer Vacation on TV?",
        "when is the book School Holidays published?",
    ),
)
def test_school_holiday_statements_remain_conversation(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.AI_CHAT
