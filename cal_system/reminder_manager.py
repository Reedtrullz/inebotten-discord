#!/usr/bin/env python3
"""
Reminder Manager for Inebotten
Tracks reminders that can be marked as completed
"""

import re
import uuid
import copy
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from utils.json_storage import hermes_discord_data_path, write_json_atomic
from utils.storage_contract import DocumentOwner, StorageMutationError, bucket_records, writable_store, store_worker
from cal_system.event_schema import Clock, EventTime
from cal_system.sync_outbox import SyncOwnerMixin, SyncOutbox, enqueue, SyncOperation, remote_completion
from core.access_policy import AccessPolicy
from cal_system.mutation_preview import actor_key


class ReminderManager(SyncOwnerMixin):
    """
    Manages reminders that users can mark as completed
    """

    def __init__(self, storage_path=None, *, gcal_manager=None, clock=None, access_policy=None):
        if storage_path is None:
            storage_path = hermes_discord_data_path("reminders.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or Clock()
        self.access_policy = access_policy or AccessPolicy()
        self.gcal = gcal_manager
        self.gcal_enabled = gcal_manager is not None
        self._storage = DocumentOwner(self.storage_path, self._validate_document)
        self.reminders = self._storage.rollback()
        self._outbox = SyncOutbox(self)
        self._sync_conflicts = OrderedDict()

    @staticmethod
    def _validate_document(document):
        if not bucket_records('text', require_ids=True)(document):
            return False
        try:
            for items in document.values():
                for item in items:
                    operations = item.get('sync_operations', [])
                    if not isinstance(operations, list) or len(operations) > 8:
                        return False
                    for raw in operations:
                        if SyncOperation.from_document(raw).item_id != item['id']:
                            return False
        except (TypeError, ValueError, AttributeError, KeyError):
            return False
        return True

    @property
    def items(self):
        return self.reminders

    @items.setter
    def items(self, value):
        self.reminders = value

    def configure_google(self, provider, *, slot=None, access_policy=None):
        self.gcal, self.gcal_enabled = provider, provider is not None
        if slot is not None:
            self._outbox.slot = slot
        if access_policy is not None:
            self.access_policy = access_policy

    def _authorize_mutation(self, actor, scope):
        actor_key(actor)
        key = scope if scope in self.access_policy.scopes or scope.startswith(('private:', 'group:')) else 'shared'
        if not self.access_policy.authorize(actor, key, 'write').allowed:
            raise PermissionError('scope_membership_required')

    def sync_payload(self, item):
        # Legacy linked reminders patch only their text/completion. A deadline
        # task is never turned into a newly created timed Google event.
        return {'summary': item['text'] + (' [FERDIG]' if item.get('completed') else ''),
                'extendedProperties': {'private': {'inebotten_completed': 'true' if item.get('completed') else 'false'}}}

    def apply_remote_sync_fields(self, item, remote):
        item['text'], item['completed'] = remote_completion(remote)
        if remote.get('start'):
            item['due_date'] = EventTime.from_google(remote).local_date.strftime('%d.%m.%Y')

    def _queue_sync(self, item, kind, scope):
        if item.get('gcal_event_id'):
            enqueue(item, kind, scope, payload={} if kind == 'delete' else self.sync_payload(item))

    async def process_due(self, *, deadline):
        return await self._outbox.process_due(deadline=deadline)

    async def _save_data(self):
        result = await store_worker(self._storage.commit, copy.deepcopy(self.reminders), writer=write_json_atomic)
        if not result.ok:
            self.reminders = self._storage.rollback()
            raise StorageMutationError(result.error_code)

    @property
    def reminders(self):
        return self._storage.data

    @reminders.setter
    def reminders(self, value):
        self._storage.data = value

    @property
    def storage_state(self):
        return self._storage.state

    def _load_reminders(self):
        return self._storage.load()

    def _save_reminders(self):
        result = self._storage.commit(self.reminders, writer=write_json_atomic)
        if not result.ok:
            self.reminders = self._storage.rollback()
            raise StorageMutationError(result.error_code)

    @writable_store
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
        reminder_id = f"rem_{guild_id}_{uuid.uuid4().hex}"

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

    @writable_store
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

        incomplete = self.get_active_reminders(guild_id)

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
                # Legacy reminders have no explicit event duration; advancing a
                # local deadline must not invent a remote timed event.
                if target_reminder.get('gcal_event_id'):
                    target_reminder['sync_blocked'] = 'explicit_event_time_required'
                    raw = enqueue(target_reminder, 'update', guild_key, payload=self.sync_payload(target_reminder))
                    raw.update(state='failed', reason_code='explicit_event_time_required')
                self._save_reminders()
                return True, target_reminder["text"], next_date

        # Non-recurring reminder - mark as completed
        target_reminder["completed"] = True
        target_reminder["completed_at"] = datetime.now().isoformat()
        self._queue_sync(target_reminder, 'update', guild_key)
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

    @writable_store
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

    @writable_store
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
            if r["completed"] and r.get("completed_at") and not r.get('_mutation_deleted'):
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

    @writable_store
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

    @writable_store
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
        self._queue_sync(target, 'update', guild_key)
        if target.get('gcal_event_id') and (date is not None or recurrence is not None):
            target['sync_blocked'] = 'explicit_event_time_required'
            target['sync_operations'][-1].update(state='failed', reason_code='explicit_event_time_required')
        self._save_reminders()
        return target

    @writable_store
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
        if target.get('gcal_event_id'):
            self._queue_sync(target, 'delete', guild_key)
            target['completed'] = True
            target['delete_pending'] = True
            target['_mutation_deleted'] = True
        else:
            self.reminders[guild_key].remove(target)
        self._save_reminders()
        return target

    @writable_store
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

    def format_search_results(self, guild_id, query, lang="no"):
        """Format reminder search results for Discord."""
        matches = self.search_reminders(guild_id, query)
        if not matches:
            return (
                f"🔎 Fant ingen påminnelser som matcher **{query}**."
                if lang == "no"
                else f"🔎 No reminders matched **{query}**."
            )

        header = (
            f"🔎 **Påminnelser som matcher \"{query}\":**"
            if lang == "no"
            else f"🔎 **Reminders matching \"{query}\":**"
        )
        lines = [header]
        for i, reminder in enumerate(matches[:10], 1):
            status = "✅" if reminder.get("completed") else "⬜"
            due = f" (frist: {reminder['due_date']})" if reminder.get("due_date") else ""
            lines.append(f"{status} **{i}.** {reminder.get('text', '')}{due}")

        if len(matches) > 10:
            more = len(matches) - 10
            lines.append(f"\n… og {more} til." if lang == "no" else f"\n… and {more} more.")

        return "\n".join(lines)


def parse_reminder_command(message_content):
    """
    Parse reminder commands

    Returns:
        dict with action and data, or None
    """
    cleaned_content = re.sub(r"<@!?\d+>", "", message_content)
    cleaned_content = cleaned_content.replace("@inebotten", "").strip()
    content_lower = cleaned_content.lower()

    # Check for explicit complete reminder commands before creation, so
    # "ferdig påminnelse 1" does not become a new reminder titled "ferdig 1".
    complete_keywords = ["ferdig", "fullfør", "fullført", "done", "completed", "gjort", "✓"]
    complete_pattern = "|".join(re.escape(keyword) for keyword in complete_keywords)
    reminder_context = r"(?:påminnelse|påminnelser|reminder|reminders|gjøremål|todo)"
    complete_match = re.fullmatch(
        rf"\s*(?:{complete_pattern})\s+{reminder_context}(?:\s+(\d+))?\s*",
        content_lower,
        flags=re.IGNORECASE,
    )
    if complete_match:
        number = complete_match.group(1)
        return {"action": "complete", "number": int(number) if number else None}

    # Check for list reminders before singular creation.
    list_keywords = ["påminnelser", "gjøremål", "reminders", "todos", "huskeliste"]
    if any(
        re.search(rf"\b{re.escape(word)}\b", content_lower)
        for word in list_keywords
    ):
        return {"action": "list"}

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
            text = cleaned_content

            # Remove the keyword phrase
            patterns = [
                f"^{keyword}\\s*",
                f"{keyword}\\s*",
            ]
            for pattern in patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

            # Clean up common prefixes
            prefixes = ["å", "at", "om å", "på å", "meg om å", "meg på å"]
            for prefix in prefixes:
                if text.lower().startswith(prefix + " "):
                    text = text[len(prefix) :].strip()

            # Check for due date in text (DD.MM)
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

    return None


if __name__ == "__main__":
    # Test
    print("=== Reminder Manager Test ===\n")

    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as tmp:
        storage_path = tmp.name
    manager = ReminderManager(storage_path=storage_path)

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
    manager.storage_path.unlink(missing_ok=True)
