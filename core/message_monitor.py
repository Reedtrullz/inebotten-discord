#!/usr/bin/env python3
"""
Message Monitor for Discord Selfbot
Polls DMs and detects @inebotten mentions using discord.py
"""

import asyncio
import json
import time
from utils.storage_contract import StorageMutationError
from core.outbound_sender import monitor_sender
from core.access_policy import AccessPolicy, invocation_decision
import os
import re
import signal
import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord

from core.intent_router import BotIntent, IntentRouter
from core.request_context import RequestContext, request_scope, request_localization
from core.intent_thresholds import CONFIDENCE_THRESHOLDS
from ai.action_schema import parse_action_draft
from ai.result_schema import AIResult, MAX_AI_PROMPT_CHARS
from core.intent_keywords import STATUS_KEYWORDS
from core.command_registry import command_metadata, dispatch_command, CommandPayloadError
from web_console.server import ConsoleServer


# Compatibility export; consumers obtain fresh copied metadata via the getter.
COMMAND_REGISTRY = command_metadata()


_COUNTER_STAT_KEYS = ("count", "low_confidence", "errors")
AI_REPLY_TIMEOUT_S = 20.0


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
    ):
        from utils.resource_shutdown import OwnedResources
        self._owned_resources = OwnedResources()
        self._active_requests = set()
        self._closing = False
        self._shutdown_registered = False
        self.client = client
        self.bot = client
        self.hermes = hermes_connector
        self.rate_limiter = rate_limiter
        monitor_sender(self)
        self._owned_resources.add('outbound', self.outbound.aclose)
        self.response_gen = response_generator
        self.bot_name = bot_name
        self.bot_mention = f"@{bot_name}"

        # Initialize unified calendar manager
        from cal_system.calendar_manager import CalendarManager
        from cal_system.natural_language_parser import NaturalLanguageParser
        from cal_system.google_calendar_manager import GoogleCalendarManager

        # Initialize GCal manager if token exists
        gcal = GoogleCalendarManager()
        if not gcal.is_configured():
            gcal = None
        else:
            print("[MONITOR] Google Calendar integration enabled")

        self.access_policy = AccessPolicy.from_config(self.client.config)
        self.calendar = CalendarManager(
            access_policy=self.access_policy,
            gcal_manager=gcal,
            owner_email=getattr(self.client.config, 'DISCORD_EMAIL', None),
            owner_name=getattr(self.client.config, 'CALENDAR_OWNER_NAME', 'ᚱᛊᛊᚦ')
        )
        self._owned_resources.add('calendar-store', self.calendar._storage.aclose)
        self._owned_resources.add('google-slot', self.calendar._outbox.slot.close)
        self.nlp_parser = NaturalLanguageParser()

        from cal_system.reminder_manager import ReminderManager
        self.reminders = ReminderManager(gcal_manager=gcal, access_policy=self.access_policy,
            clock=self.calendar.clock)
        self._owned_resources.add('reminder-store', self.reminders._storage.aclose)
        self.reminders.configure_google(gcal, slot=self.calendar._outbox.slot,
            access_policy=self.access_policy)

        # Initialize personality and memory systems
        from memory.user_memory import get_user_memory
        from memory.conversation_context import get_context_manager
        from ai.personality_config import get_system_prompt, ResponseStyle

        self.user_memory = get_user_memory()
        self.conversation = get_context_manager()
        self.user_memory.conversation = self.conversation
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
        self.poll = PollManager()
        self._owned_resources.add('poll-store', self.poll._storage.aclose)
        self.watchlist = WatchlistManager()
        self.wod = WordOfTheDay()
        self.quote = QuoteManager()
        self.crypto = CryptoManager()
        self._owned_resources.add('crypto', self.crypto.close)
        self.compliments = ComplimentsManager()
        self.horoscope = HoroscopeManager()
        self.calculator = CalculatorManager()
        self.url_shortener = URLShortener()
        self.aurora = AuroraForecast()
        self._owned_resources.add('aurora', self.aurora.close)
        from features.forecast_service import ForecastService
        self.forecasts = ForecastService(aurora_client=self.aurora, owns_aurora=False)
        self._owned_resources.add('forecasts', self.forecasts.close)
        self.search_manager = SearchManager()
        self._owned_resources.add('search', self.search_manager.close)
        self.browser_manager = BrowserManager()
        self.detect_search_intent = detect_search_intent
        from features.birthday_manager import BirthdayManager
        self.birthdays = BirthdayManager()

        self.daily_digest = DailyDigestManager(
            event_manager=self.calendar,
            birthday_manager=self.birthdays,
            crypto_manager=self.crypto,
            aurora_manager=self.aurora,
            watchlist_manager=self.watchlist,
            forecast_service=self.forecasts
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
        self._task_health: dict[str, dict[str, object]] = {}
        self._provider_readiness: dict[str, object] = {"probe": None, "inference": None}

        self.handlers = {}
        self._register_handlers()
        self.intent_router = IntentRouter(self)

    def _track_background_task(self, coro, name):
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        self._set_task_health(name, state="running", started_at=datetime.now(timezone.utc).isoformat(), last_error=None)

        def _done_callback(done_task):
            self._background_tasks.discard(done_task)
            if done_task.cancelled():
                self._set_task_health(name, state="cancelled", finished_at=datetime.now(timezone.utc).isoformat())
                return
            try:
                exc = done_task.exception()
            except Exception:
                return
            if exc:
                self._mark_task_error(name, exc, state="failed", finished_at=datetime.now(timezone.utc).isoformat())
                print(f"[MONITOR] Background task {name} failed: {exc}")
            else:
                self._set_task_health(
                    name,
                    state="completed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    last_ok=datetime.now(timezone.utc).isoformat(),
                    last_error=None,
                    exception_type=None,
                )

        task.add_done_callback(_done_callback)
        return task

    def record_scheduler_iteration(self, successful):
        if successful:
            self._mark_task_ok('reminder-checker')
        else:
            self._set_task_health('reminder-checker', state='degraded',
                reason_code='scheduler_iteration_failed',
                last_error_at=datetime.now(timezone.utc).isoformat())

    def record_provider_health_check(self, healthy):
        """Retain only startup reachability evidence; discard provider text."""
        if not isinstance(getattr(self, '_provider_readiness', None), dict):
            self._provider_readiness = {'probe': None, 'inference': None}
        self._provider_readiness["probe"] = {
            "ok": bool(healthy),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def record_provider_inference(self, result):
        """Retain outcome metadata from a real request, never its prompt or text."""
        status = str(getattr(result, "status", "unavailable")).lower()
        if status not in {"success", "busy", "retryable", "auth_error", "unavailable"}:
            status = "unavailable"
        provider = str(getattr(result, "provider", "unknown")).strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{1,32}", provider):
            provider = "unknown"
        accepted = status == "success" and bool(getattr(result, "text", None))
        if not isinstance(getattr(self, '_provider_readiness', None), dict):
            self._provider_readiness = {'probe': None, 'inference': None}
        self._provider_readiness["inference"] = {
            "status": status,
            "provider": provider,
            "fallback": bool(getattr(result, "fallback", False)),
            "accepted": accepted,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_provider_readiness(self):
        return {
            key: dict(value) if isinstance(value, dict) else None
            for key, value in self._provider_readiness.items()
        }

    def _set_task_health(self, name, **updates):
        health = self._task_health.setdefault(name, {"state": "unknown"})
        health.update(updates)

    def _mark_task_ok(self, name):
        self._set_task_health(
            name,
            state="running",
            last_ok=datetime.now(timezone.utc).isoformat(),
            last_error=None,
            exception_type=None,
        )

    def _mark_task_error(self, name, exc, *, state="degraded", **extra):
        self._set_task_health(
            name,
            state=state,
            last_error=str(exc),
            exception_type=type(exc).__name__,
            last_error_at=datetime.now(timezone.utc).isoformat(),
            **extra,
        )

    def get_task_health(self):
        return {name: dict(values) for name, values in self._task_health.items()}

    @property
    def loc(self):
        return request_localization(self._localization)

    @loc.setter
    def loc(self, value):
        self._localization = value

    async def setup(self):
        await self.calendar.setup()
        await self.user_memory.setup()

        # Auto-sync from GCal on startup if enabled
        if self.calendar.gcal_enabled:
            print("[MONITOR] Performing initial Google Calendar sync...")
            try:
                # Use a background task so we don't block startup
                self._track_background_task(self.calendar.sync_from_gcal(), "initial-gcal-sync")
            except Exception as e:
                print(f"[MONITOR] Initial GCal sync failed: {e}")

        # Start periodic console stats persistence
        self._track_background_task(self._console_persistence_loop(), "console-persistence")

        print("[MONITOR] Async managers (Calendar, Memory, Birthdays) initialized")

    async def _drain_owned_work(self):
        tasks = set(getattr(self, '_background_tasks', set())) | set(getattr(self, '_active_requests', set()))
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        getattr(self, '_background_tasks', set()).clear()

    async def close(self, deadline=None):
        """Close only owned resources; retain pending work and failed deltas."""
        from utils.resource_shutdown import OwnedResources
        self._closing = True
        if not hasattr(self, '_owned_resources'):
            self._owned_resources = OwnedResources()
        if not getattr(self, '_shutdown_registered', False):
            if hasattr(self, 'intent_stats'):
                self._owned_resources.add('final-counters', self._persist_console_stats_once)
            self._owned_resources.add('owned-work', self._drain_owned_work)
            self._shutdown_registered = True
        try:
            await self._owned_resources.close(deadline if deadline is not None else time.monotonic() + 10)
        finally:
            self.shutdown_receipt = self._owned_resources.receipt()
            self.shutdown_receipt['unsaved_intents'] = self.get_unsaved_intent_stats() if hasattr(self, 'intent_stats') else {}
            self.shutdown_receipt['unsaved_rate_requests'] = sum(getattr(self, '_pending_console_delta', {}).get('rates', {}).values())

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
        if not hasattr(self, '_stats_flush_lock'):
            self._stats_flush_lock = asyncio.Lock()
        async with self._stats_flush_lock:
            await self._persist_console_stats_locked()

    async def _persist_console_stats_locked(self) -> None:
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
        self._pending_console_delta = {'intents': intent_delta, 'rates': rate_delta}
        if intent_delta or rate_delta:
            worker = asyncio.create_task(asyncio.to_thread(store.save_stats, intent_delta, rate_delta))
            cancelled = False
            try:
                saved = await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
                saved = await worker
            if not saved:
                raise RuntimeError("console stats save failed")
        else:
            cancelled = False
        self._last_persisted_intent_stats = intent_snapshot
        self._last_persisted_rate_stats = dict(rate_stats)
        self._pending_console_delta = {'intents': {}, 'rates': {}}
        self._mark_task_ok("console-persistence")
        if cancelled:
            raise asyncio.CancelledError

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
        if getattr(self, '_closing', False):
            return
        if not hasattr(self, '_active_requests'):
            self._active_requests = set()
        task = asyncio.current_task()
        self._active_requests.add(task)
        try:
            await self._handle_message(message)
        finally:
            self._active_requests.discard(task)

    async def _handle_message(self, message):
        """Process an incoming message"""
        # Skip own messages
        if message.author.id == self.client.user.id:
            return

        invocation = invocation_decision(
            RequestContext.from_message(message, 'no'),
            mode=getattr(self.client.config, 'INVOCATION_MODE', 'legacy'),
            allowed_users=getattr(self.client.config, 'ALLOWED_USERS', []),
            allowed_channels=getattr(self.client.config, 'ALLOWED_CHANNELS', []))
        if not invocation.allowed:
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
        self.mention_count += 1
        print(
            f"[MONITOR] Mention detected from {message.author.name} "
            f"in {self._get_channel_type(message.channel)}"
        )

        # Rate limit check
        can_send, reason = self.rate_limiter.can_send()
        if not can_send:
            print(f"[MONITOR] Rate limited, cannot respond: {reason}")
            self.rate_limiter.record_dropped()
            return

        # Wait if needed
        if not await self.rate_limiter.wait_if_needed():
            print("[MONITOR] Daily quota exceeded, dropping message")
            self.rate_limiter.record_dropped()
            return

        # Detect language from message
        lang = self.loc.detect_language(message.content)
        print(f"[MONITOR] Detected language: {lang}")

        context = RequestContext.from_message(message, lang)
        with request_scope(context):
            guild_id = message.guild.id if message.guild else message.channel.id
            route = None
            try:
                route = self.intent_router.route(message.content, guild_id=guild_id)
                self._last_routed_intent = route.intent
                print(f"[MONITOR] Intent matched: {route.intent.value} ({route.reason}, {route.confidence:.2f})")
                await self._handle_intent(message, route)
                self.intent_stats[route.intent.value]["count"] += 1
            except StorageMutationError:
                self.error_count += 1
                await self._send_response(message, "❌ Kunne ikke lagre endringen lokalt. Kontroller status før du prøver igjen.")
            except Exception as exc:
                route_name = route.intent.value if route else "unknown"
                print(f"[MONITOR] ERROR handling intent {route_name}: {exc}")
                self.error_count += 1
                self.intent_stats[route_name]["errors"] += 1
                error_message = (
                    "🤖 Jeg fikk ikke hentet et svar nå. Prøv igjen om litt."
                    if route and route.intent == BotIntent.AI_CHAT
                    else "❌ Kommandoen kunne ikke fullføres. Kontroller status før du prøver igjen, "
                    "eller bruk hjelp."
                )
                await self._send_response(
                    message,
                    error_message,
                )

    async def _handle_intent(self, message, route):
        """Execute the handler for a routed intent."""
        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        if route.confidence < threshold:
            print(
                f"[MONITOR] Intent {route.intent.value} rejected: confidence {route.confidence:.2f} < threshold {threshold}"
            )
            self.intent_stats[route.intent.value]["low_confidence"] += 1
            await self._send_ai_response(message)
            return

        try:
            return await dispatch_command(self, message, route)
        except CommandPayloadError:
            await self._send_response(message,
                '❌ Kommandodataene er ugyldige. Bruk hjelp og prøv en støttet kommando.')

    async def _registry_calendar_help(self, message):
        return await self._send_response(message, self.conv_gen.get_calendar_help())

    async def _registry_profile(self, message):
        if not await self.handlers['profile'].handle_profile_command(message):
            await self._send_response(message,
                'Jeg kjenner ikke igjen profilkommandoen. Prøv status eller aktivitet.')

    async def _registry_watchlist(self, message, payload):
        action = payload.get('action')
        if action == 'remove':
            text = await self.handlers['watchlist'].handle_watchlist_remove(message, payload)
        elif action == 'edit':
            text = await self.handlers['watchlist'].handle_watchlist_edit(message, payload)
        else:
            return await self.handlers['watchlist'].handle_watchlist(message, payload)
        if text:
            return await self._send_response(message, text)

    async def _registry_search(self, message, search):
        return await self._send_ai_response(message, forced_search_info=search)

    async def _send_dashboard_response(self, message):
        """Generate and send an explicit dashboard response."""
        guild_id = message.guild.id if message.guild else message.channel.id
        content_lower = message.content.lower()
        from features.weather_api import extract_city

        try:
            response_text = await self._generate_dashboard(
                guild_id,
                city_name=extract_city(message.content),
                show_navnedag=any(
                    re.search(rf"\b{re.escape(word)}\b", content_lower)
                    for word in ["navnedag", "oppsummering", "brief", "status"]
                ),
                user_id=message.author.id,
            )
        except ValueError as error:
            response_text = str(error)
        await self._send_response(message, response_text)

    async def _provider_memory_context(self, message, channel_id):
        """Filter every retained surface for every route that could receive it."""
        build = getattr(self.user_memory, 'build_prompt_memory', None)
        policy_for = getattr(self.user_memory, 'policy_for_user', None)
        if not callable(build) or not callable(policy_for):
            return '', ''
        primary = getattr(self.hermes, 'primary', self.hermes)
        providers = [getattr(primary, 'provider', 'unknown')]
        fallback = getattr(self.hermes, 'fallback', None)
        if fallback is not None:
            providers.append(getattr(fallback, 'provider', 'unknown'))
        from core.request_context import current_request
        actor = current_request() or RequestContext.from_message(message, 'no')
        scope = f'private:{message.author.id}' if actor.channel_kind == 'dm' else 'shared'
        snapshots = [await build(message.author.id, provider, scope) for provider in providers]
        # One prompt is reused by declared fallback: sharing cannot expand on it.
        policy = policy_for(message.author.id)
        shared = {key: value for key, value in snapshots[0].items()
            if all(key in snapshot and snapshot[key] == value for snapshot in snapshots)} if snapshots and all(snapshots) else {}
        if not policy.learning_enabled or any(provider not in policy.allowed_provider_ids for provider in providers):
            shared = {}
        elif not policy.private_facts_enabled or scope != f'private:{message.author.id}':
            shared = {key: value for key, value in shared.items() if key == 'preferences'}
        user_context = json.dumps(shared, ensure_ascii=False) if shared else ''
        messages = []
        get_messages = getattr(self.conversation, 'get_channel_messages', None)
        if callable(get_messages):
            for entry in get_messages(channel_id, limit=5):
                owner = entry.get('source_user_id') if entry.get('is_bot') else entry.get('user_id')
                if owner is None:
                    continue
                policy = policy_for(owner)
                if policy.learning_enabled and all(provider in policy.allowed_provider_ids for provider in providers):
                    if str(owner) == str(message.author.id) or actor.channel_kind != 'dm':
                        messages.append(f'{entry.get("username", "Bruker")}: {entry["content"]}')
        return user_context, '\n'.join(messages)

    async def _send_ai_response(self, message, forced_search_info=None):
        """
        Generate and send an AI response to a mention.
        Uses Hermes AI with personality system.
        """
        print('[MONITOR] AI response requested')

        channel_type = self._get_channel_type(message.channel)
        print(f"[MONITOR] Channel type: {channel_type}")
        guild_id = message.guild.id if message.guild else message.channel.id
        context_channel = message.channel.id
        content_lower = message.content.lower()
        wants_dashboard, dashboard_reason = self.conversation.should_show_dashboard(
            message.content, context_channel
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
            channel_id=context_channel,
            user_id=message.author.id,
            username=message.author.name,
            content=message.content,
            is_bot=False,
        )

        # Automatic topics belong only to the opted-in speaker.
        policy_for = getattr(self.user_memory, 'policy_for_user', None)
        learning = callable(policy_for) and policy_for(message.author.id).learning_enabled
        topic = self.conversation.get_conversation_summary(context_channel, user_id=message.author.id) if learning else None
        await self.user_memory.update_last_interaction(
            message.author.id,
            topic=topic,
            username=message.author.name,
        )

        response_text = None

        # If it's small talk, don't show dashboard - use AI conversation
        if not wants_dashboard:
            # Check for Norwegian dialect expressions first (fast path)
            from ai.personality import get_personality
            dialect_response = get_personality().respond_to_dialect(message.content)
            if dialect_response:
                response_text = dialect_response
                print('[MONITOR] Using dialect response')
            
            # Fall back to AI if no dialect match and hermes is available
            if not response_text and self.hermes:
                try:
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
                        user_context, conversation_context = await self._provider_memory_context(message, context_channel)
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

                        from core.request_context import current_request

                        request_context = current_request() or RequestContext.from_message(
                            message, "no"
                        )
                        prompt = f"{system_prompt}\n\nBrukermelding:\n{message.content}"
                        if len(prompt) > MAX_AI_PROMPT_CHARS:
                            result = AIResult("unavailable", None, "monitor", None)
                        elif not callable(getattr(self.hermes, "generate_reply", None)):
                            result = AIResult("unavailable", None, "monitor", None)
                        else:
                            result = await self.hermes.generate_reply(
                                request_context,
                                prompt,
                                deadline=time.monotonic() + AI_REPLY_TIMEOUT_S,
                            )

                        if not isinstance(result, AIResult):
                            result = AIResult("unavailable", None, "monitor", None)
                        self.record_provider_inference(result)
                        if result.status == "success" and result.text:
                            print(
                                f"[MONITOR] AI response from {result.provider} "
                                f"(fallback={result.fallback})"
                            )
                            response_text = await self._parse_and_execute_actions(
                                result.text, message
                            )
                            if result.fallback and response_text:
                                origin = result.provider
                                if result.model:
                                    origin += f" ({result.model})"
                                response_text = (
                                    f"_(Svar fra lokal reserve {origin})_\n\n"
                                    f"{response_text}"
                                )
                        else:
                            response_text = self._ai_outcome_message(result)
                except Exception as e:
                    print(f"[MONITOR] Personalized AI failed: {e}")
                    response_text = self._ai_outcome_message(
                        AIResult("unavailable", None, "monitor", None)
                    )

        # Fallback: dashboard or basic response
        if not response_text:
            if wants_dashboard:
                response_text = await self._generate_dashboard(
                    guild_id, 
                    city_name=city_name, 
                    show_navnedag=show_navnedag,
                    user_id=message.author.id
                )
            else:
                response_text = self._ai_outcome_message(
                    AIResult("unavailable", None, "monitor", None)
                )

        # Send the response
        await self._send_response(message, response_text)

    async def _parse_and_execute_actions(self, response_text, message):
        """Turn one validated model draft into user-confirmed text only."""
        output_lines = []
        draft_confirmation = None
        for line in response_text.splitlines():
            action = parse_action_draft(line.strip())
            if action and action.get("action") == "SAVE_EVENT" and draft_confirmation is None:
                draft_confirmation = self._append_calendar_draft_confirmation(
                    "", action["title"], action["date"], action["time"]
                )
            else:
                output_lines.append(line)

        cleaned_text = "\n".join(output_lines).strip()
        if draft_confirmation:
            cleaned_text = f"{cleaned_text}\n\n{draft_confirmation}".strip()
        return cleaned_text

    @staticmethod
    def _ai_outcome_message(result: AIResult) -> str:
        if result.status == "busy":
            delay = result.retry_after_s
            if delay is not None:
                return f"🤖 Jeg er opptatt akkurat nå. Prøv igjen om {max(1, int(delay))} sekunder."
            return "🤖 Jeg er opptatt akkurat nå. Prøv igjen om litt."
        if result.status == "cancelled":
            return "🤖 Forespørselen ble avbrutt før jeg rakk å svare."
        if result.status == "auth_error":
            return "🤖 AI-tilkoblingen trenger oppmerksomhet. Prøv igjen senere."
        if result.status == "retryable":
            return "🤖 AI-tjenesten feilet midlertidig. Prøv igjen om litt."
        return "🤖 AI-tjenesten er ikke tilgjengelig akkurat nå."

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

    async def _handle_set_location(self, message, city):
        """Handle setting the user's location."""
        try:
            from features.weather_api import NORWEGIAN_CITIES
            city_info = NORWEGIAN_CITIES.get(city.lower())
            
            if city_info:
                await self.user_memory.set_location(message.author.id, city_info['name'])
                response = f"✅ Den er grei! Jeg har lagret at du bor i **{city_info['name']}**. Jeg skal bruke dette når jeg henter været for deg framover. 😊"
            else:
                response = f"❌ Beklager, jeg kjenner ikke til \"{city}\" ennå. Jeg kan foreløpig bare store norske byer."
            
            await self._send_response(message, response)
        except Exception as e:
            print(f"[MONITOR] Error setting location: {e}")
            await self._send_response(message, "❌ Beklager, det oppstod en feil da jeg prøvde å lagre lokasjonen din.")

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

    async def _generate_dashboard(self, guild_id: int, city_name: str = None, show_navnedag: bool = False, user_id: int = None) -> str:
        """Generate dashboard response with weather, events, etc."""
        from cal_system.norwegian_calendar import get_todays_info
        from features.forecast_service import ForecastService, resolve_location
        from core.request_context import current_request
        norwegian_data = get_todays_info()
        if not city_name and user_id:
            user_mem = await self.user_memory.get_user(user_id)
            city_name = user_mem.get("location")
        location = resolve_location(city_name or "oslo")
        service = getattr(self, "forecasts", None)
        if service is None:
            self.forecasts = service = ForecastService(aurora_client=getattr(self, "aurora", None))
        result = await service.get_weather(location)
        context = current_request()
        weather_formatted = {
            "status": result.status, "source": result.source,
            "valid_at": result.valid_at.isoformat() if result.valid_at else None,
            "expires_at": result.expires_at.isoformat() if result.expires_at else None,
            "fetched_at": result.fetched_at.isoformat(),
            "locale": context.locale if context else "no",
            "location": location["name"], "lat": location["lat"], "lon": location["lon"],
            "temp": result.data.get("temp") if result.data else None,
            "conditions": result.data.get("condition") if result.data else None,
        }

        upcoming_items = self.calendar.get_upcoming(guild_id, days=7)

        dashboard = self.conv_gen.generate_dashboard(
            weather_data=weather_formatted,
            events=upcoming_items,
            reminders=[],
            norwegian_data=norwegian_data,
            show_navnedag=show_navnedag,
        )

        return dashboard

    async def _send_response(self, message, response_text):
        """Only acknowledged responses enter counters and conversation history."""
        result = await monitor_sender(self).reply(message, response_text)
        if result.status == 'delivered' and result.reason_code == 'remote_message':
            self.response_count += 1
            self.conversation.add_message(channel_id=message.channel.id, user_id=None,
                username='Inebotten', content=response_text, is_bot=True, source_user_id=message.author.id)
        return result

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
        return command_metadata()

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
        self.reminder_checker = None
        self.reminder_checker_task = None
        self.start_time = None

    async def setup_hook(self):
        """Start diagnostics before the Discord session reaches ready."""
        await self.start_console()

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
        if getattr(self, '_client_closing', False):
            return
        previous = getattr(self, '_failed_monitor', None)
        if previous is not None:
            await previous.close()
            if getattr(previous, 'shutdown_receipt', {}).get('status', 'closed') != 'closed':
                raise RuntimeError('previous_initialization_cleanup_pending')
            self._failed_monitor = None
        # Discord may emit READY again after a reconnect.  Keep the existing
        # monitor, console, and reminder task instead of creating duplicate
        # background workers or resetting the uptime clock.
        if self.monitor is not None:
            print(f"[BOT] Session ready again as {self.user}; existing monitor retained")
            await self.start_console()
            if self.console_server:
                self.console_server.monitor = self.monitor
            return

        self.start_time = datetime.now()
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

        # Initialize message monitor
        monitor = MessageMonitor(
            client=self,
            hermes_connector=self.hermes,
            rate_limiter=self.rate_limiter,
            response_generator=self.response_gen,
        )
        self._process_memory_owner = getattr(monitor, 'user_memory', None)
        reminder_checker = None
        try:
            await monitor.setup()

            # Initialize and start calendar reminder checker
            reminder_checker = self._create_reminder_checker(monitor)
            if reminder_checker:
                await reminder_checker.setup()
        except BaseException:
            # setup() may already have started monitor-owned background tasks.
            # Cancel them before leaving the components unpublished for retry.
            self._failed_monitor = monitor
            try:
                await monitor.close()
                if reminder_checker is not None and hasattr(reminder_checker, 'close_storage'):
                    from utils.storage_contract import store_worker
                    await store_worker(reminder_checker.close_storage)
            except Exception:
                print('[BOT] Initialization cleanup remains incomplete')
            raise

        # Publish fully initialized components only. A failed first READY can
        # then be retried safely when Discord reconnects.
        self.monitor = monitor
        self.reminder_checker = reminder_checker

        await self.start_console()
        if self.console_server:
            self.console_server.monitor = self.monitor

        if reminder_checker:
            self.reminder_checker_task = monitor._track_background_task(
                reminder_checker.start(),
                "reminder-checker",
            )
            print("[BOT] Calendar reminder checker started")

        # Check AI connector health
        if not self.hermes:
            print("[BOT] WARNING: AI connector missing")
            print("[BOT] Will use local response generator as fallback")
            return

        healthy, message = await self.hermes.check_health()
        if self.monitor is not None:
            record_probe = getattr(self.monitor, "record_provider_health_check", None)
            if callable(record_probe):
                record_probe(healthy)
        if healthy:
            print(f"[BOT] AI connector: {message}")
        else:
            print(f"[BOT] WARNING: AI connector issue - {message}")
            print("[BOT] Will use local response generator as fallback")

    def _create_reminder_checker(self, monitor=None):
        """Create a ReminderChecker wired to the bot's channels."""
        from cal_system.reminder_checker import ReminderChecker
        selected_monitor = monitor if monitor is not None else self.monitor
        if selected_monitor is None:
            raise RuntimeError("Reminder checker requires an initialized monitor")
        calendar = selected_monitor.calendar
        reminders = selected_monitor.reminders

        def get_channel(channel_id: int):
            return self.get_channel(channel_id)

        return ReminderChecker(
            calendar_manager=calendar,
            reminder_manager=reminders,
            health_callback=getattr(selected_monitor, 'record_scheduler_iteration', None),
            get_channel_func=get_channel,
            outbound_sender=monitor_sender(selected_monitor) if hasattr(selected_monitor, "rate_limiter") else None,
        )

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
        if not getattr(self, '_client_closing', False) and self.monitor:
            await self.monitor.handle_message(message)

    async def on_disconnect(self):
        """Called when disconnected"""
        print("[BOT] Disconnected from Discord")

    async def on_resumed(self):
        """Called when session is resumed"""
        print("[BOT] Session resumed")

    async def close(self, deadline=None):
        from utils.resource_shutdown import OwnedResources
        self._client_closing = True
        if not hasattr(self, '_close_scope'):
            scope = self._close_scope = OwnedResources()
            scope.add('discord-transport', super().close)
            checker = getattr(self, 'reminder_checker', None)
            if checker is not None and hasattr(checker, 'close_storage'):
                scope.add('checker-store', checker.close_storage)
            monitor = getattr(self, 'monitor', None) or getattr(self, '_failed_monitor', None)
            if monitor is not None:
                async def close_monitor():
                    await monitor.close()
                    if getattr(monitor, 'shutdown_receipt', {}).get('status', 'closed') != 'closed':
                        raise RuntimeError('monitor_cleanup_incomplete')
                scope.add('monitor', close_monitor)
            async def close_checker_work():
                if checker is not None:
                    checker.stop()
                tasks = [task for task in (getattr(self, 'reminder_checker_task', None),
                                          getattr(self, 'console_task', None)) if task is not None]
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            scope.add('checker-work', close_checker_work)
            if getattr(self, 'console_server', None) is not None:
                scope.add('console-connections', self.console_server.stop)
        try:
            await self._close_scope.close(deadline if deadline is not None else time.monotonic() + 10)
        finally:
            self.shutdown_receipt = self._close_scope.receipt()
        if self.shutdown_receipt['status'] != 'closed':
            raise RuntimeError('client_cleanup_incomplete')

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
