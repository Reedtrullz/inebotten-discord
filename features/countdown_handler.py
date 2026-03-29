#!/usr/bin/env python3
"""
CountdownHandler - Handles countdown queries for the selfbot.

Commands:
- Countdown to specific dates
- Days until events
"""

from typing import Dict, Any

from features.base_handler import BaseHandler


class CountdownHandler(BaseHandler):
    """Handler for countdown-related commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.countdown = monitor.countdown

    async def handle_countdown(self, message, countdown_result: Dict[str, Any]) -> None:
        """
        Handle countdown queries.

        Args:
            message: The Discord message
            countdown_result: Parsed countdown data
        """
        try:
            lang = self.loc.current_lang
            response_text = self.countdown.format_response(countdown_result, lang)
            await self.send_response(message, response_text)
        except Exception as e:
            self.log(f"Error handling countdown: {e}")
