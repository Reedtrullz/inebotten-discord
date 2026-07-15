#!/usr/bin/env python3
"""
Poll Manager for Inebotten
Simple, conversational polls for quick decisions
"""

import asyncio
import copy
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import random
from zoneinfo import ZoneInfo

from cal_system.reminder_clock import ReminderClock, SystemReminderClock
from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MutationCoordinator, POLL_STORE_SCOPE
from utils.json_storage import hermes_discord_data_path, write_json_atomic


OSLO = ZoneInfo("Europe/Oslo")


class PollManager:
    """
    Manages quick polls for group decisions
    """

    def __init__(
        self,
        storage_path=None,
        *,
        clock: ReminderClock | None = None,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        if storage_path is None:
            storage_path = hermes_discord_data_path("polls.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.polls = self._load_polls()
        self.clock = clock or SystemReminderClock()
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()
        self.emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    def _load_polls(self):
        """Load polls from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[FEATURES] Poll load error: {e}")
                return {}
        return {}

    def _save_polls(self, candidate):
        """Persist a detached complete-root candidate."""
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

    async def _commit_candidate(self, candidate):
        """Settle one owned atomic write, publish once, and retain cancellation truth."""
        writer = asyncio.create_task(asyncio.to_thread(self._save_polls, candidate))
        current = asyncio.current_task()
        outer_cancelled = False
        while True:
            try:
                await asyncio.shield(writer)
                break
            except asyncio.CancelledError:
                cancellation_requests = current.cancelling() if current else 0
                if cancellation_requests:
                    outer_cancelled = True
                    for _ in range(cancellation_requests):
                        current.uncancel()
                    continue
                raise ManagerMutationCancelled(
                    "commit_state_unknown",
                    mutated=False,
                    retryable=False,
                    commit_unknown=True,
                )
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

        self.polls = candidate
        if outer_cancelled:
            raise ManagerMutationCancelled(
                "cancelled",
                mutated=True,
                retryable=False,
            )

    async def create_poll_result(
        self,
        guild_id,
        question,
        options,
        created_by,
        created_by_id=None,
        *,
        reference_time,
    ):
        """Create and durably publish a poll from one captured aware instant."""
        now = self._require_aware(reference_time)
        async with self.mutation_coordinator.hold(POLL_STORE_SCOPE):
            candidate = copy.deepcopy(self.polls)
            poll_id = f"poll_{guild_id}_{uuid.uuid4().hex}"
            poll = {
                "id": poll_id,
                "guild_id": str(guild_id),
                "question": question,
                "options": [
                    {"text": opt, "votes": [], "emoji": self.emojis[i]}
                    for i, opt in enumerate(options[:10])
                ],
                "created_by": created_by,
                "created_by_id": created_by_id,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(days=7)).isoformat(),
                "status": "active",
            }
            candidate.setdefault(str(guild_id), {})[poll_id] = poll
            await self._commit_candidate(candidate)
            return poll

    def create_poll(self, guild_id, question, options, created_by, created_by_id=None):
        """
        Create a new poll

        Args:
            guild_id: Discord guild/channel ID
            question: The poll question
            options: List of option strings
            created_by: Username who created it
            created_by_id: User ID who created it (optional, for ownership)

        Returns:
            poll_id
        """
        self._require_offline_projection()
        reference_time = self._require_aware(self.clock.now())
        return asyncio.run(
            self.create_poll_result(
                guild_id,
                question,
                options,
                created_by,
                created_by_id,
                reference_time=reference_time,
            )
        )

    def get_poll(self, guild_id, poll_id):
        """Get a poll by guild and poll ID. Returns dict or None."""
        guild_key = str(guild_id)
        if guild_key in self.polls and poll_id in self.polls[guild_key]:
            return self.polls[guild_key][poll_id]
        return None

    def is_poll_owner(self, poll, user_id, username=None):
        """
        Check if a user owns a poll.

        For polls created after this update, checks created_by_id.
        For legacy polls without created_by_id, falls back to created_by name.
        """
        if "created_by_id" in poll and poll["created_by_id"] is not None:
            return str(poll["created_by_id"]) == str(user_id)
        if username is not None:
            return poll.get("created_by") == username
        return False

    async def edit_poll_result(
        self,
        guild_id,
        poll_id,
        user_id,
        username=None,
        question=None,
        options=None,
    ):
        async with self.mutation_coordinator.hold(POLL_STORE_SCOPE):
            candidate = copy.deepcopy(self.polls)
            guild_key = str(guild_id)
            poll = candidate.get(guild_key, {}).get(poll_id)
            if not poll:
                return False, "Poll not found"
            if poll["status"] != "active":
                return False, "Poll is closed"
            if not self.is_poll_owner(poll, user_id, username):
                return False, "You are not the owner of this poll"
            if question is not None:
                poll["question"] = question
            if options is not None:
                poll["options"] = [
                    {"text": opt, "votes": [], "emoji": self.emojis[i]}
                    for i, opt in enumerate(options[:10])
                ]
            await self._commit_candidate(candidate)
            return True, poll

    def edit_poll(self, guild_id, poll_id, user_id, username=None, question=None, options=None):
        """
        Edit an existing active poll.

        Returns:
            (True, poll) or (False, error_message)
        """
        self._require_offline_projection()
        return asyncio.run(
            self.edit_poll_result(
                guild_id,
                poll_id,
                user_id,
                username,
                question,
                options,
            )
        )

    async def delete_poll_result(self, guild_id, poll_id, user_id, username=None):
        async with self.mutation_coordinator.hold(POLL_STORE_SCOPE):
            candidate = copy.deepcopy(self.polls)
            guild_key = str(guild_id)
            poll = candidate.get(guild_key, {}).get(poll_id)
            if not poll:
                return False, "Poll not found"
            if not self.is_poll_owner(poll, user_id, username):
                return False, "You are not the owner of this poll"
            del candidate[guild_key][poll_id]
            await self._commit_candidate(candidate)
            return True, "Poll deleted"

    def delete_poll(self, guild_id, poll_id, user_id, username=None):
        """
        Delete a poll.

        Returns:
            (True, "Poll deleted") or (False, error_message)
        """
        self._require_offline_projection()
        return asyncio.run(
            self.delete_poll_result(guild_id, poll_id, user_id, username)
        )

    async def vote_result(self, guild_id, poll_id, option_num, user_id, username):
        async with self.mutation_coordinator.hold(POLL_STORE_SCOPE):
            candidate = copy.deepcopy(self.polls)
            guild_key = str(guild_id)
            poll = candidate.get(guild_key, {}).get(poll_id)
            if not poll:
                return False, "Poll not found"
            if poll["status"] != "active":
                return False, "Poll is closed"
            option_idx = option_num - 1
            if option_idx < 0 or option_idx >= len(poll["options"]):
                return False, "Invalid option"
            for option in poll["options"]:
                if str(user_id) in option["votes"]:
                    option["votes"].remove(str(user_id))
            poll["options"][option_idx]["votes"].append(str(user_id))
            await self._commit_candidate(candidate)
            return True, "Vote recorded"

    def vote(self, guild_id, poll_id, option_num, user_id, username):
        """
        Cast a vote

        Args:
            option_num: 1-indexed option number
        """
        self._require_offline_projection()
        return asyncio.run(
            self.vote_result(guild_id, poll_id, option_num, user_id, username)
        )

    @classmethod
    def _select_active_polls(cls, polls, guild_id, *, reference_time):
        now = cls._require_aware(reference_time)
        active = []
        for poll_id, poll in polls.get(str(guild_id), {}).items():
            if poll.get("status") != "active":
                continue
            expires = datetime.fromisoformat(poll["expires_at"])
            if expires.tzinfo is None or expires.utcoffset() is None:
                expires = expires.replace(tzinfo=OSLO)
            if expires > now.astimezone(expires.tzinfo):
                active.append((poll_id, poll))
        return active

    def get_active_polls(self, guild_id, *, reference_time=None):
        """Get active polls for a guild at one explicit point in time."""
        guild_key = str(guild_id)

        if reference_time is None:
            reference_time = self._require_aware(self.clock.now())
        return [
            poll
            for _, poll in self._select_active_polls(
                self.polls,
                guild_key,
                reference_time=reference_time,
            )
        ]

    def snapshot_pending_items(self, scope_id, *, reference_time):
        """Return detached active polls in the same order users see."""
        rows = []
        for poll_id, poll in self._select_active_polls(
            self.polls,
            scope_id,
            reference_time=reference_time,
        ):
            if not isinstance(poll_id, str) or not poll_id.strip():
                raise ValueError("invalid_target_state")
            if not isinstance(poll.get("question"), str) or not poll["question"].strip():
                raise ValueError("invalid_target_state")
            if not isinstance(poll.get("options"), list):
                raise ValueError("invalid_target_state")
            row = copy.deepcopy(poll)
            row["poll_id"] = poll_id
            rows.append(row)
        return tuple(rows)

    def format_poll(self, poll, lang="no"):
        """Format poll for display in specified language"""
        lines = [f"📊 **{poll['question']}**", ""]

        total_votes = sum(len(opt["votes"]) for opt in poll["options"])
        vote_label = "stemmer" if lang == "no" else "votes"
        total_label = "Totalt" if lang == "no" else "Total"
        vote_hint = "Stem med tall" if lang == "no" else "Vote with numbers"

        for i, option in enumerate(poll["options"], 1):
            votes = len(option["votes"])
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0
            bar_length = int(percentage / 10)
            bar = "█" * bar_length + "░" * (10 - bar_length)

            lines.append(f"{option['emoji']} {option['text']}")
            lines.append(f"   {bar} {votes} {vote_label} ({percentage:.0f}%)")
            lines.append("")

        lines.append(f"{total_label}: {total_votes} {vote_label}")
        lines.append(f"💡 {vote_hint} (1-{len(poll['options'])})")

        return "\n".join(lines)

    async def close_poll_result(
        self,
        guild_id,
        poll_id,
        user_id=None,
        username=None,
    ):
        async with self.mutation_coordinator.hold(POLL_STORE_SCOPE):
            candidate = copy.deepcopy(self.polls)
            guild_key = str(guild_id)
            poll = candidate.get(guild_key, {}).get(poll_id)
            if not poll:
                return False, "Poll not found"
            if user_id is not None and not self.is_poll_owner(
                poll, user_id, username
            ):
                return False, "You are not the owner of this poll"
            if poll["status"] == "closed":
                return False, "Poll is already closed"
            poll["status"] = "closed"
            await self._commit_candidate(candidate)
            return True, poll

    def close_poll(self, guild_id, poll_id, user_id=None, username=None):
        """
        Close a poll. If user_id is provided, checks ownership.

        Returns:
            (True, poll) or (False, error_message)
        """
        self._require_offline_projection()
        return asyncio.run(
            self.close_poll_result(guild_id, poll_id, user_id, username)
        )


def parse_poll_command(message_content):
    """
    Parse poll creation command (Norwegian and English)

    Examples:
    - "@inebotten avstemning Pizza eller burgere i kveld?"
    - "@inebotten poll Pizza or burgers tonight?"
    - "@inebotten stemme Favorittfarge: rød/blå/grønn/gul"
    """
    content_lower = message_content.lower()

    # Remove @inebotten
    content = re.sub(r"@inebotten\s*", "", message_content, flags=re.IGNORECASE).strip()

    # Detect language
    lang_keywords = ["avstemning", "stemme", "eller"]
    lang = (
        "no"
        if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in lang_keywords)
        else "en"
    )

    # Check for poll keywords - must be more specific to avoid false positives
    poll_triggers = ["avstemning", "poll", "lag poll", "create poll", "ny poll"]
    is_explicit = any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in poll_triggers)
    
    # Also allow if it has multiple options separated by /
    slash_parts = content.split("/")
    has_options = False
    if len(slash_parts) >= 2:
        if is_explicit:
            has_options = True
        else:
            # Implicit: require at least 3 parts (2 slashes) OR spaces around the single slash
            has_spaces = " / " in content or content.endswith(" /") or content.startswith("/ ")
            has_options = len(slash_parts) >= 3 or has_spaces
    
    if not (is_explicit or has_options):
        return None

    # Use the full list for keyword removal
    poll_keywords = ["avstemning", "poll", "stemme", "vote", "avstemnning", "voting"]

    # Remove poll keyword
    for keyword in poll_keywords:
        content = re.sub(f"^{keyword}\\s*", "", content, flags=re.IGNORECASE)

    # Look for options separated by / or eller/or
    # Try slash separator
    if "/" in content:
        parts = content.split("/")
        if len(parts) >= 2:
            question = parts[0].strip()
            options = [p.strip() for p in parts[1:]]
            return {"question": question, "options": options, "lang": lang}

    # Try "eller" or "or" separator
    # Pattern: "question? option1 eller/or option2"
    eller_pattern = r"(.+?)\?\s*(.+?)(?:\s+(?:eller|or)\s+(.+))+"
    match = re.search(eller_pattern, content, re.IGNORECASE)
    if match:
        question = match.group(1).strip() + "?"
        # Split remaining by "eller" or "or"
        rest = content.split("?", 1)[1]
        options = [
            opt.strip()
            for opt in re.split(r"\s+(?:eller|or)\s+", rest, flags=re.IGNORECASE)
            if opt.strip()
        ]
        if len(options) >= 2:
            return {"question": question, "options": options, "lang": lang}

    # Simple yes/no if no options found
    if "?" in content:
        yes_no = ["Ja", "Nei"] if lang == "no" else ["Yes", "No"]
        return {"question": content.strip(), "options": yes_no, "lang": lang}

    return None


def parse_vote(message_content):
    """
    Parse a vote

    Returns option number (1-indexed) or None
    """
    content = message_content.lower()

    # Remove @inebotten
    content = re.sub(r"@inebotten\s*", "", content).strip()

    # Check if it's just a number
    if content.isdigit():
        num = int(content)
        if 1 <= num <= 10:
            return num

    return None


# Quick test
if __name__ == "__main__":
    print("=== Poll Manager Test ===\n")

    # Test parsing
    tests = [
        "@inebotten avstemning Pizza eller burgere i kveld?",
        "@inebotten poll Skal vi møtes lørdag/søndag/mandag?",
        "@inebotten Hva synes dere om planen?",
    ]

    for test in tests:
        result = parse_poll_command(test)
        print(f"'{test}'")
        print(f"  → {result}\n")
