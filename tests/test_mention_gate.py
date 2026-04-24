#!/usr/bin/env python3
"""Tests for Inebotten's explicit mention gate."""

import unittest
import sys
from types import SimpleNamespace

try:
    import discord  # noqa: F401
except ModuleNotFoundError:
    class _FakeDiscordClient:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeDiscordError(Exception):
        def __init__(self, *args, status=None, **kwargs):
            super().__init__(*args)
            self.status = status

    sys.modules["discord"] = SimpleNamespace(
        Client=_FakeDiscordClient,
        DMChannel=type("DMChannel", (), {}),
        GroupChannel=type("GroupChannel", (), {}),
        TextChannel=type("TextChannel", (), {}),
        Message=type("Message", (), {}),
        errors=SimpleNamespace(
            Forbidden=type("Forbidden", (_FakeDiscordError,), {}),
            HTTPException=type("HTTPException", (_FakeDiscordError,), {}),
        ),
    )

from core.message_monitor import MessageMonitor


class FakeRateLimiter:
    def __init__(self):
        self.can_send_calls = 0
        self.wait_calls = 0
        self.dropped = 0

    def can_send(self):
        self.can_send_calls += 1
        return True, "ok"

    async def wait_if_needed(self):
        self.wait_calls += 1
        return True

    def record_dropped(self):
        self.dropped += 1

    def get_stats(self):
        return {"sent_last_second": 0, "sent_today": 0}


class FakeLocalization:
    current_lang = "en"

    def detect_language(self, content):
        return "en"

    def set_language(self, lang):
        self.current_lang = lang


class FakeParser:
    def parse_task_with_recurrence(self, content):
        return None

    def parse_event(self, content):
        return None


class RecordingHelpHandler:
    def __init__(self):
        self.messages = []

    async def handle_help(self, message):
        self.messages.append(message)


class MentionGateTests(unittest.IsolatedAsyncioTestCase):
    def make_monitor(self):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.client = SimpleNamespace(user=SimpleNamespace(id=42))
        monitor.bot_name = "inebotten"
        monitor.bot_mention = "@inebotten"
        monitor.processed_messages = []
        monitor.mention_count = 0
        monitor.response_count = 0
        monitor.rate_limiter = FakeRateLimiter()
        monitor.loc = FakeLocalization()
        monitor.nlp_parser = FakeParser()
        monitor.handlers = {"help": RecordingHelpHandler()}
        monitor.countdown = SimpleNamespace(parse_countdown_query=lambda content: None)
        monitor.parse_poll_command = lambda content: None
        monitor.parse_vote = lambda content: None
        monitor.parse_watchlist_command = lambda content: None
        monitor.parse_quote_command = lambda content: None
        monitor.parse_price_command = lambda content: None
        monitor.parse_horoscope_command = lambda content: None
        monitor.parse_compliment_command = lambda content: None
        monitor.parse_calculator_command = lambda content: None
        monitor.parse_shorten_command = lambda content: None
        return monitor

    def make_message(self, content, mentions=None, message_id=1):
        return SimpleNamespace(
            id=message_id,
            content=content,
            mentions=mentions or [],
            guild=None,
            channel=SimpleNamespace(id=100),
            author=SimpleNamespace(id=7, name="Tester"),
        )

    async def test_untagged_message_is_ignored_without_tracking_or_rate_limit(self):
        monitor = self.make_monitor()
        message = self.make_message("plain private group chat")

        await monitor.handle_message(message)

        self.assertEqual(monitor.mention_count, 0)
        self.assertEqual(monitor.processed_messages, [])
        self.assertEqual(monitor.rate_limiter.can_send_calls, 0)
        self.assertEqual(monitor.handlers["help"].messages, [])

    def test_dm_style_message_is_not_implicitly_authorized(self):
        monitor = self.make_monitor()
        message = self.make_message("help")

        self.assertFalse(monitor.is_mention(message))
        self.assertIsNone(monitor.authorize_message(message))

    def test_own_discord_mention_is_removed_after_authorization(self):
        monitor = self.make_monitor()
        message = self.make_message("<@42> help")

        authorized = monitor.authorize_message(message)

        self.assertIsNotNone(authorized)
        self.assertEqual(authorized.content, "help")
        self.assertEqual(authorized.raw_content, "<@42> help")

    def test_other_discord_mentions_are_preserved_in_authorized_text(self):
        monitor = self.make_monitor()
        message = self.make_message("<@!42> ask <@99> about Friday")

        authorized = monitor.authorize_message(message)

        self.assertEqual(authorized.content, "ask <@99> about Friday")

    def test_discord_mention_metadata_authorizes_message(self):
        monitor = self.make_monitor()
        message = self.make_message(
            "help",
            mentions=[SimpleNamespace(id=42)],
        )

        self.assertTrue(monitor.is_mention(message))

    async def test_tagged_help_routes_with_cleaned_content(self):
        monitor = self.make_monitor()
        message = self.make_message("@Inebotten help")

        await monitor.handle_message(message)

        self.assertEqual(monitor.mention_count, 1)
        self.assertEqual(len(monitor.handlers["help"].messages), 1)
        routed_message = monitor.handlers["help"].messages[0]
        self.assertEqual(routed_message.content, "help")
        self.assertEqual(routed_message.raw_content, "@Inebotten help")


if __name__ == "__main__":
    unittest.main()
