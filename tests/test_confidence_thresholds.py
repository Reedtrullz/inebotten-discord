#!/usr/bin/env python3
"""Regression tests for confidence threshold enforcement."""

import unittest

from core.intent_router import BotIntent, IntentResult
from core.intent_thresholds import CONFIDENCE_THRESHOLDS


class ConfidenceThresholdTests(unittest.TestCase):
    def test_calendar_item_threshold_is_094(self):
        self.assertEqual(CONFIDENCE_THRESHOLDS.get(BotIntent.CALENDAR_ITEM), 0.94)

    def test_search_threshold_is_070(self):
        self.assertEqual(CONFIDENCE_THRESHOLDS.get(BotIntent.SEARCH), 0.70)

    def test_help_has_no_threshold(self):
        self.assertEqual(CONFIDENCE_THRESHOLDS.get(BotIntent.HELP, 0.0), 0.0)

    def test_low_confidence_calendar_rejected(self):
        route = IntentResult(BotIntent.CALENDAR_ITEM, 0.90, {}, "test")
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        self.assertLess(route.confidence, threshold)

    def test_high_confidence_calendar_accepted(self):
        route = IntentResult(BotIntent.CALENDAR_ITEM, 0.97, {}, "test")
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        self.assertGreaterEqual(route.confidence, threshold)

    def test_low_confidence_search_rejected(self):
        route = IntentResult(BotIntent.SEARCH, 0.69, {}, "test")
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        self.assertLess(route.confidence, threshold)

    def test_high_confidence_search_accepted(self):
        route = IntentResult(BotIntent.SEARCH, 0.85, {}, "test")
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        self.assertGreaterEqual(route.confidence, threshold)

    def test_search_at_072_accepted(self):
        route = IntentResult(BotIntent.SEARCH, 0.72, {}, "test")
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        self.assertGreaterEqual(route.confidence, threshold)

    def test_exactly_at_threshold_accepted(self):
        route = IntentResult(BotIntent.SEARCH, 0.70, {}, "test")
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        self.assertGreaterEqual(route.confidence, threshold)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
