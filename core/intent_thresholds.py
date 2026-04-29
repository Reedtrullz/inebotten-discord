#!/usr/bin/env python3
"""Minimum confidence thresholds for intent dispatch."""

from core.intent_router import BotIntent


CONFIDENCE_THRESHOLDS = {
    BotIntent.CALENDAR_ITEM: 0.94,
    BotIntent.SEARCH: 0.70,
    BotIntent.PRICE: 0.85,
    BotIntent.HOROSCOPE: 0.85,
    BotIntent.COMPLIMENT: 0.80,
    BotIntent.REMINDER_EDIT: 0.98,
    BotIntent.REMINDER_DELETE: 0.98,
    BotIntent.QUOTE_LIST: 0.95,
    BotIntent.QUOTE_EDIT: 0.95,
    BotIntent.QUOTE_DELETE: 0.95,
    BotIntent.BIRTHDAY_EDIT: 0.95,
}
