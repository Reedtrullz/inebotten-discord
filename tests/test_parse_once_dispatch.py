from __future__ import annotations

import asyncio
import copy
import gc
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from cal_system.reminder_clock import OSLO, SystemReminderClock
from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
    MessageSendResult,
    SEND_ERROR_CODES,
)
from core.intent_models import BotIntent, IntentSource
from core.intent_payloads import (
    ENVELOPE_KEYS,
    INTENT_VALIDATORS,
    PayloadValidationError,
    typed_or_legacy_payload,
    validate_intent_payload,
)
from core.mutation_coordinator import (
    BIRTHDAY_STORE_SCOPE,
    CALENDAR_SHARED_SCOPE,
    MEMORY_STORE_SCOPE,
    POLL_STORE_SCOPE,
    QUOTE_STORE_SCOPE,
    REMINDER_SENT_LOG_SCOPE,
    REMINDER_STORE_SCOPE,
    WATCHLIST_STORE_SCOPE,
    MutationCoordinator,
)


def test_success_keeps_mutation_separate_from_response():
    outcome = DispatchOutcome.success(mutated=True, response_sent=False)
    assert outcome == DispatchOutcome(True, True, False, False, None, False, None)


def test_not_found_can_be_retryable_before_any_write():
    outcome = DispatchOutcome.failure("not_found", retryable=True)
    assert outcome.ok is False
    assert outcome.mutated is False
    assert outcome.retryable is True


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (DeliveryState.NOT_DELIVERED, "empty"),
        (DeliveryState.UNKNOWN, "transport"),
    ],
)
def test_message_send_result_accepts_only_finite_error_codes(state, code):
    assert MessageSendResult(state, code).error_code in SEND_ERROR_CODES
    with pytest.raises(ValueError, match="invalid_send_error_code"):
        MessageSendResult(state, "provider said secret text")


def test_message_send_result_is_immutable_and_delivered_has_no_error():
    result = MessageSendResult(DeliveryState.DELIVERED)
    with pytest.raises(FrozenInstanceError):
        result.error_code = "empty"  # type: ignore[misc]
    with pytest.raises(ValueError, match="delivered_with_error"):
        MessageSendResult(DeliveryState.DELIVERED, "empty")


@pytest.mark.parametrize("state", ["unknown", "bogus", 1, None, {}])
def test_message_send_result_rejects_non_enum_states(state):
    with pytest.raises(ValueError, match="invalid_delivery_state"):
        MessageSendResult(state, "timeout")  # type: ignore[arg-type]


def test_unknown_delivery_is_retained_and_terminal():
    base = DispatchOutcome.failure("not_found", retryable=True)
    send = MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    outcome = base.with_delivery(send)
    assert outcome.response_sent is False
    assert outcome.retryable is False
    assert outcome.delivery_result is send


def test_delivered_is_the_only_response_sent_state():
    delivered = MessageSendResult(DeliveryState.DELIVERED)
    outcome = DispatchOutcome.success(mutated=True).with_delivery(delivered)
    assert outcome.response_sent is True
    assert outcome.delivery_result is delivered
    with pytest.raises(ValueError, match="response_sent_without_delivery"):
        DispatchOutcome.success(response_sent=True)


def test_dispatch_outcome_rejects_inconsistent_unknown_states():
    unknown = MessageSendResult(DeliveryState.UNKNOWN, "http")
    with pytest.raises(ValueError, match="invalid_unknown_commit_outcome"):
        DispatchOutcome(ok=True, commit_unknown=True)
    with pytest.raises(ValueError, match="invalid_unknown_commit_outcome"):
        DispatchOutcome(ok=False, retryable=True, commit_unknown=True)
    with pytest.raises(ValueError, match="inconsistent_delivery_outcome"):
        DispatchOutcome(ok=True, delivery_result=MessageSendResult(DeliveryState.DELIVERED))
    with pytest.raises(ValueError, match="retryable_unknown_delivery"):
        DispatchOutcome(ok=False, retryable=True, delivery_result=unknown)


def test_dispatch_outcome_retains_proven_mutation_with_unknown_commit_remainder():
    outcome = DispatchOutcome.failure(
        "commit_state_unknown", mutated=True, commit_unknown=True
    )
    assert outcome.mutated is True
    assert outcome.commit_unknown is True


def test_dispatch_cancellation_and_manager_carriers_preserve_truth():
    manager_error = ManagerMutationError("storage_error", mutated=True)
    assert (manager_error.code, manager_error.mutated, manager_error.commit_unknown) == (
        "storage_error",
        True,
        False,
    )
    manager_cancel = ManagerMutationCancelled(
        "cancelled", mutated=False, retryable=True
    )
    assert manager_cancel.retryable is True
    outcome = DispatchOutcome.failure("cancelled", retryable=True)
    assert DispatchCancelled(outcome).outcome is outcome
    send = MessageSendResult(DeliveryState.UNKNOWN, "send_task_cancelled")
    assert MessageSendCancelled(send).result is send


def test_external_mutation_result_keeps_finite_commit_state():
    assert {state.value for state in ExternalCommitState} == {
        "changed",
        "unchanged",
        "commit_unknown",
    }
    result = ExternalMutationResult(
        ok=False,
        state=ExternalCommitState.UNKNOWN,
        error_code="external_error",
    )
    assert result.state is ExternalCommitState.UNKNOWN


VALID_PAYLOAD_CASES = [
    (
        BotIntent.CALENDAR_ITEM,
        {
            "title": "  Styremøte  ",
            "date": "15.7.2026",
            "time": "9:05",
            "type": "event",
            "recurrence": "weekly",
            "recurrence_day": "onsdag",
            "rrule_day": "WE",
            "days_offset": 0,
            "description": "  Saksliste  ",
        },
        {
            "title": "Styremøte",
            "date": "15.07.2026",
            "time": "09:05",
            "type": "event",
            "recurrence": "weekly",
            "recurrence_day": "onsdag",
            "rrule_day": "WE",
            "days_offset": 0,
            "description": "Saksliste",
        },
    ),
    (
        BotIntent.CALENDAR_EDIT,
        {
            "target": "  Styremøte  ",
            "changes": {
                "title": "  Ny tittel ",
                "type": "task",
                "date": "16.7.2026",
                "time": "10:00",
                "recurrence": None,
            },
        },
        {
            "target": "Styremøte",
            "changes": {
                "title": "Ny tittel",
                "type": "task",
                "date": "16.07.2026",
                "time": "10:00",
                "recurrence": None,
            },
        },
    ),
    (BotIntent.CALENDAR_DELETE, {"number": 2}, {"number": 2}),
    (BotIntent.CALENDAR_COMPLETE, {"target": "Rapport"}, {"target": "Rapport"}),
    (BotIntent.CALENDAR_CLEAR, {"all": True}, {"all": True}),
    (
        BotIntent.REMINDER_CREATE,
        {
            "action": "add",
            "text": "  Ring legen  ",
            "due_at": "2026-07-15T09:05:00+02:00",
            "recurrence": "weekly",
        },
        {
            "action": "add",
            "text": "Ring legen",
            "due_at": "2026-07-15T09:05:00+02:00",
            "due_date": "15.07.2026",
            "time": "09:05",
            "timezone": "Europe/Oslo",
            "recurrence": "weekly",
        },
    ),
    (
        BotIntent.REMINDER_EDIT,
        {
            "action": "edit",
            "reminder_id": " rem-1 ",
            "changes": {"text": " Ny tekst ", "due_date": "16.7.2026"},
        },
        {
            "action": "edit",
            "reminder_id": "rem-1",
            "changes": {"text": "Ny tekst", "due_date": "16.07.2026"},
        },
    ),
    (BotIntent.REMINDER_LIST, {"action": "list"}, {"action": "list"}),
    (
        BotIntent.REMINDER_SEARCH,
        {"action": "search", "query": "  lege  "},
        {"action": "search", "query": "lege"},
    ),
    (
        BotIntent.REMINDER_COMPLETE,
        {"action": "complete", "number": 1},
        {"action": "complete", "number": 1},
    ),
    (
        BotIntent.REMINDER_DELETE,
        {"action": "delete", "reminder_id": " rem-2 "},
        {"action": "delete", "reminder_id": "rem-2"},
    ),
    (
        BotIntent.POLL_CREATE,
        {"question": "  Mat? ", "options": [" Pizza ", "Taco"], "lang": "no"},
        {"question": "Mat?", "options": ["Pizza", "Taco"], "lang": "no"},
    ),
    (BotIntent.POLL_VOTE, {"option": 2, "poll_id": " p-1 "}, {"option": 2, "poll_id": "p-1"}),
    (
        BotIntent.POLL_EDIT,
        {"target": "siste", "question": " Ny? ", "options": ["Ja", "Nei"]},
        {"target": "siste", "question": "Ny?", "options": ["Ja", "Nei"]},
    ),
    (BotIntent.POLL_DELETE, {"poll_id": " p-2 "}, {"poll_id": "p-2"}),
    (BotIntent.POLL_CLOSE, {"target": 1}, {"target": 1}),
    (
        BotIntent.BIRTHDAY_CREATE,
        {"action": "add", "user_id": 7, "display_name": " Kari ", "day": 29, "month": 2, "year": 2024},
        {"action": "add", "user_id": 7, "display_name": "Kari", "day": 29, "month": 2, "year": 2024},
    ),
    (
        BotIntent.BIRTHDAY_EDIT,
        {"action": "edit", "user_id": 7, "day": 1, "month": 3},
        {"action": "edit", "user_id": 7, "day": 1, "month": 3},
    ),
    (BotIntent.BIRTHDAY_LIST, {"action": "list"}, {"action": "list", "scope": "all"}),
    (
        BotIntent.WATCHLIST,
        {"action": "add", "title": "  Life is Strange ", "type": "series", "lang": "en"},
        {"action": "add", "title": "Life is Strange", "type": "series", "lang": "en"},
    ),
    (
        BotIntent.WATCHLIST,
        {"action": "edit", "index": 2, "comment": None, "genre": " Drama "},
        {"action": "edit", "index": 2, "comment": None, "genre": "Drama"},
    ),
    (BotIntent.WATCHLIST, {"action": "remove", "index": 3}, {"action": "remove", "index": 3}),
    (BotIntent.WATCHLIST, {"action": "status"}, {"action": "status"}),
    (BotIntent.WATCHLIST, {"action": "suggest", "genre": " Sci-Fi "}, {"action": "suggest", "genre": "Sci-Fi"}),
    (
        BotIntent.QUOTE,
        {"action": "save", "text": "  Husk dette  ", "author": " Kari ", "lang": "no"},
        {"action": "save", "text": "Husk dette", "author": "Kari", "lang": "no"},
    ),
    (
        BotIntent.QUOTE_EDIT,
        {"action": "edit", "index": 1, "text": " Ny tekst ", "author": " Ola "},
        {"action": "edit", "index": 1, "text": "Ny tekst", "author": "Ola"},
    ),
    (BotIntent.QUOTE_DELETE, {"action": "delete", "index": 2}, {"action": "delete", "index": 2}),
    (BotIntent.QUOTE_LIST, {"action": "list"}, {"action": "list"}),
    (
        BotIntent.QUOTE,
        {"action": "get", "author": " Kari ", "lang": "no"},
        {"action": "get", "author": "Kari", "lang": "no"},
    ),
]


@pytest.mark.parametrize(("intent", "raw", "expected"), VALID_PAYLOAD_CASES)
def test_valid_payload_families_normalize_without_mutating_input(intent, raw, expected):
    original = copy.deepcopy(raw)
    assert validate_intent_payload(intent, raw) == expected
    assert raw == original


def test_validation_returns_detached_nested_values():
    poll_raw = {"question": "Mat?", "options": ["Pizza", "Taco"]}
    poll_result = validate_intent_payload(BotIntent.POLL_CREATE, poll_raw)
    assert poll_result["options"] is not poll_raw["options"]
    poll_result["options"].append("Sushi")
    assert poll_raw["options"] == ["Pizza", "Taco"]

    edit_raw = {
        "target": "Møte",
        "changes": {"title": "Nytt møte", "type": "event"},
    }
    edit_result = validate_intent_payload(BotIntent.CALENDAR_EDIT, edit_raw)
    assert edit_result["changes"] is not edit_raw["changes"]
    edit_result["changes"]["title"] = "Endret igjen"
    assert edit_raw["changes"]["title"] == "Nytt møte"


def test_matching_due_at_compatibility_fields_are_canonicalized_together():
    raw = {
        "action": "add",
        "text": "Ring legen",
        "due_at": "2026-07-15T09:05:00+02:00",
        "due_date": "15.7.2026",
        "time": "9:05",
        "timezone": "Europe/Oslo",
    }
    assert validate_intent_payload(BotIntent.REMINDER_CREATE, raw) == {
        "action": "add",
        "text": "Ring legen",
        "due_at": "2026-07-15T09:05:00+02:00",
        "due_date": "15.07.2026",
        "time": "09:05",
        "timezone": "Europe/Oslo",
    }


def test_aware_utc_due_at_is_normalized_to_oslo_without_wall_clock_state():
    assert validate_intent_payload(
        BotIntent.REMINDER_CREATE,
        {
            "action": "add",
            "text": "Ring legen",
            "due_at": "2026-07-15T07:05:00+00:00",
        },
    ) == {
        "action": "add",
        "text": "Ring legen",
        "due_at": "2026-07-15T09:05:00+02:00",
        "due_date": "15.07.2026",
        "time": "09:05",
        "timezone": "Europe/Oslo",
    }


@pytest.mark.parametrize(
    ("due_at", "expected_offset"),
    [
        ("2026-10-25T02:30:00+02:00", "+02:00"),
        ("2026-10-25T02:30:00+01:00", "+01:00"),
    ],
)
def test_explicit_oslo_fold_offsets_disambiguate_due_at(due_at, expected_offset):
    result = validate_intent_payload(
        BotIntent.REMINDER_CREATE,
        {"action": "add", "text": "DST", "due_at": due_at},
    )
    assert result["due_at"].endswith(expected_offset)
    assert result["due_date"] == "25.10.2026"
    assert result["time"] == "02:30"


def test_yearless_leap_day_is_calendar_valid():
    assert validate_intent_payload(
        BotIntent.BIRTHDAY_EDIT,
        {"action": "edit", "user_id": 1, "day": 29, "month": 2},
    ) == {"action": "edit", "user_id": 1, "day": 29, "month": 2}


INVALID_PAYLOAD_CASES = [
    (BotIntent.QUOTE, None, IntentSource.DETERMINISTIC, "missing_payload"),
    (BotIntent.QUOTE, {"action": "save", "text": "x", "raw_text": "secret"}, IntentSource.SEMANTIC, "unknown_key"),
    (BotIntent.REMINDER_CREATE, {"action": "edit", "text": "x"}, IntentSource.DETERMINISTIC, "wrong_action"),
    (BotIntent.CALENDAR_DELETE, {}, IntentSource.DETERMINISTIC, "missing_target"),
    (BotIntent.CALENDAR_DELETE, {"target": "x", "number": 1}, IntentSource.DETERMINISTIC, "ambiguous_target"),
    (BotIntent.CALENDAR_EDIT, {"target": "x", "changes": {}}, IntentSource.DETERMINISTIC, "missing_change"),
    (BotIntent.QUOTE, {"action": "save", "text": "  "}, IntentSource.DETERMINISTIC, "blank_value"),
    (BotIntent.POLL_VOTE, {"option": True}, IntentSource.DETERMINISTIC, "invalid_number"),
    (BotIntent.CALENDAR_ITEM, {"title": "x", "date": "31.02.2026"}, IntentSource.DETERMINISTIC, "invalid_date"),
    (BotIntent.CALENDAR_ITEM, {"title": "x", "date": "15.07.2026", "time": "25:00"}, IntentSource.DETERMINISTIC, "invalid_time"),
        (BotIntent.CALENDAR_ITEM, {"title": "x", "date": "25.10.2026", "time": "02:30"}, IntentSource.DETERMINISTIC, "ambiguous_time"),
        (BotIntent.CALENDAR_ITEM, {"title": "x", "date": "29.03.2026", "time": "02:30"}, IntentSource.DETERMINISTIC, "invalid_time"),
    (BotIntent.CALENDAR_ITEM, {"title": "x"}, IntentSource.DETERMINISTIC, "missing_date"),
    (BotIntent.REMINDER_CREATE, {"action": "add", "text": "x", "due_at": "2026-07-15T09:00:00"}, IntentSource.DETERMINISTIC, "invalid_due_at"),
    (BotIntent.REMINDER_CREATE, {"action": "add", "text": "x", "due_date": "15.07.2026", "timezone": "Europe/Paris"}, IntentSource.DETERMINISTIC, "invalid_timezone"),
    (BotIntent.REMINDER_CREATE, {"action": "add", "text": "x", "recurrence": "weekly"}, IntentSource.DETERMINISTIC, "invalid_recurrence"),
    (BotIntent.POLL_CREATE, {"question": "x", "options": ["Ja", " ja "]}, IntentSource.DETERMINISTIC, "invalid_options"),
    (BotIntent.POLL_CREATE, {"question": "x" * 301, "options": ["Ja", "Nei"]}, IntentSource.DETERMINISTIC, "value_too_long"),
    (BotIntent.HELP, {}, IntentSource.DETERMINISTIC, "unsupported_intent"),
]


@pytest.mark.parametrize(("intent", "raw", "source", "code"), INVALID_PAYLOAD_CASES)
def test_invalid_payloads_raise_only_bounded_codes(intent, raw, source, code):
    with pytest.raises(PayloadValidationError) as error:
        validate_intent_payload(intent, raw, source=source)  # type: ignore[arg-type]
    assert error.value.code == code
    assert str(error.value) == code


@pytest.mark.parametrize(
    ("intent", "raw", "code"),
    [
        (BotIntent.CALENDAR_COMPLETE, {"number": False}, "invalid_number"),
        (BotIntent.CALENDAR_ITEM, {"title": "x", "days_offset": False}, "invalid_number"),
        (BotIntent.CALENDAR_ITEM, {"title": "x", "date": True}, "invalid_date"),
        (BotIntent.CALENDAR_CLEAR, {"all": False}, "missing_target"),
        (BotIntent.CALENDAR_DELETE, {"all": True}, "wrong_action"),
        (BotIntent.CALENDAR_EDIT, {"target": "x", "changes": {"type": "note"}}, "wrong_action"),
        (BotIntent.REMINDER_SEARCH, {"action": "search", "query": " "}, "blank_value"),
        (BotIntent.REMINDER_COMPLETE, {"action": "complete", "number": 1, "reminder_id": "x"}, "ambiguous_target"),
        (BotIntent.REMINDER_EDIT, {"action": "edit", "number": 1, "changes": {"due_at": None, "recurrence": "weekly"}}, "invalid_recurrence"),
        (BotIntent.REMINDER_EDIT, {"action": "edit", "number": 1, "changes": {"timezone": "Europe/Oslo"}}, "missing_change"),
        (BotIntent.REMINDER_EDIT, {"action": "edit", "number": 1, "changes": {"due_at": "2026-07-15T09:00:00+02:00", "due_date": "16.07.2026"}}, "invalid_due_at"),
        (BotIntent.POLL_EDIT, {"target": None, "question": "x"}, "missing_target"),
        (BotIntent.POLL_EDIT, {"target": 1}, "missing_change"),
        (BotIntent.POLL_CREATE, {"question": "x", "options": ["Ja", ""]}, "blank_value"),
        (BotIntent.BIRTHDAY_CREATE, {"action": "add", "user_id": 1, "display_name": "x", "day": 29, "month": 2, "year": 2023}, "invalid_date"),
        (BotIntent.BIRTHDAY_EDIT, {"action": "edit", "user_id": True, "day": 1, "month": 1}, "invalid_number"),
        (BotIntent.BIRTHDAY_EDIT, {"action": "edit", "user_id": 1, "day": True, "month": 1}, "invalid_number"),
        (BotIntent.WATCHLIST, {"action": "edit", "index": 1}, "missing_change"),
        (BotIntent.WATCHLIST, {"action": "edit", "index": 1, "lang": "no"}, "missing_change"),
        (BotIntent.WATCHLIST, {"action": "edit", "index": 1, "type": None}, "missing_change"),
        (BotIntent.WATCHLIST, {"action": "remove", "index": False}, "invalid_number"),
        (BotIntent.QUOTE_EDIT, {"action": "edit", "index": 1, "author": " "}, "blank_value"),
        (BotIntent.QUOTE_EDIT, {"action": "edit", "index": 1, "lang": "no"}, "missing_change"),
        (BotIntent.QUOTE_DELETE, {"action": "delete", "index": 0}, "invalid_number"),
    ],
)
def test_cross_field_and_scalar_invalid_payloads(intent, raw, code):
    with pytest.raises(PayloadValidationError) as error:
        validate_intent_payload(intent, raw)
    assert error.value.code == code


@pytest.mark.parametrize(
    ("intent", "raw"),
    [
        (BotIntent.CALENDAR_ITEM, {"title": "x", "date": "15.07"}),
        (BotIntent.CALENDAR_ITEM, {"title": "x", "date": "15.07.95"}),
        (
            BotIntent.REMINDER_CREATE,
            {"action": "add", "text": "x", "due_date": "15.07"},
        ),
        (
            BotIntent.REMINDER_EDIT,
            {
                "action": "edit",
                "number": 1,
                "changes": {"due_date": "15.07.95"},
            },
        ),
    ],
)
def test_canonical_dates_require_four_digit_year(intent, raw):
    with pytest.raises(PayloadValidationError, match="invalid_date"):
        validate_intent_payload(intent, raw)


@pytest.mark.parametrize(
    ("intent", "raw"),
    [
        (
            BotIntent.CALENDAR_ITEM,
            {"title": "x", "date": "15.07.2026", "type": []},
        ),
        (
            BotIntent.CALENDAR_EDIT,
            {"target": "x", "changes": {"type": {}}},
        ),
        (
            BotIntent.POLL_CREATE,
            {"question": "x", "options": ["a", "b"], "lang": {}},
        ),
        (BotIntent.BIRTHDAY_LIST, {"action": "list", "scope": []}),
        (
            BotIntent.BIRTHDAY_CREATE,
            {
                "action": "add",
                "user_id": 1,
                "display_name": "Kari",
                "day": 10**1000,
                "month": 2,
            },
        ),
        (BotIntent.WATCHLIST, {"action": {}}),
        (BotIntent.QUOTE_LIST, {"action": []}),
    ],
)
def test_json_shaped_invalid_values_raise_bounded_payload_errors(intent, raw):
    with pytest.raises(PayloadValidationError) as captured:
        validate_intent_payload(intent, raw)
    assert captured.value.code in {"invalid_date", "wrong_action"}


@pytest.mark.parametrize(
    ("intent", "raw"),
    [
        (BotIntent.WATCHLIST, {"action": "status", "title": "Secret"}),
        (BotIntent.WATCHLIST, {"action": "status", "index": 1}),
        (BotIntent.WATCHLIST, {"action": "status", "type": "movie"}),
        (BotIntent.WATCHLIST, {"action": "suggest", "comment": "Secret"}),
        (BotIntent.WATCHLIST, {"action": "remove", "index": 1, "title": "X"}),
        (BotIntent.QUOTE_LIST, {"action": "list", "text": "Secret"}),
        (
            BotIntent.QUOTE_DELETE,
            {"action": "delete", "index": 1, "author": "Secret"},
        ),
        (BotIntent.QUOTE, {"action": "get", "text": "Secret"}),
    ],
)
def test_operation_irrelevant_known_fields_fail_closed(intent, raw):
    with pytest.raises(PayloadValidationError, match="unknown_key"):
        validate_intent_payload(intent, raw)


@pytest.mark.parametrize(
    ("intent", "raw"),
    [
        (
            BotIntent.CALENDAR_EDIT,
            {"target": "Møte", "changes": {"title": "Ny", "raw_text": "secret"}},
        ),
        (
            BotIntent.REMINDER_EDIT,
            {
                "action": "edit",
                "number": 1,
                "changes": {"text": "Ny", "content": "secret"},
            },
        ),
    ],
)
def test_nested_raw_or_unknown_parser_state_is_rejected(intent, raw):
    with pytest.raises(PayloadValidationError) as error:
        validate_intent_payload(intent, raw, source=IntentSource.SEMANTIC)
    assert error.value.code == "unknown_key"


def test_action_envelope_map_is_complete_and_stable():
    assert set(INTENT_VALIDATORS) == set(ENVELOPE_KEYS)
    assert ENVELOPE_KEYS[BotIntent.CALENDAR_ITEM] == "calendar_item"
    assert ENVELOPE_KEYS[BotIntent.REMINDER_EDIT] == "reminder"
    assert ENVELOPE_KEYS[BotIntent.POLL_VOTE] == "vote"
    assert ENVELOPE_KEYS[BotIntent.BIRTHDAY_EDIT] == "birthday"
    assert ENVELOPE_KEYS[BotIntent.WATCHLIST] == "watchlist"
    assert ENVELOPE_KEYS[BotIntent.QUOTE_DELETE] == "quote"
    assert BotIntent.CALENDAR_SEARCH not in ENVELOPE_KEYS


class _MetricsSpy:
    def __init__(self):
        self.families: list[str] = []

    def record_legacy_payload_fallback(self, family: str) -> None:
        self.families.append(family)


class _MonitorSpy:
    def __init__(self):
        self.nlu_metrics = _MetricsSpy()


def test_typed_payload_bypasses_legacy_factory_and_metric():
    monitor = _MonitorSpy()
    called = False

    def legacy_factory():
        nonlocal called
        called = True
        return {"legacy": True}

    typed = {"typed": True}
    assert typed_or_legacy_payload(
        monitor=monitor,
        family="quote",
        typed_value=typed,
        legacy_factory=legacy_factory,
    ) is typed
    assert called is False
    assert monitor.nlu_metrics.families == []


def test_empty_typed_payload_is_authoritative_and_never_reparsed():
    monitor = _MonitorSpy()

    def legacy_factory():
        raise AssertionError("typed empty mapping must not fall back")

    typed: dict[str, object] = {}
    assert typed_or_legacy_payload(
        monitor=monitor,
        family="calendar",
        typed_value=typed,
        legacy_factory=legacy_factory,
    ) is typed
    assert monitor.nlu_metrics.families == []


def test_missing_typed_payload_records_and_uses_legacy_factory_once():
    monitor = _MonitorSpy()
    calls = 0

    def legacy_factory():
        nonlocal calls
        calls += 1
        return {"legacy": True}

    assert typed_or_legacy_payload(
        monitor=monitor,
        family="quote",
        typed_value=None,
        legacy_factory=legacy_factory,
    ) == {"legacy": True}
    assert calls == 1
    assert monitor.nlu_metrics.families == ["quote"]


def test_system_reminder_clock_is_aware_and_rejects_naive_configuration():
    clock = SystemReminderClock()
    now = clock.now()
    assert now.tzinfo is OSLO
    assert clock.epoch() > 0
    with pytest.raises(ValueError, match="naive_reminder_clock"):
        SystemReminderClock(timezone=None)  # type: ignore[arg-type]


def test_mutation_scope_constants_protect_complete_roots():
    assert {
        CALENDAR_SHARED_SCOPE,
        REMINDER_STORE_SCOPE,
        REMINDER_SENT_LOG_SCOPE,
        POLL_STORE_SCOPE,
        WATCHLIST_STORE_SCOPE,
        QUOTE_STORE_SCOPE,
        BIRTHDAY_STORE_SCOPE,
        MEMORY_STORE_SCOPE,
    } == {
        ("calendar", "shared"),
        ("reminder", "store"),
        ("reminder", "sent_log"),
        ("poll", "store"),
        ("watchlist", "store"),
        ("quote", "store"),
        ("birthday", "store"),
        ("memory", "store"),
    }


@pytest.mark.asyncio
async def test_mutation_coordinator_same_task_reentry():
    coordinator = MutationCoordinator()
    async with coordinator.hold(REMINDER_STORE_SCOPE):
        async with coordinator.hold(REMINDER_STORE_SCOPE):
            assert True


@pytest.mark.asyncio
async def test_mutation_coordinator_excludes_cross_task_root_writes():
    coordinator = MutationCoordinator()
    entered: list[str] = []
    release = asyncio.Event()

    async def writer(label: str):
        async with coordinator.hold(WATCHLIST_STORE_SCOPE):
            entered.append(label)
            if label == "guild-1":
                await release.wait()

    first = asyncio.create_task(writer("guild-1"))
    await asyncio.sleep(0)
    second = asyncio.create_task(writer("guild-2"))
    await asyncio.sleep(0)
    assert entered == ["guild-1"]
    release.set()
    await asyncio.gather(first, second)
    assert entered == ["guild-1", "guild-2"]


@pytest.mark.asyncio
async def test_mutation_coordinator_fifo_and_cancelled_middle_waiter():
    coordinator = MutationCoordinator()
    entered: list[int] = []

    async def waiter(number: int):
        async with coordinator.hold(POLL_STORE_SCOPE):
            entered.append(number)

    async with coordinator.hold(POLL_STORE_SCOPE):
        tasks = []
        for number in (1, 2, 3, 4):
            tasks.append(asyncio.create_task(waiter(number)))
            await asyncio.sleep(0)
        tasks[1].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[1]
    await asyncio.gather(tasks[0], tasks[2], tasks[3])
    assert entered == [1, 3, 4]


@pytest.mark.asyncio
async def test_mutation_coordinator_new_arrival_cannot_barge_a_queued_waiter():
    coordinator = MutationCoordinator()
    entered: list[str] = []

    async def waiter(label: str):
        async with coordinator.hold(CALENDAR_SHARED_SCOPE):
            entered.append(label)

    async with coordinator.hold(CALENDAR_SHARED_SCOPE):
        queued = asyncio.create_task(waiter("queued"))
        await asyncio.sleep(0)
    newcomer = asyncio.create_task(waiter("newcomer"))
    await asyncio.gather(queued, newcomer)
    assert entered == ["queued", "newcomer"]


@pytest.mark.asyncio
async def test_cancelled_granted_waiter_hands_scope_to_next_waiter():
    coordinator = MutationCoordinator()
    entered: list[str] = []

    async def waiter(label: str):
        async with coordinator.hold(REMINDER_STORE_SCOPE):
            entered.append(label)

    async with coordinator.hold(REMINDER_STORE_SCOPE):
        granted = asyncio.create_task(waiter("cancelled"))
        await asyncio.sleep(0)
        next_waiter = asyncio.create_task(waiter("next"))
        await asyncio.sleep(0)
    granted.cancel()
    with pytest.raises(asyncio.CancelledError):
        await granted
    await asyncio.wait_for(next_waiter, timeout=1)
    assert entered == ["next"]


@pytest.mark.asyncio
async def test_mutation_coordinator_scope_isolation():
    coordinator = MutationCoordinator()
    other_entered = asyncio.Event()

    async def other_scope():
        async with coordinator.hold(QUOTE_STORE_SCOPE):
            other_entered.set()

    async with coordinator.hold(BIRTHDAY_STORE_SCOPE):
        task = asyncio.create_task(other_scope())
        await asyncio.wait_for(other_entered.wait(), timeout=1)
    await task


@pytest.mark.asyncio
async def test_mutation_coordinator_child_task_does_not_inherit_ownership():
    coordinator = MutationCoordinator()
    child_entered = asyncio.Event()

    async def child():
        async with coordinator.hold(MEMORY_STORE_SCOPE):
            child_entered.set()

    async with coordinator.hold(MEMORY_STORE_SCOPE):
        task = asyncio.create_task(child())
        await asyncio.sleep(0)
        assert child_entered.is_set() is False
    await asyncio.wait_for(task, timeout=1)
    assert child_entered.is_set() is True


@pytest.mark.asyncio
async def test_owner_body_cancellation_releases_scope_for_next_task():
    coordinator = MutationCoordinator()
    owner_entered = asyncio.Event()
    next_entered = asyncio.Event()

    async def owner():
        async with coordinator.hold(QUOTE_STORE_SCOPE):
            owner_entered.set()
            await asyncio.Event().wait()

    async def next_writer():
        async with coordinator.hold(QUOTE_STORE_SCOPE):
            next_entered.set()

    owner_task = asyncio.create_task(owner())
    await owner_entered.wait()
    next_task = asyncio.create_task(next_writer())
    await asyncio.sleep(0)
    owner_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner_task
    await asyncio.wait_for(next_task, timeout=1)
    assert next_entered.is_set() is True


@pytest.mark.asyncio
async def test_calendar_and_reminder_sent_log_writers_share_one_fifo_scope():
    coordinator = MutationCoordinator()
    entered: list[str] = []
    release = asyncio.Event()

    async def writer(source: str):
        async with coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            entered.append(source)
            if source == "calendar":
                await release.wait()

    calendar = asyncio.create_task(writer("calendar"))
    await asyncio.sleep(0)
    reminder = asyncio.create_task(writer("reminder"))
    await asyncio.sleep(0)
    assert entered == ["calendar"]
    release.set()
    await asyncio.gather(calendar, reminder)
    assert entered == ["calendar", "reminder"]


@pytest.mark.asyncio
async def test_mutation_coordinator_releases_unused_locks_weakly():
    coordinator = MutationCoordinator()
    for number in range(25):
        async with coordinator.hold(("test", str(number))):
            pass
    gc.collect()
    await asyncio.sleep(0)
    assert len(coordinator._locks) == 0
