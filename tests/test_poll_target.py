#!/usr/bin/env python3
# pyright: reportPrivateUsage=false, reportUnannotatedClassAttribute=false
"""Regression tests for poll target resolution."""

import unittest
from typing import cast

from core.intent_router import IntentRouter


class DummyMonitor:
    pass


class PollTargetTests(unittest.TestCase):
    router: IntentRouter = IntentRouter(DummyMonitor())

    def parse_target(self, text: str) -> int | str | None:
        return cast(int | str | None, self.router._parse_poll_reference(text.lower())["target"])

    def test_scoped_poll_number_is_used(self):
        self.assertEqual(self.parse_target("slett poll 2"), 2)

    def test_time_phrase_does_not_become_poll_target(self):
        self.assertIsNone(self.parse_target("slett poll etter 15 minutter"))

    def test_delete_poll_without_number_uses_latest(self):
        self.assertIsNone(self.parse_target("slett poll"))

    def test_scoped_avstemning_number_is_used(self):
        self.assertEqual(self.parse_target("slett avstemning 3"), 3)

    def test_edit_poll_number_is_used(self):
        self.assertEqual(self.parse_target("endre poll 1 tittel: ny"), 1)

    def test_fallback_first_number_is_used_when_unscoped(self):
        self.assertEqual(self.parse_target("slett 2"), 2)

    def test_siste_keyword_is_preserved(self):
        self.assertEqual(self.parse_target("slett poll siste"), "siste")

    def test_no_number_or_siste_returns_none(self):
        self.assertIsNone(self.parse_target("slett poll nå"))


if __name__ == "__main__":
    _ = unittest.main()
