"""Resolved and authorized identity context for intent routing."""

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class ConversationKey:
    guild_id: int | None
    channel_id: int
    user_id: int


def domain_scope_id(key: ConversationKey) -> int:
    """Return the persisted domain bucket for a guild or DM conversation.

    Guild and channel snowflakes are globally unique.  Keeping the bare DM
    channel ID also preserves the bucket keys written by earlier releases.
    """

    return key.guild_id if key.guild_id is not None else key.channel_id


@dataclass(frozen=True, slots=True)
class ResolvedMention:
    user_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class RoutingContext:
    key: ConversationKey
    author: ResolvedMention
    mentions: tuple[ResolvedMention, ...] = ()


def conversation_key_from_message(message) -> ConversationKey:
    return ConversationKey(
        guild_id=(
            message.guild.id if message.guild is not None else None
        ),
        channel_id=message.channel.id,
        user_id=message.author.id,
    )


def strip_leading_bot_invocation(
    content: str,
    *,
    bot_user_id: int,
) -> str:
    """Remove one authorized leading bot invocation without crossing lines."""

    if not isinstance(content, str):
        raise TypeError("message_content_must_be_string")
    if isinstance(bot_user_id, bool) or not isinstance(bot_user_id, int):
        raise TypeError("bot_user_id_must_be_integer")
    invocation = re.compile(
        rf"^[ \t]*(?:<@!?{bot_user_id}>|@inebotten(?!\w))"
        rf"[ \t]*[,;:]?[ \t]*",
        re.IGNORECASE,
    )
    return invocation.sub("", content, count=1)


def routing_context_from_message(
    message,
    *,
    bot_user_id: int | None = None,
) -> RoutingContext:
    author_name = (
        getattr(message.author, "display_name", None)
        or getattr(message.author, "name", None)
        or str(message.author.id)
    )
    seen: set[int] = set()
    mentions: list[ResolvedMention] = []
    for mentioned in getattr(message, "mentions", ()):
        user_id = int(mentioned.id)
        if user_id == bot_user_id or user_id in seen:
            continue
        seen.add(user_id)
        display_name = (
            getattr(mentioned, "display_name", None)
            or getattr(mentioned, "name", None)
            or str(user_id)
        )
        mentions.append(ResolvedMention(user_id, display_name))
    return RoutingContext(
        key=conversation_key_from_message(message),
        author=ResolvedMention(int(message.author.id), author_name),
        mentions=tuple(mentions),
    )
