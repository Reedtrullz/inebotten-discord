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

from features.watchlist_manager import WatchlistManager


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
