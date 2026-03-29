#!/usr/bin/env python3
"""
AuroraHandler - Handles aurora (nordlys) forecast commands for the selfbot.

Commands:
- Get aurora forecast for Norway
"""

from features.base_handler import BaseHandler


class AuroraHandler(BaseHandler):
    """Handler for aurora/nordlys commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.aurora = monitor.aurora

    async def handle_aurora(self, message) -> None:
        """
        Handle aurora forecast requests.

        Args:
            message: The Discord message
        """
        try:
            forecast = await self.aurora.get_forecast()

            if forecast:
                response_text = self.aurora.format_forecast(forecast)
            else:
                response_text = (
                    "Kunne ikke hente nordlysvarsel akkurat nå. Prøv igjen senere! 🌌"
                )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling aurora command: {e}")
