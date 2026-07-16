import pytest

from features.calculator_manager import CalculatorManager
from features.compliments_manager import ComplimentsManager
from features.countdown_manager import CountdownManager
from features.crypto_manager import CryptoManager
from features.horoscope_manager import HoroscopeManager


@pytest.mark.parametrize(
    ("text", "asset", "coin_id"),
    [
        ("bitcoin pris", "bitcoin", "bitcoin"),
        ("pris BTC", "BTC", "bitcoin"),
        ("pris BTC, om du kan", "BTC", "bitcoin"),
        ("kan du vise prisen på BTC hvis du har tid", "BTC", "bitcoin"),
        ("please, if you can, show me the Bitcoin price", "Bitcoin", "bitcoin"),
        ("kan du, hvis du har tid, vise meg prisen på BTC", "BTC", "bitcoin"),
        ("kan du hvis du har tid vise prisen på BTC", "BTC", "bitcoin"),
        ("hvis du har tid, kan du vise prisen på BTC", "BTC", "bitcoin"),
        ("kan du vise meg prisen på Bitcoin?", "Bitcoin", "bitcoin"),
        ("kan du syne meg prisen på Shiba Inu, takk", "Shiba Inu", "shiba-inu"),
        ("Could you show me the crypto price of NewCoin?", "NewCoin", "newcoin"),
        ("WIF token price", "WIF", "wif"),
        ("could you show the Bitcoin price?", "Bitcoin", "bitcoin"),
        ("what is the BTC price?", "BTC", "bitcoin"),
        ("what is the price of The Graph?", "The Graph", "the-graph"),
        ("what's the BTC price?", "BTC", "bitcoin"),
        ("what’s the BTC price?", "BTC", "bitcoin"),
        ("hva koster en bitcoin?", "bitcoin", "bitcoin"),
        ("how much is a bitcoin?", "bitcoin", "bitcoin"),
        ("what is the price of a Bitcoin?", "Bitcoin", "bitcoin"),
        ("price of the Bitcoin", "Bitcoin", "bitcoin"),
        ("what is Bitcoin worth?", "Bitcoin", "bitcoin"),
        ("what's Bitcoin worth?", "Bitcoin", "bitcoin"),
        ("hva er bitcoin verdt?", "bitcoin", "bitcoin"),
        ("kan du sjekke prisen på bitcoin?", "bitcoin", "bitcoin"),
    ],
)
def test_price_parser_accepts_bounded_natural_requests_and_preserves_asset_case(
    text, asset, coin_id
):
    parsed = CryptoManager().parse_price_query(text)

    assert parsed is not None
    assert parsed["asset"] == asset
    assert parsed["coin_id"] == coin_id


@pytest.mark.parametrize(
    "text",
    [
        "show the price",
        "vise pris",
        "the price",
        "price of freedom",
        "price of a flight",
        "price of prediction",
        "price prediction for bitcoin",
        "house price",
        "price of gold",
        "train-ticket price",
        "what is the price of a house?",
        "what is a house worth?",
        "kan du ikke vise prisen på bitcoin?",
        "jeg sa at du skulle vise prisen på bitcoin",
        "hvis jeg spør om prisen på bitcoin",
        "what happens if you show me the Bitcoin price?",
        "what does 'price of bitcoin' mean?",
    ],
)
def test_price_parser_rejects_empty_generic_negated_reported_and_meta_neighbors(text):
    assert CryptoManager().parse_price_query(text) is None


@pytest.mark.parametrize(
    ("text", "expression"),
    [
        ("regn ut 2+2", "2+2"),
        ("kan du regne ut 2 + 2?", "2 + 2"),
        ("kan du rekne ut 7 X 6?", "7 X 6"),
        ("Could you calculate (5 + 3) * 2, please?", "(5 + 3) * 2"),
        ("what is 9 / 3?", "9 / 3"),
        ("kan du hvis du har tid regne ut 2+2", "2+2"),
        ("calculate 100/5/2", "100/5/2"),
        ("compute 144/12/2", "144/12/2"),
        ("calculate 10-2-3", "10-2-3"),
        ("regn ut 2,5 + 1", "2,5 + 1"),
        ("hva er 2,5 + 1?", "2,5 + 1"),
        ("what's 2+2?", "2+2"),
        ("what’s 2+2?", "2+2"),
        ("if you have time, could you calculate 2+2", "2+2"),
    ],
)
def test_calculator_parser_accepts_natural_math_and_strips_question_wrapper(
    text, expression
):
    assert CalculatorManager().parse_command(text) == {
        "type": "math",
        "expression": expression,
    }


def test_calculator_parser_accepts_polite_conversion():
    parsed = CalculatorManager().parse_command(
        "kan du konvertere 100 USD til NOK, takk?"
    )

    assert parsed == {
        "type": "currency",
        "amount": 100.0,
        "from": "usd",
        "to": "nok",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "konverter 10 km til meter",
            {"type": "length", "value": 10.0, "from": "km", "to": "meter"},
        ),
        (
            "convert 5 kg to pounds",
            {"type": "weight", "value": 5.0, "from": "kg", "to": "pounds"},
        ),
        (
            "25C til F",
            {"type": "temperature", "value": 25.0, "from": "c", "to": "f"},
        ),
        (
            "konverter 10,5 km til meter",
            {"type": "length", "value": 10.5, "from": "km", "to": "meter"},
        ),
        (
            "10 km i meter",
            {"type": "length", "value": 10.0, "from": "km", "to": "meter"},
        ),
        (
            "10 km in meters",
            {"type": "length", "value": 10.0, "from": "km", "to": "meters"},
        ),
        (
            "25 °C til °F",
            {"type": "temperature", "value": 25.0, "from": "c", "to": "f"},
        ),
        (
            "25°C til °F",
            {"type": "temperature", "value": 25.0, "from": "c", "to": "f"},
        ),
    ],
)
def test_calculator_parser_types_physical_conversions_before_currency(text, expected):
    assert CalculatorManager().parse_command(text) == expected


def test_calculator_parser_preserves_bounded_kalk_alias_and_courtesy_suffix():
    manager = CalculatorManager()

    assert manager.parse_command("kalk (100 * 1.25) / 2") == {
        "type": "math",
        "expression": "(100 * 1.25) / 2",
    }
    assert manager.parse_command("calculate 2+2, if you can") == {
        "type": "math",
        "expression": "2+2",
    }
    assert manager.parse_command("calculate 2+2 if you can") == {
        "type": "math",
        "expression": "2+2",
    }
    assert manager.parse_command(
        "kan du, hvis du har tid, regne ut 2+2"
    ) == {
        "type": "math",
        "expression": "2+2",
    }


@pytest.mark.parametrize("unit", ["USD", "BTC"])
def test_calculator_same_currency_conversion_is_identity(unit):
    manager = CalculatorManager()
    parsed = manager.parse_command(f"100 {unit} til {unit}")

    result = manager.calculate(parsed)

    assert "Ukjent valutakonvertering" not in result
    assert "100.00" in result


@pytest.mark.parametrize(
    "text",
    [
        "calculate happiness",
        "calculate cost of freedom",
        "convert 5 cats to dogs",
        "convert 10 km to cats",
        "what is 42?",
        "hva er 17.07.2026?",
        "what is 07/16/2026?",
        "what is 2026-07-17?",
        "what is 2026-07-17 + 1?",
        "hva er 17.07.2026 + 1?",
        "what is 2026/07/17 + 1?",
        "calculate 2026-07-17 + 1",
        "kan du ikke regne ut 2+2?",
        "jeg sa regn ut 2+2",
        "if I asked you to calculate 2+2",
        "what happens if you calculate 2+2?",
        "what does 'calculate 2+2' mean?",
    ],
)
def test_calculator_parser_rejects_non_math_negated_reported_and_meta_neighbors(text):
    assert CalculatorManager().parse_command(text) is None


@pytest.mark.parametrize(
    ("text", "sign", "sign_key"),
    [
        ("horoskop væren", "Aries", "væren"),
        ("kan du vise meg horoskopet for Løven?", "Leo", "Løven"),
        ("kan du syne meg horoskopet for løva?", "Leo", "løva"),
        ("horoskop kreften", "Cancer", "kreften"),
        ("horoskop Løven, om du kan", "Leo", "Løven"),
        ("kan du hvis du har tid vise horoskopet for Løven", "Leo", "Løven"),
        ("What is my horoscope for Aquarius?", "Aquarius", "Aquarius"),
        ("what's my horoscope for Leo?", "Leo", "Leo"),
        ("what’s my horoscope for Leo?", "Leo", "Leo"),
        ("hvis du har tid, kan du vise horoskopet for Løven", "Leo", "Løven"),
        ("give me the horoscope for Leo", "Leo", "Leo"),
        ("could you check the horoscope for Leo?", "Leo", "Leo"),
    ],
)
def test_horoscope_parser_accepts_bounded_natural_requests(text, sign, sign_key):
    assert HoroscopeManager().parse_horoscope_command(text) == {
        "sign": sign,
        "sign_key": sign_key,
    }


@pytest.mark.parametrize(
    "text",
    [
        "kan du ikke vise horoskopet for løven?",
        "jeg sa horoskop løven",
        "I wrote horoscope Leo",
        "if I ask for horoscope Leo",
        "what does horoscope Leo mean?",
        "Leo is mentioned in a horoscope article",
    ],
)
def test_horoscope_parser_rejects_negated_reported_hypothetical_and_meta_neighbors(
    text,
):
    assert HoroscopeManager().parse_horoscope_command(text) is None


def test_horoscope_generation_does_not_mutate_global_random_state():
    import random

    state = random.getstate()
    HoroscopeManager().get_horoscope("Cancer")

    assert random.getstate() == state


@pytest.mark.parametrize(
    ("text", "event"),
    [
        ("hvor lenge til jul", "jul"),
        ("kan du fortelle meg hvor lenge det er til Jul?", "Jul"),
        ("kor mange dagar er det til påske?", "påske"),
        ("Could you tell me how long until Christmas?", "Christmas"),
        ("hvor lenge til Jul, om du kan", "Jul"),
        ("kan du hvis du har tid si hvor lenge det er til Jul", "Jul"),
        ("when is the New Year?", "New Year"),
        ("when's Christmas?", "Christmas"),
        ("when’s Christmas?", "Christmas"),
        ("kan du fortelle meg hvor mange dager det er til jul?", "jul"),
        ("Could you tell me how many days there are until Christmas?", "Christmas"),
        ("when is New Year's Eve?", "New Year's Eve"),
        ("when is Mother’s Day?", "Mother’s Day"),
        ("when is Father's Day?", "Father's Day"),
        ("when is Valentine's Day?", "Valentine's Day"),
        ("when is All Saints' Day?", "All Saints' Day"),
        ("if you have time, could you tell me how long until Christmas?", "Christmas"),
        ("hvor mange dager igjen til jul?", "jul"),
        ("how many days are left until Christmas?", "Christmas"),
        ("can you count down to Christmas?", "Christmas"),
        ("tell me the days until Christmas", "Christmas"),
    ],
)
def test_countdown_parser_accepts_natural_requests_and_preserves_event_case(text, event):
    parsed = CountdownManager().parse_countdown_query(text)

    assert parsed is not None
    assert parsed["event"] == event


@pytest.mark.parametrize(
    "text",
    [
        "play countdown music",
        "this countdown music is catchy",
        "the song Countdown to Christmas",
        "countdown to Christmas music",
        "kan du ikke si hvor lenge det er til jul?",
        "jeg skrev nedtelling til jul",
        "if I ask for a countdown to Christmas",
        "what does countdown mean?",
    ],
)
def test_countdown_parser_rejects_media_negated_reported_hypothetical_and_meta_neighbors(
    text,
):
    assert CountdownManager().parse_countdown_query(text) is None


@pytest.mark.parametrize(
    ("text", "action", "user"),
    [
        ("kompliment @ola", "compliment", "ola"),
        ("kan du gi @Ola et kompliment?", "compliment", "Ola"),
        ("kan du gje @Åse eit kompliment?", "compliment", "Åse"),
        ("Could you give @Jane a compliment?", "compliment", "Jane"),
        ("please roast @Casey", "roast", "Casey"),
        ("roast @Casey, if you can", "roast", "Casey"),
        ("kan du hvis du har tid gi @Ola et kompliment", "compliment", "Ola"),
        ("hvis du har tid, kan du gi @Ola et kompliment", "compliment", "Ola"),
        ("roast <@!12345>", "roast", "<@12345>"),
    ],
)
def test_compliment_parser_accepts_bounded_requests_and_preserves_target_case(
    text, action, user
):
    assert ComplimentsManager().parse_compliment_command(text) == {
        "action": action,
        "user": user,
    }


@pytest.mark.parametrize(
    "text",
    [
        "roast chicken",
        "this roast looks delicious",
        "how do I roast chicken?",
        "play a diss track",
        "kan du ikke roaste @Ola?",
        "jeg sa roast @Ola",
        "if I asked you to roast @Ola",
        "what does roast mean?",
    ],
)
def test_compliment_parser_rejects_food_negated_reported_hypothetical_and_meta_neighbors(
    text,
):
    assert ComplimentsManager().parse_compliment_command(text) is None
