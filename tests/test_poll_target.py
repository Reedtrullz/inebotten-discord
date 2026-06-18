#!/usr/bin/env python3
# pyright: reportPrivateUsage=false, reportUnannotatedClassAttribute=false
"""Regression tests for poll target resolution."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from core.intent_router import IntentRouter
from features.poll_manager import PollManager
from features.polls_handler import PollsHandler


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


class PollVoteAmbiguityTests(unittest.IsolatedAsyncioTestCase):
    async def test_vote_with_multiple_active_polls_requires_disambiguation(self):
        with TemporaryDirectory() as tmp:
            manager = PollManager(storage_path=Path(tmp) / "polls.json")
            manager.create_poll("123", "Første?", ["Ja", "Nei"], "Tester")
            manager.create_poll("123", "Andre?", ["Ja", "Nei"], "Tester")
            monitor = SimpleNamespace(
                poll=manager,
                loc=SimpleNamespace(
                    current_lang="no",
                    t=lambda key, **kwargs: {
                        "no_active_polls": "Ingen aktive",
                        "vote_registered": "Stemmen er registrert",
                        "vote_error": "Feil",
                    }.get(key, key),
                ),
                rate_limiter=SimpleNamespace(record_sent=lambda: None, record_failure=lambda **kwargs: None),
                client=None,
            )
            handler = PollsHandler(monitor)
            handler.send_response = AsyncMock()
            message = SimpleNamespace(
                guild=SimpleNamespace(id=123),
                channel=SimpleNamespace(id=456),
                author=SimpleNamespace(id=7, name="Tester"),
            )

            await handler.handle_vote(message, {"option_index": 1})

            response = handler.send_response.await_args.args[1]
            self.assertIn("flere aktive avstemninger", response)

    async def test_delete_with_multiple_active_polls_requires_disambiguation(self):
        with TemporaryDirectory() as tmp:
            manager = PollManager(storage_path=Path(tmp) / "polls.json")
            manager.create_poll("123", "Første?", ["Ja", "Nei"], "Tester", created_by_id=7)
            manager.create_poll("123", "Andre?", ["Ja", "Nei"], "Tester", created_by_id=7)
            monitor = SimpleNamespace(
                poll=manager,
                loc=SimpleNamespace(
                    current_lang="no",
                    t=lambda key, **kwargs: {
                        "poll_not_found": "Fant ikke poll",
                        "poll_deleted": "Slettet poll",
                        "poll_not_owner": "Ikke eier",
                    }.get(key, key),
                ),
                rate_limiter=SimpleNamespace(record_sent=lambda: None, record_failure=lambda **kwargs: None),
                client=None,
            )
            handler = PollsHandler(monitor)
            handler.send_response = AsyncMock()
            message = SimpleNamespace(
                guild=SimpleNamespace(id=123),
                channel=SimpleNamespace(id=456),
                author=SimpleNamespace(id=7, name="Tester"),
            )

            await handler.handle_poll_delete(message, {"target": None})

            response = handler.send_response.await_args.args[1]
            self.assertIn("flere aktive avstemninger", response)
            self.assertEqual(len(manager.get_active_polls("123")), 2)


if __name__ == "__main__":
    _ = unittest.main()
