from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cal_system.natural_language_parser import NaturalLanguageParser, NaturalParseResult
from cal_system.temporal_resolver import DATE_ALIASES, TemporalResolver
from core.utterance import normalize_utterance


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)


@pytest.mark.parametrize("alias", tuple(DATE_ALIASES))
@pytest.mark.parametrize("method", ["parse_event_result", "parse_task_with_recurrence_result"])
def test_all_date_aliases_work_through_both_result_wrappers(alias, method):
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    prefix = "møte" if method == "parse_event_result" else "jeg må levere rapport"
    result = getattr(parser, method)(f"{prefix} {alias} kl 14")
    assert isinstance(result, NaturalParseResult)
    assert result.errors == ()
    assert result.item is not None
    expected = NOW.date() + timedelta(days=DATE_ALIASES[alias])
    assert result.item["date"] == expected.strftime("%d.%m.%Y")
    assert result.item["time"] == "14:00"


@pytest.mark.parametrize(
    ("phrase", "canonical"),
    [
        ("13:30", "13:30"),
        ("noon", "12:00"),
        ("midnatt", "00:00"),
        ("midnight", "00:00"),
        ("i morges", "10:00"),
        ("i formiddag", "10:00"),
        ("på formiddagen", "10:00"),
        ("i ettermiddag", "14:00"),
        ("på ettermiddagen", "14:00"),
        ("i kveld", "19:00"),
        ("på kvelden", "19:00"),
        ("i natt", "22:00"),
        ("på natten", "22:00"),
        ("rundt tre på ettermiddagen", "15:00"),
    ],
)
@pytest.mark.parametrize("method", ["parse_event_result", "parse_task_with_recurrence_result"])
def test_time_vocabulary_uses_only_resolver_canonical_values(phrase, canonical, method):
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    prefix = "møte" if method == "parse_event_result" else "jeg må levere rapport"
    result = getattr(parser, method)(f"{prefix} 15. august {phrase}")
    assert result.errors == ()
    assert result.item is not None
    assert result.item["date"] == "15.08.2026"
    assert result.item["time"] == canonical


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("møte 32.13.2026 kl 14", "invalid_date"),
        ("møte i morgen kl 25:61", "invalid_time"),
        ("møte i morgen 16.07.2026 kl 14", "conflicting_temporal"),
        ("møte 25.10.2026 kl 02:30", "ambiguous_time"),
    ],
)
@pytest.mark.parametrize("method", ["parse_event_result", "parse_task_with_recurrence_result"])
def test_invalid_and_conflicting_temporal_evidence_fails_closed(text, error, method):
    if method.startswith("parse_task"):
        text = f"jeg må {text}"
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = getattr(parser, method)(text)
    assert result.item is None
    assert result.errors == (error,)


@pytest.mark.parametrize(
    "method",
    ("parse_event_result", "parse_task_with_recurrence_result"),
)
def test_conflicting_recurrences_fail_closed(method):
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = getattr(parser, method)(
        "lag møte hver uke og hver måned",
        reference_time=NOW,
    )

    assert result.item is None
    assert result.errors == ("conflicting_recurrence",)


def test_relative_parse_accepts_a_real_clock_with_nonzero_seconds():
    reference = datetime(2026, 7, 14, 12, 0, 37, 123456, tzinfo=OSLO)
    parser = NaturalLanguageParser(now_provider=lambda: reference)
    result = parser.parse_event_result("møte om to timer")
    assert result.errors == ()
    assert result.item is not None
    assert result.item["date"] == "14.07.2026"
    assert result.item["time"] == "14:00"
    assert result.item["due_at"] == "2026-07-14T14:00:37+02:00"
    assert result.item["title"] == "Møte"


def test_unquoted_title_uses_the_shared_temporal_cleanup():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = parser.parse_event_result("møte med Ola om to timer")
    assert result.errors == ()
    assert result.item is not None
    assert result.item["title"] == "Møte med Ola"


@pytest.mark.parametrize(
    ("text", "time"),
    (
        ("møte i morgen kl 14.30", "14:30"),
        ("møte i morgen klokka 14:30", "14:30"),
        (
            "møte i morgen klokka halv tre på ettermiddagen",
            "14:30",
        ),
        (
            "møte i morgen kvart over to på ettermiddagen",
            "14:15",
        ),
        (
            "møte i morgen klokka kvart over to på ettermiddagen",
            "14:15",
        ),
    ),
)
def test_minimal_event_title_is_derived_from_original_temporal_cleanup(
    text,
    time,
):
    result = NaturalLanguageParser(now_provider=lambda: NOW).parse_event_result(
        text
    )

    assert result.errors == ()
    assert result.item is not None
    assert result.item["title"] == "Møte"
    assert result.item["date"] == "15.07.2026"
    assert result.item["time"] == time


@pytest.mark.parametrize(
    "text",
    [
        'møte "i morgen kl 14"',
        "møte `i morgen kl 14`",
        "møte\n```text\ni morgen kl 14\n```",
    ],
)
def test_quoted_or_code_only_temporal_evidence_is_inert(text):
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    utterance = normalize_utterance(text)
    result = parser.parse_event_result(text, temporal_text=utterance.control_text)
    assert result.item is None
    assert result.errors == ()


@pytest.mark.parametrize(
    ("left", "right"),
    [("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"), ("«", "»")],
)
def test_all_supported_quoted_titles_remain_case_preserving_data(left, right):
    title = "Team Sync i Morgen"
    text = f"møte {left}{title}{right} i dag kl 14"
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = parser.parse_event_result(
        text,
        temporal_text=normalize_utterance(text).control_text,
    )
    assert result.item is not None
    assert result.item["title"] == title
    assert result.item["date"] == "14.07.2026"
    assert result.item["time"] == "14:00"


def test_curly_quoted_temporal_words_do_not_leak_into_control_slots():
    text = "møte ‘i morgen kl 09’ fredag kl 14"
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = parser.parse_event_result(
        text,
        temporal_text=normalize_utterance(text).control_text,
    )
    assert result.item is not None
    assert result.item["title"] == "i morgen kl 09"
    assert (result.item["date"], result.item["time"]) == (
        "17.07.2026",
        "14:00",
    )


def test_recurrence_only_event_uses_reference_date_and_zero_offset():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = parser.parse_event_result("regninger hver måned")
    assert result.item is not None
    assert result.item["date"] == "14.07.2026"
    assert result.item["days_offset"] == 0
    assert result.item["recurrence"] == "monthly"


def test_event_days_offset_is_always_derived_from_canonical_date():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = parser.parse_event_result("møte 20.07.2026 kl 14")
    assert result.item is not None
    assert result.item["days_offset"] == 6


def test_task_shape_keeps_recurrence_but_never_gains_days_offset():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    result = parser.parse_task_with_recurrence_result(
        "husk å betale regninger hver måned"
    )
    assert result.item is not None
    assert result.item["date"] == "14.07.2026"
    assert result.item["recurrence"] == "monthly"
    assert "days_offset" not in result.item


def test_task_parser_does_not_claim_an_event_without_task_language():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    assert parser.parse_task_with_recurrence_result(
        "møte i morgen kl 14"
    ).item is None
    event = parser.parse_event_result("møte i morgen kl 14").item
    assert event is not None
    assert event["type"] == "event"


def test_dictionary_wrappers_preserve_dict_or_none_contract():
    parser = NaturalLanguageParser(now_provider=lambda: NOW)
    assert isinstance(parser.parse_event("møte i morgen kl 14"), dict)
    assert parser.parse_event("møte 32.13.2026 kl 14") is None
    assert isinstance(
        parser.parse_task_with_recurrence("jeg må levere i morgen kl 14"),
        dict,
    )
    assert parser.parse_task_with_recurrence("jeg må levere 32.13.2026") is None


def test_omitted_reference_reads_advancing_provider_once_per_operation():
    values = iter(
        [
            NOW,
            NOW + timedelta(days=1),
            NOW + timedelta(days=2),
            NOW + timedelta(days=3),
        ]
    )
    calls = []

    def provider():
        value = next(values)
        calls.append(value)
        return value

    parser = NaturalLanguageParser(now_provider=provider)
    first = parser.parse_event_result("møte i morgen kl 14")
    second = parser.parse_event("møte i morgen kl 14")
    third = parser.parse_task_with_recurrence_result("jeg må levere i morgen kl 14")
    fourth = parser.parse_task_with_recurrence("jeg må levere i morgen kl 14")
    assert len(calls) == 4
    assert first.item["date"] == "15.07.2026"
    assert second["date"] == "16.07.2026"
    assert third.item["date"] == "17.07.2026"
    assert fourth["date"] == "18.07.2026"


def test_explicit_reference_reads_provider_zero_times():
    calls = []

    def provider():
        calls.append(True)
        return NOW + timedelta(days=100)

    parser = NaturalLanguageParser(now_provider=provider)
    result = parser.parse_event_result(
        "møte i morgen kl 14",
        reference_time=NOW,
    )
    assert result.item["date"] == "15.07.2026"
    assert calls == []


def test_naive_reference_raises_without_provider_read():
    calls = []
    parser = NaturalLanguageParser(now_provider=lambda: calls.append(True) or NOW)
    with pytest.raises(ValueError, match="temporal_reference_must_be_aware"):
        parser.parse_event_result(
            "møte i morgen kl 14",
            reference_time=datetime(2026, 7, 14, 12),
        )
    assert calls == []


def test_injected_resolver_is_reused_and_never_reads_its_provider():
    resolver_calls = []
    resolver = TemporalResolver(now_provider=lambda: resolver_calls.append(True) or NOW)
    parser = NaturalLanguageParser(
        now_provider=lambda: NOW,
        temporal_resolver=resolver,
    )
    result = parser.parse_event_result("møte i morgen kl 14")
    assert result.item is not None
    assert parser.temporal_resolver is resolver
    assert resolver_calls == []
