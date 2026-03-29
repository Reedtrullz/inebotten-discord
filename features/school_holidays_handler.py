#!/usr/bin/env python3
"""
SchoolHolidaysHandler - Handles school holidays commands for the selfbot.

Commands:
- Get school holidays for Norwegian counties
"""

from features.base_handler import BaseHandler
from features.school_holidays import format_holidays_list, get_fylke_from_location


class SchoolHolidaysHandler(BaseHandler):
    """Handler for school holidays commands"""

    def __init__(self, monitor):
        super().__init__(monitor)

    async def handle_school_holidays(self, message) -> None:
        """
        Handle school holidays requests.

        Args:
            message: The Discord message
        """
        try:
            content_lower = message.content.lower()
            fylke = get_fylke_from_location(content_lower)
            lang = self.loc.current_lang

            response_text = format_holidays_list(fylke, days=90, lang=lang)

            if not fylke:
                if lang == "no":
                    response_text += (
                        '\n\n💡 *Tips: Nevn byen din for å se ferier i ditt fylke '
                        '(f.eks. "skoleferie Tromsø")*'
                    )
                else:
                    response_text += (
                        '\n\n💡 *Tip: Mention your city to see holidays in your county '
                        '(e.g. "school holidays Tromsø")*'
                    )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling school holidays: {e}")
