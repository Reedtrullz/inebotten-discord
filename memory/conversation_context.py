#!/usr/bin/env python3
"""Scoped typed conversation history with one-release legacy wrappers."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ai.chat_contract import ChatTurn, prepare_history
from core.message_context import ConversationKey


OSLO = ZoneInfo("Europe/Oslo")


@dataclass(frozen=True, slots=True)
class _StoredTurn:
    turn: ChatTurn
    timestamp: datetime
    # Retained only so integer-keyed compatibility wrappers do not lose their
    # exact legacy dictionary identity after lazy migration.
    legacy_user_id: object | None = None
    legacy_username: str | None = None


class ConversationContext:
    """Manage exact-key prompt history and isolated legacy channel threads."""

    DASHBOARD_KEYWORDS = [
        "vær",
        "været",
        "værmelding",
        "weather",
        "kalender",
        "kalenderen",
        "calendar",
        "plan",
        "planer",
        "hva skjer",
        "hva skal",
        "hva har jeg",
        "oversikt",
        "status",
        "dashboard",
        "påminnelse",
        "påminnelser",
        "huskeliste",
        "gjøremål",
        "navnedag",
        "navnedager",
    ]

    SMALL_TALK_PATTERNS = [
        r"^hei\b",
        r"^hallo\b",
        r"^halla\b",
        r"^yo\b",
        r"^god (morgen|dag|kveld|natt)",
        r"^morn\b",
        r"^kvelden\b",
        r"^heisann\b",
        r"hvordan går det",
        r"how are you",
        r"hva (gjør|driver) du",
        r"takk",
        r"bra",
        r"\?$",
        r"hva (synes|mener) du",
        r"forklar",
        r"fortell",
        r"\bkjekt\b",
        r"\btøft\b",
        r"\brått\b",
        r"\bskikkelig\b",
        r"\bkult\b",
        r"\bstilig\b",
        r"\bkempe",
        r"\bsupert\b",
        r"\bflott\b",
        r"\bskal\b",
        r"\bvil\b",
        r"\bblir\b",
        r"\bønsker\b",
        r"\bhva skjer\b",
        r"\bhva driver\b",
    ]

    def __init__(
        self,
        max_history: int = 10,
        expiry_minutes: int = 30,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            isinstance(max_history, bool)
            or not isinstance(max_history, int)
            or max_history < 1
        ):
            raise ValueError("invalid_max_history")
        if (
            isinstance(expiry_minutes, bool)
            or not isinstance(expiry_minutes, int)
            or expiry_minutes < 1
        ):
            raise ValueError("invalid_expiry_minutes")
        if now_provider is not None and not callable(now_provider):
            raise ValueError("invalid_now_provider")
        self.max_history = max_history
        self.expiry_minutes = expiry_minutes
        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )
        self.threads: defaultdict[
            ConversationKey | int,
            list[_StoredTurn | dict[str, object]],
        ] = defaultdict(list)
        self.last_bot_message: dict[ConversationKey | int, datetime] = {}

    def _now(self) -> datetime:
        value = self._now_provider()
        if not isinstance(value, datetime):
            raise ValueError("conversation_clock_must_be_datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("conversation_clock_must_be_aware")
        return value

    @staticmethod
    def _aware_timestamp(value: object) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=OSLO)
        return value

    def _coerce_entry(
        self,
        value: _StoredTurn | dict[str, object],
    ) -> _StoredTurn | None:
        if isinstance(value, _StoredTurn):
            return value
        if not isinstance(value, dict):
            return None
        content = value.get("content")
        if not isinstance(content, str):
            return None
        role_value = value.get("role")
        if role_value in {"user", "assistant"}:
            role = role_value
        else:
            role = "assistant" if bool(value.get("is_bot")) else "user"
        source_id = value.get("source_message_id")
        if isinstance(source_id, bool) or not isinstance(source_id, int):
            source_id = None
        timestamp = self._aware_timestamp(value.get("timestamp"))
        if timestamp is None:
            return None
        username = value.get("username")
        return _StoredTurn(
            ChatTurn(role, content, source_id),
            timestamp,
            legacy_user_id=value.get("user_id"),
            legacy_username=(username if isinstance(username, str) else None),
        )

    def _clean_old_messages(self, key: ConversationKey | int) -> None:
        cutoff = self._now() - timedelta(minutes=self.expiry_minutes)
        kept: list[_StoredTurn | dict[str, object]] = []
        for value in self.threads.get(key, ()):
            if isinstance(key, ConversationKey) and not isinstance(
                value,
                _StoredTurn,
            ):
                # Dictionary turns belong exclusively to the integer-keyed
                # compatibility API and can never migrate into provider input.
                continue
            stored = self._coerce_entry(value)
            if stored is not None and stored.timestamp > cutoff:
                kept.append(stored)
        if kept:
            self.threads[key] = kept[-self.max_history :]
        else:
            self.threads.pop(key, None)
            self.last_bot_message.pop(key, None)

    def add_turn(self, key: ConversationKey, turn: ChatTurn) -> None:
        if not isinstance(key, ConversationKey):
            raise TypeError("scoped_history_requires_conversation_key")
        if not isinstance(turn, ChatTurn):
            raise TypeError("scoped_history_requires_chat_turn")
        validated = prepare_history(
            (turn,),
            max_turns=1,
            max_chars=4_000,
        )
        if not validated:
            return
        self._clean_old_messages(key)
        stored = _StoredTurn(validated[0], self._now())
        self.threads[key].append(stored)
        self.threads[key] = self.threads[key][-self.max_history :]
        if stored.turn.role == "assistant":
            self.last_bot_message[key] = stored.timestamp

    def get_prompt_history(
        self,
        key: ConversationKey,
        *,
        limit: int = 10,
        exclude_source_message_id: int | None = None,
    ) -> tuple[ChatTurn, ...]:
        if not isinstance(key, ConversationKey):
            raise TypeError("scoped_history_requires_conversation_key")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("invalid_history_limit")
        if exclude_source_message_id is not None and (
            isinstance(exclude_source_message_id, bool)
            or not isinstance(exclude_source_message_id, int)
        ):
            raise ValueError("invalid_source_message_id")
        self._clean_old_messages(key)
        turns: list[ChatTurn] = []
        for value in self.threads.get(key, ()):
            stored = self._coerce_entry(value)
            if stored is None:
                continue
            if (
                exclude_source_message_id is not None
                and stored.turn.source_message_id
                == exclude_source_message_id
            ):
                continue
            turns.append(stored.turn)
        return prepare_history(tuple(turns[-limit:]))

    def add_message(
        self,
        channel_id,
        user_id,
        username,
        content,
        is_bot=False,
    ) -> None:
        self._clean_old_messages(channel_id)
        now = self._now()
        entry = {
            "user_id": user_id,
            "username": username,
            "content": content,
            "is_bot": is_bot,
            "timestamp": now,
        }
        self.threads[channel_id].append(entry)
        self.threads[channel_id] = self.threads[channel_id][
            -self.max_history :
        ]
        if is_bot:
            self.last_bot_message[channel_id] = now

    def get_channel_messages(self, channel_id, limit=6):
        self._clean_old_messages(channel_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("invalid_history_limit")
        result = []
        for value in self.threads.get(channel_id, ())[-limit:]:
            stored = self._coerce_entry(value)
            if stored is None:
                continue
            result.append(
                {
                    "user_id": stored.legacy_user_id,
                    "username": stored.legacy_username
                    or (
                        "Inebotten"
                        if stored.turn.role == "assistant"
                        else "User"
                    ),
                    "content": stored.turn.content,
                    "is_bot": stored.turn.role == "assistant",
                    "timestamp": stored.timestamp,
                    "source_message_id": stored.turn.source_message_id,
                }
            )
        return result

    def get_context(self, channel_id, limit=5):
        channel_or_key = channel_id
        if isinstance(channel_or_key, ConversationKey):
            turns = self.get_prompt_history(channel_or_key, limit=limit)
            return "\n".join(
                f"{'Bot' if turn.role == 'assistant' else 'User'}: "
                f"{turn.content}"
                for turn in turns
            )
        messages = self.get_channel_messages(channel_or_key, limit=limit)
        return "\n".join(
            f"{'Bot' if item['is_bot'] else item.get('username', 'User')}: "
            f"{item['content']}"
            for item in messages
        )

    def wants_dashboard(self, content):
        content_lower = content.lower()
        if re.search(r"\bhva er\b", content_lower) and not re.search(
            r"\b(været|status|værmelding)\b",
            content_lower,
        ):
            return False
        words = set(re.findall(r"\b\w+\b", content_lower))
        for keyword in self.DASHBOARD_KEYWORDS:
            if " " in keyword:
                if keyword in content_lower:
                    return True
            elif keyword in words:
                return True
        return False

    def is_small_talk(self, content):
        if self.wants_dashboard(content):
            return False
        content_lower = content.lower().strip()
        for pattern in self.SMALL_TALK_PATTERNS:
            if re.search(pattern, content_lower):
                return True
        if len(content_lower) < 15 and any(
            word in content_lower
            for word in ["hei", "hallo", "halla", "morn", "kveld"]
        ):
            return True
        return False

    def should_show_dashboard(self, content, channel_id):
        channel_or_key = channel_id
        if self.wants_dashboard(content):
            return True, "explicit_request"
        if self.is_small_talk(content):
            return False, "small_talk"
        self._clean_old_messages(channel_or_key)
        cutoff = self._now() - timedelta(minutes=10)
        recent_user_turns = 0
        for value in self.threads.get(channel_or_key, ()):
            stored = self._coerce_entry(value)
            if (
                stored is not None
                and stored.turn.role == "user"
                and stored.timestamp > cutoff
            ):
                recent_user_turns += 1
        if recent_user_turns > 1:
            return False, "ongoing_conversation"
        return False, "default"

    def get_conversation_summary(self, channel_id):
        channel_or_key = channel_id
        if isinstance(channel_or_key, ConversationKey):
            turns = self.get_prompt_history(channel_or_key, limit=10)
            contents = [
                turn.content
                for turn in turns
                if turn.role == "user"
            ][-3:]
        else:
            contents = [
                str(item["content"])
                for item in self.get_channel_messages(
                    channel_or_key,
                    limit=self.max_history,
                )
                if not item["is_bot"]
            ][-3:]
        if not contents:
            return None
        topics = []
        for raw_content in contents:
            content = raw_content.lower()
            if "rbk" in content or "rosenborg" in content:
                topics.append("RBK")
            if "vær" in content:
                topics.append("været")
            if "kalender" in content or "plan" in content:
                topics.append("planer")
        return list(dict.fromkeys(topics)) if topics else None


_context_manager = None


def get_context_manager():
    global _context_manager
    if _context_manager is None:
        _context_manager = ConversationContext()
    return _context_manager


if __name__ == "__main__":
    ctx = ConversationContext()
    test_messages = [
        ("Hei!", "small_talk"),
        ("Hvordan går det?", "small_talk"),
        ("Hva er været i dag?", "dashboard"),
        ("Vis meg kalenderen", "dashboard"),
        ("Hva synes du om RBK?", "small_talk"),
        ("Takk for hjelpen!", "small_talk"),
    ]
    print("Intent detection tests:")
    for msg, expected in test_messages:
        is_small = ctx.is_small_talk(msg)
        wants_dash = ctx.wants_dashboard(msg)
        result = "small_talk" if is_small else (
            "dashboard" if wants_dash else "other"
        )
        status = "✓" if result == expected else "✗"
        print(f"{status} '{msg}' -> {result} (expected: {expected})")
