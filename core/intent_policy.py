"""Exhaustive, payload-aware risk classification for bot intents."""

from collections.abc import Mapping
from typing import Any

from core.intent_models import BotIntent, IntentRisk


BASE_INTENT_RISK: dict[BotIntent, IntentRisk] = {
    BotIntent.HELP: IntentRisk.READ_ONLY,
    BotIntent.STATUS: IntentRisk.READ_ONLY,
    BotIntent.PROFILE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_HELP: IntentRisk.READ_ONLY,
    BotIntent.CALENDAR_LIST: IntentRisk.READ_ONLY,
    BotIntent.CALENDAR_SYNC: IntentRisk.MUTATING,
    BotIntent.CALENDAR_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.CALENDAR_COMPLETE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_EDIT: IntentRisk.MUTATING,
    BotIntent.CALENDAR_SEARCH: IntentRisk.READ_ONLY,
    BotIntent.CALENDAR_CLEAR: IntentRisk.DESTRUCTIVE,
    BotIntent.CALENDAR_ITEM: IntentRisk.ADDITIVE,
    BotIntent.POLL_CREATE: IntentRisk.ADDITIVE,
    BotIntent.POLL_VOTE: IntentRisk.MUTATING,
    BotIntent.POLL_EDIT: IntentRisk.MUTATING,
    BotIntent.POLL_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.POLL_CLOSE: IntentRisk.MUTATING,
    BotIntent.POLL_LIST: IntentRisk.READ_ONLY,
    BotIntent.COUNTDOWN: IntentRisk.READ_ONLY,
    BotIntent.WATCHLIST: IntentRisk.DESTRUCTIVE,
    BotIntent.WORD_OF_DAY: IntentRisk.READ_ONLY,
    BotIntent.QUOTE: IntentRisk.DESTRUCTIVE,
    BotIntent.QUOTE_LIST: IntentRisk.READ_ONLY,
    BotIntent.QUOTE_EDIT: IntentRisk.MUTATING,
    BotIntent.QUOTE_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.AURORA: IntentRisk.READ_ONLY,
    BotIntent.SCHOOL_HOLIDAYS: IntentRisk.READ_ONLY,
    BotIntent.PRICE: IntentRisk.READ_ONLY,
    BotIntent.HOROSCOPE: IntentRisk.READ_ONLY,
    BotIntent.COMPLIMENT: IntentRisk.READ_ONLY,
    BotIntent.CALCULATOR: IntentRisk.READ_ONLY,
    BotIntent.SHORTEN_URL: IntentRisk.READ_ONLY,
    BotIntent.DAILY_DIGEST: IntentRisk.READ_ONLY,
    BotIntent.SEARCH: IntentRisk.READ_ONLY,
    BotIntent.DASHBOARD: IntentRisk.READ_ONLY,
    BotIntent.SET_LOCATION: IntentRisk.MUTATING,
    BotIntent.MEMORY_VIEW: IntentRisk.READ_ONLY,
    BotIntent.MEMORY_EXPORT: IntentRisk.READ_ONLY,
    BotIntent.MEMORY_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.BIRTHDAY_EDIT: IntentRisk.MUTATING,
    BotIntent.REMINDER_EDIT: IntentRisk.MUTATING,
    BotIntent.REMINDER_DELETE: IntentRisk.DESTRUCTIVE,
    BotIntent.REMINDER_SEARCH: IntentRisk.READ_ONLY,
    BotIntent.REMINDER_CREATE: IntentRisk.ADDITIVE,
    BotIntent.REMINDER_LIST: IntentRisk.READ_ONLY,
    BotIntent.REMINDER_COMPLETE: IntentRisk.MUTATING,
    BotIntent.CALENDAR_AUTH: IntentRisk.MUTATING,
    BotIntent.AI_CHAT: IntentRisk.READ_ONLY,
    BotIntent.CLARIFY: IntentRisk.READ_ONLY,
    BotIntent.BIRTHDAY_CREATE: IntentRisk.ADDITIVE,
    BotIntent.BIRTHDAY_LIST: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CONFIRM: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CANCEL: IntentRisk.READ_ONLY,
    BotIntent.ACTION_SELECT: IntentRisk.READ_ONLY,
    BotIntent.ACTION_CORRECT: IntentRisk.READ_ONLY,
}


def _action(payload: Mapping[str, Any], envelope: str) -> str:
    value = payload.get(envelope)
    if not isinstance(value, Mapping):
        return ""
    action = value.get("action")
    return action.casefold().strip() if isinstance(action, str) else ""


WATCHLIST_ACTION_RISK = {
    "status": IntentRisk.READ_ONLY,
    "list": IntentRisk.READ_ONLY,
    "suggest": IntentRisk.READ_ONLY,
    "add": IntentRisk.ADDITIVE,
    "edit": IntentRisk.MUTATING,
    "remove": IntentRisk.DESTRUCTIVE,
}
QUOTE_ACTION_RISK = {
    "get": IntentRisk.READ_ONLY,
    "save": IntentRisk.ADDITIVE,
}


def classify_intent_risk(
    intent: BotIntent, payload: Mapping[str, Any]
) -> IntentRisk:
    if intent is BotIntent.WATCHLIST:
        return WATCHLIST_ACTION_RISK.get(
            _action(payload, "watchlist"), IntentRisk.DESTRUCTIVE
        )
    if intent is BotIntent.QUOTE:
        return QUOTE_ACTION_RISK.get(
            _action(payload, "quote"), IntentRisk.DESTRUCTIVE
        )
    return BASE_INTENT_RISK[intent]
