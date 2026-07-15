#!/usr/bin/env python3
"""
Message Monitor for Discord Selfbot
Polls DMs and detects @inebotten mentions using discord.py
"""

import asyncio
import copy
import inspect
import os
import re
import signal
import subprocess
import sys
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import discord

from ai.chat_contract import (
    ChatTurn,
    HistoryPolicy,
    build_context_prompt,
    capture_history_policy,
    history_policy_for_effective_routes,
    history_safe_content,
)
from cal_system.temporal_resolver import TemporalResolver
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
from core.action_authorization import (
    ClaimedActionAuthorization,
    issue_claimed_action_authorization,
)
from core.intent_models import IntentResult, IntentRisk, IntentSource
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
from core.message_context import (
    RoutingContext,
    conversation_key_from_message,
    domain_scope_id,
    routing_context_from_message,
    strip_leading_bot_invocation,
)
from core.mutation_coordinator import MEMORY_STORE_SCOPE, MutationCoordinator
from core.nlu_metrics import NLUMetrics
from core.pending_actions import (
    PendingAction,
    PendingActionStore,
    PendingBusyError,
    PendingKind,
)
from core.pending_targets import (
    FrozenPendingRoute,
    PendingTargetError,
    PendingTargetResolver,
    conversation_turn_scope,
)
from core.send_receipt import (
    DiscordSendCoordinator,
    _settle_owned_send,
    capture_send_receipt,
    current_send_receipt,
)
from core.utterance import NormalizedUtterance, normalize_utterance
from features.ai_action_handler import (
    AIActionHandler,
    ActionFlowOutcome,
    ConfirmationPreviewTooLarge,
    ModelDisposition,
    PendingPresentationSpec,
    UnsupportedConfirmationSummary,
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
_TRUNCATION_MARKER = "\n\n[svaret er forkortet]"
_SEARCH_CONTEXT_FIELDS = ("title", "href", "url", "body", "snippet")


@dataclass(frozen=True, slots=True)
class RouteProcessOutcome:
    dispatch: DispatchOutcome
    decision_route: IntentResult
    decision_outcome: str


def _validated_search_results(value: object) -> tuple[dict[str, str], ...]:
    """Copy only bounded, display-only fields from search adapters."""

    if not isinstance(value, (list, tuple)):
        return ()
    copied: list[dict[str, str]] = []
    for candidate in value[:5]:
        if not isinstance(candidate, Mapping):
            continue
        item = {
            field: field_value
            for field in _SEARCH_CONTEXT_FIELDS
            if isinstance((field_value := candidate.get(field)), str)
        }
        if item:
            copied.append(item)
    return tuple(copied)


def _bounded_exception_type(exc: BaseException) -> str:
    name = type(exc).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        return name
    return "Exception"


def bounded_discord_text_chunks(
    text: str,
    *,
    max_messages: int = 5,
    max_chars: int = 2000,
) -> tuple[str, ...]:
    """Bound ordinary provider prose to one finite Discord send sequence."""

    if not isinstance(text, str):
        text = str(text)
    if max_messages < 1 or max_chars < 1:
        raise ValueError("invalid_discord_text_bounds")
    total = max_messages * max_chars
    if len(text) > total:
        text = text[: total - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
    return tuple(
        text[index : index + max_chars]
        for index in range(0, len(text), max_chars)
    ) or ("",)


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
        self.nlu_metrics = NLUMetrics()
        self.temporal_resolver = TemporalResolver()
        clock_now = self.reminder_clock.now
        self._reference_time_now = clock_now
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
        self.nlp_parser = NaturalLanguageParser(
            now_provider=clock_now,
            temporal_resolver=self.temporal_resolver,
        )

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
        self.pending_actions = PendingActionStore(
            metrics=self.nlu_metrics,
            now_provider=clock_now,
        )
        self.pending_targets = PendingTargetResolver(
            self,
            coordinator=self.mutation_coordinator,
        )
        self.intent_router = IntentRouter(
            self,
            metrics=self.nlu_metrics,
            pending_actions=self.pending_actions,
            temporal_resolver=self.temporal_resolver,
            now_provider=clock_now,
        )
        self.ai_action_handler = AIActionHandler(
            store=self.pending_actions,
            dispatch_claimed=self._dispatch_claimed_intent,
            metrics=self.nlu_metrics,
            temporal_resolver=self.temporal_resolver,
        )

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
                exception_type = self._mark_task_error(
                    name,
                    exc,
                    state="failed",
                    finished_at=datetime.now().isoformat(),
                )
                print(
                    f"[MONITOR] Background task {name} failed: "
                    f"{exception_type}"
                )
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
        exception_type = _bounded_exception_type(exc)
        self._set_task_health(
            name,
            state=state,
            last_error="background_task_failed",
            exception_type=exception_type,
            last_error_at=datetime.now().isoformat(),
            **extra,
        )
        return exception_type

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
        """Process one authorized input through the single routing owner."""
        if message.author.id == self.client.user.id:
            return

        allowed_users = getattr(self.client.config, "ALLOWED_USERS", [])
        if allowed_users and message.author.id not in allowed_users:
            return

        allowed_channels = getattr(self.client.config, "ALLOWED_CHANNELS", [])
        if allowed_channels and not isinstance(message.channel, discord.DMChannel):
            if message.channel.id not in allowed_channels:
                if not isinstance(message.channel, discord.GroupChannel):
                    return

        authorized_message = self.authorize_message(message)
        if not authorized_message:
            return

        msg_id = f"{message.channel.id}:{message.id}"
        if msg_id in self.processed_messages:
            return
        self.processed_messages.append(msg_id)

        message = authorized_message
        can_send = getattr(self.rate_limiter, "can_send", None)
        try:
            admission = can_send() if callable(can_send) else None
        except Exception:
            admission = None
        if (
            not isinstance(admission, tuple)
            or len(admission) != 2
            or admission[0] is not True
        ):
            record_dropped = getattr(
                self.rate_limiter,
                "record_dropped",
                None,
            )
            if callable(record_dropped):
                record_dropped()
            reason = (
                admission[1]
                if isinstance(admission, tuple) and len(admission) == 2
                else "rate_limiter_unavailable"
            )
            print(f"[MONITOR] Turn rejected before routing: {reason}")
            return
        routing_context = routing_context_from_message(
            message,
            bot_user_id=self.client.user.id,
        )
        key = routing_context.key
        self.mention_count += 1
        print(
            "[MONITOR] Authorized mention admitted in "
            f"{self._get_channel_type(message.channel)}"
        )

        async with self.mutation_coordinator.hold(
            conversation_turn_scope(key)
        ):
            route: IntentResult | None = None
            decision_recorded = False
            history_policy = HistoryPolicy.REDACT_AUTH
            with capture_send_receipt() as receipt:
                try:
                    lang = self.loc.detect_language(message.content)
                    self.loc.set_language(lang)
                    print(f"[MONITOR] Detected language: {lang}")
                    reference_time = self._reference_time_now()
                    visible_content = strip_leading_bot_invocation(
                        message.raw_content,
                        bot_user_id=self.client.user.id,
                    )
                    utterance = normalize_utterance(visible_content)
                    route = self.intent_router.route_utterance(
                        utterance,
                        guild_id=key.guild_id,
                        channel_id=key.channel_id,
                        user_id=key.user_id,
                        routing_context=routing_context,
                        reference_time=reference_time,
                    )
                    print(
                        f"[MONITOR] Intent matched: {route.intent.value} "
                        f"({route.reason}, {route.confidence:.2f})"
                    )
                    try:
                        effective_routes = (
                            self.pending_actions.effective_routes_for_history(
                                key,
                                route,
                            )
                        )
                    except Exception:
                        effective_routes = None
                    history_policy = history_policy_for_effective_routes(
                        effective_routes
                    )
                    with capture_history_policy(history_policy):
                        add_turn = getattr(
                            self.conversation,
                            "add_turn",
                            None,
                        )
                        if callable(add_turn):
                            try:
                                add_turn(
                                    key,
                                    ChatTurn(
                                        "user",
                                        history_safe_content(utterance.raw),
                                        source_message_id=message.id,
                                    ),
                                )
                            except Exception:
                                print(
                                    "[MONITOR] Inbound conversation "
                                    "recording degraded"
                                )
                        processed = await self._process_route(
                            message,
                            utterance=utterance,
                            routing_context=routing_context,
                            route=route,
                            reference_time=reference_time,
                        )
                    self.nlu_metrics.record_decision(
                        intent=processed.decision_route.intent,
                        source=processed.decision_route.source,
                        outcome=processed.decision_outcome,
                    )
                    decision_recorded = True
                    self.intent_stats[
                        processed.decision_route.intent.value
                    ]["count"] += 1
                    return processed.dispatch
                except DispatchCancelled as exc:
                    if not decision_recorded:
                        cancelled_route = (
                            exc.decision_route
                            if isinstance(exc.decision_route, IntentResult)
                            else (
                                route
                                if isinstance(route, IntentResult)
                                else None
                            )
                        )
                        cancelled_outcome = (
                            exc.decision_outcome
                            if isinstance(exc.decision_outcome, str)
                            and exc.decision_outcome
                            else (
                                "executed" if exc.outcome.ok else "failed"
                            )
                        )
                    else:
                        cancelled_route = None
                        cancelled_outcome = "failed"
                    if cancelled_route is not None:
                        self.nlu_metrics.record_decision(
                            intent=cancelled_route.intent,
                            source=cancelled_route.source,
                            outcome=cancelled_outcome,
                        )
                    raise
                except asyncio.CancelledError:
                    if (
                        isinstance(route, IntentResult)
                        and not decision_recorded
                    ):
                        self.nlu_metrics.record_decision(
                            intent=route.intent,
                            source=route.source,
                            outcome="failed",
                        )
                    raise
                except Exception as exc:
                    valid_route = (
                        route if isinstance(route, IntentResult) else None
                    )
                    route_name = (
                        valid_route.intent.value
                        if valid_route is not None
                        else "unknown"
                    )
                    print(
                        f"[MONITOR] ERROR handling intent {route_name}: "
                        f"{type(exc).__name__}"
                    )
                    self.error_count += 1
                    self.intent_stats[route_name]["errors"] += 1
                    decision_route = valid_route or IntentResult(
                        BotIntent.AI_CHAT,
                        0.0,
                        reason="turn_exception",
                    )
                    if not decision_recorded:
                        self.nlu_metrics.record_decision(
                            intent=decision_route.intent,
                            source=decision_route.source,
                            outcome="failed",
                        )
                    base = DispatchOutcome.failure(
                        "turn_exception",
                        retryable=False,
                        commit_unknown=(
                            valid_route is not None
                            and valid_route.risk is not IntentRisk.READ_ONLY
                        ),
                    )
                    if receipt.result is not None:
                        return base.with_delivery(receipt.result)
                    try:
                        with capture_history_policy(history_policy):
                            send = await self._send_text_sequence_result(
                                message,
                                "Beklager, noe gikk galt. Jeg prøver ikke "
                                "handlingen automatisk på nytt.",
                            )
                    except MessageSendCancelled as cancelled:
                        raise DispatchCancelled(
                            base.with_delivery(cancelled.result),
                            decision_route=decision_route,
                            decision_outcome="failed",
                        ) from cancelled
                    return base.with_delivery(send)

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

    async def _send_presentation_chunk(
        self,
        message,
        text: str,
    ) -> tuple[MessageSendResult, asyncio.CancelledError | None]:
        task = asyncio.create_task(self._send_response_result(message, text))
        cancellation: asyncio.CancelledError | None = None
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError as cancelled:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    cancellation = cancellation or cancelled
                    current.uncancel()
                if task.done():
                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        result = MessageSendResult(
                            DeliveryState.UNKNOWN,
                            "send_task_cancelled",
                        )
                    except Exception:
                        result = MessageSendResult(
                            DeliveryState.UNKNOWN,
                            "send_task_exception",
                        )
                    break
                cancellation = cancellation or cancelled
                continue
            except Exception:
                result = MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "send_task_exception",
                )
                break
        assert task.done()
        return result, cancellation

    async def _present_pending(
        self,
        message,
        spec: PendingPresentationSpec,
        *,
        cancellation_route: IntentResult,
        cancellation_success_outcome: str,
    ) -> RouteProcessOutcome:
        key = conversation_key_from_message(message)
        async with self.mutation_coordinator.hold(conversation_turn_scope(key)):
            try:
                if spec.correction_action_id is not None:
                    token = self.pending_actions.begin_correction(
                        key,
                        spec.correction_action_id,
                        spec.routes[0],
                        spec.summary,
                        target_guard=spec.target_guards[0],
                    )
                    if token is None:
                        return RouteProcessOutcome(
                            DispatchOutcome.failure("stale_correction"),
                            cancellation_route,
                            "failed",
                        )
                elif spec.kind is PendingKind.CHOICE:
                    token = self.pending_actions.begin_choices(
                        key,
                        spec.routes,
                        spec.summary,
                        target_guards=spec.target_guards,
                    )
                else:
                    token = self.pending_actions.begin_confirmation(
                        key,
                        spec.routes[0],
                        spec.summary,
                        target_guard=spec.target_guards[0],
                    )
            except PendingBusyError:
                return RouteProcessOutcome(
                    DispatchOutcome.failure("pending_action_busy"),
                    cancellation_route,
                    "failed",
                )

            delivered = 0
            activated = None
            final_result = MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "empty",
            )
            cancellation: asyncio.CancelledError | None = None
            for chunk in spec.messages:
                final_result, cancellation = (
                    await self._send_presentation_chunk(message, chunk)
                )
                if final_result.state is DeliveryState.DELIVERED:
                    delivered += 1
                if (
                    final_result.state is not DeliveryState.DELIVERED
                    or cancellation is not None
                ):
                    break

            if delivered == len(spec.messages):
                activated = self.pending_actions.activate_presentation(token)
                if activated is None:
                    final_result = MessageSendResult(
                        DeliveryState.UNKNOWN,
                        "partial_send",
                    )
                    self.pending_actions.abort_presentation(
                        token,
                        safe_to_restore_previous=False,
                    )
            else:
                self.pending_actions.abort_presentation(
                    token,
                    safe_to_restore_previous=(
                        delivered == 0
                        and final_result.state is DeliveryState.NOT_DELIVERED
                    ),
                )

            if cancellation is not None:
                cancellation_result = (
                    final_result
                    if activated is not None
                    else (
                        MessageSendResult(DeliveryState.UNKNOWN, "partial_send")
                        if delivered > 0
                        else final_result
                    )
                )
                cancellation_base = (
                    DispatchOutcome.success()
                    if activated is not None
                    else DispatchOutcome.failure(
                        "presentation_cancelled",
                        retryable=False,
                    )
                )
                raise DispatchCancelled(
                    cancellation_base.with_delivery(cancellation_result),
                    decision_route=cancellation_route,
                    decision_outcome=(
                        cancellation_success_outcome
                        if activated is not None
                        else "failed"
                    ),
                ) from cancellation
            if delivered == len(spec.messages) and activated is not None:
                return RouteProcessOutcome(
                    DispatchOutcome.success().with_delivery(final_result),
                    cancellation_route,
                    cancellation_success_outcome,
                )
            code = (
                "confirmation_delivery_unknown"
                if final_result.state is DeliveryState.UNKNOWN
                else (
                    "partial_confirmation_preview"
                    if delivered
                    else "confirmation_send_failed"
                )
            )
            sequence_result = (
                MessageSendResult(DeliveryState.UNKNOWN, "partial_send")
                if delivered > 0
                else final_result
            )
            return RouteProcessOutcome(
                DispatchOutcome.failure(
                    code,
                    retryable=False,
                ).with_delivery(sequence_result),
                cancellation_route,
                "failed",
            )

    async def _send_flow_outcome(
        self,
        message,
        outcome: ActionFlowOutcome,
        *,
        fallback_route: IntentResult,
        fallback_outcome: str = "failed",
    ) -> RouteProcessOutcome:
        if outcome.presentation is not None:
            presented = await self._present_pending(
                message,
                outcome.presentation,
                cancellation_route=(
                    outcome.decision_route
                    or fallback_route
                ),
                cancellation_success_outcome=(
                    outcome.decision_outcome or "staged"
                ),
            )
            return presented
        if (
            outcome.dispatch is not None
            and outcome.dispatch.delivery_result is not None
        ):
            dispatch = outcome.dispatch
        elif outcome.text:
            try:
                send = await self._send_text_sequence_result(
                    message,
                    outcome.text,
                )
            except MessageSendCancelled as exc:
                if outcome.dispatch is not None:
                    cancellation_base = outcome.dispatch
                elif exc.result.state is DeliveryState.DELIVERED:
                    cancellation_base = DispatchOutcome.success()
                else:
                    cancellation_base = DispatchOutcome.failure(
                        "response_delivery_unknown"
                        if exc.result.state is DeliveryState.UNKNOWN
                        else "response_send_failed",
                        retryable=False,
                    )
                cancellation_dispatch = cancellation_base.with_delivery(
                    exc.result
                )
                decision_outcome = outcome.decision_outcome
                if not decision_outcome:
                    decision_outcome = (
                        fallback_outcome
                        if fallback_outcome != "failed"
                        or not cancellation_dispatch.ok
                        else "executed"
                    )
                raise DispatchCancelled(
                    cancellation_dispatch,
                    decision_route=(
                        outcome.decision_route or fallback_route
                    ),
                    decision_outcome=decision_outcome,
                ) from exc
            if outcome.dispatch is not None:
                dispatch = outcome.dispatch.with_delivery(send)
            elif send.state is DeliveryState.DELIVERED:
                dispatch = DispatchOutcome.success().with_delivery(send)
            else:
                dispatch = DispatchOutcome.failure(
                    "response_delivery_unknown"
                    if send.state is DeliveryState.UNKNOWN
                    else "response_send_failed",
                    retryable=False,
                ).with_delivery(send)
        else:
            dispatch = outcome.dispatch or DispatchOutcome.failure(
                "empty_action_outcome",
                retryable=False,
            )
        return RouteProcessOutcome(
            dispatch=dispatch,
            decision_route=outcome.decision_route or fallback_route,
            decision_outcome=outcome.decision_outcome or fallback_outcome,
        )

    async def _send_route_text(
        self,
        message,
        text: str,
        route: IntentResult,
        success_outcome: str,
    ) -> RouteProcessOutcome:
        try:
            send = await self._send_text_sequence_result(message, text)
        except MessageSendCancelled as exc:
            if exc.result.state is DeliveryState.DELIVERED:
                base = DispatchOutcome.success()
                decision_outcome = success_outcome
            else:
                base = DispatchOutcome.failure(
                    "response_delivery_unknown"
                    if exc.result.state is DeliveryState.UNKNOWN
                    else "response_send_failed",
                    retryable=False,
                )
                decision_outcome = "failed"
            raise DispatchCancelled(
                base.with_delivery(exc.result),
                decision_route=route,
                decision_outcome=decision_outcome,
            ) from exc
        if send.state is DeliveryState.DELIVERED:
            return RouteProcessOutcome(
                DispatchOutcome.success().with_delivery(send),
                route,
                success_outcome,
            )
        return RouteProcessOutcome(
            DispatchOutcome.failure(
                "response_delivery_unknown"
                if send.state is DeliveryState.UNKNOWN
                else "response_send_failed",
                retryable=False,
            ).with_delivery(send),
            route,
            "failed",
        )

    async def _process_route(
        self,
        message,
        *,
        utterance: NormalizedUtterance,
        routing_context: RoutingContext,
        route: IntentResult,
        reference_time: datetime,
        visible_text: str = "",
        model_origin: bool = False,
        pre_frozen: FrozenPendingRoute | None = None,
        selected_interpretation: bool = False,
    ) -> RouteProcessOutcome:
        """Keep cancellation and failure bound to the effective inner route."""

        receipt = current_send_receipt()
        if receipt is None:
            # Production turns already own a task-local receipt.  Keep direct
            # internal calls equally safe without forcing every caller to know
            # about delivery bookkeeping.
            with capture_send_receipt():
                return await self._process_route(
                    message,
                    utterance=utterance,
                    routing_context=routing_context,
                    route=route,
                    reference_time=reference_time,
                    visible_text=visible_text,
                    model_origin=model_origin,
                    pre_frozen=pre_frozen,
                    selected_interpretation=selected_interpretation,
                )

        try:
            return await self._process_route_impl(
                message,
                utterance=utterance,
                routing_context=routing_context,
                route=route,
                reference_time=reference_time,
                visible_text=visible_text,
                model_origin=model_origin,
                pre_frozen=pre_frozen,
                selected_interpretation=selected_interpretation,
            )
        except DispatchCancelled as exc:
            raise DispatchCancelled(
                exc.outcome,
                decision_route=(
                    exc.decision_route
                    if isinstance(exc.decision_route, IntentResult)
                    else route
                ),
                decision_outcome=(
                    exc.decision_outcome
                    if isinstance(exc.decision_outcome, str)
                    and exc.decision_outcome
                    else ("executed" if exc.outcome.ok else "failed")
                ),
            ) from exc
        except MessageSendCancelled as exc:
            base = DispatchOutcome.failure(
                "response_delivery_unknown"
                if exc.result.state is DeliveryState.UNKNOWN
                else "response_send_failed",
                retryable=False,
                commit_unknown=(
                    route.risk is not IntentRisk.READ_ONLY
                    and not route.requires_confirmation
                ),
            ).with_delivery(exc.result)
            raise DispatchCancelled(
                base,
                decision_route=route,
                decision_outcome="failed",
            ) from exc
        except asyncio.CancelledError as exc:
            raise DispatchCancelled(
                DispatchOutcome.failure(
                    "cancelled",
                    retryable=False,
                    commit_unknown=(
                        route.risk is not IntentRisk.READ_ONLY
                        and not route.requires_confirmation
                    ),
                ),
                decision_route=route,
                decision_outcome="failed",
            ) from exc
        except Exception as exc:
            print(
                f"[MONITOR] ERROR processing effective route "
                f"{route.intent.value}: {type(exc).__name__}"
            )
            self.error_count += 1
            self.intent_stats[route.intent.value]["errors"] += 1
            base = DispatchOutcome.failure(
                "turn_exception",
                retryable=False,
                commit_unknown=(
                    route.risk is not IntentRisk.READ_ONLY
                    and not route.requires_confirmation
                ),
            )
            if receipt.result is not None:
                # A handler may fail after its one Discord attempt.  Preserve
                # that terminal delivery truth; never replay an apology after
                # DELIVERED or UNKNOWN.
                return RouteProcessOutcome(
                    base.with_delivery(receipt.result),
                    route,
                    "failed",
                )
            try:
                send = await self._send_text_sequence_result(
                    message,
                    "Beklager, noe gikk galt. Jeg prøver ikke handlingen "
                    "automatisk på nytt.",
                )
            except MessageSendCancelled as cancelled:
                raise DispatchCancelled(
                    base.with_delivery(cancelled.result),
                    decision_route=route,
                    decision_outcome="failed",
                ) from cancelled
            return RouteProcessOutcome(
                base.with_delivery(send),
                route,
                "failed",
            )

    async def _process_route_impl(
        self,
        message,
        *,
        utterance: NormalizedUtterance,
        routing_context: RoutingContext,
        route: IntentResult,
        reference_time: datetime,
        visible_text: str = "",
        model_origin: bool = False,
        pre_frozen: FrozenPendingRoute | None = None,
        selected_interpretation: bool = False,
    ) -> RouteProcessOutcome:
        if selected_interpretation:
            if pre_frozen is None or pre_frozen.route != route:
                return RouteProcessOutcome(
                    DispatchOutcome.failure(
                        "missing_frozen_choice",
                        retryable=False,
                    ),
                    route,
                    "failed",
                )
            route = replace(
                route,
                reason=f"user_selected:{route.reason}",
                requires_confirmation=(
                    route.requires_confirmation
                    or route.risk is not IntentRisk.READ_ONLY
                ),
            )
            pre_frozen = FrozenPendingRoute(route, pre_frozen.guard)

        if (
            not selected_interpretation
            and not self._passes_intent_threshold(route)
        ):
            if model_origin:
                text = visible_text or (
                    "Jeg er ikke sikker nok til å foreslå handlingen."
                )
                return await self._send_route_text(
                    message,
                    text,
                    route,
                    "low_confidence",
                )
            return await self._send_ai_response(
                message,
                utterance=utterance,
                routing_context=routing_context,
                routed_intent=route,
                reference_time=reference_time,
                semantic_action_allowed=True,
            )

        if route.requires_confirmation:
            try:
                if pre_frozen is None:
                    async with self.pending_targets.mutation_context(
                        route,
                        routing_context.key,
                    ):
                        frozen = self.pending_targets.freeze(
                            route,
                            routing_context,
                            reference_time=reference_time,
                        )
                else:
                    frozen = pre_frozen
                staged = self.ai_action_handler.prepare_confirmation(
                    message,
                    frozen.route,
                    prefix=visible_text,
                    target_guard=frozen.guard,
                )
            except (
                PendingTargetError,
                UnsupportedConfirmationSummary,
                ConfirmationPreviewTooLarge,
            ) as exc:
                code = getattr(
                    exc,
                    "code",
                    "unsupported_confirmation_summary",
                )
                base = DispatchOutcome.failure(
                    code,
                    retryable=False,
                )
                try:
                    send = await self._send_text_sequence_result(
                        message,
                        "Jeg kan ikke vise en full og entydig "
                        "bekreftelse. Kort ned eller presiser handlingen.",
                    )
                except MessageSendCancelled as cancelled:
                    raise DispatchCancelled(
                        base.with_delivery(cancelled.result),
                        decision_route=route,
                        decision_outcome="failed",
                    ) from cancelled
                return RouteProcessOutcome(
                    base.with_delivery(send),
                    route,
                    "failed",
                )
            return await self._send_flow_outcome(
                message,
                staged,
                fallback_route=frozen.route,
            )

        if (
            route.intent is BotIntent.AI_CHAT
            and route.reason == "unsafe_mutation_blocked"
        ):
            return await self._send_route_text(
                message,
                "Jeg utfører ikke en negert, sitert eller hypotetisk handling.",
                route,
                "blocked",
            )
        if route.intent is BotIntent.AI_CHAT:
            return await self._send_ai_response(
                message,
                utterance=utterance,
                routing_context=routing_context,
                routed_intent=route,
                reference_time=reference_time,
                semantic_action_allowed=True,
            )
        if route.intent is BotIntent.SEARCH:
            return await self._send_ai_response(
                message,
                utterance=utterance,
                routing_context=routing_context,
                routed_intent=route,
                reference_time=reference_time,
                semantic_action_allowed=False,
                forced_search_info=route.payload.get("search"),
            )

        if route.intent is BotIntent.CLARIFY:
            choices = route.payload.get("choices", ())
            if choices:
                frozen_choices: list[FrozenPendingRoute] = []
                try:
                    for choice in choices:
                        if not isinstance(choice, IntentResult):
                            raise ValueError("invalid_choice")
                        if choice.risk is IntentRisk.READ_ONLY:
                            frozen_choices.append(
                                FrozenPendingRoute(
                                    copy.deepcopy(choice),
                                    None,
                                )
                            )
                            continue
                        async with self.pending_targets.mutation_context(
                            choice,
                            routing_context.key,
                        ):
                            frozen_choices.append(
                                self.pending_targets.freeze(
                                    choice,
                                    routing_context,
                                    reference_time=reference_time,
                                )
                            )
                    prepared = self.ai_action_handler.prepare_choices(
                        message,
                        tuple(item.route for item in frozen_choices),
                        tuple(item.guard for item in frozen_choices),
                        route.payload.get(
                            "clarification",
                            "Velg ett alternativ.",
                        ),
                    )
                except (
                    PendingTargetError,
                    ConfirmationPreviewTooLarge,
                    ValueError,
                ) as exc:
                    base = DispatchOutcome.failure(
                        getattr(exc, "code", "ambiguous_choice"),
                        retryable=False,
                    )
                    try:
                        send = await self._send_text_sequence_result(
                            message,
                            "Jeg kan ikke fryse alle alternativene "
                            "entydig. Beskriv ønsket handling på nytt.",
                        )
                    except MessageSendCancelled as cancelled:
                        raise DispatchCancelled(
                            base.with_delivery(cancelled.result),
                            decision_route=route,
                            decision_outcome="failed",
                        ) from cancelled
                    return RouteProcessOutcome(
                        base.with_delivery(send),
                        route,
                        "failed",
                    )
                return await self._send_flow_outcome(
                    message,
                    prepared,
                    fallback_route=route,
                    fallback_outcome="clarified",
                )
            return await self._send_route_text(
                message,
                route.payload.get(
                    "clarification",
                    visible_text or "Kan du presisere?",
                ),
                route,
                "clarified",
            )

        pending = route.payload.get("pending", {})
        if route.intent is BotIntent.ACTION_CONFIRM:
            outcome = await self.ai_action_handler.confirm(
                message,
                str(pending["action_id"]),
                reference_time=reference_time,
            )
            return await self._send_flow_outcome(
                message,
                outcome,
                fallback_route=route,
            )
        if route.intent is BotIntent.ACTION_CANCEL:
            outcome = await self.ai_action_handler.cancel(
                message,
                str(pending["action_id"]),
            )
            return await self._send_flow_outcome(
                message,
                outcome,
                fallback_route=route,
            )
        if route.intent is BotIntent.ACTION_SELECT:
            outcome = await self.ai_action_handler.select(
                message,
                str(pending["action_id"]),
                int(pending["choice_index"]),
            )
            if outcome.route is not None:
                return await self._process_route(
                    message,
                    utterance=utterance,
                    routing_context=routing_context,
                    route=outcome.route,
                    reference_time=reference_time,
                    pre_frozen=FrozenPendingRoute(
                        outcome.route,
                        outcome.target_guard,
                    ),
                    selected_interpretation=True,
                )
            return await self._send_flow_outcome(
                message,
                outcome,
                fallback_route=route,
            )
        if route.intent is BotIntent.ACTION_CORRECT:
            correction_pending = self.pending_actions.peek(
                routing_context.key
            )
            outcome = await self.ai_action_handler.correct(
                message,
                str(pending["action_id"]),
                utterance,
                reference_time=reference_time,
            )
            if (
                outcome.presentation is not None
                and correction_pending is not None
                and len(correction_pending.routes) == 1
                and len(outcome.presentation.routes) == 1
                and outcome.presentation.target_guards[0] is not None
            ):
                try:
                    rebound_guard = self.pending_targets.rebind_corrected(
                        correction_pending.routes[0],
                        outcome.presentation.routes[0],
                        outcome.presentation.target_guards[0],
                    )
                except PendingTargetError:
                    outcome = ActionFlowOutcome(
                        text=(
                            "Jeg kunne ikke bevare det valgte målet trygt. "
                            "Be om handlingen på nytt."
                        ),
                        decision_route=correction_pending.routes[0],
                        decision_outcome="failed",
                    )
                else:
                    outcome = replace(
                        outcome,
                        presentation=replace(
                            outcome.presentation,
                            target_guards=(rebound_guard,),
                        ),
                    )
            return await self._send_flow_outcome(
                message,
                outcome,
                fallback_route=route,
            )

        try:
            dispatch = await self._handle_intent(
                message,
                route,
                reference_time=reference_time,
            )
        except DispatchCancelled as exc:
            raise DispatchCancelled(
                exc.outcome,
                decision_route=(
                    exc.decision_route
                    if isinstance(exc.decision_route, IntentResult)
                    else route
                ),
                decision_outcome=(
                    exc.decision_outcome
                    if isinstance(exc.decision_outcome, str)
                    and exc.decision_outcome
                    else ("executed" if exc.outcome.ok else "failed")
                ),
            ) from exc
        except MessageSendCancelled as exc:
            if route.risk is IntentRisk.READ_ONLY:
                if exc.result.state is DeliveryState.DELIVERED:
                    cancellation_dispatch = DispatchOutcome.success()
                else:
                    cancellation_dispatch = DispatchOutcome.failure(
                        "response_delivery_unknown"
                        if exc.result.state is DeliveryState.UNKNOWN
                        else "response_send_failed",
                        retryable=False,
                    )
            else:
                cancellation_dispatch = DispatchOutcome.failure(
                    "commit_state_unknown",
                    retryable=False,
                    commit_unknown=True,
                )
            cancellation_dispatch = cancellation_dispatch.with_delivery(
                exc.result
            )
            raise DispatchCancelled(
                cancellation_dispatch,
                decision_route=route,
                decision_outcome=(
                    "executed" if cancellation_dispatch.ok else "failed"
                ),
            ) from exc
        if dispatch.delivery_result is None:
            if dispatch.ok:
                fallback = "Handlingen ble utført."
            elif dispatch.mutated or dispatch.commit_unknown:
                fallback = (
                    "Utfallet er usikkert etter at data kan ha blitt endret. "
                    "Jeg prøver ikke automatisk igjen."
                )
            else:
                fallback = "Handlingen kunne ikke utføres."
            try:
                send = await self._send_text_sequence_result(
                    message,
                    fallback,
                )
            except MessageSendCancelled as exc:
                cancellation_dispatch = dispatch.with_delivery(exc.result)
                raise DispatchCancelled(
                    cancellation_dispatch,
                    decision_route=route,
                    decision_outcome=(
                        "executed" if dispatch.ok else "failed"
                    ),
                ) from exc
            dispatch = dispatch.with_delivery(send)
        final = "executed" if dispatch.ok else "failed"
        return RouteProcessOutcome(dispatch, route, final)

    def _passes_intent_threshold(self, route: IntentResult) -> bool:
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        if route.confidence >= threshold:
            return True
        self.intent_stats[route.intent.value]["low_confidence"] += 1
        return False

    async def _dispatch_claimed_intent(
        self,
        message,
        pending: PendingAction,
        reference_time: datetime,
    ) -> DispatchOutcome:
        key = conversation_key_from_message(message)
        if not self.pending_actions.is_executing(key, pending):
            return DispatchOutcome.failure(
                "invalid_pending_claim",
                retryable=False,
            )
        route = pending.routes[0]
        try:
            mutation_context = self.pending_targets.mutation_context(
                route,
                key,
            )
        except PendingTargetError as exc:
            return DispatchOutcome.failure(exc.code, retryable=False)
        except ValueError:
            return DispatchOutcome.failure(
                "invalid_pending_claim",
                retryable=False,
            )

        async with mutation_context:
            if not self.pending_actions.is_executing(key, pending):
                return DispatchOutcome.failure(
                    "invalid_pending_claim",
                    retryable=False,
                )
            try:
                rebound = self.pending_targets.revalidate(
                    route,
                    pending.target_guards[0],
                    routing_context_from_message(
                        message,
                        bot_user_id=self.client.user.id,
                    ),
                    reference_time=reference_time,
                )
                confirmed = replace(
                    rebound,
                    requires_confirmation=False,
                )
                authorization = (
                    issue_claimed_action_authorization(
                        key=key,
                        action_id=pending.action_id,
                        claim_id=pending.claim_id,
                        pending_actions=self.pending_actions,
                    )
                    if confirmed.intent is BotIntent.MEMORY_DELETE
                    else None
                )
            except PendingTargetError as exc:
                return DispatchOutcome.failure(exc.code, retryable=False)
            except ValueError:
                return DispatchOutcome.failure(
                    "invalid_pending_claim",
                    retryable=False,
                )
            return await self._dispatch_intent_body(
                message,
                confirmed,
                authorization=authorization,
                reference_time=reference_time,
            )

    async def _handle_intent(
        self,
        message,
        route: IntentResult,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Dispatch an accepted route under its backing-store scope."""

        if route.requires_confirmation:
            return DispatchOutcome.failure(
                "confirmation_required",
                retryable=False,
            )
        if route.risk is IntentRisk.READ_ONLY:
            return await self._dispatch_intent_body(
                message,
                route,
                reference_time=reference_time,
            )
        key = conversation_key_from_message(message)
        routing = routing_context_from_message(
            message,
            bot_user_id=self.client.user.id,
        )
        try:
            frozen = self.pending_targets.freeze(
                route,
                routing,
                reference_time=reference_time,
            )
            async with self.pending_targets.mutation_context(frozen.route, key):
                rebound = self.pending_targets.revalidate(
                    frozen.route,
                    frozen.guard,
                    routing,
                    reference_time=reference_time,
                )
                return await self._dispatch_intent_body(
                    message,
                    rebound,
                    reference_time=reference_time,
                )
        except PendingTargetError as exc:
            return DispatchOutcome.failure(exc.code, retryable=False)

    async def _dispatch_intent_body(
        self,
        message,
        route: IntentResult,
        *,
        reference_time: datetime,
        authorization: ClaimedActionAuthorization | None = None,
    ) -> DispatchOutcome:
        """Execute one validated route without routing or confirmation logic."""
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

        if route.intent == BotIntent.HELP:
            return await self._invoke_legacy_read(
                lambda: self.handlers["help"].handle_help(message)
            )
        elif route.intent == BotIntent.CALENDAR_HELP:
            return await self._invoke_legacy_read(
                lambda: self._send_text_sequence_result(
                    message,
                    self.conv_gen.get_calendar_help(),
                )
            )
        elif route.intent == BotIntent.STATUS:
            return await self._invoke_legacy_read(
                lambda: self._send_status_response(message)
            )
        elif route.intent == BotIntent.PROFILE:
            return await self._invoke_legacy_read(
                lambda: self.handlers["profile"].handle_profile_command(
                    message
                )
            )
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
        elif route.intent in (
            BotIntent.MEMORY_VIEW,
            BotIntent.MEMORY_EXPORT,
            BotIntent.MEMORY_DELETE,
        ):
            return await self.handlers["memory"].handle_memory(
                message,
                typed_payload,
                authorization=authorization,
            )
        elif route.intent == BotIntent.DASHBOARD:
            return await self._invoke_legacy_read(
                lambda: self._send_dashboard_response(
                    message,
                    reference_time=reference_time,
                )
            )
        return DispatchOutcome.failure(
            "unsupported_dispatch_intent",
            retryable=False,
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
        await self._send_text_sequence_result(message, response_text)

    async def _send_ai_response(
        self,
        message,
        *,
        utterance: NormalizedUtterance,
        routing_context: RoutingContext,
        routed_intent: IntentResult,
        reference_time: datetime,
        semantic_action_allowed: bool,
        forced_search_info: dict[str, str] | None = None,
    ) -> RouteProcessOutcome:
        """Generate prose or one typed proposal without inline execution."""

        print("[MONITOR] AI response requested")
        channel_type = self._get_channel_type(message.channel)
        try:
            conversation_topic = self.conversation.get_conversation_summary(
                routing_context.key
            )
        except Exception as exc:
            conversation_topic = None
            print(
                "[MONITOR] Conversation summary degraded: "
                f"{_bounded_exception_type(exc)}"
            )
        update_interaction = getattr(
            self.user_memory,
            "update_last_interaction_result",
            None,
        )
        if callable(update_interaction):
            try:
                await update_interaction(
                    routing_context.author.user_id,
                    reference_time=reference_time,
                    topic=conversation_topic,
                    username=routing_context.author.display_name,
                )
            except ManagerMutationError as exc:
                code = (
                    exc.code
                    if exc.code
                    in {
                        "storage_write_failed",
                        "commit_state_unknown",
                    }
                    else "commit_state_unknown"
                )
                print(
                    "[MONITOR] User-memory update degraded: "
                    f"{code}"
                )
            except Exception as exc:
                print(
                    "[MONITOR] User-memory update degraded: "
                    f"{_bounded_exception_type(exc)}"
                )
        search_was_requested = forced_search_info is not None
        search_context: dict[str, object] = {
            "requested": search_was_requested,
            "status": "not_requested",
            "results": (),
        }

        if forced_search_info is not None:
            query_value = (
                forced_search_info.get("query", "")
                if isinstance(forced_search_info, Mapping)
                else ""
            )
            query = query_value if isinstance(query_value, str) else ""
            type_value = (
                forced_search_info.get("type", "web")
                if isinstance(forced_search_info, Mapping)
                else "web"
            )
            search_type = "news" if type_value == "news" else "web"
            search_context = {
                "requested": True,
                "query": query,
                "type": search_type,
                "status": "no_results",
                "results": (),
            }
            try:
                if search_type == "news":
                    raw_search_results = await self.search_manager.get_news(
                        query
                    )
                else:
                    raw_search_results = await self.search_manager.search(query)
                search_results = _validated_search_results(raw_search_results)
                if search_results:
                    search_context["status"] = "ok"
                    search_context["results"] = search_results
                    has_deep_content = any(
                        len(result.get("body", "")) > 500
                        for result in search_results
                    )
                    if (
                        not has_deep_content
                        and self.browser_manager.is_configured()
                    ):
                        top_url = search_results[0].get(
                            "href"
                        ) or search_results[0].get("url")
                        if top_url:
                            page_content = (
                                await self.browser_manager.fetch_page_content(
                                    top_url
                                )
                            )
                            if page_content:
                                search_context["fetched_page"] = {
                                    "url": top_url,
                                    "content": page_content,
                                }
            except Exception as exc:
                search_context["status"] = "degraded"
                search_context["results"] = ()
                print(
                    "[MONITOR] Search context degraded: "
                    f"{type(exc).__name__}"
                )

        from ai.personality_config import get_fallback_response

        if not self.hermes:
            return await self._send_route_text(
                message,
                get_fallback_response("general"),
                routed_intent,
                "failed",
            )

        try:
            snapshot = self.user_memory.snapshot_user(message.author.id)
            user_snapshot = (
                copy.deepcopy(snapshot)
                if isinstance(snapshot, Mapping)
                else {}
            )
        except Exception:
            user_snapshot = {}

        context_data = {
            "author": {
                "id": routing_context.author.user_id,
                "display_name": routing_context.author.display_name,
            },
            "channel_type": channel_type,
            "user_memory": user_snapshot,
            "search": search_context,
        }
        try:
            context_prompt = build_context_prompt(context_data)
        except Exception:
            print("[MONITOR] Untrusted context serialization degraded")
            context_prompt = build_context_prompt(
                {"context_unavailable": True}
            )

        get_prompt_history = getattr(
            self.conversation,
            "get_prompt_history",
            None,
        )
        try:
            history = (
                get_prompt_history(
                    routing_context.key,
                    limit=10,
                    exclude_source_message_id=message.id,
                )
                if callable(get_prompt_history)
                else ()
            )
        except Exception:
            print("[MONITOR] Conversation history retrieval degraded")
            history = ()

        system_prompt = self.get_system_prompt(
            style=self.ResponseStyle.CASUAL,
            routed_intent=routed_intent.intent,
            reference_time=reference_time,
        )

        try:
            success, ai_response = await self.hermes.generate_response(
                message_content=utterance.raw,
                author_name=routing_context.author.display_name,
                channel_type=channel_type,
                is_mention=True,
                system_prompt=system_prompt,
                context_prompt=context_prompt,
                history=history,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                "[MONITOR] Personalized AI failed: "
                f"{type(exc).__name__}"
            )
            success, ai_response = False, ""

        if not success or not ai_response:
            return await self._send_route_text(
                message,
                get_fallback_response("general"),
                routed_intent,
                "failed",
            )

        try:
            active_polls = self.poll.snapshot_pending_items(
                domain_scope_id(routing_context.key),
                reference_time=reference_time,
            )
        except (TypeError, ValueError):
            active_polls = ()
        active_poll_id = (
            str(active_polls[0]["poll_id"])
            if len(active_polls) == 1
            and isinstance(active_polls[0], Mapping)
            and active_polls[0].get("poll_id") is not None
            else None
        )
        model_outcome = await self.ai_action_handler.handle_model_response(
            raw=ai_response,
            utterance=utterance,
            routing=routing_context,
            reference_time=reference_time,
            deterministic_route=routed_intent,
            active_poll_count=len(active_polls),
            active_poll_id=active_poll_id,
            semantic_action_allowed=semantic_action_allowed,
        )
        if model_outcome.route is None:
            text = model_outcome.visible_text or get_fallback_response("general")
            if (
                routed_intent.intent is BotIntent.SEARCH
                and model_outcome.disposition is ModelDisposition.ORDINARY
            ):
                decision_route = routed_intent
                decision_outcome = "executed"
            else:
                decision_route = IntentResult(
                    BotIntent.AI_CHAT,
                    1.0,
                    {},
                    (
                        "model_prose"
                        if not model_outcome.parser_errors
                        else "model_action_invalid"
                    ),
                    source=IntentSource.SEMANTIC,
                    risk=IntentRisk.READ_ONLY,
                )
                decision_outcome = {
                    ModelDisposition.BLOCKED: "blocked",
                    ModelDisposition.INVALID: "failed",
                    ModelDisposition.ORDINARY: "routed",
                }.get(model_outcome.disposition, "failed")
            return await self._send_route_text(
                message,
                text,
                decision_route,
                decision_outcome,
            )
        return await self._process_route(
            message,
            utterance=utterance,
            routing_context=routing_context,
            route=model_outcome.route,
            reference_time=reference_time,
            visible_text=model_outcome.visible_text,
            model_origin=True,
        )

    async def _parse_and_execute_actions(self, response_text, message):
        """Compatibility cleaner; model proposals remain inert on this path."""

        utterance = normalize_utterance(message.content)
        routing = routing_context_from_message(
            message,
            bot_user_id=self.client.user.id,
        )
        outcome = await self.ai_action_handler.handle_model_response(
            raw=response_text,
            utterance=utterance,
            routing=routing,
            reference_time=self._reference_time_now(),
            deterministic_route=None,
            active_poll_count=None,
            active_poll_id=None,
            semantic_action_allowed=True,
        )
        return outcome.visible_text

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
        await self._send_text_sequence_result(message, response_text)

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

    def record_outbound(self, message, content: str) -> None:
        """Record one definitely delivered response in the exact turn scope."""

        self.conversation.add_turn(
            conversation_key_from_message(message),
            ChatTurn("assistant", history_safe_content(content)),
        )

    def _record_monitor_delivery(
        self,
        message,
        response_text: str,
        result: MessageSendResult,
    ) -> None:
        if result.state is not DeliveryState.DELIVERED:
            return
        self.response_count += 1
        print("[MONITOR] Response delivered")
        try:
            self.record_outbound(message, response_text)
        except Exception:
            # Conversation history is contextual bookkeeping.  Once the
            # Discord adapter has confirmed delivery it must not rewrite
            # that truth or trigger an alternate response.
            print("[MONITOR] Outbound conversation recording degraded")

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

    async def _send_text_sequence_result(
        self,
        message,
        text: str,
    ) -> MessageSendResult:
        """Send at most five ordered chunks without replaying a prefix."""

        delivered = 0
        chunks = bounded_discord_text_chunks(text)
        for chunk in chunks:
            try:
                result = await self._send_response_result(message, chunk)
            except MessageSendCancelled as exc:
                if exc.result.state is DeliveryState.DELIVERED:
                    delivered += 1
                if delivered == len(chunks):
                    aggregate = MessageSendResult(DeliveryState.DELIVERED)
                elif delivered:
                    aggregate = MessageSendResult(
                        DeliveryState.UNKNOWN,
                        "partial_send",
                    )
                else:
                    aggregate = exc.result
                raise MessageSendCancelled(aggregate) from exc
            if result.state is DeliveryState.DELIVERED:
                delivered += 1
                continue
            if delivered:
                return MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "partial_send",
                )
            return result
        return MessageSendResult(DeliveryState.DELIVERED)

    async def _send_response(self, message, response_text) -> bool:
        """One-release projection over tri-state monitor delivery truth."""
        result = await self._send_response_result(message, response_text)
        return result.state is DeliveryState.DELIVERED

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
