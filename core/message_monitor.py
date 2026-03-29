#!/usr/bin/env python3
"""
Message Monitor for Discord Selfbot
Polls DMs and detects @inebotten mentions using discord.py
"""

import asyncio
import discord
from datetime import datetime


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

        # Initialize unified calendar manager (replaces separate event/reminder systems)
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

        # Initialize calendar handler (after loc is available)
        from features.calendar_handler import CalendarHandler

        self.calendar_handler = CalendarHandler(self)

        # Initialize new feature managers
        from features.countdown_manager import CountdownManager
        from features.poll_manager import PollManager, parse_poll_command, parse_vote
        from features.watchlist_manager import WatchlistManager, parse_watchlist_command
        from features.word_of_day import WordOfTheDay
        from features.quote_manager import QuoteManager, parse_quote_command
        from features.crypto_manager import CryptoManager, parse_price_command
        from features.compliments_manager import (
            ComplimentsManager,
            parse_compliment_command,
        )
        from features.horoscope_manager import HoroscopeManager, parse_horoscope_command
        from features.calculator_manager import (
            CalculatorManager,
            parse_calculator_command,
        )
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

        # Tracking
        self.processed_messages = set()
        self.mention_count = 0
        self.response_count = 0
        self.error_count = 0

        # Handler Registry - modular handler objects
        self.handlers = {}
        self._register_handlers()

    def is_mention(self, message):
        """
        Check if message mentions the bot
        """
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
        """
        Process an incoming message
        """
        # Skip own messages
        if message.author.id == self.client.user.id:
            return

        # Skip already processed
        msg_id = f"{message.channel.id}:{message.id}"
        if msg_id in self.processed_messages:
            return
        self.processed_messages.add(msg_id)

        # Clean old processed messages (keep last 1000)
        if len(self.processed_messages) > 1000:
            self.processed_messages = set(list(self.processed_messages)[-500:])

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

        # Check for natural language calendar items (events, tasks, recurring items)
        print(f"[MONITOR] Checking natural language calendar parser...")
        try:
            # First try recurring task pattern (e.g., "Jeg må ... på ... og ... deretter")
            parsed = self.nlp_parser.parse_task_with_recurrence(message.content)

            # If not a recurring pattern, try general calendar parsing
            if not parsed:
                parsed = self.nlp_parser.parse_event(message.content)

            if parsed:
                print(f"[MONITOR] Calendar item matched: {parsed}")
                await self._handle_calendar_item(message, parsed)
                return
            print(f"[MONITOR] No calendar match")
        except Exception as e:
            print(f"[MONITOR] Error in calendar parser: {e}")
            import traceback

            traceback.print_exc()

        # Check for calendar list command
        print(f"[MONITOR] Checking command matchers...")
        content_lower = message.content.lower()
        if any(
            word in content_lower
            for word in [
                "kalender",
                "calendar",
                "arrangementer",
                "events",
                "kommende",
                "planlagt",
                "påminnelser",
                "huskeliste",
            ]
        ):
            print(f"[MONITOR] Matched: calendar list command")
            if hasattr(self.calendar_handler, "handle_list"):
                await self.calendar_handler.handle_list(message)
            else:
                await self._handle_list_calendar(message)
            return

        # Check for delete item command
        if any(phrase in content_lower for phrase in ["slett", "delete", "fjern"]):
            print(f"[MONITOR] Matched: delete item command")
            if hasattr(self.calendar_handler, "handle_delete"):
                await self.calendar_handler.handle_delete(message)
            else:
                await self._handle_delete_item(message)
            return

        # Check for complete item command
        if any(
            word in content_lower for word in ["ferdig", "done", "complete", "fullført"]
        ):
            print(f"[MONITOR] Matched: complete item command")
            if hasattr(self.calendar_handler, "handle_complete"):
                await self.calendar_handler.handle_complete(message)
            else:
                await self._handle_complete_item(message)
            return

        # Check for edit event command (keep for now)
        if any(phrase in content_lower for phrase in ["endre", "edit", "oppdater"]):
            print(f"[MONITOR] Matched: edit event command")
            if hasattr(self.calendar_handler, "handle_edit"):
                await self.calendar_handler.handle_edit(message)
            else:
                await self._handle_edit_event(message)
            return

        # Check for countdown queries
        print(f"[MONITOR] Checking countdown...")
        countdown_result = self.countdown.parse_countdown_query(message.content)
        if countdown_result:
            print(f"[MONITOR] Matched: countdown query")
            countdown_handler = self.handlers.get("countdown")
            if countdown_handler:
                await countdown_handler.handle_countdown(message, countdown_result)
            else:
                await self._handle_countdown(message, countdown_result)
            return

        # Check for poll commands
        print(f"[MONITOR] Checking poll...")
        poll_cmd = self.parse_poll_command(message.content)
        if poll_cmd:
            print(f"[MONITOR] Matched: poll command")
            polls_handler = self.handlers.get("polls")
            if polls_handler:
                await polls_handler.handle_poll(message, poll_cmd)
            else:
                await self._handle_poll_command(message, poll_cmd)
            return

        # Check for vote
        print(f"[MONITOR] Checking vote...")
        vote = self.parse_vote(message.content)
        if vote:
            print(f"[MONITOR] Matched: vote")
            polls_handler = self.handlers.get("polls")
            if polls_handler:
                await polls_handler.handle_vote(message, vote)
            else:
                await self._handle_vote(message, vote)
            return

        # Check for watchlist commands
        print(f"[MONITOR] Checking watchlist...")
        watchlist_cmd = self.parse_watchlist_command(message.content)
        if watchlist_cmd:
            print(f"[MONITOR] Matched: watchlist command")
            watchlist_handler = self.handlers.get("watchlist")
            if watchlist_handler:
                await watchlist_handler.handle_watchlist(message, watchlist_cmd)
            else:
                await self._handle_watchlist_command(message, watchlist_cmd)
            return

        # Check for word of the day
        if any(
            phrase in content_lower
            for phrase in ["dagens ord", "word of the day", "lære meg et ord"]
        ):
            print(f"[MONITOR] Matched: word of the day")
            fun_handler = self.handlers.get("fun")
            if fun_handler:
                await fun_handler.handle_word_of_day(message)
            else:
                await self._handle_word_of_day(message)
            return

        # Check for quote commands
        quote_cmd = self.parse_quote_command(message.content)
        if quote_cmd:
            print(f"[MONITOR] Matched: quote command")
            fun_handler = self.handlers.get("fun")
            if fun_handler:
                await fun_handler.handle_quote_command(message, quote_cmd)
            else:
                await self._handle_quote_command(message, quote_cmd)
            return

        # Check for aurora/nordlys command
        if any(word in content_lower for word in ["nordlys", "aurora", "nordly"]):
            print(f"[MONITOR] Matched: aurora command")
            if hasattr(self, "aurora_handler"):
                await self.aurora_handler.handle_aurora(message)
            else:
                await self._handle_aurora_command(message)
            return

        # Check for school holidays command
        if any(
            phrase in content_lower
            for phrase in ["skoleferie", "skoleferier", "vinterferie", "påskeferie"]
        ):
            print(f"[MONITOR] Matched: school holidays")
            if hasattr(self, "school_holidays_handler"):
                await self.school_holidays_handler.handle_school_holidays(message)
            else:
                await self._handle_school_holidays_command(message)
            return

        # Check for crypto/stock price commands
        price_cmd = self.parse_price_command(message.content)
        if price_cmd:
            print(f"[MONITOR] Matched: price command")
            util_handler = self.handlers.get("utility")
            if util_handler:
                await util_handler.handle_price(message, price_cmd)
            else:
                await self._handle_price_command(message, price_cmd)
            return

        # Check for compliment/roast commands
        # Check for horoscope commands FIRST (before compliment to avoid "horoskop" matching "kompliment")
        horoscope_cmd = self.parse_horoscope_command(message.content)
        if horoscope_cmd:
            print(f"[MONITOR] Matched: horoscope command")
            fun_handler = self.handlers.get("fun")
            if fun_handler:
                await fun_handler.handle_horoscope(message, horoscope_cmd)
            else:
                await self._handle_horoscope_command(message, horoscope_cmd)
            return

        # Check for compliment commands
        compliment_cmd = self.parse_compliment_command(message.content)
        if compliment_cmd:
            print(f"[MONITOR] Matched: compliment command")
            fun_handler = self.handlers.get("fun")
            if fun_handler:
                await fun_handler.handle_compliment(message, compliment_cmd)
            else:
                await self._handle_compliment_command(message, compliment_cmd)
            return

        # Check for calculator/conversion commands
        calc_cmd = self.parse_calculator_command(message.content)
        if calc_cmd:
            print(f"[MONITOR] Matched: calculator command")
            util_handler = self.handlers.get("utility")
            if util_handler:
                await util_handler.handle_calculator(message, calc_cmd)
            else:
                await self._handle_calculator_command(message, calc_cmd)
            return

        # Check for URL shorten commands
        shorten_cmd = self.parse_shorten_command(message.content)
        if shorten_cmd:
            print(f"[MONITOR] Matched: url shorten")
            util_handler = self.handlers.get("utility")
            if util_handler:
                await util_handler.handle_shorten(message, shorten_cmd)
            else:
                await self._handle_shorten_command(message, shorten_cmd)
            return

        # Check for daily digest
        if any(
            phrase in content_lower
            for phrase in [
                "daglig oppsummering",
                "daily digest",
                "oppsummering",
                "summary",
            ]
        ):
            print(f"[MONITOR] Matched: daily digest")
            if hasattr(self, "daily_digest_handler"):
                await self.daily_digest_handler.handle_daily_digest(message)
            else:
                await self._handle_daily_digest(message)
            return

        # Check for help command
        if any(
            word in content_lower
            for word in ["hjelp", "help", "kommandoer", "commands"]
        ):
            print(f"[MONITOR] Matched: help command")
            if hasattr(self, "help_handler"):
                await self.help_handler.handle_help(message)
            else:
                await self._handle_help_command(message)
            return

        # Generate and send AI response
        print(f"[MONITOR] No command matched, falling back to AI response...")
        try:
            await self._send_response(message)
        except Exception as e:
            print(f"[MONITOR] Error sending response: {e}")
            import traceback

            traceback.print_exc()
            self.error_count += 1

    async def _handle_calendar_item(self, message, item_data):
        """
        Handle natural language calendar item creation (unified events + tasks)
        """
        try:
            guild_id = message.guild.id if message.guild else message.channel.id

            # Sync to Google Calendar if available
            gcal_event_id = None
            gcal_link = None

            try:
                if self.calendar.gcal_enabled:
                    print(f"[MONITOR] Syncing to Google Calendar: {item_data['title']}")

                    # Convert DD.MM.YYYY to ISO format for GCal
                    day, month, year = item_data["date"].split(".")
                    start_iso = f"{year}-{month.zfill(2)}-{day.zfill(2)}T{item_data.get('time', '09:00')}:00"
                    end_time = f"{int(item_data.get('time', '09:00').split(':')[0]) + 1:02d}:{item_data.get('time', '09:00').split(':')[1] if ':' in item_data.get('time', '09:00') else '00'}"
                    end_iso = f"{year}-{month.zfill(2)}-{day.zfill(2)}T{end_time}:00"

                    gcal_result = self.calendar.gcal.create_event(
                        title=item_data["title"],
                        start_time=start_iso,
                        end_time=end_iso,
                        description=item_data["title"],
                        recurrence=item_data.get("recurrence"),
                        rrule_day=item_data.get("rrule_day"),
                    )
                    if gcal_result:
                        gcal_event_id = gcal_result.get("id")
                        gcal_link = gcal_result.get("htmlLink")
                        print(f"[MONITOR] GCal sync successful: {gcal_link}")
                    else:
                        print(f"[MONITOR] GCal sync returned no result")
                else:
                    print(f"[MONITOR] GCal not enabled, skipping sync")
            except Exception as e:
                print(f"[MONITOR] GCal sync failed: {e}")
                import traceback

                traceback.print_exc()

            # Add to calendar
            item = self.calendar.add_item(
                guild_id=guild_id,
                user_id=message.author.id,
                username=message.author.name,
                title=item_data["title"],
                date_str=item_data["date"],
                time_str=item_data.get("time"),
                recurrence=item_data.get("recurrence"),
                recurrence_day=item_data.get("recurrence_day"),
                rrule_day=item_data.get("rrule_day"),
                gcal_event_id=gcal_event_id,
                gcal_link=gcal_link,
            )

            if item:
                response_text = self.calendar.format_single_item(item)
                self.rate_limiter.record_sent()
                self.response_count += 1
            else:
                response_text = (
                    "❌ Beklager, jeg klarte ikke å legge til i kalenderen. Prøv igjen!"
                )

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

        except Exception as e:
            print(f"[MONITOR] Error handling calendar item: {e}")

    async def _handle_delete_item(self, message):
        """
        Handle calendar item deletion
        Supports: '@inebotten slett [nummer]'
        """
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            content_lower = message.content.lower()

            # Remove Discord mentions before extracting number
            content_clean = re.sub(r"<@!?\d+>", "", content_lower).strip()

            # Extract number from message
            num_match = re.search(r"\b(\d+)\b", content_clean)

            if num_match:
                item_num = int(num_match.group(1))
                success, title = self.calendar.delete_item(guild_id, item_num)

                if success:
                    response_text = f"✅ **Slettet!** {title}"
                else:
                    response_text = "❌ Fant ikke noe med det nummeret. Bruk `@inebotten kalender` for å se listen."
            else:
                # No number provided, show calendar
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = f"📋 Hva vil du slette?\n\n{calendar_text}"
                else:
                    response_text = "📭 Kalenderen er tom."

            # Send response
            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1

        except Exception as e:
            print(f"[MONITOR] Error deleting item: {e}")

    async def _handle_complete_item(self, message):
        """
        Handle completing a calendar item
        Supports: '@inebotten ferdig [nummer]'
        """
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            content_lower = message.content.lower()

            # Remove Discord mentions before extracting number
            content_clean = re.sub(r"<@!?\d+>", "", content_lower)

            # Extract number
            num_match = re.search(r"\b(\d+)\b", content_clean)

            if num_match:
                item_num = int(num_match.group(1))
                success, title, next_date = self.calendar.complete_item(
                    guild_id, item_num
                )

                if success:
                    if next_date:
                        response_text = f"✅ **Fullført!**\n\n✓ ~~{title}~~\n\n📅 Neste gang: {next_date}\n\nBra jobba! 🎉"
                    else:
                        response_text = (
                            f"✅ **Fullført!**\n\n✓ ~~{title}~~\n\nBra jobba! 🎉"
                        )
                else:
                    response_text = "❌ Fant ikke noe med det nummeret. Bruk `@inebotten kalender` for å se listen."
            else:
                # No number, show calendar
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = (
                        f"📝 Hvilket vil du markere som fullført?\n\n{calendar_text}"
                    )
                else:
                    response_text = "📭 Kalenderen er tom."

            # Send response
            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1

        except Exception as e:
            print(f"[MONITOR] Error completing item: {e}")

    async def _handle_edit_event(self, message):
        """
        Handle event editing
        Supports: '@inebotten endre arrangement [nummer/navn] til [ny dato/tid]'
        """
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            content_lower = message.content.lower()

            # Get upcoming items
            items = self.calendar.get_upcoming(guild_id, days=365)

            if not items:
                response_text = "📭 **Ingen arrangementer å endre**\n\nDet er ingen aktive arrangementer."
            else:
                response_text = "📝 **Endre arrangement**\n\n"
                response_text += (
                    "For å endre et arrangement, slett det først og lag et nytt:\n\n"
                )
                for i, item in enumerate(items[:5], 1):
                    response_text += f"{i}. **{item['title']}** - {item['date']}\n"
                response_text += "\nBruk: `@inebotten slett [nummer]`\n"
                response_text += (
                    "Deretter: `@inebotten [nytt arrangement] [dato] [tid]`"
                )

            # Send response
            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1

        except Exception as e:
            print(f"[MONITOR] Error editing event: {e}")

    async def _handle_countdown(self, message, countdown_result):
        """Handle countdown queries"""
        try:
            lang = self.loc.current_lang
            response_text = self.countdown.format_response(countdown_result, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling countdown: {e}")

    async def _handle_poll_command(self, message, poll_cmd):
        """Handle poll creation"""
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            lang = poll_cmd.get("lang", self.loc.current_lang)

            poll = self.poll.create_poll(
                guild_id=guild_id,
                question=poll_cmd["question"],
                options=poll_cmd["options"],
                created_by=message.author.name,
            )

            response_text = self.poll.format_poll(poll, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error creating poll: {e}")

    async def _handle_vote(self, message, vote_num):
        """Handle voting"""
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            lang = self.loc.current_lang

            # Get active polls
            active_polls = self.poll.get_active_polls(guild_id)

            if not active_polls:
                response_text = self.loc.t("no_active_polls") + " 📊"
            else:
                # Vote on the most recent poll
                poll = active_polls[-1]
                success, msg = self.poll.vote(
                    guild_id,
                    poll["id"],
                    vote_num,
                    message.author.id,
                    message.author.name,
                )

                if success:
                    response_text = self.loc.t("vote_registered", num=vote_num)
                else:
                    response_text = self.loc.t("vote_error", error=msg)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling vote: {e}")

    async def _handle_watchlist_command(self, message, watchlist_cmd):
        """Handle watchlist commands"""
        try:
            lang = watchlist_cmd.get("lang", self.loc.current_lang)

            if watchlist_cmd["action"] == "suggest":
                suggestion = self.watchlist.get_random_suggestion(
                    watchlist_cmd.get("type"), watchlist_cmd.get("genre")
                )
                if suggestion:
                    response_text = self.watchlist.format_suggestion(suggestion, lang)
                else:
                    response_text = self.loc.t("no_suggestions")

            elif watchlist_cmd["action"] == "status":
                response_text = self.watchlist.format_watchlist_status(lang)

            else:
                response_text = self.loc.t("watchlist_help")

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling watchlist: {e}")

    async def _handle_word_of_day(self, message):
        """Handle word of the day request"""
        try:
            lang = self.loc.current_lang
            word = self.wod.get_word_of_day(lang)
            response_text = self.wod.format_word(word, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling word of day: {e}")

    async def _handle_quote_command(self, message, quote_cmd):
        """Handle quote commands"""
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            lang = quote_cmd.get("lang", self.loc.current_lang)

            if quote_cmd["action"] == "save":
                # Save the quote
                self.quote.add_quote(
                    guild_id=guild_id,
                    text=quote_cmd["text"],
                    author=message.author.name,
                )
                response_text = self.quote.format_confirmation(quote_cmd["text"], lang)

            elif quote_cmd["action"] == "get":
                # Get random quote
                quote = self.quote.get_random_quote(guild_id)
                if quote:
                    response_text = self.quote.format_quote(quote, lang)
                else:
                    response_text = self.loc.t("no_quotes")

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling quote: {e}")

    async def _handle_price_command(self, message, price_cmd):
        """Handle crypto/stock price commands"""
        try:
            lang = self.loc.current_lang

            price_data = await self.crypto.get_price(price_cmd)
            response_text = self.crypto.format_price(price_data, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling price command: {e}")

    async def _handle_compliment_command(self, message, compliment_cmd):
        """Handle compliment/roast commands"""
        try:
            lang = self.loc.current_lang

            if compliment_cmd["action"] == "compliment":
                text = self.compliments.get_compliment(lang)
                response_text = self.compliments.format_compliment(
                    text, compliment_cmd.get("user"), lang
                )
            else:  # roast
                text = self.compliments.get_roast(lang)
                response_text = self.compliments.format_roast(
                    text, compliment_cmd.get("user"), lang
                )

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling compliment: {e}")

    async def _handle_horoscope_command(self, message, horoscope_cmd):
        """Handle horoscope commands"""
        try:
            lang = self.loc.current_lang

            horoscope_data = self.horoscope.get_horoscope(horoscope_cmd["sign"], lang)
            response_text = self.horoscope.format_horoscope(horoscope_data, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling horoscope: {e}")

    async def _handle_calculator_command(self, message, calc_cmd):
        """Handle calculator/conversion commands"""
        try:
            lang = self.loc.current_lang

            response_text = self.calculator.calculate(calc_cmd, lang)

            if response_text:
                if isinstance(message.channel, discord.DMChannel):
                    await message.channel.send(response_text)
                elif isinstance(message.channel, discord.GroupChannel):
                    await message.channel.send(response_text)
                else:
                    await message.reply(response_text, mention_author=False)

                self.rate_limiter.record_sent()
                self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling calculator: {e}")

    async def _handle_shorten_command(self, message, shorten_cmd):
        """Handle URL shorten commands"""
        try:
            lang = self.loc.current_lang

            short_data = self.url_shortener.shorten_url(shorten_cmd["url"])
            response_text = self.url_shortener.format_short_url(short_data, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling URL shorten: {e}")

    async def _handle_list_calendar(self, message):
        """
        Handle listing calendar (unified events + tasks)
        """
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            calendar_text = self.calendar.format_list(guild_id, days=90)

            if calendar_text:
                response_text = calendar_text
            else:
                response_text = "📭 **Kalenderen er tom**\n\nLegg til med:\n• `@inebotten [noe] på [dato]`\n• `@inebotten Jeg må [gjøremål] på [dato]`"

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.rate_limiter.record_sent()
            self.response_count += 1

        except Exception as e:
            print(f"[MONITOR] Error handling list calendar: {e}")

    def _calculate_days_until(self, date_str):
        """Calculate days until a date string (DD.MM.YYYY)"""
        try:
            from datetime import datetime

            event_date = datetime.strptime(date_str, "%d.%m.%Y")
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            delta = event_date - today
            return delta.days
        except Exception as e:
            print(f"[MONITOR] Date parse error: {e}")
            return 999

    # NOTE: _handle_reminder_command and _handle_recurring_task are now consolidated
    # into _handle_calendar_item which handles all calendar items (events, tasks, recurring items)

    async def _send_response(self, message):
        """
        Generate and send a conversational response to a mention
        Uses Hermes AI with personality system, falls back to local dashboard only when appropriate
        """
        print(f"[MONITOR] _send_response called for message: {message.content[:50]}...")

        # Determine channel type
        channel_type = self._get_channel_type(message.channel)
        print(f"[MONITOR] Channel type: {channel_type}")

        # Check if user wants dashboard or just chat
        guild_id = message.guild.id if message.guild else message.channel.id
        wants_dashboard, reason = self.conversation.should_show_dashboard(
            message.content, guild_id
        )
        print(
            f"[MONITOR] Intent detection: wants_dashboard={wants_dashboard}, reason={reason}"
        )

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
            try:
                if self.hermes:
                    # Build personalized system prompt
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

                    print(
                        f"[MONITOR] Using personalized system prompt ({len(system_prompt)} chars)"
                    )
                    print(f"[MONITOR] System prompt preview: {system_prompt[:200]}...")

                    # Try AI with personality
                    success, ai_response = await self.hermes.generate_response(
                        message_content=message.content,
                        author_name=message.author.name,
                        channel_type=channel_type,
                        is_mention=True,
                        system_prompt=system_prompt,  # Pass custom personality
                    )

                    if success and ai_response:
                        response_text = ai_response
                        print(f"[MONITOR] Using personalized AI response")
            except Exception as e:
                print(f"[MONITOR] Personalized AI failed: {e}")

        # Fallback: dashboard or basic response
        if not response_text:
            if wants_dashboard:
                # Show dashboard
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

                # Add personalized greeting if we know the user
                user = self.user_memory.get_user(message.author.id, message.author.name)
                greeting = ""
                if user.get("username") or user.get("last_interaction"):
                    greeting = (
                        self.user_memory.get_personalized_greeting(
                            message.author.id, message.author.name
                        )
                        + "\n\n"
                    )

                dashboard = self.conv_gen.generate_dashboard(
                    weather_data=weather_formatted,
                    events=upcoming_items,
                    reminders=[],
                    norwegian_data=norwegian_data,
                )
                response_text = greeting + dashboard
            else:
                # Just a simple chat response
                from ai.personality_config import get_fallback_response

                response_text = get_fallback_response("general")

        # Send the response
        try:
            # For DMs, reply directly
            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            # For group DMs
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            # For guild channels, reply in channel
            else:
                await message.reply(response_text, mention_author=False)

            # Record successful send
            self.rate_limiter.record_sent()
            self.response_count += 1
            print(
                f"[MONITOR] Response sent to {message.author.name}: {response_text[:100]}..."
            )

            # Add bot response to conversation history
            self.conversation.add_message(
                channel_id=guild_id,
                user_id=None,  # Bot has no user ID
                username="Inebotten",
                content=response_text,
                is_bot=True,
            )

        except discord.errors.Forbidden:
            print(f"[MONITOR] Forbidden: Cannot send message in this channel")
            self.rate_limiter.record_failure()
        except discord.errors.HTTPException as e:
            print(f"[MONITOR] HTTP error sending message: {e}")
            self.rate_limiter.record_failure(is_rate_limit=(e.status == 429))

    def _get_channel_type(self, channel):
        """
        Get string representation of channel type
        """
        if isinstance(channel, discord.DMChannel):
            return "DM"
        elif isinstance(channel, discord.GroupChannel):
            return "GROUP_DM"
        elif isinstance(channel, discord.TextChannel):
            return "GUILD_TEXT"
        else:
            return "UNKNOWN"

    def get_stats(self):
        """
        Get monitor statistics
        """
        return {
            "mentions_detected": self.mention_count,
            "responses_sent": self.response_count,
            "errors": self.error_count,
            "messages_tracked": len(self.processed_messages),
        }

    def get_handlers_status(self):
        status = {}
        if hasattr(self, "handlers") and self.handlers:
            for name, handler in self.handlers.items():
                status[name] = "loaded" if handler is not None else "not loaded"
        else:
            status["handlers"] = "not initialized"
        return status

    def _register_handlers(self):
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

        self.aurora_handler = self.handlers.get("aurora")
        self.school_holidays_handler = self.handlers.get("school_holidays")
        self.help_handler = self.handlers.get("help")
        self.daily_digest_handler = self.handlers.get("daily_digest")


class SelfbotClient(discord.Client):
    """
    Custom Discord client with selfbot functionality
    """

    def __init__(
        self, config, auth_handler, rate_limiter, hermes_connector, response_generator
    ):
        # discord.py-self uses different initialization
        super().__init__(max_messages=10000, self_bot=True)

        self.config = config
        self.auth_handler = auth_handler
        self.rate_limiter = rate_limiter
        self.hermes = hermes_connector
        self.response_gen = response_generator

        self.monitor = None
        self.start_time = None

    async def on_ready(self):
        """
        Called when bot is ready
        """
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

        # Check Hermes health
        healthy, message = await self.hermes.check_health()
        if healthy:
            print(f"[BOT] Hermes API: {message}")
        else:
            print(f"[BOT] WARNING: Hermes API issue - {message}")
            print("[BOT] Will use local response generator as fallback")

    async def on_message(self, message):
        """
        Called when a message is received
        """
        if self.monitor:
            await self.monitor.handle_message(message)

    async def on_disconnect(self):
        """
        Called when disconnected
        """
        print("[BOT] Disconnected from Discord")

    async def on_resumed(self):
        """
        Called when session is resumed
        """
        print("[BOT] Session resumed")

    def get_uptime(self):
        """
        Get bot uptime
        """
        if self.start_time:
            return datetime.now() - self.start_time
        return None

    def get_full_stats(self):
        """
        Get comprehensive statistics
        """
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
    """
    Factory function to create MessageMonitor
    """
    return MessageMonitor(client, hermes_connector, rate_limiter, response_generator)
