#!/usr/bin/env python3
"""Tests for group-scoped watchlists."""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

try:
    import discord  # noqa: F401
except ModuleNotFoundError:
    class _FakeDiscordClient:
        def __init__(self, *args, **kwargs):
            pass

    sys.modules["discord"] = SimpleNamespace(
        Client=_FakeDiscordClient,
        DMChannel=type("DMChannel", (), {}),
        GroupChannel=type("GroupChannel", (), {}),
        TextChannel=type("TextChannel", (), {}),
        Message=type("Message", (), {}),
        errors=SimpleNamespace(
            Forbidden=type("Forbidden", (Exception,), {}),
            HTTPException=type("HTTPException", (Exception,), {}),
        ),
    )

from features.watchlist_manager import WatchlistManager, parse_watchlist_command


class WatchlistParserContractTests(unittest.TestCase):
    def test_owned_watchlist_questions_parse_as_status(self):
        for text in (
            "what’s on my watchlist?",
            "show me my watchlist",
            "which movies are on my watchlist?",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    parse_watchlist_command(text),
                    {"action": "status", "lang": "en"},
                )

    def test_add_requires_a_bounded_watchlist_frame_and_preserves_case(self):
        cases = (
            ("husk å se Inception", "Inception"),
            ("hugs å sjå Arrival", "Arrival"),
            ("remember to watch The Bear", "The Bear"),
            ("legg til film Inception", "Inception"),
            ("add The Bear to watchlist", "The Bear"),
            ("Kan du legge Inception til watchlisten min?", "Inception"),
            ("Kan du legge til Inception på watchlisten min?", "Inception"),
            ("Kan du huske at jeg vil se Inception?", "Inception"),
            ("Kan du huske at jeg skal se Inception?", "Inception"),
        )
        for text, title in cases:
            with self.subTest(text=text):
                parsed = parse_watchlist_command(text)
                self.assertEqual(parsed["action"], "add")
                self.assertEqual(parsed["title"], title)

    def test_generic_and_cross_language_frames_are_inert(self):
        for text in (
            "legg til melk",
            "fjern nummer 2",
            "endre tittel",
            "se her",
            "add to watchlist",
            "legg til i watchlist",
            "fjern på watchlist",
            "endre i watchlist",
            "add movie Inception",
            "legg til show The Bear",
            "Kan du huske at jeg vil se hvordan dette virker?",
            "Kan du huske at jeg skal se legen i morgen?",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_watchlist_command(text))

    def test_mutations_return_complete_typed_fields(self):
        self.assertEqual(
            parse_watchlist_command("fjern film 2"),
            {
                "action": "remove",
                "index": 2,
                "type": "movie",
                "lang": "no",
            },
        )
        self.assertEqual(
            parse_watchlist_command(
                "endre watchlist 2 tittel: The Matrix type: film "
                "sjanger: sci-fi kommentar: klassiker"
            ),
            {
                "action": "edit",
                "index": 2,
                "title": "The Matrix",
                "type": "movie",
                "genre": "sci-fi",
                "comment": "klassiker",
                "lang": "no",
            },
        )


class WatchlistScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        self.manager = WatchlistManager(storage_path=self.temp_file.name)

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_group_watchlists_are_separate(self):
        self.manager.add_from_discord_message("Movie A", guild_id=100)
        self.manager.add_from_discord_message("Movie B", guild_id=200)

        group_a_titles = {item["title"] for item in self.manager.get_watchlist(100)}
        group_b_titles = {item["title"] for item in self.manager.get_watchlist(200)}

        self.assertEqual(group_a_titles, {"Movie A"})
        self.assertEqual(group_b_titles, {"Movie B"})

    def test_legacy_global_watchlist_still_works_without_scope(self):
        self.manager.add_from_discord_message("Global Movie")

        titles = {item["title"] for item in self.manager.get_watchlist()}

        self.assertEqual(titles, {"Global Movie"})


if __name__ == "__main__":
    unittest.main()
