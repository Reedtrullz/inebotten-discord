#!/usr/bin/env python3
"""
User Memory System for Inebotten
Stores preferences, conversation history, and personal details per user
"""

import json
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from pathlib import Path

from utils.json_storage import hermes_discord_data_path, write_json_atomic
from utils.storage_contract import DocumentOwner, StorageMutationError, user_records, writable_store, store_worker


@dataclass(frozen=True)
class MemoryPolicy:
    learning_enabled: bool = False
    topic_retention_days: int | None = 7
    allowed_provider_ids: tuple[str, ...] = ()
    private_facts_enabled: bool = False

    def __post_init__(self):
        if type(self.learning_enabled) is not bool or type(self.private_facts_enabled) is not bool:
            raise ValueError('invalid_memory_policy')
        if self.topic_retention_days is not None and (type(self.topic_retention_days) is not int or not 1 <= self.topic_retention_days <= 365):
            raise ValueError('invalid_topic_retention')
        if not isinstance(self.allowed_provider_ids, (list, tuple)) or any(p not in ('hermes', 'openrouter') for p in self.allowed_provider_ids):
            raise ValueError('invalid_memory_provider')
        object.__setattr__(self, 'allowed_provider_ids', tuple(dict.fromkeys(self.allowed_provider_ids)))

    def document(self):
        value = asdict(self)
        value['allowed_provider_ids'] = list(self.allowed_provider_ids)
        return value


def validate_memory(document):
    if not user_records(document):
        return False
    try:
        for user in document.values():
            if 'memory_policy' in user:
                MemoryPolicy(**user['memory_policy'])
            if 'topic_timestamps' in user and (not isinstance(user['topic_timestamps'], dict)
                or any(not isinstance(key, str) or not isinstance(value, str) for key, value in user['topic_timestamps'].items())):
                return False
        return True
    except (TypeError, ValueError):
        return False


class UserMemory:
    """
    Manages persistent memory about users across conversations
    """

    def __init__(self, storage_path=None, *, wall=None, conversation=None):
        if storage_path is None:
            storage_path = hermes_discord_data_path("user_memory.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.wall = wall or (lambda: datetime.now(timezone.utc))
        self.conversation = conversation
        self._storage = DocumentOwner(self.storage_path, validate_memory)
        self.memory = self._storage.rollback()

    async def setup(self):
        """Async initialization"""
        self.memory = await self._load_memory()

    @property
    def memory(self):
        return self._storage.data

    @memory.setter
    def memory(self, value):
        self._storage.data = value

    @property
    def storage_state(self):
        return self._storage.state

    async def _load_memory(self):
        return await asyncio.to_thread(self._storage.load)

    async def _save_memory(self):
        result = await store_worker(self._storage.commit, copy.deepcopy(self.memory), writer=write_json_atomic)
        if not result.ok:
            self.memory = self._storage.rollback()
            raise StorageMutationError(result.error_code)

    @writable_store
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

    def policy_for_user(self, user_id):
        user = self.memory.get(str(user_id), {})
        return MemoryPolicy(**user.get('memory_policy', {}))

    @writable_store
    async def set_policy(self, user_id, **changes):
        policy = self.policy_for_user(user_id).document()
        policy.update(changes)
        validated = MemoryPolicy(**policy)
        user = await self.get_user(user_id)
        user['memory_policy'] = validated.document()
        await self._save_memory()
        return validated

    @writable_store
    async def update_last_interaction(self, user_id, topic=None, username=None):
        """Only opted-in temporary topics are automatically retained."""
        if not self.policy_for_user(user_id).learning_enabled:
            return
        user = await self.get_user(user_id, username)
        now = self.wall().isoformat()
        user['last_interaction'] = now
        user['conversation_count'] = user.get('conversation_count', 0) + 1
        if topic:
            topics = topic if isinstance(topic, list) else [topic]
            valid = [value for value in topics if isinstance(value, str) and value.strip() and len(value) <= 500]
            dated = user.setdefault('topic_timestamps', {})
            for value in reversed(valid[:5]):
                user['last_topics'] = [value] + [old for old in user.get('last_topics', []) if old != value]
                dated[value] = now
            user['last_topics'] = user['last_topics'][:5]
            user['topic_timestamps'] = {key: value for key, value in dated.items() if key in user['last_topics']}
        await self._save_memory()

    @writable_store
    async def prune_topics(self):
        changed = False
        now = self.wall()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        for user_id, user in self.memory.items():
            days = self.policy_for_user(user_id).topic_retention_days
            if days is None:
                continue
            timestamps = user.get('topic_timestamps', {})
            expired = set()
            for topic, raw in timestamps.items():
                try:
                    stamp = datetime.fromisoformat(raw)
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    if now - stamp >= timedelta(days=days):
                        expired.add(topic)
                except (TypeError, ValueError):
                    continue  # Unknown legacy age is never inferred for deletion.
            if expired:
                user['last_topics'] = [topic for topic in user.get('last_topics', []) if not isinstance(topic, str) or topic not in expired]
                user['topic_timestamps'] = {key: value for key, value in timestamps.items() if key not in expired}
                changed = True
        if changed:
            await self._save_memory()
        return changed

    async def build_prompt_memory(self, user_id, provider_id, scope_id):
        await self.prune_topics()
        policy = self.policy_for_user(user_id)
        if not policy.learning_enabled or provider_id not in policy.allowed_provider_ids:
            return {}
        user = self.memory.get(str(user_id), {})
        result = {'preferences': copy.deepcopy(user.get('preferences', {}))}
        # Personal facts and remembered topics cannot travel into a group or
        # shared audience simply because a provider has been allowed.
        if policy.private_facts_enabled and scope_id == f'private:{user_id}':
            result.update({key: copy.deepcopy(user[key]) for key in ('location', 'interests', 'saved_facts', 'school_locality') if user.get(key)})
            timestamps = user.get('topic_timestamps', {})
            topics = []
            now = self.wall()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            for topic in user.get('last_topics', []):
                if not isinstance(topic, str) or topic not in timestamps:
                    continue
                try:
                    stamp = datetime.fromisoformat(timestamps[topic])
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    if stamp <= now:
                        topics.append(topic)
                except (TypeError, ValueError):
                    pass
            result['last_topics'] = topics[:5]
        return result

    @writable_store
    async def set_saved_fact(self, user_id, key, value):
        if key != 'school_locality' or value not in ('oslo', 'trondheim'):
            raise ValueError('unsupported_saved_fact')
        user = await self.get_user(user_id)
        user[key] = value
        await self._save_memory()

    async def delete_local_memory(self, user_id, *, include_transient):
        deleted = await self.delete_user_memory(user_id)
        count = self.conversation.delete_user(user_id) if include_transient and self.conversation is not None else 0
        return {'persistent_deleted': deleted, 'transient_deleted': count,
            'exclusions': ['backups', 'remote_providers', 'discord_messages']}

    @writable_store
    async def add_interest(self, user_id, interest):
        """Add an interest for a user"""
        user = await self.get_user(user_id)
        if interest.lower() not in [i.lower() for i in user.get("interests", [])]:
            user["interests"].append(interest)
            await self._save_memory()

    @writable_store
    async def set_preference(self, user_id, key, value):
        """Set a user preference"""
        user = await self.get_user(user_id)
        if "preferences" not in user:
            user["preferences"] = {}
        user["preferences"][key] = value
        await self._save_memory()

    @writable_store
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
            now = self.wall()
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            delta = now - last_date
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

    async def format_context_for_prompt(self, user_id, username=None, *, provider_id=None, scope_id='shared'):
        """Format user memory as context for AI prompt"""
        if provider_id is None:
            return ''  # Compatibility callers must name the actual recipient.
        user = await self.build_prompt_memory(user_id, provider_id, scope_id)

        context_parts = []

        # Basic info
        if user.get("location"):
            context_parts.append(f"Bor i: {user['location']}")

        # Interests
        if user.get("interests"):
            interests = [str(i) for i in user["interests"] if i]
            if interests:
                context_parts.append(f"Interesser: {', '.join(interests)}")

        # Recent topics
        if user.get("last_topics"):
            # Ensure all items are strings (handles legacy corrupted data)
            topics = []
            for t in user["last_topics"][:3]:
                if isinstance(t, list):
                    topics.extend([str(item) for item in t if item])
                elif t:
                    topics.append(str(t))
            
            if topics:
                context_parts.append(
                    f"Nylige samtaler: {', '.join(topics[:3])}"
                )

        # Preferences
        prefs = user.get("preferences", {})
        if prefs.get("humor_style"):
            context_parts.append(f"Humørstil: {prefs['humor_style']}")
        if prefs.get("use_dialect"):
            context_parts.append("Bruker gjerne dialektuttrykk")

        return " | ".join(context_parts) if context_parts else ""

    @writable_store
    async def export_user_memory(self, user_id):
        """Return a copy of one user's stored memory without creating new data."""
        await self.prune_topics()
        user = self.memory.get(str(user_id))
        return copy.deepcopy(user) if isinstance(user, dict) else {}

    async def format_user_memory_for_user(self, user_id, username=None):
        """Format one user's memory for direct user-facing display."""
        user = await self.export_user_memory(user_id)
        if not user:
            return "Jeg har ikke lagret noe brukerminne om deg ennå."

        preferences = user.get("preferences") or {}
        interests = user.get("interests") or []
        topics = user.get("last_topics") or []
        policy = self.policy_for_user(user_id)
        lines = [
            "🧠 **Dette husker jeg om deg:**",
            f"Navn: {user.get('username') or username or 'ikke lagret'}",
            f"Sted: {user.get('location') or 'ikke lagret'}",
            f"Interesser: {', '.join(map(str, interests)) if interests else 'ingen lagret'}",
            f"Preferanser: {json.dumps(preferences, ensure_ascii=False)}",
            f"Siste tema: {', '.join(map(str, topics[:5])) if topics else 'ingen lagret'}",
            f"Automatisk læring: {'på' if policy.learning_enabled else 'pauset'}",
            f"Deling med AI: {', '.join(policy.allowed_provider_ids) or 'ingen'}",
            f"Private fakta i direktemelding: {'på' if policy.private_facts_enabled else 'av'}",
            f"Behold midlertidige tema: {str(policy.topic_retention_days) + ' dager' if policy.topic_retention_days else 'ubegrenset'}",
            f"Skolekommune: {user.get('school_locality') or 'ikke valgt'}",
            'Automatisk læring og provider-deling er av som standard. Bruk `minne læring på|av`, '
            '`minne del med lokal|openrouter|ingen`, `minne private fakta på|av` og `minne behold tema 7 dager`.',
            "",
            "Skriv `@inebotten eksporter minnet mitt` for JSON, eller "
            "`@inebotten slett minnet mitt bekreft` for å slette det.",
        ]
        return "\n".join(lines)

    @writable_store
    async def delete_user_memory(self, user_id):
        """Delete one user's stored memory, returning True if anything was removed."""
        user_key = str(user_id)
        if user_key not in self.memory:
            return False
        self.memory.pop(user_key, None)
        await self._save_memory()
        return True


# Singleton instance
_user_memory = None


def get_user_memory():
    """Get or create singleton UserMemory instance"""
    global _user_memory
    if _user_memory is None:
        _user_memory = UserMemory()
    return _user_memory


if __name__ == "__main__":
    async def main():
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(delete=False) as tmp:
            storage_path = tmp.name
        mem = UserMemory(storage_path=storage_path)

        # Simulate user interactions
        await mem.update_last_interaction("user1", "RBK-kamp", username="Ola")
        await mem.add_interest("user1", "fotball")
        await mem.add_interest("user1", "RBK")
        await mem.set_location("user1", "Trondheim")

        print("User memory:", await mem.get_user("user1"))
        print("\nGreeting:", await mem.get_personalized_greeting("user1"))
        print("\nContext:", await mem.format_context_for_prompt("user1"))

        Path(storage_path).unlink(missing_ok=True)

    asyncio.run(main())
