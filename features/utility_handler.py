#!/usr/bin/env python3
"""
UtilityHandler - Handles utility commands for the selfbot.

Commands:
- Calculator and unit conversions
- Crypto/stock prices
- URL shortening
"""

from typing import Dict, Any

from features.base_handler import BaseHandler


class UtilityHandler(BaseHandler):
    """Handler for utility commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.calculator = monitor.calculator
        self.crypto = monitor.crypto
        self.url_shortener = monitor.url_shortener

    async def handle_calculator(self, message, calc_cmd: Dict[str, Any]) -> None:
        """
        Handle calculator/conversion commands.

        Args:
            message: The Discord message
            calc_cmd: Parsed calculator command
        """
        try:
            lang = calc_cmd.get("lang", self.loc.current_lang)
            response_text = self.calculator.calculate(calc_cmd, lang)

            if response_text:
                await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling calculator: {e}")

    async def handle_price(self, message, price_cmd: Dict[str, Any]) -> None:
        """
        Handle crypto/stock price commands.

        Args:
            message: The Discord message
            price_cmd: Parsed price command with 'symbol'
        """
        try:
            lang = self.loc.current_lang

            price_data = await self.crypto.get_price(price_cmd)
            response_text = self.crypto.format_price(price_data, lang)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling price command: {e}")

    async def handle_shorten(self, message, shorten_cmd: Dict[str, Any]) -> None:
        """
        Handle URL shorten commands.

        Args:
            message: The Discord message
            shorten_cmd: Parsed command with 'url'
        """
        try:
            lang = self.loc.current_lang

            short_data = self.url_shortener.shorten_url(shorten_cmd["url"])
            response_text = self.url_shortener.format_short_url(short_data, lang)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling URL shorten: {e}")
