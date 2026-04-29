#!/usr/bin/env python3
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownLambdaType=false, reportUnknownParameterType=false, reportUnannotatedClassAttribute=false, reportImplicitOverride=false, reportUnusedCallResult=false, reportUnusedParameter=false, reportUnknownArgumentType=false, reportUninitializedInstanceVariable=false, reportOptionalSubscript=false, reportMissingParameterType=false
"""Regression tests for watchlist and birthday edit/remove flows."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast

from core.intent_router import BotIntent, IntentRouter
from features.birthday_manager import BirthdayManager
from features.watchlist_manager import WatchlistManager, parse_watchlist_command


class DummyMonitor:
    def __init__(self):
        self.nlp_parser = SimpleNamespace(
            parse_task_with_recurrence=lambda content: None,
            parse_event=lambda content: None,
        )
        self.countdown = SimpleNamespace(parse_countdown_query=lambda content: None)
        self.conversation = SimpleNamespace(
            should_show_dashboard=lambda content, guild_id: (False, "default"),
        )
        self.detect_search_intent = lambda content: None
        self.parse_watchlist_command = parse_watchlist_command
        self.parse_poll_command = lambda content: None
        self.parse_vote = lambda content: None
        self.parse_quote_command = lambda content: None
        self.parse_price_command = lambda content: None
        self.parse_horoscope_command = lambda content: None
        self.parse_compliment_command = lambda content: None
        self.parse_calculator_command = lambda content: None
        self.parse_shorten_command = lambda content: None
        self.poll = SimpleNamespace(get_active_polls=lambda guild_id: [])

    def _has_active_poll(self, guild_id):
        return False


class WatchlistBirthdayEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.storage_dir = Path(self.tmp.name)
        self.watchlist_path = self.storage_dir / "watchlist.json"
        self.birthday_path = self.storage_dir / "birthdays.json"
        self.watchlist = WatchlistManager(storage_path=self.watchlist_path)
        self.watchlist.watchlist = {"movies": [], "series": []}
        self.birthdays = BirthdayManager(storage_path=self.birthday_path)
        self.birthdays.birthdays = {}
        self.birthdays.gcal = None
        self.birthdays.gcal_enabled = False

    def tearDown(self):
        self.tmp.cleanup()

    def test_remove_from_watchlist_removes_by_index(self):
        self.watchlist.add_from_discord_message("Movie A", "movie", guild_id=123)
        self.watchlist.add_from_discord_message("Series B", "series", guild_id=123)

        removed = self.watchlist.remove_from_watchlist(2, guild_id=123)

        self.assertIsNotNone(removed)
        self.assertEqual(removed["title"], "Series B")
        self.assertEqual([item["title"] for item in self.watchlist.get_watchlist(123)], ["Movie A"])

    def test_remove_from_watchlist_invalid_index_raises_value_error(self):
        self.watchlist.add_from_discord_message("Movie A", "movie", guild_id=123)

        with self.assertRaises(ValueError):
            self.watchlist.remove_from_watchlist(2, guild_id=123)

    def test_edit_watchlist_entry_updates_title(self):
        self.watchlist.add_from_discord_message("Old Title", "movie", guild_id=123)

        item = self.watchlist.edit_watchlist_entry(1, title="New Title", guild_id=123)

        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "New Title")
        self.assertEqual(self.watchlist.get_watchlist(123)[0]["title"], "New Title")

    def test_edit_watchlist_entry_updates_type_and_moves_between_buckets(self):
        self.watchlist.add_from_discord_message("Switch Me", "movie", guild_id=123)

        item = self.watchlist.edit_watchlist_entry(1, type="series", guild_id=123)

        self.assertIsNotNone(item)
        self.assertEqual(item["type"], "series")
        scopes = cast(
            dict[str, dict[str, list[dict[str, object]]]],
            self.watchlist.watchlist.get("scopes", {}),
        )
        scoped = scopes["123"]
        self.assertEqual(scoped["movies"], [])
        self.assertEqual(len(scoped["series"]), 1)
        self.assertEqual(scoped["series"][0]["title"], "Switch Me")

    def test_edit_birthday_updates_date_by_name(self):
        self.birthdays.add_birthday(123, 1, "Ola Nordmann", 1, 1, 1990)

        updated = self.birthdays.edit_birthday(123, "Ola Nordmann", 2, 3, 1991)

        self.assertIsNotNone(updated)
        self.assertEqual(updated["day"], 2)
        self.assertEqual(updated["month"], 3)
        self.assertEqual(updated["year"], 1991)
        self.assertIn("updated_at", updated)

    def test_edit_birthday_case_insensitive_name_match(self):
        self.birthdays.add_birthday(123, 1, "Ola Nordmann", 1, 1, 1990)

        updated = self.birthdays.edit_birthday(123, "ola nordmann", 4, 5)

        self.assertIsNotNone(updated)
        self.assertEqual(updated["day"], 4)
        self.assertEqual(updated["month"], 5)
        self.assertEqual(updated["username"], "Ola Nordmann")

    def test_edit_birthday_missing_name_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.birthdays.edit_birthday(123, "Mangler Navn", 1, 1)

    def test_intent_routing_fjern_watchlist_routes_correctly(self):
        route = IntentRouter(DummyMonitor()).route("fjern watchlist 2", guild_id=123)

        self.assertEqual(route.intent, BotIntent.WATCHLIST)
        self.assertEqual(route.payload["watchlist"]["action"], "remove")
        self.assertEqual(route.payload["watchlist"]["index"], 2)

    def test_intent_routing_endre_bursdag_routes_correctly(self):
        route = IntentRouter(DummyMonitor()).route("endre bursdag Ola Nordmann 02.03.1991", guild_id=123)

        self.assertEqual(route.intent, BotIntent.BIRTHDAY_EDIT)
        self.assertEqual(route.reason, "birthday_edit_keyword")


if __name__ == "__main__":
    unittest.main()
