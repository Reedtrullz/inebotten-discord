#!/usr/bin/env python3
"""
Reminder Manager for Inebotten
Tracks reminders that can be marked as completed
"""

import asyncio
import copy
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cal_system.reminder_clock import ReminderClock, SystemReminderClock
from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MutationCoordinator, REMINDER_STORE_SCOPE
from utils.json_storage import hermes_discord_data_path, write_json_atomic


OSLO = ZoneInfo("Europe/Oslo")


class ReminderManager:
    """
    Manages reminders that users can mark as completed
    """

    def __init__(
        self,
        storage_path=None,
        *,
        clock: ReminderClock | None = None,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        if storage_path is None:
            storage_path = hermes_discord_data_path("reminders.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.reminders = self._load_reminders()
        self.clock = clock or SystemReminderClock()
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()

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

    def _save_reminders(self, candidate):
        """Persist one detached complete-root candidate or raise."""
        write_json_atomic(self.storage_path, candidate)

    @staticmethod
    def _require_aware(reference_time):
        if (
            not isinstance(reference_time, datetime)
            or reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time_must_be_aware")
        return reference_time.astimezone(OSLO)

    @staticmethod
    def _require_offline_projection():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError("use_async_result_api")

    async def _persist_and_publish(self, candidate):
        """Settle the owned write, then publish or carry exact cancellation truth."""
        writer = asyncio.create_task(
            asyncio.to_thread(self._save_reminders, candidate),
            name="reminder-store-save",
        )
        current = asyncio.current_task()
        outer_cancelled = False

        while True:
            try:
                await asyncio.shield(writer)
                break
            except asyncio.CancelledError as exc:
                if current is not None and current.cancelling() > 0:
                    outer_cancelled = True
                    while current.cancelling() > 0:
                        current.uncancel()
                    continue
                raise ManagerMutationCancelled(
                    "commit_state_unknown",
                    mutated=False,
                    retryable=False,
                    commit_unknown=True,
                ) from exc
            except Exception:
                break

        if writer.cancelled():
            raise ManagerMutationCancelled(
                "commit_state_unknown",
                mutated=False,
                retryable=False,
                commit_unknown=True,
            )

        try:
            writer.result()
        except Exception as exc:
            if outer_cancelled:
                raise ManagerMutationCancelled(
                    "storage_write_failed",
                    mutated=False,
                    retryable=True,
                ) from exc
            raise ManagerMutationError(
                "storage_write_failed",
                mutated=False,
            ) from exc

        self.reminders = candidate
        if outer_cancelled:
            raise ManagerMutationCancelled(
                "cancelled",
                mutated=True,
                retryable=False,
            )

    async def _transaction(self, mutate):
        """Mutate a detached root and make it visible only after persistence."""
        try:
            async with self.mutation_coordinator.hold(REMINDER_STORE_SCOPE):
                candidate = copy.deepcopy(self.reminders)
                result, changed = mutate(candidate)
                if changed:
                    await self._persist_and_publish(candidate)
                return copy.deepcopy(result)
        except (ManagerMutationError, ManagerMutationCancelled):
            raise
        except asyncio.CancelledError as exc:
            raise ManagerMutationCancelled(
                "cancelled",
                mutated=False,
                retryable=True,
            ) from exc

    @staticmethod
    def _active_reminders_in(root, guild_id):
        """Select active rows in the stable order used for display numbering."""
        rows = [
            (position, reminder)
            for position, reminder in enumerate(root.get(str(guild_id), ()))
            if not reminder.get("completed", False)
        ]
        rows.sort(key=lambda row: (str(row[1].get("created_at", "")), row[0]))
        return [reminder for _, reminder in rows]

    async def add_reminder_result(
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
        *,
        reference_time,
    ):
        """Create and durably publish a reminder from one captured instant."""
        now = self._require_aware(reference_time)

        def mutate(candidate):
            guild_key = str(guild_id)
            reminder_id = f"rem_{guild_id}_{uuid.uuid4().hex}"
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
                "channel_id": (
                    str(channel_id) if channel_id is not None else None
                ),
                "created_at": now.isoformat(),
                "completed": False,
                "completed_at": None,
                "completed_by": None,
            }
            candidate.setdefault(guild_key, []).append(reminder)
            return reminder_id, True

        return await self._transaction(mutate)

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
        self._require_offline_projection()
        reference_time = self._require_aware(self.clock.now())
        return asyncio.run(
            self.add_reminder_result(
                guild_id,
                user_id,
                username,
                text,
                due_date,
                recurrence,
                recurrence_day,
                rrule_day,
                gcal_event_id,
                gcal_link,
                channel_id,
                reference_time=reference_time,
            )
        )

    async def complete_reminder_result(
        self,
        guild_id,
        reminder_num=None,
        reminder_id=None,
        *,
        reference_time,
    ):
        """Complete one reminder or advance its legacy recurrence atomically."""
        now = self._require_aware(reference_time)

        def mutate(candidate):
            active = self._active_reminders_in(candidate, guild_id)
            target = None
            if reminder_num is not None:
                index = reminder_num - 1
                if 0 <= index < len(active):
                    target = active[index]
            elif reminder_id:
                target = next(
                    (
                        reminder
                        for reminder in active
                        if reminder.get("id") == reminder_id
                    ),
                    None,
                )

            if target is None:
                return (False, None, None), False

            if target.get("recurrence") and target.get("due_date"):
                next_date = self._calculate_next_date(
                    target["due_date"],
                    target["recurrence"],
                    target.get("recurrence_day"),
                )
                if next_date:
                    target["due_date"] = next_date
                    target["completed_count"] = (
                        target.get("completed_count", 0) + 1
                    )
                    return (True, target["text"], next_date), True

            target["completed"] = True
            target["completed_at"] = now.isoformat()
            return (True, target["text"], None), True

        return await self._transaction(mutate)

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
        self._require_offline_projection()
        reference_time = self._require_aware(self.clock.now())
        return asyncio.run(
            self.complete_reminder_result(
                guild_id,
                reminder_num=reminder_num,
                reminder_id=reminder_id,
                reference_time=reference_time,
            )
        )

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
        return self._active_reminders_in(self.reminders, guild_id)

    def snapshot_pending_items(self, scope_id):
        """Return detached active reminders in display/target order."""
        return tuple(
            copy.deepcopy(
                self._active_reminders_in(self.reminders, scope_id)
            )
        )

    def get_completed_reminders(
        self,
        guild_id,
        days=7,
        *,
        reference_time=None,
    ):
        """
        Get recently completed reminders
        """
        guild_key = str(guild_id)

        if guild_key not in self.reminders:
            return []

        if reference_time is None:
            reference_time = self.clock.now()
        cutoff = self._require_aware(reference_time) - timedelta(days=days)

        completed = []
        for r in self.reminders[guild_key]:
            if r["completed"] and r.get("completed_at"):
                completed_at = datetime.fromisoformat(r["completed_at"])
                if completed_at.tzinfo is None or completed_at.utcoffset() is None:
                    completed_at = completed_at.replace(tzinfo=OSLO)
                if completed_at >= cutoff:
                    completed.append(r)

        return completed

    def format_reminders_list(
        self,
        guild_id,
        show_completed=False,
        *,
        reference_time=None,
    ):
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
            completed = self.get_completed_reminders(
                guild_id,
                days=3,
                reference_time=reference_time,
            )
            if completed:
                lines.append("\n✅ **Fullført nylig:**")
                for r in completed[:5]:
                    lines.append(f"✓ ~~{r['text']}~~")

        return "\n".join(lines) if lines else None

    async def delete_old_completed_result(
        self,
        guild_id,
        days=7,
        *,
        reference_time,
    ):
        """Prune old completions through the same complete-root transaction."""
        now = self._require_aware(reference_time)
        cutoff = now - timedelta(days=days)

        def mutate(candidate):
            guild_key = str(guild_id)
            existing = candidate.get(guild_key)
            if existing is None:
                return 0, False

            retained = []
            for reminder in existing:
                completed_at_raw = reminder.get("completed_at")
                keep = not reminder.get("completed") or not completed_at_raw
                if not keep:
                    try:
                        completed_at = datetime.fromisoformat(completed_at_raw)
                        if completed_at.tzinfo is None:
                            completed_at = completed_at.replace(tzinfo=OSLO)
                        keep = completed_at >= cutoff.astimezone(
                            completed_at.tzinfo
                        )
                    except (TypeError, ValueError):
                        keep = False
                if keep:
                    retained.append(reminder)

            removed = len(existing) - len(retained)
            if not removed:
                return 0, False
            candidate[guild_key] = retained
            return removed, True

        return await self._transaction(mutate)

    def delete_old_completed(self, guild_id, days=7):
        """Offline compatibility projection for old-reminder pruning."""
        self._require_offline_projection()
        reference_time = self._require_aware(self.clock.now())
        asyncio.run(
            self.delete_old_completed_result(
                guild_id,
                days,
                reference_time=reference_time,
            )
        )

    async def edit_reminder_result(
        self,
        guild_id,
        index=None,
        title=None,
        date=None,
        time=None,
        recurrence=None,
        *,
        reminder_id=None,
        reference_time,
    ):
        """Edit a numbered or stable-ID reminder on a detached candidate."""
        self._require_aware(reference_time)

        def mutate(candidate):
            active = self._active_reminders_in(candidate, guild_id)
            target = None
            if reminder_id is not None:
                target = next(
                    (
                        reminder
                        for reminder in active
                        if reminder.get("id") == reminder_id
                    ),
                    None,
                )
            elif index is not None:
                position = index - 1
                if 0 <= position < len(active):
                    target = active[position]

            if target is None:
                if not candidate.get(str(guild_id)):
                    raise ValueError(
                        "Ingen påminnelser funnet for denne serveren."
                    )
                selector = reminder_id if reminder_id is not None else index
                raise ValueError(f"Ugyldig påminnelse-nummer: {selector}")

            if title is not None:
                target["text"] = title
            if date is not None:
                target["due_date"] = date
            # Separate reminder time storage arrives in Task 5. Preserve the
            # historical no-op projection until that schema lands.
            _ = time
            if recurrence is not None:
                target["recurrence"] = recurrence
            return target, True

        return await self._transaction(mutate)

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
        self._require_offline_projection()
        reference_time = self._require_aware(self.clock.now())
        return asyncio.run(
            self.edit_reminder_result(
                guild_id,
                index,
                title,
                date,
                time,
                recurrence,
                reference_time=reference_time,
            )
        )

    async def _delete_reminder_record_result(
        self,
        guild_id,
        *,
        index=None,
        reminder_id=None,
        reference_time,
    ):
        """Return the deleted record for the legacy index projection."""
        self._require_aware(reference_time)

        def mutate(candidate):
            active = self._active_reminders_in(candidate, guild_id)
            target = None
            if reminder_id is not None:
                target = next(
                    (
                        reminder
                        for reminder in active
                        if reminder.get("id") == reminder_id
                    ),
                    None,
                )
            elif index is not None:
                position = index - 1
                if 0 <= position < len(active):
                    target = active[position]

            if target is None:
                if not candidate.get(str(guild_id)):
                    raise ValueError(
                        "Ingen påminnelser funnet for denne serveren."
                    )
                selector = reminder_id if reminder_id is not None else index
                raise ValueError(f"Ugyldig påminnelse-nummer: {selector}")

            candidate[str(guild_id)].remove(target)
            return target, True

        return await self._transaction(mutate)

    async def delete_reminder_result(
        self,
        guild_id,
        reminder_id,
        *,
        reference_time,
    ):
        """Delete an active reminder by exact stable ID."""
        self._require_aware(reference_time)
        try:
            await self._delete_reminder_record_result(
                guild_id,
                reminder_id=reminder_id,
                reference_time=reference_time,
            )
        except ValueError:
            return False
        return True

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
        self._require_offline_projection()
        reference_time = self._require_aware(self.clock.now())
        return asyncio.run(
            self._delete_reminder_record_result(
                guild_id,
                index=index,
                reference_time=reference_time,
            )
        )

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


_REMINDER_NOUN = (
    r"(?:påminnelse|påminnelsen|påminning|påminninga|reminder)"
)
_POLITE_PREFIX = (
    r"(?:(?:kan|kunne|vil|can|could|would|will)\s+(?:du|you)\s+|"
    r"(?:vennligst|please)\s+)?"
)
_REMINDER_QUOTE = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|«[^»\n]*»|(?<!\w)\'[^\'\n]+\'(?!\w)'
)
_REMINDER_EDIT_FIELD = re.compile(
    r"(?<!\w)(tekst|text|dato|date|tid|time|kl|"
    r"gjentakelse|gjentaking|recurrence)\s*:\s*",
    re.I,
)
_REMINDER_ANY_LABEL = re.compile(r"(?<!\w)([^\W\d_][^\W_]*)\s*:\s*", re.I)
_REMINDER_RECURRENCE = {
    "hver dag": "daily",
    "kvar dag": "daily",
    "daglig": "daily",
    "daily": "daily",
    "hver uke": "weekly",
    "kvar veke": "weekly",
    "ukentlig": "weekly",
    "weekly": "weekly",
    "annenhver uke": "biweekly",
    "hver andre uke": "biweekly",
    "kvar andre veke": "biweekly",
    "biweekly": "biweekly",
    "hver måned": "monthly",
    "kvar månad": "monthly",
    "månedlig": "monthly",
    "monthly": "monthly",
    "hvert år": "yearly",
    "kvart år": "yearly",
    "årlig": "yearly",
    "yearly": "yearly",
}


def _strip_reminder_temporal_data(text, resolver, now):
    """Strip resolver-owned evidence outside supported quoted title data."""
    def preserve_boundary_spacing(raw_part, cleaned_part):
        if not cleaned_part:
            return cleaned_part
        if raw_part[:1].isspace() and not cleaned_part[:1].isspace():
            cleaned_part = f" {cleaned_part}"
        if raw_part[-1:].isspace() and not cleaned_part[-1:].isspace():
            cleaned_part = f"{cleaned_part} "
        return cleaned_part

    parts = []
    cursor = 0
    stripped_temporal = False
    for match in _REMINDER_QUOTE.finditer(text):
        raw_part = text[cursor : match.start()]
        cleaned_part = resolver.strip_temporal_evidence(
            raw_part,
            reference=now,
        )
        stripped_temporal = stripped_temporal or cleaned_part != raw_part
        parts.append(preserve_boundary_spacing(raw_part, cleaned_part))
        parts.append(match.group(0))
        cursor = match.end()
    raw_part = text[cursor:]
    cleaned_part = resolver.strip_temporal_evidence(raw_part, reference=now)
    stripped_temporal = stripped_temporal or cleaned_part != raw_part
    parts.append(preserve_boundary_spacing(raw_part, cleaned_part))
    cleaned = "".join(parts).strip()
    if stripped_temporal:
        # The shared resolver owns temporal grammar and its own cue cleanup.
        # This only removes conjunctions stranded by removing a later/earlier
        # temporal span (for example, ``ring legen fredag og kl 14``).
        connector = r"(?:og|and|på|til|den|at|kl\.?|rundt|about|om|in)"
        cleaned = re.sub(
            rf"^(?:{connector}\b[\s,;:-]*)+",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(
            rf"(?:[\s,;:-]*{connector}\b)+$",
            "",
            cleaned,
            flags=re.I,
        )
    return cleaned.strip()


def _mask_reminder_quotes(text):
    """Mask supported quote spans without changing string offsets."""
    chars = list(text)
    for match in _REMINDER_QUOTE.finditer(text):
        for index in range(match.start(), match.end()):
            if not chars[index].isspace():
                # A non-whitespace, non-word sentinel keeps ``\s*`` field
                # delimiters from consuming the whole masked quoted value.
                chars[index] = "\ufffc"
    return "".join(chars)


def _collapse_reminder_unquoted_whitespace(text):
    """Collapse spacing introduced by removals while preserving quote data."""
    parts = []
    cursor = 0
    for match in _REMINDER_QUOTE.finditer(text):
        parts.append(re.sub(r"\s+", " ", text[cursor : match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(re.sub(r"\s+", " ", text[cursor:]))
    return "".join(parts).strip()


def _canonical_recurrence(value):
    folded = " ".join(value.casefold().split())
    if folded in _REMINDER_RECURRENCE.values():
        return folded
    return _REMINDER_RECURRENCE.get(folded)


def _extract_recurrence(text):
    """Extract consistent recurrence evidence only from unquoted text."""
    masked = _mask_reminder_quotes(text)
    matches = []
    occupied = []
    for phrase in sorted(_REMINDER_RECURRENCE, key=len, reverse=True):
        for match in re.finditer(
            rf"(?<!\w){re.escape(phrase)}(?!\w)",
            masked,
            re.I,
        ):
            if any(
                match.start() < end and match.end() > start
                for start, end in occupied
            ):
                continue
            matches.append((match, _REMINDER_RECURRENCE[phrase]))
            occupied.append(match.span())
    if not matches:
        return None, text, False
    recurrences = {value for _, value in matches}
    if len(recurrences) != 1:
        return None, text, True
    chars = list(text)
    for match, _ in matches:
        for index in range(match.start(), match.end()):
            if not chars[index].isspace():
                chars[index] = " "
    cleaned = _collapse_reminder_unquoted_whitespace("".join(chars))
    cleaned = re.sub(r"^(?:(?:og|and)\b[\s,;:-]*)+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:[\s,;:-]*(?:og|and)\b)+$", "", cleaned, flags=re.I)
    return next(iter(recurrences)), cleaned.strip(), False


def _parse_reminder_selector(value):
    value = value.strip().strip("?.!,")
    explicit_id = re.fullmatch(
        r"id\s*[:#]?\s*([a-z0-9][a-z0-9_-]{5,79})",
        value,
        re.I,
    )
    if explicit_id:
        return "reminder_id", explicit_id.group(1)

    value = re.sub(
        r"^(?:nummer|number|nr\.?|no\.?)\s+",
        "",
        value,
        flags=re.I,
    )
    value = value.lstrip("#").strip()
    if value.isdigit() and int(value) > 0:
        return "number", int(value)
    if re.fullmatch(r"rem_[a-z0-9][a-z0-9_-]{3,75}", value, re.I):
        return "reminder_id", value
    return None


def _parse_reminder_edit_fields(body, resolver, now):
    from core.utterance import normalize_utterance

    masked = _mask_reminder_quotes(body)
    matches = list(_REMINDER_EDIT_FIELD.finditer(masked))
    if not matches or masked[: matches[0].start()].strip():
        return None
    supported_colons = {match.end() - 1 for match in matches}
    if any(
        match.end() - 1 not in supported_colons
        for match in _REMINDER_ANY_LABEL.finditer(masked)
    ):
        return None
    values = {}
    aliases = {
        "tekst": "text",
        "text": "text",
        "dato": "date",
        "date": "date",
        "tid": "time",
        "time": "time",
        "kl": "time",
        "gjentakelse": "recurrence",
        "gjentaking": "recurrence",
        "recurrence": "recurrence",
    }
    for index, match in enumerate(matches):
        key = aliases[match.group(1).casefold()]
        if key in values:
            return None
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[match.end() : end].strip(" ,;?.")
        if not value or not value.strip(" \t\r\n\"'“”‘’«»"):
            return None
        values[key] = value

    changes = {}
    if "text" in values:
        changes["text"] = values["text"]
    if "recurrence" in values:
        recurrence = _canonical_recurrence(values["recurrence"])
        if recurrence is None:
            return None
        changes["recurrence"] = recurrence

    date_value = values.get("date")
    time_value = values.get("time")
    if date_value is not None or time_value is not None:
        date_control = (
            normalize_utterance(date_value).control_text
            if date_value is not None
            else None
        )
        time_control = (
            normalize_utterance(time_value).control_text
            if time_value is not None
            else None
        )
        time_expression = time_control
        if time_control is not None:
            direct_time = resolver.resolve(time_control, reference=now)
            if direct_time.errors:
                return None
            if direct_time.time is None:
                time_expression = f"kl {time_control}"
        if date_value is not None and time_value is not None:
            resolved = resolver.resolve(
                f"{date_control} {time_expression}", reference=now
            )
            if resolved.errors or resolved.date is None or resolved.time is None:
                return None
            changes.update(
                due_at=resolved.due_at,
                due_date=resolved.date,
                time=resolved.time,
                timezone="Europe/Oslo",
            )
        elif date_value is not None:
            resolved = resolver.resolve(date_control, reference=now)
            if resolved.errors or resolved.date is None:
                return None
            changes["due_date"] = resolved.date
        else:
            resolved = resolver.resolve(time_expression, reference=now)
            if resolved.errors or resolved.time is None:
                return None
            changes["time"] = resolved.time
    return changes or None


def parse_reminder_command(
    message_content, *, now=None, temporal_resolver=None
):
    """Parse one bounded reminder frame into a complete canonical object."""
    from cal_system.temporal_resolver import TemporalResolver
    from core.utterance import normalize_utterance

    if not isinstance(message_content, str):
        return None
    resolver = temporal_resolver or TemporalResolver()
    cleaned = re.sub(r"<@!?\d+>", "", message_content)
    cleaned = re.sub(r"^\s*@inebotten\b", "", cleaned, flags=re.I).strip()
    control = normalize_utterance(cleaned).control_text.strip()

    # A plain media-title frame belongs to the watchlist parser. Temporal or
    # caretaking/checking forms remain reminders ("se på saken", "watch the
    # kids tomorrow") instead of being swallowed as titles.
    media_frame = re.match(
        r"^(?:husk\s+å\s+se|hugs\s+å\s+sjå|remember\s+to\s+watch)\s+(.+)$",
        cleaned,
        re.I,
    )
    if media_frame:
        media_body = normalize_utterance(
            media_frame.group(1).strip()
        ).control_text
        media_temporal = resolver.resolve(media_body, reference=now)
        reminder_media_shape = bool(
            media_temporal.date
            or media_temporal.time
            or re.match(
                r"^(?:på|om|til)\b|^(?:the\s+)?(?:kids|children)\b",
                media_body,
                re.I,
            )
        )
        if not reminder_media_shape:
            return None

    edit = re.match(
        rf"^{_POLITE_PREFIX}(?:endre|rediger|edit)\s+{_REMINDER_NOUN}\s+"
        r"(\d+|(?:id\s*[:#]?\s*)?[a-z0-9][a-z0-9_-]{5,79})\s+(.+)$",
        cleaned,
        re.I,
    )
    if edit:
        selector = _parse_reminder_selector(edit.group(1))
        changes = _parse_reminder_edit_fields(edit.group(2), resolver, now)
        if selector is None or changes is None:
            return None
        key, value = selector
        return {"action": "edit", key: value, "changes": changes}

    target = re.fullmatch(
        rf"{_POLITE_PREFIX}(?P<verb>slett|fjern|delete|remove|ferdig|fullfør|"
        rf"fullført|done|complete|gjort)\s+(?:the\s+)?{_REMINDER_NOUN}\s+"
        rf"(?P<selector>.+?)\s*[?.!]*",
        cleaned,
        re.I,
    )
    if target:
        selector = _parse_reminder_selector(target.group("selector"))
        if selector is None:
            return None
        key, value = selector
        action = (
            "delete"
            if target.group("verb").casefold()
            in {"slett", "fjern", "delete", "remove"}
            else "complete"
        )
        return {"action": action, key: value}

    search = re.fullmatch(
        r"(?:søk|search)\s+(?:påminnelse|påminnelser|påminning|"
        r"påminningar|reminder|reminders)\s+(.+?)\s*[?.!]*",
        cleaned,
        re.I,
    )
    if search and search.group(1).strip():
        return {"action": "search", "query": search.group(1).strip()}

    if re.fullmatch(
        r"(?:(?:vis|list|show)\s+)?(?:påminnelser|påminningar|reminders|"
        r"gjøremål|todos|huskeliste)\s*[?.!]*",
        cleaned,
        re.I,
    ):
        return {"action": "list"}

    frame = re.match(
        rf"^{_POLITE_PREFIX}(?:påminn(?:e)?\s+meg(?:\s+(?:om|på))?(?:\s+å)?|"
        r"minn(?:e)?\s+(?:meg|mæ)(?:\s+(?:om|på))?(?:\s+å)?|"
        r"husk\s+(?:å|at)|hugs\s+(?:å|at)|"
        r"ikke\s+glem\s+(?:å|at)|ikkje\s+gløym\s+(?:å|at)|"
        r"(?:don't|don’t)\s+forget\s+(?:to|that)|"
        r"remind\s+me(?:\s+(?:to|that))?|"
        r"remember\s+to|"
        r"påminnelse|påminning|reminder|gjøremål|todo)\s+(.+)$",
        cleaned,
        re.I,
    )
    if frame is None:
        return None
    body = frame.group(1).strip()
    if not body:
        return None

    recurrence, body_without_recurrence, recurrence_conflict = _extract_recurrence(body)
    if recurrence_conflict:
        return None
    temporal_control = normalize_utterance(body_without_recurrence).control_text
    resolved = resolver.resolve(temporal_control, reference=now)
    if resolved.errors:
        return None
    if resolved.date is not None and resolved.time is None:
        # Date-only reminder policy is 09:00, included before year selection.
        resolved = resolver.resolve(
            f"{temporal_control} kl 09:00", reference=now
        )
        if resolved.errors:
            return None
    elif recurrence is not None and resolved.date is None:
        resolved = resolver.resolve("kl 09:00", reference=now)
        if resolved.errors:
            return None

    title = _strip_reminder_temporal_data(
        body_without_recurrence, resolver, now
    )
    title = title.strip(" -–—,;:.!?")
    if len(title) < 2:
        return None
    result = {"action": "add", "text": title}
    if resolved.date is not None:
        result["due_date"] = resolved.date
    if resolved.time is not None:
        result["time"] = resolved.time
    if resolved.due_at is not None:
        result["due_at"] = resolved.due_at
    if resolved.date is not None or resolved.time is not None:
        result["timezone"] = "Europe/Oslo"
    if recurrence is not None:
        result["recurrence"] = recurrence
    return result


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
