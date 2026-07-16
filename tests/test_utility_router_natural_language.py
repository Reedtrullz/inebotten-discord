"""Production utility gates stay aligned with their bounded parsers."""

from __future__ import annotations

import pytest

from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    ("text", "intent"),
    (
        ("pris BTC", BotIntent.PRICE),
        ("kan du syne meg prisen på Shiba Inu, takk", BotIntent.PRICE),
        ("kan du rekne ut 7 X 6?", BotIntent.CALCULATOR),
        ("kan du konvertere 100 USD til NOK, takk?", BotIntent.CALCULATOR),
        ("kan du vise meg horoskopet for Løven?", BotIntent.HOROSCOPE),
        ("kan du syne meg horoskopet for løva?", BotIntent.HOROSCOPE),
        ("kor mange dagar er det til påske?", BotIntent.COUNTDOWN),
        ("Could you tell me how long until Christmas?", BotIntent.COUNTDOWN),
        ("when is the New Year?", BotIntent.COUNTDOWN),
        ("hvor mange dager er det til jul?", BotIntent.COUNTDOWN),
        ("når er jul?", BotIntent.COUNTDOWN),
        ("nedteljing til jul", BotIntent.COUNTDOWN),
        ("how many days are there until Christmas?", BotIntent.COUNTDOWN),
        ("how many days to Christmas?", BotIntent.COUNTDOWN),
        ("days to Christmas", BotIntent.COUNTDOWN),
        ("how long to Christmas?", BotIntent.COUNTDOWN),
        (
            "kan du fortelle meg hvor mange dager det er til jul?",
            BotIntent.COUNTDOWN,
        ),
        (
            "Could you tell me how many days there are until Christmas?",
            BotIntent.COUNTDOWN,
        ),
        ("when's Christmas?", BotIntent.COUNTDOWN),
        ("when’s Christmas?", BotIntent.COUNTDOWN),
        ("omgjør 10 km til meter", BotIntent.CALCULATOR),
        ("gjør om 10 km til meter", BotIntent.CALCULATOR),
        ("gjer om 10 km til meter", BotIntent.CALCULATOR),
        ("compute 42", BotIntent.CALCULATOR),
        ("work out 42", BotIntent.CALCULATOR),
        ("how much is Solana?", BotIntent.PRICE),
        ("how much does Solana cost?", BotIntent.PRICE),
        ("how much is Dogecoin?", BotIntent.PRICE),
        ("what's the BTC price?", BotIntent.PRICE),
        ("what’s the BTC price?", BotIntent.PRICE),
        ("what's my horoscope for Leo?", BotIntent.HOROSCOPE),
        ("what’s my horoscope for Leo?", BotIntent.HOROSCOPE),
        ("what's 2+2?", BotIntent.CALCULATOR),
        ("what’s 2+2?", BotIntent.CALCULATOR),
        ("10 km i meter", BotIntent.CALCULATOR),
        ("10 km in meter", BotIntent.CALCULATOR),
        ("regn ut 2,5 + 1", BotIntent.CALCULATOR),
        ("hva koster en bitcoin?", BotIntent.PRICE),
        ("how much is a bitcoin?", BotIntent.PRICE),
        ("what is the price of a Bitcoin?", BotIntent.PRICE),
        ("price of the Bitcoin", BotIntent.PRICE),
        ("price of The Graph", BotIntent.PRICE),
        ("what is Bitcoin worth?", BotIntent.PRICE),
        ("what's Bitcoin worth?", BotIntent.PRICE),
        ("hva er bitcoin verdt?", BotIntent.PRICE),
        ("kan du sjekke prisen på bitcoin?", BotIntent.PRICE),
        ("give me the horoscope for Leo", BotIntent.HOROSCOPE),
        ("could you check the horoscope for Leo?", BotIntent.HOROSCOPE),
        ("hvor mange dager igjen til jul?", BotIntent.COUNTDOWN),
        ("how many days are left until Christmas?", BotIntent.COUNTDOWN),
        ("can you count down to Christmas?", BotIntent.COUNTDOWN),
        ("tell me the days until Christmas", BotIntent.COUNTDOWN),
        ("when is New Year's Eve?", BotIntent.COUNTDOWN),
        ("when is Mother’s Day?", BotIntent.COUNTDOWN),
        ("when is Father's Day?", BotIntent.COUNTDOWN),
        ("when is Valentine's Day?", BotIntent.COUNTDOWN),
        ("when is All Saints' Day?", BotIntent.COUNTDOWN),
        ("days until 2026-12-25", BotIntent.COUNTDOWN),
        (
            "kan du forkorte https://example.com/long/path, takk",
            BotIntent.SHORTEN_URL,
        ),
    ),
)
def test_manager_positive_natural_requests_survive_production_gates(text, intent):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent


def test_compact_price_help_alias_preserves_asset_case_end_to_end():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "pris BTC"
    )

    assert result.payload == {
        "price": {
            "type": "crypto",
            "asset": "BTC",
            "coin_id": "bitcoin",
            "display_name": "BTC",
        }
    }


@pytest.mark.parametrize(
    ("text", "asset", "coin_id"),
    (
        ("hva koster en bitcoin?", "bitcoin", "bitcoin"),
        ("how much is a bitcoin?", "bitcoin", "bitcoin"),
        ("what is the price of a Bitcoin?", "Bitcoin", "bitcoin"),
        ("price of the Bitcoin", "Bitcoin", "bitcoin"),
        ("price of The Graph", "The Graph", "the-graph"),
    ),
)
def test_price_articles_are_normalized_without_losing_asset_names(
    text,
    asset,
    coin_id,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is BotIntent.PRICE
    assert result.payload["price"]["asset"] == asset
    assert result.payload["price"]["coin_id"] == coin_id


def test_countdown_uses_the_router_turn_clock_not_the_machine_clock():
    result = build_production_router(EvalFixture.EMPTY).route_help_example(
        "Could you tell me how long until Christmas?"
    )

    assert result.intent is BotIntent.COUNTDOWN
    assert result.payload["countdown"]["event"] == "Christmas"
    assert result.payload["countdown"]["days"] == 164
    assert result.payload["countdown"]["is_past"] is False


@pytest.mark.parametrize(
    ("text", "intent", "payload_key", "payload_value"),
    (
        ("pris BTC, om du kan", BotIntent.PRICE, "asset", "BTC"),
        ("price of BTC, if you can", BotIntent.PRICE, "asset", "BTC"),
        ("roast @Ola, if you can", BotIntent.COMPLIMENT, "user", "Ola"),
        ("compute 42, if you can", BotIntent.CALCULATOR, "expression", "42"),
        (
            "hvor lenge til Jul, om du kan",
            BotIntent.COUNTDOWN,
            "event",
            "Jul",
        ),
    ),
)
def test_bounded_trailing_courtesy_stays_out_of_utility_payloads(
    text,
    intent,
    payload_key,
    payload_value,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent
    envelope = {
        BotIntent.PRICE: "price",
        BotIntent.COMPLIMENT: "compliment",
        BotIntent.CALCULATOR: "calculator",
        BotIntent.COUNTDOWN: "countdown",
    }[intent]
    assert result.payload[envelope][payload_key] == payload_value


@pytest.mark.parametrize(
    ("text", "intent", "envelope", "payload_key", "payload_value"),
    (
        (
            "kan du hvis du har tid vise prisen på BTC",
            BotIntent.PRICE,
            "price",
            "asset",
            "BTC",
        ),
        (
            "kan du hvis du har tid regne ut 2+2",
            BotIntent.CALCULATOR,
            "calculator",
            "expression",
            "2+2",
        ),
        (
            "kan du hvis du har tid vise horoskopet for løven",
            BotIntent.HOROSCOPE,
            "horoscope",
            "sign",
            "Leo",
        ),
        (
            "kan du hvis du har tid si hvor lenge det er til jul",
            BotIntent.COUNTDOWN,
            "countdown",
            "event",
            "jul",
        ),
        (
            "kan du hvis du har tid gi @Ola et kompliment",
            BotIntent.COMPLIMENT,
            "compliment",
            "user",
            "Ola",
        ),
        (
            "kan du hvis du har tid forkorte https://example.com/a",
            BotIntent.SHORTEN_URL,
            "shorten",
            "url",
            "https://example.com/a",
        ),
        (
            "could you if you have time show me the price of BTC",
            BotIntent.PRICE,
            "price",
            "asset",
            "BTC",
        ),
        (
            "could you if you have time calculate 2+2",
            BotIntent.CALCULATOR,
            "calculator",
            "expression",
            "2+2",
        ),
        (
            "could you if you can show me horoscope for Leo",
            BotIntent.HOROSCOPE,
            "horoscope",
            "sign",
            "Leo",
        ),
        (
            "could you if you have time tell me how long until Christmas",
            BotIntent.COUNTDOWN,
            "countdown",
            "event",
            "Christmas",
        ),
        (
            "could you if you can give @Ola a compliment",
            BotIntent.COMPLIMENT,
            "compliment",
            "user",
            "Ola",
        ),
        (
            "could you if you have time shorten https://example.com/a",
            BotIntent.SHORTEN_URL,
            "shorten",
            "url",
            "https://example.com/a",
        ),
        (
            "if you have time, could you show me the price of BTC",
            BotIntent.PRICE,
            "price",
            "asset",
            "BTC",
        ),
        (
            "if you have time, could you calculate 2+2",
            BotIntent.CALCULATOR,
            "calculator",
            "expression",
            "2+2",
        ),
        (
            "if you have time, could you show me my horoscope for Leo",
            BotIntent.HOROSCOPE,
            "horoscope",
            "sign",
            "Leo",
        ),
        (
            "if you have time, could you tell me how long until Christmas",
            BotIntent.COUNTDOWN,
            "countdown",
            "event",
            "Christmas",
        ),
        (
            "if you have time, could you give @Ola a compliment",
            BotIntent.COMPLIMENT,
            "compliment",
            "user",
            "Ola",
        ),
        (
            "if you have time could you show me the price of BTC",
            BotIntent.PRICE,
            "price",
            "asset",
            "BTC",
        ),
        (
            "if you have time could you calculate 2+2",
            BotIntent.CALCULATOR,
            "calculator",
            "expression",
            "2+2",
        ),
        (
            "if you have time could you show me my horoscope for Leo",
            BotIntent.HOROSCOPE,
            "horoscope",
            "sign",
            "Leo",
        ),
        (
            "if you have time could you tell me how long until Christmas",
            BotIntent.COUNTDOWN,
            "countdown",
            "event",
            "Christmas",
        ),
        (
            "if you have time could you give @Ola a compliment",
            BotIntent.COMPLIMENT,
            "compliment",
            "user",
            "Ola",
        ),
        (
            "if you have time could you shorten https://example.com/a",
            BotIntent.SHORTEN_URL,
            "shorten",
            "url",
            "https://example.com/a",
        ),
    ),
)
def test_no_comma_courtesy_requests_route_end_to_end(
    text,
    intent,
    envelope,
    payload_key,
    payload_value,
):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent is intent
    assert result.payload[envelope][payload_key] == payload_value


@pytest.mark.parametrize(
    "text",
    (
        "kan du forklare hvordan man viser horoskopet for løven?",
        "Ola sa kan du vise horoskopet for løven",
        "ikke vis horoskopet for løven",
        "price of freedom",
        "price of a flight",
        "what is a house worth?",
        "10 cats in dogs",
    ),
)
def test_expanded_utility_gates_keep_inert_neighbors_out(text):
    result = build_production_router(EvalFixture.EMPTY).route_help_example(text)

    assert result.intent not in {
        BotIntent.PRICE,
        BotIntent.HOROSCOPE,
        BotIntent.CALCULATOR,
    }
