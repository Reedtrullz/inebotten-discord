#!/usr/bin/env python3
"""Async monitor routing regressions."""

import unittest
from types import SimpleNamespace

from core.intent_router import IntentRouter
from core.message_monitor import MessageMonitor


class FakeRateLimiter:
    def __init__(self):
        self.sent = 0

    def can_send(self):
        return True, "ok"

    async def wait_if_needed(self):
        return True

    def record_sent(self):
        self.sent += 1

    def record_dropped(self):
        pass

    def record_failure(self, is_rate_limit=False):
        pass

    def get_stats(self):
        return {"sent_last_second": 0, "sent_today": self.sent}


class FakeConversation:
    def __init__(self, wants_dashboard=False):
        self.wants_dashboard_value = wants_dashboard
        self.messages = []

    def should_show_dashboard(self, content, channel_id):
        return self.wants_dashboard_value, "test"

    def add_message(self, **kwargs):
        self.messages.append(kwargs)

    def get_conversation_summary(self, channel_id):
        return None

    def get_context(self, channel_id, limit=5):
        return ""


class FakeUserMemory:
    async def update_last_interaction(self, *args, **kwargs):
        pass

    async def format_context_for_prompt(self, *args, **kwargs):
        return ""

    async def get_memory(self, *args, **kwargs):
        return {}


class RecordingMessage:
    def __init__(self, content):
        self.id = 1
        self.content = content
        self.mentions = []
        self.guild = None
        self.channel = SimpleNamespace(id=100)
        self.author = SimpleNamespace(id=7, name="Tester")
        self.replies = []

    async def reply(self, content, mention_author=False):
        self.replies.append(content)


class RecordingPollsHandler:
    def __init__(self):
        self.votes = []

    async def handle_vote(self, message, vote):
        self.votes.append((message, vote))


class MessageMonitorRoutingTests(unittest.IsolatedAsyncioTestCase):
    def make_monitor(self, wants_dashboard=False, active_polls=False):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.client = SimpleNamespace(user=SimpleNamespace(id=42))
        monitor.bot_name = "inebotten"
        monitor.bot_mention = "@inebotten"
        monitor.processed_messages = []
        monitor.mention_count = 0
        monitor.response_count = 0
        monitor.rate_limiter = FakeRateLimiter()
        monitor.loc = SimpleNamespace(detect_language=lambda content: "no", set_language=lambda lang: None)
        monitor.nlp_parser = SimpleNamespace(
            parse_task_with_recurrence=lambda content: None,
            parse_event=lambda content: None,
        )
        monitor.conversation = FakeConversation(wants_dashboard=wants_dashboard)
        monitor.user_memory = FakeUserMemory()
        monitor.hermes = None
        monitor.ResponseStyle = SimpleNamespace(CASUAL="casual")
        monitor.get_system_prompt = lambda **kwargs: ""
        monitor.search_manager = SimpleNamespace()
        monitor.browser_manager = SimpleNamespace(is_configured=lambda: False)
        monitor.detect_search_intent = lambda content: None
        monitor.calendar = SimpleNamespace(get_upcoming=lambda guild_id, days=7: [])
        monitor.conv_gen = SimpleNamespace(generate_dashboard=lambda **kwargs: "dashboard")

        monitor.countdown = SimpleNamespace(parse_countdown_query=lambda content: None)
        monitor.poll = SimpleNamespace(
            get_active_polls=lambda guild_id: [{"id": "poll1"}] if active_polls else []
        )
        monitor.parse_poll_command = lambda content: None
        monitor.parse_vote = lambda content: int(content) if content.strip().isdigit() else None
        monitor.parse_watchlist_command = lambda content: None
        monitor.parse_quote_command = lambda content: None
        monitor.parse_price_command = lambda content: None
        monitor.parse_horoscope_command = lambda content: None
        monitor.parse_compliment_command = lambda content: None
        monitor.parse_calculator_command = lambda content: None
        monitor.parse_shorten_command = lambda content: None

        polls = RecordingPollsHandler()
        monitor.handlers = {
            "polls": polls,
            "help": SimpleNamespace(handle_help=lambda message: None),
        }
        monitor.intent_router = IntentRouter(monitor)
        monitor.recording_polls = polls
        return monitor

    async def test_ai_fallback_no_longer_crashes_on_chat(self):
        monitor = self.make_monitor()
        message = RecordingMessage("@inebotten hva skjer?")

        await monitor.handle_message(message)

        self.assertEqual(monitor.mention_count, 1)
        self.assertEqual(len(message.replies), 1)
        self.assertEqual(monitor.response_count, 1)

    async def test_dashboard_fallback_has_defined_context(self):
        monitor = self.make_monitor(wants_dashboard=True)

        async def fake_dashboard(guild_id, city_name=None, show_navnedag=False):
            return f"dashboard:{guild_id}:{show_navnedag}"

        monitor._generate_dashboard = fake_dashboard
        message = RecordingMessage("@inebotten vis dashboard")

        await monitor.handle_message(message)

        self.assertEqual(message.replies, ["dashboard:100:False"])

    async def test_active_poll_vote_routes_before_ai(self):
        monitor = self.make_monitor(active_polls=True)
        message = RecordingMessage("@inebotten 1")

        await monitor.handle_message(message)

        self.assertEqual(len(monitor.recording_polls.votes), 1)
        self.assertEqual(monitor.recording_polls.votes[0][1], 1)
        self.assertEqual(message.replies, [])


if __name__ == "__main__":
    unittest.main()
