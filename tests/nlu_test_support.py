"""Shared deterministic support for offline natural-language unit tests.

The helpers in this module intentionally construct only inert value objects and
``AsyncMock`` send surfaces.  They never create a Discord client or open a
socket.
"""

from __future__ import annotations

from datetime import datetime
from itertools import count
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import discord

from ai.action_schema import ActionProposal
from cal_system.temporal_resolver import TemporalResolver
from core.action_bridge import ActionBridgeContext
from core.message_context import (
    ConversationKey,
    ResolvedMention,
    RoutingContext,
)
from core.utterance import normalize_utterance


FIXED_NOW = datetime(
    2026,
    7,
    14,
    12,
    0,
    tzinfo=ZoneInfo("Europe/Oslo"),
)


def routing_context(*, mentions=()) -> RoutingContext:
    return RoutingContext(
        key=ConversationKey(guild_id=1, channel_id=10, user_id=20),
        author=ResolvedMention(20, "Testbruker"),
        mentions=tuple(mentions),
    )


def proposal_for(
    action,
    slots,
    *,
    confidence=0.91,
    reply="",
    clarification=None,
) -> ActionProposal:
    return ActionProposal(
        action=action,
        confidence=confidence,
        slots=MappingProxyType(dict(slots)),
        reply=reply,
        clarification=clarification,
    )


def bridge_context(
    *,
    utterance=None,
    mentions=(),
    reference_time=FIXED_NOW,
    deterministic_route=None,
    active_poll_count=0,
    active_poll_id=None,
    semantic_action_allowed=True,
) -> ActionBridgeContext:
    return ActionBridgeContext(
        utterance=utterance or normalize_utterance("utfør handlingen"),
        routing=routing_context(mentions=mentions),
        reference_time=reference_time,
        temporal_resolver=TemporalResolver(),
        deterministic_route=deterministic_route,
        active_poll_count=active_poll_count,
        active_poll_id=active_poll_id,
        semantic_action_allowed=semantic_action_allowed,
    )


def ready_confirmation(store, key, route, summary, guard=None):
    draft = store.begin_confirmation(
        key,
        route,
        summary,
        target_guard=guard,
    )
    ready = store.activate_presentation(draft)
    assert ready is not None
    return ready


def ready_choices(store, key, routes, summary, guards):
    draft = store.begin_choices(
        key,
        routes,
        summary,
        target_guards=guards,
    )
    ready = store.activate_presentation(draft)
    assert ready is not None
    return ready


class OfflineMessageFactory:
    """Build socket-free Discord-shaped messages for adapter tests."""

    BOT_USER_ID = 999
    AUTHOR_USER_ID = 20
    GUILD_ID = 1
    GUILD_CHANNEL_ID = 10
    DM_CHANNEL_ID = 11

    def __init__(self, *, first_message_id: int = 10_000):
        self._message_ids = count(first_message_id)
        self.bot_user = discord.Object(id=self.BOT_USER_ID)

    @staticmethod
    def _author() -> SimpleNamespace:
        return SimpleNamespace(
            id=OfflineMessageFactory.AUTHOR_USER_ID,
            name="Testbruker",
            display_name="Testbruker",
            bot=False,
        )

    def _message(
        self,
        content: str,
        *,
        mentions: tuple[discord.Object, ...],
        guild: bool,
    ) -> SimpleNamespace:
        if not isinstance(content, str):
            raise TypeError("message content must be str")

        author = self._author()
        channel = SimpleNamespace(
            id=self.GUILD_CHANNEL_ID if guild else self.DM_CHANNEL_ID,
            name="testkanal" if guild else None,
            recipient=None if guild else author,
            send=AsyncMock(name="offline_channel_send"),
        )
        guild_value: SimpleNamespace | None = None
        if guild:
            guild_value = SimpleNamespace(id=self.GUILD_ID, name="Testserver")

        return SimpleNamespace(
            id=next(self._message_ids),
            content=content,
            raw_content=content,
            clean_content=content,
            guild=guild_value,
            channel=channel,
            author=author,
            mentions=list(mentions),
            role_mentions=[],
            mention_everyone=False,
            attachments=[],
            created_at=FIXED_NOW,
            reply=AsyncMock(name="offline_message_reply"),
        )

    def mentioned_message(
        self,
        text: str,
        *,
        guild: bool = True,
    ) -> SimpleNamespace:
        """Return a message with a leading invocation and the bot mention."""

        return self._message(
            f"<@{self.BOT_USER_ID}> {text}",
            mentions=(self.bot_user,),
            guild=guild,
        )

    def untagged_message(
        self,
        text: str,
        *,
        guild: bool = True,
    ) -> SimpleNamespace:
        """Return a message with no bot mention or content rewriting."""

        return self._message(text, mentions=(), guild=guild)


__all__ = [
    "FIXED_NOW",
    "OfflineMessageFactory",
    "bridge_context",
    "proposal_for",
    "ready_choices",
    "ready_confirmation",
    "routing_context",
]
