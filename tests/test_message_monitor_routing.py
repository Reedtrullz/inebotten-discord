#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false, reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnusedCallResult=false, reportUnknownLambdaType=false, reportUnusedParameter=false
"""Async monitor routing regressions."""

import unittest
import asyncio
import io
from collections import defaultdict
from contextlib import redirect_stdout
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from cal_system.temporal_resolver import TemporalResolver
from ai.chat_contract import (
    REDACTED_AUTH_TURN,
    ChatTurn,
    HistoryPolicy,
    capture_history_policy,
)
from core.dispatch_result import (
    DeliveryState,
    DispatchOutcome,
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationError,
    MessageSendResult,
)
from core.intent_models import IntentResult, IntentSource
from core.intent_payloads import PayloadValidationError
from core.intent_router import BotIntent, IntentRouter
from core.message_context import ConversationKey, routing_context_from_message
from core.message_monitor import MessageMonitor, RouteProcessOutcome
from core.mutation_coordinator import MutationCoordinator
from core.nlu_metrics import NLUMetrics
from core.pending_actions import PendingActionStore
from core.pending_targets import PendingTargetResolver
from core.send_receipt import DiscordSendCoordinator
from core.utterance import normalize_utterance
from features.ai_action_handler import AIActionHandler
from features.quote_manager import parse_quote_command
from features.watchlist_manager import parse_watchlist_command
from memory.conversation_context import ConversationContext


NOW = datetime(2026, 7, 15, 9, 30, tzinfo=ZoneInfo("Europe/Oslo"))

ACTION_HANDLER_CASES = (
    (BotIntent.CALENDAR_ITEM, "calendar_item", "calendar", "handle_calendar_item", True),
    (BotIntent.CALENDAR_EDIT, "calendar_edit", "calendar", "handle_edit", True),
    (BotIntent.CALENDAR_DELETE, "calendar_target", "calendar", "handle_delete", True),
    (BotIntent.CALENDAR_COMPLETE, "calendar_target", "calendar", "handle_complete", True),
    (BotIntent.CALENDAR_CLEAR, "calendar_target", "calendar", "handle_clear", True),
    (BotIntent.REMINDER_CREATE, "reminder", "reminders", "handle_reminder_create", True),
    (BotIntent.REMINDER_LIST, "reminder", "reminders", "handle_reminder_list", True),
    (BotIntent.REMINDER_SEARCH, "reminder", "reminders", "handle_reminder_search", True),
    (BotIntent.REMINDER_COMPLETE, "reminder", "reminders", "handle_reminder_complete", True),
    (BotIntent.REMINDER_EDIT, "reminder", "reminders", "handle_reminder_edit", True),
    (BotIntent.REMINDER_DELETE, "reminder", "reminders", "handle_reminder_delete", True),
    (BotIntent.POLL_CREATE, "poll", "polls", "handle_poll", True),
    (BotIntent.POLL_VOTE, "vote", "polls", "handle_vote", True),
    (BotIntent.POLL_EDIT, "poll_edit", "polls", "handle_poll_edit", True),
    (BotIntent.POLL_DELETE, "poll_delete", "polls", "handle_poll_delete", True),
    (BotIntent.POLL_CLOSE, "poll_close", "polls", "handle_poll_close", True),
    (BotIntent.BIRTHDAY_CREATE, "birthday", "birthdays", "handle_birthday_create", True),
    (BotIntent.BIRTHDAY_LIST, "birthday", "birthdays", "handle_birthday_list", True),
    (BotIntent.BIRTHDAY_EDIT, "birthday", "birthdays", "handle_birthday_edit", True),
    (BotIntent.WATCHLIST, "watchlist", "watchlist", "handle_watchlist", True),
    (BotIntent.QUOTE, "quote", "fun", "handle_quote_command", False),
    (BotIntent.QUOTE_LIST, "quote", "quotes", "handle_quote_list", False),
    (BotIntent.QUOTE_EDIT, "quote", "quotes", "handle_quote_edit", False),
    (BotIntent.QUOTE_DELETE, "quote", "quotes", "handle_quote_delete", False),
)


class FakeRateLimiter:
    def __init__(self):
        self.sent = 0
        self.can_send_calls = 0
        self.wait_calls = 0

    def can_send(self):
        self.can_send_calls += 1
        return True, "ok"

    async def wait_if_needed(self):
        self.wait_calls += 1
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
        self.threads = {}
        self.dashboard_channels = []
        self.summary_channels = []
        self.context_channels = []

    def should_show_dashboard(self, content, channel_id):
        self.dashboard_channels.append(channel_id)
        return self.wants_dashboard_value, "test"

    def add_message(self, **kwargs):
        self.messages.append(kwargs)

    def add_turn(self, key, turn):
        self.threads.setdefault(key, []).append(turn)
        self.messages.append({"key": key, "turn": turn})

    def stage_source_turn(self, key, turn):
        self.add_turn(key, turn)
        return True

    def reclassify_source_turn(self, key, source_message_id, policy):
        matched = False
        updated = []
        for turn in self.threads.get(key, ()):
            if not (
                isinstance(turn, ChatTurn)
                and turn.role == "user"
                and turn.source_message_id == source_message_id
            ):
                updated.append(turn)
                continue
            matched = True
            if policy is HistoryPolicy.OMIT:
                continue
            if policy is HistoryPolicy.REDACT_AUTH:
                turn = ChatTurn(
                    "user",
                    REDACTED_AUTH_TURN,
                    source_message_id,
                )
            updated.append(turn)
        if updated:
            self.threads[key] = updated
        else:
            self.threads.pop(key, None)
        return matched

    def get_prompt_history(
        self,
        key,
        *,
        limit=10,
        exclude_source_message_id=None,
    ):
        self.context_channels.append(key)
        return tuple(
            turn
            for turn in self.threads.get(key, ())[-limit:]
            if isinstance(turn, ChatTurn)
            and (
                exclude_source_message_id is None
                or turn.source_message_id != exclude_source_message_id
            )
        )

    def get_conversation_summary(self, channel_id):
        self.summary_channels.append(channel_id)
        return None

    def get_context(self, channel_id, limit=5):
        self.context_channels.append(channel_id)
        return ""


class FakeUserMemory:
    async def update_last_interaction(self, *args, **kwargs):
        pass

    async def update_last_interaction_result(self, *args, **kwargs):
        return True

    async def format_context_for_prompt(self, *args, **kwargs):
        return ""

    async def get_memory(self, *args, **kwargs):
        return {}

    def snapshot_user(self, *args, **kwargs):
        return None

    def snapshot_pending_user(self, *args, **kwargs):
        return None

    async def format_user_memory_for_user(self, *args, **kwargs):
        return "Jeg har ikke lagret noe brukerminne om deg ennå."

    async def export_user_memory(self, *args, **kwargs):
        return {}

    async def delete_user_memory_result(self, *args, **kwargs):
        return False


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

    async def reply(self, content, mention_author=False, **_kwargs):
        self.replies.append(content)


class RecordingPollsHandler:
    def __init__(self):
        self.votes = []

    async def handle_vote(self, message, vote, *, reference_time=None):
        self.votes.append((message, vote, reference_time))
        return DispatchOutcome.success(mutated=True)


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
        monitor._provider_history_quarantined = False
        monitor.rate_limiter = FakeRateLimiter()
        monitor.mutation_coordinator = MutationCoordinator()
        monitor.discord_sender = DiscordSendCoordinator(monitor.rate_limiter)
        monitor.reminder_clock = SimpleNamespace(now=Mock(return_value=NOW))
        clock_now = monitor.reminder_clock.now
        monitor._reference_time_now = clock_now
        monitor.nlu_metrics = NLUMetrics()
        monitor.temporal_resolver = TemporalResolver()
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
        monitor.calendar = SimpleNamespace(
            get_upcoming=lambda guild_id, days=7, reference_time=None: [],
            snapshot_pending_items=lambda *, reference_time: (),
            snapshot_all_item_ids=lambda: (),
        )
        monitor.conv_gen = SimpleNamespace(generate_dashboard=lambda **kwargs: "dashboard")

        monitor.countdown = SimpleNamespace(parse_countdown_query=lambda content: None)
        monitor.poll = SimpleNamespace(
            get_active_polls=lambda guild_id, reference_time=None: (
                [{"id": "poll1"}] if active_polls else []
            ),
            snapshot_pending_items=lambda scope_id, reference_time=None: (
                (
                    {
                        "poll_id": "poll1",
                        "question": "Test?",
                        "options": [
                            {"text": "Ja", "votes": []},
                            {"text": "Nei", "votes": []},
                        ],
                        "status": "active",
                    },
                )
                if active_polls
                else ()
            ),
        )
        monitor.reminders = SimpleNamespace(
            get_active_reminders=lambda guild_id: [{"id": "rem1"}] if active_reminders else [],
            snapshot_pending_items=lambda scope_id: (
                (
                    {
                        "id": "rem1",
                        "text": "Testpåminnelse",
                        "due_at": "2026-07-16T09:30:00+02:00",
                        "due_date": "16.07.2026",
                        "time": "09:30",
                        "timezone": "Europe/Oslo",
                        "recurrence": None,
                        "recurrence_sequence": 0,
                        "completed": False,
                    },
                )
                if active_reminders
                else ()
            ),
        )
        monitor.watchlist = SimpleNamespace(snapshot_pending_items=lambda scope_id: ())
        monitor.quote = SimpleNamespace(snapshot_pending_items=lambda scope_id: ())
        monitor.birthdays = SimpleNamespace(
            snapshot_pending_user=lambda scope_id, user_id: None
        )
        monitor.parse_poll_command = lambda content: None
        monitor.parse_vote = lambda content: int(content) if content.strip().isdigit() else None
        monitor.parse_watchlist_command = parse_watchlist_command
        monitor.parse_quote_command = parse_quote_command
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
            "fun": SimpleNamespace(handle_quote_command=noop),
            "watchlist": SimpleNamespace(
                handle_watchlist=noop,
                handle_watchlist_edit=noop,
                handle_watchlist_remove=noop,
            ),
            "birthdays": SimpleNamespace(handle_birthday_edit=noop),
            "calendar": SimpleNamespace(handle_search=noop, handle_delete=noop),
        }
        monitor.pending_actions = PendingActionStore(
            metrics=monitor.nlu_metrics,
            now_provider=clock_now,
        )
        monitor.pending_targets = PendingTargetResolver(
            monitor,
            coordinator=monitor.mutation_coordinator,
        )
        monitor.intent_router = IntentRouter(
            monitor,
            metrics=monitor.nlu_metrics,
            pending_actions=monitor.pending_actions,
            temporal_resolver=monitor.temporal_resolver,
            now_provider=clock_now,
        )
        monitor.ai_action_handler = AIActionHandler(
            store=monitor.pending_actions,
            dispatch_claimed=monitor._dispatch_claimed_intent,
            metrics=monitor.nlu_metrics,
            temporal_resolver=monitor.temporal_resolver,
        )
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

    async def test_routing_passes_exact_message_scope_to_intent_router(self):
        monitor = self.make_monitor()
        routed = []

        class RecordingRouter:
            def route_utterance(
                self,
                utterance,
                guild_id=None,
                *,
                channel_id=None,
                user_id=None,
                routing_context=None,
                reference_time=None,
            ):
                routed.append(
                    {
                        "content": utterance.raw,
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "routing_context": routing_context,
                        "reference_time": reference_time,
                    }
                )
                return IntentResult(
                    BotIntent.HELP,
                    1.0,
                    reason="recording_router",
                )

        handled = []

        async def noop_process_route(
            message,
            *,
            utterance,
            routing_context,
            route,
            reference_time,
        ):
            handled.append(reference_time)
            return RouteProcessOutcome(
                DispatchOutcome.success(),
                route,
                "routed",
            )

        monitor.intent_router = RecordingRouter()
        monitor._process_route = noop_process_route
        message = RecordingMessage("@inebotten hjelp")
        message.guild = SimpleNamespace(id=321)
        message.channel = SimpleNamespace(id=654)
        message.author = SimpleNamespace(id=987, name="Scoped user")

        await monitor.handle_message(message)

        self.assertEqual(
            routed,
            [
                {
                    "content": "hjelp",
                    "guild_id": 321,
                    "channel_id": 654,
                    "user_id": 987,
                    "routing_context": routed[0]["routing_context"],
                    "reference_time": NOW,
                }
            ],
        )
        routing = routed[0]["routing_context"]
        self.assertEqual(routing.key.guild_id, 321)
        self.assertEqual(routing.key.channel_id, 654)
        self.assertEqual(routing.key.user_id, 987)
        self.assertEqual(routing.author.display_name, "Scoped user")
        self.assertEqual(handled, [NOW])

    async def test_ai_conversation_uses_channel_scope_and_recipient_identity(self):
        monitor = self.make_monitor()

        class FakeHermes:
            async def generate_response(self, **kwargs):
                return True, "Et kaninsvar"

        monitor.hermes = FakeHermes()
        message = RecordingMessage("@inebotten fortell en historie om kaniner")
        message.guild = SimpleNamespace(id=999)
        message.channel = SimpleNamespace(id=100)
        message.author = SimpleNamespace(id=7, name="Current user")

        await monitor.handle_message(message)

        self.assertEqual(monitor.conversation.dashboard_channels, [])
        key = ConversationKey(999, 100, 7)
        self.assertEqual(monitor.conversation.summary_channels, [key])
        self.assertEqual(monitor.conversation.context_channels, [key])
        self.assertEqual(
            [entry["key"] for entry in monitor.conversation.messages],
            [key, key],
        )
        self.assertEqual(
            [entry["turn"].role for entry in monitor.conversation.messages],
            ["user", "assistant"],
        )
        self.assertEqual(
            [entry["turn"].content for entry in monitor.conversation.messages],
            ["fortell en historie om kaniner", "Et kaninsvar"],
        )

    async def test_dashboard_generation_keeps_guild_domain_scope(self):
        monitor = self.make_monitor(wants_dashboard=True)
        generated = []

        async def fake_dashboard(
            guild_id,
            city_name=None,
            show_navnedag=False,
            user_id=None,
            *,
            reference_time=None,
        ):
            generated.append((guild_id, user_id))
            return "dashboard"

        monitor._generate_dashboard = fake_dashboard
        message = RecordingMessage("@inebotten fortell en historie om kaniner")
        message.guild = SimpleNamespace(id=999)
        message.channel = SimpleNamespace(id=100)
        message.author = SimpleNamespace(id=7, name="Current user")

        await monitor.handle_message(message)

        self.assertEqual(monitor.conversation.dashboard_channels, [])
        self.assertEqual(generated, [])
        self.assertEqual(
            [entry["turn"].role for entry in monitor.conversation.messages],
            ["user", "assistant"],
        )

    async def test_real_conversation_followup_does_not_scrape_prior_bot_prose(self):
        monitor = self.make_monitor()
        monitor.conversation = ConversationContext(max_history=20)
        monitor.intent_router = IntentRouter(monitor)
        created = []

        async def capture_reminder(message, payload, *, reference_time):
            created.append((payload, reference_time))
            return DispatchOutcome.success(mutated=True)

        monitor.handlers["reminders"].handle_reminder_create = capture_reminder
        own_offer = RecordingMessage("ignored")
        own_offer.guild = SimpleNamespace(id=999)
        own_offer.channel = SimpleNamespace(id=100)
        own_offer.author = SimpleNamespace(id=7, name="Current user")
        with capture_history_policy(HistoryPolicy.FULL):
            await monitor._send_response(
                own_offer,
                "Skal jeg legge inn en påminnelse om å kjøpe melk?",
            )

        other_channel_offer = RecordingMessage("ignored")
        other_channel_offer.guild = SimpleNamespace(id=999)
        other_channel_offer.channel = SimpleNamespace(id=200)
        other_channel_offer.author = SimpleNamespace(id=7, name="Current user")
        with capture_history_policy(HistoryPolicy.FULL):
            await monitor._send_response(
                other_channel_offer,
                "Skal jeg legge inn en påminnelse om å dele helsejournalen?",
            )

        other_user_offer = RecordingMessage("ignored")
        other_user_offer.guild = SimpleNamespace(id=999)
        other_user_offer.channel = SimpleNamespace(id=100)
        other_user_offer.author = SimpleNamespace(id=8, name="Other user")
        with capture_history_policy(HistoryPolicy.FULL):
            await monitor._send_response(
                other_user_offer,
                "Skal jeg legge inn en påminnelse om å sende lønnsslippen?",
            )

        followup = RecordingMessage("@inebotten minn meg på det i morgen")
        followup.guild = SimpleNamespace(id=999)
        followup.channel = SimpleNamespace(id=100)
        followup.author = SimpleNamespace(id=7, name="Current user")

        await monitor.handle_message(followup)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0]["text"], "det")
        self.assertNotIn("helsejournal", created[0][0]["text"].casefold())
        self.assertNotIn("lønnsslipp", created[0][0]["text"].casefold())
        self.assertIs(created[0][1], NOW)
        self.assertEqual(
            set(monitor.conversation.threads),
            {
                ConversationKey(999, 100, 7),
                ConversationKey(999, 200, 7),
                ConversationKey(999, 100, 8),
            },
        )

    async def test_real_conversation_dm_followup_does_not_scrape_prior_bot_prose(self):
        monitor = self.make_monitor()
        monitor.conversation = ConversationContext(max_history=20)
        monitor.intent_router = IntentRouter(monitor)
        created = []

        async def capture_reminder(message, payload, *, reference_time):
            created.append((payload, reference_time))
            return DispatchOutcome.success(mutated=True)

        monitor.handlers["reminders"].handle_reminder_create = capture_reminder
        own_offer = RecordingMessage("ignored")
        own_offer.guild = None
        own_offer.channel = SimpleNamespace(id=300)
        own_offer.author = SimpleNamespace(id=7, name="Current user")
        with capture_history_policy(HistoryPolicy.FULL):
            await monitor._send_response(
                own_offer,
                "Skal jeg legge inn en påminnelse om å kjøpe melk?",
            )

        other_dm_offer = RecordingMessage("ignored")
        other_dm_offer.guild = None
        other_dm_offer.channel = SimpleNamespace(id=301)
        other_dm_offer.author = SimpleNamespace(id=7, name="Current user")
        with capture_history_policy(HistoryPolicy.FULL):
            await monitor._send_response(
                other_dm_offer,
                "Skal jeg legge inn en påminnelse om å dele helsejournalen?",
            )

        followup = RecordingMessage("@inebotten minn meg på det i morgen")
        followup.guild = None
        followup.channel = SimpleNamespace(id=300)
        followup.author = SimpleNamespace(id=7, name="Current user")
        await monitor.handle_message(followup)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0]["text"], "det")
        self.assertNotIn("helsejournal", created[0][0]["text"].casefold())
        self.assertIs(created[0][1], NOW)
        self.assertEqual(
            set(monitor.conversation.threads),
            {
                ConversationKey(None, 300, 7),
                ConversationKey(None, 301, 7),
            },
        )

    async def test_untagged_contextual_followup_keeps_mention_gate(self):
        monitor = self.make_monitor()
        monitor.conversation = ConversationContext(max_history=20)
        monitor.intent_router = IntentRouter(monitor)
        created = []

        async def capture_reminder(message, payload, *, reference_time):
            created.append((payload, reference_time))
            return DispatchOutcome.success(mutated=True)

        monitor.handlers["reminders"].handle_reminder_create = capture_reminder
        offer = RecordingMessage("ignored")
        offer.guild = SimpleNamespace(id=999)
        offer.channel = SimpleNamespace(id=100)
        offer.author = SimpleNamespace(id=7, name="Current user")
        await monitor._send_response(
            offer,
            "Skal jeg legge inn en påminnelse om å kjøpe melk?",
        )

        followup = RecordingMessage("minn meg på det i morgen")
        followup.guild = SimpleNamespace(id=999)
        followup.channel = SimpleNamespace(id=100)
        followup.author = SimpleNamespace(id=7, name="Current user")
        await monitor.handle_message(followup)

        self.assertEqual(created, [])
        self.assertEqual(monitor.mention_count, 0)

    async def test_low_confidence_rejection_is_tracked(self):
        monitor = self.make_monitor()
        route = IntentResult(BotIntent.SEARCH, 0.0)

        self.assertFalse(monitor._passes_intent_threshold(route))
        self.assertEqual(monitor.intent_stats[BotIntent.SEARCH.value]["low_confidence"], 1)

    async def test_confirmation_required_fails_closed_before_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def destructive_handler(message):
            calls.append(message)

        monitor.handlers["calendar"].handle_delete = destructive_handler
        route = IntentResult(
            BotIntent.CALENDAR_DELETE,
            1.0,
            {"calendar_target": {"target": "1"}},
            requires_confirmation=True,
        )

        outcome = await monitor._handle_intent(
            RecordingMessage("@inebotten slett kalender 1"),
            route,
            reference_time=NOW,
        )

        self.assertEqual(calls, [])
        self.assertFalse(outcome.ok)
        self.assertFalse(outcome.mutated)
        self.assertEqual(outcome.error_code, "confirmation_required")
        self.assertIsNone(outcome.delivery_result)

    async def test_malformed_action_envelope_precedes_confidence_and_confirmation(self):
        for requires_confirmation in (False, True):
            with self.subTest(requires_confirmation=requires_confirmation):
                monitor = self.make_monitor()
                monitor._send_ai_response = AsyncMock()
                handler = AsyncMock(
                    return_value=DispatchOutcome.success(mutated=True)
                )
                monitor.handlers["reminders"].handle_reminder_create = handler
                route = IntentResult(
                    BotIntent.REMINDER_CREATE,
                    0.1,
                    {"reminder": {"action": "add", "text": ""}},
                    source=IntentSource.DETERMINISTIC,
                    requires_confirmation=requires_confirmation,
                )

                outcome = await monitor._handle_intent(
                    RecordingMessage("must not enter fallback"),
                    route,
                    reference_time=NOW,
                )

                self.assertEqual(
                    outcome.error_code,
                    (
                        "confirmation_required"
                        if requires_confirmation
                        else "invalid_payload"
                    ),
                )
                self.assertFalse(outcome.mutated)
                monitor._send_ai_response.assert_not_awaited()
                handler.assert_not_awaited()

    async def test_valid_low_confidence_action_is_gated_before_dispatch(self):
        monitor = self.make_monitor()
        handler = AsyncMock(return_value=DispatchOutcome.success(mutated=True))
        monitor.handlers["reminders"].handle_reminder_create = handler
        route = IntentResult(
            BotIntent.REMINDER_CREATE,
            0.1,
            {"reminder": {"action": "add", "text": "Ring legen"}},
            source=IntentSource.DETERMINISTIC,
        )

        self.assertFalse(monitor._passes_intent_threshold(route))
        handler.assert_not_awaited()

    def test_typed_inner_payload_validates_present_and_distinguishes_absence(self):
        monitor = self.make_monitor()
        valid = IntentResult(
            BotIntent.POLL_VOTE,
            1.0,
            {"vote": {"option": 2, "poll_id": "poll-1"}},
            source=IntentSource.DETERMINISTIC,
        )
        missing = IntentResult(
            BotIntent.POLL_VOTE,
            1.0,
            {},
            source=IntentSource.DETERMINISTIC,
        )
        invalid = IntentResult(
            BotIntent.POLL_VOTE,
            1.0,
            {"vote": {"option": 0}},
            source=IntentSource.DETERMINISTIC,
        )

        self.assertEqual(
            monitor._typed_inner_payload(valid),
            {"option": 2, "poll_id": "poll-1"},
        )
        self.assertIsNone(monitor._typed_inner_payload(missing))
        with self.assertRaises(PayloadValidationError):
            monitor._typed_inner_payload(invalid)

    async def test_migrated_families_receive_validated_inner_payload_and_return_outcome(self):
        delivered = MessageSendResult(DeliveryState.DELIVERED)
        cases = (
            (
                "reminder",
                BotIntent.REMINDER_CREATE,
                {"reminder": {"action": "add", "text": "  Ring legen  "}},
                {"action": "add", "text": "Ring legen"},
                "reminders",
                "handle_reminder_create",
                True,
            ),
            (
                "poll",
                BotIntent.POLL_VOTE,
                {"vote": {"option": 2, "poll_id": " poll-1 "}},
                {"option": 2, "poll_id": "poll-1"},
                "polls",
                "handle_vote",
                True,
            ),
            (
                "watchlist",
                BotIntent.WATCHLIST,
                {"watchlist": {"action": "add", "title": "  The Bear  ", "lang": "no"}},
                {"action": "add", "title": "The Bear", "lang": "no"},
                "watchlist",
                "handle_watchlist",
                True,
            ),
            (
                "quote",
                BotIntent.QUOTE_EDIT,
                {"quote": {"action": "edit", "index": 1, "author": "  Kari  "}},
                {"action": "edit", "index": 1, "author": "Kari"},
                "quotes",
                "handle_quote_edit",
                False,
            ),
        )

        for (
            label,
            intent,
            outer,
            expected_inner,
            handler_family,
            handler_name,
            receives_reference,
        ) in cases:
            with self.subTest(family=label):
                monitor = self.make_monitor()
                outcome = DispatchOutcome.success(mutated=True).with_delivery(delivered)
                handler = AsyncMock(return_value=outcome)
                setattr(monitor.handlers[handler_family], handler_name, handler)
                message = RecordingMessage("CONTRADICTORY RAW CONTENT")
                route = IntentResult(
                    intent,
                    1.0,
                    outer,
                    source=IntentSource.DETERMINISTIC,
                )

                actual = await monitor._handle_intent(
                    message,
                    route,
                    reference_time=NOW,
                )

                self.assertIs(actual, outcome)
                if receives_reference:
                    handler.assert_awaited_once_with(
                        message,
                        expected_inner,
                        reference_time=NOW,
                    )
                else:
                    handler.assert_awaited_once_with(message, expected_inner)

    async def test_every_action_envelope_dispatches_only_its_validated_inner_value(self):
        cases = (
            (BotIntent.CALENDAR_ITEM, "calendar_item", {"title": "Møte", "date": "16.07.2026"}, "calendar", "handle_calendar_item", True),
            (BotIntent.CALENDAR_EDIT, "calendar_edit", {"target": "Møte", "changes": {"title": "Nytt møte"}}, "calendar", "handle_edit", True),
            (BotIntent.CALENDAR_DELETE, "calendar_target", {"number": 1}, "calendar", "handle_delete", True),
            (BotIntent.CALENDAR_COMPLETE, "calendar_target", {"number": 1}, "calendar", "handle_complete", True),
            (BotIntent.CALENDAR_CLEAR, "calendar_target", {"all": True}, "calendar", "handle_clear", True),
            (BotIntent.REMINDER_CREATE, "reminder", {"action": "add", "text": "Ring legen"}, "reminders", "handle_reminder_create", True),
            (BotIntent.REMINDER_LIST, "reminder", {"action": "list"}, "reminders", "handle_reminder_list", True),
            (BotIntent.REMINDER_SEARCH, "reminder", {"action": "search", "query": "legen"}, "reminders", "handle_reminder_search", True),
            (BotIntent.REMINDER_COMPLETE, "reminder", {"action": "complete", "number": 1}, "reminders", "handle_reminder_complete", True),
            (BotIntent.REMINDER_EDIT, "reminder", {"action": "edit", "number": 1, "changes": {"text": "Ring tannlegen"}}, "reminders", "handle_reminder_edit", True),
            (BotIntent.REMINDER_DELETE, "reminder", {"action": "delete", "number": 1}, "reminders", "handle_reminder_delete", True),
            (BotIntent.POLL_CREATE, "poll", {"question": "Velg?", "options": ["A", "B"]}, "polls", "handle_poll", True),
            (BotIntent.POLL_VOTE, "vote", {"option": 1, "poll_id": "poll-1"}, "polls", "handle_vote", True),
            (BotIntent.POLL_EDIT, "poll_edit", {"target": 1, "question": "Nytt?"}, "polls", "handle_poll_edit", True),
            (BotIntent.POLL_DELETE, "poll_delete", {"target": 1}, "polls", "handle_poll_delete", True),
            (BotIntent.POLL_CLOSE, "poll_close", {"target": "siste"}, "polls", "handle_poll_close", True),
            (BotIntent.BIRTHDAY_CREATE, "birthday", {"action": "add", "user_id": 7, "display_name": "Kari", "day": 15, "month": 7}, "birthdays", "handle_birthday_create", True),
            (BotIntent.BIRTHDAY_LIST, "birthday", {"action": "list", "scope": "upcoming"}, "birthdays", "handle_birthday_list", True),
            (BotIntent.BIRTHDAY_EDIT, "birthday", {"action": "edit", "user_id": 7, "day": 16, "month": 7}, "birthdays", "handle_birthday_edit", True),
            (BotIntent.WATCHLIST, "watchlist", {"action": "add", "title": "Arrival", "lang": "no"}, "watchlist", "handle_watchlist", True),
            (BotIntent.QUOTE, "quote", {"action": "save", "text": "Hei", "lang": "no"}, "fun", "handle_quote_command", False),
            (BotIntent.QUOTE_LIST, "quote", {"action": "list", "lang": "no"}, "quotes", "handle_quote_list", False),
            (BotIntent.QUOTE_EDIT, "quote", {"action": "edit", "index": 1, "text": "Ny"}, "quotes", "handle_quote_edit", False),
            (BotIntent.QUOTE_DELETE, "quote", {"action": "delete", "index": 1}, "quotes", "handle_quote_delete", False),
        )

        self.assertEqual(len(cases), 24)
        for intent, envelope, inner, family, method, receives_reference in cases:
            with self.subTest(intent=intent.value):
                monitor = self.make_monitor()
                expected = DispatchOutcome.success(mutated=True)
                handler = AsyncMock(return_value=expected)
                setattr(monitor.handlers[family], method, handler)
                message = RecordingMessage("CONTRADICTORY RAW CONTENT")
                route = IntentResult(
                    intent,
                    1.0,
                    {envelope: inner},
                    source=IntentSource.DETERMINISTIC,
                )

                actual = await monitor._handle_intent(
                    message,
                    route,
                    reference_time=NOW,
                )

                self.assertIs(actual, expected)
                normalized = monitor._typed_inner_payload(route)
                if receives_reference:
                    handler.assert_awaited_once_with(
                        message,
                        normalized,
                        reference_time=NOW,
                    )
                else:
                    handler.assert_awaited_once_with(message, normalized)

    async def test_absent_family_envelopes_pass_none_to_one_release_handler(self):
        self.assertEqual(len(ACTION_HANDLER_CASES), 24)
        for intent, _envelope, family, method, receives_reference in ACTION_HANDLER_CASES:
            with self.subTest(intent=intent.value):
                monitor = self.make_monitor()
                outcome = DispatchOutcome.success(mutated=False)
                handler = AsyncMock(return_value=outcome)
                setattr(monitor.handlers[family], method, handler)
                message = RecordingMessage("legacy-compatible raw content")
                route = IntentResult(
                    intent,
                    1.0,
                    {},
                    source=IntentSource.DETERMINISTIC,
                )

                actual = await monitor._handle_intent(
                    message,
                    route,
                    reference_time=NOW,
                )

                self.assertIs(actual, outcome)
                if receives_reference:
                    handler.assert_awaited_once_with(
                        message,
                        None,
                        reference_time=NOW,
                    )
                else:
                    handler.assert_awaited_once_with(message, None)

    async def test_malformed_present_family_envelopes_fail_before_any_handler(self):
        self.assertEqual(len(ACTION_HANDLER_CASES), 24)
        for intent, envelope, family, method, _receives_reference in ACTION_HANDLER_CASES:
            with self.subTest(intent=intent.value):
                monitor = self.make_monitor()
                handler = AsyncMock(
                    return_value=DispatchOutcome.success(mutated=True)
                )
                setattr(monitor.handlers[family], method, handler)
                route = IntentResult(
                    intent,
                    1.0,
                    {envelope: {}},
                    source=IntentSource.DETERMINISTIC,
                )

                outcome = await monitor._handle_intent(
                    RecordingMessage("must not reach a handler"),
                    route,
                    reference_time=NOW,
                )

                self.assertFalse(outcome.ok)
                self.assertFalse(outcome.mutated)
                self.assertFalse(outcome.retryable)
                self.assertEqual(outcome.error_code, "invalid_payload")
                handler.assert_not_awaited()

    async def test_typed_watchlist_handler_delivery_is_not_sent_twice(self):
        monitor = self.make_monitor()
        calls = []

        async def typed_handler(message, payload, *, reference_time):
            calls.append((payload, reference_time))
            delivery = await monitor._send_response_result(message, "ett svar")
            return DispatchOutcome.success(mutated=True).with_delivery(delivery)

        monitor.handlers["watchlist"].handle_watchlist = typed_handler
        monitor.handlers["watchlist"].handle_watchlist_remove = typed_handler
        message = RecordingMessage("contradictory raw content")
        route = IntentResult(
            BotIntent.WATCHLIST,
            1.0,
            {"watchlist": {"action": "remove", "index": 1, "lang": "no"}},
            source=IntentSource.DETERMINISTIC,
        )

        outcome = await monitor._handle_intent(
            message,
            route,
            reference_time=NOW,
        )

        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.mutated)
        self.assertTrue(outcome.response_sent)
        self.assertEqual(calls, [({"action": "remove", "index": 1, "lang": "no"}, NOW)])
        self.assertEqual(message.replies, ["ett svar"])
        self.assertEqual(monitor.response_count, 1)

    async def test_set_location_unknown_city_fails_without_memory_calls(self):
        monitor = self.make_monitor()
        monitor.user_memory = SimpleNamespace(
            snapshot_user=AsyncMock(side_effect=AssertionError("memory read")),
            get_or_create_user_result=AsyncMock(
                side_effect=AssertionError("memory create")
            ),
            set_location_result=AsyncMock(
                side_effect=AssertionError("memory mutation")
            ),
        )
        message = RecordingMessage("contradictory raw content")

        outcome = await monitor._handle_set_location(
            message,
            "Atlantis",
            reference_time=NOW,
        )

        self.assertFalse(outcome.ok)
        self.assertFalse(outcome.mutated)
        self.assertFalse(outcome.retryable)
        self.assertEqual(outcome.error_code, "unsupported_city")
        self.assertTrue(outcome.response_sent)
        self.assertEqual(len(message.replies), 1)
        self.assertEqual(monitor.response_count, 1)
        monitor.user_memory.snapshot_user.assert_not_called()
        monitor.user_memory.get_or_create_user_result.assert_not_awaited()
        monitor.user_memory.set_location_result.assert_not_awaited()

    async def test_set_location_returns_exact_changed_and_noop_mutation_truth(self):
        for current_city, changed in (("Oslo", True), ("Trondheim", False)):
            with self.subTest(changed=changed):
                monitor = self.make_monitor()
                calls = []

                class LocationMemory:
                    def snapshot_user(self, user_id):
                        calls.append(("snapshot", user_id))
                        return {"location": current_city}

                    async def get_or_create_user_result(
                        self,
                        user_id,
                        username,
                        *,
                        reference_time,
                    ):
                        calls.append(
                            (
                                "get_or_create",
                                user_id,
                                username,
                                reference_time,
                            )
                        )
                        return {"location": current_city}

                    async def set_location_result(self, user_id, city):
                        calls.append(("set_location", user_id, city))
                        return changed

                monitor.user_memory = LocationMemory()
                message = RecordingMessage("contradictory raw content")
                route = IntentResult(
                    BotIntent.SET_LOCATION,
                    1.0,
                    {"city": "  trondheim  "},
                    source=IntentSource.DETERMINISTIC,
                )

                outcome = await monitor._handle_intent(
                    message,
                    route,
                    reference_time=NOW,
                )

                self.assertTrue(outcome.ok)
                self.assertIs(outcome.mutated, changed)
                self.assertTrue(outcome.response_sent)
                self.assertEqual(
                    calls,
                    [
                        ("snapshot", 7),
                        ("get_or_create", 7, "Tester", NOW),
                        ("set_location", 7, "Trondheim"),
                    ],
                )
                self.assertEqual(len(message.replies), 1)
                self.assertEqual(monitor.response_count, 1)

    async def test_set_location_new_user_counts_lazy_creation_as_mutation(self):
        monitor = self.make_monitor()
        calls = []

        class LocationMemory:
            def snapshot_user(self, user_id):
                calls.append(("snapshot", user_id))
                return None

            async def get_or_create_user_result(
                self,
                user_id,
                username,
                *,
                reference_time,
            ):
                calls.append(("create", user_id, username, reference_time))
                return {"location": None}

            async def set_location_result(self, user_id, city):
                calls.append(("set", user_id, city))
                return True

        monitor.user_memory = LocationMemory()
        outcome = await monitor._handle_set_location(
            RecordingMessage("contradictory raw content"),
            "Trondheim",
            reference_time=NOW,
        )

        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.mutated)
        self.assertEqual(
            calls,
            [
                ("snapshot", 7),
                ("create", 7, "Tester", NOW),
                ("set", 7, "Trondheim"),
            ],
        )

    async def test_set_location_second_write_failure_retains_first_commit_truth(self):
        monitor = self.make_monitor()

        class LocationMemory:
            def snapshot_user(self, _user_id):
                return None

            async def get_or_create_user_result(self, *_args, **_kwargs):
                return {"location": None}

            async def set_location_result(self, _user_id, _city):
                raise ManagerMutationError(
                    "storage_write_failed",
                    mutated=False,
                )

        monitor.user_memory = LocationMemory()
        outcome = await monitor._handle_set_location(
            RecordingMessage("contradictory raw content"),
            "Trondheim",
            reference_time=NOW,
        )

        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.mutated)
        self.assertFalse(outcome.retryable)
        self.assertEqual(outcome.error_code, "storage_write_failed")
        self.assertTrue(outcome.response_sent)

    async def test_chat_survives_local_user_memory_write_failure(self):
        monitor = self.make_monitor()
        monitor.user_memory.update_last_interaction_result = AsyncMock(
            side_effect=ManagerMutationError(
                "storage_write_failed",
                mutated=False,
            )
        )
        message = RecordingMessage("@inebotten hvordan går det?")

        await monitor.handle_message(message)

        self.assertEqual(len(message.replies), 1)
        self.assertEqual(monitor.response_count, 1)
        monitor.user_memory.update_last_interaction_result.assert_awaited_once_with(
            7,
            reference_time=NOW,
            topic=None,
            username="Tester",
        )
        self.assertEqual(
            monitor.conversation.summary_channels,
            [ConversationKey(None, 100, 7)],
        )

    async def test_setup_initializes_gcal_before_frozen_background_sync(self):
        monitor = MessageMonitor.__new__(MessageMonitor)
        calls = []
        tracked = []

        class Calendar:
            async def setup(self):
                calls.append("calendar_setup")

            async def ensure_gcal_configured(self):
                calls.append("gcal_initialize")
                return ExternalMutationResult(
                    True,
                    ExternalCommitState.UNCHANGED,
                    value=True,
                )

            def sync_from_gcal_result(self, *, reference_time):
                calls.append(("sync_created", reference_time))

                async def run():
                    calls.append(("sync_ran", reference_time))

                return run()

        class UserMemory:
            async def setup(self):
                calls.append("memory_setup")

        async def console_loop():
            return None

        def track(coro, name):
            tracked.append((name, coro))
            return coro

        monitor.calendar = Calendar()
        monitor.user_memory = UserMemory()
        monitor.nlu_metrics = NLUMetrics()
        monitor.console_store = SimpleNamespace(load_nlu_stats=lambda: {})
        monitor.reminder_clock = SimpleNamespace(now=Mock(return_value=NOW))
        monitor._track_background_task = track
        monitor._console_persistence_loop = console_loop
        monitor._set_task_health = lambda *args, **kwargs: None

        await monitor.setup()

        self.assertEqual(
            calls,
            [
                "calendar_setup",
                "memory_setup",
                "gcal_initialize",
                ("sync_created", NOW),
            ],
        )
        self.assertEqual(
            [name for name, _ in tracked],
            ["initial-gcal-sync", "console-persistence"],
        )
        monitor.reminder_clock.now.assert_called_once_with()
        await tracked[0][1]
        await tracked[1][1]
        self.assertEqual(calls[-1], ("sync_ran", NOW))

    async def test_legacy_read_adapter_retains_unknown_delivery(self):
        monitor = self.make_monitor()
        monitor.discord_sender = SimpleNamespace(
            send_result=AsyncMock(
                return_value=MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "timeout",
                )
            )
        )

        async def legacy_read():
            await monitor._send_response(
                RecordingMessage("@inebotten les"),
                "Svar",
            )

        outcome = await monitor._invoke_legacy_read(legacy_read)

        self.assertTrue(outcome.ok)
        self.assertFalse(outcome.response_sent)
        self.assertFalse(outcome.retryable)
        self.assertIs(outcome.delivery_result.state, DeliveryState.UNKNOWN)

    async def test_delivered_reply_survives_conversation_recording_failure(self):
        monitor = self.make_monitor()
        monitor.conversation.add_turn = Mock(
            side_effect=RuntimeError("private storage detail")
        )
        message = RecordingMessage("@inebotten hei")

        with capture_history_policy(HistoryPolicy.FULL):
            result = await monitor._send_response_result(
                message,
                "Hei tilbake",
            )

        self.assertIs(result.state, DeliveryState.DELIVERED)
        self.assertEqual(message.replies, ["Hei tilbake"])
        self.assertEqual(monitor.response_count, 1)
        monitor.conversation.add_turn.assert_called_once()

    async def test_legacy_handler_exception_returns_bounded_outcome(self):
        monitor = self.make_monitor()

        async def boom(message):
            raise RuntimeError("boom")

        monitor.handlers["help"].handle_help = boom
        message = RecordingMessage("@inebotten hjelp")
        route = IntentResult(
            BotIntent.HELP,
            1.0,
            {},
            source=IntentSource.DETERMINISTIC,
        )

        outcome = await monitor._handle_intent(
            message,
            route,
            reference_time=NOW,
        )

        self.assertFalse(outcome.ok)
        self.assertFalse(outcome.mutated)
        self.assertFalse(outcome.retryable)
        self.assertEqual(outcome.error_code, "handler_exception")
        self.assertIsNone(outcome.delivery_result)

    async def test_status_response_includes_intent_stats(self):
        monitor = self.make_monitor()
        monitor.intent_stats["help"]["count"] = 3
        monitor.intent_stats["help"]["low_confidence"] = 1
        monitor.intent_stats["help"]["errors"] = 2

        captured = {}

        async def fake_send_sequence(message, response_text):
            captured["text"] = response_text
            return MessageSendResult(DeliveryState.DELIVERED)

        monitor._send_text_sequence_result = fake_send_sequence

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
        canary = "BACKGROUND_SECRET_CANARY"

        async def boom():
            raise RuntimeError(canary)

        output = io.StringIO()
        with redirect_stdout(output):
            monitor._track_background_task(boom(), "boom-task")
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        task_health = monitor.get_task_health()["boom-task"]
        self.assertEqual(task_health["state"], "failed")
        self.assertEqual(
            task_health["last_error"],
            "background_task_failed",
        )
        self.assertEqual(task_health["exception_type"], "RuntimeError")
        self.assertNotIn(canary, output.getvalue())
        self.assertNotIn(canary, repr(task_health))

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

        async def fake_ai_response(
            message,
            *,
            utterance,
            routing_context,
            routed_intent,
            reference_time,
            semantic_action_allowed,
            forced_search_info=None,
        ):
            captured["forced_search_info"] = forced_search_info
            captured["reference_time"] = reference_time
            return RouteProcessOutcome(
                DispatchOutcome.success(),
                routed_intent,
                "executed",
            )

        monitor._send_ai_response = fake_ai_response
        search_payload = {"query": "dagens nyheter", "type": "web"}
        route = IntentResult(
            BotIntent.SEARCH,
            0.9,
            {"search": search_payload},
        )
        message = RecordingMessage("@inebotten søk på nett dagens nyheter")
        await monitor._process_route(
            message,
            utterance=normalize_utterance("søk på nett dagens nyheter"),
            routing_context=routing_context_from_message(
                message,
                bot_user_id=42,
            ),
            route=route,
            reference_time=NOW,
        )

        self.assertEqual(captured["forced_search_info"], search_payload)
        self.assertIs(captured["reference_time"], NOW)

    async def test_dashboard_intent_uses_explicit_dashboard_handler(self):
        monitor = self.make_monitor()
        captured = {}

        async def fake_dashboard(message, *, reference_time):
            captured["message"] = message
            captured["reference_time"] = reference_time

        monitor._send_dashboard_response = fake_dashboard
        route = IntentResult(BotIntent.DASHBOARD, 0.9)
        message = RecordingMessage("@inebotten dashboard")

        await monitor._handle_intent(message, route, reference_time=NOW)

        self.assertIs(captured["message"], message)
        self.assertIs(captured["reference_time"], NOW)

    async def test_ai_fallback_no_longer_crashes_on_chat(self):
        monitor = self.make_monitor()
        message = RecordingMessage("@inebotten hva skjer?")

        await monitor.handle_message(message)

        self.assertEqual(monitor.mention_count, 1)
        self.assertEqual(len(message.replies), 1)
        self.assertEqual(monitor.response_count, 1)
        self.assertEqual(monitor.rate_limiter.can_send_calls, 1)
        self.assertEqual(monitor.rate_limiter.wait_calls, 1)

    async def test_dashboard_fallback_has_defined_context(self):
        monitor = self.make_monitor(wants_dashboard=True)

        async def fake_dashboard(
            guild_id,
            city_name=None,
            show_navnedag=False,
            user_id=None,
            *,
            reference_time=None,
        ):
            return f"dashboard:{guild_id}:{show_navnedag}"

        monitor._generate_dashboard = fake_dashboard
        message = RecordingMessage("@inebotten vis dashboard")

        await monitor.handle_message(message)

        self.assertEqual(message.replies, ["dashboard:100:False"])

    async def test_poll_list_routes_to_handler(self):
        monitor = self.make_monitor(active_polls=True)

        calls = []

        async def fake_handle_poll_list(message, *, reference_time):
            calls.append((message, reference_time))
            return DispatchOutcome.success(mutated=False)

        monitor.handlers["polls"].handle_poll_list = fake_handle_poll_list
        message = RecordingMessage("@inebotten polls")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0].content, "polls")
        self.assertIs(calls[0][1], NOW)
        self.assertEqual(monitor.intent_stats[BotIntent.POLL_LIST.value]["count"], 1)

    async def test_active_poll_vote_routes_before_ai(self):
        monitor = self.make_monitor(active_polls=True)
        message = RecordingMessage("@inebotten 1")

        await monitor.handle_message(message)

        self.assertEqual(len(monitor.recording_polls.votes), 1)
        self.assertEqual(
            monitor.recording_polls.votes[0][1],
            {"option": 1, "poll_id": "poll1"},
        )
        self.assertIs(monitor.recording_polls.votes[0][2], NOW)
        self.assertEqual(message.replies, ["Handlingen ble utført."])

    async def test_incomplete_reminder_edit_falls_back_without_handler(self):
        monitor = self.make_monitor(active_reminders=True)
        calls = []

        async def fake_handle_reminder_edit(message, payload, *, reference_time):
            calls.append((message.content, payload["watchlist"] if "watchlist" in payload else payload))
            return DispatchOutcome.success(mutated=True)

        monitor.handlers["reminders"].handle_reminder_edit = fake_handle_reminder_edit
        message = RecordingMessage("@inebotten endre påminnelse")

        await monitor.handle_message(message)

        self.assertEqual(calls, [])
        self.assertEqual(monitor.intent_stats[BotIntent.AI_CHAT.value]["count"], 1)
        self.assertEqual(len(message.replies), 1)

    async def test_complete_reminder_edit_routes_to_handler(self):
        monitor = self.make_monitor(active_reminders=True)
        calls = []

        async def fake_handle_reminder_edit(message, payload, *, reference_time):
            calls.append((message.content, payload, reference_time))
            return DispatchOutcome.success(mutated=True)

        monitor.handlers["reminders"].handle_reminder_edit = fake_handle_reminder_edit
        message = RecordingMessage(
            "@inebotten endre påminnelse 1 tekst: Ring legen"
        )

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][1],
            {
                "action": "edit",
                "reminder_id": "rem1",
                "changes": {"text": "Ring legen"},
            },
        )
        self.assertIs(calls[0][2], NOW)
        self.assertEqual(monitor.intent_stats[BotIntent.REMINDER_EDIT.value]["count"], 1)

    async def test_calendar_search_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_calendar_search(message, payload, *, reference_time):
            calls.append((message.content, payload, reference_time))
            return DispatchOutcome.success(mutated=False)

        monitor.handlers["calendar"].handle_search = fake_handle_calendar_search
        message = RecordingMessage("@inebotten søk kalender møte")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["query"], "møte")
        self.assertIs(calls[0][2], NOW)
        self.assertEqual(monitor.intent_stats[BotIntent.CALENDAR_SEARCH.value]["count"], 1)

    async def test_reminder_create_list_and_complete_route_to_handlers(self):
        monitor = self.make_monitor(active_reminders=True)
        calls = []

        async def fake_create(message, payload, *, reference_time):
            calls.append(("create", payload, reference_time))
            return DispatchOutcome.success(mutated=True)

        async def fake_list(message, payload, *, reference_time):
            calls.append(("list", payload, reference_time))
            return DispatchOutcome.success(mutated=False)

        async def fake_complete(message, payload, *, reference_time):
            calls.append(("complete", payload, reference_time))
            return DispatchOutcome.success(mutated=True)

        monitor.handlers["reminders"].handle_reminder_create = fake_create
        monitor.handlers["reminders"].handle_reminder_list = fake_list
        monitor.handlers["reminders"].handle_reminder_complete = fake_complete

        await monitor.handle_message(RecordingMessage("@inebotten påminnelse Ring lege om 2 timer"))
        await monitor.handle_message(RecordingMessage("@inebotten påminnelser"))
        await monitor.handle_message(RecordingMessage("@inebotten ferdig 1"))

        self.assertEqual([call[0] for call in calls], ["create", "list", "complete"])
        self.assertEqual(calls[0][1]["action"], "add")
        self.assertEqual(calls[1][1], {"action": "list"})
        self.assertEqual(
            calls[2][1],
            {"action": "complete", "reminder_id": "rem1"},
        )
        self.assertTrue(all(call[2] is NOW for call in calls))

    async def test_bare_calendar_title_delete_fails_closed_until_confirmation(self):
        monitor = self.make_monitor()
        row = {
            "id": "calendar-1",
            "title": "Send inn meldekort (Uke 25 - 26)",
            "date": "29.06.2026",
            "time": "12:00",
            "type": "event",
            "description": "",
            "completed": False,
            "recurrence": None,
            "recurrence_sequence": 0,
        }
        monitor.calendar = SimpleNamespace(
            get_upcoming=lambda guild_id, days=365, reference_time=None: [
                row
            ],
            snapshot_pending_items=lambda *, reference_time: (dict(row),),
            snapshot_all_item_ids=lambda: ("calendar-1",),
        )
        monitor.intent_router = IntentRouter(monitor)
        calls = []

        async def fake_handle_calendar_delete(message):
            calls.append(message.content)

        monitor.handlers["calendar"].handle_delete = fake_handle_calendar_delete
        message = RecordingMessage("@inebotten slett meldekort")

        await monitor.handle_message(message)

        self.assertEqual(calls, [])
        self.assertEqual(len(message.replies), 1)
        self.assertIn(
            "Skal jeg slette kalenderoppføringen?",
            message.replies[0],
        )
        self.assertIn("@inebotten ja", message.replies[0])
        self.assertIn("@inebotten nei", message.replies[0])
        self.assertEqual(monitor.pending_actions.counts()["ready"], 1)
        self.assertEqual(monitor.intent_stats[BotIntent.CALENDAR_DELETE.value]["count"], 1)

    async def test_reminder_search_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_reminder_search(message, payload, *, reference_time):
            calls.append((message.content, payload, reference_time))
            return DispatchOutcome.success(mutated=False)

        monitor.handlers["reminders"].handle_reminder_search = fake_handle_reminder_search
        message = RecordingMessage("@inebotten søk påminnelse lege")

        await monitor.handle_message(message)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["query"], "lege")
        self.assertIs(calls[0][2], NOW)
        self.assertEqual(monitor.intent_stats[BotIntent.REMINDER_SEARCH.value]["count"], 1)

    async def test_quote_list_routes_to_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_quote_list(message, payload):
            calls.append((message.content, payload))
            return DispatchOutcome.success(mutated=False)

        monitor.handlers["quotes"].handle_quote_list = fake_handle_quote_list
        message = RecordingMessage("@inebotten liste sitater")

        await monitor.handle_message(message)

        self.assertEqual(calls, [("liste sitater", {"action": "list", "lang": "no"})])
        self.assertEqual(monitor.intent_stats[BotIntent.QUOTE_LIST.value]["count"], 1)

    async def test_birthday_edit_without_stable_identity_clarifies(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_birthday_edit(message, payload):
            calls.append((message.content, payload))

        monitor.handlers["birthdays"].handle_birthday_edit = fake_handle_birthday_edit
        message = RecordingMessage("@inebotten endre bursdag")

        await monitor.handle_message(message)

        self.assertEqual(calls, [])
        self.assertEqual(monitor.intent_stats[BotIntent.CLARIFY.value]["count"], 1)
        self.assertEqual(len(message.replies), 1)

    async def test_incomplete_watchlist_remove_falls_back_without_handler(self):
        monitor = self.make_monitor()
        calls = []

        async def fake_handle_watchlist_remove(message, payload):
            calls.append((message.content, payload))

        monitor.handlers["watchlist"].handle_watchlist_remove = fake_handle_watchlist_remove
        message = RecordingMessage("@inebotten fjern watchlist")

        await monitor.handle_message(message)

        self.assertEqual(calls, [])
        self.assertEqual(monitor.intent_stats[BotIntent.AI_CHAT.value]["count"], 1)
        self.assertEqual(len(message.replies), 1)

    async def test_watchlist_remove_fails_closed_until_confirmation(self):
        monitor = self.make_monitor()

        async def fake_handle_watchlist_remove(message, payload):
            return "✅ Fjernet Movie A"

        monitor.handlers["watchlist"].handle_watchlist_remove = fake_handle_watchlist_remove
        monitor.watchlist.snapshot_pending_items = lambda scope_id: (
            {
                "title": "Movie A",
                "type": "movie",
                "genre": "drama",
                "comment": "",
            },
        )
        message = RecordingMessage("@inebotten fjern watchlist 1")

        await monitor.handle_message(message)

        self.assertEqual(len(message.replies), 1)
        self.assertIn(
            "Skal jeg fjerne elementet fra se-listen?",
            message.replies[0],
        )
        self.assertNotIn("**Type:** fjern", message.replies[0])
        self.assertEqual(monitor.pending_actions.counts()["ready"], 1)
        self.assertEqual(monitor.response_count, 1)


if __name__ == "__main__":
    unittest.main()
