#!/usr/bin/env python3
"""
Calendar Reminder Checker for Inebotten

Background asyncio task that:
1. Checks every minute for events/reminders coming up in 30 minutes
   and pings the event creator in the original channel
2. Sends a "now" reminder when events are happening
3. Sends a "passed" notification when events just happened
4. Sends a morning digest at 09:00 Europe/Oslo with today's events

Tracks sent reminders in a JSON file to avoid duplicate pings.
"""

import json
import time
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

from zoneinfo import ZoneInfo


class ReminderChecker:
    """
    Proactive calendar reminder checker that pings users in Discord
    when events are approaching, happening, or have just happened.
    Also sends a morning digest.
    """

    def __init__(
        self,
        calendar_manager=None,
        reminder_manager=None,
        event_manager=None,
        get_channel_func=None,
        send_channel_message_func=None,
        send_ping_message_func=None,
        storage_path=None,
    ):
        self.calendar = calendar_manager
        self.reminders = reminder_manager
        self.events = event_manager
        self.get_channel = get_channel_func
        self.send_channel_message = send_channel_message_func
        self.send_ping_message = send_ping_message_func
        self.running = False
        self._morning_digest_sent = False
        self._last_gcal_sync = 0

        self.stats = {
            "30min_sent": 0,
            "now_sent": 0,
            "passed_sent": 0,
            "digest_sent": 0,
            "errors": 0,
        }

        if storage_path is None:
            storage_path = Path.home() / ".hermes" / "discord" / "reminder_log.json"

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.sent_log = {"reminders_sent": {}, "digest_log": {}}

    async def setup(self):
        """Async initialization"""
        self.sent_log = await self._load_sent_log()

    async def _load_sent_log(self):
        """Load log of sent reminders asynchronously"""
        if not self.storage_path.exists():
            return {"reminders_sent": {}, "digest_log": {}}

        def _read():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[REMIND] Sent log load error: {e}")
                return {"reminders_sent": {}, "digest_log": {}}

        return await asyncio.to_thread(_read)

    async def _save_sent_log(self):
        """Save sent log atomically and asynchronously"""
        def _write():
            # Prune old entries (> 2 days old) to keep file small
            cutoff_key = int(time.time()) - 172800
            reminders_sent = self.sent_log.get("reminders_sent", {})
            reminders_sent = {
                k: v for k, v in reminders_sent.items()
                if isinstance(v, (int, float)) and v > cutoff_key
            }
            self.sent_log["reminders_sent"] = reminders_sent

            # Keep only last 30 days of digest logs
            today_key = datetime.now(ZoneInfo("Europe/Oslo")).strftime("%Y-%m-%d")
            digest_log = self.sent_log.get("digest_log", {})
            digest_log = {
                k: v for k, v in digest_log.items()
                if k >= (datetime.now(ZoneInfo("Europe/Oslo")) - timedelta(days=30)).strftime("%Y-%m-%d")
            }
            self.sent_log["digest_log"] = digest_log

            temp_path = self.storage_path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self.sent_log, f, ensure_ascii=False, indent=2)
                os.replace(temp_path, self.storage_path)
            except Exception as e:
                print(f"[REMIND] Sent log save error: {e}")
                if temp_path.exists():
                    os.remove(temp_path)

        await asyncio.to_thread(_write)

    def _has_been_sent(self, item_id, remind_type):
        """Check if a reminder was already sent for this item+type"""
        key = f"{item_id}:{remind_type}"
        sent_at = self.sent_log.setdefault("reminders_sent", {}).get(key)
        if sent_at is None:
            return False
        # Only suppress within a 60-minute window (allow re-alert for next occurrence)
        if time.time() - sent_at < 3600:
            return True
        # Update timestamp to keep it fresh
        self.sent_log["reminders_sent"][key] = int(time.time())
        return True

    async def _mark_sent(self, item_id, remind_type):
        """Mark a reminder as sent"""
        key = f"{item_id}:{remind_type}"
        self.sent_log.setdefault("reminders_sent", {})[key] = int(time.time())
        await self._save_sent_log()

    def _digest_already_sent_today(self, guild_id, channel_id):
        key = f"{guild_id}:{channel_id}"
        today_key = datetime.now(ZoneInfo("Europe/Oslo")).strftime("%Y-%m-%d")
        digest_log = self.sent_log.get("digest_log", {})
        return digest_log.get(key) == today_key

    async def _mark_digest_sent_today(self, guild_id, channel_id):
        key = f"{guild_id}:{channel_id}"
        today_key = datetime.now(ZoneInfo("Europe/Oslo")).strftime("%Y-%m-%d")
        self.sent_log.setdefault("digest_log", {})[key] = today_key
        await self._save_sent_log()

    # ---- 30-min warning ----

    async def check_upcoming_30min(self):
        """Check calendar items & reminders due within 30 minutes, ping creator in channel"""
        now = datetime.now(ZoneInfo("Europe/Oslo"))
        thirty_min = now + timedelta(minutes=30)

        # Check calendar items from CalendarManager
        if self.calendar:
            for guild_id, items_list in self.calendar.items.items():
                for item in items_list:
                    if item.get("completed"):
                        continue
                    try:
                        item_date = self._parse_item_datetime(item)
                    except (ValueError, TypeError):
                        continue
                    if item_date is None:
                        continue
                    # Already happened or exactly in the 30-min window
                    if now <= item_date <= thirty_min:
                        if self._has_been_sent(item["id"], "30min"):
                            continue
                        await self._send_item_reminder(item, "30min", "30 minutter")

        # Check reminders from ReminderManager
        if self.reminders:
            for guild_id, reminders_list in self.reminders.reminders.items():
                for reminder in reminders_list:
                    if reminder.get("completed"):
                        continue
                    due = reminder.get("due_date")
                    if not due:
                        continue
                    try:
                        reminder_dt = self._parse_due_date(due)
                    except Exception:
                        continue
                    if reminder_dt is None:
                        continue
                    if now <= reminder_dt <= thirty_min:
                        if self._has_been_sent(reminder["id"], "30min"):
                            continue
                        await self._send_reminder_remind(reminder, "30min", "30 minutter")

    # ---- Event happening NOW ----

    async def check_event_now(self):
        """Check for events happening NOW and send notifications"""
        now = datetime.now(ZoneInfo("Europe/Oslo"))
        one_minute_ago = now - timedelta(minutes=1)
        one_minute_ahead = now + timedelta(minutes=1)

        # Check calendar items
        if self.calendar:
            for guild_id, items_list in self.calendar.items.items():
                for item in items_list:
                    if item.get("completed"):
                        continue
                    try:
                        item_date = self._parse_item_datetime(item)
                    except (ValueError, TypeError):
                        continue
                    if item_date is None:
                        continue
                    # Check if event is happening NOW (within 1 minute window)
                    if one_minute_ago <= item_date <= one_minute_ahead:
                        if self._has_been_sent(item["id"], "now"):
                            continue
                        await self._send_item_reminder(item, "now", "nå")

        # Check reminders
        if self.reminders:
            for guild_id, reminders_list in self.reminders.reminders.items():
                for reminder in reminders_list:
                    if reminder.get("completed"):
                        continue
                    due = reminder.get("due_date")
                    if not due:
                        continue
                    try:
                        reminder_dt = self._parse_due_date(due)
                    except Exception:
                        continue
                    if reminder_dt is None:
                        continue
                    if one_minute_ago <= reminder_dt <= one_minute_ahead:
                        if self._has_been_sent(reminder["id"], "now"):
                            continue
                        await self._send_reminder_remind(reminder, "now", "nå")

    # ---- Event just passed ----

    async def check_event_passed(self):
        """Check for events that just happened (within last 5 minutes)"""
        now = datetime.now(ZoneInfo("Europe/Oslo"))
        five_minutes_ago = now - timedelta(minutes=5)

        # Check calendar items
        if self.calendar:
            for guild_id, items_list in self.calendar.items.items():
                for item in items_list:
                    if item.get("completed"):
                        continue
                    try:
                        item_date = self._parse_item_datetime(item)
                    except (ValueError, TypeError):
                        continue
                    if item_date is None:
                        continue
                    # Check if event just happened (within last 5 minutes)
                    if five_minutes_ago <= item_date <= now:
                        if self._has_been_sent(item["id"], "passed"):
                            continue
                        await self._send_item_reminder(item, "passed", "akkurat nå")

        # Check reminders
        if self.reminders:
            for guild_id, reminders_list in self.reminders.reminders.items():
                for reminder in reminders_list:
                    if reminder.get("completed"):
                        continue
                    due = reminder.get("due_date")
                    if not due:
                        continue
                    try:
                        reminder_dt = self._parse_due_date(due)
                    except Exception:
                        continue
                    if reminder_dt is None:
                        continue
                    if five_minutes_ago <= reminder_dt <= now:
                        if self._has_been_sent(reminder["id"], "passed"):
                            continue
                        await self._send_reminder_remind(reminder, "passed", "akkurat nå")

    # ---- Morning digest at 09:00 ----

    async def check_morning_digest(self):
        """If it's past 09:00 and we haven't sent a morning digest yet per guild, send one"""
        oslo_tz = ZoneInfo("Europe/Oslo")
        now = datetime.now(oslo_tz)

        # Trigger between 09:00 and 10:00 (wider window for reliability)
        if not (9 <= now.hour < 10):
            return

        # Check all guilds that have calendar data
        if self.calendar:
            for guild_id in self.calendar.items:
                # Try to find a channel to send the digest to:
                # Use the channel from the earliest upcoming item, or guild default
                channel_id = self._find_digest_channel(guild_id)
                if channel_id is None:
                    continue

                if self._digest_already_sent_today(guild_id, channel_id):
                    continue

                items = self.calendar.get_upcoming(guild_id, days=1)
                if not items:
                    continue

                digest = self._format_morning_digest(items, now)
                await self._send_to_channel(channel_id, digest)
                await self._mark_digest_sent_today(guild_id, channel_id)

    # ---- Helpers ----

    def _parse_item_datetime(self, item):
        """Parse date+time from a calendar item into a Europe/Oslo datetime"""
        oslo_tz = ZoneInfo("Europe/Oslo")
        date_str = item.get("date", "")
        time_str = item.get("time") or None

        if not date_str:
            return None

        dt = datetime.strptime(date_str, "%d.%m.%Y").replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=oslo_tz
        )
        if time_str:
            try:
                parts = time_str.split(":")
                dt = dt.replace(hour=int(parts[0]), minute=int(parts[1]))
            except (ValueError, IndexError):
                pass
        else:
            # For date-only events, use 09:00 as default time
            dt = dt.replace(hour=9, minute=0)
        return dt

    def _parse_due_date(self, due_str):
        """Parse DD.MM.YYYY or DD.MM into a datetime"""
        oslo_tz = ZoneInfo("Europe/Oslo")
        try:
            dt = datetime.strptime(due_str, "%d.%m.%Y").replace(
                hour=9, minute=0, tzinfo=oslo_tz
            )
            return dt
        except ValueError:
            pass
        try:
            dt = datetime.strptime(due_str, "%d.%m").replace(
                year=datetime.now().year, hour=9, minute=0, tzinfo=oslo_tz
            )
            return dt
        except ValueError:
            return None

    def _find_digest_channel(self, guild_id):
        """Find a sensible channel_id for the morning digest"""
        items = self.calendar.get_upcoming(guild_id, days=1)
        for item in items:
            if item.get("channel_id"):
                return int(item["channel_id"])
        # Fallback: use guild_id
        return int(guild_id)

    def _format_morning_digest(self, items, now):
        """Format morning digest message in Norwegian"""
        day_names = [
            "mandag", "tirsdag", "onsdag", "torsdag",
            "fredag", "lørdag", "søndag",
        ]
        day_name = day_names[now.weekday()]
        date_str = now.strftime("%d.%m.%Y")

        lines = [
            f"☀️ **God morgen!** {day_name} {date_str}",
            "",
        ]
        for item in items[:8]:
            time_str = f" kl. {item['time']}" if item.get("time") else ""
            lines.append(f"  {item['title']}{time_str}")

        if len(items) > 8:
            lines.append(f"  ...og {len(items) - 8} til. Bruk @inebotten kalender for hele listen.")

        lines.append("")
        lines.append("Ha ein fin dag! ✨")
        return "\n".join(lines)

    async def _send_item_reminder(self, item, remind_type, label):
        """Send a reminder for a calendar item in its original channel"""
        channel_id = item.get("channel_id")
        time_str = f" kl. {item['time']}" if item.get("time") else ""

        # Different messages based on reminder type
        if remind_type == "30min":
            message = (
                f"⏰ **Påminnelse: {item['title']}**\n\n"
                f"Det er {label} til!{time_str}\n\n"
                f"Klar? 😊"
            )
        elif remind_type == "now":
            message = (
                f"🔔 **Starter nå: {item['title']}**\n\n"
                f"Det er på tide!{time_str}\n\n"
                f"Lykke til! 🎉"
            )
        elif remind_type == "passed":
            message = (
                f"✅ **Akkurat ferdig: {item['title']}**\n\n"
                f"Håper det gikk bra!{time_str}\n\n"
                f"Bra jobba! 👍"
            )
        else:
            message = f"⏰ **{item['title']}** - {label}{time_str}"

        await self._send_mentions_item(channel_id, item, message)
        await self._mark_sent(item["id"], remind_type)
        
        # Update statistics
        if remind_type == "30min":
            self.stats["30min_sent"] += 1
        elif remind_type == "now":
            self.stats["now_sent"] += 1
        elif remind_type == "passed":
            self.stats["passed_sent"] += 1

    async def _send_reminder_remind(self, reminder, remind_type, label):
        """Send a reminder for a reminder item"""
        channel_id = reminder.get("channel_id")
        
        # Different messages based on reminder type
        if remind_type == "30min":
            message = (
                f"⏰ **Påminnelse: {reminder['text']}**\n\n"
                f"Det er {label} til!\n\n"
                f"Klar? 😊"
            )
        elif remind_type == "now":
            message = (
                f"🔔 **Nå: {reminder['text']}**\n\n"
                f"Det er på tide!\n\n"
                f"Lykke til! 🎉"
            )
        elif remind_type == "passed":
            message = (
                f"✅ **Ferdig: {reminder['text']}**\n\n"
                f"Bra jobba! 👍"
            )
        else:
            message = f"⏰ **{reminder['text']}** - {label}"

        if channel_id:
            await self._send_to_channel(channel_id, message)
        else:
            print(f"[REMIND] No channel_id for reminder: {reminder['text']}")

        await self._mark_sent(reminder["id"], remind_type)
        
        # Update statistics
        if remind_type == "30min":
            self.stats["30min_sent"] += 1
        elif remind_type == "now":
            self.stats["now_sent"] += 1
        elif remind_type == "passed":
            self.stats["passed_sent"] += 1

    async def _send_mentions_item(self, channel_id, item, message):
        """Send a message mentioning the item creator"""
        # Try to mention the original creator via Discord user ID
        user_id = item.get("user_id")
        if user_id and user_id != "gcal_sync":
            mention = f"<@{user_id}>"
            message = f"{mention}\n\n{message}"
        elif user_id == "gcal_sync":
            # For GCal items, maybe just add a header
            message = f"📅 **Google Calendar Sync**\n\n{message}"

        await self._send_to_channel(channel_id, message)

    async def _send_to_channel(self, channel_id, message):
        """Send a message to a channel_id. Uses the send function if available."""
        if not channel_id:
            print("[REMIND] No channel_id to send reminder to")
            return

        try:
            if self.get_channel:
                channel = self.get_channel(int(channel_id))
                if channel:
                    await channel.send(message)
                    print(f"[REMIND] Sent to channel {channel_id}: {message[:80]}")
                    return

            # Fallback: use send_channel_message
            if self.send_channel_message:
                await self.send_channel_message(int(channel_id), message)
                print(f"[REMIND] Sent (fallback) to channel {channel_id}: {message[:80]}")
        except Exception as e:
            print(f"[REMIND] Failed to send to channel {channel_id}: {e}")
            self.stats["errors"] += 1

    # ---- Main loop ----

    async def start(self):
        """Start the reminder checker background task"""
        self.running = True
        print("[REMIND] Reminder checker started")
        while self.running:
            try:
                await self.check_upcoming_30min()
                await self.check_event_now()
                await self.check_event_passed()
                await self.check_morning_digest()

                # Periodic Google Calendar sync (every 15 minutes)
                if self.calendar and self.calendar.gcal_enabled:
                    now_ts = time.time()
                    if now_ts - self._last_gcal_sync > 900:  # 900 seconds = 15 min
                        try:
                            await self.calendar.sync_from_gcal()
                            self._last_gcal_sync = now_ts
                        except Exception as e:
                            print(f"[REMIND] GCal sync error: {e}")
            except Exception as e:
                print(f"[REMIND] Error in checker loop: {e}")
                self.stats["errors"] += 1

            # Check every 60 seconds
            for _ in range(60):
                if not self.running:
                    break
                import asyncio
                await asyncio.sleep(1)

    def stop(self):
        """Stop the reminder checker"""
        self.running = False
        print("[REMIND] Reminder checker stopped")
        print(f"[REMIND] Statistics: {self.stats}")
