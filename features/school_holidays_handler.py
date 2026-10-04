"""Discord adapter for locality-specific school holiday schedules."""

from features.base_handler import BaseHandler
from features.school_holidays import format_holidays_list, get_locality_from_location


class SchoolHolidaysHandler(BaseHandler):
    """Handle school holiday requests using an explicitly named locality."""

    def __init__(self, monitor):
        super().__init__(monitor)

    async def handle_school_holidays(self, message) -> None:
        try:
            locality_id = get_locality_from_location(message.content)
            response_text = format_holidays_list(
                locality_id,
                days=90,
                lang=self.loc.current_lang,
            )
            await self.send_response(message, response_text)
        except Exception as exc:
            self.log(f"Error handling school holidays: {exc}")
