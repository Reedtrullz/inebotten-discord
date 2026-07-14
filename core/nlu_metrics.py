"""Privacy-safe, bounded-cardinality in-memory NLU metrics."""

from collections import Counter
from collections.abc import Mapping

from core.intent_models import BotIntent, IntentSource, RejectionCode

INTENT_VALUES = frozenset(intent.value for intent in BotIntent)
SOURCE_VALUES = frozenset({"deterministic", "semantic"})
DECISION_OUTCOMES = frozenset(
    {
        "routed",
        "clarified",
        "blocked",
        "low_confidence",
        "staged",
        "executed",
        "failed",
        "canceled",
        "other",
    }
)
REJECTION_VALUES = frozenset(code.value for code in RejectionCode)
PENDING_EVENTS = frozenset(
    {
        "staged",
        "confirmed",
        "canceled",
        "selected",
        "corrected",
        "expired",
        "claim_failed",
        "dispatch_failed",
        "presentation_failed",
        "other",
    }
)
ACTION_RESULTS = frozenset(
    {
        "accepted",
        "invalid_json",
        "unknown_action",
        "unknown_key",
        "invalid_slot",
        "missing_slot",
        "multiple_proposals",
        "legacy",
        "other",
    }
)
PARSER_NAMES = frozenset(
    {
        "calendar",
        "reminder",
        "poll",
        "watchlist",
        "quote",
        "birthday",
        "profile",
        "countdown",
        "price",
        "horoscope",
        "compliment",
        "calculator",
        "shorten",
        "search",
        "action_schema",
        "other",
    }
)
PARSER_ERROR_CODES = frozenset(
    {"invalid_temporal", "invalid_payload", "exception", "other"}
)
REMINDER_EVENTS = frozenset(
    {
        "attempted",
        "sent",
        "send_failed",
        "catchup_sent",
        "deduplicated",
        "digest_sent",
        "digest_failed",
        "other",
    }
)
REMINDER_ERROR_CODES = frozenset(
    {
        "channel_missing",
        "send_forbidden",
        "send_http",
        "manager_error",
        "invalid_due_at",
        "none",
        "other",
    }
)
LEGACY_FAMILIES = frozenset(
    {"calendar", "reminder", "poll", "watchlist", "quote", "birthday", "other"}
)
METRIC_SECTIONS = frozenset(
    {
        "decisions",
        "rejections",
        "pending",
        "actions",
        "parser_errors",
        "legacy_payload_fallbacks",
        "reminder_delivery",
    }
)


def _raw_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return enum_value if isinstance(enum_value, str) else "other"


def _bounded(value: object, allowed: frozenset[str]) -> str:
    raw = _raw_value(value)
    return raw if raw in allowed else "other"


def _allowed_metric_keys() -> dict[str, frozenset[str]]:
    decision_keys = frozenset(
        f"intent={intent}|source={source}|outcome={outcome}"
        for intent in INTENT_VALUES | {"other"}
        for source in SOURCE_VALUES | {"other"}
        for outcome in DECISION_OUTCOMES
    )
    parser_keys = frozenset(
        f"parser={parser}|code={code}"
        for parser in PARSER_NAMES
        for code in PARSER_ERROR_CODES
    )
    reminder_keys = frozenset(
        f"event={event}|error={code}"
        for event in REMINDER_EVENTS
        for code in REMINDER_ERROR_CODES
    )
    return {
        "decisions": decision_keys,
        "rejections": REJECTION_VALUES | {"other"},
        "pending": PENDING_EVENTS,
        "actions": ACTION_RESULTS,
        "parser_errors": parser_keys,
        "legacy_payload_fallbacks": LEGACY_FAMILIES,
        "reminder_delivery": reminder_keys,
    }


ALLOWED_METRIC_KEYS = _allowed_metric_keys()


class NLUMetrics:
    def __init__(self) -> None:
        self._counts: dict[str, Counter[str]] = {
            section: Counter() for section in METRIC_SECTIONS
        }

    def _increment(self, section: str, key: str, count: int = 1) -> None:
        if key in ALLOWED_METRIC_KEYS[section] and count > 0:
            self._counts[section][key] += count

    def record_decision(
        self,
        *,
        intent: BotIntent | str,
        source: IntentSource | str,
        outcome: str,
    ) -> None:
        key = (
            f"intent={_bounded(intent, INTENT_VALUES)}|"
            f"source={_bounded(source, SOURCE_VALUES)}|"
            f"outcome={_bounded(outcome, DECISION_OUTCOMES)}"
        )
        self._increment("decisions", key)

    def record_rejection(self, code: RejectionCode | str) -> None:
        self._increment("rejections", _bounded(code, REJECTION_VALUES))

    def record_pending(self, event: str) -> None:
        self._increment("pending", _bounded(event, PENDING_EVENTS))

    def record_action_result(self, result: str) -> None:
        self._increment("actions", _bounded(result, ACTION_RESULTS))

    def record_parser_error(self, parser: str, code: str) -> None:
        key = (
            f"parser={_bounded(parser, PARSER_NAMES)}|"
            f"code={_bounded(code, PARSER_ERROR_CODES)}"
        )
        self._increment("parser_errors", key)

    def record_legacy_payload_fallback(self, family: str) -> None:
        self._increment(
            "legacy_payload_fallbacks", _bounded(family, LEGACY_FAMILIES)
        )

    def record_reminder_delivery(
        self, event: str, *, error_code: str | None = None
    ) -> None:
        key = (
            f"event={_bounded(event, REMINDER_EVENTS)}|"
            f"error={_bounded(error_code or 'none', REMINDER_ERROR_CODES)}"
        )
        self._increment("reminder_delivery", key)

    def merge_snapshot(self, delta: Mapping[str, Mapping[str, int]]) -> None:
        for section, values in delta.items():
            if section not in METRIC_SECTIONS or not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 < value <= 2**63 - 1
                ):
                    self._increment(section, key, value)

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            section: dict(sorted(self._counts[section].items()))
            for section in sorted(METRIC_SECTIONS)
            if self._counts[section]
        }
