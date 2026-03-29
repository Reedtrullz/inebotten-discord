#!/usr/bin/env python3
"""CalendarHandler - Events, tasks, reminders"""

import re


class CalendarHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.calendar = monitor.calendar
        self.nlp_parser = monitor.nlp_parser
        self.loc = monitor.loc

    async def handle_calendar_item(self, message, item_data):
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            gcal_event_id = None
            gcal_link = None
            if self.calendar.gcal_enabled:
                day, month, year = item_data["date"].split(".")
                start_iso = f"{year}-{month.zfill(2)}-{day.zfill(2)}T{item_data.get('time', '09:00')}:00"
                end_time = f"{int(item_data.get('time', '09:00').split(':')[0]) + 1:02d}:{item_data.get('time', '09:00').split(':')[1] if ':' in item_data.get('time', '09:00') else '00'}"
                end_iso = f"{year}-{month.zfill(2)}-{day.zfill(2)}T{end_time}:00"
                gcal_result = self.calendar.gcal.create_event(
                    title=item_data["title"],
                    start_time=start_iso,
                    end_time=end_iso,
                    description=item_data["title"],
                    recurrence=item_data.get("recurrence"),
                    rrule_day=item_data.get("rrule_day"),
                )
                if gcal_result:
                    gcal_event_id = gcal_result.get("id")
                    gcal_link = gcal_result.get("htmlLink")

            self.calendar.add_item(
                guild_id=guild_id,
                title=item_data["title"],
                date=item_data["date"],
                time=item_data.get("time"),
                event_type=item_data.get("type", "event"),
                recurrence=item_data.get("recurrence"),
                gcal_event_id=gcal_event_id,
                gcal_link=gcal_link,
            )
            lang = self.monitor.loc.current_lang
            response_text = self.loc.t("event_created", lang)
            if gcal_link:
                response_text += f"\n{gcal_link}"
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Calendar item error: {e}")

    async def handle_list(self, message):
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            items = self.calendar.get_upcoming_items(guild_id)
            lang = self.monitor.loc.current_lang
            if items:
                response_text = self.loc.t("calendar_upcoming", lang) + "\n"
                for i, item in enumerate(items[:10], 1):
                    response_text += f"{i}. {item['title']} ({item['date']})\n"
            else:
                response_text = self.loc.t("calendar_empty", lang)
            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Calendar list error: {e}")

    async def handle_delete(self, message):
        try:
            import re

            guild_id = message.guild.id if message.guild else message.channel.id
            content_lower = message.content.lower()
            content_clean = re.sub(r"<@!?\d+>", "", content_lower).strip()
            num_match = re.search(r"\b(\d+)\b", content_clean)

            if num_match:
                item_num = int(num_match.group(1))
                success, title = self.calendar.delete_item(guild_id, item_num)

                if success:
                    response_text = f"✅ **Slettet!** {title}"
                else:
                    response_text = "❌ Fant ikke noe med det nummeret. Bruk `@inebotten kalender` for å se listen."
            else:
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = f"📋 Hva vil du slette?\n\n{calendar_text}"
                else:
                    response_text = "📭 Kalenderen er tom."

            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Calendar delete error: {e}")

    async def handle_complete(self, message):
        try:
            import re

            guild_id = message.guild.id if message.guild else message.channel.id
            content_lower = message.content.lower()
            content_clean = re.sub(r"<@!?\d+>", "", content_lower)
            num_match = re.search(r"\b(\d+)\b", content_clean)

            if num_match:
                item_num = int(num_match.group(1))
                success, title, next_date = self.calendar.complete_item(
                    guild_id, item_num
                )

                if success:
                    if next_date:
                        response_text = f"✅ **Fullført!**\n\n✓ ~~{title}~~\n\n📅 Neste gang: {next_date}\n\nBra jobba! 🎉"
                    else:
                        response_text = (
                            f"✅ **Fullført!**\n\n✓ ~~{title}~~\n\nBra jobba! 🎉"
                        )
                else:
                    response_text = "❌ Fant ikke noe med det nummeret. Bruk `@inebotten kalender` for å se listen."
            else:
                calendar_text = self.calendar.format_list(guild_id)
                if calendar_text:
                    response_text = (
                        f"📝 Hvilket vil du markere som fullført?\n\n{calendar_text}"
                    )
                else:
                    response_text = "📭 Kalenderen er tom."

            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Calendar complete error: {e}")

    async def handle_edit(self, message):
        try:
            guild_id = message.guild.id if message.guild else message.channel.id
            items = self.calendar.get_upcoming(guild_id, days=365)

            if not items:
                response_text = "📭 **Ingen arrangementer å endre**\n\nDet er ingen aktive arrangementer."
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

            await message.reply(response_text, mention_author=False)
            self.monitor.rate_limiter.record_sent()
            self.monitor.response_count += 1
        except Exception as e:
            print(f"[MONITOR] Calendar edit error: {e}")
