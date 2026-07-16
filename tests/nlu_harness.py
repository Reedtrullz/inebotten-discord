"""Privacy-safe evaluation harness for production NLU parsers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Literal, Protocol, TypeAlias, cast, get_args
from zoneinfo import ZoneInfo

from cal_system.natural_language_parser import NaturalLanguageParser
from core.eval_fixtures import EvalFixture
from core.intent_router import BotIntent, IntentResult, IntentRouter
from core.message_context import (
    ConversationKey,
    ResolvedMention,
    RoutingContext,
)
from core.utterance import normalize_utterance


ParserName: TypeAlias = Literal[
    "parse_task_with_recurrence",
    "parse_event",
    "parse_countdown_query",
    "parse_poll_command",
    "parse_vote",
    "parse_watchlist_command",
    "parse_quote_command",
    "parse_price_command",
    "parse_horoscope_command",
    "parse_compliment_command",
    "parse_calculator_command",
    "parse_shorten_command",
    "detect_search_intent",
    "parse_reminder_command",
    "parse_birthday_command",
    "parse_profile_command",
]
RiskName: TypeAlias = Literal[
    "read_only",
    "additive",
    "mutating",
    "destructive",
]

PARSER_NAMES: tuple[ParserName, ...] = (
    "parse_task_with_recurrence",
    "parse_event",
    "parse_countdown_query",
    "parse_poll_command",
    "parse_vote",
    "parse_watchlist_command",
    "parse_quote_command",
    "parse_price_command",
    "parse_horoscope_command",
    "parse_compliment_command",
    "parse_calculator_command",
    "parse_shorten_command",
    "detect_search_intent",
    "parse_reminder_command",
    "parse_birthday_command",
    "parse_profile_command",
)
PARSER_NAME_VALUES = frozenset(get_args(ParserName))
EVAL_LOCALES = ("nb", "nn", "en")
CASE_KEYS = frozenset(
    {
        "id",
        "locale",
        "family",
        "text",
        "expected_intent",
        "expected_payload",
        "forbidden_intents",
        "fixture",
        "critical",
    }
)
PAYLOAD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
EVAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
EVAL_FAMILIES = frozenset(
    {
        "chat",
        "help",
        "negative",
        "calendar_create",
        "calendar_fact_check",
        "calendar_read",
        "calendar_search",
        "calendar_edit",
        "calendar_complete",
        "calendar_delete",
        "calendar_clear",
        "calendar_sync",
        "calendar_auth",
        "reminder_create",
        "reminder_read",
        "reminder_search",
        "reminder_edit",
        "reminder_complete",
        "reminder_delete",
        "poll_create",
        "poll_read",
        "poll_vote",
        "poll_edit",
        "poll_close",
        "poll_delete",
        "watchlist",
        "quote",
        "birthday",
        "weather",
        "location",
        "utility",
        "profile",
        "memory",
        "status",
        "dashboard",
        "fun",
        "search",
        "temporal",
    }
)


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    locale: Literal["nb", "nn", "en"]
    family: str
    text: str
    expected_intent: str
    expected_payload: Mapping[str, object]
    forbidden_intents: tuple[str, ...]
    fixture: EvalFixture
    critical: bool


@dataclass(frozen=True, slots=True)
class EvalResult:
    id: str
    locale: str
    family: str
    expected_intent: str
    actual_intent: str
    expected_risk: RiskName
    actual_risk: RiskName
    intent_match: bool
    payload_labeled: bool
    payload_match: bool
    forbidden_hit: bool
    parser_names: tuple[ParserName, ...]
    critical: bool

    @property
    def parser_error(self) -> bool:
        return bool(self.parser_names)


class EvaluationRouter(Protocol):
    def evaluate(
        self, text: str, *, guild_id: int | None
    ) -> tuple[IntentResult, tuple[ParserName, ...]]: ...

    def route_help_example(self, text: str) -> IntentResult: ...


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _is_json_scalar(value: object) -> bool:
    if value is None or type(value) in {str, int, bool}:
        return True
    return type(value) is float and math.isfinite(cast(float, value))


def _validate_payload_value(value: object) -> bool:
    return _is_json_scalar(value) or (
        isinstance(value, list)
        and all(_is_json_scalar(item) for item in value)
    )


def _critical_destructive_payload_is_labeled(
    expected_intent: str,
    expected_payload: Mapping[str, object],
) -> bool:
    """Require the exact action and target evidence used for precision."""

    if expected_intent == "calendar_delete":
        return any(
            path in expected_payload
            for path in ("calendar_target.number", "calendar_target.target")
        )
    if expected_intent == "calendar_clear":
        return expected_payload.get("calendar_target.all") is True
    if expected_intent == "poll_delete":
        return any(
            path in expected_payload
            for path in ("poll_delete.target", "poll_delete.poll_id")
        )
    if expected_intent == "quote_delete":
        return "quote.index" in expected_payload
    if expected_intent == "memory_delete":
        return expected_payload.get("memory.action") == "delete"
    if expected_intent == "reminder_delete":
        return (
            expected_payload.get("reminder.action") == "delete"
            and any(
                path in expected_payload
                for path in ("reminder.number", "reminder.reminder_id")
            )
        )
    if (
        expected_intent == "watchlist"
        and expected_payload.get("watchlist.action") == "remove"
    ):
        return any(
            path in expected_payload
            for path in ("watchlist.index", "watchlist.title")
        )
    if expected_intent in DESTRUCTIVE:
        return False
    return True


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    """Load and strictly validate the finite JSONL evaluation contract."""

    valid_intents = {intent.value for intent in BotIntent}
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            decoded = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        if not isinstance(decoded, dict):
            raise ValueError("eval case must be an object")
        if set(decoded) != CASE_KEYS:
            raise ValueError("eval case keys must exactly match the contract")

        case_id = decoded["id"]
        if (
            not isinstance(case_id, str)
            or EVAL_ID_RE.fullmatch(case_id) is None
        ):
            raise ValueError("invalid eval id")
        if case_id in seen_ids:
            raise ValueError(f"duplicate eval id: {case_id}")

        locale = decoded["locale"]
        if locale not in EVAL_LOCALES:
            raise ValueError("invalid locale")
        family = decoded["family"]
        if not isinstance(family, str) or family not in EVAL_FAMILIES:
            raise ValueError("unknown eval family")
        text = decoded["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a nonblank string")
        if type(decoded["critical"]) is not bool:
            raise ValueError("critical must be a boolean")

        expected_intent = decoded["expected_intent"]
        if (
            not isinstance(expected_intent, str)
            or expected_intent not in valid_intents
        ):
            raise ValueError("unknown expected intent")
        forbidden = decoded["forbidden_intents"]
        if not isinstance(forbidden, list) or not all(
            isinstance(item, str) for item in forbidden
        ):
            raise ValueError("forbidden_intents must be a list of strings")
        if any(item not in valid_intents for item in forbidden):
            raise ValueError("unknown forbidden intent")
        if expected_intent in forbidden:
            raise ValueError("expected intent cannot be forbidden")

        expected_payload = decoded["expected_payload"]
        if not isinstance(expected_payload, dict):
            raise ValueError("expected_payload must be an object")
        for payload_path, value in expected_payload.items():
            if (
                not isinstance(payload_path, str)
                or PAYLOAD_PATH.fullmatch(payload_path) is None
            ):
                raise ValueError("invalid payload path")
            if not _validate_payload_value(value):
                raise ValueError(
                    "payload values must be JSON scalars or flat scalar lists"
                )

        if expected_intent == "watchlist":
            action = expected_payload.get("watchlist.action")
            if not isinstance(action, str) or action not in {
                "status",
                "list",
                "suggest",
                "add",
                "edit",
                "remove",
            }:
                raise ValueError("invalid watchlist.action")
        if expected_intent == "quote":
            action = expected_payload.get("quote.action")
            if not isinstance(action, str) or action not in {"get", "save"}:
                raise ValueError("invalid quote.action")
        if decoded["critical"] and not _critical_destructive_payload_is_labeled(
            expected_intent,
            expected_payload,
        ):
            raise ValueError(
                "critical destructive case requires action and target payload"
            )

        try:
            fixture = EvalFixture(decoded["fixture"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown fixture") from exc

        case = EvalCase(
            id=case_id,
            locale=locale,
            family=family,
            text=text,
            expected_intent=expected_intent,
            expected_payload=expected_payload,
            forbidden_intents=tuple(forbidden),
            fixture=fixture,
            critical=decoded["critical"],
        )
        seen_ids.add(case.id)
        cases.append(case)

    return tuple(cases)


READ_ONLY = frozenset(
    {
        "help",
        "status",
        "calendar_help",
        "calendar_list",
        "calendar_search",
        "calendar_fact_check",
        "poll_list",
        "countdown",
        "word_of_day",
        "quote_list",
        "aurora",
        "school_holidays",
        "price",
        "horoscope",
        "compliment",
        "calculator",
        "shorten_url",
        "daily_digest",
        "search",
        "dashboard",
        "memory_view",
        "memory_export",
        "reminder_search",
        "reminder_list",
        "birthday_list",
        "clarify",
        "action_confirm",
        "action_cancel",
        "action_select",
        "action_correct",
        "ai_chat",
    }
)
ADDITIVE = frozenset(
    {"calendar_item", "poll_create", "reminder_create", "birthday_create"}
)
MUTATING = frozenset(
    {
        "profile",
        "calendar_sync",
        "calendar_complete",
        "calendar_edit",
        "poll_vote",
        "poll_edit",
        "poll_close",
        "quote_edit",
        "set_location",
        "birthday_edit",
        "reminder_edit",
        "reminder_complete",
        "calendar_auth",
    }
)
DESTRUCTIVE = frozenset(
    {
        "calendar_delete",
        "calendar_clear",
        "poll_delete",
        "quote_delete",
        "memory_delete",
        "reminder_delete",
    }
)
WATCHLIST_ACTION_RISK: dict[str, RiskName] = {
    "status": "read_only",
    "list": "read_only",
    "suggest": "read_only",
    "add": "additive",
    "edit": "mutating",
    "remove": "destructive",
}
QUOTE_ACTION_RISK: dict[str, RiskName] = {
    "get": "read_only",
    "save": "additive",
}


def nested_string(
    payload: Mapping[str, object], envelope: str, key: str
) -> str:
    nested = payload.get(envelope)
    if not isinstance(nested, Mapping):
        return ""
    value = nested.get(key)
    return value.casefold().strip() if isinstance(value, str) else ""


def classify_eval_risk(intent: str, payload: Mapping[str, object]) -> RiskName:
    if intent == "watchlist":
        return WATCHLIST_ACTION_RISK.get(
            nested_string(payload, "watchlist", "action"), "destructive"
        )
    if intent == "quote":
        return QUOTE_ACTION_RISK.get(
            nested_string(payload, "quote", "action"), "destructive"
        )
    for values, risk in (
        (READ_ONLY, "read_only"),
        (ADDITIVE, "additive"),
        (MUTATING, "mutating"),
        (DESTRUCTIVE, "destructive"),
    ):
        if intent in values:
            return cast(RiskName, risk)
    raise AssertionError(f"unclassified eval intent: {intent}")


def classify_expected_eval_risk(case: EvalCase) -> RiskName:
    if case.expected_intent in {"watchlist", "quote"}:
        action = case.expected_payload[f"{case.expected_intent}.action"]
        payload: Mapping[str, object] = {
            case.expected_intent: {"action": action}
        }
    else:
        payload = {}
    return classify_eval_risk(case.expected_intent, payload)


class ParserProbe:
    def __init__(self) -> None:
        self._names: list[ParserName] = []

    def call(
        self, name: ParserName, fn: Callable[..., object], *args: object
    ) -> object | None:
        try:
            return fn(*args)
        except Exception:
            self._names.append(name)
            return None

    def wrap(
        self, name: ParserName, fn: Callable[..., object]
    ) -> Callable[..., object | None]:
        return lambda *args: self.call(name, fn, *args)

    def reset(self) -> None:
        self._names.clear()

    def snapshot(self) -> tuple[ParserName, ...]:
        return tuple(dict.fromkeys(self._names))


_HELP_REFERENCE_TIME = datetime(
    2026,
    7,
    14,
    12,
    0,
    tzinfo=ZoneInfo("Europe/Oslo"),
)


class ProductionRouterAdapter:
    def __init__(self, monitor: object) -> None:
        self._router = IntentRouter(
            monitor,
            now_provider=lambda captured=_HELP_REFERENCE_TIME: captured,
        )
        self._routing_context = RoutingContext(
            key=ConversationKey(
                guild_id=monitor.guild_id,
                channel_id=monitor.channel_id,
                user_id=monitor.author_id,
            ),
            author=ResolvedMention(monitor.author_id, monitor.author_name),
            mentions=tuple(
                ResolvedMention(user_id, display_name)
                for user_id, display_name in monitor.resolved_mentions.items()
            ),
        )

    def evaluate(
        self, text: str, *, guild_id: int | None
    ) -> tuple[IntentResult, tuple[ParserName, ...]]:
        use_context = guild_id == self._routing_context.key.guild_id
        routed = self._router.evaluate_utterance(
            normalize_utterance(text),
            guild_id=guild_id,
            channel_id=(
                self._routing_context.key.channel_id if use_context else None
            ),
            user_id=(
                self._routing_context.key.user_id if use_context else None
            ),
            routing_context=self._routing_context if use_context else None,
            reference_time=_HELP_REFERENCE_TIME,
        )
        parser_names = tuple(
            name
            for name in routed.diagnostics.parser_errors
            if name in PARSER_NAME_VALUES
        )
        return routed.result, parser_names

    def route_help_example(self, text: str) -> IntentResult:
        return self._router.route_utterance(
            normalize_utterance(text),
            guild_id=self._routing_context.key.guild_id,
            channel_id=self._routing_context.key.channel_id,
            user_id=self._routing_context.key.user_id,
            routing_context=self._routing_context,
            reference_time=_HELP_REFERENCE_TIME,
        )


def build_production_router(fixture: EvalFixture) -> EvaluationRouter:
    """Build a file-free adapter around the production router and parsers."""

    from cal_system.reminder_manager import parse_reminder_command
    from features.birthday_manager import parse_birthday_command
    from features.calculator_manager import parse_calculator_command
    from features.compliments_manager import parse_compliment_command
    from features.countdown_manager import CountdownManager
    from features.crypto_manager import parse_price_command
    from features.horoscope_manager import parse_horoscope_command
    from features.poll_manager import parse_poll_command, parse_vote
    from features.profile_commands import parse_profile_command
    from features.quote_manager import parse_quote_command
    from features.search_manager import detect_search_intent
    from features.url_shortener import parse_shorten_command
    from features.watchlist_manager import parse_watchlist_command
    from memory.conversation_context import ConversationContext

    nlp_parser = NaturalLanguageParser()
    countdown = CountdownManager()

    calendar_record = {
        "id": "calendar-1",
        "title": "Møte med Ola",
        "date": "15.07.2026",
        "time": "10:00",
    }
    reminder_record = {
        "id": "reminder-1",
        "title": "Ring legen",
        "completed": False,
    }
    poll_record = {"id": "poll-1", "status": "active", "question": "Pizza?"}

    calendar_rows = (
        [calendar_record]
        if fixture
        in {EvalFixture.CALENDAR_TITLE_MEETING, EvalFixture.MIXED_STATE}
        else []
    )
    reminder_rows = (
        [reminder_record]
        if fixture in {EvalFixture.ACTIVE_REMINDER, EvalFixture.MIXED_STATE}
        else []
    )
    poll_rows = (
        [poll_record]
        if fixture in {EvalFixture.ACTIVE_POLL, EvalFixture.MIXED_STATE}
        else []
    )
    resolved_mentions = (
        {42: "Ola"}
        if fixture in {EvalFixture.MENTIONED_USER_42, EvalFixture.MIXED_STATE}
        else {}
    )

    monitor = SimpleNamespace(
        nlp_parser=nlp_parser,
        countdown=countdown,
        parse_poll_command=parse_poll_command,
        parse_vote=parse_vote,
        parse_watchlist_command=parse_watchlist_command,
        parse_quote_command=parse_quote_command,
        parse_price_command=parse_price_command,
        parse_horoscope_command=parse_horoscope_command,
        parse_compliment_command=parse_compliment_command,
        parse_calculator_command=parse_calculator_command,
        parse_shorten_command=parse_shorten_command,
        detect_search_intent=detect_search_intent,
        parse_reminder_command=parse_reminder_command,
        parse_birthday_command=parse_birthday_command,
        parse_profile_command=parse_profile_command,
        conversation=ConversationContext(),
        calendar=SimpleNamespace(
            get_upcoming=lambda guild_id, days=365, reference_time=None: list(
                calendar_rows
            )
        ),
        reminders=SimpleNamespace(
            get_active_reminders=lambda guild_id: list(reminder_rows)
        ),
        poll=SimpleNamespace(
            get_active_polls=lambda guild_id, reference_time=None: list(
                poll_rows
            )
        ),
        guild_id=123,
        channel_id=456,
        author_id=7,
        author_name="Kari",
        resolved_mentions=resolved_mentions,
    )
    return ProductionRouterAdapter(monitor)


def dotted_payload_matches(
    payload: Mapping[str, object], labels: Mapping[str, object]
) -> bool:
    for path, expected in labels.items():
        current: object = payload
        for segment in path.split("."):
            if not isinstance(current, Mapping) or segment not in current:
                return False
            current = current[segment]
        if current != expected:
            return False
    return True


def evaluate_case(
    case: EvalCase, router: EvaluationRouter, guild_id: int | None = 123
) -> EvalResult:
    result, parser_names = router.evaluate(case.text, guild_id=guild_id)
    actual_intent = result.intent.value
    payload_labeled = bool(case.expected_payload)
    return EvalResult(
        id=case.id,
        locale=case.locale,
        family=case.family,
        expected_intent=case.expected_intent,
        actual_intent=actual_intent,
        expected_risk=classify_expected_eval_risk(case),
        actual_risk=classify_eval_risk(actual_intent, result.payload),
        intent_match=actual_intent == case.expected_intent,
        payload_labeled=payload_labeled,
        payload_match=(
            dotted_payload_matches(result.payload, case.expected_payload)
            if payload_labeled
            else True
        ),
        forbidden_hit=actual_intent in case.forbidden_intents,
        parser_names=tuple(dict.fromkeys(parser_names)),
        critical=case.critical,
    )


def _metric(numerator: int, denominator: int) -> dict[str, int | float | bool]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else 0.0,
        "defined": bool(denominator),
    }


def aggregate_intent_report(
    results: tuple[EvalResult, ...] | list[EvalResult],
) -> dict[str, object]:
    """Aggregate exact metrics into the stable privacy-safe report schema."""

    rows = tuple(results)
    labeled = tuple(result for result in rows if result.payload_labeled)
    negative = tuple(result for result in rows if result.family == "negative")
    critical_actions = tuple(
        result
        for result in rows
        if result.critical
        and result.expected_intent not in {"ai_chat", "clarify"}
    )
    actual_destructive = tuple(
        result for result in rows if result.actual_risk == "destructive"
    )

    exact_count = sum(result.intent_match for result in rows)
    labeled_match_count = sum(result.payload_match for result in labeled)
    parser_error_count = sum(result.parser_error for result in rows)
    negative_false_positive_count = sum(
        result.actual_risk != "read_only" for result in negative
    )
    critical_recall_count = sum(
        result.intent_match for result in critical_actions
    )
    destructive_precision_count = sum(
        result.expected_risk == "destructive"
        and result.intent_match
        and result.payload_labeled
        and result.payload_match
        for result in actual_destructive
    )

    by_locale = {
        locale: _metric(
            sum(
                result.intent_match
                for result in rows
                if result.locale == locale
            ),
            sum(result.locale == locale for result in rows),
        )
        for locale in EVAL_LOCALES
    }
    by_family = {
        family: _metric(
            sum(
                result.intent_match
                for result in rows
                if result.family == family
            ),
            sum(result.family == family for result in rows),
        )
        for family in sorted(EVAL_FAMILIES)
    }
    parser_counts = Counter(
        parser_name for result in rows for parser_name in result.parser_names
    )

    public_cases = [
        {
            "id": sha256(result.id.encode("utf-8")).hexdigest()[:16],
            "expected_intent": result.expected_intent,
            "actual_intent": result.actual_intent,
            "expected_risk": result.expected_risk,
            "actual_risk": result.actual_risk,
            "intent_match": result.intent_match,
            "payload_labeled": result.payload_labeled,
            "payload_match": result.payload_match,
            "forbidden_hit": result.forbidden_hit,
            "parser_names": list(result.parser_names),
            "critical": result.critical,
        }
        for result in rows
    ]

    return {
        "schema_version": 1,
        "totals": {
            "cases": len(rows),
            "intent_matches": exact_count,
            "payload_labeled": len(labeled),
            "payload_matches": labeled_match_count,
            "parser_errors": parser_error_count,
            "negative_cases": len(negative),
            "critical_action_cases": len(critical_actions),
            "actual_destructive_cases": len(actual_destructive),
        },
        "metrics": {
            "overall_exact_intent_accuracy": _metric(exact_count, len(rows)),
            "labeled_payload_accuracy": _metric(
                labeled_match_count, len(labeled)
            ),
            "parser_error_rate": _metric(parser_error_count, len(rows)),
            "negative_mutation_false_positive_rate": _metric(
                negative_false_positive_count, len(negative)
            ),
            "critical_action_recall": _metric(
                critical_recall_count, len(critical_actions)
            ),
            "destructive_action_precision": _metric(
                destructive_precision_count, len(actual_destructive)
            ),
        },
        "by_locale": by_locale,
        "by_family": by_family,
        "parser_errors_by_name": {
            name: parser_counts[name]
            for name in PARSER_NAMES
            if parser_counts[name]
        },
        "cases": public_cases,
    }
