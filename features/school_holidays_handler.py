"""Discord adapter for locality-specific school holiday schedules."""

import re

from features.base_handler import BaseHandler
from features.school_holidays import format_holidays_list, get_locality_from_location


class SchoolHolidaysHandler(BaseHandler):
    """Handle school holiday requests using an explicitly named locality."""

    def __init__(self, monitor):
        super().__init__(monitor)

    async def handle_school_holidays(self, message) -> None:
        try:
            locality_id = get_locality_from_location(message.content)
            years = {f'{start}-{end}' for start, end in re.findall(r'\b(\d{4})\s*[-/–]\s*(\d{4})\b', message.content)}
            if len(years) > 1:
                await self.send_response(message, '📚 Velg ett skoleår om gangen, for eksempel 2026–2027.')
                return
            response_text = format_holidays_list(
                locality_id,
                days=90,
                lang=self.loc.current_lang,
                school_year=next(iter(years), None),
            )
            await self.send_response(message, response_text)
        except Exception as exc:
            self.log(f"Error handling school holidays: {exc}")
