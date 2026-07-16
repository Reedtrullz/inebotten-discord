from datetime import datetime
from zoneinfo import ZoneInfo

from features.countdown_manager import CountdownManager


OSLO = ZoneInfo("Europe/Oslo")


def fixed_reference(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=OSLO)


def test_date_only_tomorrow_uses_calendar_days_not_midnight_duration():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16, 23, 59)
    )

    parsed = manager.parse_countdown_query("dager til 17.07")

    assert parsed is not None
    assert parsed["days"] == 1
    assert parsed["hours"] == 0
    assert parsed["minutes"] == 0
    assert parsed["is_tomorrow"] is True
    assert parsed["target_date"] == fixed_reference(2026, 7, 17, 0, 0)


def test_supplied_turn_reference_bypasses_provider_and_is_used_exactly():
    def forbidden_provider():
        raise AssertionError("provider must not be read when turn clock is supplied")

    manager = CountdownManager(now_provider=forbidden_provider)
    reference = fixed_reference(2026, 12, 24, 23, 59)

    parsed = manager.parse_countdown_query(
        "hvor lenge til jul",
        reference_time=reference,
    )

    assert parsed is not None
    assert parsed["days"] == 1
    assert parsed["target_date"] == fixed_reference(2026, 12, 25, 0, 0)


def test_omitted_reference_reads_injected_provider_exactly_once():
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return fixed_reference(2026, 7, 16, 23, 59)

    parsed = CountdownManager(now_provider=provider).parse_countdown_query(
        "dager til 17.07"
    )

    assert parsed is not None
    assert parsed["days"] == 1
    assert calls == 1


def test_named_holiday_rolls_to_next_recurring_occurrence():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 12, 26)
    )

    parsed = manager.parse_countdown_query("countdown to Christmas")

    assert parsed is not None
    assert parsed["target_date"] == fixed_reference(2027, 12, 25, 0, 0)
    assert parsed["days"] == 364


def test_easter_is_computed_for_the_next_applicable_year():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 4, 6)
    )

    parsed = manager.parse_countdown_query("hvor lenge til påske")

    assert parsed is not None
    assert parsed["target_date"] == fixed_reference(2027, 3, 28, 0, 0)
    assert parsed["days"] == 356


def test_explicit_past_year_is_never_rolled_forward():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    parsed = manager.parse_countdown_query("dager til 01.01.2020")

    assert parsed is not None
    assert parsed["target_date"] == fixed_reference(2020, 1, 1, 0, 0)
    assert parsed["days"] < 0
    assert parsed["is_past"] is True


def test_iso_date_uses_the_captured_turn_clock():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    parsed = manager.parse_countdown_query("days until 2026-12-25")

    assert parsed is not None
    assert parsed["target_date"] == fixed_reference(2026, 12, 25, 0, 0)
    assert parsed["days"] == 162


def test_yearless_past_date_rolls_once_to_next_year():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    parsed = manager.parse_countdown_query("dager til 01.01")

    assert parsed is not None
    assert parsed["target_date"] == fixed_reference(2027, 1, 1, 0, 0)
    assert parsed["days"] == 169


def test_yearless_leap_day_finds_the_next_valid_occurrence():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    parsed = manager.parse_countdown_query("dager til 29.02")

    assert parsed is not None
    assert parsed["target_date"] == fixed_reference(2028, 2, 29, 0, 0)


def test_impossible_yearless_date_fails_closed_without_unbounded_search():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    assert manager.parse_countdown_query("dager til 31.02") is None


def test_numeric_date_rejects_unconsumed_suffix():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    assert manager.parse_countdown_query("dager til 17.07 garbage") is None
    assert manager.parse_countdown_query("days until 07/17 garbage") is None


def test_movable_norwegian_sunday_observances_are_computed_per_year():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2027, 2, 1)
    )

    mothers_day = manager.parse_countdown_query("hvor lenge til morsdag")

    assert mothers_day is not None
    assert mothers_day["target_date"] == fixed_reference(2027, 2, 14, 0, 0)

    november = fixed_reference(2027, 11, 1)
    all_saints = manager.parse_countdown_query(
        "hvor lenge til allehelgensdag",
        reference_time=november,
    )
    fathers_day = manager.parse_countdown_query(
        "hvor lenge til farsdag",
        reference_time=november,
    )

    assert all_saints is not None
    assert all_saints["target_date"] == fixed_reference(2027, 11, 7, 0, 0)
    assert fathers_day is not None
    assert fathers_day["target_date"] == fixed_reference(2027, 11, 14, 0, 0)


def test_regional_school_holidays_do_not_fabricate_one_universal_date():
    manager = CountdownManager(
        now_provider=lambda: fixed_reference(2026, 7, 16)
    )

    for text in (
        "hvor lenge til sommerferie",
        "hvor lenge til vinterferie",
        "hvor lenge til høstferie",
        "countdown to summer vacation",
        "countdown to winter holiday",
        "countdown to fall break",
    ):
        assert manager.parse_countdown_query(text) is None
