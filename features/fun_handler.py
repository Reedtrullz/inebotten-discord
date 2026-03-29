#!/usr/bin/env python3
"""
FunHandler - Modular handler for fun features (word of day, quotes, etc)

This handler object wraps the feature managers and provides
a clean interface for message_monitor to delegate to.
"""

import discord


class FunHandler:
    """Handler for fun features"""

    def __init__(self, monitor):
        self.monitor = monitor
        self.wod = monitor.wod
        self.quote = monitor.quote
        self.compliments = monitor.compliments
        self.horoscope = monitor.horoscope
        self.loc = monitor.loc

    async def handle_word_of_day(self, message):
        """Handle word of the day request"""
        try:
            lang = self.monitor.loc.current_lang
            word = self.wod.get_word_of_day(lang)
            response_text = self.wod.format_word(word, lang)

            if isinstance(message.channel, discord.DMChannel):
                await message.channel.send(response_text)
            elif isinstance(message.channel, discord.GroupChannel):
                await message.channel.send(response_text)
            else:
                await message.reply(response_text, mention_author=False)

            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Error handling word of day: {e}")

    async def handle_quote_command(self, message, quote_cmd):
        """Handle quote commands"""
        guild_id = message.guild.id if message.guild else message.channel.id
        lang = quote_cmd.get("lang", self.monitor.loc.current_lang)

        if quote_cmd["action"] == "save":
            self.quote.add_quote(
                guild_id=guild_id,
                text=quote_cmd["text"],
            )
            response_text = self.loc.t("quote_saved", lang)
        else:
            quote = self.quote.get_random_quote(guild_id)
            if quote:
                response_text = self.loc.t("quote_random", lang).format(quote=quote)
            else:
                response_text = self.loc.t("quote_empty", lang)

        await message.reply(response_text, mention_author=False)
        self.monitor.rate_limiter.record_sent()
        self.monitor.response_count += 1

    async def handle_compliment(self, message, compliment_cmd):
        """Handle compliment/roast commands"""
        target = compliment_cmd.get("target")
        lang = compliment_cmd.get("lang", self.monitor.loc.current_lang)

        if compliment_cmd["type"] == "roast":
            response_text = self.compliments.get_roast(target, lang)
        else:
            response_text = self.compliments.get_compliment(target, lang)

        await message.reply(response_text, mention_author=False)
        self.monitor.rate_limiter.record_sent()
        self.monitor.response_count += 1

    async def handle_horoscope(self, message, horoscope_cmd):
        """Handle horoscope requests"""
        sign = horoscope_cmd.get("sign", "").lower()
        lang = horoscope_cmd.get("lang", self.monitor.loc.current_lang)

        response_text = self.horoscope.get_horoscope(sign, lang)

        if isinstance(message.channel, discord.DMChannel):
            await message.channel.send(response_text)
        else:
            await message.reply(response_text, mention_author=False)

        self.monitor.rate_limiter.record_sent()
        self.monitor.response_count += 1
