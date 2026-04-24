#!/usr/bin/env python3
"""
HelpHandler - Handles help commands for the selfbot.

Commands:
- Show available commands and features
"""

from features.base_handler import BaseHandler


class HelpHandler(BaseHandler):
    """Handler for help commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.calendar = monitor.calendar

    async def handle_help(self, message) -> None:
        """
        Handle help requests.

        Args:
            message: The Discord message
        """
        try:
            lang = self.loc.current_lang

            gcal_status = ""
            if self.calendar.gcal_enabled:
                gcal_status = "✅ Synkronisert med Google Calendar"

            lines = [
                self.loc.t("help_title"),
                "",
                self.loc.t("help_events"),
            ]

            if gcal_status:
                lines.extend(["", gcal_status])

            lines.extend(
                [
                    "",
                    self.loc.t("help_reminders"),
                    "",
                    self.loc.t("help_profile"),
                    "",
                    self.loc.t("help_fun"),
                    self.loc.t("help_footer_tip"),
                ]
            )

            response_text = "\n".join(lines)
            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling help command: {e}")
