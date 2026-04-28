#!/usr/bin/env python3
"""
Message Monitor for Discord Selfbot
Polls DMs and detects @inebotten mentions using discord.py
"""

import asyncio
import os
import re
import signal
from collections import defaultdict, deque
from datetime import datetime, timedelta

import discord

from core.intent_router import BotIntent, IntentRouter
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
    {"name": "ai_chat", "aliases": [], "priority": 1000, "scope": "any"},
]


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
        self.client = client
        self.bot = client
        self.hermes = hermes_connector
        self.rate_limiter = rate_limiter
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

        self.calendar = CalendarManager(
            gcal_manager=gcal,
            owner_email=getattr(self.client.config, 'DISCORD_EMAIL', None),
            owner_name=getattr(self.client.config, 'CALENDAR_OWNER_NAME', 'ᚱᛊᛊᚦ')
        )
        self.nlp_parser = NaturalLanguageParser()

        # Initialize personality and memory systems
        from memory.user_memory import get_user_memory
        from memory.conversation_context import get_context_manager
        from ai.personality_config import get_system_prompt, ResponseStyle

        self.user_memory = get_user_memory()
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
        self.poll = PollManager()
        self.watchlist = WatchlistManager()
        self.wod = WordOfTheDay()
        self.quote = QuoteManager()
        self.crypto = CryptoManager()
        self.compliments = ComplimentsManager()
        self.horoscope = HoroscopeManager()
        self.calculator = CalculatorManager()
        self.url_shortener = URLShortener()
        self.aurora = AuroraForecast()
        self.search_manager = SearchManager()
        self.browser_manager = BrowserManager()
        self.detect_search_intent = detect_search_intent
        self.daily_digest = DailyDigestManager(
            event_manager=self.calendar,
            birthday_manager=None,  # Will be set in setup()
            crypto_manager=self.crypto,
            aurora_manager=self.aurora,
            watchlist_manager=self.watchlist
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

        self.handlers = {}
        self._register_handlers()
        self.intent_router = IntentRouter(self)

    async def setup(self):
        await self.calendar.setup()
        await self.user_memory.setup()

        # Inject birthday manager into daily digest after initialization
        from features.birthday_manager import BirthdayManager
        self.birthdays = BirthdayManager()
        self.daily_digest.birthday_manager = self.birthdays

        # Auto-sync from GCal on startup if enabled
        if self.calendar.gcal_enabled:
            print("[MONITOR] Performing initial Google Calendar sync...")
            try:
                # Use a background task so we don't block startup
                asyncio.create_task(self.calendar.sync_from_gcal())
            except Exception as e:
                print(f"[MONITOR] Initial GCal sync failed: {e}")
        
        print("[MONITOR] Async managers (Calendar, Memory, Birthdays) initialized")

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
        self.loc.set_language(lang)
        print(f"[MONITOR] Detected language: {lang}")

        guild_id = message.guild.id if message.guild else message.channel.id
        route = None
        try:
            route = self.intent_router.route(message.content, guild_id=guild_id)
            self._last_routed_intent = route.intent
            print(f"[MONITOR] Intent matched: {route.intent.value} ({route.reason}, {route.confidence:.2f})")
            await self._handle_intent(message, route)
            self.intent_stats[route.intent.value]["count"] += 1
        except Exception as exc:
            import traceback

            route_name = route.intent.value if route else "unknown"
            print(f"[MONITOR] ERROR handling intent {route_name}: {exc}")
            traceback.print_exc()
            self.error_count += 1
            self.intent_stats[route_name]["errors"] += 1
            try:
                await self._send_ai_response(message)
            except Exception as ai_exc:
                print(f"[MONITOR] AI fallback also failed: {ai_exc}")

    async def _handle_intent(self, message, route):
        """Execute the handler for a routed intent."""
        payload = route.payload

        threshold = CONFIDENCE_THRESHOLDS.get(route.intent, 0.0)
        if route.confidence < threshold:
            print(
                f"[MONITOR] Intent {route.intent.value} rejected: confidence {route.confidence:.2f} < threshold {threshold}"
            )
            self.intent_stats[route.intent.value]["low_confidence"] += 1
            await self._send_ai_response(message)
            return

        if route.intent == BotIntent.HELP:
            await self.handlers["help"].handle_help(message)
        elif route.intent == BotIntent.CALENDAR_HELP:
            await self._send_response(message, self.conv_gen.get_calendar_help())
        elif route.intent == BotIntent.STATUS:
            await self._send_status_response(message)
        elif route.intent == BotIntent.PROFILE:
            if not await self.handlers["profile"].handle_profile_command(message):
                await self._send_ai_response(message)
        elif route.intent == BotIntent.CALENDAR_LIST:
            await self.handlers["calendar"].handle_list(message)
        elif route.intent == BotIntent.CALENDAR_SYNC:
            await self.handlers["calendar"].handle_sync(message)
        elif route.intent == BotIntent.CALENDAR_DELETE:
            await self.handlers["calendar"].handle_delete(message)
        elif route.intent == BotIntent.CALENDAR_COMPLETE:
            await self.handlers["calendar"].handle_complete(message)
        elif route.intent == BotIntent.CALENDAR_EDIT:
            await self.handlers["calendar"].handle_edit(message)
        elif route.intent == BotIntent.CALENDAR_CLEAR:
            await self.handlers["calendar"].handle_clear(message)
        elif route.intent == BotIntent.CALENDAR_ITEM:
            await self.handlers["calendar"].handle_calendar_item(message, payload["calendar_item"])
        elif route.intent == BotIntent.POLL_CREATE:
            await self.handlers["polls"].handle_poll(message, payload["poll"])
        elif route.intent == BotIntent.POLL_VOTE:
            await self.handlers["polls"].handle_vote(message, payload["vote"])
        elif route.intent == BotIntent.POLL_EDIT:
            await self.handlers["polls"].handle_poll_edit(message, payload["poll_edit"])
        elif route.intent == BotIntent.POLL_DELETE:
            await self.handlers["polls"].handle_poll_delete(message, payload["poll_delete"])
        elif route.intent == BotIntent.POLL_CLOSE:
            await self.handlers["polls"].handle_poll_close(message, payload["poll_close"])
        elif route.intent == BotIntent.COUNTDOWN:
            await self.handlers["countdown"].handle_countdown(message, payload["countdown"])
        elif route.intent == BotIntent.WATCHLIST:
            await self.handlers["watchlist"].handle_watchlist(message, payload["watchlist"])
        elif route.intent == BotIntent.WORD_OF_DAY:
            await self.handlers["fun"].handle_word_of_day(message)
        elif route.intent == BotIntent.QUOTE:
            await self.handlers["fun"].handle_quote_command(message, payload["quote"])
        elif route.intent == BotIntent.AURORA:
            await self.handlers["aurora"].handle_aurora(message)
        elif route.intent == BotIntent.SCHOOL_HOLIDAYS:
            await self.handlers["school_holidays"].handle_school_holidays(message)
        elif route.intent == BotIntent.PRICE:
            await self.handlers["utility"].handle_price(message, payload["price"])
        elif route.intent == BotIntent.HOROSCOPE:
            await self.handlers["fun"].handle_horoscope(message, payload["horoscope"])
        elif route.intent == BotIntent.COMPLIMENT:
            await self.handlers["fun"].handle_compliment(message, payload["compliment"])
        elif route.intent == BotIntent.CALCULATOR:
            await self.handlers["utility"].handle_calculator(message, payload["calculator"])
        elif route.intent == BotIntent.SHORTEN_URL:
            await self.handlers["utility"].handle_shorten(message, payload["shorten"])
        elif route.intent == BotIntent.DAILY_DIGEST:
            await self.handlers["daily_digest"].handle_daily_digest(message)
        elif route.intent == BotIntent.SET_LOCATION:
            await self._handle_set_location(message, payload["city"])
        else:
            await self._send_ai_response(message)

    async def _send_ai_response(self, message):
        """
        Generate and send an AI response to a mention.
        Uses Hermes AI with personality system.
        """
        print(f"[MONITOR] _send_ai_response called for message: {message.content[:50]}...")

        channel_type = self._get_channel_type(message.channel)
        print(f"[MONITOR] Channel type: {channel_type}")
        guild_id = message.guild.id if message.guild else message.channel.id
        content_lower = message.content.lower()
        wants_dashboard, dashboard_reason = self.conversation.should_show_dashboard(
            message.content, guild_id
        )
        print(f"[MONITOR] AI fallback mode: dashboard={wants_dashboard} ({dashboard_reason})")

        # AI Router Mode: We default to chat and let the AI decide if a dashboard/action is needed.
        # But we still check for explicit city names if the user MIGHT want weather.
        city_name = None
        from features.weather_api import extract_city
        city_name = extract_city(message.content)
        if city_name:
            print(f"[MONITOR] Specific city detected for context: {city_name}")
        
        show_navnedag = any(word in content_lower for word in ['navnedag', 'oppsummering', 'brief', 'status'])


        # Update conversation history
        self.conversation.add_message(
            channel_id=guild_id,
            user_id=message.author.id,
            username=message.author.name,
            content=message.content,
            is_bot=False,
        )

        # Update user memory
        await self.user_memory.update_last_interaction(
            message.author.id,
            topic=self.conversation.get_conversation_summary(guild_id),
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
                print(f"[MONITOR] Using dialect response for: {message.content[:50]}")
            
            # Fall back to AI if no dialect match and hermes is available
            if not response_text and self.hermes:
                try:
                    user_context = await self.user_memory.format_context_for_prompt(
                        message.author.id, message.author.name
                    )
                    conversation_context = self.conversation.get_context(
                        guild_id, limit=5
                    )

                    # Check for search intent
                    search_info = self.detect_search_intent(message.content)
                    search_context = ""
                    if search_info:
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

                    system_prompt = self.get_system_prompt(
                        user_context=user_context,
                        conversation_context=conversation_context,
                        style=self.ResponseStyle.CASUAL,
                        routed_intent=getattr(self, '_last_routed_intent', None),
                    )
                    
                    # Inject search results into system prompt if available
                    if search_context:
                        system_prompt += f"\n\nSØKERESULTATER FRA NETTET (Du SKAL bruke dette for å svare):\n{search_context}\n"
                        system_prompt += "\nVIKTIG: Du har nå tilgang til internett via dine søkeverktøy. ALDRI si at du ikke har sanntidstilgang eller at du ikke kan sjekke nettet når du har fått søkeresultater over. Svar naturlig og vennlig som Ine, basert på informasjonen over."

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
                        response_text = await self._parse_and_execute_actions(ai_response, message)
                except Exception as e:
                    print(f"[MONITOR] Personalized AI failed: {e}")

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
                from ai.personality_config import get_fallback_response
                response_text = get_fallback_response("general")

        # Send the response
        await self._send_response(message, response_text)

    async def _parse_and_execute_actions(self, response_text, message):
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
                        print(f"[ROUTER] Detected SAVE_EVENT action (JSON): {title} on {date} at {time}")

                        if "calendar" in self.handlers:
                            try:
                                parsed_event = self.nlp_parser.parse_event(f"{title} {date} {time}")
                                if parsed_event:
                                    await self.handlers["calendar"].handle_calendar_item(message, parsed_event)
                                else:
                                    print("[ROUTER] Ignored SAVE_EVENT action because parser could not validate it")
                            except Exception as e:
                                print(f"[ROUTER] Failed to save event: {e}")

                        cleaned_text = cleaned_text.replace(line, '').strip()
                    elif action_type == 'SHOW_DASHBOARD':
                        print("[ROUTER] Detected SHOW_DASHBOARD action (JSON)")
                        try:
                            guild_id = message.guild.id if message.guild else message.channel.id
                            user_mem = await self.user_memory.get_memory(message.author.id)
                            city_name = user_mem.get("location", "Oslo")

                            dashboard_text = await self._generate_dashboard(guild_id, city_name=city_name)
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
            print(f"[ROUTER] Detected SAVE_EVENT action: {title} on {date} at {time}")
            
            if "calendar" in self.handlers:
                try:
                    parsed_event = self.nlp_parser.parse_event(f"{title} {date} {time}")
                    if parsed_event:
                        await self.handlers["calendar"].handle_calendar_item(message, parsed_event)
                    else:
                        print("[ROUTER] Ignored SAVE_EVENT action because parser could not validate it")
                except Exception as e:
                    print(f"[ROUTER] Failed to save event: {e}")
            
            cleaned_text = cleaned_text.replace(event_match.group(0), "").strip()

        # 2. Handle [SHOW_DASHBOARD]
        if '[SHOW_DASHBOARD]' in cleaned_text:
            print("[ROUTER] Detected SHOW_DASHBOARD action")
            try:
                guild_id = message.guild.id if message.guild else message.channel.id
                # Get location from user memory
                user_mem = await self.user_memory.get_memory(message.author.id)
                city_name = user_mem.get("location", "Oslo")
                
                dashboard_text = await self._generate_dashboard(guild_id, city_name=city_name)
                await self._send_response(message, dashboard_text)
            except Exception as e:
                print(f"[ROUTER] Failed to show dashboard: {e}")
            
            cleaned_text = cleaned_text.replace('[SHOW_DASHBOARD]', "").strip()
            
        return cleaned_text

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
        from features.weather_api import METWeatherAPI, NORWEGIAN_CITIES

        norwegian_data = get_todays_info()
        weather_api = METWeatherAPI()
        
        # If no city name provided, check user memory
        if not city_name and user_id:
            user_mem = await self.user_memory.get_user(user_id)
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
        """Send response with proper channel handling."""
        try:
            if not response_text:
                print("[MONITOR] Warning: Attempted to send empty response. Skipping.")
                return

            if isinstance(message.channel, (discord.DMChannel, discord.GroupChannel)):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
            print(f"[MONITOR] Response sent to {message.author.name}: {response_text[:100]}...")

            # Add bot response to conversation history
            guild_id = message.guild.id if message.guild else message.channel.id
            self.conversation.add_message(
                channel_id=guild_id,
                user_id=None,
                username="Inebotten",
                content=response_text,
                is_bot=True,
            )

        except discord.errors.Forbidden:
            print("[MONITOR] Forbidden: Cannot send message in this channel")
            self.rate_limiter.record_failure()
        except discord.errors.HTTPException as e:
            print(f"[MONITOR] HTTP error sending message: {e}")
            self.rate_limiter.record_failure(is_rate_limit=(e.status == 429))

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

        self.handlers = {
            "fun": FunHandler(self),
            "utility": UtilityHandler(self),
            "countdown": CountdownHandler(self),
            "polls": PollsHandler(self),
            "calendar": CalendarHandler(self),
            "watchlist": WatchlistHandler(self),
            "aurora": AuroraHandler(self),
            "school_holidays": SchoolHolidaysHandler(self),
            "help": HelpHandler(self),
            "daily_digest": DailyDigestHandler(self),
            "profile": __import__('features.profile_handler', fromlist=['ProfileHandler']).ProfileHandler(self),
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
            )
            await self.console_server.start()
            print(f"[BOT] Web console started on http://{self.config.console_host}:{self.config.console_port}")
            print(f"[BOT] Console API key: {self.config.console_api_key[:8]}...")
            self._setup_signal_handlers()
        except Exception as e:
            self.console_server = None
            print(f"[BOT] WARNING: Could not start web console: {e}")

    async def on_ready(self):
        """Called when bot is ready"""
        self.start_time = datetime.now()
        print(f"[BOT] Logged in as {self.user} (ID: {self.user.id})")
        print(f"[BOT] Connected to {len(self.guilds)} guilds")
        print(
            f"[BOT] Rate limit: {self.config.MAX_MSGS_PER_SECOND}/sec, {self.config.DAILY_QUOTA}/day"
        )

        # Initialize message monitor
        self.monitor = MessageMonitor(
            client=self,
            hermes_connector=self.hermes,
            rate_limiter=self.rate_limiter,
            response_generator=self.response_gen,
        )
        await self.monitor.setup()

        await self.start_console()
        if self.console_server:
            self.console_server.monitor = self.monitor

        # Initialize and start calendar reminder checker
        self.reminder_checker = self._create_reminder_checker()
        if self.reminder_checker:
            await self.reminder_checker.setup()
            asyncio.create_task(self.reminder_checker.start())
            print("[BOT] Calendar reminder checker started")

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

    def _create_reminder_checker(self):
        """Create a ReminderChecker wired to the bot's channels."""
        from cal_system.reminder_checker import ReminderChecker
        from cal_system.calendar_manager import CalendarManager
        from cal_system.reminder_manager import ReminderManager

        calendar = self.monitor.calendar if self.monitor else CalendarManager()
        reminders = ReminderManager()

        def get_channel(channel_id: int):
            return self.get_channel(channel_id)

        return ReminderChecker(
            calendar_manager=calendar,
            reminder_manager=reminders,
            get_channel_func=get_channel,
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
        if self.monitor:
            await self.monitor.handle_message(message)

    async def on_disconnect(self):
        """Called when disconnected"""
        print("[BOT] Disconnected from Discord")

    async def on_resumed(self):
        """Called when session is resumed"""
        print("[BOT] Session resumed")

    async def close(self):
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
