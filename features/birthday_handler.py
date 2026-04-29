#!/usr/bin/env python3
"""BirthdayHandler - Handles birthday commands for the selfbot."""

import re
from typing import Dict, Any, Optional

import discord

from features.base_handler import BaseHandler


class BirthdayHandler(BaseHandler):
    """Handler for birthday commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.birthdays = monitor.birthdays

    async def handle_birthday_edit(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle birthday edit requests.

        Args:
            message: The Discord message
            payload: Parsed payload with edit info (optional)
        """
        try:
            guild_id = self.get_guild_id(message)
            content = message.content

            parsed = self._parse_birthday_edit(content)
            if not parsed:
                await self.send_response(
                    message,
                    "❌ Kunne ikke forstå redigeringen. Bruk: `@inebotten endre bursdag [navn] DD.MM[.ÅÅÅÅ]`"
                )
                return

            name = parsed["name"]
            day = parsed["day"]
            month = parsed["month"]
            year = parsed.get("year")

            self.birthdays.edit_birthday(guild_id, name, day, month, year)
            response_text = self.loc.t("birthday_edit_success")
            await self.send_response(message, response_text)

        except ValueError as exc:
            name_match = re.search(r"Birthday for (.+) not found", str(exc))
            name = name_match.group(1) if name_match else ""
            response_text = self.loc.t("birthday_edit_not_found", name=name)
            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling birthday edit: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    def _parse_birthday_edit(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Parse birthday edit command from message content.

        Format: "@inebotten endre bursdag Ola Nordmann 20.05.1990"
        """
        content = re.sub(r"<@!?\d+>", "", content)
        content = re.sub(r"@inebotten\b[:,]?", "", content, flags=re.IGNORECASE)
        content = content.strip()

        for keyword in ("endre bursdag", "rediger bursdag", "oppdater bursdag",
                        "edit birthday", "update birthday"):
            content = re.sub(re.escape(keyword), "", content, flags=re.IGNORECASE)

        content = content.strip()

        date_match = re.search(r"(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?", content)
        if not date_match:
            return None

        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year_str = date_match.group(3)
        year = None

        if year_str:
            year = int(year_str)
            if year < 100:
                if year >= 50:
                    year = 1900 + year
                else:
                    year = 2000 + year

        date_start = date_match.start()
        name = content[:date_start].strip()
        name = re.sub(r"[:\-–—]\s*$", "", name).strip()

        if not name:
            return None

        return {"name": name, "day": day, "month": month, "year": year}
