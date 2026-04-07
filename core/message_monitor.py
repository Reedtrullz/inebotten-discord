#!/usr/bin/env python3
"""
Message Monitor for Discord Selfbot
Polls DMs and detects @inebotten mentions using discord.py
"""

import asyncio
import re
from collections import deque
from datetime import datetime

import discord


# Keyword sets for command matching
CALENDAR_KEYWORDS = [
    "kalender", "calendar", "arrangementer", "events",
    "kommende", "planlagt", "påminnelser", "huskeliste",
]

DELETE_KEYWORDS = ["slett", "delete", "fjern"]
COMPLETE_KEYWORDS = ["ferdig", "done", "complete", "fullført"]
EDIT_KEYWORDS = ["endre", "edit", "oppdater"]
WORD_OF_DAY_KEYWORDS = ["dagens ord", "word of the day", "lære meg et ord"]
AURORA_KEYWORDS = ["nordlys", "aurora", "nordly"]
SCHOOL_HOLIDAYS_KEYWORDS = [
    "skoleferie", "skoleferier", "vinterferie", "påskeferie"
]
DAILY_DIGEST_KEYWORDS = [
    "daglig oppsummering", "daily digest", "oppsummering", "summary"
]
HELP_KEYWORDS = [
    "hjelp", "help", "kommandoer", "commands",
    "hva kan du gjøre", "hva kan du", "hva gjør du",
    "funksjoner", "features", "capabilities",
    "hva er du", "hvem er du", "what can you do",
]


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

        self.calendar = CalendarManager()
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
        self.daily_digest = DailyDigestManager(self.calendar)

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

        # Handler Registry
        self.handlers = {}
        self._register_handlers()

    def is_mention(self, message):
        """Check if message mentions the bot"""
        content = message.content.lower()

        # Check for @inebotten mention
        if self.bot_mention.lower() in content:
            return True

        # Check for bot mention via Discord mention syntax
        if self.client.user:
            mention_strings = [
                f"<@{self.client.user.id}>",
                f"<@!{self.client.user.id}>",
            ]
            for mention in mention_strings:
                if mention in message.content:
                    return True

        return False

    async def handle_message(self, message):
        """Process an incoming message"""
        # Skip own messages
        if message.author.id == self.client.user.id:
            return

        # Skip already processed
        msg_id = f"{message.channel.id}:{message.id}"
        if msg_id in self.processed_messages:
            return
        self.processed_messages.append(msg_id)

        # Check for mention
        if not self.is_mention(message):
            return

        self.mention_count += 1
        print(
            f"[MONITOR] Mention detected from {message.author.name}: {message.content[:50]}..."
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

        try:
            # Check for natural language calendar items
            parsed = self.nlp_parser.parse_task_with_recurrence(message.content)
            if not parsed:
                parsed = self.nlp_parser.parse_event(message.content)

            if parsed:
                print(f"[MONITOR] Calendar item matched: {parsed}")
                await self.handlers["calendar"].handle_calendar_item(message, parsed)
                return
        except (ValueError, KeyError, AttributeError) as e:
            print(f"[MONITOR] Calendar parser error: {e}")

        # Get lowercase content once for all keyword checks
        content_lower = message.content.lower()

        # Check for calendar list command
        if any(word in content_lower for word in CALENDAR_KEYWORDS):
            print("[MONITOR] Matched: calendar list command")
            await self.handlers["calendar"].handle_list(message)
            return

        # Check for delete item command
        if any(phrase in content_lower for phrase in DELETE_KEYWORDS):
            print("[MONITOR] Matched: delete item command")
            await self.handlers["calendar"].handle_delete(message)
            return

        # Check for complete item command
        if any(word in content_lower for word in COMPLETE_KEYWORDS):
            print("[MONITOR] Matched: complete item command")
            await self.handlers["calendar"].handle_complete(message)
            return

        # Check for edit event command
        if any(phrase in content_lower for phrase in EDIT_KEYWORDS):
            print("[MONITOR] Matched: edit event command")
            await self.handlers["calendar"].handle_edit(message)
            return

        # Check for countdown queries
        print("[MONITOR] Checking countdown...")
        countdown_result = self.countdown.parse_countdown_query(message.content)
        if countdown_result:
            print("[MONITOR] Matched: countdown query")
            await self.handlers["countdown"].handle_countdown(message, countdown_result)
            return

        # Check for poll commands
        print("[MONITOR] Checking poll...")
        poll_cmd = self.parse_poll_command(message.content)
        if poll_cmd:
            print("[MONITOR] Matched: poll command")
            await self.handlers["polls"].handle_poll(message, poll_cmd)
            return

        # Check for vote
        print("[MONITOR] Checking vote...")
        vote = self.parse_vote(message.content)
        if vote:
            print("[MONITOR] Matched: vote")
            await self.handlers["polls"].handle_vote(message, vote)
            return

        # Check for watchlist commands
        print("[MONITOR] Checking watchlist...")
        watchlist_cmd = self.parse_watchlist_command(message.content)
        if watchlist_cmd:
            print("[MONITOR] Matched: watchlist command")
            await self.handlers["watchlist"].handle_watchlist(message, watchlist_cmd)
            return

        # Check for word of the day
        if any(phrase in content_lower for phrase in WORD_OF_DAY_KEYWORDS):
            print("[MONITOR] Matched: word of the day")
            await self.handlers["fun"].handle_word_of_day(message)
            return

        # Check for quote commands
        quote_cmd = self.parse_quote_command(message.content)
        if quote_cmd:
            print("[MONITOR] Matched: quote command")
            await self.handlers["fun"].handle_quote_command(message, quote_cmd)
            return

        # Check for aurora/nordlys command
        if any(word in content_lower for word in AURORA_KEYWORDS):
            print("[MONITOR] Matched: aurora command")
            await self.handlers["aurora"].handle_aurora(message)
            return

        # Check for school holidays command
        if any(phrase in content_lower for phrase in SCHOOL_HOLIDAYS_KEYWORDS):
            print("[MONITOR] Matched: school holidays")
            await self.handlers["school_holidays"].handle_school_holidays(message)
            return

        # Check for crypto/stock price commands
        price_cmd = self.parse_price_command(message.content)
        if price_cmd:
            print("[MONITOR] Matched: price command")
            await self.handlers["utility"].handle_price(message, price_cmd)
            return

        # Check for horoscope commands FIRST (before compliment)
        horoscope_cmd = self.parse_horoscope_command(message.content)
        if horoscope_cmd:
            print("[MONITOR] Matched: horoscope command")
            await self.handlers["fun"].handle_horoscope(message, horoscope_cmd)
            return

        # Check for compliment commands
        compliment_cmd = self.parse_compliment_command(message.content)
        if compliment_cmd:
            print("[MONITOR] Matched: compliment command")
            await self.handlers["fun"].handle_compliment(message, compliment_cmd)
            return

        # Check for calculator/conversion commands
        calc_cmd = self.parse_calculator_command(message.content)
        if calc_cmd:
            print("[MONITOR] Matched: calculator command")
            await self.handlers["utility"].handle_calculator(message, calc_cmd)
            return

        # Check for URL shorten commands
        shorten_cmd = self.parse_shorten_command(message.content)
        if shorten_cmd:
            print("[MONITOR] Matched: url shorten")
            await self.handlers["utility"].handle_shorten(message, shorten_cmd)
            return

        # Check for daily digest
        if any(phrase in content_lower for phrase in DAILY_DIGEST_KEYWORDS):
            print("[MONITOR] Matched: daily digest")
            await self.handlers["daily_digest"].handle_daily_digest(message)
            return

        # Check for help command
        if any(word in content_lower for word in HELP_KEYWORDS):
            print("[MONITOR] Matched: help command")
            await self.handlers["help"].handle_help(message)
            return

        # Generate and send AI response
        print("[MONITOR] No command matched, falling back to AI response...")
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
        wants_dashboard, reason = self.conversation.should_show_dashboard(
            message.content, guild_id
        )
        print(f"[MONITOR] Intent detection: wants_dashboard={wants_dashboard}, reason={reason}")

        # Update conversation history
        self.conversation.add_message(
            channel_id=guild_id,
            user_id=message.author.id,
            username=message.author.name,
            content=message.content,
            is_bot=False,
        )

        # Update user memory
        self.user_memory.update_last_interaction(
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
                    user_context = self.user_memory.format_context_for_prompt(
                        message.author.id, message.author.name
                    )
                    conversation_context = self.conversation.get_context(
                        guild_id, limit=5
                    )

                    system_prompt = self.get_system_prompt(
                        user_context=user_context,
                        conversation_context=conversation_context,
                        style=self.ResponseStyle.CASUAL,
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
                        response_text = ai_response
                        print("[MONITOR] Using personalized AI response")
                except Exception as e:
                    print(f"[MONITOR] Personalized AI failed: {e}")

        # Fallback: dashboard or basic response
        if not response_text:
            if wants_dashboard:
                response_text = await self._generate_dashboard(guild_id)
            else:
                from ai.personality_config import get_fallback_response
                response_text = get_fallback_response("general")

        # Send the response
        await self._send_response(message, response_text)

    async def _generate_dashboard(self, guild_id: int) -> str:
        """Generate dashboard response with weather, events, etc."""
        from cal_system.norwegian_calendar import get_todays_info
        from features.weather_api import METWeatherAPI

        norwegian_data = get_todays_info()
        weather_api = METWeatherAPI()
        weather_data = await weather_api.get_weather()
        await weather_api.close()

        if weather_data:
            weather_formatted = {
                "conditions": weather_data["condition"],
                "temp": weather_data["temp"],
            }
        else:
            weather_formatted = {"conditions": "Delvis skyet", "temp": 8}

        upcoming_items = self.calendar.get_upcoming(guild_id, days=7)

        dashboard = self.conv_gen.generate_dashboard(
            weather_data=weather_formatted,
            events=upcoming_items,
            reminders=[],
            norwegian_data=norwegian_data,
        )

        return dashboard

    async def _send_response(self, message, response_text):
        """Send response with proper channel handling."""
        try:
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

    def get_handlers_status(self):
        """Get status of all handlers"""
        status = {}
        for name, handler in self.handlers.items():
            status[name] = "loaded" if handler is not None else "not loaded"
        return status

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
        }


class SelfbotClient(discord.Client):
    """Custom Discord client with selfbot functionality"""

    def __init__(
        self, config, auth_handler, rate_limiter, hermes_connector, response_generator
    ):
        super().__init__(max_messages=10000, self_bot=True)

        self.config = config
        self.auth_handler = auth_handler
        self.rate_limiter = rate_limiter
        self.hermes = hermes_connector
        self.response_gen = response_generator

        self.monitor = None
        self.start_time = None

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

        # Initialize and start calendar reminder checker
        self.reminder_checker = self._create_reminder_checker()
        if self.reminder_checker:
            asyncio.create_task(self.reminder_checker.start())
            print("[BOT] Calendar reminder checker started")

        # Check Hermes health
        healthy, message = await self.hermes.check_health()
        if healthy:
            print(f"[BOT] Hermes API: {message}")
        else:
            print(f"[BOT] WARNING: Hermes API issue - {message}")
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
            "hermes": self.hermes.get_stats(),
        }

        if self.monitor:
            stats["monitor"] = self.monitor.get_stats()

        return stats


def create_monitor(client, hermes_connector, rate_limiter, response_generator):
    """Factory function to create MessageMonitor"""
    return MessageMonitor(client, hermes_connector, rate_limiter, response_generator)
