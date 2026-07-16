"""Send-free orchestration for validated model and pending actions."""

from __future__ import annotations

import asyncio
import copy
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from ai.action_schema import (
    ActionName,
    parse_ai_response,
    strip_suspected_protocol_lines,
)
from ai.response_cleaner import ResponseCleaningError, clean_thinking_response
from cal_system.temporal_resolver import TemporalResolver
from core.action_bridge import (
    ActionBridge,
    ActionBridgeContext,
    validate_route_payload,
)
from core.confirmation_display import (
    confirmation_display_identity,
    display_confirmation_value,
)
from core.dispatch_result import DispatchCancelled, DispatchOutcome
from core.intent_display import INTENT_DISPLAY_LABELS
from core.intent_models import BotIntent, IntentResult, IntentRisk
from core.intent_payloads import (
    ENVELOPE_KEYS,
    PayloadValidationError,
)
from core.message_context import (
    ConversationKey,
    RoutingContext,
    conversation_key_from_message,
)
from core.nlu_metrics import NLUMetrics
from core.pending_actions import (
    PendingAction,
    PendingActionStore,
    PendingKind,
    PendingStatus,
    PendingTargetFamily,
    PendingTargetGuard,
    neutralize_discord_text,
)
from core.utterance import NormalizedUtterance


class ModelDisposition(str, Enum):
    ORDINARY = "ordinary"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AIModelOutcome:
    visible_text: str
    route: IntentResult | None = None
    parser_errors: tuple[str, ...] = ()
    disposition: ModelDisposition = ModelDisposition.ORDINARY


@dataclass(frozen=True, slots=True)
class PendingPresentationSpec:
    kind: PendingKind
    routes: tuple[IntentResult, ...]
    target_guards: tuple[PendingTargetGuard | None, ...]
    summary: str
    messages: tuple[str, ...]
    correction_action_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionFlowOutcome:
    text: str = ""
    route: IntentResult | None = None
    target_guard: PendingTargetGuard | None = None
    presentation: PendingPresentationSpec | None = None
    dispatch: DispatchOutcome | None = None
    decision_route: IntentResult | None = None
    decision_outcome: str | None = None

    @property
    def response_sent(self) -> bool:
        return bool(self.dispatch and self.dispatch.response_sent)


ClaimedDispatch = Callable[
    [object, PendingAction, datetime],
    Awaitable[DispatchOutcome],
]


class PendingCorrectionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class UnsupportedConfirmationSummary(ValueError):
    def __init__(self, code: str = "unsupported_confirmation_summary"):
        self.code = code
        super().__init__(code)


class ConfirmationPreviewTooLarge(ValueError):
    def __init__(self, code: str = "confirmation_preview_too_large"):
        self.code = code
        super().__init__(code)


def _parsed_action_metric(code: str) -> str:
    base = code.split(":", 1)[0]
    if base in {
        "invalid_json",
        "unknown_action",
        "multiple_proposals",
    }:
        return base
    if base in {"unknown_key", "unknown_slot"}:
        return "unknown_key"
    if base in {
        "missing_slot",
        "at_least_one_slot_required",
        "exactly_one_slot_required",
    }:
        return "missing_slot"
    if base.startswith("invalid_") or base in {
        "inconsistent_temporal",
        "unexpected_clarification",
    }:
        return "invalid_slot"
    return "other"


def _payload_action_metric(code: str) -> str:
    if code == "unknown_key":
        return "unknown_key"
    if code.startswith("missing_"):
        return "missing_slot"
    return "invalid_slot"


def _bounded_parser_errors(errors: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_parsed_action_metric(code) for code in errors))


_INVALID_ACTION_COPY = (
    "Jeg utførte ingen handling fordi forslaget ikke kunne valideres. "
    "Formuler ønsket på nytt."
)
_BLOCKED_ACTION_COPY = (
    "Jeg utførte ingen handling fordi forespørselen ikke passerte "
    "sikkerhetskontrollen."
)
_STAGED_ACTION_COPY = "Jeg har forberedt handlingen, men ikke utført den."


def _inert_model_visible_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        cleaned = clean_thinking_response(value)
    except ResponseCleaningError:
        return ""
    return strip_suspected_protocol_lines(cleaned).strip()


def neutralize_confirmation_value(value: object) -> str:
    return neutralize_discord_text(value)


def sanitize_visible_prefix(value: object, *, limit: int = 1000) -> str:
    """Return bounded optional prose; authoritative values are never cut."""

    if limit < 0:
        raise ValueError("negative_prefix_limit")
    return neutralize_confirmation_value(value)[:limit].rstrip("\\")


_CONFIRMATION_OPERATIONS = {
    BotIntent.CALENDAR_ITEM: "opprette kalenderoppføringen",
    BotIntent.CALENDAR_EDIT: "endre kalenderoppføringen",
    BotIntent.CALENDAR_DELETE: "slette kalenderoppføringen",
    BotIntent.CALENDAR_COMPLETE: "fullføre kalenderoppføringen",
    BotIntent.CALENDAR_CLEAR: "tømme hele kalenderen",
    BotIntent.CALENDAR_SYNC: "synkronisere kalenderen",
    BotIntent.CALENDAR_AUTH: "koble til Google Kalender",
    BotIntent.REMINDER_CREATE: "opprette påminnelsen",
    BotIntent.REMINDER_EDIT: "endre påminnelsen",
    BotIntent.REMINDER_DELETE: "slette påminnelsen",
    BotIntent.REMINDER_COMPLETE: "fullføre påminnelsen",
    BotIntent.POLL_CREATE: "opprette avstemningen",
    BotIntent.POLL_VOTE: "stemme i avstemningen",
    BotIntent.POLL_EDIT: "endre avstemningen",
    BotIntent.POLL_DELETE: "slette avstemningen",
    BotIntent.POLL_CLOSE: "lukke avstemningen",
    BotIntent.WATCHLIST: "endre se-listen",
    BotIntent.QUOTE: "lagre sitatet",
    BotIntent.QUOTE_EDIT: "endre sitatet",
    BotIntent.QUOTE_DELETE: "slette sitatet",
    BotIntent.BIRTHDAY_CREATE: "lagre bursdagen",
    BotIntent.BIRTHDAY_EDIT: "endre bursdagen",
    BotIntent.MEMORY_DELETE: "slette det jeg husker om deg",
    BotIntent.SET_LOCATION: "lagre bostedet",
    BotIntent.PROFILE: "endre profilen min",
}
_CONFIRMATION_ACTION_OPERATIONS = {
    (BotIntent.WATCHLIST, "add"): "legge til i se-listen",
    (BotIntent.WATCHLIST, "edit"): "endre elementet i se-listen",
    (BotIntent.WATCHLIST, "remove"): "fjerne elementet fra se-listen",
    (BotIntent.WATCHLIST, "status"): "vise se-listen",
    (BotIntent.WATCHLIST, "suggest"): "foreslå fra se-listen",
    (BotIntent.QUOTE, "save"): "lagre sitatet",
    (BotIntent.QUOTE, "get"): "vise et sitat",
    (BotIntent.PROFILE, "status"): "endre statusen min",
    (BotIntent.PROFILE, "playing"): "vise hva jeg spiller",
    (BotIntent.PROFILE, "watching"): "vise hva jeg ser på",
}
_CONFIRMATION_FIELD_LABELS = {
    "title": "tittel",
    "text": "tekst",
    "date": "dato",
    "days_offset": "dager fra nå",
    "time": "tid",
    "due_date": "dato",
    "due_at": "tidspunkt",
    "timezone": "tidssone",
    "description": "beskrivelse",
    "recurrence": "gjentakelse",
    "recurrence_day": "gjentakelsesdag",
    "rrule_day": "gjentakelsesdag",
    "item_type": "type",
    "type": "type",
    "question": "spørsmål",
    "options": "alternativer",
    "option": "valg",
    "genre": "sjanger",
    "comment": "kommentar",
    "author": "forfatter",
    "day": "dag",
    "month": "måned",
    "year": "år",
    "city": "sted",
    "status": "status",
    "activity": "aktivitet",
    "value": "verdi",
    "display_name": "person",
    "changes": "endringer",
}
_CONFIRMATION_METADATA_KEYS = frozenset(
    {
        *ENVELOPE_KEYS.values(),
        "memory",
        "profile",
        "action",
        "lang",
        "number",
        "index",
        "target",
        "reminder_id",
        "poll_id",
        "item_id",
        "user_id",
        "scope",
        "confirmed",
        "all",
    }
)
_AUTH_SECRET_KEYS = frozenset(
    {"code", "token", "state", "secret", "oauth_code", "auth_code"}
)


def _has_auth_secret(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    for key, nested in value.items():
        if isinstance(key, str) and key.casefold() in _AUTH_SECRET_KEYS:
            if isinstance(nested, str) and nested.strip():
                return True
            continue
        if _has_auth_secret(nested):
            return True
    return False


def _render_material_fields(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        raise UnsupportedConfirmationSummary()
    rendered: list[str] = []
    for key, nested in value.items():
        if not isinstance(key, str):
            raise UnsupportedConfirmationSummary()
        if key in _CONFIRMATION_METADATA_KEYS:
            if isinstance(nested, Mapping):
                rendered.extend(_render_material_fields(nested))
            continue
        label = _CONFIRMATION_FIELD_LABELS.get(key)
        if label is None:
            raise UnsupportedConfirmationSummary()
        if isinstance(nested, Mapping):
            children = _render_material_fields(nested)
            rendered.append(f"{label}: " + "; ".join(children))
        elif isinstance(nested, (list, tuple)):
            values = [
                f"{index}. {neutralize_confirmation_value(item)}"
                for index, item in enumerate(nested, start=1)
            ]
            rendered.append(f"{label}: " + "; ".join(values))
        else:
            shown = (
                "fjern"
                if nested is None
                else neutralize_confirmation_value(nested)
            )
            rendered.append(f"{label}: {shown}")
    return rendered


def _inner_action(route: IntentResult) -> str | None:
    for value in route.payload.values():
        if isinstance(value, Mapping):
            action = value.get("action")
            if isinstance(action, str):
                return action
    return None


def _confirmation_operation(route: IntentResult) -> str:
    inner_action = _inner_action(route)
    operation = (
        _CONFIRMATION_ACTION_OPERATIONS.get((route.intent, inner_action))
        if inner_action is not None
        else None
    )
    if operation is None:
        operation = _CONFIRMATION_OPERATIONS.get(route.intent)
    if operation is None:
        raise UnsupportedConfirmationSummary()
    if route.intent is BotIntent.CALENDAR_AUTH and _has_auth_secret(
        route.payload
    ):
        return "sende inn kalenderkoden"
    return operation


def format_confirmation_details(
    route: IntentResult,
    target_guard: PendingTargetGuard | None,
) -> str:
    operation = _confirmation_operation(route)
    if route.intent is BotIntent.CALENDAR_AUTH:
        if _has_auth_secret(route.payload):
            return (
                "sende inn den oppgitte kalenderkoden "
                "(selve koden vises ikke)"
            )
        return operation
    if route.intent is BotIntent.MEMORY_DELETE:
        return operation
    if route.intent is BotIntent.CALENDAR_SYNC:
        return operation
    parts = [operation]
    if target_guard is not None:
        parts.append(f"mål: {target_guard.display_detail}")
    parts.extend(_render_material_fields(route.payload))
    return "; ".join(parts)


_PRIMARY_CONFIRMATION_FIELDS = frozenset(
    {"tittel", "tekst", "spørsmål", "person", "omfang"}
)
_EDIT_CONFIRMATION_INTENTS = frozenset(
    {
        BotIntent.CALENDAR_EDIT,
        BotIntent.REMINDER_EDIT,
        BotIntent.POLL_EDIT,
        BotIntent.QUOTE_EDIT,
        BotIntent.BIRTHDAY_EDIT,
    }
)
_DELETE_CONFIRMATION_INTENTS = frozenset(
    {
        BotIntent.CALENDAR_DELETE,
        BotIntent.REMINDER_DELETE,
        BotIntent.POLL_DELETE,
        BotIntent.QUOTE_DELETE,
    }
)
_COMPLETE_CONFIRMATION_INTENTS = frozenset(
    {
        BotIntent.CALENDAR_COMPLETE,
        BotIntent.REMINDER_COMPLETE,
        BotIntent.POLL_CLOSE,
    }
)
_TARGET_PRIMARY_LABELS = {
    PendingTargetFamily.CALENDAR: "tittel",
    PendingTargetFamily.REMINDER: "tekst",
    PendingTargetFamily.POLL: "spørsmål",
    PendingTargetFamily.WATCHLIST: "tittel",
    PendingTargetFamily.QUOTE: "tekst",
    PendingTargetFamily.BIRTHDAY: "person",
}
_DOMAIN_CONFIRMATION_ICONS = {
    BotIntent.CALENDAR_ITEM: "📅",
    BotIntent.REMINDER_CREATE: "🔔",
    BotIntent.POLL_CREATE: "🗳️",
    BotIntent.WATCHLIST: "🎬",
    BotIntent.QUOTE: "📝",
    BotIntent.BIRTHDAY_CREATE: "🎂",
    BotIntent.SET_LOCATION: "📍",
    BotIntent.PROFILE: "👤",
}
_MAX_BOLD_HEADLINE_LENGTH = 200
_OSLO = ZoneInfo("Europe/Oslo")


def _material_confirmation_fields(
    value: object,
    *,
    none_means_remove: bool = False,
) -> list[tuple[str, str]]:
    if not isinstance(value, Mapping):
        raise UnsupportedConfirmationSummary()
    rendered: list[tuple[str, str]] = []
    for key, nested in value.items():
        if not isinstance(key, str):
            raise UnsupportedConfirmationSummary()
        if key in _CONFIRMATION_METADATA_KEYS:
            if isinstance(nested, Mapping):
                rendered.extend(
                    _material_confirmation_fields(
                        nested,
                        none_means_remove=none_means_remove,
                    )
                )
            continue
        label = _CONFIRMATION_FIELD_LABELS.get(key)
        if label is None:
            raise UnsupportedConfirmationSummary()
        if isinstance(nested, Mapping):
            children = _material_confirmation_fields(
                nested,
                none_means_remove=(none_means_remove or key == "changes"),
            )
            if key == "changes":
                rendered.extend(children)
            else:
                rendered.append(
                    (
                        label,
                        "; ".join(
                            f"{child_label}: {child_value}"
                            for child_label, child_value in children
                        ),
                    )
                )
        elif isinstance(nested, (list, tuple)):
            rendered.append(
                (
                    label,
                    "; ".join(
                        f"{index}. {neutralize_confirmation_value(item)}"
                        for index, item in enumerate(nested, start=1)
                    ),
                )
            )
        else:
            if nested is None and not none_means_remove:
                continue
            rendered.append(
                (
                    label,
                    "fjern"
                    if nested is None
                    else neutralize_confirmation_value(nested),
                )
            )
    return rendered


def _display_label(value: str) -> str:
    return value[:1].upper() + value[1:]


def _combine_birthday_date_fields(
    fields: list[tuple[str, str]],
    *,
    label: str,
) -> list[tuple[str, str]]:
    positions = {
        field_label: index
        for index, (field_label, _) in enumerate(fields)
        if field_label in {"dag", "måned", "år"}
    }
    if "dag" not in positions or "måned" not in positions:
        return fields
    values = dict(fields)
    day = values["dag"]
    month = values["måned"]
    year = values.get("år")
    if not day.isdecimal() or not month.isdecimal() or (
        year is not None and not year.isdecimal()
    ):
        return fields
    rendered = f"{int(day):02d}.{int(month):02d}"
    if year is not None:
        rendered += f".{int(year)}"
    first_position = min(positions.values())
    combined = [
        field
        for field in fields
        if field[0] not in {"dag", "måned", "år"}
    ]
    combined.insert(first_position, (label, rendered))
    return combined


def _normalize_confirmation_time_fields(
    fields: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    labels = {label for label, _ in fields}
    has_explicit_date = any(
        label == "dato" and value != "fjern" for label, value in fields
    )
    has_local_time = bool({"dato", "tid"} & labels)
    normalized = [
        field
        for field in fields
        if not (has_explicit_date and field[0] == "dager fra nå")
    ]
    due_at = next(
        (
            (index, value)
            for index, (label, value) in enumerate(normalized)
            if label == "tidspunkt"
        ),
        None,
    )
    if due_at is not None and not has_local_time and due_at[1] != "fjern":
        index, value = due_at
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("naive_due_at")
            local = parsed.astimezone(_OSLO)
        except (OverflowError, ValueError):
            pass
        else:
            normalized[index:index + 1] = [
                ("dato", local.strftime("%d.%m.%Y")),
                ("tid", local.strftime("%H:%M")),
            ]
            has_local_time = True
    if has_local_time:
        normalized = [
            field
            for field in normalized
            if field[0] not in {"tidspunkt", "tidssone"}
        ]
    return normalized


def _deduplicate_confirmation_fields(
    fields: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    deduplicated: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for label, value in fields:
        label_key = label.casefold()
        value_key = confirmation_display_identity(label, value)
        previous = seen.get(label_key)
        if previous == value_key:
            continue
        if previous is not None:
            raise UnsupportedConfirmationSummary(
                "conflicting_confirmation_fields"
            )
        seen[label_key] = value_key
        deduplicated.append((label, value))
    return deduplicated


def _format_confirmation_fields(
    fields: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    *,
    headline: str | None,
) -> list[str]:
    remaining = _deduplicate_confirmation_fields(
        _normalize_confirmation_time_fields(list(fields))
    )
    lines: list[str] = []
    if headline and len(headline) <= _MAX_BOLD_HEADLINE_LENGTH:
        lines.append(f"**{headline}**")
        for index, (label, value) in enumerate(remaining):
            if label in _PRIMARY_CONFIRMATION_FIELDS and value == headline:
                remaining.pop(index)
                break

    date_index = next(
        (
            index
            for index, (label, value) in enumerate(remaining)
            if label == "dato" and value != "fjern"
        ),
        None,
    )
    time_index = next(
        (
            index
            for index, (label, value) in enumerate(remaining)
            if label == "tid" and value != "fjern"
        ),
        None,
    )
    if date_index is not None:
        _, date_value = remaining[date_index]
        time_value = remaining[time_index][1] if time_index is not None else None
        line = f"📅 {date_value}"
        if time_value:
            line += f" kl. {time_value}"
        lines.append(line)
        consumed = {date_index}
        if time_index is not None:
            consumed.add(time_index)
        remaining = [
            field for index, field in enumerate(remaining) if index not in consumed
        ]
    elif time_index is not None:
        _, time_value = remaining.pop(time_index)
        lines.append(f"🕒 {time_value}")

    lines.extend(
        f"**{_display_label(label)}:** {display_confirmation_value(label, value)}"
        for label, value in remaining
    )
    return lines


def _fallback_target_lines(target_guard: PendingTargetGuard) -> list[str]:
    lines = [f"**{target_guard.label}**"]
    detail = target_guard.display_detail
    primary = _TARGET_PRIMARY_LABELS.get(target_guard.family)
    prefixes = [target_guard.label]
    if primary is not None:
        prefixes.insert(0, f"{primary}: {target_guard.label}")
    for prefix in prefixes:
        if detail == prefix:
            detail = ""
            break
        marker = f"{prefix}; "
        if detail.startswith(marker):
            detail = detail[len(marker):]
            break
    if detail:
        lines.append(detail[:1].upper() + detail[1:])
    return lines


def _confirmation_icon(route: IntentResult) -> str:
    inner_action = _inner_action(route)
    if route.intent in {BotIntent.CALENDAR_CLEAR, BotIntent.MEMORY_DELETE}:
        return "⚠️"
    if route.intent in _DELETE_CONFIRMATION_INTENTS or inner_action in {
        "delete",
        "remove",
    }:
        return "🗑️"
    if route.intent in _EDIT_CONFIRMATION_INTENTS or inner_action == "edit":
        return "✏️"
    if route.intent in _COMPLETE_CONFIRMATION_INTENTS:
        return "✅"
    if route.intent is BotIntent.CALENDAR_AUTH:
        return "🔐"
    if route.intent is BotIntent.CALENDAR_SYNC:
        return "🔄"
    if route.intent is BotIntent.POLL_VOTE:
        return "🗳️"
    return _DOMAIN_CONFIRMATION_ICONS.get(route.intent, "➕")


def format_confirmation_card_heading(route: IntentResult) -> str:
    operation = _confirmation_operation(route)
    return f"{_confirmation_icon(route)} **Skal jeg {operation}?**"


def format_confirmation_card_details(
    route: IntentResult,
    target_guard: PendingTargetGuard | None,
) -> str:
    if route.intent is BotIntent.CALENDAR_AUTH and _has_auth_secret(
        route.payload
    ):
        return "Den oppgitte kalenderkoden sendes inn. Selve koden vises ikke."

    if route.intent is BotIntent.CALENDAR_CLEAR and target_guard is not None:
        count = next(
            (
                value
                for label, value in target_guard.display_fields
                if label == "oppføringer"
            ),
            None,
        )
        if count is not None:
            if count == "1":
                return "Hele **1 oppføring** blir slettet."
            return f"Alle **{count} oppføringer** blir slettet."

    lines: list[str] = []
    if target_guard is not None and route.intent is not BotIntent.MEMORY_DELETE:
        if target_guard.display_fields:
            headline = target_guard.label
            primary_label = _TARGET_PRIMARY_LABELS.get(target_guard.family)
            primary_value = next(
                (
                    value
                    for label, value in target_guard.display_fields
                    if label == primary_label
                ),
                None,
            )
            if primary_value is not None and primary_value != headline:
                headline = None
            lines.extend(
                _format_confirmation_fields(
                    target_guard.display_fields,
                    headline=headline,
                )
            )
        else:
            lines.extend(_fallback_target_lines(target_guard))

    birthday_guard_has_date = bool(
        route.intent is BotIntent.BIRTHDAY_CREATE
        and target_guard is not None
        and any(label == "dato" for label, _ in target_guard.display_fields)
    )
    if route.intent in {BotIntent.CALENDAR_SYNC, BotIntent.MEMORY_DELETE} or (
        birthday_guard_has_date
    ):
        fields = []
    else:
        fields = _material_confirmation_fields(
            route.payload,
            none_means_remove=(
                route.intent is BotIntent.WATCHLIST
                and _inner_action(route) == "edit"
            ),
        )
    if route.intent in {BotIntent.BIRTHDAY_CREATE, BotIntent.BIRTHDAY_EDIT}:
        fields = _combine_birthday_date_fields(
            fields,
            label=(
                "ny dato"
                if route.intent is BotIntent.BIRTHDAY_EDIT
                and target_guard is not None
                else "dato"
            ),
        )
    if route.intent is BotIntent.PROFILE:
        profile_label = (
            "status" if _inner_action(route) == "status" else "aktivitet"
        )
        fields = [
            (profile_label if label == "verdi" else label, value)
            for label, value in fields
        ]
    if (
        route.intent is BotIntent.POLL_VOTE
        and target_guard is not None
        and any(label == "valg" for label, _ in target_guard.display_fields)
    ):
        fields = [field for field in fields if field[0] != "valg"]
    if fields:
        if lines and (
            route.intent in _EDIT_CONFIRMATION_INTENTS
            or _inner_action(route) == "edit"
        ):
            lines.extend(("", "**Endringer**"))
        headline = None
        if not lines:
            headline = next(
                (
                    value
                    for label, value in fields
                    if label in _PRIMARY_CONFIRMATION_FIELDS
                ),
                None,
            )
        lines.extend(_format_confirmation_fields(fields, headline=headline))

    return "\n".join(lines)


def _lossless_chunks(text: str, limit: int) -> tuple[str, ...]:
    if limit <= 0:
        raise ConfirmationPreviewTooLarge()
    chunks: list[str] = []
    remaining = text
    while remaining:
        cut = min(limit, len(remaining))
        if cut < len(remaining):
            newline = remaining.rfind("\n", 0, cut + 1)
            if newline >= 0 and newline >= cut - 128:
                cut = newline + 1
        trailing_backslashes = len(remaining[:cut]) - len(
            remaining[:cut].rstrip("\\")
        )
        if trailing_backslashes % 2:
            cut -= 1
        if cut == 0:
            raise ConfirmationPreviewTooLarge()
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    return tuple(chunks) or ("",)


def format_confirmation_messages(
    *,
    details: str,
    instruction: str,
    optional_prefix: str,
    max_messages: int,
    max_message_length: int,
) -> tuple[str, ...]:
    if max_messages < 1 or max_message_length < 1:
        raise ConfirmationPreviewTooLarge()
    reserved = len(
        f"Bekreftelsesdetaljer {max_messages}/{max_messages}:\n"
        f"\n{instruction}"
    )
    pieces = _lossless_chunks(
        details,
        min(1700, max_message_length - reserved),
    )
    if len(pieces) > max_messages:
        raise ConfirmationPreviewTooLarge()
    messages: list[str] = []
    total = len(pieces)
    for index, piece in enumerate(pieces, start=1):
        header = f"Bekreftelsesdetaljer {index}/{total}:\n"
        suffix = f"\n{instruction}" if index == total else ""
        prefix_budget = (
            max_message_length - len(header) - len(piece) - len(suffix) - 2
        )
        prefix = (
            sanitize_visible_prefix(optional_prefix, limit=max(0, prefix_budget))
            if index == 1
            else ""
        )
        message = f"{prefix}\n\n" if prefix else ""
        message += header + piece + suffix
        if len(message) > max_message_length:
            raise ConfirmationPreviewTooLarge()
        messages.append(message)
    return tuple(messages)


def format_confirmation_card_messages(
    *,
    heading: str,
    details: str,
    instruction: str,
    optional_prefix: str,
    max_messages: int,
    max_message_length: int,
) -> tuple[str, ...]:
    if (
        not isinstance(heading, str)
        or not heading
        or "\n" in heading
        or len(heading) > 300
        or max_messages < 1
        or max_message_length < 1
    ):
        raise ConfirmationPreviewTooLarge()
    continuation_marker = "↪ "
    reserved = len(
        f"{heading} _(del {max_messages} av {max_messages})_\n\n"
        f"\n\n{instruction}"
    ) + len(continuation_marker)
    pieces = _lossless_chunks(
        details,
        max_message_length - reserved,
    )
    if len(pieces) > max_messages:
        raise ConfirmationPreviewTooLarge()

    messages: list[str] = []
    total = len(pieces)
    for index, piece in enumerate(pieces, start=1):
        header = (
            heading
            if total == 1
            else f"{heading} _(del {index} av {total})_"
        )
        suffix = instruction if index == total else ""
        piece_prefix = continuation_marker if index > 1 and piece else ""
        fixed_size = len(header) + len(piece_prefix) + len(piece) + len(suffix)
        if piece:
            fixed_size += 2
        if suffix:
            fixed_size += 2
        prefix_budget = max_message_length - fixed_size - 2
        prefix = (
            sanitize_visible_prefix(optional_prefix, limit=max(0, prefix_budget))
            if index == 1
            else ""
        )
        message = f"{prefix}\n\n" if prefix else ""
        message += header
        if piece:
            message += f"\n\n{piece_prefix}{piece}"
        if suffix:
            message += f"\n\n{suffix}"
        if len(message) > max_message_length:
            raise ConfirmationPreviewTooLarge()
        messages.append(message)
    return tuple(messages)


def format_choice_label(
    route: IntentResult,
    guard: PendingTargetGuard | None,
) -> str:
    inner_action = _inner_action(route)
    operation = (
        _CONFIRMATION_ACTION_OPERATIONS.get((route.intent, inner_action))
        if inner_action is not None
        else None
    )
    if operation is None:
        operation = _CONFIRMATION_OPERATIONS.get(
            route.intent,
            INTENT_DISPLAY_LABELS.get(route.intent),
        )
    if operation is None:
        raise UnsupportedConfirmationSummary("missing_choice_label")
    raw = f"{operation}: {guard.label}" if guard is not None else operation
    return neutralize_confirmation_value(raw)[:200].rstrip("\\")


_TEXT_CHANGE = re.compile(
    r"^(?:tittel|tekst|navn|spørsmål|question|kall den|endre tittel til|"
    r"endre teksten til|endre til|i stedet|isteden|heller)"
    r"\s*[:\-]?\s*(.+)$",
    re.IGNORECASE,
)
_NAMED_TEXT_CHANGE = re.compile(
    r"^(?:tittel|tekst|navn|spørsmål|question|kall den|endre tittel til|"
    r"endre teksten til)\b",
    re.IGNORECASE,
)
_OPTIONS_CHANGE = re.compile(
    r"^(?:alternativer?|valg|options?)\s*[:\-]?\s*(.+)$",
    re.IGNORECASE,
)
_DATE_EVIDENCE_LABELS = frozenset(
    {
        "date_alias",
        "numeric_date",
        "month_date",
        "day_of_month",
        "weekday",
    }
)
_TIME_EVIDENCE_LABELS = frozenset(
    {"natural_time", "raw_time", "special_hour", "daypart"}
)
_ANCHOR_TODAY_DAYPART = re.compile(
    r"(?<!\w)(?:i\s+(?:morges|formiddag|ettermiddag|kveld|natt)|"
    r"this\s+(?:morning|afternoon|evening)|tonight)(?!\w)",
    re.IGNORECASE,
)


def _child_mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise PendingCorrectionError("invalid_pending_payload")
    return value


def _apply_temporal(
    payload: dict[str, object],
    route: IntentResult,
    utterance: NormalizedUtterance,
    resolver: TemporalResolver,
    reference: datetime,
) -> bool:
    stripped = utterance.text.strip()
    if (
        _NAMED_TEXT_CHANGE.search(stripped) is not None
        or _OPTIONS_CHANGE.fullmatch(stripped) is not None
    ):
        return False
    resolved = resolver.resolve(utterance.text, reference=reference)
    if not resolved.matched_text:
        return False
    if not resolved.valid:
        raise PendingCorrectionError("invalid_temporal")
    labels = frozenset(resolved.matched_text)
    explicit_date = bool(labels & _DATE_EVIDENCE_LABELS) or (
        "relative" in labels
    )
    if "daypart" in labels and _ANCHOR_TODAY_DAYPART.search(utterance.text):
        explicit_date = True
    explicit_time = bool(labels & _TIME_EVIDENCE_LABELS) or (
        "relative" in labels
    )
    if explicit_date and resolved.date is None:
        raise PendingCorrectionError("invalid_temporal")
    if explicit_time and resolved.time is None:
        raise PendingCorrectionError("invalid_temporal")
    if not (explicit_date or explicit_time):
        raise PendingCorrectionError("invalid_temporal")
    if route.intent is BotIntent.CALENDAR_ITEM:
        item = _child_mapping(payload, "calendar_item")
        if explicit_date:
            item["date"] = resolved.date
            item.pop("days_offset", None)
        if explicit_time:
            item["time"] = resolved.time
        return True
    if route.intent is BotIntent.CALENDAR_EDIT:
        edit = _child_mapping(payload, "calendar_edit")
        changes = _child_mapping(edit, "changes")
        if explicit_date:
            changes["date"] = resolved.date
        if explicit_time:
            changes["time"] = resolved.time
        return True
    if route.intent in {BotIntent.REMINDER_CREATE, BotIntent.REMINDER_EDIT}:
        reminder = _child_mapping(payload, "reminder")
        target = (
            _child_mapping(reminder, "changes")
            if reminder.get("action") == "edit"
            else reminder
        )
        existing_date = target.get("due_date")
        existing_time = target.get("time")
        due_at = target.get("due_at")
        aliases_incomplete = not isinstance(
            existing_date,
            str,
        ) or not isinstance(existing_time, str)
        if aliases_incomplete and isinstance(due_at, str):
            try:
                parsed_due_at = datetime.fromisoformat(
                    due_at.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise PendingCorrectionError("invalid_temporal") from exc
            if (
                parsed_due_at.tzinfo is None
                or parsed_due_at.utcoffset() is None
            ):
                raise PendingCorrectionError("invalid_temporal")
            local_due_at = parsed_due_at.astimezone(resolver.zone)
            if not isinstance(existing_date, str):
                existing_date = local_due_at.strftime("%d.%m.%Y")
            if not isinstance(existing_time, str):
                existing_time = local_due_at.strftime("%H:%M")

        merged_date = resolved.date if explicit_date else existing_date
        merged_time = resolved.time if explicit_time else existing_time
        for name in ("due_date", "time", "due_at", "timezone"):
            target.pop(name, None)

        if isinstance(merged_date, str):
            if merged_time is not None and not isinstance(merged_time, str):
                raise PendingCorrectionError("invalid_temporal")
            canonical = resolver.validate_fields(
                merged_date,
                merged_time,
                reference=reference,
            )
            if not canonical.valid or canonical.date is None:
                raise PendingCorrectionError("invalid_temporal")
            target["due_date"] = canonical.date
            if canonical.time is not None:
                target["time"] = canonical.time
            if canonical.due_at is not None:
                target["due_at"] = canonical.due_at
            target["timezone"] = "Europe/Oslo"
        elif isinstance(merged_time, str):
            if route.intent is BotIntent.REMINDER_CREATE:
                raise PendingCorrectionError("missing_date")
            canonical_time = resolver.validate_time(merged_time)
            if canonical_time is None:
                raise PendingCorrectionError("invalid_temporal")
            target["time"] = canonical_time
            target["timezone"] = "Europe/Oslo"
        else:
            raise PendingCorrectionError("invalid_temporal")
        return True
    return False


def _apply_text_change(
    payload: dict[str, object],
    route: IntentResult,
    utterance: NormalizedUtterance,
    *,
    temporal_applied: bool,
) -> bool:
    match = _TEXT_CHANGE.fullmatch(utterance.text.strip())
    if match is None:
        return False
    prefix = utterance.text[: match.start(1)].casefold()
    if temporal_applied and not any(
        token in prefix for token in ("tittel", "tekst", "navn", "kall den")
    ):
        return False
    value = match.group(1).strip()
    if not value:
        raise PendingCorrectionError("blank_correction")
    if route.intent is BotIntent.CALENDAR_ITEM:
        _child_mapping(payload, "calendar_item")["title"] = value
        return True
    if route.intent is BotIntent.CALENDAR_EDIT:
        edit = _child_mapping(payload, "calendar_edit")
        _child_mapping(edit, "changes")["title"] = value
        return True
    if route.intent is BotIntent.REMINDER_CREATE:
        _child_mapping(payload, "reminder")["text"] = value
        return True
    if route.intent is BotIntent.REMINDER_EDIT:
        reminder = _child_mapping(payload, "reminder")
        _child_mapping(reminder, "changes")["text"] = value
        return True
    if route.intent is BotIntent.POLL_CREATE:
        _child_mapping(payload, "poll")["question"] = value
        return True
    if route.intent is BotIntent.POLL_EDIT:
        _child_mapping(payload, "poll_edit")["question"] = value
        return True
    return False


def _apply_options_change(
    payload: dict[str, object],
    route: IntentResult,
    utterance: NormalizedUtterance,
) -> bool:
    match = _OPTIONS_CHANGE.fullmatch(utterance.text.strip())
    if match is None or route.intent not in {
        BotIntent.POLL_CREATE,
        BotIntent.POLL_EDIT,
    }:
        return False
    options = [
        item.strip()
        for item in re.split(r"\s*(?:\||,)\s*", match.group(1))
        if item.strip()
    ]
    key = "poll" if route.intent is BotIntent.POLL_CREATE else "poll_edit"
    _child_mapping(payload, key)["options"] = options
    return True


def apply_pending_correction(
    route: IntentResult,
    utterance: NormalizedUtterance,
    resolver: TemporalResolver,
    *,
    reference: datetime,
) -> IntentResult:
    payload = copy.deepcopy(route.payload)
    temporal = _apply_temporal(payload, route, utterance, resolver, reference)
    text = _apply_text_change(
        payload,
        route,
        utterance,
        temporal_applied=temporal,
    )
    options = _apply_options_change(payload, route, utterance)
    if not (temporal or text or options):
        raise PendingCorrectionError("unsupported_correction")
    payload = validate_route_payload(
        route.intent,
        payload,
        source=route.source,
    )
    return replace(route, payload=payload, requires_confirmation=True)


class AIActionHandler:
    def __init__(
        self,
        *,
        store: PendingActionStore,
        dispatch_claimed: ClaimedDispatch,
        metrics: NLUMetrics,
        temporal_resolver: TemporalResolver,
        bridge: ActionBridge | None = None,
    ):
        if metrics is not store.metrics:
            raise ValueError("metrics_identity_mismatch")
        if bridge is not None and bridge.metrics is not metrics:
            raise ValueError("bridge_metrics_identity_mismatch")
        self.store = store
        self.metrics = metrics
        self.dispatch_claimed = dispatch_claimed
        self.bridge = bridge or ActionBridge(metrics=self.metrics)
        self.temporal_resolver = temporal_resolver

    async def handle_model_response(
        self,
        *,
        raw: str,
        utterance: NormalizedUtterance,
        routing: RoutingContext,
        reference_time: datetime,
        deterministic_route: IntentResult | None,
        active_poll_count: int | None,
        active_poll_id: str | None,
        semantic_action_allowed: bool,
    ) -> AIModelOutcome:
        try:
            cleaned = clean_thinking_response(raw)
        except ResponseCleaningError as exc:
            metric_code = _parsed_action_metric(exc.code)
            self.metrics.record_action_result(metric_code)
            return AIModelOutcome(
                visible_text=_INVALID_ACTION_COPY,
                parser_errors=(metric_code,),
                disposition=ModelDisposition.INVALID,
            )
        parsed = parse_ai_response(cleaned)
        bounded_errors = _bounded_parser_errors(parsed.errors)
        for error in parsed.errors:
            self.metrics.record_action_result(_parsed_action_metric(error))
        if parsed.proposal is None:
            return AIModelOutcome(
                visible_text=(
                    _INVALID_ACTION_COPY
                    if parsed.errors
                    else parsed.text.strip()
                ),
                parser_errors=bounded_errors,
                disposition=(
                    ModelDisposition.INVALID
                    if parsed.errors
                    else ModelDisposition.ORDINARY
                ),
            )

        safe_proposal = replace(
            parsed.proposal,
            reply=_inert_model_visible_text(parsed.proposal.reply),
            clarification=(
                _inert_model_visible_text(parsed.proposal.clarification)
                if parsed.proposal.clarification is not None
                else None
            ),
        )
        visible = parsed.text.strip() or safe_proposal.reply
        try:
            route = self.bridge.to_result(
                safe_proposal,
                ActionBridgeContext(
                    utterance=utterance,
                    routing=routing,
                    reference_time=reference_time,
                    temporal_resolver=self.temporal_resolver,
                    deterministic_route=deterministic_route,
                    active_poll_count=active_poll_count,
                    active_poll_id=active_poll_id,
                    semantic_action_allowed=semantic_action_allowed,
                ),
            )
        except PayloadValidationError as exc:
            metric_code = _payload_action_metric(exc.code)
            self.metrics.record_action_result(metric_code)
            return AIModelOutcome(
                visible_text=_INVALID_ACTION_COPY,
                parser_errors=tuple(
                    dict.fromkeys((*bounded_errors, metric_code))
                ),
                disposition=ModelDisposition.INVALID,
            )
        if route is None:
            if safe_proposal.action is ActionName.NONE:
                return AIModelOutcome(
                    visible_text=visible,
                    parser_errors=bounded_errors,
                    disposition=ModelDisposition.ORDINARY,
                )
            return AIModelOutcome(
                visible_text=_BLOCKED_ACTION_COPY,
                parser_errors=bounded_errors,
                disposition=ModelDisposition.BLOCKED,
            )
        self.metrics.record_action_result(
            "legacy" if parsed.legacy else "accepted"
        )
        if route.risk is not IntentRisk.READ_ONLY:
            visible = _STAGED_ACTION_COPY
        return AIModelOutcome(
            visible_text=visible,
            route=route,
            parser_errors=bounded_errors,
            disposition=ModelDisposition.ACCEPTED,
        )

    def _summary(
        self,
        route: IntentResult,
        target_guard: PendingTargetGuard | None = None,
    ) -> str:
        return format_confirmation_details(route, target_guard)

    def _confirmation_messages(
        self,
        message: object,
        route: IntentResult,
        *,
        prefix: str = "",
        target_guard: PendingTargetGuard | None = None,
    ) -> tuple[str, ...]:
        del message
        instruction = (
            "Svar `@inebotten ja` for å bekrefte, eller "
            "`@inebotten nei` for å avbryte."
        )
        return format_confirmation_card_messages(
            heading=format_confirmation_card_heading(route),
            details=format_confirmation_card_details(route, target_guard),
            instruction=instruction,
            optional_prefix=("" if prefix == _STAGED_ACTION_COPY else prefix),
            max_messages=5,
            max_message_length=2000,
        )

    def prepare_confirmation(
        self,
        message: object,
        route: IntentResult,
        *,
        prefix: str = "",
        target_guard: PendingTargetGuard | None = None,
    ) -> ActionFlowOutcome:
        if not route.requires_confirmation:
            raise ValueError("route_does_not_require_confirmation")
        summary = self._summary(route, target_guard)
        return ActionFlowOutcome(
            presentation=PendingPresentationSpec(
                kind=PendingKind.CONFIRMATION,
                routes=(copy.deepcopy(route),),
                target_guards=(target_guard,),
                summary=summary,
                messages=self._confirmation_messages(
                    message,
                    route,
                    prefix=prefix,
                    target_guard=target_guard,
                ),
            ),
            decision_route=route,
            decision_outcome="staged",
        )

    def prepare_choices(
        self,
        message: object,
        routes: tuple[IntentResult, ...],
        guards: tuple[PendingTargetGuard | None, ...],
        prompt: str,
    ) -> ActionFlowOutcome:
        del message
        if len(routes) != len(guards) or not 2 <= len(routes) <= 5:
            raise ValueError("invalid_choice_count")
        labels = tuple(
            format_choice_label(route, guard)
            for route, guard in zip(routes, guards, strict=True)
        )
        if len(set(labels)) != len(labels):
            raise ValueError("indistinguishable_choice_labels")
        lines = [sanitize_visible_prefix(prompt, limit=400)]
        lines.extend(
            f"{index}. {label}"
            for index, label in enumerate(labels, start=1)
        )
        lines.append(
            "Svar @inebotten etterfulgt av nummeret eller for eksempel "
            "«den andre»."
        )
        text = "\n".join(line for line in lines if line)
        if len(text) > 2000:
            raise ConfirmationPreviewTooLarge()
        return ActionFlowOutcome(
            presentation=PendingPresentationSpec(
                kind=PendingKind.CHOICE,
                routes=tuple(copy.deepcopy(route) for route in routes),
                target_guards=copy.deepcopy(guards),
                summary="Velg ett alternativ",
                messages=(text,),
            ),
            decision_outcome="clarified",
        )

    async def confirm(
        self,
        message: object,
        action_id: str,
        *,
        reference_time: datetime,
    ) -> ActionFlowOutcome:
        key = conversation_key_from_message(message)
        pending = self.store.claim(key, action_id)
        if pending is None:
            return ActionFlowOutcome(
                text="Det finnes ingen aktiv bekreftelse å utføre."
            )
        route = pending.routes[0]
        try:
            outcome = await self.dispatch_claimed(
                message,
                pending,
                reference_time,
            )
            if not isinstance(outcome, DispatchOutcome):
                raise TypeError("invalid_dispatch_outcome")
        except DispatchCancelled as exc:
            outcome = exc.outcome
            self._settle_dispatch(key, action_id, outcome)
            raise DispatchCancelled(
                outcome,
                decision_route=route,
                decision_outcome=(
                    "executed" if outcome.ok else "failed"
                ),
            ) from exc
        except asyncio.CancelledError as exc:
            self.store.fail_terminal(key, action_id)
            raise DispatchCancelled(
                DispatchOutcome.failure(
                    "cancelled",
                    retryable=False,
                    commit_unknown=(route.risk is not IntentRisk.READ_ONLY),
                ),
                decision_route=route,
                decision_outcome="failed",
            ) from exc
        except Exception:
            self.store.fail_terminal(key, action_id)
            return ActionFlowOutcome(
                text=(
                    "Jeg kunne ikke bekrefte om handlingen ble lagret. "
                    "Ikke prøv denne bekreftelsen på nytt; sjekk status først."
                ),
                dispatch=DispatchOutcome.failure(
                    "commit_state_unknown",
                    retryable=False,
                    commit_unknown=True,
                ),
                decision_route=route,
                decision_outcome="failed",
            )
        self._settle_dispatch(key, action_id, outcome)
        text = ""
        if outcome.delivery_result is None:
            if outcome.error_code == "target_changed":
                text = (
                    "Målet ble endret eller fjernet. "
                    "Be meg om handlingen på nytt."
                )
            elif outcome.commit_unknown:
                text = (
                    "Jeg kunne ikke bekrefte om handlingen ble lagret. "
                    "Ikke prøv denne bekreftelsen på nytt; sjekk status først."
                )
            elif outcome.ok:
                text = "Handlingen er utført."
            elif outcome.mutated:
                text = (
                    "Noe data ble endret, men handlingen ble ikke fullført. "
                    "Ikke prøv denne bekreftelsen på nytt; sjekk status og "
                    "be om en ny handling."
                )
            elif outcome.retryable:
                text = (
                    "Handlingen ble ikke utført. "
                    "Du kan prøve @inebotten ja på nytt."
                )
            else:
                text = (
                    "Handlingen kunne ikke utføres. "
                    "Be meg om den på nytt."
                )
        return ActionFlowOutcome(
            text=text,
            dispatch=outcome,
            decision_route=route,
            decision_outcome="executed" if outcome.ok else "failed",
        )

    def _settle_dispatch(
        self,
        key: ConversationKey,
        action_id: str,
        outcome: DispatchOutcome,
    ) -> None:
        if outcome.ok:
            self.store.complete(key, action_id)
        elif outcome.retryable and not outcome.mutated and not outcome.commit_unknown:
            self.store.release_retryable(key, action_id, outcome)
        else:
            self.store.fail_terminal(key, action_id)

    async def cancel(
        self,
        message: object,
        action_id: str,
    ) -> ActionFlowOutcome:
        key = conversation_key_from_message(message)
        pending = self.store.peek(key)
        cancelled = self.store.cancel(key, action_id)
        return ActionFlowOutcome(
            text=(
                "Avbrutt."
                if cancelled
                else "Det finnes ingen aktiv handling å avbryte."
            ),
            decision_route=(
                pending.routes[0] if cancelled and pending else None
            ),
            decision_outcome="canceled" if cancelled else None,
        )

    async def select(
        self,
        message: object,
        action_id: str,
        choice_index: int,
    ) -> ActionFlowOutcome:
        key = conversation_key_from_message(message)
        selection = self.store.consume_choice(
            key,
            action_id,
            choice_index,
        )
        if selection is None:
            return ActionFlowOutcome(text="Det valget finnes ikke lenger.")
        route = selection.route
        if route.risk is not IntentRisk.READ_ONLY:
            route = replace(route, requires_confirmation=True)
        return ActionFlowOutcome(
            route=route,
            target_guard=selection.target_guard,
        )

    async def correct(
        self,
        message: object,
        action_id: str,
        utterance: NormalizedUtterance,
        *,
        reference_time: datetime,
    ) -> ActionFlowOutcome:
        key = conversation_key_from_message(message)
        pending = self.store.peek(key)
        if (
            pending is None
            or pending.action_id != action_id
            or len(pending.routes) != 1
            or pending.status is not PendingStatus.READY
        ):
            return ActionFlowOutcome(
                text="Det finnes ingen aktiv handling å rette."
            )
        try:
            route = apply_pending_correction(
                pending.routes[0],
                utterance,
                self.temporal_resolver,
                reference=reference_time,
            )
            target_guard = pending.target_guards[0]
            summary = self._summary(route, target_guard)
            messages = self._confirmation_messages(
                message,
                route,
                target_guard=target_guard,
            )
        except (
            PendingCorrectionError,
            PayloadValidationError,
            UnsupportedConfirmationSummary,
            ConfirmationPreviewTooLarge,
        ):
            return ActionFlowOutcome(
                text=(
                    "Jeg forstod ikke rettelsen. "
                    "Oppgi ny dato, tid, tittel eller alternativer tydelig."
                )
            )
        return ActionFlowOutcome(
            presentation=PendingPresentationSpec(
                kind=PendingKind.CONFIRMATION,
                routes=(route,),
                target_guards=(target_guard,),
                summary=summary,
                messages=messages,
                correction_action_id=action_id,
            ),
            decision_route=route,
            decision_outcome="staged",
        )


__all__ = [
    "AIActionHandler",
    "AIModelOutcome",
    "ActionFlowOutcome",
    "ConfirmationPreviewTooLarge",
    "ModelDisposition",
    "PendingCorrectionError",
    "PendingPresentationSpec",
    "UnsupportedConfirmationSummary",
    "apply_pending_correction",
    "format_choice_label",
    "format_confirmation_card_details",
    "format_confirmation_card_heading",
    "format_confirmation_card_messages",
    "format_confirmation_details",
    "format_confirmation_messages",
    "neutralize_confirmation_value",
    "sanitize_visible_prefix",
]
