#!/usr/bin/env python3
"""
Simple Calendar Manager for Inebotten
Everything is just a calendar item with a date
"""

import json
import os
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any


class AwaitableDict(dict):
    """Dictionary result that can also be awaited by async handlers."""

    def __await__(self):
        async def _return():
            return self
        return _return().__await__()


class AwaitableValue:
    """Generic result wrapper that can be awaited without breaking sync callers."""

    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _return():
            return self.value
        return _return().__await__()

    def __bool__(self):
        return bool(self.value)

    def __iter__(self):
        return iter(self.value)

    def __getitem__(self, key):
        return self.value[key]

    def __repr__(self):
        return repr(self.value)


class CalendarManager:
    """
    Manages calendar items - everything is just something happening on a date
    """

    def __init__(self, storage_path=None, gcal_manager=None, owner_email=None, owner_name=None):
        if storage_path is None:
            storage_path = (
                Path.home() / ".hermes" / "discord" / "data" / "calendar.json"
            )

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.gcal = gcal_manager
        self.gcal_enabled = gcal_manager is not None
        self.owner_email = owner_email
        self.owner_name = owner_name
        self.items = {}  # {guild_id: [item1, item2, ...]}

    async def setup(self):
        """Async initialization"""
        self.items = await self._load_data()
        print(f"[CAL] Calendar system initialized with {sum(len(v) for v in self.items.values())} items")

    async def _load_data(self) -> Dict:
        """Load calendar data from JSON file asynchronously"""
        if not self.storage_path.exists():
            return {}

        def _read():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CAL] Error loading calendar data: {e}")
                return {}

        return await asyncio.to_thread(_read)

    async def _save_data(self):
        """Save calendar data to JSON file atomically and asynchronously"""
        await asyncio.to_thread(self._save_data_sync)

    def _save_data_sync(self):
        """Save calendar data to JSON file atomically."""
        temp_path = self.storage_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.storage_path)
        except Exception as e:
            print(f"[CAL] Error saving calendar data: {e}")
            if temp_path.exists():
                os.remove(temp_path)

    def add_item(
        self,
        guild_id,
        user_id,
        username,
        title,
        date_str,
        time_str=None,
        recurrence=None,
        recurrence_day=None,
        gcal_event_id=None,
        gcal_link=None,
        channel_id=None,
    ):
        """Add a new item to the calendar"""
        # Validate date format
        if not self._validate_date_format(date_str):
            # Try to fix padding if possible
            parts = date_str.split('.')
            if len(parts) == 3:
                try:
                    date_str = f"{int(parts[0]):02d}.{int(parts[1]):02d}.{int(parts[2])}"
                except ValueError:
                    pass

        guild_key = str(guild_id)
        if guild_key not in self.items:
            self.items[guild_key] = []

        item = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "username": username,
            "title": title,
            "date": date_str,
            "time": time_str,
            "recurrence": recurrence,
            "recurrence_day": recurrence_day,
            "created_at": datetime.now().isoformat(),
            "completed": False,
            "gcal_event_id": gcal_event_id,
            "gcal_link": gcal_link,
            "channel_id": str(channel_id) if channel_id else None,
        }

        self.items[guild_key].append(item)
        self._save_data_sync()
        return AwaitableDict(item)

    def delete_item(self, guild_id, item_num):
        """Delete an item by its list number"""
        guild_key = str(guild_id)
        items = self.get_upcoming(guild_id, days=365)

        if item_num is not None and 1 <= item_num <= len(items):
            item_to_delete = items[item_num - 1]
            title = item_to_delete["title"]

            # Remove from GCal if enabled
            if self.gcal_enabled and item_to_delete.get("gcal_event_id"):
                try:
                    self.gcal.delete_event(item_to_delete["gcal_event_id"])
                    print(f"[CAL] Deleted from GCal: {title}")
                except Exception as e:
                    print(f"[CAL] GCal delete failed: {e}")

            # Remove from main list
            self.items[guild_key] = [
                i for i in self.items[guild_key] if i["id"] != item_to_delete["id"]
            ]

            self._save_data_sync()
            return AwaitableValue((True, title))

        return AwaitableValue((False, None))

    async def delete_item_by_title(self, guild_id, title_search):
        """Delete a single item by title matching"""
        guild_key = str(guild_id)
        if guild_key not in self.items:
            return False, None

        title_search = title_search.lower()
        for i, item in enumerate(self.items[guild_key]):
            if title_search in item["title"].lower():
                title = item["title"]
                self.items[guild_key].pop(i)
                await self._save_data()
                return True, title

        return False, None

    async def delete_items_by_title(self, guild_id, title_search):
        """Delete multiple items by title matching"""
        guild_key = str(guild_id)
        if guild_key not in self.items:
            return 0, []

        title_search = title_search.lower()
        to_keep = []
        deleted_titles = []

        for item in self.items[guild_key]:
            if title_search in item["title"].lower():
                deleted_titles.append(item["title"])
            else:
                to_keep.append(item)

        count = len(deleted_titles)
        if count > 0:
            self.items[guild_key] = to_keep
            await self._save_data()

        return count, deleted_titles

    def complete_item(self, guild_id, item_num=None, item_id=None):
        """Mark an item as complete (or move to next date if recurring)"""
        guild_key = str(guild_id)
        items = self.get_upcoming(guild_id, days=365)

        if item_id:
            for item in items:
                if item.get("id") == item_id:
                    return AwaitableValue(self._process_completion_sync(guild_key, item))
            return AwaitableValue((False, None, None))

        if item_num is not None and 1 <= item_num <= len(items):
            item = items[item_num - 1]
            return AwaitableValue(self._process_completion_sync(guild_key, item))

        return AwaitableValue((False, None, None))

    async def complete_item_by_title(self, guild_id, title_search):
        """Mark an item as complete by title matching"""
        guild_key = str(guild_id)
        items = self.get_upcoming(guild_id, days=365)

        title_search = title_search.lower()
        for item in items:
            if title_search in item["title"].lower():
                return await self._process_completion(guild_key, item)

        return False, None, None

    async def complete_items_by_title(self, guild_id, title_search):
        """Mark multiple items as complete by title matching"""
        guild_key = str(guild_id)
        items = self.get_upcoming(guild_id, days=365)

        title_search = title_search.lower()
        count = 0
        completed_titles = []
        has_recurring = False

        for item in items:
            if title_search in item["title"].lower():
                success, title, next_date = await self._process_completion(guild_key, item)
                if success:
                    count += 1
                    completed_titles.append(title)
                    if next_date:
                        has_recurring = True

        return count, completed_titles, has_recurring

    async def _process_completion(self, guild_key, item):
        """Internal helper to handle completion logic"""
        return self._process_completion_sync(guild_key, item)

    def _process_completion_sync(self, guild_key, item):
        """Internal helper to handle completion logic synchronously."""
        title = item["title"]

        if item.get("recurrence"):
            # Update to next date
            next_date = self._calculate_next_date(item["date"], item["recurrence"])
            item["date"] = next_date
            self._save_data_sync()
            return True, title, next_date
        else:
            # Mark as completed
            item["completed"] = True
            
            # Sync to GCal if enabled
            if self.gcal_enabled and item.get("gcal_event_id"):
                try:
                    self.gcal.update_event(item["gcal_event_id"], completed=True)
                    print(f"[CAL] Marked completed in GCal: {title}")
                except Exception as e:
                    print(f"[CAL] GCal update failed: {e}")

            self._save_data_sync()
            return True, title, None

    def _calculate_next_date(self, current_date_str, recurrence):
        """Calculate next occurrence date with month-end safety"""
        try:
            current_date = datetime.strptime(current_date_str, "%d.%m.%Y")
            
            if recurrence == "daily":
                next_date = current_date + timedelta(days=1)
            elif recurrence == "weekly":
                next_date = current_date + timedelta(weeks=1)
            elif recurrence == "biweekly":
                next_date = current_date + timedelta(weeks=2)
            elif recurrence == "monthly":
                # Handle month transition safely
                year = current_date.year + (current_date.month // 12)
                month = (current_date.month % 12) + 1
                day = current_date.day
                
                # Clamp day to max days in next month
                import calendar as py_cal
                last_day = py_cal.monthrange(year, month)[1]
                next_date = datetime(year, month, min(day, last_day))
            elif recurrence == "yearly":
                try:
                    next_date = current_date.replace(year=current_date.year + 1)
                except ValueError:
                    # Feb 29 leap year case
                    next_date = current_date.replace(year=current_date.year + 1, day=28)
            else:
                return None
                
            return next_date.strftime("%d.%m.%Y")
        except Exception as e:
            print(f"[CALENDAR] Calendar parse error: {e}")
            return None

    async def sync_from_gcal(self, default_guild_id=None):
        """
        Pull events from Google Calendar and sync to local store
        """
        if not self.gcal_enabled or not self.gcal.is_configured():
            return 0

        print("[CAL] Syncing from Google Calendar...")
        gcal_events = self.gcal.list_upcoming_events(days=30)
        if gcal_events is None:
            return 0

        added_count = 0
        updated_count = 0

        # Build a map of gcal_event_id -> (guild_id, item) for quick lookup
        gcal_map = {}
        for guild_id, items in self.items.items():
            for item in items:
                if item.get("gcal_event_id"):
                    gcal_map[item["gcal_event_id"]] = (guild_id, item)

        for event in gcal_events:
            gcal_id = event.get("id")
            if not gcal_id:
                continue

            summary = event.get("summary", "Uten tittel")
            
            # Check if marked as completed in GCal
            gcal_completed = summary.endswith(" [FERDIG]")
            if gcal_completed:
                summary = summary.replace(" [FERDIG]", "").strip()

            start = event.get("start", {})
            
            # Parse date and time from GCal
            date_str = ""
            time_str = None
            
            try:
                if "dateTime" in start:
                    # ISO format: 2024-04-24T10:00:00+02:00
                    dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
                    from zoneinfo import ZoneInfo
                    local_dt = dt.astimezone(ZoneInfo("Europe/Oslo"))
                    date_str = local_dt.strftime("%d.%m.%Y")
                    time_str = local_dt.strftime("%H:%M")
                else:
                    # Date only: 2024-04-24
                    d_str = start.get("date", "")
                    if d_str:
                        dt = datetime.strptime(d_str, "%Y-%m-%d")
                        date_str = dt.strftime("%d.%m.%Y")
            except Exception as e:
                print(f"[CAL] Error parsing GCal date for {summary}: {e}")
                continue

            if not date_str:
                continue

            # Extract creator information if available
            creator = event.get("creator", {})
            organizer = event.get("organizer", {})
            
            # Check for Discord metadata in extended properties first
            ext_props = event.get("extendedProperties", {}).get("private", {})
            gcal_username = ext_props.get("discord_username")
            gcal_user_id = ext_props.get("discord_user_id") or "gcal_sync"

            if not gcal_username:
                # Fallback to Display Name > Email > Default
                gcal_username = creator.get("displayName") or organizer.get("displayName")
                
                if not gcal_username:
                    email = creator.get("email") or organizer.get("email")
                    if email and self.owner_email and email.lower() == self.owner_email.lower() and self.owner_name:
                        gcal_username = self.owner_name
                    elif email and "@" in email:
                        gcal_username = email.split("@")[0]
                    else:
                        gcal_username = email or self.owner_name or "Google Calendar"
                
            # Final fallback if still empty
            if not gcal_username or gcal_username == "Google Calendar":
                gcal_username = self.owner_name or "Google Calendar"

            if gcal_id in gcal_map:
                # Existing item, check for updates
                guild_id, item = gcal_map[gcal_id]
                changed = False
                
                if item["title"] != summary:
                    item["title"] = summary
                    changed = True
                if item["date"] != date_str:
                    item["date"] = date_str
                    changed = True
                if item.get("time") != time_str:
                    item["time"] = time_str
                    changed = True
                
                # Update username/user_id if it's currently generic and we found better info
                if item.get("username") == "Google Calendar" and gcal_username != "Google Calendar":
                    item["username"] = gcal_username
                    changed = True
                
                if item.get("user_id") == "gcal_sync" and gcal_user_id != "gcal_sync":
                    item["user_id"] = gcal_user_id
                    changed = True
                
                # Check if it was marked as completed in GCal
                if gcal_completed and not item.get("completed"):
                    item["completed"] = True
                    changed = True
                
                if changed:
                    updated_count += 1
            else:
                # New item from GCal
                guild_id = default_guild_id or (list(self.items.keys())[0] if self.items else "global")
                
                await self.add_item(
                    guild_id=guild_id,
                    user_id=gcal_user_id,
                    username=gcal_username,
                    title=summary,
                    date_str=date_str,
                    time_str=time_str,
                    gcal_event_id=gcal_id,
                    gcal_link=event.get("htmlLink"),
                )
                
                # If it was completed, mark it so (add_item defaults to False)
                if gcal_completed:
                    self.items[str(guild_id)][-1]["completed"] = True
                
                added_count += 1

        if added_count > 0 or updated_count > 0:
            await self._save_data()
            print(f"[CAL] Sync complete: {added_count} added, {updated_count} updated")
        
        return added_count + updated_count

    def get_upcoming(self, guild_id, days=30, include_completed=False):
        """
        Get upcoming calendar items
        """
        guild_key = str(guild_id)

        if guild_key not in self.items:
            return []

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = today + timedelta(days=days)

        upcoming = []
        for item in self.items[guild_key]:
            if not include_completed and item.get("completed"):
                continue

            if item.get("date"):
                try:
                    item_date = datetime.strptime(item["date"], "%d.%m.%Y")
                    if include_completed or (today <= item_date <= cutoff):
                        upcoming.append(item)
                except Exception as e:
                    print(f"[CALENDAR] Calendar loop error: {e}")
                    continue

        # Sort by date
        upcoming.sort(key=lambda x: datetime.strptime(x["date"], "%d.%m.%Y"))
        return upcoming

    def format_list(self, guild_id, days=90, show_completed=False, footer=None):
        """
        Format calendar items for display
        """
        items = self.get_upcoming(guild_id, days=days, include_completed=False)

        if not items:
            return None

        lines = ["📅 **Kalender:**"]

        for i, item in enumerate(items[:10], 1):
            time_str = f" kl. {item['time']}" if item.get("time") else ""

            if item.get("completed"):
                status_indicator = "✓"
            elif item.get("gcal_event_id") or item.get("gcal_link"):
                status_indicator = "📅"
            else:
                status_indicator = "📌"

            recurrence_str = ""
            if item.get("recurrence"):
                labels = {
                    "weekly": "uke",
                    "biweekly": "2uker",
                    "monthly": "mnd",
                    "yearly": "år",
                }
                if item.get("recurrence_day"):
                    recurrence_str = f" 🔄 {item['recurrence_day'][:3].lower()} {labels.get(item['recurrence'], '')}"
                else:
                    recurrence_str = f" 🔄 {labels.get(item['recurrence'], '')}"

            title_display = (
                f"~~{item['title']}~~" if item.get("completed") else item["title"]
            )
            
            creator_str = f" ({item.get('username', 'Ukjent')})"

            lines.append(
                f"{status_indicator} **{i}.** {title_display} — _{item['date']}{time_str}_{creator_str}{recurrence_str}"
            )

        if show_completed:
            all_items = self.items.get(str(guild_id), [])
            completed = [i for i in all_items if i.get("completed")][:3]
            if completed:
                lines.append("\n✅ **Nylig fullført:**")
                for item in completed:
                    lines.append(f"  ✓ ~~{item['title']}~~")

        return "\n".join(lines)

    def format_single_item(self, item):
        """Format a single item for display"""
        time_str = f" kl. {item['time']}" if item.get("time") else ""

        lines = [
            f"✅ **Lagt til i kalenderen!**",
            "",
            f"📌 **{item['title']}**",
            f"📅 {item['date']}{time_str}",
            f"👤 Lagt til av: {item.get('username', 'Ukjent')}",
        ]

        if item.get("recurrence"):
            labels = {
                "weekly": "hver uke",
                "biweekly": "annenhver uke",
                "monthly": "hver måned",
                "yearly": "hvert år",
            }
            if item.get("recurrence_day"):
                lines.append(
                    f"🔄 Gjentas hver {item['recurrence_day']} ({labels.get(item['recurrence'], item['recurrence'])})"
                )
            else:
                lines.append(
                    f"🔄 Gjentas {labels.get(item['recurrence'], item['recurrence'])}"
                )

        if item.get("gcal_link"):
            lines.append("")
            lines.append(f"📅 [Se i Google Calendar]({item['gcal_link']})")

        lines.append("")
        lines.append("— *Bruk `@inebotten kalender` for å se alt*")

        return "\n".join(lines)

    def _validate_date_format(self, date_str):
        """Validate DD.MM.YYYY format"""
        try:
            datetime.strptime(date_str, "%d.%m.%Y")
            return True
        except (ValueError, TypeError):
            return False


if __name__ == "__main__":
    # Test
    print("=== Calendar Manager Test ===\n")

    manager = CalendarManager(storage_path="/tmp/test_calendar_simple.json")

    # Add various items
    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Grillfest",
        date_str="28.03.2026",
        time_str="18:00",
    )
    print("Added: Grillfest")

    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Sende meldekort",
        date_str="04.04.2026",
        time_str="10:00",
        recurrence="biweekly",
        recurrence_day="lørdag",
    )
    print("Added: Sende meldekort (recurring)")

    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Kjøpe melk",
        date_str="29.03.2026",
    )
    print("Added: Kjøpe melk")

    print("\n--- Calendar ---")
    print(manager.format_list("test"))

    print("\n--- Complete item #2 ---")
    success, title, next_date = manager.complete_item("test", item_num=2)
    print(f"Completed: {title}, next: {next_date}")

    print("\n--- Calendar after ---")
    print(manager.format_list("test"))

    # Cleanup
    import os

    os.remove("/tmp/test_calendar_simple.json")
