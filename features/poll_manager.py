#!/usr/bin/env python3
"""
Poll Manager for Inebotten
Simple, conversational polls for quick decisions
"""

import copy
import time
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

from utils.json_storage import hermes_discord_data_path, write_json_atomic
from utils.storage_contract import DocumentOwner, writable_store


def validate_poll_document(document):
    try:
        for bucket in document.values():
            if not isinstance(bucket, dict):
                return False
            for poll_id, poll in bucket.items():
                if (not isinstance(poll, dict) or poll.get('id') != poll_id
                        or not isinstance(poll.get('question'), str)
                        or poll.get('status') not in ('active', 'closed')
                        or type(poll.get('revision', 0)) is not int or poll.get('revision', 0) < 0
                        or not isinstance(poll.get('options'), list) or not 1 <= len(poll['options']) <= 10):
                    return False
                datetime.fromisoformat(poll['expires_at'])
                if any(not isinstance(option, dict) or not isinstance(option.get('text'), str)
                       or not isinstance(option.get('votes'), list)
                       or any(not isinstance(voter, str) for voter in option['votes'])
                       for option in poll['options']):
                    return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


class PollStorageError(RuntimeError):
    """A poll could not be durably written to its configured store."""


class PollManager:
    """
    Manages quick polls for group decisions
    """

    def __init__(self, storage_path=None, *, monotonic=None):
        self._monotonic = monotonic or time.monotonic
        if storage_path is None:
            storage_path = hermes_discord_data_path("polls.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage = DocumentOwner(self.storage_path, validate_poll_document, schema_version=3, upgrade_from=(1,))
        self.polls = self._storage.rollback()
        self.emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        self._edit_previews = {}
        self.planning_authorizer = None
        self._upgrade_legacy_records()

    @property
    def polls(self):
        return self._storage.data

    @polls.setter
    def polls(self, value):
        self._storage.data = value

    def close_storage(self):
        self._storage.close()

    def _load_polls(self):
        return self._storage.load()

    def _save_polls(self):
        result = self._storage.commit(self.polls, writer=write_json_atomic)
        if not result.ok:
            raise PollStorageError('Poll could not be saved')

    def _prune_previews(self):
        now = self._monotonic()
        self._edit_previews = {token: preview for token, preview in self._edit_previews.items()
                               if preview['expires_at'] > now}
        while len(self._edit_previews) > 128:
            self._edit_previews.pop(next(iter(self._edit_previews)))

    def _upgrade_legacy_records(self):
        """Add stable IDs and revisions to records from old versions."""
        records = self.polls
        for guild_polls in records.values():
            for poll_id, poll in guild_polls.items():
                poll.setdefault("revision", 0)
                for index, option in enumerate(poll.get("options", [])):
                    option.setdefault(
                        "id",
                        uuid.uuid5(
                            uuid.NAMESPACE_URL, f"{poll_id}:option:{index}"
                        ).hex,
                    )

        self.polls = records

    @staticmethod
    def _is_expired(poll):
        expires = datetime.fromisoformat(poll["expires_at"])
        now = (
            datetime.now(expires.tzinfo)
            if expires.tzinfo
            else datetime.now()
        )
        return now >= expires

    def _persist_or_restore(self, guild_key, poll_id, previous):
        try:
            self._save_polls()
        except Exception:
            current = self.polls[guild_key].get(poll_id)
            if isinstance(current, dict):
                current.clear()
                current.update(previous)
            else:
                self.polls[guild_key][poll_id] = previous
            return False
        return True

    def _new_poll_record(self, guild_id, question, options, created_by, created_by_id=None):
        """Build a record so composed domain metadata can share one commit."""
        poll_id = f"poll_{guild_id}_{uuid.uuid4().hex}"

        poll = {
            "id": poll_id,
            "guild_id": str(guild_id),
            "question": question,
            "options": [
                {
                    "id": uuid.uuid4().hex,
                    "text": opt,
                    "votes": [],
                    "emoji": self.emojis[i],
                }
                for i, opt in enumerate(options[:10])
            ],
            "created_by": created_by,
            "created_by_id": created_by_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "status": "active",
            "revision": 0,
        }

        return poll

    @writable_store
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
        poll = self._new_poll_record(guild_id, question, options, created_by, created_by_id)
        poll_id = poll['id']

        guild_key = str(guild_id)
        created_guild_bucket = guild_key not in self.polls
        if created_guild_bucket:
            self.polls[guild_key] = {}

        self.polls[guild_key][poll_id] = poll
        try:
            self._save_polls()
        except Exception as error:
            del self.polls[guild_key][poll_id]
            if created_guild_bucket:
                del self.polls[guild_key]
            raise PollStorageError("Poll could not be saved") from error

        return poll

    def get_poll(self, guild_id, poll_id):
        """Get a poll by guild and poll ID. Returns dict or None."""
        guild_key = str(guild_id)
        records = self.polls
        if guild_key in records and poll_id in records[guild_key]:
            poll = records[guild_key][poll_id]
            return poll if self._planning_allowed(poll) else None
        return None

    def _planning_allowed(self, poll):
        metadata = poll.get('_planning')
        if metadata is None:
            return True
        from core.request_context import current_request
        actor = current_request()
        return bool(actor and actor.channel_id == metadata['channel_id']
            and self.planning_authorizer and self.planning_authorizer(actor, metadata['scope_id']))

    def is_poll_owner(self, poll, user_id, username=None):
        """
        Check if a user owns a poll.

        For polls created after this update, checks created_by_id.
        For legacy polls without created_by_id, falls back to created_by name.
        """
        if poll.get('_planning'):
            from core.request_context import current_request
            actor = current_request()
            if not actor or actor.user_id != str(user_id) or not self._planning_allowed(poll):
                return False
        if "created_by_id" in poll and poll["created_by_id"] is not None:
            return str(poll["created_by_id"]) == str(user_id)
        if username is not None:
            return poll.get("created_by") == username
        return False

    @writable_store
    def edit_poll(self, guild_id, poll_id, user_id, username=None, question=None, options=None):
        """
        Edit an existing active poll.

        Returns:
            (True, poll) or (False, error_message)
        """
        guild_key = str(guild_id)
        poll = self.get_poll(guild_key, poll_id)
        if not poll:
            return False, "Poll not found"

        if poll["status"] != "active":
            return False, "Poll is closed"

        if not self.is_poll_owner(poll, user_id, username):
            return False, "You are not the owner of this poll"

        changes = {}
        if question is not None:
            changes["question"] = question
        if options is not None:
            if len(options) != len(poll.get("options", [])):
                return False, (
                    "Structural edits require a reset preview and confirmation"
                )
            changes["option_labels"] = {option["id"]: label for option, label in zip(poll["options"], options)}
        preview = self.preview_poll_edit(
            guild_key, poll_id, changes, user_id, username
        )
        if not preview.get("ok"):
            return False, preview["error"]
        if preview["effect"] == "reset_votes":
            return False, "Structural poll edits require a reset confirmation"
        return self.apply_poll_edit(
            guild_key, poll_id, user_id, preview["token"]
        )

    @writable_store
    def preview_poll_edit(
        self, guild_id, poll_id, changes, actor_id, username=None
    ):
        """Build an actor- and revision-bound preview for a poll edit."""
        self._prune_previews()
        poll = self.get_poll(guild_id, poll_id)
        if poll is None:
            return {"ok": False, "error": "Poll not found"}
        if poll.get("status") != "active" or self._is_expired(poll):
            return {"ok": False, "error": "Poll is closed or expired"}
        if not self.is_poll_owner(poll, actor_id, username):
            return {"ok": False, "error": "You are not the owner of this poll"}
        if (
            not isinstance(changes, dict)
            or not changes
            or set(changes) - {"question", "options", "option_labels"}
        ):
            return {"ok": False, "error": "Invalid poll changes"}

        proposed = copy.deepcopy(poll)
        if "question" in changes:
            question = changes["question"]
            if (
                not isinstance(question, str)
                or not question.strip()
            ):
                return {"ok": False, "error": "Poll question cannot be empty"}
            proposed["question"] = question.strip()

        if "options" in changes:
            labels = changes["options"]
            if (
                not isinstance(labels, list)
                or not 1 <= len(labels) <= 10
                or any(
                    not isinstance(label, str) or not label.strip()
                    for label in labels
                )
            ):
                return {
                    "ok": False,
                    "error": "Poll needs 1-10 non-empty options",
                }
            old_options = poll["options"]
            reset_votes = labels != [option["text"] for option in old_options]
            if reset_votes:
                proposed["options"] = [
                    {
                        "id": uuid.uuid4().hex,
                        "text": label.strip(),
                        "votes": [],
                        "emoji": self.emojis[index],
                    }
                    for index, label in enumerate(labels)
                ]
            else:
                proposed["options"] = []
                for index, label in enumerate(labels):
                    option = copy.deepcopy(old_options[index])
                    option["text"] = label.strip()
                    option["emoji"] = self.emojis[index]
                    proposed["options"].append(option)
        else:
            reset_votes = False

        if 'option_labels' in changes:
            labels = changes['option_labels']
            known = {option['id'] for option in poll['options']}
            if ('options' in changes or not isinstance(labels, dict) or not labels
                    or set(labels) - known or any(not isinstance(text, str) or not text.strip() for text in labels.values())):
                return {'ok': False, 'error': 'Invalid option label changes'}
            for option in proposed['options']:
                if option['id'] in labels:
                    option['text'] = labels[option['id']].strip()
        if len(self._edit_previews) >= 128:
            self._edit_previews.pop(next(iter(self._edit_previews)))
        token = uuid.uuid4().hex
        self._edit_previews[token] = {
            "guild_id": str(guild_id),
            "expires_at": self._monotonic() + 300,
            "poll_id": poll_id,
            "actor_id": str(actor_id),
            "revision": poll.get("revision", 0),
            "changes": proposed,
            "effect": "reset_votes" if reset_votes else "preserve_votes",
        }
        return {
            "ok": True,
            "token": token,
            "poll_id": poll_id,
            "revision": poll.get("revision", 0),
            "effect": "reset_votes" if reset_votes else "preserve_votes",
            "requires_confirmation": reset_votes,
            "question": proposed["question"],
            "options": copy.deepcopy(proposed["options"]),
        }

    @writable_store
    def apply_poll_edit(
        self, guild_id, poll_id, actor_id, preview_token, confirm_reset=False,
        username=None,
    ):
        """Apply when actor, revision, and reset confirmation match."""
        self._prune_previews()
        preview = self._edit_previews.get(preview_token)
        if preview is None:
            return False, "Poll edit preview is missing or stale"
        if poll_id is None:
            poll_id = preview["poll_id"]
        if (
            preview["guild_id"] != str(guild_id)
            or preview["poll_id"] != poll_id
            or preview["actor_id"] != str(actor_id)
        ):
            return False, "Poll edit preview belongs to another poll or actor"
        poll = self.get_poll(guild_id, poll_id)
        if poll is None:
            return False, "Poll not found"
        if not self.is_poll_owner(poll, actor_id, username):
            return False, "You are not the owner of this poll"
        if poll.get("status") != "active" or self._is_expired(poll):
            return False, "Poll is closed or expired"
        if poll.get("revision", 0) != preview["revision"]:
            self._edit_previews.pop(preview_token, None)
            return False, "Poll edit preview is stale"
        if preview["effect"] == "reset_votes" and not confirm_reset:
            return False, "Structural poll edits require a reset confirmation"

        previous = copy.deepcopy(poll)
        proposed = copy.deepcopy(preview["changes"])
        proposed["revision"] = poll.get("revision", 0) + 1
        self.polls[str(guild_id)][poll_id] = proposed
        if not self._persist_or_restore(str(guild_id), poll_id, previous):
            return False, "Poll edit could not be saved"
        self._edit_previews.pop(preview_token, None)
        return True, proposed

    @writable_store
    def delete_poll(self, guild_id, poll_id, user_id, username=None):
        """
        Delete a poll.

        Returns:
            (True, "Poll deleted") or (False, error_message)
        """
        guild_key = str(guild_id)
        poll = self.get_poll(guild_key, poll_id)
        if not poll:
            return False, "Poll not found"

        if not self.is_poll_owner(poll, user_id, username):
            return False, "You are not the owner of this poll"

        if poll.get('_planning'):
            return False, "Use plan cancellation; linked planning receipts are retained"

        previous = copy.deepcopy(poll)
        del self.polls[guild_key][poll_id]
        try:
            self._save_polls()
        except Exception:
            self.polls[guild_key][poll_id] = previous
            return False, "Poll deletion could not be saved"
        return True, "Poll deleted"

    @writable_store
    def vote(self, guild_id, poll_id, option_num, user_id, username):
        """
        Cast a vote

        Args:
            option_num: 1-indexed option number
        """
        guild_key = str(guild_id)

        if guild_key not in self.polls or poll_id not in self.polls[guild_key]:
            return False, "Poll not found"

        poll = self.polls[guild_key][poll_id]

        if poll["status"] != "active":
            return False, "Poll is closed"
        if self._is_expired(poll):
            return False, "Poll has expired"

        if type(option_num) is not int:
            return False, "Invalid option"
        if poll.get('_planning'):
            from core.request_context import current_request
            actor = current_request()
            if not actor or actor.user_id != str(user_id):
                return False, "Poll actor is unavailable"
        option_idx = option_num - 1
        if option_idx < 0 or option_idx >= len(poll["options"]):
            return False, "Invalid option"

        if not self._planning_allowed(poll):
            return False, "Poll scope is unavailable"

        previous = copy.deepcopy(poll)
        # Remove previous vote from this user
        for opt in poll["options"]:
            if str(user_id) in opt["votes"]:
                opt["votes"].remove(str(user_id))

        # Add new vote
        poll["options"][option_idx]["votes"].append(str(user_id))
        poll["revision"] = poll.get("revision", 0) + 1
        if not self._persist_or_restore(guild_key, poll_id, previous):
            return False, "Vote could not be saved"

        return True, "Vote recorded"

    def get_active_polls(self, guild_id):
        """Get active polls for a guild"""
        guild_key = str(guild_id)

        if guild_key not in self.polls:
            return []

        active = []

        for poll_id, poll in self.polls[guild_key].items():
            if poll["status"] == "active" and self._planning_allowed(poll):
                if not self._is_expired(poll):
                    active.append(poll)

        return active

    def get_closed_polls(self, guild_id):
        """Return explicitly closed polls in this guild, newest first."""
        polls = self.polls.get(str(guild_id), {})
        return sorted(
            (
                poll for poll in polls.values()
                if poll.get("status") == "closed" and self._planning_allowed(poll)
            ),
            key=lambda poll: poll.get("created_at", ""), reverse=True,
        )

    def get_closed_poll_results(self, guild_id, poll_id):
        """Return only a closed poll from the requested guild."""
        poll = self.get_poll(guild_id, poll_id)
        if poll is not None and poll.get("status") == "closed":
            return poll
        return None

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
            if option.get("id"):
                lines.append(f"   Valg-ID: `{option['id']}`")
            lines.append(f"   {bar} {votes} {vote_label} ({percentage:.0f}%)")
            lines.append("")

        lines.append(f"{total_label}: {total_votes} {vote_label}")
        if poll.get('status') == 'closed' or self._is_expired(poll):
            lines.append('🔒 Avstemningen er lukket eller utløpt; nye stemmer avvises.' if lang == 'no' else 'Closed or expired; new votes are refused.')
        else:
            lines.append(f"💡 {vote_hint} (1-{len(poll['options'])})")

        return "\n".join(lines)

    @writable_store
    def close_poll(self, guild_id, poll_id, user_id=None, username=None):
        """
        Close a poll. If user_id is provided, checks ownership.

        Returns:
            (True, poll) or (False, error_message)
        """
        guild_key = str(guild_id)
        poll = self.get_poll(guild_key, poll_id)
        if not poll:
            return False, "Poll not found"

        if (user_id is not None or poll.get('_planning')) and not self.is_poll_owner(poll, user_id, username):
            return False, "You are not the owner of this poll"

        if poll["status"] == "closed":
            return False, "Poll is already closed"

        previous = copy.deepcopy(poll)
        poll["status"] = "closed"
        poll["revision"] = poll.get("revision", 0) + 1
        if not self._persist_or_restore(guild_key, poll_id, previous):
            return False, "Poll close could not be saved"
        return True, poll


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
