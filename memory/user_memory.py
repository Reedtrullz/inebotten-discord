#!/usr/bin/env python3
"""
User Memory System for Inebotten
Stores preferences, conversation history, and personal details per user
"""

import json
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path


class UserMemory:
    """
    Manages persistent memory about users across conversations
    """

    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = (
                Path.home() / ".hermes" / "discord" / "data" / "user_memory.json"
            )

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory = {}

    async def setup(self):
        """Async initialization"""
        self.memory = await self._load_memory()

    async def _load_memory(self):
        """Load memory from storage asynchronously"""
        if not self.storage_path.exists():
            return {}

        def _read():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[MEMORY] User memory load error: {e}")
                return {}

        return await asyncio.to_thread(_read)

    async def _save_memory(self):
        """Save memory to storage atomically and asynchronously"""
        def _write():
            temp_path = self.storage_path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self.memory, f, ensure_ascii=False, indent=2)
                os.replace(temp_path, self.storage_path)
            except Exception as e:
                print(f"[MEMORY] User memory save error: {e}")
                if temp_path.exists():
                    os.remove(temp_path)

        await asyncio.to_thread(_write)

    async def get_user(self, user_id, username=None):
        """
        Get or create user memory
        """
        user_key = str(user_id)

        if user_key not in self.memory:
            self.memory[user_key] = {
                "username": username,
                "first_seen": datetime.now().isoformat(),
                "preferences": {
                    "formality": "casual",
                    "humor_style": "friendly",
                    "response_length": "medium",
                    "use_dialect": True,
                },
                "interests": [],
                "location": None,
                "last_topics": [],
                "conversation_count": 0,
                "last_interaction": None,
                "favorite_commands": [],
                "birthday": None,
                "timezone": "Europe/Oslo",
            }
            await self._save_memory()

        if username and not self.memory[user_key].get("username"):
            self.memory[user_key]["username"] = username
            await self._save_memory()

        return self.memory[user_key]

    async def update_last_interaction(self, user_id, topic=None, username=None):
        """Update last interaction time and optionally topic"""
        user = await self.get_user(user_id, username)
        user["last_interaction"] = datetime.now().isoformat()
        user["conversation_count"] = user.get("conversation_count", 0) + 1

        if topic:
            user["last_topics"] = ([topic] + user.get("last_topics", []))[:5]

        await self._save_memory()

    async def add_interest(self, user_id, interest):
        """Add an interest for a user"""
        user = await self.get_user(user_id)
        if interest.lower() not in [i.lower() for i in user.get("interests", [])]:
            user["interests"].append(interest)
            await self._save_memory()

    async def set_preference(self, user_id, key, value):
        """Set a user preference"""
        user = await self.get_user(user_id)
        if "preferences" not in user:
            user["preferences"] = {}
        user["preferences"][key] = value
        await self._save_memory()

    async def set_location(self, user_id, location):
        """Set user location"""
        user = await self.get_user(user_id)
        user["location"] = location
        await self._save_memory()

    async def get_days_since_last_chat(self, user_id):
        """Get number of days since last interaction"""
        user = await self.get_user(user_id)
        last = user.get("last_interaction")
        if not last:
            return None

        try:
            last_date = datetime.fromisoformat(last)
            delta = datetime.now() - last_date
            return delta.days
        except Exception as e:
            print(f"[MEMORY] Date parse error: {e}")
            return None

    async def get_personalized_greeting(self, user_id, username=None):
        """Generate a personalized greeting"""
        user = await self.get_user(user_id, username)
        days_since = await self.get_days_since_last_chat(user_id)

        greetings = []
        name = user.get("username") or username or ""

        # Time-based greeting
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_greeting = "God morgen"
        elif 12 <= hour < 17:
            time_greeting = "God dag"
        elif 17 <= hour < 22:
            time_greeting = "God kveld"
        else:
            time_greeting = "Hei"

        # Add name if known
        if name:
            greetings.append(f"{time_greeting} {name}!")
        else:
            greetings.append(f"{time_greeting}!")

        # Add "long time no see" if appropriate
        if days_since is not None and days_since >= 3:
            greetings.append(f"Lenge siden sist - {days_since} dager!")

        # Add reference to known interests
        interests = user.get("interests", [])
        if interests and len(interests) > 0:
            import random

            interest = random.choice(interests)
            greetings.append(f"Forresten, hvordan går det med {interest}?")

        return " ".join(greetings)

    async def format_context_for_prompt(self, user_id, username=None):
        """Format user memory as context for AI prompt"""
        user = await self.get_user(user_id, username)

        context_parts = []

        # Basic info
        if user.get("location"):
            context_parts.append(f"Bor i: {user['location']}")

        # Interests
        if user.get("interests"):
            context_parts.append(f"Interesser: {', '.join(user['interests'])}")

        # Recent topics
        if user.get("last_topics"):
            context_parts.append(
                f"Nylige samtaler: {', '.join(user['last_topics'][:3])}"
            )

        # Preferences
        prefs = user.get("preferences", {})
        if prefs.get("humor_style"):
            context_parts.append(f"Humørstil: {prefs['humor_style']}")
        if prefs.get("use_dialect"):
            context_parts.append("Bruker gjerne dialektuttrykk")

        return " | ".join(context_parts) if context_parts else ""


# Singleton instance
_user_memory = None


def get_user_memory():
    """Get or create singleton UserMemory instance"""
    global _user_memory
    if _user_memory is None:
        _user_memory = UserMemory()
    return _user_memory


if __name__ == "__main__":
    # Test
    mem = UserMemory(storage_path="/tmp/test_user_memory.json")

    # Simulate user interactions
    mem.update_last_interaction("user1", "RBK-kamp", username="Ola")
    mem.add_interest("user1", "fotball")
    mem.add_interest("user1", "RBK")
    mem.set_location("user1", "Trondheim")

    print("User memory:", mem.get_user("user1"))
    print("\nGreeting:", mem.get_personalized_greeting("user1"))
    print("\nContext:", mem.format_context_for_prompt("user1"))

    # Cleanup
    import os

    os.remove("/tmp/test_user_memory.json")
