import pytest

from core.intent_models import BotIntent, IntentRisk
from core.intent_payloads import PayloadValidationError, validate_intent_payload
from core.intent_policy import classify_intent_risk


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (
            {
                "action": "start",
                "field": "schedule",
                "target": "Rosenborg - Fredrikstad",
            },
            {
                "action": "start",
                "field": "schedule",
                "target": "Rosenborg - Fredrikstad",
            },
        ),
        ({"action": "select", "number": 2}, {"action": "select", "number": 2}),
        (
            {"action": "search", "field": "schedule", "target": "calendar-1"},
            {"action": "search", "field": "schedule", "target": "calendar-1"},
        ),
        ({"action": "cancel"}, {"action": "cancel"}),
    ),
)
def test_calendar_fact_check_payload_is_exact(raw, expected):
    assert validate_intent_payload(BotIntent.CALENDAR_FACT_CHECK, raw) == expected
    assert classify_intent_risk(
        BotIntent.CALENDAR_FACT_CHECK,
        {"calendar_fact_check": expected},
    ) is IntentRisk.READ_ONLY


@pytest.mark.parametrize(
    "raw",
    (
        {},
        {"action": "start", "field": "schedule"},
        {"action": "start", "field": "title", "target": "kampen"},
        {"action": "select", "number": 0},
        {"action": "select", "number": 1, "target": "kampen"},
        {"action": "search", "field": "schedule", "target": ""},
        {"action": "cancel", "target": "kampen"},
        {"action": "unknown"},
    ),
)
def test_calendar_fact_check_payload_rejects_partial_or_extra_state(raw):
    with pytest.raises(PayloadValidationError):
        validate_intent_payload(BotIntent.CALENDAR_FACT_CHECK, raw)
