#!/usr/bin/env python3
"""
Message Monitor for Discord Selfbot
Polls DMs and detects @inebotten mentions using discord.py
"""

import asyncio
import inspect
import os
import re
import signal
import subprocess
import sys
from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import datetime, timedelta

import discord

from cal_system.reminder_checker import ReminderChecker
from cal_system.reminder_clock import SystemReminderClock
from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    ExternalCommitState,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
    MessageSendResult,
)
from core.intent_router import BotIntent, IntentRouter
from core.intent_payloads import (
    ENVELOPE_KEYS,
    PayloadValidationError,
    validate_intent_payload,
)
from core.intent_thresholds import CONFIDENCE_THRESHOLDS
from core.intent_keywords import (
    CALENDAR_KEYWORDS,
    COMPLETE_KEYWORDS,
    DELETE_KEYWORDS,
    EDIT_KEYWORDS,
    HELP_KEYWORDS,
    LIST_KEYWORDS,
    STATUS_KEYWORDS,
)
from core.message_context import routing_context_from_message
from core.mutation_coordinator import MEMORY_STORE_SCOPE, MutationCoordinator
from core.send_receipt import (
    DiscordSendCoordinator,
    _settle_owned_send,
    capture_send_receipt,
)
from web_console.server import ConsoleServer


COMMAND_REGISTRY = [
    {"name": "help", "aliases": HELP_KEYWORDS, "priority": 10, "scope": "any"},
    {"name": "status", "aliases": STATUS_KEYWORDS, "priority": 20, "scope": "any"},
    {
        "name": "calendar",
        "aliases": CALENDAR_KEYWORDS + DELETE_KEYWORDS + COMPLETE_KEYWORDS + EDIT_KEYWORDS,
        "priority": 30,
        "scope": "any",
    },
    {
        "name": "polls",
        "aliases": ["poll", "avstemning", "vote", "stemme"],
        "priority": 40,
        "scope": "any",
    },
    {
        "name": "watchlist",
        "aliases": ["watchlist", "filmforslag", "hva skal vi se"],
        "priority": 50,
        "scope": "any",
    },
    {
        "name": "memory",
        "aliases": ["vis minnet mitt", "eksporter minnet mitt", "slett minnet mitt"],
        "priority": 60,
        "scope": "any",
    },
    {"name": "ai_chat", "aliases": [], "priority": 1000, "scope": "any"},
]


_COUNTER_STAT_KEYS = ("count", "low_confidence", "errors")
_NO_TYPED_ENVELOPE = object()


def _counter_stats_delta(current, previous):
    """Return positive per-key counter deltas for nested intent stats."""
    delta = {}
    previous = previous or {}
    for name, stats in current.items():
        if not isinstance(stats, dict):
            continue
        previous_stats = previous.get(name, {}) if isinstance(previous, dict) else {}
        entry = {}
        for key in _COUNTER_STAT_KEYS:
            value = int(stats.get(key, 0) or 0)
            old_value = int(previous_stats.get(key, 0) or 0) if isinstance(previous_stats, dict) else 0
            change = value - old_value
            if change > 0:
                entry[key] = change
            else:
                entry[key] = 0
        if any(entry.values()):
            delta[str(name)] = entry
    return delta


def _flat_counter_delta(current, previous):
    """Return positive deltas for flat cumulative counters."""
    delta = {}
    previous = previous or {}
    for name, value in current.items():
        old_value = previous.get(name, 0) if isinstance(previous, dict) else 0
        change = int(value or 0) - int(old_value or 0)
        if change > 0:
            delta[str(name)] = change
    return delta


def _copy_counter_stats(stats):
    copied = {}
    for name, values in stats.items():
        if not isinstance(values, dict):
            continue
        copied[str(name)] = {key: int(values.get(key, 0) or 0) for key in _COUNTER_STAT_KEYS}
    return copied


class AuthorizedMessage:
    """
    Delegates to a Discord message while exposing content that has passed the
    mention gate and had only Inebotten's own mention removed.
    """

    def __init__(self, message, authorized_content):
        self._message = message
        self.raw_content = message.content
        self.authorized_content = authorized_content

    @property
    def content(self):
        return self.authorized_content

    def __getattr__(self, name):
        return getattr(self._message, name)


class MessageMonitor:
    """
    Monitors Discord messages for mentions of the bot
    Triggers responses when @inebotten is mentioned
    """

    def __init__(
        self,
        client,
        hermes_connector,
        rate_limiter,
        response_generator,
        bot_name="inebotten",
        *,
        reminder_clock=None,
        reminder_manager=None,
        reminder_checker_factory=ReminderChecker,
    ):
        self.client = client
        self.bot = client
        self.hermes = hermes_connector
        self.rate_limiter = rate_limiter
        self.response_gen = response_generator
        self.bot_name = bot_name
        self.bot_mention = f"@{bot_name}"
        injected_coordinator = getattr(
            reminder_manager,
            "mutation_coordinator",
            None,
        )
        self.mutation_coordinator = injected_coordinator or MutationCoordinator()
        injected_clock = getattr(reminder_manager, "clock", None)
        self.reminder_clock = (
            reminder_clock or injected_clock or SystemReminderClock()
        )
        self.discord_sender = DiscordSendCoordinator(self.rate_limiter)

        # Initialize unified calendar manager
        from cal_system.calendar_manager import CalendarManager
        from cal_system.natural_language_parser import NaturalLanguageParser
        from cal_system.google_calendar_manager import GoogleCalendarManager

        # Construction is deliberately offline.  The same injected manager is
        # initialized during ``setup`` and remains available for later auth.
        gcal = GoogleCalendarManager(
            mutation_coordinator=self.mutation_coordinator,
        )

        self.calendar = CalendarManager(
            gcal_manager=gcal,
            owner_email=getattr(self.client.config, 'DISCORD_EMAIL', None),
            owner_name=getattr(self.client.config, 'CALENDAR_OWNER_NAME', 'ᚱᛊᛊᚦ'),
            clock=self.reminder_clock,
            mutation_coordinator=self.mutation_coordinator,
        )
        self.nlp_parser = NaturalLanguageParser()

        from cal_system.reminder_manager import ReminderManager
        if reminder_manager is None:
            self.reminders = ReminderManager(
                clock=self.reminder_clock,
                mutation_coordinator=self.mutation_coordinator,
            )
        else:
            self.reminders = reminder_manager
            self.reminders.clock = self.reminder_clock
            self.reminders.mutation_coordinator = self.mutation_coordinator

        get_channel = getattr(self.client, "get_channel", None)

        def resolve_channel(channel_id):
            return get_channel(channel_id) if callable(get_channel) else None

        self.reminder_checker = reminder_checker_factory(
            calendar_manager=self.calendar,
            reminder_manager=self.reminders,
            get_channel_func=resolve_channel,
            clock=self.reminder_clock,
            mutation_coordinator=self.mutation_coordinator,
        )
        self.reminder_checker_task = None

        # Initialize personality and memory systems
        from memory.user_memory import get_user_memory
        from memory.conversation_context import get_context_manager
        from ai.personality_config import get_system_prompt, ResponseStyle

        self.user_memory = get_user_memory(self.mutation_coordinator)
        self.conversation = get_context_manager()
        self.get_system_prompt = get_system_prompt
        self.ResponseStyle = ResponseStyle

        # Initialize conversational response generator
        from ai.conversational_responses import get_conversational_generator

        self.conv_gen = get_conversational_generator()

        # Initialize localization
        from memory.localization import get_localization

        self.loc = get_localization()

        # Initialize feature managers
        from features.countdown_manager import CountdownManager
        from features.poll_manager import PollManager, parse_poll_command, parse_vote
        from features.watchlist_manager import WatchlistManager, parse_watchlist_command
        from features.word_of_day import WordOfTheDay
        from features.quote_manager import QuoteManager, parse_quote_command
        from features.crypto_manager import CryptoManager, parse_price_command
        from features.compliments_manager import ComplimentsManager, parse_compliment_command
        from features.horoscope_manager import HoroscopeManager, parse_horoscope_command
        from features.calculator_manager import CalculatorManager, parse_calculator_command
        from features.url_shortener import URLShortener, parse_shorten_command
        from features.aurora_forecast import AuroraForecast
        from features.daily_digest_manager import DailyDigestManager
        from features.search_manager import SearchManager, detect_search_intent
        from features.browser_manager import BrowserManager
        from features.daily_digest_manager import DailyDigestManager

        self.countdown = CountdownManager()
        self.poll = PollManager(
            clock=self.reminder_clock,
            mutation_coordinator=self.mutation_coordinator,
        )
        self.watchlist = WatchlistManager(
            mutation_coordinator=self.mutation_coordinator,
        )
        self.wod = WordOfTheDay()
        self.quote = QuoteManager(
            mutation_coordinator=self.mutation_coordinator,
        )
        self.crypto = CryptoManager()
        self.compliments = ComplimentsManager()
        self.horoscope = HoroscopeManager()
        self.calculator = CalculatorManager()
        self.url_shortener = URLShortener()
        self.aurora = AuroraForecast()
        self.search_manager = SearchManager()
        self.browser_manager = BrowserManager()
        self.detect_search_intent = detect_search_intent
        from features.birthday_manager import BirthdayManager
        self.birthdays = BirthdayManager(
            mutation_coordinator=self.mutation_coordinator,
            gcal_manager=gcal,
        )

        self.daily_digest = DailyDigestManager(
            event_manager=self.calendar,
            birthday_manager=self.birthdays,
            crypto_manager=self.crypto,
            aurora_manager=self.aurora,
            watchlist_manager=self.watchlist,
            user_memory=self.user_memory,
        )

        self.parse_poll_command = parse_poll_command
        self.parse_vote = parse_vote
        self.parse_watchlist_command = parse_watchlist_command
        self.parse_quote_command = parse_quote_command
        self.parse_price_command = parse_price_command
        self.parse_compliment_command = parse_compliment_command
        self.parse_horoscope_command = parse_horoscope_command
        self.parse_calculator_command = parse_calculator_command
        self.parse_shorten_command = parse_shorten_command

        # Tracking - use deque with maxlen for automatic dedup cleanup
        self.processed_messages = deque(maxlen=1000)
        self.mention_count = 0
        self.response_count = 0
        self.error_count = 0
        self.intent_stats = defaultdict(lambda: {"count": 0, "low_confidence": 0, "errors": 0})
        self._last_persisted_intent_stats: dict[str, dict[str, int]] = {}
        self._last_persisted_rate_stats: dict[str, int] = {}
        self._background_tasks = set()
        self._tasks_by_name = {}
        self._task_health: dict[str, dict[str, object]] = {}
        self._setup_lock = asyncio.Lock()
        self._setup_complete = False
        self._close_lock = asyncio.Lock()
        self._closed = False

        self.handlers = {}
        self._register_handlers()
        self.intent_router = IntentRouter(self)
        self.nlu_metrics = self.intent_router.metrics

    def _track_background_task(self, coro, name):
        if not hasattr(self, "_tasks_by_name"):
            self._tasks_by_name = {}
        existing = self._tasks_by_name.get(name)
        if existing is not None and not existing.done():
            if inspect.iscoroutine(coro):
                coro.close()
            return existing

        task = asyncio.create_task(coro, name=name)
        self._tasks_by_name[name] = task
        self._background_tasks.add(task)
        self._set_task_health(name, state="running", started_at=datetime.now().isoformat(), last_error=None)
        task.add_done_callback(self._background_task_done(name))
        return task

    def _background_task_done(self, name):
        def done_callback(done_task):
            self._background_tasks.discard(done_task)
            tasks_by_name = getattr(self, "_tasks_by_name", {})
            if tasks_by_name.get(name) is not done_task:
                return
            tasks_by_name.pop(name, None)
            if done_task.cancelled():
                self._set_task_health(name, state="cancelled", finished_at=datetime.now().isoformat())
                return
            try:
                exc = done_task.exception()
            except Exception:
                return
            if exc:
                self._mark_task_error(name, exc, state="failed", finished_at=datetime.now().isoformat())
                print(f"[MONITOR] Background task {name} failed: {exc}")
            else:
                self._set_task_health(
                    name,
                    state="completed",
                    finished_at=datetime.now().isoformat(),
                    last_ok=datetime.now().isoformat(),
                    last_error=None,
                    exception_type=None,
                )

        return done_callback

    def _set_task_health(self, name, **updates):
        health = self._task_health.setdefault(name, {"state": "unknown"})
        health.update(updates)

    def _mark_task_ok(self, name):
        self._set_task_health(
            name,
            state="running",
            last_ok=datetime.now().isoformat(),
            last_error=None,
            exception_type=None,
        )

    def _mark_task_error(self, name, exc, *, state="degraded", **extra):
        self._set_task_health(
            name,
            state=state,
            last_error=str(exc),
            exception_type=type(exc).__name__,
            last_error_at=datetime.now().isoformat(),
            **extra,
        )

    def get_task_health(self):
        return {name: dict(values) for name, values in self._task_health.items()}

    async def setup(self):
        if not hasattr(self, "_setup_lock"):
            self._setup_lock = asyncio.Lock()
        if not hasattr(self, "_setup_complete"):
            self._setup_complete = False
        async with self._setup_lock:
            if getattr(self, "_closed", False) or self._setup_complete:
                return

            await self.calendar.setup()
            await self.user_memory.setup()

            # OAuth/token refresh is an explicit startup boundary, never
            # constructor I/O.  Keep the injected manager even when initially
            # unconfigured so an auth flow can enable it later in this process.
            gcal_status = await self.calendar.ensure_gcal_configured()
            if gcal_status.ok:
                print("[MONITOR] Google Calendar integration enabled")
                print("[MONITOR] Performing initial Google Calendar sync...")
                reference_time = self.reminder_clock.now()
                self._track_background_task(
                    self.calendar.sync_from_gcal_result(
                        reference_time=reference_time,
                    ),
                    "initial-gcal-sync",
                )
            elif gcal_status.state is ExternalCommitState.UNKNOWN:
                self._set_task_health(
                    "initial-gcal-sync",
                    state="degraded",
                    last_error="external_commit_unknown",
                )

            self._track_background_task(
                self._console_persistence_loop(),
                "console-persistence",
            )
            reminder_checker = getattr(self, "reminder_checker", None)
            if reminder_checker is not None:
                await reminder_checker.setup()
                self.reminder_checker_task = self._track_background_task(
                    reminder_checker.start(),
                    "reminder-checker",
                )
                print("[MONITOR] Calendar reminder checker started")
            self._setup_complete = True

            print("[MONITOR] Async managers (Calendar, Memory, Birthdays) initialized")

    async def close(self):
        """Stop the checker, then settle every monitor-owned task once."""
        if not hasattr(self, "_setup_lock"):
            self._setup_lock = asyncio.Lock()
        if not hasattr(self, "_close_lock"):
            self._close_lock = asyncio.Lock()
        if not hasattr(self, "_closed"):
            self._closed = False
        # Serialize shutdown behind any in-flight setup. Once ``_closed`` is
        # published under this boundary, a later setup cannot start new work.
        async with self._setup_lock:
            async with self._close_lock:
                if self._closed:
                    return

                reminder_checker = getattr(self, "reminder_checker", None)
                if reminder_checker is not None:
                    try:
                        stopped = reminder_checker.stop()
                        if inspect.isawaitable(stopped):
                            await stopped
                    except Exception as exc:
                        self._mark_task_error("reminder-checker", exc)

                tasks = list(self._background_tasks)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                self._background_tasks.clear()
                getattr(self, "_tasks_by_name", {}).clear()
                if hasattr(self, "reminder_checker_task"):
                    self.reminder_checker_task = None
                self._closed = True

    async def _console_persistence_loop(self) -> None:
        """Periodically save intent and rate-limit stats to disk."""
        try:
            while True:
                await asyncio.sleep(60)
                try:
                    await self._persist_console_stats_once()
                except Exception as exc:
                    self._mark_task_error("console-persistence", exc)
        except asyncio.CancelledError:
            pass

    async def _persist_console_stats_once(self) -> None:
        """Persist one stats delta batch and update health only after success."""
        from web_console.console_store import get_console_store

        store = get_console_store()
        rate_stats: dict[str, int] = {}
        overall = self.rate_limiter.get_stats() if hasattr(self.rate_limiter, "get_stats") else {}
        if isinstance(overall, dict):
            for key in ("user_stats", "per_user", "users"):
                candidate = overall.get(key)
                if isinstance(candidate, dict):
                    for user, stats in candidate.items():
                        count = stats.get("requests", 0) if isinstance(stats, dict) else int(stats)
                        rate_stats[user] = rate_stats.get(user, 0) + count
                    break
        intent_snapshot = _copy_counter_stats(dict(self.intent_stats))
        intent_delta = _counter_stats_delta(
            intent_snapshot,
            getattr(self, "_last_persisted_intent_stats", {}),
        )
        rate_delta = _flat_counter_delta(
            rate_stats,
            getattr(self, "_last_persisted_rate_stats", {}),
        )
        if intent_delta or rate_delta:
            if not store.save_stats(intent_delta, rate_delta):
                raise RuntimeError("console stats save failed")
        self._last_persisted_intent_stats = intent_snapshot
        self._last_persisted_rate_stats = dict(rate_stats)
        self._mark_task_ok("console-persistence")

    def is_mention(self, message):
        """Check if message explicitly mentions the bot."""
        if self.client.user and any(
            getattr(user, "id", None) == self.client.user.id
            for user in getattr(message, "mentions", [])
        ):
            return True

        if self.client.user:
            mention_strings = [
                f"<@{self.client.user.id}>",
                f"<@!{self.client.user.id}>",
            ]
            for mention in mention_strings:
                if mention in message.content:
                    return True

        if self.bot_mention.lower() in message.content.lower():
            return True

        return False

    def clean_authorized_content(self, message):
        """Remove only Inebotten's own mention after the message is authorized."""
        content = message.content

        if self.client.user:
            content = re.sub(
                rf"<@!?{re.escape(str(self.client.user.id))}>",
                "",
                content,
            )

        content = re.sub(
            rf"@{re.escape(self.bot_name)}\b[:,]?",
            "",
            content,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", content).strip()

    def authorize_message(self, message):
        """Return a cleaned message proxy if the bot is explicitly mentioned."""
        if not self.is_mention(message):
            return None
        return AuthorizedMessage(message, self.clean_authorized_content(message))

    async def handle_message(self, message):
        """Process an incoming message"""
        # Skip own messages
        if message.author.id == self.client.user.id:
            return

        # Security & Privacy Gate: Only respond to authorized users
        # This is a selfbot, so we should be very strict about who can trigger AI/actions.
        allowed_users = getattr(self.client.config, 'ALLOWED_USERS', [])
        if allowed_users and message.author.id not in allowed_users:
            return

        # Optional: Channel restriction for non-DM channels
        allowed_channels = getattr(self.client.config, 'ALLOWED_CHANNELS', [])
        if allowed_channels and not isinstance(message.channel, discord.DMChannel):
            if message.channel.id not in allowed_channels:
                # If it's a group DM, we might still want to allow it, 
                # but the user specifically pointed to one channel.
                if not isinstance(message.channel, discord.GroupChannel):
                    return

        authorized_message = self.authorize_message(message)
        if not authorized_message:
            return

        # Skip already processed after the mention gate so untagged messages are not tracked.
        msg_id = f"{message.channel.id}:{message.id}"
        if msg_id in self.processed_messages:
            return
        self.processed_messages.append(msg_id)

        message = authorized_message
        reference_time = self.reminder_clock.now()
        routing_context = routing_context_from_message(
            message,
            bot_user_id=self.client.user.id,
        )
        self.mention_count += 1
        print(
            f"[MONITOR] Mention detected from {message.author.name} "
            f"in {self._get_channel_type(message.channel)}"
        )

        # Detect language from message
        lang = self.loc.detect_language(message.content)
        self.loc.set_language(lang)
        print(f"[MONITOR] Detected language: {lang}")

        guild_id = routing_context.key.guild_id
        route = None
        try:
            route = self.intent_router.route(
                message.content,
                guild_id=guild_id,
                channel_id=message.channel.id,
                user_id=message.author.id,
                routing_context=routing_context,
                reference_time=reference_time,
            )
            self._last_routed_intent = route.intent
            print(f"[MONITOR] Intent matched: {route.intent.value} ({route.reason}, {route.confidence:.2f})")
            await self._handle_intent(
                message,
                route,
                reference_time=reference_time,
            )
            self.intent_stats[route.intent.value]["count"] += 1
        except Exception as exc:
            import traceback

            route_name = route.intent.value if route else "unknown"
            print(f"[MONITOR] ERROR handling intent {route_name}: {exc}")
            traceback.print_exc()
            self.error_count += 1
            self.intent_stats[route_name]["errors"] += 1
            try:
                await self._send_ai_response(
                    message,
                    reference_time=reference_time,
                )
            except Exception as ai_exc:
                print(f"[MONITOR] AI fallback also failed: {ai_exc}")

    def _typed_inner_payload(self, route):
        """Return one validated canonical inner payload or compatibility absence."""
        key = ENVELOPE_KEYS.get(route.intent)
        if key is None:
            return _NO_TYPED_ENVELOPE
        route_payload = getattr(route, "payload", None)
        if route_payload is None:
            return None
        if not isinstance(route_payload, Mapping):
            raise PayloadValidationError("missing_payload")
        if key not in route_payload:
            return None
        source = getattr(route, "source", None)
        if source is None:
            return validate_intent_payload(
                route.intent,
                route_payload[key],
            )
        return validate_intent_payload(
            route.intent,
            route_payload[key],
            source=source,
        )

    async def _invoke_legacy_read(self, callback) -> DispatchOutcome:
        """Adapt one unchanged read handler using task-local delivery truth."""
        with capture_send_receipt() as receipt:
            try:
                result = await callback()
            except Exception:
                base = DispatchOutcome.failure("handler_exception")
                return (
                    base
                    if receipt.result is None
                    else base.with_delivery(receipt.result)
                )
        if isinstance(result, DispatchOutcome):
            if result.delivery_result is not None:
                return result
            base = result
        else:
            base = DispatchOutcome.success(mutated=False)
        return (
            base
            if receipt.result is None
            else base.with_delivery(receipt.result)
        )

    async def _handle_intent(self, message, route, *, reference_time: datetime):
        """Execute one routed intent from its already parsed payload."""
        raw_payload = getattr(route, "payload", None)
        payload = raw_payload if isinstance(raw_payload, Mapping) else {}

        try:
            typed_payload = self._typed_inner_payload(route)
        except PayloadValidationError as exc:
            print(
                f"[MONITOR] Rejected malformed {route.intent.value} payload: "
                f"{exc.code}"
            )
            send = await self._send_response_result(
                message,
                "Jeg klarte ikke å tolke handlingen trygt. Ingenting ble endret.",
            )
            return DispatchOutcome.failure(
                "invalid_payload",
            ).with_delivery(send)

        if getattr(route, "requires_confirmation", False):
            send = await self._send_response_result(
                message,
                "Jeg kan ikke bekrefte denne handlingen trygt ennå. "
                "Ingenting ble endret.",
            )
            return DispatchOutcome.failure(
                "confirmation_unavailable",
                retryable=False,
            ).with_delivery(send)

        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        if route.confidence < threshold:
            print(
                f"[MONITOR] Intent {route.intent.value} rejected: confidence {route.confidence:.2f} < threshold {threshold}"
            )
            self.intent_stats[route.intent.value]["low_confidence"] += 1
            fallback = await self._invoke_legacy_read(
                lambda: self._send_ai_response(
                    message,
                    reference_time=reference_time,
                )
            )
            base = DispatchOutcome.failure("low_confidence")
            return (
                base
                if fallback.delivery_result is None
                else base.with_delivery(fallback.delivery_result)
            )

        if route.intent == BotIntent.HELP:
            return await self._invoke_legacy_read(
                lambda: self.handlers["help"].handle_help(message)
            )
        elif route.intent == BotIntent.CALENDAR_HELP:
            return await self._invoke_legacy_read(
                lambda: self._send_response(
                    message,
                    self.conv_gen.get_calendar_help(),
                )
            )
        elif route.intent == BotIntent.STATUS:
            return await self._invoke_legacy_read(
                lambda: self._send_status_response(message)
            )
        elif route.intent == BotIntent.PROFILE:
            async def handle_profile_or_chat():
                handled = await self.handlers["profile"].handle_profile_command(
                    message
                )
                if not handled:
                    await self._send_ai_response(
                        message,
                        reference_time=reference_time,
                    )

            return await self._invoke_legacy_read(handle_profile_or_chat)
        elif route.intent == BotIntent.CALENDAR_LIST:
            return await self.handlers["calendar"].handle_list(
                message,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_SYNC:
            return await self.handlers["calendar"].handle_sync(
                message,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_DELETE:
            return await self.handlers["calendar"].handle_delete(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_COMPLETE:
            return await self.handlers["calendar"].handle_complete(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_EDIT:
            return await self.handlers["calendar"].handle_edit(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_SEARCH:
            return await self.handlers["calendar"].handle_search(
                message,
                payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_CLEAR:
            return await self.handlers["calendar"].handle_clear(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_ITEM:
            return await self.handlers["calendar"].handle_calendar_item(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.CALENDAR_AUTH:
            return await self.handlers["calendar"].handle_auth(
                message,
                payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.REMINDER_EDIT:
            return await self.handlers["reminders"].handle_reminder_edit(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.REMINDER_DELETE:
            return await self.handlers["reminders"].handle_reminder_delete(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.REMINDER_SEARCH:
            return await self.handlers["reminders"].handle_reminder_search(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.REMINDER_CREATE:
            return await self.handlers["reminders"].handle_reminder_create(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.REMINDER_LIST:
            return await self.handlers["reminders"].handle_reminder_list(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.REMINDER_COMPLETE:
            return await self.handlers["reminders"].handle_reminder_complete(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.POLL_CREATE:
            return await self.handlers["polls"].handle_poll(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.POLL_VOTE:
            return await self.handlers["polls"].handle_vote(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.POLL_EDIT:
            return await self.handlers["polls"].handle_poll_edit(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.POLL_DELETE:
            return await self.handlers["polls"].handle_poll_delete(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.POLL_CLOSE:
            return await self.handlers["polls"].handle_poll_close(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.POLL_LIST:
            return await self.handlers["polls"].handle_poll_list(
                message,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.COUNTDOWN:
            return await self._invoke_legacy_read(
                lambda: self.handlers["countdown"].handle_countdown(
                    message,
                    payload.get("countdown"),
                )
            )
        elif route.intent == BotIntent.WATCHLIST:
            return await self.handlers["watchlist"].handle_watchlist(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.WORD_OF_DAY:
            return await self._invoke_legacy_read(
                lambda: self.handlers["fun"].handle_word_of_day(message)
            )
        elif route.intent == BotIntent.QUOTE:
            return await self.handlers["fun"].handle_quote_command(
                message,
                typed_payload,
            )
        elif route.intent == BotIntent.QUOTE_LIST:
            return await self.handlers["quotes"].handle_quote_list(
                message,
                typed_payload,
            )
        elif route.intent == BotIntent.QUOTE_EDIT:
            return await self.handlers["quotes"].handle_quote_edit(
                message,
                typed_payload,
            )
        elif route.intent == BotIntent.QUOTE_DELETE:
            return await self.handlers["quotes"].handle_quote_delete(
                message,
                typed_payload,
            )
        elif route.intent == BotIntent.AURORA:
            return await self._invoke_legacy_read(
                lambda: self.handlers["aurora"].handle_aurora(message)
            )
        elif route.intent == BotIntent.SCHOOL_HOLIDAYS:
            return await self._invoke_legacy_read(
                lambda: self.handlers["school_holidays"].handle_school_holidays(
                    message
                )
            )
        elif route.intent == BotIntent.PRICE:
            return await self._invoke_legacy_read(
                lambda: self.handlers["utility"].handle_price(
                    message,
                    payload.get("price"),
                )
            )
        elif route.intent == BotIntent.HOROSCOPE:
            return await self._invoke_legacy_read(
                lambda: self.handlers["fun"].handle_horoscope(
                    message,
                    payload.get("horoscope"),
                )
            )
        elif route.intent == BotIntent.COMPLIMENT:
            return await self._invoke_legacy_read(
                lambda: self.handlers["fun"].handle_compliment(
                    message,
                    payload.get("compliment"),
                )
            )
        elif route.intent == BotIntent.CALCULATOR:
            return await self._invoke_legacy_read(
                lambda: self.handlers["utility"].handle_calculator(
                    message,
                    payload.get("calculator"),
                )
            )
        elif route.intent == BotIntent.SHORTEN_URL:
            return await self._invoke_legacy_read(
                lambda: self.handlers["utility"].handle_shorten(
                    message,
                    payload.get("shorten"),
                )
            )
        elif route.intent == BotIntent.DAILY_DIGEST:
            return await self._invoke_legacy_read(
                lambda: self.handlers["daily_digest"].handle_daily_digest(message)
            )
        elif route.intent == BotIntent.BIRTHDAY_CREATE:
            return await self.handlers["birthdays"].handle_birthday_create(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.BIRTHDAY_LIST:
            return await self.handlers["birthdays"].handle_birthday_list(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.BIRTHDAY_EDIT:
            return await self.handlers["birthdays"].handle_birthday_edit(
                message,
                typed_payload,
                reference_time=reference_time,
            )
        elif route.intent == BotIntent.SET_LOCATION:
            return await self._handle_set_location(
                message,
                payload.get("city"),
                reference_time=reference_time,
            )
        elif route.intent in (BotIntent.MEMORY_VIEW, BotIntent.MEMORY_EXPORT, BotIntent.MEMORY_DELETE):
            return await self._invoke_legacy_read(
                lambda: self.handlers["memory"].handle_memory(
                    message,
                    payload.get("memory", {}),
                )
            )
        elif route.intent == BotIntent.SEARCH:
            return await self._invoke_legacy_read(
                lambda: self._send_ai_response(
                    message,
                    forced_search_info=payload.get("search"),
                    reference_time=reference_time,
                )
            )
        elif route.intent == BotIntent.DASHBOARD:
            return await self._invoke_legacy_read(
                lambda: self._send_dashboard_response(
                    message,
                    reference_time=reference_time,
                )
            )
        else:
            return await self._invoke_legacy_read(
                lambda: self._send_ai_response(
                    message,
                    reference_time=reference_time,
                )
            )

    async def _send_dashboard_response(
        self,
        message,
        *,
        reference_time: datetime,
    ):
        """Generate and send an explicit dashboard response."""
        guild_id = message.guild.id if message.guild else message.channel.id
        content_lower = message.content.lower()
        from features.weather_api import extract_city

        response_text = await self._generate_dashboard(
            guild_id,
            city_name=extract_city(message.content),
            show_navnedag=any(
                re.search(rf"\b{re.escape(word)}\b", content_lower)
                for word in ["navnedag", "oppsummering", "brief", "status"]
            ),
            user_id=message.author.id,
            reference_time=reference_time,
        )
        await self._send_response(message, response_text)

    async def _send_ai_response(
        self,
        message,
        forced_search_info=None,
        *,
        reference_time: datetime,
    ):
        """
        Generate and send an AI response to a mention.
        Uses Hermes AI with personality system.
        """
        print(f"[MONITOR] _send_ai_response called for message: {message.content[:50]}...")

        channel_type = self._get_channel_type(message.channel)
        print(f"[MONITOR] Channel type: {channel_type}")
        guild_id = message.guild.id if message.guild else message.channel.id
        channel_id = message.channel.id
        content_lower = message.content.lower()
        wants_dashboard, dashboard_reason = self.conversation.should_show_dashboard(
            message.content, channel_id
        )
        print(f"[MONITOR] AI fallback mode: dashboard={wants_dashboard} ({dashboard_reason})")

        # AI Router Mode: We default to chat and let the AI decide if a dashboard/action is needed.
        # But we still check for explicit city names if the user MIGHT want weather.
        city_name = None
        from features.weather_api import extract_city
        city_name = extract_city(message.content)
        if city_name:
            print(f"[MONITOR] Specific city detected for context: {city_name}")
        
        show_navnedag = any(re.search(rf"\b{re.escape(word)}\b", content_lower) for word in ['navnedag', 'oppsummering', 'brief', 'status'])


        # Update conversation history
        self.conversation.add_message(
            channel_id=channel_id,
            user_id=message.author.id,
            username=message.author.name,
            content=message.content,
            is_bot=False,
        )

        # Conversation persistence is helpful context, but a local memory
        # write failure must not turn an otherwise valid chat turn into
        # command-style silence.  Cancellation still propagates separately.
        try:
            await self.user_memory.update_last_interaction_result(
                message.author.id,
                reference_time=reference_time,
                topic=self.conversation.get_conversation_summary(channel_id),
                username=message.author.name,
            )
        except ManagerMutationError as exc:
            code = (
                exc.code
                if exc.code in {"storage_write_failed", "commit_state_unknown"}
                else "commit_state_unknown"
            )
            print(f"[MONITOR] User-memory update degraded: {code}")
        except Exception as exc:
            print(
                "[MONITOR] User-memory update degraded: "
                f"{type(exc).__name__}"
            )

        response_text = None

        # If it's small talk, don't show dashboard - use AI conversation
        if not wants_dashboard:
            # Check for Norwegian dialect expressions first (fast path)
            from ai.personality import get_personality
            dialect_response = get_personality().respond_to_dialect(message.content)
            if dialect_response:
                response_text = dialect_response
                print(f"[MONITOR] Using dialect response for: {message.content[:50]}")
            
            # Fall back to AI if no dialect match and hermes is available
            if not response_text and self.hermes:
                try:
                    user_context = await self.user_memory.format_context_for_prompt(
                        message.author.id, message.author.name
                    )
                    conversation_context = self.conversation.get_context(
                        channel_id, limit=5
                    )

                    # Check for search intent
                    search_info = forced_search_info or self.detect_search_intent(message.content)
                    search_context = ""
                    search_was_requested = False
                    if search_info:
                        search_was_requested = True
                        query = search_info["query"]
                        search_type = search_info["type"]
                        print(f"[MONITOR] Web search ({search_type}) triggered for: {query}")
                        
                        if search_type == "news":
                            search_results = await self.search_manager.get_news(query)
                        else:
                            search_results = await self.search_manager.search(query)
                            
                        if search_results:
                            search_context = self.search_manager.format_results_for_ai(search_results)
                            print(f"[MONITOR] Found {len(search_results)} search results")
                            
                            # WEB LOOKUP: Only use Browserbase if we don't have deep content yet
                            has_deep_content = any(len(res.get('body', '')) > 500 for res in search_results)
                            
                            if not has_deep_content and self.browser_manager.is_configured() and len(search_results) > 0:
                                top_url = search_results[0].get('href') or search_results[0].get('url')
                                if top_url:
                                    print(f"[MONITOR] Web Lookup: Tavily content was shallow. Using Browserbase fallback for: {top_url}")
                                    page_content = await self.browser_manager.fetch_page_content(top_url)
                                    if page_content:
                                        search_context += f"\n\nDETALJERT INFORMASJON FRA KILDEN ({top_url}):\n{page_content}\n"
                                        print("[MONITOR] Web Lookup: Browserbase fallback successful")
                            elif has_deep_content:
                                print("[MONITOR] Web Lookup: Tavily provided deep content. Skipping Browserbase.")
                        else:
                            response_text = (
                                "Jeg fant ingen ferske kilder akkurat nå, så jeg vil ikke late som jeg "
                                "har sjekket dette. Jeg kan svare generelt hvis du vil, men da bør vi "
                                "merke det som ikke-verifisert."
                            )

                    if not response_text:
                        system_prompt = self.get_system_prompt(
                            user_context=user_context,
                            conversation_context=conversation_context,
                            style=self.ResponseStyle.CASUAL,
                            routed_intent=getattr(self, '_last_routed_intent', None),
                        )

                        # Inject search results into system prompt if available
                        if search_context:
                            system_prompt += f"\n\nSØKERESULTATER FRA NETTET:\n{search_context}\n"
                            system_prompt += (
                                "\nVIKTIG: Bruk bare kildene over for oppdaterte påstander. "
                                "Oppgi kilde med tittel eller URL. Ikke kall noe ferskt bare fordi "
                                "det ble hentet nå. Hvis publiseringsdato mangler, si at "
                                "publiseringsdato ikke var tilgjengelig. Hvis kildene spriker eller "
                                "er svake, si det tydelig."
                            )
                        elif search_was_requested:
                            system_prompt += (
                                "\n\nSØK: Ingen kilder ble funnet. Ikke presenter svaret som live-sjekket "
                                "eller verifisert på nettet."
                            )

                        print(f"[MONITOR] Using personalized system prompt ({len(system_prompt)} chars)")

                        success, ai_response = await self.hermes.generate_response(
                            message_content=message.content,
                            author_name=message.author.name,
                            channel_type=channel_type,
                            is_mention=True,
                            system_prompt=system_prompt,
                        )

                        if success and ai_response:
                            print("[MONITOR] Using personalized AI response")
                            # Parse and execute actions before sending
                            response_text = await self._parse_and_execute_actions(
                                ai_response,
                                message,
                                reference_time=reference_time,
                            )
                except Exception as e:
                    print(f"[MONITOR] Personalized AI failed: {e}")

        # Fallback: dashboard or basic response
        if not response_text:
            if wants_dashboard:
                response_text = await self._generate_dashboard(
                    guild_id, 
                    city_name=city_name, 
                    show_navnedag=show_navnedag,
                    user_id=message.author.id,
                    reference_time=reference_time,
                )
            else:
                from ai.personality_config import get_fallback_response
                response_text = get_fallback_response("general")

        # Send the response
        await self._send_response(message, response_text)

    async def _parse_and_execute_actions(
        self,
        response_text,
        message,
        *,
        reference_time: datetime | None = None,
    ):
        """
        Parses AI response for [ACTION] tags and executes them.
        Returns the cleaned response text.
        """
        cleaned_text = response_text
        import json

        # 0. Try JSON format first
        for line in cleaned_text.split('\n'):
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    action_data = json.loads(line)
                    action_type = action_data.get('action')
                    if action_type == 'SAVE_EVENT':
                        title = action_data.get('title', '')
                        date = action_data.get('date', '')
                        time = action_data.get('time', '')
                        print(f"[ROUTER] Drafted SAVE_EVENT action (JSON), waiting for user confirmation: {title} on {date} at {time}")
                        cleaned_text = cleaned_text.replace(line, '').strip()
                        cleaned_text = self._append_calendar_draft_confirmation(
                            cleaned_text, title, date, time
                        )
                    elif action_type == 'SHOW_DASHBOARD':
                        print("[ROUTER] Detected SHOW_DASHBOARD action (JSON)")
                        try:
                            guild_id = message.guild.id if message.guild else message.channel.id
                            user_mem = (
                                self.user_memory.snapshot_user(message.author.id)
                                or {}
                            )
                            city_name = user_mem.get("location", "Oslo")

                            dashboard_text = await self._generate_dashboard(
                                guild_id,
                                city_name=city_name,
                                reference_time=reference_time,
                            )
                            await self._send_response(message, dashboard_text)
                        except Exception as e:
                            print(f"[ROUTER] Failed to show dashboard: {e}")

                        cleaned_text = cleaned_text.replace(line, '').strip()
                except json.JSONDecodeError:
                    pass

        # 1. Handle [SAVE_EVENT: Title | Date | Time]
        event_match = re.search(r'\[SAVE_EVENT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\]', cleaned_text)
        if event_match:
            title, date, time = event_match.groups()
            print(f"[ROUTER] Drafted SAVE_EVENT action, waiting for user confirmation: {title} on {date} at {time}")
            
            cleaned_text = cleaned_text.replace(event_match.group(0), "").strip()
            cleaned_text = self._append_calendar_draft_confirmation(
                cleaned_text, title, date, time
            )

        # 2. Handle [SHOW_DASHBOARD]
        if '[SHOW_DASHBOARD]' in cleaned_text:
            print("[ROUTER] Detected SHOW_DASHBOARD action")
            try:
                guild_id = message.guild.id if message.guild else message.channel.id
                # Get location from user memory
                user_mem = self.user_memory.snapshot_user(message.author.id) or {}
                city_name = user_mem.get("location", "Oslo")
                
                dashboard_text = await self._generate_dashboard(
                    guild_id,
                    city_name=city_name,
                    reference_time=reference_time,
                )
                await self._send_response(message, dashboard_text)
            except Exception as e:
                print(f"[ROUTER] Failed to show dashboard: {e}")
            
            cleaned_text = cleaned_text.replace('[SHOW_DASHBOARD]', "").strip()
            
        return cleaned_text

    def _append_calendar_draft_confirmation(self, text, title, date, time):
        """Ask the user to confirm model-suggested calendar writes explicitly."""
        title = str(title or "").strip() or "Uten tittel"
        date = str(date or "").strip()
        time = str(time or "").strip()
        command = f'@inebotten legg til "{title}"'
        if date:
            command += f" {date}"
        if time:
            command += f" kl {time}"
        draft = (
            f"📅 Jeg kan legge dette i kalenderen, men jeg lagrer det ikke uten bekreftelse:\n"
            f"**{title}**"
            f"{f' — {date}' if date else ''}"
            f"{f' kl. {time}' if time else ''}\n\n"
            f"Skriv `{command}` hvis det skal lagres."
        )
        return f"{text}\n\n{draft}".strip() if text else draft

    async def _handle_set_location(
        self,
        message,
        city,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Persist one canonical city and report mutation/delivery truth."""
        from features.weather_api import NORWEGIAN_CITIES

        city_info = (
            NORWEGIAN_CITIES.get(city.strip().lower())
            if isinstance(city, str) and city.strip()
            else None
        )
        if city_info is None:
            response = (
                f'❌ Beklager, jeg kjenner ikke til "{city or ""}" ennå. '
                "Jeg kan foreløpig bare lagre norske byer."
            )
            base = DispatchOutcome.failure(
                "unsupported_city",
            )
            try:
                delivery = await self._send_response_result(message, response)
            except MessageSendCancelled as exc:
                raise DispatchCancelled(base.with_delivery(exc.result)) from None
            return base.with_delivery(delivery)

        known_manager_codes = {
            "cancelled",
            "commit_state_unknown",
            "storage_write_failed",
        }
        prior_mutated = False

        def manager_outcome(exc, *, cancelled: bool) -> DispatchOutcome:
            code = getattr(exc, "code", "commit_state_unknown")
            bounded = code if code in known_manager_codes else "commit_state_unknown"
            mutated = prior_mutated or bool(getattr(exc, "mutated", False))
            commit_unknown = bool(getattr(exc, "commit_unknown", False)) or (
                bounded == "commit_state_unknown" and code not in known_manager_codes
            )
            retryable = (
                bool(getattr(exc, "retryable", False))
                if cancelled
                else bounded == "storage_write_failed"
            )
            return DispatchOutcome.failure(
                bounded,
                mutated=mutated,
                retryable=retryable and not mutated and not commit_unknown,
                commit_unknown=commit_unknown,
            )

        try:
            # Keep lazy user creation and the location update in one reentrant
            # family lease so another task cannot make mutation attribution
            # ambiguous between the two compatibility writes.
            async with self.mutation_coordinator.hold(MEMORY_STORE_SCOPE):
                existed = (
                    self.user_memory.snapshot_user(message.author.id) is not None
                )
                await self.user_memory.get_or_create_user_result(
                    message.author.id,
                    message.author.name,
                    reference_time=reference_time,
                )
                prior_mutated = not existed
                changed = await self.user_memory.set_location_result(
                    message.author.id,
                    city_info["name"],
                )
        except ManagerMutationCancelled as exc:
            raise DispatchCancelled(
                manager_outcome(exc, cancelled=True)
            ) from None
        except ManagerMutationError as exc:
            base = manager_outcome(exc, cancelled=False)
            response = (
                "❌ Beklager, det oppstod en feil da jeg prøvde å lagre "
                "lokasjonen din."
            )
        except Exception as exc:
            print(
                "[MONITOR] Unexpected location mutation error: "
                f"{type(exc).__name__}"
            )
            base = DispatchOutcome.failure(
                "commit_state_unknown",
                mutated=prior_mutated,
                commit_unknown=True,
            )
            response = (
                "❌ Beklager, det oppstod en feil da jeg prøvde å lagre "
                "lokasjonen din."
            )
        else:
            base = DispatchOutcome.success(mutated=prior_mutated or changed)
            response = (
                "✅ Den er grei! Jeg har lagret at du bor i "
                f"**{city_info['name']}**. Jeg bruker dette når jeg henter "
                "været for deg framover. 😊"
            )

        try:
            delivery = await self._send_response_result(message, response)
        except MessageSendCancelled as exc:
            raise DispatchCancelled(base.with_delivery(exc.result)) from None
        return base.with_delivery(delivery)

    def _is_status_command(self, content_lower):
        """Return True for bot health/status commands, not profile status changes."""
        normalized = content_lower.strip()
        return any(keyword in normalized for keyword in STATUS_KEYWORDS)

    async def _send_status_response(self, message):
        """Send a concise operational status report."""
        uptime = self.client.get_uptime() if hasattr(self.client, "get_uptime") else None
        handler_count = sum(1 for handler in self.handlers.values() if handler is not None)
        rate_stats = self.rate_limiter.get_stats()
        hermes_stats = self.hermes.get_stats() if self.hermes else {}
        last_error = (
            getattr(self.hermes, "last_error", None)
            or getattr(self.rate_limiter, "last_error", None)
            or "none"
        )

        try:
            if self.hermes:
                healthy, health_message = await self.hermes.check_health()
            else:
                healthy, health_message = False, "AI connector missing"
        except Exception as e:
            healthy, health_message = False, str(e)

        ai_status = "ok" if healthy else "degraded"
        response_text = "\n".join(
            [
                "🤖 **Inebotten status**",
                f"Uptime: {uptime or 'starting'}",
                f"Handlers: {handler_count}/{len(self.handlers)} loaded",
                f"AI: {ai_status} ({health_message})",
                f"Rate limit: {rate_stats.get('sent_last_second', 0)} sent last second, "
                f"{rate_stats.get('sent_today', 0)} today",
                f"Mentions handled: {self.mention_count}",
                f"Responses sent: {self.response_count}",
                f"Last error: {last_error}",
                f"Provider stats: {hermes_stats.get('provider', 'unknown')}",
            ]
        )
        intent_stats_lines = []
        for intent_name, stats in sorted(self.intent_stats.items()):
            intent_stats_lines.append(
                f"  {intent_name}: {stats['count']} (low: {stats['low_confidence']}, err: {stats['errors']})"
            )
        if intent_stats_lines:
            response_text += "\nIntent stats:\n" + "\n".join(intent_stats_lines)
        await self._send_response(message, response_text)

    async def _generate_dashboard(
        self,
        guild_id: int,
        city_name: str = None,
        show_navnedag: bool = False,
        user_id: int = None,
        *,
        reference_time: datetime | None = None,
    ) -> str:
        """Generate dashboard response with weather, events, etc."""
        from cal_system.norwegian_calendar import get_todays_info
        from features.weather_api import METWeatherAPI, NORWEGIAN_CITIES

        norwegian_data = get_todays_info()
        weather_api = METWeatherAPI()
        
        # If no city name provided, check user memory
        if not city_name and user_id:
            user_mem = self.user_memory.snapshot_user(user_id) or {}
            if user_mem.get("location"):
                city_name = user_mem["location"]
                print(f"[MONITOR] Using stored location for dashboard: {city_name}")

        # Get coordinates for city if provided, otherwise default to Oslo
        city_info = NORWEGIAN_CITIES.get(city_name.lower()) if city_name else NORWEGIAN_CITIES['oslo']
        
        weather_data = await weather_api.get_weather(
            lat=city_info['lat'],
            lon=city_info['lon'],
            location_name=city_info['name']
        )
        await weather_api.close()

        if weather_data:
            weather_formatted = {
                "conditions": weather_data["condition"],
                "temp": weather_data["temp"],
                "location": weather_data["location"],
                "lat": city_info['lat'],
                "lon": city_info['lon']
            }
        else:
            weather_formatted = {
                "conditions": "Delvis skyet", 
                "temp": 8, 
                "location": city_info['name'],
                "lat": city_info['lat'],
                "lon": city_info['lon']
            }

        if reference_time is None:
            reference_time = self.reminder_clock.now()
        upcoming_items = self.calendar.get_upcoming(
            guild_id,
            days=7,
            reference_time=reference_time,
        )
        active_reminders = self.reminders.get_active_reminders(guild_id)

        dashboard = self.conv_gen.generate_dashboard(
            weather_data=weather_formatted,
            events=upcoming_items,
            reminders=active_reminders,
            norwegian_data=norwegian_data,
            show_navnedag=show_navnedag,
        )

        return dashboard

    def _record_monitor_delivery(
        self,
        message,
        response_text: str,
        result: MessageSendResult,
    ) -> None:
        if result.state is not DeliveryState.DELIVERED:
            return
        self.response_count += 1
        author_name = getattr(getattr(message, "author", None), "name", "unknown")
        print(
            f"[MONITOR] Response sent to {author_name}: "
            f"{response_text[:100]}..."
        )
        add_message = getattr(self.conversation, "add_message", None)
        if callable(add_message):
            try:
                add_message(
                    channel_id=message.channel.id,
                    user_id=message.author.id,
                    username="Inebotten",
                    content=response_text,
                    is_bot=True,
                )
            except Exception:
                # Conversation history is contextual bookkeeping.  Once the
                # Discord adapter has confirmed delivery it must not rewrite
                # that truth or trigger an alternate response.
                print("[MONITOR] Conversation response recording degraded")

    async def _send_response_result(
        self,
        message,
        response_text: str,
    ) -> MessageSendResult:
        """Delegate one response to the monitor-owned canonical sender."""
        owned_send = asyncio.create_task(
            self.discord_sender.send_result(message, response_text)
        )
        try:
            result = await _settle_owned_send(owned_send)
        except MessageSendCancelled as exc:
            self._record_monitor_delivery(message, response_text, exc.result)
            raise
        self._record_monitor_delivery(message, response_text, result)
        return result

    async def _send_response(self, message, response_text):
        """One-release projection over tri-state monitor delivery truth."""
        result = await self._send_response_result(message, response_text)
        return True if result.state is DeliveryState.DELIVERED else None

    def _get_channel_type(self, channel):
        """Get string representation of channel type"""
        if isinstance(channel, discord.DMChannel):
            return "DM"
        elif isinstance(channel, discord.GroupChannel):
            return "GROUP_DM"
        elif isinstance(channel, discord.TextChannel):
            return "GUILD_TEXT"
        else:
            return "UNKNOWN"

    def get_stats(self):
        """Get monitor statistics"""
        return {
            "mentions_detected": self.mention_count,
            "responses_sent": self.response_count,
            "errors": self.error_count,
            "messages_tracked": len(self.processed_messages),
        }

    def get_intent_stats(self):
        return dict(self.intent_stats)

    def get_unsaved_intent_stats(self):
        return _counter_stats_delta(
            _copy_counter_stats(dict(self.intent_stats)),
            getattr(self, "_last_persisted_intent_stats", {}),
        )

    def get_handlers_status(self):
        """Get status of all handlers"""
        status = {}
        for name, handler in self.handlers.items():
            status[name] = "loaded" if handler is not None else "not loaded"
        return status

    def get_command_registry(self):
        """Return command metadata used by help/status surfaces."""
        return COMMAND_REGISTRY

    def _register_handlers(self):
        """Register all handlers"""
        from features.fun_handler import FunHandler
        from features.utility_handler import UtilityHandler
        from features.countdown_handler import CountdownHandler
        from features.polls_handler import PollsHandler
        from features.calendar_handler import CalendarHandler
        from features.watchlist_handler import WatchlistHandler
        from features.aurora_handler import AuroraHandler
        from features.school_holidays_handler import SchoolHolidaysHandler
        from features.help_handler import HelpHandler
        from features.daily_digest_handler import DailyDigestHandler
        from features.birthday_handler import BirthdayHandler
        from features.quote_handler import QuoteHandler
        from features.reminder_handler import ReminderHandler
        from features.memory_handler import MemoryHandler

        self.handlers = {
            "fun": FunHandler(self),
            "utility": UtilityHandler(self),
            "countdown": CountdownHandler(self),
            "polls": PollsHandler(self),
            "calendar": CalendarHandler(self),
            "reminders": ReminderHandler(self),
            "watchlist": WatchlistHandler(self),
            "aurora": AuroraHandler(self),
            "school_holidays": SchoolHolidaysHandler(self),
            "help": HelpHandler(self),
            "daily_digest": DailyDigestHandler(self),
            "profile": __import__('features.profile_handler', fromlist=['ProfileHandler']).ProfileHandler(self),
            "birthdays": BirthdayHandler(self),
            "quotes": QuoteHandler(self),
            "memory": MemoryHandler(self),
        }


class SelfbotClient(discord.Client):
    """Custom Discord client with selfbot functionality"""

    def __init__(
        self, config, auth_handler, rate_limiter, hermes_connector, response_generator
    ):
        # discord.py-self does not expose/use the normal bot Intents API.
        super().__init__(max_messages=10000, self_bot=True)

        self.config = config
        self.auth_handler = auth_handler
        self.rate_limiter = rate_limiter
        self.hermes = hermes_connector
        self.response_gen = response_generator

        self.monitor = None
        self.console_server = None
        self.console_task = None
        self.start_time = None
        self._runtime_lock = asyncio.Lock()

    async def setup_hook(self):
        """Start diagnostics before the Discord session reaches ready."""
        await self.start_console()

    async def _ensure_runtime_started(self):
        """Create and attach the single monitor retained across reconnects."""
        async with self._runtime_lock:
            if self.monitor is None:
                self.monitor = MessageMonitor(
                    client=self,
                    hermes_connector=self.hermes,
                    rate_limiter=self.rate_limiter,
                    response_generator=self.response_gen,
                )
            await self.monitor.setup()
            await self.start_console()
            if self.console_server is not None:
                self.console_server.monitor = self.monitor
            if self.start_time is None:
                self.start_time = datetime.now()
            return self.monitor

    async def start_console(self):
        if self.console_server is not None:
            self.console_server.monitor = self.monitor
            return

        if not getattr(self.config, 'console_enabled', True):
            return

        try:
            self.console_server = ConsoleServer(
                host=self.config.console_host,
                port=self.config.console_port,
                api_key=self.config.console_api_key,
                monitor=self.monitor,
                session_ttl_days=self.config.console_session_ttl_days,
                login_max_attempts=self.config.console_login_max_attempts,
                login_window_seconds=self.config.console_login_window_seconds,
                cookie_secure=self.config.console_cookie_secure,
                auth_mode=self.config.console_auth_mode,
                cloudflare_access_team_domain=self.config.console_cf_access_team_domain,
                cloudflare_access_audiences=self.config.console_cf_access_audiences,
                cloudflare_access_allowed_emails=self.config.console_cf_access_allowed_emails,
            )
            await self.console_server.start()
            print(f"[BOT] Web console started on http://{self.config.console_host}:{self.config.console_port}")
            self._setup_signal_handlers()
        except Exception as e:
            self.console_server = None
            print(f"[BOT] WARNING: Could not start web console: {e}")

    def _get_commit_hash(self):
        """Get short git commit hash from file, git, or fallback to 'unknown'."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        commit_file = os.path.join(project_root, "commit_hash.txt")
        if os.path.exists(commit_file):
            try:
                with open(commit_file, "r") as f:
                    commit = f.read().strip()
                    if commit:
                        print(f"[BOT] Read commit hash from file: {commit}")
                        return commit
            except Exception as e:
                print(f"[BOT] Error reading commit_hash.txt: {e}")

        import shutil
        if not shutil.which("git"):
            print("[BOT] git not found in PATH, cannot determine commit hash")
            return "unknown"

        candidate_dirs = [project_root, os.getcwd(), "/opt/inebotten-discord", "/app"]
        for cwd in candidate_dirs:
            if not os.path.isdir(os.path.join(cwd, ".git")):
                continue
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=cwd,
                )
                if result.returncode == 0:
                    commit = result.stdout.strip()
                    print(f"[BOT] Detected commit hash from git: {commit}")
                    return commit
            except Exception:
                pass

        print("[BOT] No commit hash source found, using 'unknown'")
        return "unknown"

    def _ensure_current_commit_hash(self, current_commit):
        """Refresh commit_hash.txt if git HEAD differs from the startup hash."""
        import shutil

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        git_bin = shutil.which("git")
        if not git_bin:
            print("[BOT] _ensure_current_commit_hash: git binary not found in PATH")
            return current_commit

        git_dir = os.path.join(project_root, ".git")
        if not os.path.isdir(git_dir):
            print(f"[BOT] _ensure_current_commit_hash: no .git directory at {project_root}")
            return current_commit

        try:
            result = subprocess.run(
                [git_bin, "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=project_root,
            )
        except Exception as e:
            print(f"[BOT] _ensure_current_commit_hash: git rev-parse failed: {e}")
            return current_commit

        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"[BOT] _ensure_current_commit_hash: git rev-parse error: {stderr}")
            return current_commit

        git_commit = result.stdout.strip()
        if not git_commit or git_commit == current_commit:
            return current_commit

        print(
            f"[BOT] commit_hash.txt is stale ({current_commit} != {git_commit}), regenerating"
        )

        python_cmd = shutil.which("python3") or sys.executable
        try:
            result = subprocess.run(
                [python_cmd, os.path.join(project_root, "scripts/write_version.py")],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=project_root,
            )
        except Exception as e:
            print(f"[BOT] Could not regenerate commit_hash.txt: {e}")
            return current_commit

        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"[BOT] Could not regenerate commit_hash.txt: {stderr}")
            return current_commit

        stdout = result.stdout.strip()
        if stdout:
            print(f"[BOT] {stdout}")
        return self._get_commit_hash()

    async def on_ready(self):
        """Called when bot is ready"""
        print(f"[BOT] Logged in as {self.user} (ID: {self.user.id})")
        print(f"[BOT] Connected to {len(self.guilds)} guilds")
        print(
            f"[BOT] Rate limit: {self.config.MAX_MSGS_PER_SECOND}/sec, {self.config.DAILY_QUOTA}/day"
        )

        commit = self._get_commit_hash()
        commit = self._ensure_current_commit_hash(commit)
        try:
            await self.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=commit))
            print(f"[BOT] Set activity to: Playing {commit}")
        except Exception as e:
            print(f"[BOT] Could not set activity: {e}")

        await self._ensure_runtime_started()

        # Check AI connector health
        if not self.hermes:
            print("[BOT] WARNING: AI connector missing")
            print("[BOT] Will use local response generator as fallback")
            return

        healthy, message = await self.hermes.check_health()
        if healthy:
            print(f"[BOT] AI connector: {message}")
        else:
            print(f"[BOT] WARNING: AI connector issue - {message}")
            print("[BOT] Will use local response generator as fallback")

    def _setup_signal_handlers(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.close()))
            except (NotImplementedError, RuntimeError):
                pass

    async def on_message(self, message):
        """Called when a message is received"""
        if self.monitor:
            await self.monitor.handle_message(message)

    async def on_disconnect(self):
        """Called when disconnected"""
        print("[BOT] Disconnected from Discord")

    async def on_resumed(self):
        """Called when session is resumed"""
        print("[BOT] Session resumed")

    async def close(self):
        if self.monitor and hasattr(self.monitor, "close"):
            try:
                await self.monitor.close()
            except Exception as e:
                print(f"[BOT] Error stopping monitor tasks: {e}")

        if self.console_task and not self.console_task.done():
            self.console_task.cancel()
            try:
                await self.console_task
            except asyncio.CancelledError:
                pass
            finally:
                self.console_task = None

        if self.console_server:
            try:
                await self.console_server.stop()
                print("[BOT] Web console stopped")
            except Exception as e:
                print(f"[BOT] Error stopping console: {e}")
            finally:
                self.console_server = None
        await super().close()

    def get_uptime(self):
        """Get bot uptime"""
        if self.start_time:
            return datetime.now() - self.start_time
        return None

    def get_full_stats(self):
        """Get comprehensive statistics"""
        stats = {
            "user": str(self.user),
            "user_id": self.user.id if self.user else None,
            "guilds": len(self.guilds),
            "uptime": str(self.get_uptime()),
            "rate_limiter": self.rate_limiter.get_stats(),
            "hermes": self.hermes.get_stats() if self.hermes else {},
        }

        if self.monitor:
            stats["monitor"] = self.monitor.get_stats()

        return stats


def create_monitor(client, hermes_connector, rate_limiter, response_generator):
    """Factory function to create MessageMonitor"""
    return MessageMonitor(client, hermes_connector, rate_limiter, response_generator)
