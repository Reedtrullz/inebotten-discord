#!/usr/bin/env python3
"""
Poll Manager for Inebotten
Simple, conversational polls for quick decisions
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
import random


class PollManager:
    """
    Manages quick polls for group decisions
    """

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / ".hermes" / "discord" / "polls.json"

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.polls = self._load_polls()
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

    def _save_polls(self):
        """Save polls to storage"""
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.polls, f, ensure_ascii=False, indent=2)

    def create_poll(self, guild_id, question, options, created_by):
        """
        Create a new poll

        Args:
            guild_id: Discord guild/channel ID
            question: The poll question
            options: List of option strings
            created_by: Username who created it

        Returns:
            poll_id
        """
        poll_id = f"poll_{guild_id}_{int(datetime.now().timestamp())}"

        poll = {
            "id": poll_id,
            "guild_id": str(guild_id),
            "question": question,
            "options": [
                {"text": opt, "votes": [], "emoji": self.emojis[i]}
                for i, opt in enumerate(options[:10])
            ],
            "created_by": created_by,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
            "status": "active",
        }

        if str(guild_id) not in self.polls:
            self.polls[str(guild_id)] = {}

        self.polls[str(guild_id)][poll_id] = poll
        self._save_polls()

        return poll

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

        option_idx = option_num - 1
        if option_idx < 0 or option_idx >= len(poll["options"]):
            return False, "Invalid option"

        # Remove previous vote from this user
        for opt in poll["options"]:
            if str(user_id) in opt["votes"]:
                opt["votes"].remove(str(user_id))

        # Add new vote
        poll["options"][option_idx]["votes"].append(str(user_id))
        self._save_polls()

        return True, "Vote recorded"

    def get_active_polls(self, guild_id):
        """Get active polls for a guild"""
        guild_key = str(guild_id)

        if guild_key not in self.polls:
            return []

        now = datetime.now()
        active = []

        for poll_id, poll in self.polls[guild_key].items():
            if poll["status"] == "active":
                expires = datetime.fromisoformat(poll["expires_at"])
                if expires > now:
                    active.append(poll)

        return active

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

    def close_poll(self, guild_id, poll_id):
        """Close a poll"""
        guild_key = str(guild_id)

        if guild_key in self.polls and poll_id in self.polls[guild_key]:
            self.polls[guild_key][poll_id]["status"] = "closed"
            self._save_polls()
            return True
        return False


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
    has_options = "/" in content and len(content.split("/")) >= 2
    
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
