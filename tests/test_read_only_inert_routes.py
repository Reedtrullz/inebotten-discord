"""Read-only feature parsers never execute quoted, reported, or negated text."""

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    ("text", "forbidden"),
    (
        ("I said shorten https://example.com", BotIntent.SHORTEN_URL),
        ("do not shorten https://example.com", BotIntent.SHORTEN_URL),
        (
            "could you not shorten https://never.example/path",
            BotIntent.SHORTEN_URL,
        ),
        (
            "if you have time could you not shorten https://never.example/path",
            BotIntent.SHORTEN_URL,
        ),
        ("shorten is an English verb https://example.com", BotIntent.SHORTEN_URL),
        ("eksempel: forkort https://example.com", BotIntent.SHORTEN_URL),
        ("I said calculate 2+2", BotIntent.CALCULATOR),
        ("do not calculate 2+2", BotIntent.CALCULATOR),
        ("I said compute 42", BotIntent.CALCULATOR),
        ("do not compute 42", BotIntent.CALCULATOR),
        ("if I ask you to compute 42", BotIntent.CALCULATOR),
        ("if you have time calculate 2+2", BotIntent.CALCULATOR),
        ("I said how many days to Christmas", BotIntent.COUNTDOWN),
        ("do not start countdown to Christmas", BotIntent.COUNTDOWN),
        ("if I ask for a countdown to Christmas", BotIntent.COUNTDOWN),
        ("I read a horoscope about Leo", BotIntent.HOROSCOPE),
        ("do not show horoscope Leo", BotIntent.HOROSCOPE),
        ("I said search the web for cats", BotIntent.SEARCH),
        ("do not search the web for cats", BotIntent.SEARCH),
        ("could you not search for cats", BotIntent.SEARCH),
        (
            "could you if you have time not search for never gonna give you up",
            BotIntent.SEARCH,
        ),
        ("kan du ikke søke etter katter", BotIntent.SEARCH),
        ("Ola said price BTC", BotIntent.PRICE),
        ("do not show price BTC", BotIntent.PRICE),
        (
            "if you have time shorten https://example.com/a",
            BotIntent.SHORTEN_URL,
        ),
        ("Ola said how much is Solana", BotIntent.PRICE),
        ("how much is a house?", BotIntent.PRICE),
        ("Ola la Inception på watchlist", BotIntent.WATCHLIST),
        ("Ola asked how many reminders do I have?", BotIntent.REMINDER_LIST),
        ("do not show me my watchlist", BotIntent.WATCHLIST),
        ("Ola said what polls are active?", BotIntent.POLL_LIST),
        ("do not give me a random quote", BotIntent.QUOTE),
        ("what does show me your commands mean?", BotIntent.HELP),
        (
            "Ola said make this URL shorter: https://example.com/a",
            BotIntent.SHORTEN_URL,
        ),
    ),
)
def test_inert_utility_and_watchlist_mentions_never_route(text, forbidden):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is not forbidden


@pytest.mark.parametrize(
    "text",
    ("vær forsiktig", "vær stille", "vær så snill"),
)
def test_norwegian_imperative_homonyms_are_not_weather(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is not BotIntent.DASHBOARD


@pytest.mark.parametrize(
    "text",
    (
        "kan du, hvis du har tid, forkorte https://example.com/a/b",
        "please, if you can, shorten https://example.com/a/b",
    ),
)
def test_polite_conditional_url_requests_remain_executable(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SHORTEN_URL
    assert result.payload == {"shorten": {"url": "https://example.com/a/b"}}


@pytest.mark.parametrize(
    "text",
    (
        "kan du forkorte https://example.com/a/b hvis du har tid",
        "if you have time, could you shorten https://example.com/a/b",
        "could you shorten https://example.com/a/b if you have time",
        "kan du forkorte https://example.com/a/b, takk",
        "could you shorten https://example.com/a/b, please",
    ),
)
def test_leading_trailing_courtesy_url_requests_keep_one_exact_payload(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.SHORTEN_URL
    assert result.payload == {"shorten": {"url": "https://example.com/a/b"}}


@pytest.mark.parametrize(
    ("text", "intent", "payload"),
    (
        (
            "shorten https://never.example/path",
            BotIntent.SHORTEN_URL,
            {"shorten": {"url": "https://never.example/path"}},
        ),
        (
            "forkort https://example.com/not/a",
            BotIntent.SHORTEN_URL,
            {"shorten": {"url": "https://example.com/not/a"}},
        ),
        (
            "search for never gonna give you up",
            BotIntent.SEARCH,
            {"search": {"query": "never gonna give you up", "type": "web"}},
        ),
        (
            "søk etter ikke stopp meg nå",
            BotIntent.SEARCH,
            {"search": {"query": "ikke stopp meg nå", "type": "web"}},
        ),
        (
            "if you have time could you shorten https://never.example/path",
            BotIntent.SHORTEN_URL,
            {"shorten": {"url": "https://never.example/path"}},
        ),
        (
            "could you if you have time shorten https://never.example/path",
            BotIntent.SHORTEN_URL,
            {"shorten": {"url": "https://never.example/path"}},
        ),
        (
            "if you have time could you search for never gonna give you up",
            BotIntent.SEARCH,
            {"search": {"query": "never gonna give you up", "type": "web"}},
        ),
        (
            "could you if you have time search for never gonna give you up",
            BotIntent.SEARCH,
            {"search": {"query": "never gonna give you up", "type": "web"}},
        ),
    ),
)
def test_negation_words_inside_bounded_read_payloads_remain_data(
    text,
    intent,
    payload,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent
    assert result.payload == payload


@pytest.mark.parametrize(
    "text",
    (
        "hva skjer hvis du forkorter https://example.com/a",
        "what happens if you shorten https://example.com/a",
        "hvis du forkorter https://example.com/a blir den kortere",
        "if you search for cats, you may find them",
    ),
)
def test_true_utility_conditionals_remain_inert(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent not in {BotIntent.SHORTEN_URL, BotIntent.SEARCH}


@pytest.mark.parametrize(
    ("text", "asset"),
    (
        ("kan du vise prisen på BTC hvis du har tid", "BTC"),
        ("could you show me the price of BTC if you have time", "BTC"),
    ),
)
def test_trailing_courtesy_price_requests_do_not_pollute_the_asset(text, asset):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.PRICE
    assert result.payload["price"]["asset"] == asset
