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

import re
from typing import Optional, Dict, Any

from features.base_handler import BaseHandler


class CalendarHandler(BaseHandler):
    """Handler for calendar-related commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.calendar = monitor.calendar
        self.nlp_parser = monitor.nlp_parser

    def _extract_search_text(self, content: str) -> Optional[str]:
        """Extract search text after the command keyword in a message.
        Looks for text after @mention + keyword combination.
        """
        # Remove Discord mentions and @inebotten
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()

        # Remove known command keywords
        keywords = [
            "slett", "delete", "fjern",
            "ferdig", "done", "complete", "fullført",
        ]
        for kw in keywords:
            if cleaned.lower().startswith(kw):
                rest = cleaned[len(kw):].strip()
                if rest and len(rest) > 1:
                    return rest
        return None

    async def handle_save_request(self, message, title, date, time):
        """
        Special entry point for AI-generated save requests.
        Ensures the title is clean and the event is created correctly.
        """
        # Final safety scrub of the title
        clean_title = title.strip()
        # Remove common leftover particles if they are at the end
        clean_title = re.sub(r'\s+(på|kl|i|ved|om)\s*$', '', clean_title, flags=re.IGNORECASE)
        # Remove leading particles
        clean_title = re.sub(r'^(å|at|om)\s+', '', clean_title, flags=re.IGNORECASE)
        
        item_data = {
            "title": clean_title[0].upper() + clean_title[1:] if clean_title else "Uten tittel",
            "date": date,
            "time": time if time and ":" in str(time) else "09:00"
        }
        
        await self.handle_calendar_item(message, item_data)

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
                    gcal_result = self._sync_to_gcal(item_data, message)
                    if gcal_result:
                        gcal_event_id = gcal_result.get("id")
                        gcal_link = gcal_result.get("htmlLink")
                        self.log(f"GCal sync successful: {gcal_link}")
                except Exception as e:
                    self.log(f"GCal sync failed: {e}")

            # Add to calendar
            item = await self.calendar.add_item(
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

    def _sync_to_gcal(self, item_data: Dict[str, Any], message) -> Optional[Dict]:
        """
        Sync a calendar item to Google Calendar with proper timezone support.
        """
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        
        try:
            day, month, year = map(int, item_data["date"].split("."))
            time_parts = item_data.get("time", "09:00").split(":")
            hour = int(time_parts[0])
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0

            # Create start datetime in local timezone
            local_tz = ZoneInfo("Europe/Oslo")
            start_dt = datetime(year, month, day, hour, minute, tzinfo=local_tz)
            
            # End time is 1 hour later
            end_dt = start_dt + timedelta(hours=1)

            return self.calendar.gcal.create_event(
                title=item_data["title"],
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                description=item_data.get("description", item_data["title"]),
                recurrence=item_data.get("recurrence"),
                rrule_day=item_data.get("rrule_day"),
                discord_user_id=message.author.id,
                discord_username=message.author.name,
            )
        except Exception as e:
            self.log(f"Error preparing GCal sync: {e}")
            return None

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

    async def handle_clear(self, message) -> None:
        """Handle clearing the entire calendar."""
        try:
            guild_id = self.get_guild_id(message)
            
            # Double check with the user? For now, just do it as requested.
            count = await self.calendar.clear_calendar(guild_id)
            
            if count > 0:
                await self.send_response(message, f"🗑️ **Kalenderen er tømt!** Slettet {count} elementer.")
            else:
                await self.send_response(message, "📭 Kalenderen er allerede tom.")
                
        except Exception as e:
            self.log(f"Error clearing calendar: {e}")
            await self.send_response(message, "❌ Beklager, det oppstod en feil under tømming av kalenderen.")

    async def handle_delete(self, message) -> None:
        """Handle calendar item deletion."""
        try:
            guild_id = self.get_guild_id(message)
            item_num = self.extract_number(message.content)
            search_text = self._extract_search_text(message.content)

            # Try title-based matching first if search text found
            if search_text and not item_num:
                # Check for bulk delete: "alle <title>" or "all <title>"
                lower_text = search_text.lower()
                bulk_match = re.match(r"^(alle?|all|every|both)\s+(.+)", lower_text)
                if bulk_match:
                    bulk_title = bulk_match.group(2).strip()
                    count, deleted = await self.calendar.delete_items_by_title(guild_id, bulk_title)
                    if count > 0:
                        titles = ", ".join(deleted) if count <= 3 else f"{count} stykker"
                        await self.send_response(message, f"✅ **Slettet {count} stykker!**\n{titles}")
                    else:
                        await self.send_response(message, f"❌ Fant ingen \"{bulk_title}\" i kalenderen.")
                    return
                else:
                    # Single delete by title
                    success, title = await self.calendar.delete_item_by_title(guild_id, search_text)
                    if success:
                        await self.send_response(message, f"✅ **Slettet! {title}**")
                        return
                    # Fall through to number/list behavior if no match

            if item_num:
                success, title = await self.calendar.delete_item(guild_id, item_num)

                if success:
                    response_text = f"✅ **Slettet! {title}**"
                else:
                    response_text = (
                        f"❌ Fant ikke noe med nummer {item_num}. "
                        "Bruk `@inebotten kalender` for å se listen."
                    )
            elif search_text:
                response_text = (
                    f"❌ Fant ikke \"{search_text}\" i kalenderen. "
                    "Sjekk stavemåten eller bruk `@inebotten kalender`."
                )
            else:
                # No number provided, show calendar
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = (
                        f"📋 Hvilken vil du slette? (nummer eller skriv tittelen)\n\n"
                        f"{calendar_text}\n\n"
                        f"Bruk: `@inebotten slett [nummer]` eller `@inebotten slett [tittel]`"
                    )
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
            search_text = self._extract_search_text(message.content)

            # Try title-based matching first if search text found
            if search_text and not item_num:
                # Check for bulk complete: "alle <title>" or "all <title>"
                lower_text = search_text.lower()
                bulk_match = re.match(r"^(alle?|all|every|both)\s+(.+)", lower_text)
                if bulk_match:
                    bulk_title = bulk_match.group(2).strip()
                    count, completed, has_recurring = await self.calendar.complete_items_by_title(
                        guild_id, bulk_title
                    )
                    if count > 0:
                        titles = ", ".join(completed) if count <= 3 else f"{count} stk"
                        response_text = f"✅ **Fullført {count}!**\n{titles}"
                        if has_recurring:
                            response_text += "\n🔄 Gjentakende oppføringer er flyttet til neste dato."
                        response_text += "\n\nBra jobba! 🎉"
                    else:
                        response_text = f"❌ Fant ingen \"{bulk_title}\" i kalenderen."
                    await self.send_response(message, response_text)
                    return
                else:
                    # Single complete by title
                    success, title, next_date = await self.calendar.complete_item_by_title(
                        guild_id, search_text
                    )
                    if success:
                        if next_date:
                            response_text = (
                                f"✅ **Fullført! {title}**\n\n"
                                f"📅 Neste gang: {next_date}\n\n"
                                f"Bra jobba! 🎉"
                            )
                        else:
                            response_text = (
                                f"✅ **Fullført! {title}**\n\n"
                                f"Bra jobba! 🎉"
                            )
                        await self.send_response(message, response_text)
                        return
                    # Fall through

            if item_num:
                success, title, next_date = await self.calendar.complete_item(
                    guild_id, item_num
                )

                if success:
                    if next_date:
                        response_text = (
                            f"✅ **Fullført! {title}**\n\n"
                            f"📅 Neste gang: {next_date}\n\n"
                            f"Bra jobba! 🎉"
                        )
                    else:
                        response_text = (
                            f"✅ **Fullført! {title}**\n\n"
                            f"Bra jobba! 🎉"
                        )
                else:
                    response_text = (
                        f"❌ Fant ikke noe med nummer {item_num}. "
                        "Bruk `@inebotten kalender` for å se listen."
                    )
            elif search_text:
                response_text = (
                    f"❌ Fant ikke \"{search_text}\" i kalenderen. "
                    "Sjekk stavemåten eller bruk `@inebotten kalender`."
                )
            else:
                calendar_text = self.calendar.format_list(guild_id, days=90)
                if calendar_text:
                    response_text = (
                        f"📝 Hvilket vil du markere som fullført? "
                        f"(nummer eller skriv tittelen)\n\n{calendar_text}\n\n"
                        f"Bruk: `@inebotten ferdig [nummer]` eller `@inebotten ferdig [tittel]`"
                    )
                else:
                    response_text = "📭 Kalenderen er tom."

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error completing item: {e}")

    _EDIT_FIELD_MAP = {
        "tittel": "title",
        "title": "title",
        "dato": "date",
        "date": "date",
        "tid": "time",
        "time": "time",
        "kl": "time",
        "klokken": "time",
        "gjentakelse": "recurrence",
        "recurrence": "recurrence",
        "gjenta": "recurrence",
        "beskrivelse": "description",
        "description": "description",
        "desc": "description",
    }

    def _parse_edit_command(self, content: str):
        """
        Extract index, search text, field name, and value from an edit command.

        Returns:
            (index, search_text, field, value) where index is 1-based or None,
            search_text is the title snippet to search for, field is the
            Norwegian/English keyword before the colon, and value is the text
            after the colon.
        """
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()

        for kw in ("endre", "rediger", "edit"):
            if cleaned.lower().startswith(kw):
                cleaned = cleaned[len(kw) :].strip()
                break

        if ":" not in cleaned:
            return None, None, None, None

        prefix, value = cleaned.split(":", 1)
        prefix = prefix.strip()
        value = value.strip()

        field = None
        search_text = prefix
        for nor_field in sorted(self._EDIT_FIELD_MAP.keys(), key=len, reverse=True):
            pattern = rf"\b{re.escape(nor_field)}$"
            if re.search(pattern, prefix, re.IGNORECASE):
                field = nor_field
                search_text = re.sub(pattern, "", prefix, flags=re.IGNORECASE).strip()
                break

        num_match = re.search(r"\b(\d+)\b", search_text if field else prefix)
        index = int(num_match.group(1)) if num_match else None

        if index is not None:
            search_text = re.sub(r"\b\d+\b", "", search_text).strip()
            if not search_text:
                search_text = None
        elif field and not search_text:
            search_text = None

        return index, search_text, field, value

    def _parse_date_value(self, value: str) -> Optional[str]:
        value = value.strip()

        if re.match(r"^\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?$", value):
            return value

        try:
            parsed = self.nlp_parser.parse_event(f"x på {value} kl 12")
            if parsed and parsed.get("date"):
                return parsed["date"]
        except Exception:
            pass

        return value

    async def handle_edit(self, message, payload=None) -> None:
        """
        Handle editing calendar items in-place.
        Supports:
          - endre 2 tittel: Ny tittel
          - rediger møte dato: i morgen
        """
        try:
            guild_id = self.get_guild_id(message)
            index, search_text, field, value = self._parse_edit_command(
                message.content
            )

            if not field or not value:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            kwarg_field = self._EDIT_FIELD_MAP.get(field.lower())
            if not kwarg_field:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            if kwarg_field == "date":
                parsed = self._parse_date_value(value)
                if parsed:
                    value = parsed

            if index is None and search_text:
                matches = self.calendar.search_items(search_text)
                if not matches:
                    await self.send_response(
                        message, self.loc.t("calendar_edit_not_found", num=search_text)
                    )
                    return

                upcoming = self.calendar.get_upcoming(guild_id, days=365)
                target_item = matches[0]
                for i, item in enumerate(upcoming, 1):
                    if item.get("id") == target_item.get("id"):
                        index = i
                        break

                if index is None:
                    await self.send_response(
                        message, self.loc.t("calendar_edit_not_found", num=search_text)
                    )
                    return
            elif index is None:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            try:
                updated_item = await self.calendar.edit_item(
                    index, **{kwarg_field: value}
                )
                await self.send_response(
                    message,
                    self.loc.t("calendar_edit_success", title=updated_item["title"]),
                )
            except ValueError:
                await self.send_response(
                    message, self.loc.t("calendar_edit_not_found", num=index)
                )

        except Exception as e:
            self.log(f"Error editing item: {e}")

    async def handle_sync(self, message) -> None:
        """Handle manual sync from Google Calendar."""
        try:
            guild_id = self.get_guild_id(message)
            
            if not self.calendar.gcal_enabled:
                await self.send_response(
                    message, 
                    "❌ Google Calendar er ikke konfigurert eller koblet til ennå."
                )
                return

            await self.send_response(message, "🔄 Synkroniserer med Google Calendar...")
            
            # Use sync_from_gcal with the current channel ID as default
            count = await self.calendar.sync_from_gcal(default_guild_id=guild_id)
            
            if count > 0:
                await self.send_response(message, f"✅ Ferdig! Hentet {count} nye/oppdaterte elementer fra Google Calendar.")
                # Show the updated list
                await self.handle_list(message)
            else:
                await self.send_response(message, "✅ Synkronisering ferdig. Ingen nye endringer funnet i Google Calendar.")
        except Exception as e:
            self.log(f"Error syncing calendar: {e}")
            await self.send_response(message, "❌ Beklager, det oppstod en feil under synkronisering med Google Calendar.")

    async def handle_auth(self, message, payload: Dict[str, Any] = None) -> None:
        """Handle Google Calendar authentication commands."""
        try:
            if not self.calendar.gcal:
                from cal_system.google_calendar_manager import GoogleCalendarManager
                self.calendar.gcal = GoogleCalendarManager()
                
            code = payload.get("auth_code") if payload else None
            
            if code:
                success, msg = self.calendar.gcal.exchange_code(code)
                if success:
                    self.calendar.gcal_enabled = True
                    await self.send_response(message, "✅ " + msg)
                    await self.handle_sync(message)
                else:
                    await self.send_response(message, "❌ " + msg)
            else:
                success, result = self.calendar.gcal.get_auth_url()
                if success:
                    auth_url = result
                    response_text = (
                        "🔐 **Koble til Google Calendar**\n\n"
                        f"1. Klikk på denne lenken for å logge inn med Google-kontoen din:\n{auth_url}\n\n"
                        "2. Etter at du har logget inn, vil nettleseren prøve å gå til `localhost`. "
                        "Dette vil kanskje feile, men det går fint! Se i adresselinjen din.\n\n"
                        "3. Kopier koden fra adresselinjen (etter `code=`) og send den til meg slik:\n"
                        "`@inebotten kalender kode <din_kode>`"
                    )
                    await self.send_response(message, response_text)
                else:
                    await self.send_response(message, "❌ " + result)
                    
        except Exception as e:
            self.log(f"Error handling calendar auth: {e}")
            await self.send_response(message, "❌ Beklager, det oppstod en feil under autentiseringen.")
