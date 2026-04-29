#!/usr/bin/env python3
"""
ReminderHandler - Handles reminder edit and delete commands.

Commands:
- Editing reminder text, date, or recurrence by index
- Deleting reminders by index
"""

import re
from typing import Dict, Optional, Tuple

from features.base_handler import BaseHandler


class ReminderHandler(BaseHandler):
    """Handler for reminder edit and delete commands."""

    _EDIT_FIELD_MAP = {
        "tittel": "title",
        "title": "title",
        "tekst": "title",
        "text": "title",
        "dato": "date",
        "date": "date",
        "gjentakelse": "recurrence",
        "recurrence": "recurrence",
        "gjenta": "recurrence",
    }

    def __init__(self, monitor):
        super().__init__(monitor)
        self.reminders = monitor.reminders

    def _parse_edit_command(self, content: str) -> Tuple[Optional[int], Dict[str, str]]:
        """
        Extract index and field updates from an edit command.

        Supports formats like:
          - endre påminnelse 2 tittel: ny tekst
          - rediger påminnelse 1 dato: 15.05.2026
          - oppdater påminnelse 3 gjentakelse: ukentlig

        Returns:
            (index, kwargs) where index is 1-based or None,
            and kwargs maps to ReminderManager.edit_reminder fields.
        """
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()

        for kw in (
            "endre påminnelse",
            "rediger påminnelse",
            "oppdater påminnelse",
            "endre",
            "rediger",
            "oppdater",
            "påminnelse",
        ):
            if cleaned.lower().startswith(kw):
                cleaned = cleaned[len(kw) :].strip()

        num_match = re.search(r"\b(\d+)\b", cleaned)
        if not num_match:
            return None, {}
        index = int(num_match.group(1))

        remaining = re.sub(r"\b\d+\b", "", cleaned, count=1).strip(" -–—:")

        if ":" in remaining:
            prefix, value = remaining.split(":", 1)
            prefix = prefix.strip().lower()
            value = value.strip()

            field = None
            for nor_field, eng_field in self._EDIT_FIELD_MAP.items():
                if nor_field in prefix:
                    field = eng_field
                    break

            if field:
                return index, {field: value}

        if remaining:
            return index, {"title": remaining}

        return index, {}

    async def handle_reminder_edit(self, message, payload=None) -> None:
        """Handle editing a reminder by its list index."""
        try:
            guild_id = self.get_guild_id(message)
            index, kwargs = self._parse_edit_command(message.content)

            if index is None:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            if not kwargs:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            updated = self.reminders.edit_reminder(guild_id, index, **kwargs)
            await self.send_response(
                message, self.loc.t("reminder_edit_success", title=updated["text"])
            )

        except ValueError:
            index = self.extract_number(message.content)
            await self.send_response(
                message, self.loc.t("reminder_edit_not_found", num=index or "?")
            )
        except Exception as e:
            self.log(f"Error editing reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_delete(self, message, payload=None) -> None:
        """Handle deleting a reminder by its list index."""
        try:
            guild_id = self.get_guild_id(message)
            index = self.extract_number(message.content)

            if index is None:
                await self.send_response(
                    message,
                    self.loc.t(
                        "reminder_delete_not_found",
                        num="?",
                    ),
                )
                return

            self.reminders.delete_reminder_by_id(guild_id, index)
            await self.send_response(message, self.loc.t("reminder_delete_success"))

        except ValueError:
            index = self.extract_number(message.content)
            await self.send_response(
                message, self.loc.t("reminder_delete_not_found", num=index or "?")
            )
        except Exception as e:
            self.log(f"Error deleting reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))
