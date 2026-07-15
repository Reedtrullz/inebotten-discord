"""Strict, inert model-action protocol parsing and validation.

This module validates proposals only.  It deliberately has no access to
Discord, feature handlers, pending state, clocks, or mutation APIs.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TypeAlias
from zoneinfo import ZoneInfo

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class ActionName(str, Enum):
    NONE = "NONE"
    CLARIFY = "CLARIFY"
    SHOW_DASHBOARD = "SHOW_DASHBOARD"
    HELP = "HELP"
    CALENDAR_CREATE = "CALENDAR_CREATE"
    CALENDAR_LIST = "CALENDAR_LIST"
    CALENDAR_SEARCH = "CALENDAR_SEARCH"
    CALENDAR_COMPLETE = "CALENDAR_COMPLETE"
    CALENDAR_EDIT = "CALENDAR_EDIT"
    CALENDAR_DELETE = "CALENDAR_DELETE"
    CALENDAR_CLEAR = "CALENDAR_CLEAR"
    REMINDER_CREATE = "REMINDER_CREATE"
    REMINDER_LIST = "REMINDER_LIST"
    REMINDER_SEARCH = "REMINDER_SEARCH"
    REMINDER_COMPLETE = "REMINDER_COMPLETE"
    REMINDER_EDIT = "REMINDER_EDIT"
    REMINDER_DELETE = "REMINDER_DELETE"
    POLL_CREATE = "POLL_CREATE"
    POLL_LIST = "POLL_LIST"
    POLL_VOTE = "POLL_VOTE"
    POLL_EDIT = "POLL_EDIT"
    POLL_DELETE = "POLL_DELETE"
    POLL_CLOSE = "POLL_CLOSE"
    BIRTHDAY_CREATE = "BIRTHDAY_CREATE"
    BIRTHDAY_LIST = "BIRTHDAY_LIST"
    BIRTHDAY_EDIT = "BIRTHDAY_EDIT"
    WATCHLIST_ADD = "WATCHLIST_ADD"
    WATCHLIST_LIST = "WATCHLIST_LIST"
    WATCHLIST_SUGGEST = "WATCHLIST_SUGGEST"
    WATCHLIST_EDIT = "WATCHLIST_EDIT"
    WATCHLIST_REMOVE = "WATCHLIST_REMOVE"
    QUOTE_SAVE = "QUOTE_SAVE"
    QUOTE_GET = "QUOTE_GET"
    QUOTE_LIST = "QUOTE_LIST"
    QUOTE_EDIT = "QUOTE_EDIT"
    QUOTE_DELETE = "QUOTE_DELETE"


class SlotRule(str, Enum):
    S200 = "S200"
    S300 = "S300"
    S500 = "S500"
    TEXT2000 = "TEXT2000"
    POS_INT = "POS_INT"
    INT = "INT"
    DAY_OFFSET = "DAY_OFFSET"
    DATE = "DATE"
    TIME = "TIME"
    DUE_AT = "DUE_AT"
    NULLABLE_DATE = "NULLABLE_DATE"
    NULLABLE_TIME = "NULLABLE_TIME"
    NULLABLE_DUE_AT = "NULLABLE_DUE_AT"
    NULLABLE_S200 = "NULLABLE_S200"
    NULLABLE_TEXT2000 = "NULLABLE_TEXT2000"
    RECURRENCE = "RECURRENCE"
    NULLABLE_RECURRENCE = "NULLABLE_RECURRENCE"
    OSLO = "OSLO"
    EVENT_TYPE = "EVENT_TYPE"
    MEDIA_TYPE = "MEDIA_TYPE"
    OPTIONS = "OPTIONS"
    POLL_TARGET = "POLL_TARGET"
    YEAR = "YEAR"
    DAY = "DAY"
    MONTH = "MONTH"
    BIRTHDAY_SCOPE = "BIRTHDAY_SCOPE"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    required: Mapping[str, SlotRule]
    optional: Mapping[str, SlotRule]
    exactly_one: tuple[str, ...] = ()
    at_least_one: tuple[str, ...] = ()
    temporal_family: str | None = None
    context_rule: str | None = None


def _spec(
    *,
    required: tuple[tuple[str, SlotRule], ...] = (),
    optional: tuple[tuple[str, SlotRule], ...] = (),
    exactly_one: tuple[str, ...] = (),
    at_least_one: tuple[str, ...] = (),
    temporal_family: str | None = None,
    context_rule: str | None = None,
) -> ActionSpec:
    return ActionSpec(
        required=MappingProxyType(dict(required)),
        optional=MappingProxyType(dict(optional)),
        exactly_one=exactly_one,
        at_least_one=at_least_one,
        temporal_family=temporal_family,
        context_rule=context_rule,
    )


ACTION_SPECS: Mapping[ActionName, ActionSpec] = MappingProxyType(
    {
        ActionName.NONE: _spec(),
        ActionName.CLARIFY: _spec(),
        ActionName.SHOW_DASHBOARD: _spec(),
        ActionName.HELP: _spec(),
        ActionName.CALENDAR_CREATE: _spec(
            required=(("title", SlotRule.S200),),
            optional=(
                ("date", SlotRule.DATE),
                ("time", SlotRule.TIME),
                ("type", SlotRule.EVENT_TYPE),
                ("recurrence", SlotRule.RECURRENCE),
                ("recurrence_day", SlotRule.S200),
                ("rrule_day", SlotRule.S200),
                ("days_offset", SlotRule.DAY_OFFSET),
                ("description", SlotRule.TEXT2000),
            ),
            at_least_one=("date", "days_offset"),
            temporal_family="calendar",
        ),
        ActionName.CALENDAR_LIST: _spec(),
        ActionName.CALENDAR_SEARCH: _spec(required=(("query", SlotRule.S500),)),
        ActionName.CALENDAR_COMPLETE: _spec(
            optional=(("target", SlotRule.S200), ("number", SlotRule.POS_INT)),
            exactly_one=("target", "number"),
        ),
        ActionName.CALENDAR_EDIT: _spec(
            required=(("target", SlotRule.S200),),
            optional=(
                ("title", SlotRule.S200),
                ("description", SlotRule.TEXT2000),
                ("date", SlotRule.DATE),
                ("time", SlotRule.TIME),
                ("recurrence", SlotRule.NULLABLE_RECURRENCE),
            ),
            at_least_one=("title", "description", "date", "time", "recurrence"),
            temporal_family="calendar",
        ),
        ActionName.CALENDAR_DELETE: _spec(
            optional=(("target", SlotRule.S200), ("number", SlotRule.POS_INT)),
            exactly_one=("target", "number"),
        ),
        ActionName.CALENDAR_CLEAR: _spec(),
        ActionName.REMINDER_CREATE: _spec(
            required=(("text", SlotRule.S500),),
            optional=(
                ("due_at", SlotRule.DUE_AT),
                ("due_date", SlotRule.DATE),
                ("time", SlotRule.TIME),
                ("timezone", SlotRule.OSLO),
                ("recurrence", SlotRule.RECURRENCE),
            ),
            temporal_family="reminder",
        ),
        ActionName.REMINDER_LIST: _spec(),
        ActionName.REMINDER_SEARCH: _spec(required=(("query", SlotRule.S500),)),
        ActionName.REMINDER_COMPLETE: _spec(required=(("number", SlotRule.POS_INT),)),
        ActionName.REMINDER_EDIT: _spec(
            required=(("number", SlotRule.POS_INT),),
            optional=(
                ("text", SlotRule.S500),
                ("due_at", SlotRule.NULLABLE_DUE_AT),
                ("due_date", SlotRule.NULLABLE_DATE),
                ("time", SlotRule.NULLABLE_TIME),
                ("timezone", SlotRule.OSLO),
                ("recurrence", SlotRule.NULLABLE_RECURRENCE),
            ),
            at_least_one=(
                "text",
                "due_at",
                "due_date",
                "time",
                "recurrence",
            ),
            temporal_family="reminder",
        ),
        ActionName.REMINDER_DELETE: _spec(required=(("number", SlotRule.POS_INT),)),
        ActionName.POLL_CREATE: _spec(
            required=(("question", SlotRule.S300), ("options", SlotRule.OPTIONS)),
        ),
        ActionName.POLL_LIST: _spec(),
        ActionName.POLL_VOTE: _spec(
            required=(("option", SlotRule.POS_INT),),
            context_rule="one_active_poll",
        ),
        ActionName.POLL_EDIT: _spec(
            optional=(
                ("target", SlotRule.POLL_TARGET),
                ("question", SlotRule.S300),
                ("options", SlotRule.OPTIONS),
            ),
            at_least_one=("question", "options"),
            context_rule="target_or_one_active_poll",
        ),
        ActionName.POLL_DELETE: _spec(
            optional=(("target", SlotRule.POLL_TARGET),),
            context_rule="target_or_one_active_poll",
        ),
        ActionName.POLL_CLOSE: _spec(
            optional=(("target", SlotRule.POLL_TARGET),),
            context_rule="target_or_one_active_poll",
        ),
        ActionName.BIRTHDAY_CREATE: _spec(
            required=(
                ("user_id", SlotRule.POS_INT),
                ("day", SlotRule.DAY),
                ("month", SlotRule.MONTH),
            ),
            optional=(("year", SlotRule.YEAR),),
            context_rule="resolved_mention",
        ),
        ActionName.BIRTHDAY_LIST: _spec(optional=(("scope", SlotRule.BIRTHDAY_SCOPE),)),
        ActionName.BIRTHDAY_EDIT: _spec(
            required=(
                ("user_id", SlotRule.POS_INT),
                ("day", SlotRule.DAY),
                ("month", SlotRule.MONTH),
            ),
            optional=(("year", SlotRule.YEAR),),
            context_rule="author_or_resolved_mention",
        ),
        ActionName.WATCHLIST_ADD: _spec(
            required=(("title", SlotRule.S500),),
            optional=(
                ("type", SlotRule.MEDIA_TYPE),
                ("genre", SlotRule.S200),
                ("comment", SlotRule.TEXT2000),
            ),
        ),
        ActionName.WATCHLIST_LIST: _spec(),
        ActionName.WATCHLIST_SUGGEST: _spec(
            optional=(("type", SlotRule.MEDIA_TYPE), ("genre", SlotRule.S200)),
        ),
        ActionName.WATCHLIST_EDIT: _spec(
            required=(("index", SlotRule.POS_INT),),
            optional=(
                ("title", SlotRule.S500),
                ("type", SlotRule.MEDIA_TYPE),
                ("genre", SlotRule.NULLABLE_S200),
                ("comment", SlotRule.NULLABLE_TEXT2000),
            ),
            at_least_one=("title", "type", "genre", "comment"),
        ),
        ActionName.WATCHLIST_REMOVE: _spec(required=(("index", SlotRule.POS_INT),)),
        ActionName.QUOTE_SAVE: _spec(
            required=(("text", SlotRule.TEXT2000),),
            optional=(("author", SlotRule.S200),),
        ),
        ActionName.QUOTE_GET: _spec(),
        ActionName.QUOTE_LIST: _spec(),
        ActionName.QUOTE_EDIT: _spec(
            required=(("index", SlotRule.POS_INT),),
            optional=(("text", SlotRule.TEXT2000), ("author", SlotRule.S200)),
            at_least_one=("text", "author"),
        ),
        ActionName.QUOTE_DELETE: _spec(required=(("index", SlotRule.POS_INT),)),
    }
)


@dataclass(frozen=True, slots=True)
class ActionProposal:
    action: ActionName
    confidence: float
    slots: Mapping[str, JsonValue]
    reply: str = ""
    clarification: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedAIResponse:
    text: str
    proposal: ActionProposal | None
    errors: tuple[str, ...] = ()
    legacy: bool = False


class ActionValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _string(value: object, limit: int, code: str) -> str:
    if not isinstance(value, str):
        raise ActionValidationError(code)
    result = value.strip()
    if not result or len(result) > limit:
        raise ActionValidationError(code)
    return result


def _integer(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionValidationError(code)
    return value


def _date_value(value: object) -> str:
    raw = _string(value, 10, "invalid_date")
    try:
        parsed = datetime.strptime(raw, "%d.%m.%Y")
    except ValueError as exc:
        raise ActionValidationError("invalid_date") from exc
    canonical = parsed.strftime("%d.%m.%Y")
    if raw != canonical:
        raise ActionValidationError("invalid_date")
    return canonical


def _time_value(value: object) -> str:
    raw = _string(value, 5, "invalid_time")
    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError as exc:
        raise ActionValidationError("invalid_time") from exc
    canonical = parsed.strftime("%H:%M")
    if raw != canonical:
        raise ActionValidationError("invalid_time")
    return canonical


def _due_at_value(value: object) -> str:
    raw = _string(value, 64, "invalid_due_at")
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
            raise ActionValidationError("invalid_due_at")
        return parsed.isoformat(timespec="seconds")
    except ActionValidationError:
        raise
    except (OverflowError, ValueError) as exc:
        raise ActionValidationError("invalid_due_at") from exc


_RECURRENCES = frozenset({"daily", "weekly", "biweekly", "monthly", "yearly"})


def _validate_slot(name: str, value: object, rule: SlotRule) -> JsonValue:
    if rule is SlotRule.S200:
        return _string(value, 200, f"invalid_slot:{name}")
    if rule is SlotRule.S300:
        return _string(value, 300, f"invalid_slot:{name}")
    if rule is SlotRule.S500:
        return _string(value, 500, f"invalid_slot:{name}")
    if rule is SlotRule.TEXT2000:
        return _string(value, 2000, f"invalid_slot:{name}")
    if rule is SlotRule.POS_INT:
        result = _integer(value, f"invalid_slot:{name}")
        if result <= 0:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.INT:
        return _integer(value, f"invalid_slot:{name}")
    if rule is SlotRule.DAY_OFFSET:
        result = _integer(value, f"invalid_slot:{name}")
        if not -3650 <= result <= 3650:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.DATE:
        return _date_value(value)
    if rule is SlotRule.TIME:
        return _time_value(value)
    if rule is SlotRule.DUE_AT:
        return _due_at_value(value)
    if rule is SlotRule.NULLABLE_DATE:
        return None if value is None else _date_value(value)
    if rule is SlotRule.NULLABLE_TIME:
        return None if value is None else _time_value(value)
    if rule is SlotRule.NULLABLE_DUE_AT:
        return None if value is None else _due_at_value(value)
    if rule is SlotRule.NULLABLE_S200:
        return None if value is None else _string(value, 200, f"invalid_slot:{name}")
    if rule is SlotRule.NULLABLE_TEXT2000:
        return None if value is None else _string(value, 2000, f"invalid_slot:{name}")
    if rule is SlotRule.RECURRENCE:
        result = _string(value, 20, f"invalid_slot:{name}")
        if result not in _RECURRENCES:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.NULLABLE_RECURRENCE:
        if value is None:
            return None
        result = _string(value, 20, f"invalid_slot:{name}")
        if result not in _RECURRENCES:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.OSLO:
        if value != "Europe/Oslo":
            raise ActionValidationError(f"invalid_slot:{name}")
        return "Europe/Oslo"
    if rule is SlotRule.EVENT_TYPE:
        if value not in {"event", "task"}:
            raise ActionValidationError(f"invalid_slot:{name}")
        return str(value)
    if rule is SlotRule.MEDIA_TYPE:
        if value not in {"movie", "series"}:
            raise ActionValidationError(f"invalid_slot:{name}")
        return str(value)
    if rule is SlotRule.OPTIONS:
        if not isinstance(value, list) or not 2 <= len(value) <= 10:
            raise ActionValidationError(f"invalid_slot:{name}")
        options = [_string(item, 100, f"invalid_slot:{name}") for item in value]
        if len({item.casefold() for item in options}) != len(options):
            raise ActionValidationError(f"invalid_slot:{name}")
        return options
    if rule is SlotRule.POLL_TARGET:
        if value == "siste":
            return "siste"
        result = _integer(value, f"invalid_slot:{name}")
        if result <= 0:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.YEAR:
        result = _integer(value, f"invalid_slot:{name}")
        if not 1900 <= result <= 2100:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.DAY:
        result = _integer(value, f"invalid_slot:{name}")
        if not 1 <= result <= 31:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.MONTH:
        result = _integer(value, f"invalid_slot:{name}")
        if not 1 <= result <= 12:
            raise ActionValidationError(f"invalid_slot:{name}")
        return result
    if rule is SlotRule.BIRTHDAY_SCOPE:
        if value not in {"all", "upcoming"}:
            raise ActionValidationError(f"invalid_slot:{name}")
        return str(value)
    raise AssertionError(f"unhandled slot rule: {rule}")


def _validate_temporal(
    slots: Mapping[str, JsonValue],
    family: str,
    *,
    action: ActionName,
) -> None:
    date_key = "date" if family == "calendar" else "due_date"
    has_date = date_key in slots
    has_time = "time" in slots
    has_due_at = "due_at" in slots
    date_value = slots.get(date_key)
    time_value = slots.get("time")
    due_at = slots.get("due_at")
    if family == "calendar":
        if date_value is None and slots.get("days_offset") is not None:
            return
        if action is ActionName.CALENDAR_EDIT and date_value is None:
            # A time-only edit is canonical, but DST validation depends on the
            # frozen target's existing date.  The resolver validates the
            # merged date/time before a confirmation is presented.
            return
        if time_value is not None and date_value is None:
            raise ActionValidationError("invalid_temporal")
        return

    if action is ActionName.REMINDER_EDIT:
        if not has_due_at and not has_date:
            # A time-only edit is validated against the frozen target date.
            return
        if has_due_at and due_at is None:
            if (has_date and date_value is not None) or (
                has_time and time_value is not None
            ):
                raise ActionValidationError("invalid_temporal")
            return
        if not has_due_at and has_date and date_value is None:
            if has_time and time_value is not None:
                raise ActionValidationError("invalid_temporal")
            return
        if has_due_at and due_at is not None:
            if (has_date and date_value is None) or (
                has_time and time_value is None
            ):
                raise ActionValidationError("inconsistent_temporal")
        if has_date and date_value is not None and has_time and time_value is None:
            raise ActionValidationError("invalid_temporal")

    if (
        action is ActionName.REMINDER_CREATE
        and slots.get("recurrence") is not None
        and due_at is None
        and date_value is None
    ):
        raise ActionValidationError("invalid_temporal")

    if time_value is not None and date_value is None and due_at is None:
        raise ActionValidationError("invalid_temporal")
    if due_at is None:
        return
    try:
        parsed = datetime.fromisoformat(str(due_at)).astimezone(
            ZoneInfo("Europe/Oslo")
        )
    except (OverflowError, ValueError) as exc:
        raise ActionValidationError("invalid_due_at") from exc
    if date_value is not None and parsed.strftime("%d.%m.%Y") != date_value:
        raise ActionValidationError("inconsistent_temporal")
    if time_value is not None and parsed.strftime("%H:%M") != time_value:
        raise ActionValidationError("inconsistent_temporal")


def _validate_birthday(slots: Mapping[str, JsonValue]) -> None:
    year = int(slots.get("year", 2000))
    try:
        date(year, int(slots["month"]), int(slots["day"]))
    except ValueError as exc:
        raise ActionValidationError("invalid_birthday") from exc


def _validate_slots(action: ActionName, raw: object) -> Mapping[str, JsonValue]:
    if not isinstance(raw, dict):
        raise ActionValidationError("invalid_slots")
    spec = ACTION_SPECS[action]
    allowed = set(spec.required) | set(spec.optional)
    if set(raw) - allowed:
        raise ActionValidationError("unknown_slot")
    if set(spec.required) - set(raw):
        raise ActionValidationError("missing_slot")
    validated: dict[str, JsonValue] = {}
    for name, value in raw.items():
        rule = spec.required.get(name) or spec.optional.get(name)
        if rule is None:
            raise ActionValidationError("unknown_slot")
        validated[name] = _validate_slot(name, value, rule)
    if spec.exactly_one and sum(name in validated for name in spec.exactly_one) != 1:
        raise ActionValidationError("exactly_one_slot_required")
    if spec.at_least_one and not any(name in validated for name in spec.at_least_one):
        raise ActionValidationError("at_least_one_slot_required")
    if spec.temporal_family:
        _validate_temporal(validated, spec.temporal_family, action=action)
    if action in {ActionName.BIRTHDAY_CREATE, ActionName.BIRTHDAY_EDIT}:
        _validate_birthday(validated)
    return MappingProxyType(validated)


_TOP_LEVEL_KEYS = {"action", "confidence", "slots", "reply", "clarification"}


def validate_action_object(raw: object) -> ActionProposal:
    if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
        raise ActionValidationError("invalid_top_level")
    try:
        action = ActionName(raw["action"])
    except (TypeError, ValueError) as exc:
        raise ActionValidationError("unknown_action") from exc
    confidence = raw["confidence"]
    try:
        numeric_confidence = float(confidence)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ActionValidationError("invalid_confidence") from exc
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(numeric_confidence)
        or not 0.0 <= numeric_confidence <= 1.0
    ):
        raise ActionValidationError("invalid_confidence")
    reply = raw["reply"]
    if not isinstance(reply, str) or len(reply) > 2000:
        raise ActionValidationError("invalid_reply")
    clarification = raw["clarification"]
    if clarification is not None and not isinstance(clarification, str):
        raise ActionValidationError("invalid_clarification")
    clarification = clarification.strip() if isinstance(clarification, str) else None
    if action is ActionName.CLARIFY:
        clarification = _string(clarification, 500, "invalid_clarification")
    elif clarification:
        raise ActionValidationError("unexpected_clarification")
    slots = _validate_slots(action, raw["slots"])
    return ActionProposal(
        action=action,
        confidence=numeric_confidence,
        slots=slots,
        reply=reply.strip(),
        clarification=clarification,
    )


_FENCE_LINE_RE = re.compile(r"^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<tail>[^\r\n]*)$")
_REASON_TAG_RE = re.compile(
    r"<(?P<close>/)?(?P<name>think|thinking)\b[^>]*>",
    re.IGNORECASE,
)
_RAW_HTML_TAGS = frozenset({"pre", "code", "script", "style", "textarea"})
_BLOCK_HTML_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "base",
        "basefont",
        "blockquote",
        "body",
        "caption",
        "center",
        "col",
        "colgroup",
        "dd",
        "details",
        "dialog",
        "dir",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "frame",
        "frameset",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hr",
        "html",
        "iframe",
        "legend",
        "li",
        "link",
        "main",
        "menu",
        "menuitem",
        "nav",
        "noframes",
        "ol",
        "optgroup",
        "option",
        "p",
        "param",
        "search",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "title",
        "tr",
        "track",
        "ul",
    }
)
_HTML_TAG_AT_COLUMN_RE = re.compile(r"^ {0,3}<(?P<close>/)?(?P<name>[A-Za-z][A-Za-z0-9-]*)\b")
_LEGACY_SAVE_RE = re.compile(r"^\[SAVE_EVENT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\]\s*$")
_LEGACY_DASHBOARD_RE = re.compile(r"^\[SHOW_DASHBOARD\]\s*$")


def parse_fence_line(line: str) -> tuple[str, str] | None:
    match = _FENCE_LINE_RE.fullmatch(line)
    if match is None:
        return None
    return match.group("marker"), match.group("tail").strip()


def is_complete_generic_html_tag(line: str) -> bool:
    """Recognize one complete generic tag without regexing through quotes."""
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return False
    value = line[indent:].rstrip()
    if not value.startswith("<"):
        return False
    index = 1
    if index < len(value) and value[index] == "/":
        index += 1
    if index >= len(value) or not value[index].isalpha():
        return False
    index += 1
    while index < len(value) and (value[index].isalnum() or value[index] == "-"):
        index += 1
    quote: str | None = None
    while index < len(value):
        char = value[index]
        if quote is not None:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "<":
            return False
        if char == ">":
            return not value[index + 1 :].strip()
        index += 1
    return False


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ActionValidationError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ActionValidationError("invalid_json_constant")


MAX_JSON_INTEGER_DIGITS = 128
MAX_JSON_NESTING = 64


def _parse_bounded_json_int(raw: str) -> int:
    if len(raw.removeprefix("-")) > MAX_JSON_INTEGER_DIGITS:
        raise ActionValidationError("invalid_number")
    return int(raw)


def _ensure_bounded_json_nesting(raw: str) -> None:
    """Reject deep structures without depending on interpreter recursion limits."""
    depth = 0
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_NESTING:
                raise ActionValidationError("json_too_deep")
        elif char in "]}":
            depth = max(0, depth - 1)


def _strict_action_json_loads(line: str) -> object:
    try:
        _ensure_bounded_json_nesting(line)
        return json.loads(
            line,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
            parse_int=_parse_bounded_json_int,
        )
    except ActionValidationError:
        raise
    except RecursionError as exc:
        raise ActionValidationError("json_too_deep") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ActionValidationError("invalid_json") from exc


def consume_reasoning_tags(line: str, stack: list[str]) -> bool:
    matches = tuple(_REASON_TAG_RE.finditer(line))
    was_inside = bool(stack)
    for match in matches:
        name = match.group("name").casefold()
        if match.group("close"):
            if stack and stack[-1] == name:
                stack.pop()
        else:
            stack.append(name)
    return was_inside or bool(matches) or bool(stack)


def consume_inert_html(line: str, stack: list[str]) -> bool:
    """Track conservative CommonMark HTML-block provenance."""
    if stack:
        mode = stack[-1]
        folded = line.casefold()
        if mode == "comment" and "-->" in line:
            stack.pop()
        elif mode == "processing" and "?>" in line:
            stack.pop()
        elif mode == "cdata" and "]]>" in line:
            stack.pop()
        elif mode == "declaration" and ">" in line:
            stack.pop()
        elif mode.startswith("raw:"):
            name = mode.split(":", 1)[1]
            if re.search(rf"</{re.escape(name)}\s*>", folded):
                stack.pop()
        elif mode == "blank_terminated" and not line.strip():
            stack.pop()
        return True

    indent = len(line) - len(line.lstrip(" "))
    stripped = line.lstrip(" ") if indent <= 3 else line
    if stripped.startswith("<!--"):
        if "-->" not in stripped[4:]:
            stack.append("comment")
        return True
    if stripped.startswith("<?"):
        if "?>" not in stripped[2:]:
            stack.append("processing")
        return True
    if stripped.startswith("<![CDATA["):
        if "]]>" not in stripped[9:]:
            stack.append("cdata")
        return True
    if re.match(r"<![A-Z]", stripped):
        if ">" not in stripped[2:]:
            stack.append("declaration")
        return True

    tag = _HTML_TAG_AT_COLUMN_RE.match(line)
    if tag is not None:
        name = tag.group("name").casefold()
        if name in _RAW_HTML_TAGS and not tag.group("close"):
            if re.search(rf"</{re.escape(name)}\s*>", line.casefold()) is None:
                stack.append(f"raw:{name}")
            return True
        if name in _BLOCK_HTML_TAGS or is_complete_generic_html_tag(line):
            stack.append("blank_terminated")
            return True
    return False


def _legacy_json(raw: Mapping[str, object]) -> ActionProposal | None:
    if raw.get("action") == "SHOW_DASHBOARD" and set(raw) == {"action"}:
        return ActionProposal(ActionName.SHOW_DASHBOARD, 1.0, MappingProxyType({}))
    if raw.get("action") != "SAVE_EVENT":
        return None
    if set(raw) != {"action", "title", "date", "time"}:
        raise ActionValidationError("invalid_legacy_action")
    converted = {
        "action": "CALENDAR_CREATE",
        "confidence": 1.0,
        "slots": {
            "title": raw["title"],
            "date": raw["date"],
            "time": raw["time"],
        },
        "reply": "",
        "clarification": None,
    }
    return validate_action_object(converted)


def _legacy_line(line: str) -> ActionProposal | None:
    event = _LEGACY_SAVE_RE.fullmatch(line)
    if event:
        title, date_value, time_value = event.groups()
        return validate_action_object(
            {
                "action": "CALENDAR_CREATE",
                "confidence": 1.0,
                "slots": {"title": title, "date": date_value, "time": time_value},
                "reply": "",
                "clarification": None,
            }
        )
    if _LEGACY_DASHBOARD_RE.fullmatch(line):
        return ActionProposal(ActionName.SHOW_DASHBOARD, 1.0, MappingProxyType({}))
    return None


def _action_json_line(line: str) -> bool:
    candidate = line.rstrip()
    return candidate.startswith("{") and candidate.endswith("}") and '"action"' in candidate


def _suspected_action_json_line(line: str) -> bool:
    candidate = line.rstrip()
    return candidate.startswith("{") and '"action"' in candidate


def _possible_json_fragment_line(line: str) -> bool:
    return line.startswith("{")


def _suspected_legacy_action_line(line: str) -> bool:
    candidate = line.rstrip()
    return candidate.startswith("[SAVE_EVENT:") or candidate == "[SHOW_DASHBOARD]"


def is_suspected_action_candidate_line(line: str) -> bool:
    """Return whether a zero-indent line has model-action provenance.

    This is deliberately broader than validity: malformed and truncated
    protocol candidates must remain visible to the authoritative parser.
    """

    return (
        _suspected_action_json_line(line)
        or _suspected_legacy_action_line(line)
    )


def _near_column_protocol_line(line: str) -> bool:
    indent = len(line) - len(line.lstrip(" "))
    if not 1 <= indent <= 3:
        return False
    candidate = line[indent:]
    return is_suspected_action_candidate_line(candidate)


def _near_column_json_fragment_line(line: str) -> bool:
    indent = len(line) - len(line.lstrip(" "))
    return 1 <= indent <= 3 and line[indent:].startswith("{")


def _visible_without_protocol(lines: list[str], indices: set[int]) -> str:
    return "\n".join(line for index, line in enumerate(lines) if index not in indices).strip()


def strip_suspected_protocol_lines(raw: str) -> str:
    """Remove possible protocol lines for display without validating actions."""
    lines = raw.splitlines()
    active_fence: tuple[str, int] | None = None
    reasoning_stack: list[str] = []
    inert_html_stack: list[str] = []
    remove: set[int] = set()
    for index, line in enumerate(lines):
        if reasoning_stack:
            consume_reasoning_tags(line, reasoning_stack)
            continue
        if inert_html_stack:
            consume_inert_html(line, inert_html_stack)
            continue
        fence = parse_fence_line(line)
        if active_fence is None and fence is not None:
            active_fence = (fence[0][0], len(fence[0]))
            continue
        if active_fence is not None:
            if (
                fence is not None
                and fence[0][0] == active_fence[0]
                and len(fence[0]) >= active_fence[1]
                and fence[1] == ""
            ):
                active_fence = None
            continue
        if consume_reasoning_tags(line, reasoning_stack):
            continue
        if consume_inert_html(line, inert_html_stack):
            continue
        if (
            _near_column_protocol_line(line)
            or is_suspected_action_candidate_line(line)
        ):
            remove.add(index)
    return _visible_without_protocol(lines, remove)


def parse_ai_response(raw: str) -> ParsedAIResponse:
    if not isinstance(raw, str):
        return ParsedAIResponse("", None, ("invalid_response_type",))
    lines = raw.splitlines()
    active_fence: tuple[str, int] | None = None
    reasoning_stack: list[str] = []
    inert_html_stack: list[str] = []
    proposals: list[tuple[int, ActionProposal, bool]] = []
    errors: list[str] = []
    deferred_json_errors: list[tuple[int, str]] = []
    protocol_indices: set[int] = set()
    for index, line in enumerate(lines):
        if reasoning_stack:
            consume_reasoning_tags(line, reasoning_stack)
            continue
        if inert_html_stack:
            consume_inert_html(line, inert_html_stack)
            continue
        fence = parse_fence_line(line)
        if active_fence is None and fence is not None:
            active_fence = (fence[0][0], len(fence[0]))
            continue
        if active_fence is not None:
            if (
                fence is not None
                and fence[0][0] == active_fence[0]
                and len(fence[0]) >= active_fence[1]
                and fence[1] == ""
            ):
                active_fence = None
            continue
        if consume_reasoning_tags(line, reasoning_stack):
            continue
        if consume_inert_html(line, inert_html_stack):
            continue
        if _near_column_protocol_line(line):
            protocol_indices.add(index)
            errors.append("non_standalone_action")
            continue
        if _near_column_json_fragment_line(line):
            deferred_json_errors.append((index, "non_standalone_action"))
            continue
        suspected_legacy = _suspected_legacy_action_line(line)
        if suspected_legacy:
            protocol_indices.add(index)
        try:
            legacy = _legacy_line(line)
        except ActionValidationError as exc:
            errors.append(exc.code)
            continue
        if legacy is not None:
            proposals.append((index, legacy, True))
            continue
        if suspected_legacy:
            errors.append("invalid_legacy_action")
            continue
        suspected_action_json = _suspected_action_json_line(line)
        if not _possible_json_fragment_line(line):
            continue
        try:
            decoded = _strict_action_json_loads(line)
        except ActionValidationError as exc:
            if suspected_action_json:
                protocol_indices.add(index)
                errors.append(exc.code)
            else:
                deferred_json_errors.append((index, exc.code))
            continue
        try:
            legacy_json = _legacy_json(decoded) if isinstance(decoded, dict) else None
            proposal = legacy_json or validate_action_object(decoded)
        except ActionValidationError as exc:
            if suspected_action_json:
                protocol_indices.add(index)
                errors.append(exc.code)
            else:
                deferred_json_errors.append((index, exc.code))
            continue
        protocol_indices.add(index)
        proposals.append((index, proposal, legacy_json is not None))
    if proposals and deferred_json_errors:
        for index, code in deferred_json_errors:
            protocol_indices.add(index)
            errors.append(code)
    if len(proposals) > 1:
        return ParsedAIResponse(
            _visible_without_protocol(lines, protocol_indices),
            None,
            ("multiple_proposals",),
        )
    if errors:
        return ParsedAIResponse(
            _visible_without_protocol(lines, protocol_indices),
            None,
            tuple(dict.fromkeys(errors)),
        )
    if not proposals:
        return ParsedAIResponse(raw, None)
    proposal_index, proposal, legacy = proposals[0]
    visible = _visible_without_protocol(lines, {proposal_index})
    return ParsedAIResponse(visible, proposal, legacy=legacy)


def is_valid_standalone_action_line(line: str) -> bool:
    if not _action_json_line(line):
        return False
    try:
        decoded = _strict_action_json_loads(line)
        if isinstance(decoded, dict) and _legacy_json(decoded) is not None:
            return True
        validate_action_object(decoded)
        return True
    except ActionValidationError:
        return False


_ATOM_FORMATS = (
    "S200=nonblank string, max 200 chars; "
    "S300=nonblank string, max 300 chars; "
    "S500=nonblank string, max 500 chars; "
    "TEXT2000=nonblank string, max 2000 chars; "
    "POS_INT=integer greater than zero, bool forbidden; "
    "INT=integer, bool forbidden; "
    "DAY_OFFSET=integer -3650..3650 inclusive, bool forbidden; "
    "DATE=exact valid DD.MM.YYYY; "
    "TIME=exact zero-padded HH:MM; "
    "DUE_AT=aware whole-second ISO-8601 datetime with offset; "
    "NULLABLE_DATE=DATE or JSON null; "
    "NULLABLE_TIME=TIME or JSON null; "
    "NULLABLE_DUE_AT=DUE_AT or JSON null; "
    "NULLABLE_S200=S200 or JSON null; "
    "NULLABLE_TEXT2000=TEXT2000 or JSON null; "
    "RECURRENCE=literal daily, weekly, biweekly, monthly, or yearly; "
    "NULLABLE_RECURRENCE=RECURRENCE or JSON null; "
    "OSLO=literal Europe/Oslo; "
    "EVENT_TYPE=literal event or task; "
    "MEDIA_TYPE=literal movie or series; "
    "OPTIONS=array of 2-10 unique strings, each 1-100 chars; "
    "POLL_TARGET=POS_INT or literal siste; "
    "YEAR=integer 1900..2100; "
    "DAY=integer 1..31; "
    "MONTH=integer 1..12; "
    "BIRTHDAY_SCOPE=literal all or upcoming"
)


def _names(values: tuple[str, ...]) -> str:
    return ",".join(values) or "none"


def _render_action_spec(action: ActionName, spec: ActionSpec) -> str:
    required = ",".join(f"{name}:{rule.value}" for name, rule in spec.required.items()) or "none"
    optional = ",".join(f"{name}:{rule.value}" for name, rule in spec.optional.items()) or "none"
    return (
        f"- {action.value}: required={required}; optional={optional}; "
        f"exactly_one={_names(spec.exactly_one)}; "
        f"at_least_one={_names(spec.at_least_one)}; "
        f"temporal={spec.temporal_family or 'none'}; "
        f"context={spec.context_rule or 'none'}"
    )


ACTION_PROTOCOL_PROMPT = "\n".join(
    [
        "MODEL ACTION PROTOCOL:",
        "Write ordinary Norwegian prose first.",
        "Then emit zero or one standalone compact JSON object line.",
        "The protocol object must be one zero-indent, unfenced, single line.",
        'The JSON keys are exactly "action","confidence","slots","reply","clarification".',
        (
            'Shape example: {"action":"REMINDER_CREATE","confidence":0.93,'
            '"slots":{"text":"ringe legen",'
            '"due_at":"2026-07-15T09:00:00+02:00",'
            '"due_date":"15.07.2026","time":"09:00",'
            '"timezone":"Europe/Oslo"},"reply":"",'
            '"clarification":null}'
        ),
        "A proposal is not execution and is not user confirmation.",
        "confidence must be a finite number from 0 through 1; bool is forbidden.",
        "reply must be a string of at most 2000 characters.",
        (
            "CLARIFY requires a nonblank clarification of at most 500 characters; "
            "all other actions require clarification to be null or blank."
        ),
        "Never invent ids, dates, times, names, targets, or choices.",
        "Resolve relative dates to absolute DATE/DUE_AT values before emitting JSON.",
        "Use CLARIFY with a short clarification when a required slot is missing.",
        "Use NONE for ordinary conversation.",
        "Slot atom formats:",
        _ATOM_FORMATS,
        "Allowed actions and slots:",
        *[_render_action_spec(action, ACTION_SPECS[action]) for action in ActionName],
    ]
)


__all__ = [
    "ACTION_PROTOCOL_PROMPT",
    "ACTION_SPECS",
    "MAX_JSON_INTEGER_DIGITS",
    "MAX_JSON_NESTING",
    "ActionName",
    "ActionProposal",
    "ActionSpec",
    "ActionValidationError",
    "JsonScalar",
    "JsonValue",
    "ParsedAIResponse",
    "SlotRule",
    "consume_inert_html",
    "consume_reasoning_tags",
    "is_complete_generic_html_tag",
    "is_suspected_action_candidate_line",
    "is_valid_standalone_action_line",
    "parse_ai_response",
    "parse_fence_line",
    "strip_suspected_protocol_lines",
    "validate_action_object",
]
