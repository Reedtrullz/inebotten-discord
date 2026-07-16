"""Canonical typed action payloads and fail-closed boundary validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
import re
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict, TypeVar

from cal_system.temporal_resolver import OSLO, TemporalResolver
from core.intent_models import BotIntent, IntentSource


class CalendarCreatePayload(TypedDict):
    title: str
    date: NotRequired[str]
    time: NotRequired[str]
    type: NotRequired[Literal["event", "task"]]
    recurrence: NotRequired[str]
    recurrence_day: NotRequired[str]
    rrule_day: NotRequired[str]
    days_offset: NotRequired[int | None]
    description: NotRequired[str]


class CalendarChanges(TypedDict, total=False):
    title: str
    description: str
    date: str
    time: str
    type: Literal["event", "task"]
    recurrence: str | None


class CalendarTargetPayload(TypedDict, total=False):
    target: str
    number: int
    all: bool


class CalendarListPayload(TypedDict, total=False):
    date: str


class CalendarEditPayload(TypedDict):
    target: str
    changes: CalendarChanges


class ReminderCreatePayload(TypedDict):
    action: Literal["add"]
    text: str
    due_at: NotRequired[str]
    due_date: NotRequired[str]
    time: NotRequired[str]
    timezone: NotRequired[str]
    recurrence: NotRequired[str]


class ReminderTargetPayload(TypedDict):
    action: Literal["list", "search", "complete", "delete"]
    number: NotRequired[int]
    reminder_id: NotRequired[str]
    query: NotRequired[str]
    due_date: NotRequired[str]


class ReminderChanges(TypedDict, total=False):
    text: str
    due_at: str | None
    due_date: str | None
    time: str | None
    timezone: str
    recurrence: str | None


class ReminderEditPayload(TypedDict):
    action: Literal["edit"]
    number: NotRequired[int]
    reminder_id: NotRequired[str]
    changes: ReminderChanges


class PollCreatePayload(TypedDict):
    question: str
    options: list[str]
    lang: NotRequired[Literal["no", "en"]]


class PollTargetPayload(TypedDict, total=False):
    target: int | Literal["siste"] | None
    poll_id: NotRequired[str]


class PollEditPayload(TypedDict, total=False):
    target: int | Literal["siste"] | None
    poll_id: str
    question: NotRequired[str]
    options: NotRequired[list[str]]


class PollVotePayload(TypedDict):
    option: int
    poll_id: NotRequired[str]


class BirthdayCreatePayload(TypedDict):
    action: Literal["add"]
    user_id: int
    display_name: str
    day: int
    month: int
    year: NotRequired[int]


class BirthdayEditPayload(TypedDict):
    action: Literal["edit"]
    user_id: int
    day: int
    month: int
    year: NotRequired[int]


class BirthdayListPayload(TypedDict):
    action: Literal["list"]
    scope: NotRequired[Literal["all", "upcoming"]]


class WatchlistPayload(TypedDict):
    action: Literal["add", "status", "suggest", "edit", "remove"]
    title: NotRequired[str]
    type: NotRequired[Literal["movie", "series"] | None]
    index: NotRequired[int]
    genre: NotRequired[str | None]
    comment: NotRequired[str | None]
    lang: NotRequired[Literal["no", "en"]]


class QuotePayload(TypedDict):
    action: Literal["save", "get", "list", "edit", "delete"]
    index: NotRequired[int]
    text: NotRequired[str]
    author: NotRequired[str]
    lang: NotRequired[Literal["no", "en"]]


class MemoryPayload(TypedDict):
    action: Literal["view", "export", "delete"]


class ProfilePayload(TypedDict):
    action: Literal["status", "playing", "watching"]
    value: str


PayloadValue: TypeAlias = (
    CalendarCreatePayload
    | CalendarListPayload
    | CalendarEditPayload
    | CalendarTargetPayload
    | ReminderCreatePayload
    | ReminderTargetPayload
    | ReminderEditPayload
    | PollCreatePayload
    | PollTargetPayload
    | PollEditPayload
    | PollVotePayload
    | BirthdayCreatePayload
    | BirthdayEditPayload
    | BirthdayListPayload
    | WatchlistPayload
    | QuotePayload
    | MemoryPayload
    | ProfilePayload
)


class PayloadValidationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_PAYLOAD_ERROR_CODES = frozenset(
    {
        "missing_payload",
        "unknown_key",
        "wrong_action",
        "missing_target",
        "ambiguous_target",
        "missing_change",
        "blank_value",
        "invalid_number",
        "invalid_date",
        "invalid_time",
        "ambiguous_time",
        "missing_date",
        "invalid_due_at",
        "invalid_timezone",
        "invalid_recurrence",
        "invalid_options",
        "value_too_long",
        "unsupported_intent",
        "unsupported_temporal_field",
    }
)
_RECURRENCES = frozenset({"daily", "weekly", "biweekly", "monthly", "yearly"})
_RECURRENCE_DAY_CODES = {
    "mo": "MO",
    "mon": "MO",
    "monday": "MO",
    "mandag": "MO",
    "man": "MO",
    "mån": "MO",
    "måndag": "MO",
    "tu": "TU",
    "tue": "TU",
    "tues": "TU",
    "tuesday": "TU",
    "tir": "TU",
    "tirsdag": "TU",
    "tysdag": "TU",
    "we": "WE",
    "wed": "WE",
    "weds": "WE",
    "wednesday": "WE",
    "ons": "WE",
    "onsdag": "WE",
    "th": "TH",
    "thu": "TH",
    "thur": "TH",
    "thurs": "TH",
    "thursday": "TH",
    "tor": "TH",
    "torsdag": "TH",
    "fr": "FR",
    "fri": "FR",
    "friday": "FR",
    "fre": "FR",
    "fredag": "FR",
    "sa": "SA",
    "sat": "SA",
    "saturday": "SA",
    "lør": "SA",
    "lørdag": "SA",
    "lau": "SA",
    "laurdag": "SA",
    "su": "SU",
    "sun": "SU",
    "sunday": "SU",
    "søn": "SU",
    "søndag": "SU",
    "sundag": "SU",
}
_MISSING = object()
_ABSOLUTE_DATE = re.compile(
    r"\s*(?P<day>\d{1,2})[./](?P<month>\d{1,2})"
    r"[./](?P<year>\d{4})\s*"
)
_TEMPORAL_RESOLVER = TemporalResolver(
    now_provider=lambda: (_ for _ in ()).throw(RuntimeError("wall_clock_forbidden"))
)


def _fail(code: str) -> None:
    if code not in _PAYLOAD_ERROR_CODES:
        raise RuntimeError("unbounded_payload_error")
    raise PayloadValidationError(code)


def _mapping(raw: object, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        _fail("missing_payload")
    value = dict(raw)
    if set(value) - allowed:
        _fail("unknown_key")
    return value


def _string(value: object, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        _fail("blank_value")
    normalized = value.strip()
    if not normalized:
        _fail("blank_value")
    return normalized


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail("invalid_number")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("invalid_number")
    return value


def _language(value: object) -> Literal["no", "en"]:
    if not isinstance(value, str) or value not in {"no", "en"}:
        _fail("wrong_action")
    return value  # type: ignore[return-value]


def _recurrence(value: object, *, allow_none: bool) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        _fail("invalid_recurrence")
    normalized = value.strip()
    if normalized not in _RECURRENCES:
        _fail("invalid_recurrence")
    return normalized


def canonical_recurrence_day_code(value: object) -> str | None:
    """Return one weekday code for known Norwegian/English aliases."""

    if not isinstance(value, str):
        return None
    return _RECURRENCE_DAY_CODES.get(value.strip().casefold())


def calendar_date_weekday_code(value: str) -> str:
    """Return the canonical weekday code for one validated calendar date."""

    weekday = datetime.strptime(value, "%d.%m.%Y").weekday()
    return ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[weekday]


def _reference_for_date(value: object) -> datetime:
    if not isinstance(value, str):
        _fail("invalid_date")
    match = _ABSOLUTE_DATE.fullmatch(value)
    if match is None:
        _fail("invalid_date")
    try:
        return datetime(int(match.group("year")), 1, 1, 12, tzinfo=OSLO)
    except (OverflowError, ValueError):
        _fail("invalid_date")


def _date_time(
    date_value: object,
    time_value: object = _MISSING,
) -> tuple[str, str | None]:
    if not isinstance(date_value, str):
        _fail("invalid_date")
    normalized_time: str | None = None
    if time_value is not _MISSING:
        if not isinstance(time_value, str):
            _fail("invalid_time")
        normalized_time = time_value.strip()
    result = _TEMPORAL_RESOLVER.validate_fields(
        date_value.strip(),
        normalized_time,
        reference=_reference_for_date(date_value),
    )
    if result.errors:
        _fail(result.errors[0])
    if result.date is None:
        _fail("invalid_date")
    return result.date, result.time


def _time(value: object) -> str:
    if not isinstance(value, str):
        _fail("invalid_time")
    normalized = _TEMPORAL_RESOLVER.validate_time(value.strip())
    if normalized is None:
        _fail("invalid_time")
    return normalized


def _due_at(value: object) -> datetime:
    if not isinstance(value, str):
        _fail("invalid_due_at")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        _fail("invalid_due_at")
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
        _fail("invalid_due_at")
    return parsed.astimezone(OSLO)


def _normalize_temporal(
    raw: Mapping[str, Any],
    *,
    allow_partial: bool,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    has_due_at = "due_at" in raw
    has_date = "due_date" in raw
    has_time = "time" in raw
    has_timezone = "timezone" in raw

    if has_timezone:
        timezone_value = raw["timezone"]
        if timezone_value != "Europe/Oslo":
            _fail("invalid_timezone")
        normalized["timezone"] = "Europe/Oslo"

    if has_due_at and raw["due_at"] is None:
        if not allow_partial:
            _fail("invalid_due_at")
        if (has_date and raw["due_date"] is not None) or (
            has_time and raw["time"] is not None
        ):
            _fail("invalid_due_at")
        normalized["due_at"] = None
        if has_date:
            normalized["due_date"] = None
        if has_time:
            normalized["time"] = None
        return normalized

    if has_due_at:
        local = _due_at(raw["due_at"])
        derived_date = local.strftime("%d.%m.%Y")
        derived_time = local.strftime("%H:%M")
        if has_date:
            if raw["due_date"] is None:
                _fail("invalid_due_at")
            canonical_date, _ = _date_time(raw["due_date"])
            if canonical_date != derived_date:
                _fail("invalid_due_at")
        if has_time:
            if raw["time"] is None or _time(raw["time"]) != derived_time:
                _fail("invalid_due_at")
        normalized.update(
            {
                "due_at": local.isoformat(timespec="seconds"),
                "due_date": derived_date,
                "time": derived_time,
                "timezone": "Europe/Oslo",
            }
        )
        return normalized

    if has_date:
        if raw["due_date"] is None:
            if not allow_partial:
                _fail("invalid_date")
            if has_time and raw["time"] is not None:
                _fail("missing_date")
            normalized["due_date"] = None
            if has_time:
                normalized["time"] = None
            return normalized
        canonical_date, canonical_time = _date_time(
            raw["due_date"], raw["time"] if has_time else _MISSING
        )
        normalized["due_date"] = canonical_date
        if has_time:
            normalized["time"] = canonical_time
        return normalized

    if has_time:
        if raw["time"] is None:
            if allow_partial:
                normalized["time"] = None
                return normalized
            _fail("invalid_time")
        if not allow_partial:
            _fail("missing_date")
        normalized["time"] = _time(raw["time"])
    return normalized


def _calendar_create(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(
        raw,
        frozenset(
            {
                "title",
                "date",
                "time",
                "type",
                "recurrence",
                "recurrence_day",
                "rrule_day",
                "days_offset",
                "description",
            }
        ),
    )
    if "title" not in value:
        _fail("blank_value")
    result: dict[str, Any] = {"title": _string(value["title"])}
    has_offset = "days_offset" in value and value["days_offset"] is not None
    if "days_offset" in value:
        offset = value["days_offset"]
        result["days_offset"] = None if offset is None else _integer(offset)
    if "date" not in value and not has_offset:
        _fail("missing_date")
    if "date" in value:
        date_value, time_value = _date_time(
            value["date"], value["time"] if "time" in value else _MISSING
        )
        result["date"] = date_value
        if "time" in value:
            result["time"] = time_value
    elif "time" in value:
        result["time"] = _time(value["time"])
    if "type" in value:
        if not isinstance(value["type"], str) or value["type"] not in {
            "event",
            "task",
        }:
            _fail("wrong_action")
        result["type"] = value["type"]
    if "recurrence" in value:
        result["recurrence"] = _recurrence(value["recurrence"], allow_none=False)
    recurrence_codes: dict[str, str] = {}
    for key in ("recurrence_day", "rrule_day"):
        if key not in value:
            continue
        day = _string(value[key])
        code = canonical_recurrence_day_code(day)
        if code is None:
            _fail("invalid_recurrence")
        recurrence_codes[key] = code
        result[key] = code if key == "rrule_day" else day
    if recurrence_codes and result.get("recurrence") not in {
        "weekly",
        "biweekly",
    }:
        _fail("invalid_recurrence")
    if len(set(recurrence_codes.values())) > 1:
        _fail("invalid_recurrence")
    if recurrence_codes and "date" in result:
        if calendar_date_weekday_code(result["date"]) != next(
            iter(recurrence_codes.values())
        ):
            _fail("invalid_recurrence")
    if "recurrence_day" in recurrence_codes:
        result["rrule_day"] = recurrence_codes["recurrence_day"]
    if "description" in value:
        result["description"] = _string(value["description"])
    return result


def _calendar_target(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource,
) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"target", "number", "all"}))
    result: dict[str, Any] = {}
    selectors = 0
    if "target" in value:
        result["target"] = _string(value["target"])
        selectors += 1
    if "number" in value:
        result["number"] = _positive_int(value["number"])
        selectors += 1
    if "all" in value:
        if not isinstance(value["all"], bool):
            _fail("invalid_number")
        if value["all"]:
            if intent is not BotIntent.CALENDAR_CLEAR:
                _fail("wrong_action")
            result["all"] = True
            selectors += 1
    if selectors == 0:
        _fail("missing_target")
    if selectors > 1:
        _fail("ambiguous_target")
    return result


def _calendar_edit(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"target", "changes"}))
    if "target" not in value:
        _fail("missing_target")
    target = _string(value["target"])
    if "changes" not in value:
        _fail("missing_change")
    changes = _mapping(
        value["changes"],
        frozenset({"title", "description", "date", "time", "type", "recurrence"}),
    )
    if not changes:
        _fail("missing_change")
    result_changes: dict[str, Any] = {}
    for key in ("title", "description"):
        if key in changes:
            result_changes[key] = _string(changes[key])
    if "type" in changes:
        if not isinstance(changes["type"], str) or changes["type"] not in {
            "event",
            "task",
        }:
            _fail("wrong_action")
        result_changes["type"] = changes["type"]
    if "date" in changes:
        canonical_date, canonical_time = _date_time(
            changes["date"], changes["time"] if "time" in changes else _MISSING
        )
        result_changes["date"] = canonical_date
        if "time" in changes:
            result_changes["time"] = canonical_time
    elif "time" in changes:
        result_changes["time"] = _time(changes["time"])
    if "recurrence" in changes:
        result_changes["recurrence"] = _recurrence(
            changes["recurrence"], allow_none=True
        )
    return {"target": target, "changes": result_changes}


def _reminder_create(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(
        raw,
        frozenset({"action", "text", "due_at", "due_date", "time", "timezone", "recurrence"}),
    )
    if value.get("action") != "add":
        _fail("wrong_action")
    if "text" not in value:
        _fail("blank_value")
    result: dict[str, Any] = {"action": "add", "text": _string(value["text"])}
    temporal = _normalize_temporal(value, allow_partial=False)
    result.update(temporal)
    if "recurrence" in value:
        result["recurrence"] = _recurrence(value["recurrence"], allow_none=False)
        if "due_at" not in result and result.get("due_date") is None:
            _fail("invalid_recurrence")
    return result


_REMINDER_ACTIONS = {
    BotIntent.REMINDER_LIST: "list",
    BotIntent.REMINDER_SEARCH: "search",
    BotIntent.REMINDER_COMPLETE: "complete",
    BotIntent.REMINDER_DELETE: "delete",
}


def _reminder_target(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource,
) -> dict[str, Any]:
    value = _mapping(
        raw,
        frozenset({"action", "number", "reminder_id", "query", "due_date"}),
    )
    expected = _REMINDER_ACTIONS[intent]
    if value.get("action") != expected:
        _fail("wrong_action")
    result: dict[str, Any] = {"action": expected}
    selector_count = 0
    if "number" in value:
        result["number"] = _positive_int(value["number"])
        selector_count += 1
    if "reminder_id" in value:
        result["reminder_id"] = _string(value["reminder_id"])
        selector_count += 1
    if expected == "list":
        if selector_count or "query" in value:
            _fail("ambiguous_target")
        if "due_date" in value:
            canonical_date, _ = _date_time(value["due_date"])
            result["due_date"] = canonical_date
        return result
    if "due_date" in value:
        _fail("wrong_action")
    if expected == "search":
        if selector_count:
            _fail("ambiguous_target")
        if "query" not in value:
            _fail("missing_target")
        result["query"] = _string(value["query"])
        return result
    if "query" in value:
        _fail("ambiguous_target")
    if selector_count == 0:
        _fail("missing_target")
    if selector_count > 1:
        _fail("ambiguous_target")
    return result


def _reminder_edit(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"action", "number", "reminder_id", "changes"}))
    if value.get("action") != "edit":
        _fail("wrong_action")
    result: dict[str, Any] = {"action": "edit"}
    selectors = 0
    if "number" in value:
        result["number"] = _positive_int(value["number"])
        selectors += 1
    if "reminder_id" in value:
        result["reminder_id"] = _string(value["reminder_id"])
        selectors += 1
    if selectors == 0:
        _fail("missing_target")
    if selectors > 1:
        _fail("ambiguous_target")
    if "changes" not in value:
        _fail("missing_change")
    changes = _mapping(
        value["changes"],
        frozenset({"text", "due_at", "due_date", "time", "timezone", "recurrence"}),
    )
    if not changes:
        _fail("missing_change")
    if not any(
        key in changes
        for key in ("text", "due_at", "due_date", "time", "recurrence")
    ):
        # Europe/Oslo is the only accepted label, so repeating it alone cannot
        # change a canonical reminder.
        _fail("missing_change")
    normalized: dict[str, Any] = {}
    if "text" in changes:
        normalized["text"] = _string(changes["text"])
    normalized.update(_normalize_temporal(changes, allow_partial=True))
    if "recurrence" in changes:
        normalized["recurrence"] = _recurrence(changes["recurrence"], allow_none=True)
    clears_timing = any(
        key in changes and changes[key] is None for key in ("due_at", "due_date")
    )
    if clears_timing and normalized.get("recurrence") is not None and "recurrence" in normalized:
        _fail("invalid_recurrence")
    return {**result, "changes": normalized}


def _options(value: object) -> list[str]:
    if not isinstance(value, list) or not 2 <= len(value) <= 10:
        _fail("invalid_options")
    normalized = [_string(option) for option in value]
    if any(len(option) > 100 for option in normalized):  # type: ignore[arg-type]
        _fail("value_too_long")
    folded = [option.casefold() for option in normalized]  # type: ignore[union-attr]
    if len(set(folded)) != len(folded):
        _fail("invalid_options")
    return normalized  # type: ignore[return-value]


def _poll_create(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"question", "options", "lang"}))
    if "question" not in value:
        _fail("blank_value")
    question = _string(value["question"])
    if len(question) > 300:  # type: ignore[arg-type]
        _fail("value_too_long")
    if "options" not in value:
        _fail("invalid_options")
    result: dict[str, Any] = {"question": question, "options": _options(value["options"])}
    if "lang" in value:
        result["lang"] = _language(value["lang"])
    return result


def _poll_selector(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    selectors = 0
    if "target" in value and value["target"] is not None:
        target = value["target"]
        if target == "siste":
            result["target"] = "siste"
        else:
            result["target"] = _positive_int(target)
        selectors += 1
    if "poll_id" in value:
        result["poll_id"] = _string(value["poll_id"])
        selectors += 1
    if selectors == 0:
        _fail("missing_target")
    if selectors > 1:
        _fail("ambiguous_target")
    return result


def _poll_target(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"target", "poll_id"}))
    return _poll_selector(value)


def _poll_edit(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"target", "poll_id", "question", "options"}))
    result = _poll_selector(value)
    changed = False
    if "question" in value:
        question = _string(value["question"])
        if len(question) > 300:  # type: ignore[arg-type]
            _fail("value_too_long")
        result["question"] = question
        changed = True
    if "options" in value:
        result["options"] = _options(value["options"])
        changed = True
    if not changed:
        _fail("missing_change")
    return result


def _poll_vote(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"option", "poll_id"}))
    if "option" not in value:
        _fail("invalid_number")
    result: dict[str, Any] = {"option": _positive_int(value["option"])}
    if "poll_id" in value:
        result["poll_id"] = _string(value["poll_id"])
    return result


def _birthday_date(value: Mapping[str, Any]) -> tuple[int, int, int | None]:
    if "day" not in value or "month" not in value:
        _fail("invalid_date")
    day = _positive_int(value["day"])
    month = _positive_int(value["month"])
    year: int | None = None
    if "year" in value:
        year = _integer(value["year"])
        if not 1900 <= year <= 2100:
            _fail("invalid_date")
    try:
        date(year or 2000, month, day)
    except (OverflowError, ValueError):
        _fail("invalid_date")
    return day, month, year


def _birthday(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource,
) -> dict[str, Any]:
    if intent is BotIntent.BIRTHDAY_LIST:
        value = _mapping(raw, frozenset({"action", "scope"}))
        if value.get("action") != "list":
            _fail("wrong_action")
        scope = value.get("scope", "all")
        if not isinstance(scope, str) or scope not in {
            "all",
            "upcoming",
            "self",
        }:
            _fail("wrong_action")
        return {"action": "list", "scope": scope}
    allowed = {"action", "user_id", "day", "month", "year"}
    if intent is BotIntent.BIRTHDAY_CREATE:
        allowed.add("display_name")
    value = _mapping(raw, frozenset(allowed))
    expected = "add" if intent is BotIntent.BIRTHDAY_CREATE else "edit"
    if value.get("action") != expected:
        _fail("wrong_action")
    if "user_id" not in value:
        _fail("invalid_number")
    day, month, year = _birthday_date(value)
    result: dict[str, Any] = {
        "action": expected,
        "user_id": _positive_int(value["user_id"]),
    }
    if intent is BotIntent.BIRTHDAY_CREATE:
        if "display_name" not in value:
            _fail("blank_value")
        result["display_name"] = _string(value["display_name"])
    result.update({"day": day, "month": month})
    if year is not None:
        result["year"] = year
    return result


def _profile(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    del source
    value = _mapping(raw, frozenset({"action", "value"}))
    action = value.get("action")
    if action not in {"status", "playing", "watching"}:
        _fail("wrong_action")
    normalized = _string(value.get("value"))
    if not isinstance(normalized, str):
        _fail("blank_value")
    if len(normalized) > 100:
        _fail("value_too_long")
    if action == "status":
        normalized = normalized.casefold()
        if normalized not in {"online", "offline", "idle", "dnd", "invisible"}:
            _fail("wrong_action")
    return {"action": action, "value": normalized}


def _watchlist(raw: Mapping[str, Any], *, source: IntentSource) -> dict[str, Any]:
    value = _mapping(
        raw,
        frozenset({"action", "title", "type", "index", "genre", "comment", "lang"}),
    )
    action = value.get("action")
    if not isinstance(action, str) or action not in {
        "add",
        "status",
        "suggest",
        "edit",
        "remove",
    }:
        _fail("wrong_action")
    allowed_by_action = {
        "add": {"action", "title", "type", "genre", "comment", "lang"},
        "status": {"action", "lang"},
        "suggest": {"action", "type", "genre", "lang"},
        "edit": {
            "action",
            "index",
            "title",
            "type",
            "genre",
            "comment",
            "lang",
        },
        "remove": {"action", "index", "type", "lang"},
    }
    if set(value) - allowed_by_action[action]:
        _fail("unknown_key")
    result: dict[str, Any] = {"action": action}
    if "title" in value:
        result["title"] = _string(value["title"])
    if "type" in value:
        item_type = value["type"]
        if item_type is not None and (
            not isinstance(item_type, str)
            or item_type not in {"movie", "series"}
        ):
            _fail("wrong_action")
        result["type"] = item_type
    if "index" in value:
        result["index"] = _positive_int(value["index"])
    for key in ("genre", "comment"):
        if key in value:
            result[key] = _string(value[key], allow_none=True)
    if "lang" in value:
        result["lang"] = _language(value["lang"])
    if action == "add" and "title" not in result:
        _fail("blank_value")
    if action == "edit":
        if "index" not in result:
            _fail("missing_target")
        has_change = any(
            key in value for key in ("title", "genre", "comment")
        ) or ("type" in value and value["type"] is not None)
        if not has_change:
            _fail("missing_change")
    if action == "remove" and "index" not in result:
        _fail("missing_target")
    return result


def _quote(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource,
) -> dict[str, Any]:
    value = _mapping(raw, frozenset({"action", "index", "text", "author", "lang"}))
    allowed_actions = {
        BotIntent.QUOTE: {"save", "get"},
        BotIntent.QUOTE_LIST: {"list"},
        BotIntent.QUOTE_EDIT: {"edit"},
        BotIntent.QUOTE_DELETE: {"delete"},
    }[intent]
    action = value.get("action")
    if not isinstance(action, str) or action not in allowed_actions:
        _fail("wrong_action")
    allowed_by_action = {
        "save": {"action", "text", "author", "lang"},
        "get": {"action", "author", "lang"},
        "list": {"action", "lang"},
        "edit": {"action", "index", "text", "author", "lang"},
        "delete": {"action", "index", "lang"},
    }
    if set(value) - allowed_by_action[action]:
        _fail("unknown_key")
    result: dict[str, Any] = {"action": action}
    if "index" in value:
        result["index"] = _positive_int(value["index"])
    for key in ("text", "author"):
        if key in value:
            result[key] = _string(value[key])
    if "lang" in value:
        result["lang"] = _language(value["lang"])
    if action == "save" and "text" not in result:
        _fail("blank_value")
    if action == "edit":
        if "index" not in result:
            _fail("missing_target")
        if not any(key in result for key in ("text", "author")):
            _fail("missing_change")
    if action == "delete" and "index" not in result:
        _fail("missing_target")
    return result


def _memory(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource,
) -> dict[str, Any]:
    del source
    expected = {
        BotIntent.MEMORY_VIEW: "view",
        BotIntent.MEMORY_EXPORT: "export",
        BotIntent.MEMORY_DELETE: "delete",
    }[intent]
    value = _mapping(raw, frozenset({"action", "confirmed"}))
    if value.get("action") != expected:
        _fail("wrong_action")
    if "confirmed" in value and not isinstance(value["confirmed"], bool):
        _fail("wrong_action")
    # Confirmation is an opaque executing capability. The legacy prose flag
    # is accepted for one release but deliberately discarded here.
    return {"action": expected}


Validator: TypeAlias = Callable[..., dict[str, Any]]


def _calendar_list(
    raw: Mapping[str, Any], *, source: IntentSource
) -> dict[str, Any]:
    del source
    value = _mapping(raw, frozenset({"date"}))
    if "date" not in value:
        return {}
    canonical_date, _ = _date_time(value["date"])
    return {"date": canonical_date}


INTENT_VALIDATORS: dict[BotIntent, Validator] = {
    BotIntent.CALENDAR_ITEM: _calendar_create,
    BotIntent.CALENDAR_LIST: _calendar_list,
    BotIntent.CALENDAR_EDIT: _calendar_edit,
    BotIntent.CALENDAR_DELETE: lambda raw, *, source: _calendar_target(
        BotIntent.CALENDAR_DELETE, raw, source=source
    ),
    BotIntent.CALENDAR_COMPLETE: lambda raw, *, source: _calendar_target(
        BotIntent.CALENDAR_COMPLETE, raw, source=source
    ),
    BotIntent.CALENDAR_CLEAR: lambda raw, *, source: _calendar_target(
        BotIntent.CALENDAR_CLEAR, raw, source=source
    ),
    BotIntent.REMINDER_CREATE: _reminder_create,
    BotIntent.REMINDER_LIST: lambda raw, *, source: _reminder_target(
        BotIntent.REMINDER_LIST, raw, source=source
    ),
    BotIntent.REMINDER_SEARCH: lambda raw, *, source: _reminder_target(
        BotIntent.REMINDER_SEARCH, raw, source=source
    ),
    BotIntent.REMINDER_COMPLETE: lambda raw, *, source: _reminder_target(
        BotIntent.REMINDER_COMPLETE, raw, source=source
    ),
    BotIntent.REMINDER_EDIT: _reminder_edit,
    BotIntent.REMINDER_DELETE: lambda raw, *, source: _reminder_target(
        BotIntent.REMINDER_DELETE, raw, source=source
    ),
    BotIntent.POLL_CREATE: _poll_create,
    BotIntent.POLL_VOTE: _poll_vote,
    BotIntent.POLL_EDIT: _poll_edit,
    BotIntent.POLL_DELETE: _poll_target,
    BotIntent.POLL_CLOSE: _poll_target,
    BotIntent.BIRTHDAY_CREATE: lambda raw, *, source: _birthday(
        BotIntent.BIRTHDAY_CREATE, raw, source=source
    ),
    BotIntent.BIRTHDAY_LIST: lambda raw, *, source: _birthday(
        BotIntent.BIRTHDAY_LIST, raw, source=source
    ),
    BotIntent.BIRTHDAY_EDIT: lambda raw, *, source: _birthday(
        BotIntent.BIRTHDAY_EDIT, raw, source=source
    ),
    BotIntent.WATCHLIST: _watchlist,
    BotIntent.QUOTE: lambda raw, *, source: _quote(BotIntent.QUOTE, raw, source=source),
    BotIntent.QUOTE_LIST: lambda raw, *, source: _quote(
        BotIntent.QUOTE_LIST, raw, source=source
    ),
    BotIntent.QUOTE_EDIT: lambda raw, *, source: _quote(
        BotIntent.QUOTE_EDIT, raw, source=source
    ),
    BotIntent.QUOTE_DELETE: lambda raw, *, source: _quote(
        BotIntent.QUOTE_DELETE, raw, source=source
    ),
    BotIntent.MEMORY_VIEW: lambda raw, *, source: _memory(
        BotIntent.MEMORY_VIEW, raw, source=source
    ),
    BotIntent.MEMORY_EXPORT: lambda raw, *, source: _memory(
        BotIntent.MEMORY_EXPORT, raw, source=source
    ),
    BotIntent.MEMORY_DELETE: lambda raw, *, source: _memory(
        BotIntent.MEMORY_DELETE, raw, source=source
    ),
    BotIntent.PROFILE: _profile,
}


ENVELOPE_KEYS: dict[BotIntent, str] = {
    BotIntent.CALENDAR_ITEM: "calendar_item",
    BotIntent.CALENDAR_LIST: "calendar_list",
    BotIntent.CALENDAR_EDIT: "calendar_edit",
    BotIntent.CALENDAR_DELETE: "calendar_target",
    BotIntent.CALENDAR_COMPLETE: "calendar_target",
    BotIntent.CALENDAR_CLEAR: "calendar_target",
    BotIntent.REMINDER_CREATE: "reminder",
    BotIntent.REMINDER_LIST: "reminder",
    BotIntent.REMINDER_SEARCH: "reminder",
    BotIntent.REMINDER_COMPLETE: "reminder",
    BotIntent.REMINDER_EDIT: "reminder",
    BotIntent.REMINDER_DELETE: "reminder",
    BotIntent.POLL_CREATE: "poll",
    BotIntent.POLL_VOTE: "vote",
    BotIntent.POLL_EDIT: "poll_edit",
    BotIntent.POLL_DELETE: "poll_delete",
    BotIntent.POLL_CLOSE: "poll_close",
    BotIntent.BIRTHDAY_CREATE: "birthday",
    BotIntent.BIRTHDAY_LIST: "birthday",
    BotIntent.BIRTHDAY_EDIT: "birthday",
    BotIntent.WATCHLIST: "watchlist",
    BotIntent.QUOTE: "quote",
    BotIntent.QUOTE_LIST: "quote",
    BotIntent.QUOTE_EDIT: "quote",
    BotIntent.QUOTE_DELETE: "quote",
    BotIntent.MEMORY_VIEW: "memory",
    BotIntent.MEMORY_EXPORT: "memory",
    BotIntent.MEMORY_DELETE: "memory",
    BotIntent.PROFILE: "profile",
}


T = TypeVar("T")


def typed_or_legacy_payload(
    *,
    monitor: Any,
    family: str,
    typed_value: T | None,
    legacy_factory: Callable[[], T | None],
) -> T | None:
    if typed_value is not None:
        return typed_value
    monitor.nlu_metrics.record_legacy_payload_fallback(family)
    return legacy_factory()


def validate_intent_payload(
    intent: BotIntent,
    raw: Mapping[str, Any],
    *,
    source: IntentSource = IntentSource.DETERMINISTIC,
) -> dict[str, Any]:
    validator = INTENT_VALIDATORS.get(intent)
    if validator is None:
        raise PayloadValidationError("unsupported_intent")
    return validator(raw, source=source)
