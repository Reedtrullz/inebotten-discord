#!/usr/bin/env python3
"""
CalendarHandler - Handles calendar-related commands for the selfbot.

Commands:
- Creating calendar items (events, tasks, recurring items)
- Listing upcoming items
- Deleting items
- Marking items as complete
- Editing items (via delete+recreate workflow)
"""

from typing import Optional, Dict, Any

from features.base_handler import BaseHandler


class CalendarHandler(BaseHandler):
    """Handler for calendar-related commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.calendar = monitor.calendar
        self.nlp_parser = monitor.nlp_parser

    async def handle_calendar_item(self, message, item_data: Dict[str, Any]) -> None:
        """
        Handle natural language calendar item creation (unified events + tasks).

        Args:
            message: The Discord message
            item_data: Parsed calendar item data from NLP parser
        """
        try:
            guild_id = self.get_guild_id(message)

            # Sync to Google Calendar if available
            gcal_event_id = None
            gcal_link = None

            if self.calendar.gcal_enabled:
                try:
                    self.log(f"Syncing to Google Calendar: {item_data['title']}")
                    gcal_result = self._sync_to_gcal(item_data)
                    if gcal_result:
                        gcal_event_id = gcal_result.get("id")
                        gcal_link = gcal_result.get("htmlLink")
                        self.log(f"GCal sync successful: {gcal_link}")
                except Exception as e:
                    self.log(f"GCal sync failed: {e}")

            # Add to calendar
            item = self.calendar.add_item(
                guild_id=guild_id,
                user_id=message.author.id,
                username=message.author.name,
                title=item_data["title"],
                date_str=item_data["date"],
                time_str=item_data.get("time"),
                recurrence=item_data.get("recurrence"),
                recurrence_day=item_data.get("recurrence_day"),
                gcal_event_id=gcal_event_id,
                gcal_link=gcal_link,
                channel_id=message.channel.id,
            )

            if item:
                response_text = self.calendar.format_single_item(item)
            else:
                response_text = (
                    "❌ Beklager, jeg klarte ikke å legge til i kalenderen. Prøv igjen!"
                )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling calendar item: {e}")

    def _sync_to_gcal(self, item_data: Dict[str, Any]) -> Optional[Dict]:
        """
        Sync a calendar item to Google Calendar.

        Args:
            item_data: The parsed calendar item data

        Returns:
            GCal API result or None if failed
        """
        day, month, year = item_data["date"].split(".")
        time_str = item_data.get("time", "09:00")

        start_iso = f"{year}-{month.zfill(2)}-{day.zfill(2)}T{time_str}:00"

        # Calculate end time (1 hour later)
        hour = int(time_str.split(":")[0])
        minute = time_str.split(":")[1] if ":" in time_str else "00"
        end_time = f"{hour + 1:02d}:{minute}"
        end_iso = f"{year}-{month.zfill(2)}-{day.zfill(2)}T{end_time}:00"

        return self.calendar.gcal.create_event(
            title=item_data["title"],
            start_time=start_iso,
            end_time=end_iso,
            description=item_data["title"],
            recurrence=item_data.get("recurrence"),
            rrule_day=item_data.get("rrule_day"),
        )

    async def handle_list(self, message) -> None:
        """Handle listing calendar items."""
        try:
            guild_id = self.get_guild_id(message)
            calendar_text = self.calendar.format_list(guild_id, days=90)

            if calendar_text:
                response_text = calendar_text
            else:
                response_text = (
                    "📭 **Kalenderen er tom**\n\n"
                    "Legg til med:\n"
                    "• `@inebotten [noe] på [dato]`\n"
                    "• `@inebotten Jeg må [gjøremål] på [dato]`"
                )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error listing calendar: {e}")

    async def handle_delete(self, message) -> None:
        """Handle calendar item deletion."""
        try:
            guild_id = self.get_guild_id(message)
            item_num = self.extract_number(message.content)

            if item_num:
                success, title = self.calendar.delete_item(guild_id, item_num)

                if success:
                    response_text = f"✅ **Slettet!** {title}"
                else:
                    response_text = (
                        "❌ Fant ikke noe med det nummeret. "
                        "Bruk `@inebotten kalender` for å se listen."
                    )
            else:
                # No number provided, show calendar
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = f"📋 Hva vil du slette?\n\n{calendar_text}"
                else:
                    response_text = "📭 Kalenderen er tom."

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error deleting item: {e}")

    async def handle_complete(self, message) -> None:
        """Handle marking calendar items as complete."""
        try:
            guild_id = self.get_guild_id(message)
            item_num = self.extract_number(message.content)

            if item_num:
                success, title, next_date = self.calendar.complete_item(
                    guild_id, item_num
                )

                if success:
                    if next_date:
                        response_text = (
                            f"✅ **Fullført!**\n\n"
                            f"✓ ~~{title}~~\n\n"
                            f"📅 Neste gang: {next_date}\n\n"
                            f"Bra jobba! 🎉"
                        )
                    else:
                        response_text = (
                            f"✅ **Fullført!**\n\n"
                            f"✓ ~~{title}~~\n\n"
                            f"Bra jobba! 🎉"
                        )
                else:
                    response_text = (
                        "❌ Fant ikke noe med det nummeret. "
                        "Bruk `@inebotten kalender` for å se listen."
                    )
            else:
                # No number, show calendar
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = (
                        f"📝 Hvilket vil du markere som fullført?\n\n{calendar_text}"
                    )
                else:
                    response_text = "📭 Kalenderen er tom."

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error completing item: {e}")

    async def handle_edit(self, message) -> None:
        """
        Handle event editing.
        Currently guides users to delete+recreate workflow.
        """
        try:
            guild_id = self.get_guild_id(message)
            items = self.calendar.get_upcoming(guild_id, days=365)

            if not items:
                response_text = (
                    "📭 **Ingen arrangementer å endre**\n\n"
                    "Det er ingen aktive arrangementer."
                )
            else:
                response_text = "📝 **Endre arrangement**\n\n"
                response_text += (
                    "For å endre et arrangement, slett det først og lag et nytt:\n\n"
                )
                for i, item in enumerate(items[:5], 1):
                    response_text += f"{i}. **{item['title']}** - {item['date']}\n"
                response_text += "\nBruk: `@inebotten slett [nummer]`\n"
                response_text += (
                    "Deretter: `@inebotten [nytt arrangement] [dato] [tid]`"
                )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error editing event: {e}")
