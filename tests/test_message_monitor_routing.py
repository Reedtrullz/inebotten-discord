#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnusedCallResult=false, reportUnknownLambdaType=false, reportUnusedParameter=false
"""Async monitor routing regressions."""

import unittest
import asyncio
from collections import defaultdict
from types import SimpleNamespace

from core.intent_router import BotIntent, IntentRouter
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
    _next_id = 1

    def __init__(self, content):
        self.id = RecordingMessage._next_id
        RecordingMessage._next_id += 1
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
    def make_monitor(self, wants_dashboard=False, active_polls=False, active_reminders=False):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.client = SimpleNamespace(
            user=SimpleNamespace(id=42),
            config=SimpleNamespace(ALLOWED_USERS=[], ALLOWED_CHANNELS=[])
        )
        monitor.bot_name = "inebotten"
        monitor.bot_mention = "@inebotten"
        monitor.processed_messages = []
        monitor.mention_count = 0
        monitor.response_count = 0
        monitor.error_count = 0
        monitor.intent_stats = defaultdict(lambda: {"count": 0, "low_confidence": 0, "errors": 0})
        monitor._background_tasks = set()
        monitor._task_health = {}
        monitor._last_persisted_intent_stats = {}
        monitor._last_persisted_rate_stats = {}
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
        monitor.reminders = SimpleNamespace(
            get_active_reminders=lambda guild_id: [{"id": "rem1"}] if active_reminders else []
        )
        monitor.parse_poll_command = lambda content: None
        monitor.parse_vote = lambda content: int(content) if content.strip().isdigit() else None
        def parse_watchlist_command(content):
            lower = content.lower()
            if "fjern watchlist" in lower or "slett watchlist" in lower or "fjern fra watchlist" in lower:
                return {"action": "remove"}
            if "endre watchlist" in lower or "rediger watchlist" in lower:
                return {"action": "edit"}
            return None

        monitor.parse_watchlist_command = parse_watchlist_command
        monitor.parse_quote_command = lambda content: None
        monitor.parse_price_command = lambda content: None
        monitor.parse_horoscope_command = lambda content: None
        monitor.parse_compliment_command = lambda content: None
        monitor.parse_calculator_command = lambda content: None
        monitor.parse_shorten_command = lambda content: None

        async def noop(*args, **kwargs):
            return None

        polls = RecordingPollsHandler()
        monitor.handlers = {
            "polls": polls,
            "help": SimpleNamespace(handle_help=lambda message: None),
            "reminders": SimpleNamespace(
                handle_reminder_edit=noop,
                handle_reminder_delete=noop,
                handle_reminder_search=noop,
                handle_reminder_create=noop,
                handle_reminder_list=noop,
                handle_reminder_complete=noop,
            ),
            "quotes": SimpleNamespace(
                handle_quote_list=noop,
                handle_quote_edit=noop,
                handle_quote_delete=noop,
            ),
            "watchlist": SimpleNamespace(
                handle_watchlist=noop,
                handle_watchlist_edit=noop,
                handle_watchlist_remove=noop,
            ),
            "birthdays": SimpleNamespace(handle_birthday_edit=noop),
            "calendar": SimpleNamespace(handle_search=noop, handle_delete=noop),
        }
        monitor.intent_router = IntentRouter(monitor)
        monitor.recording_polls = polls
        return monitor

    async def test_successful_routing_increments_intent_count(self):
        monitor = self.make_monitor()

        async def fake_help(message):
            return None

        monitor.handlers["help"].handle_help = fake_help
        message = RecordingMessage("@inebotten hjelp")

        await monitor.handle_message(message)

        self.assertEqual(monitor.intent_stats[BotIntent.HELP.value]["count"], 1)

    async def test_low_confidence_rejection_is_tracked(self):
        monitor = self.make_monitor()

        async def fake_ai_response(message):
            return None

        monitor._send_ai_response = fake_ai_response
        route = SimpleNamespace(intent=BotIntent.SEARCH, confidence=0.0, payload=None)

        await monitor._handle_intent(RecordingMessage("@inebotten hjelp"), route)

        self.assertEqual(monitor.intent_stats[BotIntent.SEARCH.value]["low_confidence"], 1)

    async def test_exception_handler_tracks_intent_errors(self):
        monitor = self.make_monitor()

        async def boom(message):
            raise RuntimeError("boom")

        monitor.handlers["help"].handle_help = boom
        message = RecordingMessage("@inebotten hjelp")

        await monitor.handle_message(message)

        self.assertEqual(monitor.error_count, 1)
        self.assertEqual(monitor.intent_stats[BotIntent.HELP.value]["errors"], 1)

    async def test_status_response_includes_intent_stats(self):
        monitor = self.make_monitor()
        monitor.intent_stats["help"]["count"] = 3
        monitor.intent_stats["help"]["low_confidence"] = 1
        monitor.intent_stats["help"]["errors"] = 2

        captured = {}

        async def fake_send_response(message, response_text):
            captured["text"] = response_text

        monitor._send_response = fake_send_response

        await monitor._send_status_response(RecordingMessage("@inebotten status"))

        self.assertIn("Intent stats:", captured["text"])
        self.assertIn("help: 3 (low: 1, err: 2)", captured["text"])
        self.assertEqual(monitor.get_intent_stats()["help"]["count"], 3)

    def test_console_persistence_uses_counter_deltas(self):
        from core import message_monitor

        current = {
            "ai_chat": {"count": 10, "low_confidence": 0, "errors": 1},
            "search": {"count": 3, "low_confidence": 2, "errors": 0},
        }
        previous = {
            "ai_chat": {"count": 7, "low_confidence": 0, "errors": 1},
            "calendar": {"count": 5, "low_confidence": 0, "errors": 0},
        }

        self.assertEqual(
            message_monitor._counter_stats_delta(current, previous),
            {
                "ai_chat": {"count": 3, "low_confidence": 0, "errors": 0},
                "search": {"count": 3, "low_confidence": 2, "errors": 0},
            },
        )
        self.assertEqual(
            message_monitor._flat_counter_delta({"u1": 10, "u2": 1}, {"u1": 8, "u3": 9}),
            {"u1": 2, "u2": 1},
        )

    async def test_failed_background_task_is_visible_in_health(self):
        monitor = self.make_monitor()

        async def boom():
            raise RuntimeError("task failed")

        monitor._track_background_task(boom(), "boom-task")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        task_health = monitor.get_task_health()["boom-task"]
        self.assertEqual(task_health["state"], "failed")
        self.assertIn("task failed", task_health["last_error"])

    async def test_console_persistence_failure_does_not_advance_snapshot(self):
        monitor = self.make_monitor()
        monitor.intent_stats["search"]["count"] = 3

        class FailingStore:
            def save_stats(self, intent_stats, rate_limit_stats):
                return False

        from web_console import console_store

        old_store = console_store._store
        console_store._store = FailingStore()
        try:
            with self.assertRaises(RuntimeError):
                await monitor._persist_console_stats_once()
        finally:
            console_store._store = old_store

        self.assertEqual(monitor._last_persisted_intent_stats, {})

    async def test_search_intent_uses_routed_payload(self):
        monitor = self.make_monitor()
        captured = {}

        async def fake_ai_response(message, forced_search_info=None):
            captured["forced_search_info"] = forced_search_info

        monitor._send_ai_response = fake_ai_response
        search_payload = {"query": "dagens nyheter", "type": "web"}
        route = SimpleNamespace(
            intent=BotIntent.SEARCH,
            confidence=0.9,
            payload={"search": search_payload},
        )

        await monitor._handle_intent(RecordingMessage("@inebotten søk på nett dagens nyheter"), route)

        self.assertEqual(captured["forced_search_info"], search_payload)

    async def test_dashboard_intent_uses_explicit_dashboard_handler(self):
        monitor = self.make_monitor()
        captured = {}

        async def fake_dashboard(message):
            captured["message"] = message

        monitor._send_dashboard_response = fake_dashboard
        route = SimpleNamespace(intent=BotIntent.DASHBOARD, confidence=0.9, payload={})
        message = RecordingMessage("@inebotten dashboard")

        await monitor._handle_intent(message, route)

        self.assertIs(captured["message"], message)

    async def test_ai_fallback_no_longer_crashes_on_chat(self):
        monitor = self.make_monitor()
        message = RecordingMessage("@inebotten hva skjer?")

        await monitor.handle_message(message)

        self.assertEqual(monitor.mention_count, 1)
        self.assertEqual(len(message.replies), 1)
        self.assertEqual(monitor.response_count, 1)

    async def test_dashboard_fallback_has_defined_context(self):
        monitor = self.make_monitor(wants_dashboard=True)

        async def fake_dashboard(guild_id, city_name=None, show_navnedag=False, user_id=None):
            return f"dashboard:{guild_id}:{show_navnedag}"

        monitor._generate_dashboard = fake_dashboard
        message = RecordingMessage("@inebotten vis dashboard")

        await monitor.handle_message(message)

        self.assertEqual(message.replies, ["dashboard:100:False"])

    async def test_poll_list_routes_to_handler(self):
        monitor = self.make_monitor(active_polls=True)

        calls = []

        async def fake_handle_poll_list(message):
            calls.append(message)

        monitor.handlers["polls"].handle_poll_list = fake_handle_poll_list
        message = RecordingMessage("@inebotten polls")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].content, "polls")
        self.assertEqual(monitor.intent_stats[BotIntent.POLL_LIST.value]["count"], 1)

    async def test_active_poll_vote_routes_before_ai(self):
        monitor = self.make_monitor(active_polls=True)
        message = RecordingMessage("@inebotten 1")

        await monitor.handle_message(message)

        self.assertEqual(len(monitor.recording_polls.votes), 1)
        self.assertEqual(monitor.recording_polls.votes[0][1], 1)
        self.assertEqual(message.replies, [])

    async def test_reminder_edit_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_reminder_edit(message, payload):
            calls.append((message.content, payload["watchlist"] if "watchlist" in payload else payload))

        monitor.handlers["reminders"].handle_reminder_edit = fake_handle_reminder_edit
        message = RecordingMessage("@inebotten endre påminnelse")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(monitor.intent_stats[BotIntent.REMINDER_EDIT.value]["count"], 1)

    async def test_calendar_search_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_calendar_search(message, payload):
            calls.append((message.content, payload))

        monitor.handlers["calendar"].handle_search = fake_handle_calendar_search
        message = RecordingMessage("@inebotten søk kalender møte")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["query"], "møte")
        self.assertEqual(monitor.intent_stats[BotIntent.CALENDAR_SEARCH.value]["count"], 1)

    async def test_reminder_create_list_and_complete_route_to_handlers(self):
        monitor = self.make_monitor(active_reminders=True)
        calls = []

        async def fake_create(message, payload):
            calls.append(("create", payload))

        async def fake_list(message, payload):
            calls.append(("list", payload))

        async def fake_complete(message, payload):
            calls.append(("complete", payload))

        monitor.handlers["reminders"].handle_reminder_create = fake_create
        monitor.handlers["reminders"].handle_reminder_list = fake_list
        monitor.handlers["reminders"].handle_reminder_complete = fake_complete

        await monitor.handle_message(RecordingMessage("@inebotten påminnelse Ring lege om 2 timer"))
        await monitor.handle_message(RecordingMessage("@inebotten påminnelser"))
        await monitor.handle_message(RecordingMessage("@inebotten ferdig 1"))

        self.assertEqual([call[0] for call in calls], ["create", "list", "complete"])

    async def test_bare_calendar_title_delete_routes_to_calendar_handler(self):
        monitor = self.make_monitor()
        monitor.calendar = SimpleNamespace(
            get_upcoming=lambda guild_id, days=365: [
                {"title": "Send inn meldekort (Uke 25 - 26)", "date": "29.06.2026", "time": "12:00"}
            ]
        )
        monitor.intent_router = IntentRouter(monitor)
        calls = []

        async def fake_handle_calendar_delete(message):
            calls.append(message.content)

        monitor.handlers["calendar"].handle_delete = fake_handle_calendar_delete
        message = RecordingMessage("@inebotten slett meldekort")

        await monitor.handle_message(message)

        self.assertEqual(calls, ["slett meldekort"])
        self.assertEqual(monitor.intent_stats[BotIntent.CALENDAR_DELETE.value]["count"], 1)

    async def test_reminder_search_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_reminder_search(message, payload):
            calls.append((message.content, payload))

        monitor.handlers["reminders"].handle_reminder_search = fake_handle_reminder_search
        message = RecordingMessage("@inebotten søk påminnelse lege")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["query"], "lege")
        self.assertEqual(monitor.intent_stats[BotIntent.REMINDER_SEARCH.value]["count"], 1)

    async def test_quote_list_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_quote_list(message):
            calls.append(message.content)

        monitor.handlers["quotes"].handle_quote_list = fake_handle_quote_list
        message = RecordingMessage("@inebotten liste sitater")

        await monitor.handle_message(message)

        self.assertEqual(calls, ["liste sitater"])
        self.assertEqual(monitor.intent_stats[BotIntent.QUOTE_LIST.value]["count"], 1)

    async def test_birthday_edit_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_birthday_edit(message, payload):
            calls.append((message.content, payload))

        monitor.handlers["birthdays"].handle_birthday_edit = fake_handle_birthday_edit
        message = RecordingMessage("@inebotten endre bursdag")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(monitor.intent_stats[BotIntent.BIRTHDAY_EDIT.value]["count"], 1)

    async def test_watchlist_remove_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_watchlist_remove(message, payload):
            calls.append((message.content, payload))

        monitor.handlers["watchlist"].handle_watchlist_remove = fake_handle_watchlist_remove
        message = RecordingMessage("@inebotten fjern watchlist")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["action"], "remove")
        self.assertEqual(monitor.intent_stats[BotIntent.WATCHLIST.value]["count"], 1)

    async def test_watchlist_remove_sends_returned_handler_response(self):
        monitor = self.make_monitor()

        async def fake_handle_watchlist_remove(message, payload):
            return "✅ Fjernet Movie A"

        monitor.handlers["watchlist"].handle_watchlist_remove = fake_handle_watchlist_remove
        message = RecordingMessage("@inebotten fjern watchlist 1")

        await monitor.handle_message(message)

        self.assertEqual(message.replies, ["✅ Fjernet Movie A"])
        self.assertEqual(monitor.response_count, 1)


if __name__ == "__main__":
    unittest.main()
