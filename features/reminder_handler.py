#!/usr/bin/env python3
"""
ReminderHandler - Handles reminder edit and delete commands.

Commands:
- Editing reminder text, date, or recurrence by index
- Deleting reminders by index
"""

import re
from typing import Dict, Optional, Tuple

from cal_system.reminder_manager import parse_reminder_command
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

    def _parse_search_query(self, content: str) -> Optional[str]:
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()
        match = re.match(
            r"^(?:søk|search)\s+(?:påminnelse|påminnelser|reminder|reminders)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        query = match.group(1).strip()
        return query or None

    async def handle_reminder_search(self, message, payload=None) -> None:
        """Handle reminder text search commands."""
        try:
            guild_id = self.get_guild_id(message)
            query = (payload or {}).get("query") or self._parse_search_query(message.content)
            if not query:
                await self.send_response(message, "🔎 Skriv hva du vil søke etter i påminnelser.")
                return
            await self.send_response(
                message,
                self.reminders.format_search_results(
                    guild_id,
                    query,
                    getattr(self.loc, "current_lang", "no"),
                ),
            )
        except Exception as e:
            self.log(f"Error searching reminders: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_create(self, message, payload=None) -> None:
        """Handle creating reminders from routed natural language."""
        try:
            guild_id = self.get_guild_id(message)
            data = (payload or {}).get("reminder") or parse_reminder_command(message.content)
            if not data or data.get("action") != "add" or not data.get("text"):
                await self.send_response(
                    message,
                    "🔔 Skriv hva jeg skal minne deg på, f.eks. `@inebotten påminnelse ring legen 20.06`.",
                )
                return

            reminder_id = self.reminders.add_reminder(
                guild_id=guild_id,
                user_id=message.author.id,
                username=message.author.name,
                text=data["text"],
                due_date=data.get("due_date"),
                channel_id=getattr(getattr(message, "channel", None), "id", None),
            )
            due = f"\n📅 Frist: {data['due_date']}" if data.get("due_date") else ""
            await self.send_response(
                message,
                f"✅ **Påminnelse lagt til!**\n{data['text']}{due}",
            )
        except Exception as e:
            self.log(f"Error creating reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_list(self, message, payload=None) -> None:
        """Handle listing active reminders."""
        try:
            guild_id = self.get_guild_id(message)
            reminders_text = self.reminders.format_reminders_list(guild_id, show_completed=True)
            if reminders_text:
                await self.send_response(message, f"🔔 **Påminnelser:**\n{reminders_text}")
            else:
                await self.send_response(message, "📭 Ingen aktive påminnelser.")
        except Exception as e:
            self.log(f"Error listing reminders: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

    async def handle_reminder_complete(self, message, payload=None) -> None:
        """Handle completing a reminder by active-list index."""
        try:
            guild_id = self.get_guild_id(message)
            data = (payload or {}).get("reminder")
            if not data:
                parsed = parse_reminder_command(message.content)
                data = parsed if parsed and parsed.get("action") == "complete" else {}
            index = data.get("number") if isinstance(data, dict) else None
            if index is None:
                cleaned = re.sub(r"<@!?\d+>", "", message.content)
                cleaned = cleaned.replace("@inebotten", "").strip().lower()
                match = re.fullmatch(
                    r"(?:ferdig|fullført|fullfør|done|complete|gjort)\s+(\d+)",
                    cleaned,
                    flags=re.IGNORECASE,
                )
                if match:
                    index = int(match.group(1))

            if index is None:
                reminders_text = self.reminders.format_reminders_list(guild_id)
                if reminders_text:
                    await self.send_response(
                        message,
                        f"📝 Hvilken påminnelse er ferdig?\n\n{reminders_text}\n\n"
                        "Bruk `@inebotten ferdig påminnelse [nummer]`.",
                    )
                else:
                    await self.send_response(message, "📭 Ingen aktive påminnelser.")
                return

            success, text, next_date = self.reminders.complete_reminder(guild_id, reminder_num=index)
            if not success:
                await self.send_response(
                    message,
                    f"❌ Fant ikke påminnelse nummer {index}. Bruk `@inebotten påminnelser` for listen.",
                )
                return

            if next_date:
                await self.send_response(
                    message,
                    f"✅ **Fullført! {text}**\n📅 Neste gang: {next_date}",
                )
            else:
                await self.send_response(message, f"✅ **Fullført! {text}**")
        except Exception as e:
            self.log(f"Error completing reminder: {e}")
            await self.send_response(message, self.loc.t("error_generic"))

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
