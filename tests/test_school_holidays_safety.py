"""Safety and data-coverage tests for the static school-holiday feature."""

from datetime import date
from types import SimpleNamespace

import pytest

from features.school_holidays import (
    format_holiday,
    format_holidays_list,
    get_fylke_from_exact_location,
    get_fylke_from_location,
    get_school_holidays,
)
from features.school_holidays_handler import SchoolHolidaysHandler


def _names(holidays):
    return [holiday["name"] for holiday in holidays]


@pytest.mark.parametrize(
    ("fylke", "own_week"),
    [
        ("oslo", "Vinterferie (Uke 8)"),
        ("rogaland", "Vinterferie (Uke 9)"),
        ("nordland", "Vinterferie (Uke 10)"),
    ],
)
def test_supplied_county_never_receives_other_regional_weeks(
    fylke,
    own_week,
):
    holidays = get_school_holidays(
        fylke,
        include_all=True,
        reference_date=date(2026, 2, 1),
    )

    names = _names(holidays)
    winter_holidays = [name for name in names if name.startswith("Vinterferie")]

    assert winter_holidays == [own_week]
    assert "Påskeferie" in names


def test_no_county_include_all_can_return_all_regional_weeks():
    holidays = get_school_holidays(
        include_all=True,
        reference_date=date(2026, 2, 1),
    )

    assert [
        name for name in _names(holidays) if name.startswith("Vinterferie")
    ] == [
        "Vinterferie (Uke 8)",
        "Vinterferie (Uke 9)",
        "Vinterferie (Uke 10)",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Når har skolene i Skien ferie?", "telemark"),
        ("What are the holidays in Ski?", "akershus"),
        ("Jeg bor i Møre og Romsdal", "møre_og_romsdal"),
        ("Skoleferie i Drammen", "buskerud"),
        ("Skoleferie i Fredrikstad", "østfold"),
        ("Skoleferie i Sandvika", "akershus"),
        ("Skoleferie i Tønsberg", "vestfold"),
        ("Skoleferie i Tromsø", "troms"),
        ("Skoleferie i Alta", "finnmark"),
        ("We are going skiing this winter", None),
        ("Skien og skiing", "telemark"),
    ],
)
def test_location_matching_is_bounded_and_longest_first(text, expected):
    assert get_fylke_from_location(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Oslo", "oslo"),
        ("i Tromsø", "troms"),
        ("in Møre og Romsdal", "møre_og_romsdal"),
        ("Oslo sounds great", None),
        ("Tromsø seem short", None),
    ],
)
def test_exact_location_matching_rejects_trailing_statement_text(
    text,
    expected,
):
    assert get_fylke_from_exact_location(text) == expected


@pytest.mark.parametrize("lang", ["no", "en"])
def test_stale_dataset_returns_honest_coverage_message(lang):
    response = format_holidays_list(
        "oslo",
        days=90,
        lang=lang,
        reference_date=date(2026, 7, 16),
    )

    assert "06.04.2026" in response
    assert "Ingen ferier planlagt" not in response
    assert "No holidays planned" not in response
    if lang == "no":
        assert "kan ikke bekrefte skoleferier" in response
    else:
        assert "cannot confirm school holidays" in response


def test_empty_covered_window_does_not_claim_there_are_no_holidays():
    response = format_holidays_list(
        "oslo",
        days=7,
        lang="no",
        reference_date=date(2025, 8, 1),
    )

    assert "ingen verifiserte feriedatoer" in response
    assert "Ingen ferier planlagt" not in response


def test_holiday_formatting_uses_injected_reference_date():
    holiday = get_school_holidays(
        "oslo",
        reference_date=date(2026, 2, 1),
    )[0]

    assert format_holiday(
        holiday,
        lang="no",
        reference_date=date(2026, 2, 16),
    ).endswith("Starter i morgen!")


@pytest.mark.asyncio
async def test_handler_uses_natural_location_tip(monkeypatch):
    monitor = SimpleNamespace(
        rate_limiter=object(),
        loc=SimpleNamespace(current_lang="no"),
        client=object(),
    )
    handler = SchoolHolidaysHandler(monitor)
    sent = []

    async def capture_response(message, content):
        del message
        sent.append(content)

    monkeypatch.setattr(handler, "send_response", capture_response)
    message = SimpleNamespace(content="Når er det skoleferie?")

    await handler.handle_school_holidays(message)

    assert sent
    assert "Fortell gjerne hvilken by eller hvilket fylke" in sent[0]
    assert '"skoleferie' not in sent[0]
