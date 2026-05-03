#!/usr/bin/env python3
"""
Reminder Manager for Inebotten
Tracks reminders that can be marked as completed
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path


class ReminderManager:
    """
    Manages reminders that users can mark as completed
    """

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / ".hermes" / "discord" / "reminders.json"

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.reminders = self._load_reminders()

    def _load_reminders(self):
        """Load reminders from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CALENDAR] Reminder load error: {e}")
                return {}
        return {}

    def _save_reminders(self):
        """Save reminders to storage"""
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.reminders, f, ensure_ascii=False, indent=2)

    def add_reminder(
        self,
        guild_id,
        user_id,
        username,
        text,
        due_date=None,
        recurrence=None,
        recurrence_day=None,
        rrule_day=None,
        gcal_event_id=None,
        gcal_link=None,
        channel_id=None,
    ):
        """
        Add a new reminder

        Args:
            guild_id: Discord guild ID
            user_id: User who created it
            username: Display name
            text: Reminder text
            due_date: Optional due date (DD.MM.YYYY)
            recurrence: Optional recurrence type ('weekly', 'biweekly', etc.)
            recurrence_day: Optional day name (e.g., 'lørdag')
            rrule_day: Optional RRULE day code (e.g., 'SA')
            gcal_event_id: Optional Google Calendar event ID
            gcal_link: Optional Google Calendar link
            channel_id: Optional Discord channel ID for reminder pings

        Returns:
            reminder_id
        """
        guild_key = str(guild_id)
        reminder_id = f"rem_{guild_id}_{int(datetime.now().timestamp())}"

        if guild_key not in self.reminders:
            self.reminders[guild_key] = []
        if channel_id:
            channel_id = str(channel_id)

        reminder = {
            "id": reminder_id,
            "user_id": str(user_id),
            "username": username,
            "text": text,
            "due_date": due_date,
            "recurrence": recurrence,
            "recurrence_day": recurrence_day,
            "rrule_day": rrule_day,
            "gcal_event_id": gcal_event_id,
            "gcal_link": gcal_link,
            "channel_id": channel_id,
            "created_at": datetime.now().isoformat(),
            "completed": False,
            "completed_at": None,
            "completed_by": None,
        }

        self.reminders[guild_key].append(reminder)
        self._save_reminders()

        return reminder_id

    def complete_reminder(self, guild_id, reminder_num=None, reminder_id=None):
        """
        Mark a reminder as completed
        For recurring reminders, advances the due date instead of completing

        Args:
            guild_id: Discord guild ID
            reminder_num: Number in the list (1-indexed) OR
            reminder_id: Specific reminder ID

        Returns:
            (success, reminder_text, next_date) - next_date is set for recurring reminders
        """
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            return False, None, None

        # Get incomplete reminders
        incomplete = [r for r in self.reminders[guild_key] if not r["completed"]]

        target_reminder = None

        if reminder_num is not None:
            # Find by number
            idx = reminder_num - 1
            if 0 <= idx < len(incomplete):
                target_reminder = incomplete[idx]

        elif reminder_id:
            # Find by ID
            for reminder in self.reminders[guild_key]:
                if reminder["id"] == reminder_id and not reminder["completed"]:
                    target_reminder = reminder
                    break

        if not target_reminder:
            return False, None, None

        # Check if it's a recurring reminder
        if target_reminder.get("recurrence") and target_reminder.get("due_date"):
            # Calculate next occurrence
            next_date = self._calculate_next_date(
                target_reminder["due_date"],
                target_reminder["recurrence"],
                target_reminder.get("recurrence_day"),
            )

            if next_date:
                target_reminder["due_date"] = next_date
                target_reminder["completed_count"] = (
                    target_reminder.get("completed_count", 0) + 1
                )
                self._save_reminders()
                return True, target_reminder["text"], next_date

        # Non-recurring reminder - mark as completed
        target_reminder["completed"] = True
        target_reminder["completed_at"] = datetime.now().isoformat()
        self._save_reminders()
        return True, target_reminder["text"], None

    def _calculate_next_date(self, current_date_str, recurrence, recurrence_day=None):
        """
        Calculate the next occurrence date for a recurring reminder

        Args:
            current_date_str: Current date in DD.MM.YYYY format
            recurrence: 'weekly', 'biweekly', 'monthly', 'yearly'
            recurrence_day: Optional day name (e.g., 'lørdag')

        Returns:
            Next date string in DD.MM.YYYY format or None
        """
        try:
            current = datetime.strptime(current_date_str, "%d.%m.%Y")

            if recurrence == "weekly":
                next_date = current + timedelta(weeks=1)
            elif recurrence == "biweekly":
                next_date = current + timedelta(weeks=2)
            elif recurrence == "monthly":
                # Add one month (approximate)
                if current.month == 12:
                    next_date = current.replace(year=current.year + 1, month=1)
                else:
                    next_date = current.replace(month=current.month + 1)
            elif recurrence == "yearly":
                next_date = current.replace(year=current.year + 1)
            else:
                return None

            return next_date.strftime("%d.%m.%Y")
        except Exception as e:
            print(f"[CALENDAR] Reminder parse error: {e}")
            return None

    def get_active_reminders(self, guild_id, include_events=True):
        """
        Get all active (incomplete) reminders

        Returns:
            List of reminder dicts
        """
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            return []

        # Filter incomplete reminders
        active = [r for r in self.reminders[guild_key] if not r["completed"]]

        # Sort by creation date
        active.sort(key=lambda x: x["created_at"])

        return active

    def get_completed_reminders(self, guild_id, days=7):
        """
        Get recently completed reminders
        """
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            return []

        cutoff = datetime.now() - timedelta(days=days)

        completed = []
        for r in self.reminders[guild_key]:
            if r["completed"] and r.get("completed_at"):
                completed_at = datetime.fromisoformat(r["completed_at"])
                if completed_at >= cutoff:
                    completed.append(r)

        return completed

    def format_reminders_list(self, guild_id, show_completed=False):
        """Format reminders for display"""
        active = self.get_active_reminders(guild_id)

        if not active and not show_completed:
            return None  # No reminders to show

        lines = []

        if active:
            for i, r in enumerate(active[:8], 1):  # Show max 8
                checkbox = "⬜"
                due = f" (frist: {r['due_date']})" if r.get("due_date") else ""

                # Add recurrence indicator
                recurrence_str = ""
                if r.get("recurrence"):
                    recurrence_labels = {
                        "weekly": "uke",
                        "biweekly": "2uker",
                        "monthly": "mnd",
                        "yearly": "år",
                    }
                    if r.get("recurrence_day"):
                        day_abbr = r["recurrence_day"][:3].lower()
                        recurrence_str = f" 🔄 {day_abbr} {recurrence_labels.get(r['recurrence'], '')}"
                    else:
                        recurrence_str = (
                            f" 🔄 {recurrence_labels.get(r['recurrence'], '')}"
                        )

                lines.append(f"{checkbox} **{i}.** {r['text']}{due}{recurrence_str}")

                # Show GCal link if available
                if r.get("gcal_link"):
                    lines.append(f"   🔗 [Åpne i Google Calendar]({r['gcal_link']})")

        if show_completed:
            completed = self.get_completed_reminders(guild_id, days=3)
            if completed:
                lines.append("\n✅ **Fullført nylig:**")
                for r in completed[:5]:
                    lines.append(f"✓ ~~{r['text']}~~")

        return "\n".join(lines) if lines else None

    def delete_old_completed(self, guild_id, days=7):
        """Delete reminders completed more than N days ago"""
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            return

        cutoff = datetime.now() - timedelta(days=days)

        self.reminders[guild_key] = [
            r
            for r in self.reminders[guild_key]
            if not r["completed"]
            or (
                r.get("completed_at")
                and datetime.fromisoformat(r["completed_at"]) >= cutoff
            )
        ]

        self._save_reminders()

    def edit_reminder(self, guild_id, index, title=None, date=None, time=None, recurrence=None):
        """
        Edit an existing reminder by its 1-based index in active reminders.

        Args:
            guild_id: Discord guild ID
            index: 1-based index in the active reminders list
            title: New reminder text (maps to 'text' field)
            date: New due date (maps to 'due_date' field)
            time: Not applied — reminders do not store a separate time field
            recurrence: New recurrence type

        Returns:
            Updated reminder dict

        Raises:
            ValueError: If index is invalid
        """
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            raise ValueError(f"Ingen påminnelser funnet for denne serveren.")

        active = [r for r in self.reminders[guild_key] if not r["completed"]]
        active.sort(key=lambda x: x["created_at"])

        idx = index - 1
        if idx < 0 or idx >= len(active):
            raise ValueError(f"Ugyldig påminnelse-nummer: {index}")

        target = active[idx]

        if title is not None:
            target["text"] = title
        if date is not None:
            target["due_date"] = date
        if recurrence is not None:
            target["recurrence"] = recurrence

        self._save_reminders()
        return target

    def delete_reminder_by_id(self, guild_id, index):
        """
        Delete a reminder by its 1-based index in active reminders.

        Args:
            guild_id: Discord guild ID
            index: 1-based index in the active reminders list

        Returns:
            Deleted reminder dict

        Raises:
            ValueError: If index is invalid
        """
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            raise ValueError(f"Ingen påminnelser funnet for denne serveren.")

        active = [r for r in self.reminders[guild_key] if not r["completed"]]
        active.sort(key=lambda x: x["created_at"])

        idx = index - 1
        if idx < 0 or idx >= len(active):
            raise ValueError(f"Ugyldig påminnelse-nummer: {index}")

        target = active[idx]
        self.reminders[guild_key].remove(target)
        self._save_reminders()
        return target

    def search_reminders(self, guild_id, query):
        """
        Search all reminders (active and completed) by title text.

        Args:
            guild_id: Discord guild ID
            query: Substring to search for (case-insensitive)

        Returns:
            List of matching reminder dicts
        """
        guild_key = str(guild_id)
        query_lower = query.lower()

        if guild_key not in self.reminders:
            return []

        matches = [
            r
            for r in self.reminders[guild_key]
            if query_lower in r.get("text", "").lower()
        ]
        return matches


def parse_reminder_command(message_content):
    """
    Parse reminder commands

    Returns:
        dict with action and data, or None
    """
    content_lower = message_content.lower()

    # Check for reminder creation
    reminder_keywords = [
        "påminnelse",
        "husk å",
        "husk at",
        "reminder",
        "gjøremål",
        "todo",
    ]

    for keyword in reminder_keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", content_lower):
            # Extract reminder text
            text = message_content

            # Remove @inebotten and keyword
            text = text.replace("@inebotten", "").strip()

            # Remove the keyword phrase
            patterns = [
                f"^{keyword}\\s*",
                f"{keyword}\\s*",
            ]
            for pattern in patterns:
                import re

                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

            # Clean up common prefixes
            prefixes = ["å", "at", "om å", "på å", "meg om å", "meg på å"]
            for prefix in prefixes:
                if text.lower().startswith(prefix + " "):
                    text = text[len(prefix) :].strip()

            # Check for due date in text (DD.MM)
            import re

            date_match = re.search(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?", text)
            due_date = None
            if date_match:
                day, month, year = date_match.groups()
                if year:
                    due_date = f"{day}.{month}.{year}"
                else:
                    due_date = f"{day}.{month}"
                # Remove date from text
                text = text[: date_match.start()] + text[date_match.end() :]
                text = text.strip(" -–—")

            if text and len(text) > 2:
                return {"action": "add", "text": text, "due_date": due_date}

    # Check for complete reminder
    complete_keywords = ["ferdig", "fullført", "done", "completed", "gjort", "✓"]
    for keyword in complete_keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", content_lower):
            # Try to extract number
            import re

            num_match = re.search(r"\b(\d+)\b", content_lower)
            if num_match:
                return {"action": "complete", "number": int(num_match.group(1))}
            return {"action": "complete", "number": None}

    # Check for list reminders
    list_keywords = ["påminnelser", "gjøremål", "reminders", "todos", "huskeliste"]
    if any(
        re.search(rf"\b{re.escape(word)}\b", content_lower)
        for word in list_keywords
    ):
        return {"action": "list"}

    return None


if __name__ == "__main__":
    # Test
    print("=== Reminder Manager Test ===\n")

    manager = ReminderManager(storage_path="/tmp/test_reminders.json")

    # Add test reminders
    manager.add_reminder("guild1", "user1", "Ola", "Kjøpe melk", "20.03.2026")
    manager.add_reminder("guild1", "user1", "Ola", "Ringe bestemor")

    print("Active reminders:")
    print(manager.format_reminders_list("guild1"))

    print("\nCompleting reminder #1...")
    success, text = manager.complete_reminder("guild1", reminder_num=1)
    print(f"Completed: {text}")

    print("\nActive reminders after completion:")
    print(manager.format_reminders_list("guild1", show_completed=True))

    # Cleanup
    if manager.storage_path.exists():
        manager.storage_path.unlink()
