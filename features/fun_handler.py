#!/usr/bin/env python3
"""
FunHandler - Handles fun/entertainment commands for the selfbot.

Commands:
- Word of the day
- Quotes (save/get)
- Compliments/roasts
- Horoscopes
"""

from typing import Dict, Any, Optional

import discord

from features.base_handler import BaseHandler


class FunHandler(BaseHandler):
    """Handler for fun/entertainment commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.wod = monitor.wod
        self.quote = monitor.quote
        self.compliments = monitor.compliments
        self.horoscope = monitor.horoscope

    async def handle_word_of_day(self, message) -> None:
        """Handle word of the day request."""
        try:
            lang = self.loc.current_lang
            word = self.wod.get_word_of_day(lang)
            response_text = self.wod.format_word(word, lang)
            await self.send_response(message, response_text)
        except Exception as e:
            self.log(f"Error handling word of day: {e}")

    async def handle_quote_command(self, message, quote_cmd: Dict[str, Any]) -> None:
        """
        Handle quote commands.

        Args:
            message: The Discord message
            quote_cmd: Parsed quote command with 'action' and optional 'text'
        """
        try:
            guild_id = self.get_guild_id(message)
            lang = quote_cmd.get("lang", self.loc.current_lang)

            if quote_cmd["action"] == "save":
                self.quote.add_quote(
                    guild_id=guild_id,
                    text=quote_cmd["text"],
                    author=message.author.name,
                )
                response_text = self.quote.format_confirmation(quote_cmd["text"], lang)
            else:  # "get"
                quote = self.quote.get_random_quote(guild_id)
                if quote:
                    response_text = self.quote.format_quote(quote, lang)
                else:
                    response_text = self.loc.t("no_quotes")

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling quote: {e}")

    async def handle_compliment(self, message, compliment_cmd: Dict[str, Any]) -> None:
        """
        Handle compliment/roast commands.

        Args:
            message: The Discord message
            compliment_cmd: Parsed command with 'action' and optional 'user'
        """
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

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling compliment: {e}")

    async def handle_horoscope(self, message, horoscope_cmd: Dict[str, Any]) -> None:
        """
        Handle horoscope requests.

        Args:
            message: The Discord message
            horoscope_cmd: Parsed command with 'sign'
        """
        try:
            lang = self.loc.current_lang

            horoscope_data = self.horoscope.get_horoscope(horoscope_cmd["sign"], lang)
            response_text = self.horoscope.format_horoscope(horoscope_data, lang)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling horoscope: {e}")
