"""Privacy and bounded-cardinality contracts for NLU metrics."""

import json

import pytest

from core.intent_models import BotIntent, IntentSource, RejectionCode
from core.nlu_metrics import METRIC_SECTIONS, NLUMetrics


def test_decision_increment_uses_bounded_dimensions():
    metrics = NLUMetrics()
    metrics.record_decision(
        intent=BotIntent.HELP,
        source=IntentSource.DETERMINISTIC,
        outcome="routed",
    )

    assert metrics.snapshot() == {
        "decisions": {"intent=help|source=deterministic|outcome=routed": 1}
    }


def test_snapshot_is_a_copy():
    metrics = NLUMetrics()
    metrics.record_rejection(RejectionCode.CONFLICT)
    snapshot = metrics.snapshot()

    snapshot["rejections"]["conflict"] = 99
    snapshot["rejections"]["other"] = 1

    assert metrics.snapshot() == {"rejections": {"conflict": 1}}


def test_unknown_and_sensitive_dimensions_become_only_other():
    secrets = {
        "intent": "private-message-content",
        "source": "secret-provider-name",
        "outcome": "user@example.com",
        "rejection": "sensitive-rejection",
        "pending": "private-pending-id",
        "action": "private-action-json",
        "parser": "private-parser-input",
        "parser_code": "private-exception-text",
        "legacy": "private-family-name",
        "reminder_event": "private-reminder-id",
        "reminder_error": "private-channel-id",
    }
    metrics = NLUMetrics()
    metrics.record_decision(
        intent=secrets["intent"],
        source=secrets["source"],
        outcome=secrets["outcome"],
    )
    metrics.record_rejection(secrets["rejection"])
    metrics.record_pending(secrets["pending"])
    metrics.record_action_result(secrets["action"])
    metrics.record_parser_error(secrets["parser"], secrets["parser_code"])
    metrics.record_legacy_payload_fallback(secrets["legacy"])
    metrics.record_reminder_delivery(
        secrets["reminder_event"], error_code=secrets["reminder_error"]
    )

    snapshot = metrics.snapshot()
    assert set(snapshot) == set(METRIC_SECTIONS)
    assert snapshot == {
        "actions": {"other": 1},
        "decisions": {"intent=other|source=other|outcome=other": 1},
        "legacy_payload_fallbacks": {"other": 1},
        "parser_errors": {"parser=other|code=other": 1},
        "pending": {"other": 1},
        "rejections": {"other": 1},
        "reminder_delivery": {"event=other|error=other": 1},
    }

    rendered = json.dumps(snapshot, sort_keys=True)
    for rejected_value in secrets.values():
        assert rejected_value not in rendered


def test_raw_text_is_not_an_accepted_dimension():
    metrics = NLUMetrics()
    with pytest.raises(TypeError):
        metrics.record_decision(
            intent=BotIntent.HELP,
            source=IntentSource.DETERMINISTIC,
            outcome="routed",
            raw_text="please leak this",
        )


@pytest.mark.parametrize("value", [True, 0, -1, 2**63, "1", 1.5])
def test_merge_snapshot_rejects_invalid_counts(value):
    metrics = NLUMetrics()
    metrics.merge_snapshot({"rejections": {"conflict": value}})
    assert metrics.snapshot() == {}


def test_merge_snapshot_allows_only_known_sections_and_keys():
    metrics = NLUMetrics()
    metrics.merge_snapshot(
        {
            "rejections": {"conflict": 2, "raw-private-reason": 5},
            "private-section": {"conflict": 7},
        }
    )

    assert metrics.snapshot() == {"rejections": {"conflict": 2}}
