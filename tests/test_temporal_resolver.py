from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cal_system.temporal_resolver import (
    DATE_ALIASES,
    DAYPART_HOURS,
    SPECIAL_HOURS,
    TemporalResolver,
)


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)
RESOLVER = TemporalResolver()


@pytest.mark.parametrize(
    ("text", "date", "time"),
    [
        ("i dag kl 13", "14.07.2026", "13:00"),
        ("idag 13:30", "14.07.2026", "13:30"),
        ("today at 1pm", "14.07.2026", "13:00"),
        ("i morgen kl 8", "15.07.2026", "08:00"),
        ("imorgen kl 8", "15.07.2026", "08:00"),
        ("imorra kl 8", "15.07.2026", "08:00"),
        ("imårra kl 8", "15.07.2026", "08:00"),
        ("i morgon klokka fjorten", "15.07.2026", "14:00"),
        ("tomorrow at 2pm", "15.07.2026", "14:00"),
        ("i overmorgen kl 9", "16.07.2026", "09:00"),
        ("overmorgen kl 9", "16.07.2026", "09:00"),
        ("i overmorgon kl 9", "16.07.2026", "09:00"),
        ("overmorgon kl 9", "16.07.2026", "09:00"),
        ("day after tomorrow at 9", "16.07.2026", "09:00"),
        ("fredag kl 10", "17.07.2026", "10:00"),
        ("om to timer", "14.07.2026", "14:00"),
        ("15. august rundt tre på ettermiddagen", "15.08.2026", "15:00"),
        ("15. august noon", "15.08.2026", "12:00"),
        ("15. august midnatt", "15.08.2026", "00:00"),
        ("15. august midnight", "15.08.2026", "00:00"),
    ],
)
def test_resolve_finite_compatibility_vocabulary(text, date, time):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.valid is True, result
    assert (result.date, result.time) == (date, time)


@pytest.mark.parametrize("alias", tuple(DATE_ALIASES))
def test_every_date_alias_is_bounded_and_resolves(alias):
    result = RESOLVER.resolve(f"{alias} kl 14", reference=NOW)
    assert result.valid is True
    expected = NOW.date().fromordinal(NOW.date().toordinal() + DATE_ALIASES[alias])
    assert result.date == expected.strftime("%d.%m.%Y")


@pytest.mark.parametrize("raw", ["00:00", "08:05", "23:59"])
def test_raw_time_without_cue_uses_first_future_local_occurrence(raw):
    result = RESOLVER.resolve(raw, reference=NOW)
    assert result.valid is True
    assert result.time == raw
    assert result.date == ("14.07.2026" if raw > "12:00" else "15.07.2026")


@pytest.mark.parametrize(
    ("phrase", "canonical"),
    [
        ("i morges", "10:00"),
        ("i formiddag", "10:00"),
        ("på formiddagen", "10:00"),
        ("i ettermiddag", "14:00"),
        ("på ettermiddagen", "14:00"),
        ("i kveld", "19:00"),
        ("kveld", "19:00"),
        ("på kvelden", "19:00"),
        ("i natt", "22:00"),
        ("på natten", "22:00"),
        ("noon", "12:00"),
        ("midnatt", "00:00"),
        ("midnight", "00:00"),
    ],
)
def test_daypart_and_special_hour_defaults(phrase, canonical):
    result = RESOLVER.resolve(phrase, reference=NOW)
    assert result.valid is True
    assert result.time == canonical


def test_legacy_i_kveld_and_i_natt_remain_today_after_default_passed():
    late = datetime(2026, 7, 14, 23, 30, tzinfo=OSLO)
    assert RESOLVER.resolve("i kveld", reference=late).date == "14.07.2026"
    assert RESOLVER.resolve("i natt", reference=late).date == "14.07.2026"


def test_hour_word_does_not_consume_pa_before_daypart():
    result = RESOLVER.resolve(
        "15. august rundt tre på ettermiddagen",
        reference=NOW,
    )
    assert result.errors == ()
    assert (result.date, result.time) == ("15.08.2026", "15:00")


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("kl 0", "00:00"),
        ("kl. 8:05", "08:05"),
        ("klokken 14", "14:00"),
        ("klokka fjorten", "14:00"),
        ("at 12am", "00:00"),
        ("at 12pm", "12:00"),
        ("at 11pm", "23:00"),
        ("rundt tre på morgenen", "03:00"),
        ("rundt tre på ettermiddagen", "15:00"),
        ("about two pm", "14:00"),
    ],
)
def test_cue_hours_and_meridiem(text, canonical):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.valid is True, result
    assert result.time == canonical


def test_small_word_hour_without_disambiguator_is_ambiguous():
    result = RESOLVER.resolve("klokka tre", reference=NOW)
    assert result.errors == ("ambiguous_time",)


NORWEGIAN_NUMBERS = {
    0: "null",
    1: "en",
    2: "to",
    3: "tre",
    4: "fire",
    5: "fem",
    6: "seks",
    7: "sju",
    8: "åtte",
    9: "ni",
    10: "ti",
    11: "elleve",
    12: "tolv",
    13: "tretten",
    14: "fjorten",
    15: "femten",
    16: "seksten",
    17: "sytten",
    18: "atten",
    19: "nitten",
    20: "tjue",
    21: "tjueen",
    22: "tjueto",
    23: "tjuetre",
    24: "tjuefire",
    25: "tjuefem",
    26: "tjueseks",
    27: "tjuesju",
    28: "tjueåtte",
    29: "tjueni",
    30: "tretti",
    31: "trettien",
}


@pytest.mark.parametrize(("number", "word"), tuple(NORWEGIAN_NUMBERS.items()))
def test_norwegian_number_words_zero_through_thirty_one(number, word):
    result = RESOLVER.resolve(f"om {word} dager", reference=NOW)
    assert result.valid is True, result
    expected = NOW.date().fromordinal(NOW.date().toordinal() + number)
    assert result.date == expected.strftime("%d.%m.%Y")
    assert result.time == "12:00"


MONTHS = [
    ("januar", "01", "2027"),
    ("februar", "02", "2027"),
    ("mars", "03", "2027"),
    ("april", "04", "2027"),
    ("mai", "05", "2027"),
    ("juni", "06", "2027"),
    ("juli", "07", "2026"),
    ("august", "08", "2026"),
    ("september", "09", "2026"),
    ("oktober", "10", "2026"),
    ("november", "11", "2026"),
    ("desember", "12", "2026"),
    ("january", "01", "2027"),
    ("february", "02", "2027"),
    ("march", "03", "2027"),
    ("may", "05", "2027"),
    ("june", "06", "2027"),
    ("july", "07", "2026"),
    ("october", "10", "2026"),
    ("december", "12", "2026"),
]


@pytest.mark.parametrize(("month", "number", "year"), MONTHS)
def test_norwegian_and_english_month_names(month, number, year):
    result = RESOLVER.resolve(f"15. {month} kl 14", reference=NOW)
    assert result.valid is True, result
    assert result.date == f"15.{number}.{year}"


def test_compact_dot_month_name_preserves_legacy_shape():
    result = RESOLVER.resolve("4.April kl 14", reference=NOW)
    assert result.valid is True
    assert result.date == "04.04.2027"


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("fredag kl 10", "17.07.2026"),
        ("førstkommende fredag kl 10", "17.07.2026"),
        ("neste fredag kl 10", "24.07.2026"),
        ("next friday at 10", "24.07.2026"),
        ("monday at 10", "20.07.2026"),
        ("førstkommende måndag kl 10", "20.07.2026"),
    ],
)
def test_weekday_next_and_forstkommende_semantics(text, canonical):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.valid is True, result
    assert result.date == canonical


def test_next_weekday_on_same_weekday_means_seven_days_not_fourteen():
    friday = datetime(2026, 7, 17, 9, 0, tzinfo=OSLO)
    next_friday = RESOLVER.resolve("neste fredag kl 10", reference=friday)
    first_friday = RESOLVER.resolve(
        "førstkommende fredag kl 10",
        reference=friday,
    )
    assert next_friday.date == "24.07.2026"
    assert first_friday.date == "17.07.2026"


@pytest.mark.parametrize(
    ("text", "date", "time"),
    [
        ("om 30 minutter", "14.07.2026", "12:30"),
        ("om to timer", "14.07.2026", "14:00"),
        ("om 2 dager", "16.07.2026", "12:00"),
        ("om to uker", "28.07.2026", "12:00"),
        ("in 90 minutes", "14.07.2026", "13:30"),
        ("in one hour", "14.07.2026", "13:00"),
        ("in 3 days", "17.07.2026", "12:00"),
        ("in one week", "21.07.2026", "12:00"),
    ],
)
def test_relative_minutes_hours_days_and_weeks(text, date, time):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.valid is True, result
    assert (result.date, result.time) == (date, time)


@pytest.mark.parametrize("value", ["32.13.2026", "29.02.2025", "1.1.1899", "1.1.2101"])
def test_invalid_dates_are_evidence(value):
    result = RESOLVER.resolve(value, reference=NOW)
    assert result.errors == ("invalid_date",)


@pytest.mark.parametrize("value", ["-1:00", "24:00", "25:61"])
def test_invalid_times_are_evidence(value):
    result = RESOLVER.resolve(value, reference=NOW)
    assert result.errors == ("invalid_time",)


@pytest.mark.parametrize(
    "text",
    [
        "i morgen 16.07.2026 kl 14",
        "i morgen kl 14 kl 15",
        "om to timer kl 14",
        "om to timer i morgen",
        "om to timer i kveld",
    ],
)
def test_distinct_or_mixed_temporal_evidence_conflicts(text):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.errors == ("conflicting_temporal",)


@pytest.mark.parametrize(
    "text",
    [
        "i morgen 15.07.2026 kl 14",
        "i morgen kl 14 14:00",
    ],
)
def test_duplicate_consistent_evidence_is_valid(text):
    result = RESOLVER.resolve(text, reference=NOW)
    assert result.valid is True, result


def test_diagnostics_are_finite_labels_not_user_substrings():
    secret = "PRIVATE_TITLE_98a7"
    result = RESOLVER.resolve(f"{secret} 25:61", reference=NOW)
    assert set(result.matched_text) <= {
        "date_alias",
        "numeric_date",
        "month_date",
        "day_of_month",
        "weekday",
        "relative",
        "natural_time",
        "raw_time",
        "special_hour",
        "daypart",
    }
    assert secret not in repr(result)


@pytest.mark.parametrize(
    ("value", "canonical"),
    [
        ("1.2.26", "01.02.2026"),
        ("1/2/99", "01.02.2099"),
        ("1.2.2000", "01.02.2000"),
        ("1/2", "01.02.2027"),
        ("29.2", "29.02.2028"),
        ("den 31.", "31.07.2026"),
    ],
)
def test_year_rules_and_den_day(value, canonical):
    result = RESOLVER.resolve(f"{value} kl 14", reference=NOW)
    assert result.valid is True, result
    assert result.date == canonical


def test_same_day_yearless_past_time_rolls_to_next_year():
    result = RESOLVER.resolve("14.7 kl 10", reference=NOW)
    assert result.date == "14.07.2027"


def test_yearless_same_day_gap_does_not_roll_to_next_year():
    reference = datetime(2026, 3, 29, 0, 30, tzinfo=OSLO)
    result = RESOLVER.resolve("29.3 kl 2:30", reference=reference)
    assert result.date == "29.03.2026"
    assert result.errors == ("invalid_time",)


def test_dst_gap_and_fold_are_rejected_without_an_explicit_instant():
    gap = RESOLVER.validate_fields("29.03.2026", "02:30", reference=NOW)
    fold = RESOLVER.validate_fields("25.10.2026", "02:30", reference=NOW)
    assert gap.errors == ("invalid_time",)
    assert fold.errors == ("ambiguous_time",)


@pytest.mark.parametrize(
    ("due_at", "canonical"),
    [
        ("2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+02:00"),
        ("2026-10-25T02:30:00+01:00", "2026-10-25T02:30:00+01:00"),
        ("2026-10-25T00:30:00Z", "2026-10-25T02:30:00+02:00"),
        ("2026-10-25T01:30:00Z", "2026-10-25T02:30:00+01:00"),
    ],
)
def test_explicit_instant_disambiguates_fold(due_at, canonical):
    result = RESOLVER.validate_fields(
        "25.10.2026", "02:30", due_at=due_at, reference=NOW
    )
    assert result.valid is True
    assert result.due_at == canonical


@pytest.mark.parametrize(
    "due_at",
    [
        "2026-10-25T02:30:00",
        "2026-10-25T03:30:00+01:00",
        "2026-10-25T02:30:00+00:00",
        "not-a-date",
    ],
)
def test_invalid_or_disagreeing_due_at_is_rejected(due_at):
    result = RESOLVER.validate_fields(
        "25.10.2026", "02:30", due_at=due_at, reference=NOW
    )
    assert result.errors == ("invalid_time",)


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (
            datetime(2026, 3, 29, 1, 30, tzinfo=OSLO),
            "2026-03-29T04:30:00+02:00",
        ),
        (
            datetime(2026, 10, 25, 1, 30, tzinfo=OSLO),
            "2026-10-25T02:30:00+01:00",
        ),
    ],
)
def test_relative_hours_are_elapsed_across_dst(reference, expected):
    result = RESOLVER.resolve("om to timer", reference=reference)
    assert result.valid is True
    assert result.due_at == expected


@pytest.mark.parametrize(
    ("value", "canonical"),
    [("0", "00:00"), ("8", "08:00"), ("8:05", "08:05"), ("23:59", "23:59")],
)
def test_validate_time_is_year_independent(value, canonical):
    assert RESOLVER.validate_time(value) == canonical


@pytest.mark.parametrize("value", ["", "-1", "24", "24:00", "8:5", "noon"])
def test_validate_time_rejects_invalid_scalar(value):
    assert RESOLVER.validate_time(value) is None


def test_validate_fields_requires_date_for_time():
    assert RESOLVER.validate_fields(None, "14:00", reference=NOW).errors == (
        "missing_date",
    )


def test_reference_provider_is_single_capture_and_explicit_reference_skips_it():
    calls = []

    def provider():
        calls.append(True)
        return NOW

    resolver = TemporalResolver(now_provider=provider)
    assert resolver.resolve("i morgen kl 14").valid
    assert len(calls) == 1
    assert resolver.resolve("i morgen kl 14", reference=NOW).valid
    assert len(calls) == 1


def test_naive_reference_is_rejected():
    with pytest.raises(ValueError, match="temporal_reference_must_be_aware"):
        RESOLVER.resolve("i morgen", reference=datetime(2026, 7, 14, 12))


def test_public_constant_vocabularies_are_exactly_finite():
    assert DAYPART_HOURS["i kveld"] == "19:00"
    assert SPECIAL_HOURS == {"noon": "12:00", "midnatt": "00:00", "midnight": "00:00"}
    assert "day after tomorrow" in DATE_ALIASES


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("ring legen i morgen kl 14", "ring legen"),
        ("ring legen om to timer", "ring legen"),
        ("møte førstkommende fredag kl 14", "møte"),
        ("møte 15.08.2026 14:00", "møte"),
        ("middag i kveld", "middag"),
        ("lunsj noon", "lunsj"),
        ("ring legen når du kan", "ring legen når du kan"),
    ],
)
def test_strip_temporal_evidence_uses_shared_finite_collector(text, cleaned):
    assert RESOLVER.strip_temporal_evidence(text, reference=NOW) == cleaned


def test_strip_temporal_evidence_explicit_reference_skips_provider():
    calls = []
    resolver = TemporalResolver(now_provider=lambda: calls.append(True) or NOW)
    assert resolver.strip_temporal_evidence(
        "ring legen i morgen kl 14",
        reference=NOW,
    ) == "ring legen"
    assert calls == []
