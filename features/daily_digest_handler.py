#!/usr/bin/env python3
"""
DailyDigestHandler - Handles daily digest commands for the selfbot.

Commands:
- Generate daily summary of calendar, weather, etc.
"""

from features.base_handler import BaseHandler


class DailyDigestHandler(BaseHandler):
    """Handler for daily digest commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.daily_digest = monitor.daily_digest

    async def handle_daily_digest(self, message) -> None:
        """
        Handle daily digest requests.

        Args:
            message: The Discord message
        """
        try:
            guild_id = self.get_guild_id(message)
            lang = self.loc.current_lang

            response_text = self.daily_digest.generate_digest(guild_id, lang)
            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling daily digest: {e}")
