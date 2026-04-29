#!/usr/bin/env python3
"""Minimum confidence thresholds for intent dispatch."""

from core.intent_router import BotIntent


CONFIDENCE_THRESHOLDS = {
    BotIntent.CALENDAR_ITEM: 0.94,
    BotIntent.SEARCH: 0.70,
    BotIntent.PRICE: 0.85,
    BotIntent.HOROSCOPE: 0.85,
    BotIntent.COMPLIMENT: 0.80,
}
