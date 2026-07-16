#!/usr/bin/env python3
"""Persistent, transaction-safe user memory for Inebotten."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MEMORY_STORE_SCOPE, MutationCoordinator
from utils.json_storage import hermes_discord_data_path, write_json_atomic


_T = TypeVar("_T")

_PROVIDER_TEXT_LIMIT = 200
_PROVIDER_LIST_LIMIT = 5


def _provider_text(value: object) -> str | None:
    """Return one bounded stored string without coercing arbitrary objects."""

    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:_PROVIDER_TEXT_LIMIT]


def _provider_text_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    selected: list[str] = []
    for raw in value:
        candidates = raw if isinstance(raw, (list, tuple)) else (raw,)
        for candidate in candidates:
            text = _provider_text(candidate)
            if text is not None:
                selected.append(text)
            if len(selected) >= _PROVIDER_LIST_LIMIT:
                return selected
    return selected


def provider_memory_projection(snapshot: object) -> dict[str, object]:
    """Project stored memory onto the explicit provider-safe schema.

    Stored records are intentionally open for backward compatibility.  That
    makes the provider boundary the wrong place to copy a record wholesale:
    unknown legacy keys can contain secrets or private notes.  Only the fields
    already used by the historical personalized-context formatter are allowed.
    """

    if not isinstance(snapshot, Mapping):
        return {}

    projected: dict[str, object] = {}
    location = _provider_text(snapshot.get("location"))
    if location is not None:
        projected["location"] = location

    interests = _provider_text_list(snapshot.get("interests"))
    if interests:
        projected["interests"] = interests

    topics = _provider_text_list(snapshot.get("last_topics"))
    if topics:
        projected["last_topics"] = topics

    raw_preferences = snapshot.get("preferences")
    if isinstance(raw_preferences, Mapping):
        preferences: dict[str, object] = {}
        humor_style = _provider_text(raw_preferences.get("humor_style"))
        if humor_style is not None:
            preferences["humor_style"] = humor_style
        use_dialect = raw_preferences.get("use_dialect")
        if isinstance(use_dialect, bool):
            preferences["use_dialect"] = use_dialect
        if preferences:
            projected["preferences"] = preferences

    return projected


class UserMemory:
    """Manage the complete user-memory JSON root through one coordinator."""

    def __init__(
        self,
        storage_path=None,
        *,
        mutation_coordinator: MutationCoordinator | None = None,
    ) -> None:
        if storage_path is None:
            storage_path = hermes_discord_data_path("user_memory.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()
        self.memory: dict[str, dict[str, Any]] = {}

    async def setup(self) -> None:
        """Load the last committed root before production writers start."""
        self.memory = await self._load_memory()

    async def _load_memory(self) -> dict[str, dict[str, Any]]:
        if not self.storage_path.exists():
            return {}

        def _read() -> dict[str, dict[str, Any]]:
            try:
                with self.storage_path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                return loaded if isinstance(loaded, dict) else {}
            except Exception:
                return {}

        return await asyncio.to_thread(_read)

    def _save_memory_sync(self, candidate: dict[str, dict[str, Any]]) -> None:
        """Persist one detached complete-root candidate or raise."""
        write_json_atomic(self.storage_path, candidate)

    async def _persist_and_publish(
        self,
        candidate: dict[str, dict[str, Any]],
    ) -> None:
        """Settle one owned atomic write before publishing or carrying cancellation."""
        save_task = asyncio.create_task(
            asyncio.to_thread(self._save_memory_sync, candidate),
            name="user-memory-save",
        )
        current = asyncio.current_task()
        outer_cancelled = False

        while True:
            try:
                await asyncio.shield(save_task)
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

        if save_task.cancelled():
            raise ManagerMutationCancelled(
                "commit_state_unknown",
                mutated=False,
                retryable=False,
                commit_unknown=True,
            )

        try:
            save_task.result()
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

        self.memory = candidate
        if outer_cancelled:
            raise ManagerMutationCancelled(
                "cancelled",
                mutated=True,
                retryable=False,
            )

    async def _transaction(
        self,
        mutate: Callable[
            [dict[str, dict[str, Any]]],
            tuple[_T, bool],
        ],
    ) -> _T:
        """Mutate a detached root, persist it, then publish exactly once."""
        try:
            async with self.mutation_coordinator.hold(MEMORY_STORE_SCOPE):
                candidate = copy.deepcopy(self.memory)
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
    def _require_reference_time(reference_time: datetime) -> datetime:
        if (
            not isinstance(reference_time, datetime)
            or reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time_must_be_aware")
        return reference_time

    @staticmethod
    def _new_user(username: object, reference_time: datetime) -> dict[str, Any]:
        return {
            "username": username,
            "first_seen": reference_time.isoformat(),
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

    def _get_user_locked(
        self,
        candidate: dict[str, dict[str, Any]],
        user_id: object,
        *,
        username: object = None,
        reference_time: datetime | None = None,
        create: bool,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Return one candidate-owned record; caller already owns the root lease."""
        key = str(user_id)
        user = candidate.get(key)
        changed = False
        if not isinstance(user, dict):
            if not create:
                return None, False
            if reference_time is None:
                raise ValueError("reference_time_required")
            user = self._new_user(username, reference_time)
            candidate[key] = user
            changed = True
        elif username and not user.get("username"):
            user["username"] = username
            changed = True
        return user, changed

    async def get_or_create_user_result(
        self,
        user_id: object,
        username: object,
        *,
        reference_time: datetime,
    ) -> dict[str, Any]:
        reference = self._require_reference_time(reference_time)

        def mutate(candidate):
            user, changed = self._get_user_locked(
                candidate,
                user_id,
                username=username,
                reference_time=reference,
                create=True,
            )
            assert user is not None
            return user, changed

        return await self._transaction(mutate)

    async def update_last_interaction_result(
        self,
        user_id: object,
        *,
        reference_time: datetime,
        topic: object = None,
        username: object = None,
    ) -> bool:
        reference = self._require_reference_time(reference_time)

        def mutate(candidate):
            user, _ = self._get_user_locked(
                candidate,
                user_id,
                username=username,
                reference_time=reference,
                create=True,
            )
            assert user is not None
            user["last_interaction"] = reference.isoformat()
            user["conversation_count"] = user.get("conversation_count", 0) + 1
            if topic:
                current = list(user.get("last_topics") or [])
                if isinstance(topic, list):
                    for item in reversed(topic):
                        if item not in current:
                            current = [item] + current
                else:
                    current = [topic] + current
                user["last_topics"] = current[:5]
            return True, True

        return await self._transaction(mutate)

    async def add_interest_result(self, user_id: object, interest: object) -> bool:
        def mutate(candidate):
            user, _ = self._get_user_locked(
                candidate, user_id, create=False
            )
            if user is None:
                return False, False
            interests = user.setdefault("interests", [])
            normalized = str(interest)
            if normalized.casefold() in {
                str(item).casefold() for item in interests
            }:
                return False, False
            interests.append(interest)
            return True, True

        return await self._transaction(mutate)

    async def set_preference_result(
        self,
        user_id: object,
        key: object,
        value: object,
    ) -> bool:
        def mutate(candidate):
            user, _ = self._get_user_locked(
                candidate, user_id, create=False
            )
            if user is None:
                return False, False
            preferences = user.setdefault("preferences", {})
            if preferences.get(key) == value and key in preferences:
                return False, False
            preferences[key] = value
            return True, True

        return await self._transaction(mutate)

    async def set_location_result(
        self,
        user_id: object,
        canonical_city: object,
    ) -> bool:
        def mutate(candidate):
            user, _ = self._get_user_locked(
                candidate, user_id, create=False
            )
            if user is None or user.get("location") == canonical_city:
                return False, False
            user["location"] = canonical_city
            return True, True

        return await self._transaction(mutate)

    async def delete_user_memory_result(self, user_id: object) -> bool:
        def mutate(candidate):
            key = str(user_id)
            if key not in candidate:
                return False, False
            del candidate[key]
            return True, True

        return await self._transaction(mutate)

    def snapshot_pending_user(self, user_id: object) -> dict[str, Any] | None:
        key = str(user_id)
        if key not in self.memory:
            return None
        user = self.memory[key]
        if not isinstance(user, dict):
            raise ValueError("invalid_target_state")
        return copy.deepcopy(user)

    def snapshot_user(self, user_id: object) -> dict[str, Any] | None:
        return self.snapshot_pending_user(user_id)

    async def get_user(self, user_id: object, username=None) -> dict[str, Any]:
        """Return a detached read-only snapshot; username never fills storage."""
        return self.snapshot_user(user_id) or {}

    async def update_last_interaction(
        self,
        user_id,
        topic=None,
        username=None,
    ) -> None:
        reference = datetime.now().astimezone()
        await self.update_last_interaction_result(
            user_id,
            reference_time=reference,
            topic=topic,
            username=username,
        )

    async def add_interest(self, user_id, interest) -> None:
        reference = datetime.now().astimezone()
        await self.get_or_create_user_result(
            user_id, None, reference_time=reference
        )
        await self.add_interest_result(user_id, interest)

    async def set_preference(self, user_id, key, value) -> None:
        reference = datetime.now().astimezone()
        await self.get_or_create_user_result(
            user_id, None, reference_time=reference
        )
        await self.set_preference_result(user_id, key, value)

    async def set_location(self, user_id, location) -> None:
        reference = datetime.now().astimezone()
        await self.get_or_create_user_result(
            user_id, None, reference_time=reference
        )
        await self.set_location_result(user_id, location)

    async def delete_user_memory(self, user_id) -> bool:
        return await self.delete_user_memory_result(user_id)

    async def get_days_since_last_chat(self, user_id):
        user = self.snapshot_user(user_id) or {}
        last = user.get("last_interaction")
        if not last:
            return None
        try:
            return (datetime.now().astimezone() - datetime.fromisoformat(last)).days
        except (TypeError, ValueError):
            return None

    async def get_personalized_greeting(self, user_id, username=None):
        user = self.snapshot_user(user_id) or {}
        days_since = await self.get_days_since_last_chat(user_id)
        hour = datetime.now().astimezone().hour
        if 5 <= hour < 12:
            greeting = "God morgen"
        elif 12 <= hour < 17:
            greeting = "God dag"
        elif 17 <= hour < 22:
            greeting = "God kveld"
        else:
            greeting = "Hei"
        name = user.get("username") or username or ""
        parts = [f"{greeting} {name}!" if name else f"{greeting}!"]
        if days_since is not None and days_since >= 3:
            parts.append(f"Lenge siden sist - {days_since} dager!")
        interests = user.get("interests") or []
        if interests:
            import random

            parts.append(f"Forresten, hvordan går det med {random.choice(interests)}?")
        return " ".join(parts)

    async def format_context_for_prompt(self, user_id, username=None):
        user = self.snapshot_user(user_id) or {}
        parts = []
        if user.get("location"):
            parts.append(f"Bor i: {user['location']}")
        interests = [str(item) for item in user.get("interests", []) if item]
        if interests:
            parts.append(f"Interesser: {', '.join(interests)}")
        topics = []
        for topic in user.get("last_topics", [])[:3]:
            if isinstance(topic, list):
                topics.extend(str(item) for item in topic if item)
            elif topic:
                topics.append(str(topic))
        if topics:
            parts.append(f"Nylige samtaler: {', '.join(topics[:3])}")
        preferences = user.get("preferences") or {}
        if preferences.get("humor_style"):
            parts.append(f"Humørstil: {preferences['humor_style']}")
        if preferences.get("use_dialect"):
            parts.append("Bruker gjerne dialektuttrykk")
        return " | ".join(parts)

    async def export_user_memory(self, user_id):
        return self.snapshot_user(user_id) or {}

    async def format_user_memory_for_user(self, user_id, username=None):
        user = self.snapshot_user(user_id)
        if not user:
            return "Jeg har ikke lagret noe brukerminne om deg ennå."
        preferences = user.get("preferences") or {}
        interests = user.get("interests") or []
        topics = user.get("last_topics") or []
        lines = [
            "🧠 **Dette husker jeg om deg:**",
            f"Navn: {user.get('username') or username or 'ikke lagret'}",
            f"Sted: {user.get('location') or 'ikke lagret'}",
            f"Interesser: {', '.join(map(str, interests)) if interests else 'ingen lagret'}",
            f"Preferanser: {json.dumps(preferences, ensure_ascii=False)}",
            f"Siste tema: {', '.join(map(str, topics[:5])) if topics else 'ingen lagret'}",
            "",
            "Skriv `@inebotten eksporter minnet mitt` for JSON, eller "
            "`@inebotten slett minnet mitt` for å slette det.",
        ]
        return "\n".join(lines)


_user_memory: UserMemory | None = None


def get_user_memory(
    mutation_coordinator: MutationCoordinator | None = None,
) -> UserMemory:
    """Return the compatibility singleton without weakening coordinator ownership."""
    global _user_memory
    if _user_memory is None:
        _user_memory = UserMemory(
            mutation_coordinator=mutation_coordinator
        )
    elif (
        mutation_coordinator is not None
        and _user_memory.mutation_coordinator is not mutation_coordinator
    ):
        raise RuntimeError("mutation_coordinator_identity_mismatch")
    return _user_memory


if __name__ == "__main__":
    async def main() -> None:
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(delete=False) as tmp:
            storage_path = tmp.name
        memory = UserMemory(storage_path)
        await memory.setup()
        await memory.update_last_interaction(
            "user1", "RBK-kamp", username="Ola"
        )
        await memory.add_interest("user1", "fotball")
        await memory.set_location("user1", "Trondheim")
        print("User memory:", await memory.get_user("user1"))
        Path(storage_path).unlink(missing_ok=True)

    asyncio.run(main())
