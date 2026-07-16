"""Public natural-language examples must keep routing as advertised."""

from __future__ import annotations

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from tests.nlu_harness import build_production_router


DOCUMENTED_EXAMPLES = (
    # README and quick reference: calendar and reminders.
    (
        "Kan du legge inn et møte med Ola i morgen klokka 14?",
        BotIntent.CALENDAR_ITEM,
        EvalFixture.EMPTY,
    ),
    ("Kan du vise meg kalenderen?", BotIntent.CALENDAR_LIST, EvalFixture.EMPTY),
    (
        "Kan du flytte møtet med Ola til fredag klokka 10?",
        BotIntent.CALENDAR_EDIT,
        EvalFixture.CALENDAR_TITLE_MEETING,
    ),
    (
        "Kan du markere møtet med Ola ferdig?",
        BotIntent.CALENDAR_COMPLETE,
        EvalFixture.CALENDAR_TITLE_MEETING,
    ),
    (
        "Kan du slette møtet med Ola?",
        BotIntent.CALENDAR_DELETE,
        EvalFixture.CALENDAR_TITLE_MEETING,
    ),
    (
        "Kan du minne meg på å ringe legen om to timer?",
        BotIntent.REMINDER_CREATE,
        EvalFixture.EMPTY,
    ),
    ("Kan du vise påminnelsene mine?", BotIntent.REMINDER_LIST, EvalFixture.ACTIVE_REMINDER),
    (
        "Kan du markere påminnelse 1 som ferdig?",
        BotIntent.REMINDER_COMPLETE,
        EvalFixture.ACTIVE_REMINDER,
    ),
    (
        "Kan du søke i kalenderen etter møte?",
        BotIntent.CALENDAR_SEARCH,
        EvalFixture.CALENDAR_TITLE_MEETING,
    ),
    # Documentation-only calendar phrasings.
    (
        "Kan du legge inn lunsj med teamet fredag klokka 12?",
        BotIntent.CALENDAR_ITEM,
        EvalFixture.EMPTY,
    ),
    (
        "Kan du minne meg på å betale regninga imårra?",
        BotIntent.REMINDER_CREATE,
        EvalFixture.EMPTY,
    ),
    (
        "Kan du legge inn tannlegen neste tirsdag klokka 09?",
        BotIntent.CALENDAR_ITEM,
        EvalFixture.EMPTY,
    ),
    (
        "Kan du legge inn RBK-kampen 12.04 klokka 18:30 hver uke?",
        BotIntent.CALENDAR_ITEM,
        EvalFixture.EMPTY,
    ),
    # Polls, quotes, watchlist, and birthdays.
    (
        "Kan du lage en avstemning: Hva spiser vi? pizza, burger eller taco",
        BotIntent.POLL_CREATE,
        EvalFixture.EMPTY,
    ),
    ("Kan du vise aktive avstemninger?", BotIntent.POLL_LIST, EvalFixture.ACTIVE_POLL),
    ("Jeg stemmer på alternativ 1", BotIntent.POLL_VOTE, EvalFixture.ACTIVE_POLL),
    (
        "Kan du redigere avstemningen 1 spørsmål: Middag?",
        BotIntent.POLL_EDIT,
        EvalFixture.ACTIVE_POLL,
    ),
    ("Kan du lukke avstemning 1?", BotIntent.POLL_CLOSE, EvalFixture.ACTIVE_POLL),
    ("Kan du lagre dette som et sitat: Et klokt sitat", BotIntent.QUOTE, EvalFixture.EMPTY),
    ("Kan du vise meg sitatene?", BotIntent.QUOTE_LIST, EvalFixture.EMPTY),
    ("Husk å se Inception", BotIntent.WATCHLIST, EvalFixture.EMPTY),
    ("Hva skal vi se?", BotIntent.WATCHLIST, EvalFixture.EMPTY),
    ("Kan du legge til bursdagen min 15. mai?", BotIntent.BIRTHDAY_CREATE, EvalFixture.EMPTY),
    ("Kan du endre bursdagen min til 20. mai?", BotIntent.BIRTHDAY_EDIT, EvalFixture.EMPTY),
    ("Kven har bursdag snart?", BotIntent.BIRTHDAY_LIST, EvalFixture.EMPTY),
    # Deterministic tools and read topics.
    ("Hvis du har tid kan du vise prisen på BTC?", BotIntent.PRICE, EvalFixture.EMPTY),
    ("Kan du regne ut 2,5 + 1?", BotIntent.CALCULATOR, EvalFixture.EMPTY),
    ("Kan du regne ut (100 * 1,25) / 2?", BotIntent.CALCULATOR, EvalFixture.EMPTY),
    ("Kan du konvertere 10,5 km til meter?", BotIntent.CALCULATOR, EvalFixture.EMPTY),
    ("Kan du konvertere 25 °C til °F?", BotIntent.CALCULATOR, EvalFixture.EMPTY),
    (
        "Kan du fortelle meg hvor mange dager det er til jul?",
        BotIntent.COUNTDOWN,
        EvalFixture.EMPTY,
    ),
    (
        "Kan du fortelle meg hvor mange dager det er til 17. mai?",
        BotIntent.COUNTDOWN,
        EvalFixture.EMPTY,
    ),
    ("How many days until 2026-12-25?", BotIntent.COUNTDOWN, EvalFixture.EMPTY),
    ("Kan du vise meg horoskopet for Løven?", BotIntent.HOROSCOPE, EvalFixture.EMPTY),
    ("Kan du forkorte https://example.invalid?", BotIntent.SHORTEN_URL, EvalFixture.EMPTY),
    ("Kan du søke etter tog til Trondheim?", BotIntent.SEARCH, EvalFixture.EMPTY),
    ("Kan du vise meg nordlysvarselet?", BotIntent.AURORA, EvalFixture.EMPTY),
    ("Kan du gi meg dagens ord?", BotIntent.WORD_OF_DAY, EvalFixture.EMPTY),
    # Weather, location, holidays, profile, memory, and help.
    ("Hva er været?", BotIntent.DASHBOARD, EvalFixture.EMPTY),
    ("Kan du vise meg været?", BotIntent.DASHBOARD, EvalFixture.EMPTY),
    ("Kan du vise meg en oversikt?", BotIntent.DASHBOARD, EvalFixture.EMPTY),
    ("Jeg bor i Trondheim.", BotIntent.SET_LOCATION, EvalFixture.EMPTY),
    ("Kan du vise skoleferiene i Tromsø?", BotIntent.SCHOOL_HOLIDAYS, EvalFixture.EMPTY),
    ("Can you show school holidays in Tromsø?", BotIntent.SCHOOL_HOLIDAYS, EvalFixture.EMPTY),
    ("Kan du vise meg botstatus?", BotIntent.STATUS, EvalFixture.EMPTY),
    ("Kan du sette statusen til online?", BotIntent.PROFILE, EvalFixture.EMPTY),
    ("Kan du sette aktiviteten til å spille CS2?", BotIntent.PROFILE, EvalFixture.EMPTY),
    ("Kan du vise hva du husker om meg?", BotIntent.MEMORY_VIEW, EvalFixture.EMPTY),
    ("Kan du eksportere minnet mitt?", BotIntent.MEMORY_EXPORT, EvalFixture.EMPTY),
    ("Kan du slette minnet mitt?", BotIntent.MEMORY_DELETE, EvalFixture.EMPTY),
    ("kva kan du gjere?", BotIntent.HELP, EvalFixture.EMPTY),
    # Public examples that intentionally remain conversation.
    ("hei, hvordan går det?", BotIntent.AI_CHAT, EvalFixture.EMPTY),
    ("hva synes du om RBK i morgen?", BotIntent.AI_CHAT, EvalFixture.EMPTY),
    ("fortell en kort vits", BotIntent.AI_CHAT, EvalFixture.EMPTY),
)


@pytest.mark.parametrize(
    ("text", "expected_intent", "fixture"),
    DOCUMENTED_EXAMPLES,
    ids=lambda value: str(value)[:80],
)
def test_documented_example_routes_to_advertised_feature(
    text,
    expected_intent,
    fixture,
):
    result = build_production_router(fixture).route_help_example(text)

    assert result.intent is expected_intent


@pytest.mark.parametrize(
    ("text", "_expected_intent", "fixture"),
    tuple(
        row
        for row in DOCUMENTED_EXAMPLES
        if row[1] is not BotIntent.AI_CHAT
    ),
    ids=lambda value: str(value)[:80],
)
def test_valid_write_plus_every_executable_documented_example_requires_split(
    text,
    _expected_intent,
    fixture,
):
    result = build_production_router(fixture).route_help_example(
        f"create a meeting tomorrow and {text}"
    )

    assert result.intent is BotIntent.CLARIFY
    assert result.reason == "multiple_actions_require_split"
    assert "calendar_item" not in result.payload
