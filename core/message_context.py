"""Resolved and authorized identity context for intent routing."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationKey:
    guild_id: int | None
    channel_id: int
    user_id: int


@dataclass(frozen=True, slots=True)
class ResolvedMention:
    user_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class RoutingContext:
    key: ConversationKey
    author: ResolvedMention
    mentions: tuple[ResolvedMention, ...] = ()
