import json
from datetime import date as real_date

from features import school_holidays

OSLO_SOURCE = "https://www.oslo.kommune.no/skole-og-utdanning/ferie-og-fridager-i-skolen/"
TRONDHEIM_SOURCE = (
    "https://www.trondheim.kommune.no/tema/skole/trondheimsskolen/"
    "overganger/ferie-og-fridager/"
)


def _schedule(locality_id, school_year, today):
    loader = getattr(school_holidays, "get_school_schedule", None)
    assert callable(loader), "get_school_schedule must expose reviewed schedule coverage"
    return loader(locality_id, school_year, today)


def _freeze_today(monkeypatch, today):
    class FrozenDate(real_date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(school_holidays, "date", FrozenDate)


def _holiday(schedule, name):
    return next(holiday for holiday in schedule.holidays if holiday["name"] == name)


def test_populated_2025_2026_table_does_not_leave_october_2026_empty(monkeypatch):
    _freeze_today(monkeypatch, real_date(2026, 10, 4))

    response = school_holidays.format_holidays_list("oslo")

    assert "juleferie" in response.lower()
    assert "ingen ferier planlagt" not in response.lower()


def test_official_locality_schedules_have_distinct_verified_ranges():
    today = real_date(2026, 10, 4)
    oslo = _schedule("oslo", "2026-2027", today)
    trondheim = _schedule("trondheim", "2026-2027", today)

    oslo_autumn = _holiday(oslo, "Høstferie")
    trondheim_autumn = _holiday(trondheim, "Høstferie")
    assert oslo_autumn["start_date"] == real_date(2026, 9, 28)
    assert oslo_autumn["end_date"] == real_date(2026, 10, 2)
    assert trondheim_autumn["start_date"] == real_date(2026, 10, 5)
    assert trondheim_autumn["end_date"] == real_date(2026, 10, 9)
    assert oslo.coverage == "verified"
    assert oslo.source_refs == [OSLO_SOURCE]
    assert oslo.verified_at == today
    assert trondheim.coverage == "partial"
    assert trondheim.source_refs == [TRONDHEIM_SOURCE]
    assert "planleggingsdager" in trondheim.coverage_note.lower()

    expected = {
        "oslo": {
            "Høstferie": (real_date(2026, 9, 28), real_date(2026, 10, 2)),
            "Juleferie": (real_date(2026, 12, 21), real_date(2027, 1, 1)),
            "Vinterferie": (real_date(2027, 2, 22), real_date(2027, 2, 26)),
            "Påskeferie": (real_date(2027, 3, 22), real_date(2027, 3, 30)),
            "Kristi Himmelfartsdag": (real_date(2027, 5, 6), real_date(2027, 5, 6)),
            "Inneklemt fridag": (real_date(2027, 5, 7), real_date(2027, 5, 7)),
            "Grunnlovsdag / 2. pinsedag": (real_date(2027, 5, 17), real_date(2027, 5, 17)),
            "Sommerferie": (real_date(2027, 6, 19), real_date(2027, 8, 15)),
        },
        "trondheim": {
            "Høstferie": (real_date(2026, 10, 5), real_date(2026, 10, 9)),
            "Juleferie": (real_date(2026, 12, 19), real_date(2027, 1, 3)),
            "Skolefri-2027-01-29": (real_date(2027, 1, 29), real_date(2027, 1, 29)),
            "Vinterferie": (real_date(2027, 2, 22), real_date(2027, 2, 26)),
            "Påskeferie": (real_date(2027, 3, 22), real_date(2027, 3, 29)),
            "Skolefri-2027-05-07": (real_date(2027, 5, 7), real_date(2027, 5, 7)),
            "Sommerferie": (real_date(2027, 6, 19), real_date(2027, 8, 22)),
        },
    }
    for schedule, expected_holidays in ((oslo, expected["oslo"]), (trondheim, expected["trondheim"])):
        actual = {}
        for holiday in schedule.holidays:
            name = holiday["name"]
            if name == "Skolefri":
                name = f"Skolefri-{holiday['start_date'].isoformat()}"
            actual[name] = (holiday["start_date"], holiday["end_date"])
        assert actual == expected_holidays


def test_unknown_locality_and_invalid_school_year_are_unavailable():
    today = real_date(2026, 10, 4)

    unknown = _schedule("bergen", "2026-2027", today)
    malformed = _schedule("oslo", "2026/27", today)

    assert unknown.coverage == "unavailable"
    assert unknown.holidays == []
    assert malformed.coverage == "unavailable"
    assert malformed.holidays == []


def test_missing_next_school_year_is_unavailable_after_rollover():
    schedule = _schedule("oslo", "2027-2028", real_date(2027, 8, 16))
    response = school_holidays.format_holidays_list(
        "oslo", today=real_date(2027, 8, 16)
    )

    assert schedule.coverage == "unavailable"
    assert "2027–2028" in response
    assert "ikke tilgjengelig" in response.lower()
    assert "ingen ferier planlagt" not in response.lower()


def test_schedule_coverage_expires_after_its_annual_review_window():
    still_current = _schedule("oslo", "2026-2027", real_date(2027, 10, 4))
    expired = _schedule("oslo", "2026-2027", real_date(2027, 10, 5))

    assert still_current.coverage == "verified"
    assert expired.coverage == "partial"
    assert "utløpt" in expired.coverage_note.lower()
    assert expired.holidays


def test_partial_schedule_never_claims_that_no_holidays_exist():
    response = school_holidays.format_holidays_list(
        "trondheim", today=real_date(2027, 4, 1)
    )

    assert "delvis dekning" in response.lower()
    assert "ingen ferier planlagt" not in response.lower()
    assert TRONDHEIM_SOURCE in response


def test_verified_schedule_can_report_no_listed_holidays_without_becoming_unavailable():
    response = school_holidays.format_holidays_list(
        "oslo", today=real_date(2027, 8, 16), school_year="2026-2027"
    )

    assert "dekning: kvalitetssikret" in response.lower()
    assert "ingen oppførte ferier" in response.lower()
    assert "ikke tilgjengelig" not in response.lower()


def test_no_locality_requests_explicit_selection(monkeypatch):
    _freeze_today(monkeypatch, real_date(2026, 10, 4))

    response = school_holidays.format_holidays_list(None)

    assert "velg" in response.lower() or "nevn" in response.lower()
    assert "oslo" in response.lower()
    assert "trondheim" in response.lower()


def test_only_explicitly_supported_localities_are_recognized():
    resolver = getattr(school_holidays, "get_locality_from_location", None)
    assert callable(resolver), "locality routing must not guess county calendars"

    assert resolver("skoleferie Oslo") == "oslo"
    assert resolver("skoleferie i Trondheim") == "trondheim"
    assert resolver("skoleferie Bergen") is None
    assert resolver("skoleferie Viken") is None
    assert resolver("Oslofjord") is None


def test_invalid_holiday_range_degrades_coverage_to_partial(tmp_path, monkeypatch):
    fixture = tmp_path / "school_calendars.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "max_verified_age_days": 365,
                "calendars": {
                    "sample": {
                        "name": "Sample",
                        "school_years": {
                            "2026-2027": {
                                "coverage": "verified",
                                "coverage_note": "Synthetic range-validation fixture.",
                                "verified_at": "2026-10-04",
                                "source_refs": ["https://example.test/calendar"],
                                "holidays": [
                                    {
                                        "name": "Reversed",
                                        "start": "2027-02-26",
                                        "end": "2027-02-22",
                                    }
                                ],
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(school_holidays, "CALENDAR_DATA_PATH", fixture, raising=False)

    schedule = _schedule("sample", "2026-2027", real_date(2026, 10, 4))

    assert schedule.coverage == "partial"
    assert schedule.holidays == []
    assert "ugyldig" in schedule.coverage_note.lower()


async def test_handler_prompts_for_explicit_locality_selection():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from features.school_holidays_handler import SchoolHolidaysHandler
    from memory.localization import Localization

    monitor = SimpleNamespace(rate_limiter=None, loc=Localization(), client=None)
    handler = SchoolHolidaysHandler(monitor)
    handler.send_response = AsyncMock()

    await handler.handle_school_holidays(SimpleNamespace(content="skoleferie Bergen"))

    response = handler.send_response.await_args.args[1]
    assert "Oslo" in response
    assert "Trondheim" in response
    assert "velg" in response.lower() or "nevn" in response.lower()


async def test_handler_shows_locality_coverage_and_official_source():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from features.school_holidays_handler import SchoolHolidaysHandler
    from memory.localization import Localization

    monitor = SimpleNamespace(rate_limiter=None, loc=Localization(), client=None)
    handler = SchoolHolidaysHandler(monitor)
    handler.send_response = AsyncMock()

    await handler.handle_school_holidays(SimpleNamespace(content="skoleferie Trondheim"))

    response = handler.send_response.await_args.args[1]
    assert "delvis dekning" in response.lower()
    assert TRONDHEIM_SOURCE in response


def test_unsupported_dataset_schema_is_unavailable(tmp_path, monkeypatch):
    fixture = tmp_path / "school_calendars.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "max_verified_age_days": 365,
                "calendars": {
                    "sample": {
                        "name": "Sample",
                        "school_years": {
                            "2026-2027": {
                                "coverage": "verified",
                                "verified_at": "2026-10-04",
                                "source_refs": ["https://example.test/calendar"],
                                "holidays": [],
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(school_holidays, "CALENDAR_DATA_PATH", fixture, raising=False)

    schedule = _schedule("sample", "2026-2027", real_date(2026, 10, 4))

    assert schedule.coverage == "unavailable"
    assert "støttes ikke" in schedule.coverage_note.lower()


def test_formatter_keeps_legacy_fylke_keyword_for_supported_localities():
    import inspect

    assert "fylke" in inspect.signature(school_holidays.format_holidays_list).parameters
    response = school_holidays.format_holidays_list(
        fylke="oslo", today=real_date(2026, 10, 4)
    )
    assert "Skoleferier – Oslo" in response


def test_verified_schedule_displays_its_source_caveat():
    response = school_holidays.format_holidays_list(
        "oslo", today=real_date(2026, 10, 4)
    )

    assert "forbehold" in response.lower() or "endres" in response.lower()


def test_legacy_location_resolver_symbol_is_a_locality_only_adapter():
    resolver = getattr(school_holidays, "get_fylke_from_location", None)
    assert callable(resolver)
    assert resolver("Oslo") == "oslo"
    assert resolver("Trondheim") == "trondheim"
    assert resolver("Bergen") is None


def test_future_review_date_is_not_reported_as_expired(tmp_path, monkeypatch):
    fixture = tmp_path / "school_calendars.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "max_verified_age_days": 365,
                "calendars": {
                    "sample": {
                        "name": "Sample",
                        "school_years": {
                            "2026-2027": {
                                "coverage": "verified",
                                "verified_at": "2026-10-05",
                                "source_refs": ["https://example.test/calendar"],
                                "holidays": [],
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(school_holidays, "CALENDAR_DATA_PATH", fixture, raising=False)

    schedule = _schedule("sample", "2026-2027", real_date(2026, 10, 4))

    assert schedule.coverage == "partial"
    assert "fremtiden" in schedule.coverage_note.lower()
    assert "utløpt" not in schedule.coverage_note.lower()


def test_two_supported_localities_require_an_unambiguous_choice():
    assert school_holidays.get_locality_from_location('Skoleferie Oslo eller Trondheim?') is None
    text = school_holidays.format_holidays_list(None, today=real_date(2026, 10, 4))
    assert 'Oslo' in text and 'Trondheim' in text
    assert 'Høstferie' not in text


async def test_handler_honors_requested_unavailable_year(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from memory.localization import Localization
    from features.school_holidays_handler import SchoolHolidaysHandler
    _freeze_today(monkeypatch, real_date(2026, 10, 4))
    handler = SchoolHolidaysHandler(SimpleNamespace(rate_limiter=None, loc=Localization(), client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(content='skoleferie Oslo 2027–2028')
    await handler.handle_school_holidays(message)
    text = handler.send_response.await_args.args[1]
    assert '2027–2028' in text and 'ikke tilgjengelig' in text
    assert 'Høstferie' not in text
