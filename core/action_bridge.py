"""Inert bridge from validated model proposals to typed intent results.

The bridge performs contextual validation and arbitration only.  It has no
executor, Discord, manager, persistence, or message-delivery dependency.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping

from ai.action_schema import ActionName, ActionProposal, JsonValue
from cal_system.reminder_clock import OSLO
from cal_system.temporal_resolver import TemporalResolver
from core.intent_arbitration import arbitrate_candidates
from core.intent_models import (
    BotIntent,
    IntentCandidate,
    IntentResult,
    IntentRisk,
    IntentSource,
    RejectionCode,
)
from core.intent_payloads import (
    ENVELOPE_KEYS,
    PayloadValidationError,
    validate_intent_payload,
)
from core.intent_policy import classify_intent_risk
from core.list_read_filters import (
    filtered_list_read_family,
    is_supported_calendar_read_date,
    looks_like_list_read_request,
    unfiltered_list_read_family,
)
from core.message_context import RoutingContext
from core.nlu_metrics import NLUMetrics
from core.utterance import NormalizedUtterance
from core.utterance_semantics import (
    analyze_utterance,
    bounded_english_calendar_create_head,
    bounded_english_reminder_create_head,
    has_future_weather_request,
    has_sequenced_action_request,
    has_unsupported_poll_mutation_request,
)


BRIDGE_TEMPORAL_ERROR_CODES = frozenset(
    {
        "naive_reference_time",
        "invalid_temporal",
        "conflicting_temporal_fields",
    }
)

@dataclass(frozen=True, slots=True)
class ActionBridgeContext:
    utterance: NormalizedUtterance
    routing: RoutingContext
    reference_time: datetime
    temporal_resolver: TemporalResolver
    deterministic_route: IntentResult | None = None
    active_poll_count: int | None = None
    active_poll_id: str | None = None
    semantic_action_allowed: bool = True


RouteBuilder = Callable[
    [Mapping[str, JsonValue], ActionBridgeContext],
    tuple[BotIntent, dict[str, object]] | None,
]


def _copy(slots: Mapping[str, JsonValue], *names: str) -> dict[str, JsonValue]:
    return {name: slots[name] for name in names if name in slots}


def _bridge_temporal_error(code: str) -> PayloadValidationError:
    if code not in BRIDGE_TEMPORAL_ERROR_CODES:
        raise RuntimeError("unbounded_bridge_temporal_error")
    return PayloadValidationError(code)


def _require_aware_reference(reference_time: datetime) -> None:
    if (
        not isinstance(reference_time, datetime)
        or reference_time.tzinfo is None
        or reference_time.utcoffset() is None
    ):
        raise _bridge_temporal_error("naive_reference_time")


def validate_route_payload(
    intent: BotIntent,
    payload: dict[str, object],
    *,
    source: IntentSource,
) -> dict[str, object]:
    """Return a detached payload after its canonical Task-6 validation."""

    key = ENVELOPE_KEYS.get(intent)
    if key is None:
        return copy.deepcopy(payload)
    if intent is BotIntent.CALENDAR_LIST and payload == {}:
        return {}
    if key not in payload:
        raise PayloadValidationError("missing_payload")
    normalized = copy.deepcopy(payload)
    normalized[key] = validate_intent_payload(
        intent,
        normalized[key],
        source=source,
    )
    return normalized


def _simple(intent: BotIntent, payload: dict[str, object]) -> RouteBuilder:
    def build(
        slots: Mapping[str, JsonValue],
        context: ActionBridgeContext,
    ) -> tuple[BotIntent, dict[str, object]]:
        del slots, context
        return intent, payload

    return build


def _list_date_filter(
    slots: Mapping[str, JsonValue],
    slot_name: str,
    family: str,
    context: ActionBridgeContext,
) -> tuple[bool, str | None]:
    """Resolve one semantic list date without trusting a model-invented slot."""

    try:
        resolved = context.temporal_resolver.resolve(
            context.utterance.control_text,
            reference=context.reference_time,
        )
    except (TypeError, ValueError):
        return False, None
    if (
        resolved.errors
        or resolved.time is not None
        or resolved.due_at is not None
        or (resolved.matched_text and resolved.date is None)
    ):
        return False, None
    matched_family = (
        filtered_list_read_family(context.utterance.control_text)
        if resolved.date is not None
        else unfiltered_list_read_family(context.utterance.control_text)
    )
    if matched_family != family:
        return False, None

    proposed = slots.get(slot_name)
    if proposed is not None and (
        not isinstance(proposed, str) or proposed != resolved.date
    ):
        return False, None
    return True, resolved.date


def _calendar_list(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]] | None:
    valid, date_filter = _list_date_filter(
        slots, "date", "calendar", context
    )
    if not valid:
        return None
    if date_filter is None:
        return BotIntent.CALENDAR_LIST, {}
    if not is_supported_calendar_read_date(
        date_filter,
        reference_time=context.reference_time,
    ):
        return None
    return BotIntent.CALENDAR_LIST, {"calendar_list": {"date": date_filter}}


def _reminder_list(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]] | None:
    valid, date_filter = _list_date_filter(
        slots, "due_date", "reminder", context
    )
    if not valid:
        return None
    return BotIntent.REMINDER_LIST, {
        "reminder": {
            "action": "list",
            **({"due_date": date_filter} if date_filter else {}),
        }
    }


def _calendar_create(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]]:
    item = _copy(
        slots,
        "title",
        "date",
        "time",
        "type",
        "recurrence",
        "recurrence_day",
        "rrule_day",
        "description",
    )
    offset = slots.get("days_offset")
    if offset is not None:
        _require_aware_reference(context.reference_time)
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise _bridge_temporal_error("invalid_temporal")
        try:
            absolute = (
                context.reference_time.astimezone(OSLO).date()
                + timedelta(days=offset)
            ).strftime("%d.%m.%Y")
        except (OverflowError, ValueError):
            raise _bridge_temporal_error("invalid_temporal") from None
        if item.get("date") not in (None, absolute):
            raise _bridge_temporal_error("conflicting_temporal_fields")
        item["date"] = absolute

    _require_aware_reference(context.reference_time)
    temporal = context.temporal_resolver.validate_fields(
        item.get("date"),
        item.get("time"),
        reference=context.reference_time,
    )
    if temporal.errors:
        raise PayloadValidationError(temporal.errors[0])
    item["date"] = temporal.date
    if "time" in item:
        item["time"] = temporal.time
    return BotIntent.CALENDAR_ITEM, {"calendar_item": item}


def _calendar_target(intent: BotIntent) -> RouteBuilder:
    def build(
        slots: Mapping[str, JsonValue],
        context: ActionBridgeContext,
    ) -> tuple[BotIntent, dict[str, object]]:
        del context
        return intent, {"calendar_target": _copy(slots, "target", "number")}

    return build


def _calendar_edit(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]]:
    changes = _copy(
        slots,
        "title",
        "description",
        "date",
        "time",
        "recurrence",
    )
    if "date" in changes:
        _require_aware_reference(context.reference_time)
        temporal = context.temporal_resolver.validate_fields(
            changes["date"],
            changes.get("time"),
            reference=context.reference_time,
        )
        if temporal.errors:
            raise PayloadValidationError(temporal.errors[0])
        changes["date"] = temporal.date
        if "time" in changes:
            changes["time"] = temporal.time
    return BotIntent.CALENDAR_EDIT, {
        "calendar_edit": {
            "target": slots["target"],
            "changes": changes,
        }
    }


def _canonicalize_reminder_temporal(
    data: dict[str, JsonValue],
    context: ActionBridgeContext,
) -> None:
    due_at = data.get("due_at")
    due_date = data.get("due_date")
    time_value = data.get("time")
    if due_at is None and due_date is None:
        return

    _require_aware_reference(context.reference_time)
    if due_at is not None:
        if not isinstance(due_at, str):
            raise _bridge_temporal_error("invalid_temporal")
        try:
            explicit = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            local = explicit.astimezone(OSLO)
        except (OverflowError, TypeError, ValueError):
            raise _bridge_temporal_error("invalid_temporal") from None
        date_value = due_date or local.strftime("%d.%m.%Y")
        effective_time = time_value or local.strftime("%H:%M")
    else:
        date_value = due_date
        effective_time = time_value

    temporal = context.temporal_resolver.validate_fields(
        date_value,
        effective_time,
        due_at=due_at,
        reference=context.reference_time,
    )
    if temporal.errors:
        raise PayloadValidationError(temporal.errors[0])
    if due_at is not None:
        data["due_at"] = temporal.due_at
    if due_date is not None:
        data["due_date"] = temporal.date
    if time_value is not None:
        data["time"] = temporal.time


def _reminder(action: str, intent: BotIntent, *names: str) -> RouteBuilder:
    def build(
        slots: Mapping[str, JsonValue],
        context: ActionBridgeContext,
    ) -> tuple[BotIntent, dict[str, object]]:
        reminder: dict[str, JsonValue] = {
            "action": action,
            **_copy(slots, *names),
        }
        _canonicalize_reminder_temporal(reminder, context)
        return intent, {"reminder": reminder}

    return build


def _reminder_edit(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]]:
    changes = _copy(
        slots,
        "text",
        "due_at",
        "due_date",
        "time",
        "timezone",
        "recurrence",
    )
    _canonicalize_reminder_temporal(changes, context)
    return BotIntent.REMINDER_EDIT, {
        "reminder": {
            "action": "edit",
            "number": slots["number"],
            "changes": changes,
        }
    }


def _sole_active_poll_id(context: ActionBridgeContext) -> str | None:
    if (
        isinstance(context.active_poll_count, bool)
        or not isinstance(context.active_poll_count, int)
        or context.active_poll_count != 1
        or not isinstance(context.active_poll_id, str)
        or not context.active_poll_id.strip()
    ):
        return None
    return context.active_poll_id


def _poll_target(intent: BotIntent, key: str) -> RouteBuilder:
    def build(
        slots: Mapping[str, JsonValue],
        context: ActionBridgeContext,
    ) -> tuple[BotIntent, dict[str, object]] | None:
        if "target" in slots:
            return intent, {key: {"target": slots["target"]}}
        poll_id = _sole_active_poll_id(context)
        if poll_id is None:
            return None
        return intent, {key: {"poll_id": poll_id}}

    return build


def _poll_vote(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]] | None:
    poll_id = _sole_active_poll_id(context)
    if poll_id is None:
        return None
    return BotIntent.POLL_VOTE, {
        "vote": {"option": slots["option"], "poll_id": poll_id}
    }


def _poll_edit(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]] | None:
    if "target" in slots:
        selector: dict[str, JsonValue] = {"target": slots["target"]}
    else:
        poll_id = _sole_active_poll_id(context)
        if poll_id is None:
            return None
        selector = {"poll_id": poll_id}
    return BotIntent.POLL_EDIT, {
        "poll_edit": {
            **selector,
            **_copy(slots, "question", "options"),
        }
    }


def _resolved_name(
    user_id: int,
    context: ActionBridgeContext,
    *,
    allow_author: bool,
) -> str | None:
    if allow_author and context.routing.author.user_id == user_id:
        return context.routing.author.display_name
    for mention in context.routing.mentions:
        if mention.user_id == user_id:
            return mention.display_name
    return None


def _birthday_create(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]] | None:
    user_id = int(slots["user_id"])
    display_name = _resolved_name(user_id, context, allow_author=False)
    if display_name is None:
        return None
    return BotIntent.BIRTHDAY_CREATE, {
        "birthday": {
            "action": "add",
            "user_id": user_id,
            "display_name": display_name,
            **_copy(slots, "day", "month", "year"),
        }
    }


def _birthday_edit(
    slots: Mapping[str, JsonValue],
    context: ActionBridgeContext,
) -> tuple[BotIntent, dict[str, object]] | None:
    user_id = int(slots["user_id"])
    if _resolved_name(user_id, context, allow_author=True) is None:
        return None
    return BotIntent.BIRTHDAY_EDIT, {
        "birthday": {
            "action": "edit",
            "user_id": user_id,
            **_copy(slots, "day", "month", "year"),
        }
    }


def _umbrella(
    intent: BotIntent,
    envelope: str,
    action: str,
    *names: str,
) -> RouteBuilder:
    def build(
        slots: Mapping[str, JsonValue],
        context: ActionBridgeContext,
    ) -> tuple[BotIntent, dict[str, object]]:
        del context
        return intent, {
            envelope: {"action": action, **_copy(slots, *names)}
        }

    return build


ACTION_ROUTE_BUILDERS: dict[ActionName, RouteBuilder] = {
    ActionName.SHOW_DASHBOARD: _simple(
        BotIntent.DASHBOARD,
        {"dashboard_reason": "model_action"},
    ),
    ActionName.HELP: _simple(BotIntent.HELP, {}),
    ActionName.CALENDAR_CREATE: _calendar_create,
    ActionName.CALENDAR_LIST: _calendar_list,
    ActionName.CALENDAR_SEARCH: lambda slots, context: (
        BotIntent.CALENDAR_SEARCH,
        {"query": slots["query"]},
    ),
    ActionName.CALENDAR_COMPLETE: _calendar_target(BotIntent.CALENDAR_COMPLETE),
    ActionName.CALENDAR_EDIT: _calendar_edit,
    ActionName.CALENDAR_DELETE: _calendar_target(BotIntent.CALENDAR_DELETE),
    ActionName.CALENDAR_CLEAR: _simple(
        BotIntent.CALENDAR_CLEAR,
        {"calendar_target": {"all": True}},
    ),
    ActionName.REMINDER_CREATE: _reminder(
        "add",
        BotIntent.REMINDER_CREATE,
        "text",
        "due_at",
        "due_date",
        "time",
        "timezone",
        "recurrence",
    ),
    ActionName.REMINDER_LIST: _reminder_list,
    ActionName.REMINDER_SEARCH: _reminder(
        "search", BotIntent.REMINDER_SEARCH, "query"
    ),
    ActionName.REMINDER_COMPLETE: _reminder(
        "complete", BotIntent.REMINDER_COMPLETE, "number"
    ),
    ActionName.REMINDER_EDIT: _reminder_edit,
    ActionName.REMINDER_DELETE: _reminder(
        "delete", BotIntent.REMINDER_DELETE, "number"
    ),
    ActionName.POLL_CREATE: lambda slots, context: (
        BotIntent.POLL_CREATE,
        {"poll": _copy(slots, "question", "options")},
    ),
    ActionName.POLL_LIST: _simple(BotIntent.POLL_LIST, {}),
    ActionName.POLL_VOTE: _poll_vote,
    ActionName.POLL_EDIT: _poll_edit,
    ActionName.POLL_DELETE: _poll_target(BotIntent.POLL_DELETE, "poll_delete"),
    ActionName.POLL_CLOSE: _poll_target(BotIntent.POLL_CLOSE, "poll_close"),
    ActionName.BIRTHDAY_CREATE: _birthday_create,
    ActionName.BIRTHDAY_LIST: lambda slots, context: (
        BotIntent.BIRTHDAY_LIST,
        {"birthday": {"action": "list", "scope": slots.get("scope", "all")}},
    ),
    ActionName.BIRTHDAY_EDIT: _birthday_edit,
    ActionName.PROFILE_STATUS: _umbrella(
        BotIntent.PROFILE, "profile", "status", "value"
    ),
    ActionName.PROFILE_PLAYING: _umbrella(
        BotIntent.PROFILE, "profile", "playing", "value"
    ),
    ActionName.PROFILE_WATCHING: _umbrella(
        BotIntent.PROFILE, "profile", "watching", "value"
    ),
    ActionName.WATCHLIST_ADD: _umbrella(
        BotIntent.WATCHLIST,
        "watchlist",
        "add",
        "title",
        "type",
        "genre",
        "comment",
    ),
    ActionName.WATCHLIST_LIST: _umbrella(
        BotIntent.WATCHLIST, "watchlist", "status"
    ),
    ActionName.WATCHLIST_SUGGEST: _umbrella(
        BotIntent.WATCHLIST, "watchlist", "suggest", "type", "genre"
    ),
    ActionName.WATCHLIST_EDIT: _umbrella(
        BotIntent.WATCHLIST,
        "watchlist",
        "edit",
        "index",
        "title",
        "type",
        "genre",
        "comment",
    ),
    ActionName.WATCHLIST_REMOVE: _umbrella(
        BotIntent.WATCHLIST, "watchlist", "remove", "index"
    ),
    ActionName.QUOTE_SAVE: _umbrella(
        BotIntent.QUOTE, "quote", "save", "text", "author"
    ),
    ActionName.QUOTE_GET: _umbrella(BotIntent.QUOTE, "quote", "get"),
    ActionName.QUOTE_LIST: _umbrella(BotIntent.QUOTE_LIST, "quote", "list"),
    ActionName.QUOTE_EDIT: _umbrella(
        BotIntent.QUOTE_EDIT, "quote", "edit", "index", "text", "author"
    ),
    ActionName.QUOTE_DELETE: _umbrella(
        BotIntent.QUOTE_DELETE, "quote", "delete", "index"
    ),
}


_ACTION_EVIDENCE: dict[ActionName, tuple[str, ...]] = {
    ActionName.NONE: (),
    ActionName.CLARIFY: (),
    ActionName.SHOW_DASHBOARD: ("vis", "oversikt", "show"),
    ActionName.HELP: ("hjelp", "help"),
    ActionName.CALENDAR_CREATE: (
        "legg til",
        "lagre",
        "opprett",
        "planlegg",
        "planlegge",
        "planleggje",
        "sette opp",
        "setje opp",
        "set up",
        "book",
        "booke",
        "put",
        "schedule",
        "add",
        "create",
    ),
    ActionName.CALENDAR_LIST: ("vis", "liste", "show", "list"),
    ActionName.CALENDAR_SEARCH: ("søk", "finn", "search", "find"),
    ActionName.CALENDAR_COMPLETE: ("fullfør", "ferdig", "complete", "done"),
    ActionName.CALENDAR_EDIT: (
        "endre",
        "rediger",
        "flytt",
        "flytte",
        "reschedule",
        "edit",
        "change",
        "move",
    ),
    ActionName.CALENDAR_DELETE: (
        "slett",
        "slette",
        "fjern",
        "fjerne",
        "ta bort",
        "bli kvitt",
        "delete",
        "remove",
        "get rid of",
    ),
    ActionName.CALENDAR_CLEAR: (
        "tøm",
        "slett alt",
        "slett alle",
        "clear",
        "delete all",
    ),
    ActionName.REMINDER_CREATE: (
        "create",
        "add",
        "make",
        "set",
        "put",
        "påminn",
        "minn",
        "minne",
        "husk",
        "hugs",
        "huske",
        "glemme",
        "gløyme",
        "forget",
        "sørg for",
        "pass på",
        "remind",
        "remember",
        "make sure",
    ),
    ActionName.REMINDER_LIST: ("vis", "liste", "show", "list"),
    ActionName.REMINDER_SEARCH: ("søk", "finn", "search", "find"),
    ActionName.REMINDER_COMPLETE: ("fullfør", "ferdig", "complete", "done"),
    ActionName.REMINDER_EDIT: (
        "endre",
        "rediger",
        "flytt",
        "oppdater",
        "oppdatere",
        "update",
        "edit",
        "change",
        "move",
    ),
    ActionName.REMINDER_DELETE: (
        "slett",
        "slette",
        "fjern",
        "fjerne",
        "ta bort",
        "bli kvitt",
        "delete",
        "remove",
        "get rid of",
    ),
    ActionName.POLL_CREATE: (
        "lag",
        "opprett",
        "stemme over",
        "vote on",
        "create",
    ),
    ActionName.POLL_LIST: ("vis", "liste", "show", "list"),
    ActionName.POLL_VOTE: (
        "stem",
        "går for",
        "velger",
        "choose",
        "vote",
    ),
    ActionName.POLL_EDIT: ("endre", "rediger", "edit", "change"),
    ActionName.POLL_DELETE: (
        "slett",
        "slette",
        "fjern",
        "fjerne",
        "delete",
        "remove",
    ),
    ActionName.POLL_CLOSE: ("lukk", "avslutt", "close", "end"),
    ActionName.BIRTHDAY_CREATE: (
        "legg til",
        "lagre",
        "registrer",
        "add",
        "save",
    ),
    ActionName.BIRTHDAY_LIST: ("vis", "liste", "show", "list"),
    ActionName.BIRTHDAY_EDIT: (
        "endre",
        "rediger",
        "edit",
        "change",
    ),
    ActionName.PROFILE_STATUS: (),
    ActionName.PROFILE_PLAYING: (),
    ActionName.PROFILE_WATCHING: (),
    ActionName.WATCHLIST_ADD: (
        "legg til",
        "legg",
        "husk å se",
        "husk å sjå",
        "hugs å se",
        "hugs å sjå",
        "remember to watch",
        "put",
        "add",
    ),
    ActionName.WATCHLIST_LIST: ("vis", "liste", "show", "list"),
    ActionName.WATCHLIST_SUGGEST: (
        "foreslå",
        "anbefal",
        "suggest",
        "recommend",
    ),
    ActionName.WATCHLIST_EDIT: ("endre", "rediger", "edit", "change"),
    ActionName.WATCHLIST_REMOVE: (
        "fjern",
        "fjerne",
        "slett",
        "slette",
        "ta bort",
        "bli kvitt",
        "remove",
        "delete",
        "get rid of",
    ),
    ActionName.QUOTE_SAVE: (
        "lagre",
        "husk dette",
        "quote this",
        "save",
    ),
    ActionName.QUOTE_GET: ("hent", "tilfeldig", "get", "random"),
    ActionName.QUOTE_LIST: ("vis", "liste", "show", "list"),
    ActionName.QUOTE_EDIT: ("endre", "rediger", "edit", "change"),
    ActionName.QUOTE_DELETE: (
        "slett",
        "slette",
        "fjern",
        "fjerne",
        "delete",
        "remove",
    ),
}


_DOMAIN_EVIDENCE: dict[ActionName, tuple[str, ...]] = {
    ActionName.NONE: (),
    ActionName.CLARIFY: (),
    ActionName.SHOW_DASHBOARD: ("oversikt", "dashboard"),
    ActionName.HELP: ("hjelp", "help"),
    **{
        action: (
            "kalender",
            "kalenderen",
            "kalenderoppføring",
            "avtale",
            "avtalen",
            "møte",
            "møtet",
            "møter",
            "møtene",
            "calendar",
            "event",
            "meeting",
            "appointment",
        )
        for action in ActionName
        if action.value.startswith("CALENDAR_")
    },
    **{
        action: (
            "påminnelse",
            "påminnelsen",
            "påminnelser",
            "påminning",
            "påminninga",
            "påminningar",
            "huskeliste",
            "reminder",
            "reminders",
        )
        for action in ActionName
        if action.value.startswith("REMINDER_")
    },
    **{
        action: (
            "poll",
            "polls",
            "avstemning",
            "avstemming",
            "avstemminga",
            "avstemningen",
        )
        for action in ActionName
        if action.value.startswith("POLL_")
    },
    **{
        action: ("bursdag", "fødselsdag", "birthday")
        for action in ActionName
        if action.value.startswith("BIRTHDAY_")
    },
    **{
        action: (
            "profil",
            "profile",
            "status",
            "statusen",
            "aktivitet",
            "aktiviteten",
            "activity",
            "spiller",
            "playing",
            "ser på",
            "watching",
        )
        for action in ActionName
        if action.value.startswith("PROFILE_")
    },
    **{
        action: (
            "watchlist",
            "se-liste",
            "se-lista",
            "se-listen",
            "filmliste",
            "filmlista",
            "filmlisten",
            "film",
            "filmer",
            "filmar",
            "serie",
            "serien",
            "serier",
            "seriar",
            "movie",
            "show",
            "series",
        )
        for action in ActionName
        if action.value.startswith("WATCHLIST_")
    },
    **{
        action: ("sitat", "sitater", "sitata", "quote")
        for action in ActionName
        if action.value.startswith("QUOTE_")
    },
}


_ANCHORED_ACTION_EVIDENCE: dict[ActionName, tuple[str, ...]] = {
    ActionName.CALENDAR_CREATE: (
        "jeg vil gjerne ha et møte",
        "jeg vil gjerne ha en avtale",
        "eg vil gjerne ha eit møte",
        "eg vil gjerne ha ein avtale",
        "i would like a meeting",
        "i would like an appointment",
        "would you mind putting a meeting",
        "would you mind putting an appointment",
        "could you please put a meeting",
        "could you please put an appointment",
        "could you put",
        "could you book",
        "could you set up",
        "kan du sette opp",
        "kan du booke",
    ),
    ActionName.CALENDAR_EDIT: (
        "i need the meeting moved",
        "i need my meeting moved",
        "i need meeting moved",
        "i need the appointment moved",
        "i need my appointment moved",
        "i need appointment moved",
    ),
    ActionName.REMINDER_CREATE: (
        "jeg trenger å bli minnet",
        "jeg treng å bli minna",
        "eg treng å bli minna",
        "jeg vil gjerne bli minnet",
        "eg vil gjerne bli minna",
        "would you mind reminding me",
        "i need to be reminded",
        "i need to remember",
        "don't let me forget",
        "don’t let me forget",
        "ikke la meg glemme",
        "i'd like a reminder to",
        "i’d like a reminder to",
        "i would like a reminder to",
    ),
    ActionName.WATCHLIST_ADD: (
        "husk at jeg vil se",
        "husk at jeg skal se",
        "huske at jeg vil se",
        "huske at jeg skal se",
        "hugs at eg vil sjå",
        "hugs at eg skal sjå",
        "hugse at eg vil sjå",
        "hugse at eg skal sjå",
    ),
    ActionName.BIRTHDAY_EDIT: (
        "bursdagen min er",
        "min bursdag er",
        "jeg har bursdag",
        "eg har bursdag",
        "fødselsdagen min er",
        "my birthday is",
    ),
    ActionName.PROFILE_STATUS: (
        "sett statusen",
        "set status",
        "kan du sette statusen",
        "kan du setje statusen",
        "kunne du sette statusen",
        "could you set your status",
        "would you set your status",
        "please set your status",
    ),
    ActionName.PROFILE_PLAYING: (
        "vis at du spiller",
        "vis at du spelar",
        "show that you are playing",
        "kan du vise at du spiller",
        "kan du vise at du spelar",
        "could you show that you are playing",
        "would you show that you are playing",
        "please set your activity to playing",
    ),
    ActionName.PROFILE_WATCHING: (
        "vis at du ser på",
        "show that you are watching",
        "kan du vise at du ser på",
        "could you show that you are watching",
        "would you show that you are watching",
        "please set your activity to watching",
    ),
}


_WATCHLIST_CHECK_FRAMES = (
    "husk å se om",
    "husk å se hvordan",
    "husk å se korleis",
    "husk å se at",
    "husk å se til",
    "husk å se på barna",
    "husk å se på barnet",
    "husk å se på ungene",
    "husk å sjå om",
    "husk å sjå korleis",
    "husk å sjå hvordan",
    "husk å sjå at",
    "husk å sjå til",
    "husk å sjå på barna",
    "husk å sjå på barnet",
    "husk å sjå på ungane",
    "hugs å se om",
    "hugs å se hvordan",
    "hugs å se korleis",
    "hugs å se at",
    "hugs å se til",
    "hugs å se på barna",
    "hugs å se på barnet",
    "hugs å se på ungene",
    "hugs å sjå om",
    "hugs å sjå korleis",
    "hugs å sjå hvordan",
    "hugs å sjå at",
    "hugs å sjå til",
    "hugs å sjå på barna",
    "hugs å sjå på barnet",
    "hugs å sjå på ungane",
    "remember to watch if",
    "remember to watch whether",
    "remember to watch how",
    "remember to watch that",
    "remember to watch out",
    "remember to watch the kids",
    "remember to watch the children",
)
_WATCHLIST_REMEMBER_ACTIONS = frozenset(
    {
        "husk å se",
        "husk å sjå",
        "hugs å se",
        "hugs å sjå",
        "remember to watch",
    }
)
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+", re.UNICODE)
_INFLECTED_EVIDENCE_FORMS: dict[str, frozenset[str]] = {
    "appointment": frozenset({"appointments"}),
    "avstemning": frozenset(
        {
            "avstemninga",
            "avstemningen",
            "avstemningar",
            "avstemningane",
            "avstemninger",
            "avstemningene",
        }
    ),
    "avstemming": frozenset(
        {"avstemminga", "avstemmingar", "avstemmingane"}
    ),
    "avtale": frozenset(
        {
            "avtala",
            "avtalen",
            "avtalar",
            "avtalane",
            "avtaler",
            "avtalene",
        }
    ),
    "birthday": frozenset({"birthdays"}),
    "bursdag": frozenset(
        {
            "bursdagen",
            "bursdagar",
            "bursdagane",
            "bursdager",
            "bursdagene",
        }
    ),
    "event": frozenset({"events"}),
    "film": frozenset(
        {"filmen", "filmer", "filmene", "filmar", "filmane", "films"}
    ),
    "fødselsdag": frozenset(
        {
            "fødselsdagen",
            "fødselsdagar",
            "fødselsdagane",
            "fødselsdager",
            "fødselsdagene",
        }
    ),
    "kalender": frozenset(
        {
            "kalenderen",
            "kalendere",
            "kalenderne",
            "kalendrar",
            "kalendrane",
        }
    ),
    "meeting": frozenset({"meetings"}),
    "movie": frozenset({"movies"}),
    "møte": frozenset({"møtet", "møter", "møtene", "møta"}),
    "påminnelse": frozenset(
        {"påminnelsen", "påminnelser", "påminnelsene"}
    ),
    "påminning": frozenset(
        {"påminninga", "påminningar", "påminningane"}
    ),
    "quote": frozenset({"quotes"}),
    "reminder": frozenset({"reminders"}),
    "serie": frozenset(
        {"serien", "serier", "seriene", "seriar", "seriane"}
    ),
    "show": frozenset({"shows"}),
    "sitat": frozenset({"sitatet", "sitater", "sitatene", "sitata"}),
}


def _evidence_tokens(value: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(value.casefold()))


def _evidence_token_matches(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    return actual in _INFLECTED_EVIDENCE_FORMS.get(expected, ())


def _present_evidence(
    utterance: NormalizedUtterance,
    phrases: tuple[str, ...],
) -> tuple[str, ...]:
    tokens = _evidence_tokens(utterance.control_text)
    present: list[str] = []
    for phrase in phrases:
        expected = _evidence_tokens(phrase)
        if not expected:
            continue
        width = len(expected)
        for index in range(0, len(tokens) - width + 1):
            window = tokens[index : index + width]
            if all(
                _evidence_token_matches(actual, wanted)
                for actual, wanted in zip(window, expected)
            ):
                live_span = " ".join(window)
                if live_span not in present:
                    present.append(live_span)
                break
    return tuple(present)


def _present_anchored_evidence(
    utterance: NormalizedUtterance,
    phrases: tuple[str, ...],
) -> tuple[str, ...]:
    tokens = _evidence_tokens(utterance.control_text)
    present: list[str] = []
    for phrase in phrases:
        expected = _evidence_tokens(phrase)
        width = len(expected)
        if not expected or len(tokens) < width:
            continue
        window = tokens[:width]
        if all(
            _evidence_token_matches(actual, wanted)
            for actual, wanted in zip(window, expected)
        ):
            live_span = " ".join(window)
            if live_span not in present:
                present.append(live_span)
    return tuple(present)


def _bounded_calendar_create_head_evidence(
    utterance: NormalizedUtterance,
) -> tuple[str, ...]:
    """Trust ambiguous English create verbs only in directive position."""

    head = bounded_english_calendar_create_head(utterance)
    return (head,) if head is not None else ()


class ActionBridge:
    """Validate and arbitrate one model proposal without executing it."""

    def __init__(self, metrics: NLUMetrics | None = None):
        self.metrics = metrics

    def to_result(
        self,
        proposal: ActionProposal,
        context: ActionBridgeContext,
    ) -> IntentResult | None:
        if proposal.action is ActionName.NONE:
            return None
        if not context.semantic_action_allowed:
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.UNSAFE_SEMANTIC)
            return None
        if proposal.action is ActionName.CLARIFY:
            return IntentResult(
                BotIntent.CLARIFY,
                proposal.confidence,
                {"clarification": proposal.clarification or ""},
                "semantic_clarification",
                source=IntentSource.SEMANTIC,
                risk=IntentRisk.READ_ONLY,
                requires_confirmation=False,
            )

        deterministic_sequence_guard = (
            context.deterministic_route is not None
            and context.deterministic_route.intent is BotIntent.CLARIFY
            and context.deterministic_route.reason
            == "multiple_actions_require_split"
        )
        if (
            deterministic_sequence_guard
            or has_sequenced_action_request(context.utterance)
        ):
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.CONFLICT)
            return None

        if has_unsupported_poll_mutation_request(context.utterance):
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.INVALID_CONTEXT)
            return None

        if (
            proposal.action is ActionName.SHOW_DASHBOARD
            and has_future_weather_request(context.utterance)
        ):
            # SHOW_DASHBOARD fetches current conditions only.  Do not let a
            # model reinterpret a dated forecast question as current weather.
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.INVALID_TEMPORAL)
            return None

        control = context.utterance.control_text.strip()
        exact_list_family = (
            filtered_list_read_family(control)
            or unfiltered_list_read_family(control)
        )
        expected_list_action = {
            "calendar": ActionName.CALENDAR_LIST,
            "reminder": ActionName.REMINDER_LIST,
        }.get(exact_list_family)
        if expected_list_action is not None:
            if proposal.action not in {
                expected_list_action,
                ActionName.CLARIFY,
            }:
                # A model may not reinterpret an inventory request as SEARCH
                # and silently discard its requested date/filter.
                if self.metrics is not None:
                    self.metrics.record_rejection(
                        RejectionCode.INVALID_CONTEXT
                    )
                return None
        elif (
            proposal.action is not ActionName.CLARIFY
            and looks_like_list_read_request(control)
        ):
            # The utterance has an unsupported qualifier/range.  No typed
            # action currently carries that complete meaning, so fail closed.
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.INVALID_TEMPORAL)
            return None

        built = ACTION_ROUTE_BUILDERS[proposal.action](proposal.slots, context)
        if built is None:
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.INVALID_CONTEXT)
            return None
        intent, payload = built
        payload = validate_route_payload(
            intent,
            payload,
            source=IntentSource.SEMANTIC,
        )
        risk = classify_intent_risk(intent, payload)
        semantics = analyze_utterance(context.utterance)
        action_terms = _present_evidence(
            context.utterance,
            _ACTION_EVIDENCE[proposal.action],
        )
        action_terms += _present_anchored_evidence(
            context.utterance,
            _ANCHORED_ACTION_EVIDENCE.get(proposal.action, ()),
        )
        if proposal.action is ActionName.CALENDAR_CREATE:
            action_terms = tuple(
                term
                for term in action_terms
                if term
                not in {"book", "schedule", "put", "add", "create"}
            )
            action_terms += _bounded_calendar_create_head_evidence(
                context.utterance
            )
        if proposal.action is ActionName.REMINDER_CREATE:
            action_terms = tuple(
                term
                for term in action_terms
                if term not in {"create", "add", "make", "set", "put"}
            )
            reminder_head = bounded_english_reminder_create_head(
                context.utterance
            )
            if reminder_head is not None:
                action_terms += (reminder_head,)
        if (
            proposal.action is ActionName.WATCHLIST_ADD
            and _present_evidence(
                context.utterance,
                _WATCHLIST_CHECK_FRAMES,
            )
        ):
            # "Husk å se om ..." asks for a later check; it is not a bounded
            # request to add media.  Preserve any separate explicit add verb.
            action_terms = tuple(
                term
                for term in action_terms
                if term not in _WATCHLIST_REMEMBER_ACTIONS
            )
        domain_terms = _present_evidence(
            context.utterance,
            _DOMAIN_EVIDENCE[proposal.action],
        )
        candidate = IntentCandidate(
            intent=intent,
            confidence=proposal.confidence,
            priority=85,
            order=0,
            payload=payload,
            reason="semantic_action",
            source=IntentSource.SEMANTIC,
            risk=risk,
            action_terms=action_terms,
            domain_terms=domain_terms,
            specificity=int(bool(action_terms)) + int(bool(domain_terms)),
            requires_confirmation=risk
            in {
                IntentRisk.ADDITIVE,
                IntentRisk.MUTATING,
                IntentRisk.DESTRUCTIVE,
            },
        )
        decision = arbitrate_candidates(
            context.utterance,
            semantics,
            [candidate],
        )
        if self.metrics is not None:
            for rejection in decision.rejected:
                self.metrics.record_rejection(rejection.code)
        if decision.blocked or decision.selected is None:
            return None
        if risk is not IntentRisk.READ_ONLY and not action_terms:
            if self.metrics is not None:
                self.metrics.record_rejection(
                    RejectionCode.MISSING_ACTION_EVIDENCE
                )
            return None
        if risk is IntentRisk.DESTRUCTIVE and not domain_terms:
            if self.metrics is not None:
                self.metrics.record_rejection(
                    RejectionCode.MISSING_DOMAIN_EVIDENCE
                )
            return None
        if risk is not IntentRisk.READ_ONLY and not semantics.allows_mutation:
            if self.metrics is not None:
                self.metrics.record_rejection(RejectionCode.UNSAFE_SEMANTIC)
            return None

        semantic_result = decision.selected.to_result()
        deterministic = context.deterministic_route
        if deterministic is None or deterministic.intent is BotIntent.AI_CHAT:
            return semantic_result
        if (
            deterministic.intent is semantic_result.intent
            and deterministic.payload == semantic_result.payload
        ):
            return semantic_result
        if self.metrics is not None:
            self.metrics.record_rejection(RejectionCode.CONFLICT)
        return IntentResult(
            BotIntent.CLARIFY,
            1.0,
            {
                "choices": (
                    copy.deepcopy(deterministic),
                    copy.deepcopy(semantic_result),
                ),
                "clarification": (
                    "Jeg ser to mulige tolkninger. Hvilken mener du?"
                ),
            },
            "deterministic_semantic_conflict",
            source=IntentSource.SEMANTIC,
            risk=IntentRisk.READ_ONLY,
            requires_confirmation=False,
        )


__all__ = [
    "ACTION_ROUTE_BUILDERS",
    "BRIDGE_TEMPORAL_ERROR_CODES",
    "ActionBridge",
    "ActionBridgeContext",
    "validate_route_payload",
]
