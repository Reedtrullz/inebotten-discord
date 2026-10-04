from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from features import calculator_manager
from features.utility_handler import UtilityHandler


CalculatorManager = calculator_manager.CalculatorManager


def rate_snapshot(**values):
    return calculator_manager.RateSnapshot(**values)


def convert_currency(*args):
    return calculator_manager.convert_currency(*args)


def test_fixed_rates_are_labeled_estimates():
    manager = CalculatorManager()

    response = manager.calculate(manager.parse_command("100 USD til NOK"))

    assert "estimat" in response.lower()
    assert "ukjent" in response.lower()
    assert "demonstrasjon" in response.lower()


def test_inverse_and_cross_pair_use_one_snapshot():
    snapshot = rate_snapshot(
        source="fixture",
        effective_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        base="USD",
        rates={
            "USD": Decimal("1"),
            "NOK": Decimal("10"),
            "EUR": Decimal("0.8"),
            "BTC": Decimal("0.00001"),
        },
        status="fresh",
    )

    nok_to_usd = convert_currency(Decimal("10"), "NOK", "USD", snapshot)
    nok_to_eur = convert_currency(Decimal("10"), "NOK", "EUR", snapshot)
    usd_to_nok = convert_currency(Decimal("1"), "USD", "NOK", snapshot)

    assert nok_to_usd == Decimal("1")
    assert nok_to_eur == Decimal("0.8")
    assert nok_to_usd * usd_to_nok == Decimal("10")


def test_unknown_pair_refuses():
    manager = CalculatorManager()
    command = {"type": "currency", "amount": Decimal("2"), "from": "xyz", "to": "abc"}

    response = manager.calculate(command)

    assert "ukjent" in response.lower()
    with pytest.raises(ValueError, match="Unsupported currency"):
        convert_currency(Decimal("2"), "XYZ", "ABC", manager.rate_snapshot)


@pytest.mark.parametrize(
    ("amount", "source", "target", "expected"),
    [
        ("1.005", "USD", "NOK", "10.90"),
        ("0.001", "USD", "BTC", "0.00000001"),
        ("0.000000019", "BTC", "USD", "0.00"),
    ],
)
def test_fiat_and_btc_rounding_is_explicit(amount, source, target, expected):
    manager = CalculatorManager()
    result = manager.calculate(
        {"type": "currency", "amount": Decimal(amount), "from": source, "to": target}
    )

    assert expected in result


def test_current_quote_request_refuses_demonstration_snapshot():
    manager = CalculatorManager()
    command = manager.parse_command("100 USD til NOK nå")

    response = manager.calculate(command)

    assert "fersk" in response.lower()
    assert "estimat" not in response.lower()


def test_current_quote_request_accepts_fresh_snapshot_and_discloses_time():
    manager = CalculatorManager()
    manager.rate_snapshot = rate_snapshot(
        source="test feed",
        effective_at=datetime(2026, 10, 4, 12, 30, tzinfo=timezone.utc),
        base="USD",
        rates={"USD": Decimal("1"), "NOK": Decimal("10")},
        status="fresh",
    )
    command = manager.parse_command("100 USD til NOK now")

    response = manager.calculate(command, lang="en")

    assert "test feed" in response
    assert "2026-10-04 12:30:00 UTC" in response
    assert "estimate" not in response.lower()


def test_stale_snapshot_is_labeled_and_cannot_answer_current_request():
    manager = CalculatorManager()
    manager.rate_snapshot = rate_snapshot(
        source="cached feed",
        effective_at=datetime(2026, 10, 3, 12, tzinfo=timezone.utc),
        base="USD",
        rates={"USD": Decimal("1"), "NOK": Decimal("10")},
        status="stale",
    )

    estimate = manager.calculate(manager.parse_command("100 USD til NOK"), lang="en")
    current = manager.calculate(manager.parse_command("100 USD til NOK currently"), lang="en")

    assert "stale" in estimate.lower()
    assert "2026-10-03" in estimate
    assert "no fresh" in current.lower()


def test_fresh_snapshot_requires_aware_effective_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        rate_snapshot(
            source="fixture",
            effective_at=datetime(2026, 10, 4),
            base="USD",
            rates={"USD": Decimal("1"), "NOK": Decimal("10")},
            status="fresh",
        )


@pytest.mark.asyncio
async def test_utility_handler_delivers_current_quote_refusal():
    manager = CalculatorManager()
    handler = UtilityHandler.__new__(UtilityHandler)
    handler.calculator = manager
    handler._localization = SimpleNamespace(current_lang="no")
    sent = []

    async def send_response(_message, response):
        sent.append(response)

    handler.send_response = send_response
    handler.log = lambda _message: None

    await handler.handle_calculator(
        object(), manager.parse_command("100 USD til NOK nåværende")
    )

    assert len(sent) == 1
    assert "Ingen fersk valutakurs" in sent[0]
