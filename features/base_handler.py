#!/usr/bin/env python3
"""
BaseHandler - Foundation class for all feature handlers in the Inebotten Discord selfbot.

Provides shared utilities common to all handlers:
- Access to rate limiter
- Access to localization
- Unified response methods (handles DM/Group DM/Guild channels)
- Rate limit checking helpers
- Logging utilities

This class should be inherited by all new handlers.
"""

import discord
import re
import json
import secrets
import time
from typing import Optional, Union
from utils.logger import LoggerMixin
from core.request_context import current_request, request_localization
from core.outbound_sender import monitor_sender


class BaseHandler(LoggerMixin):
    """
    Base handler class providing shared utilities for all feature handlers.

    All handlers in the selfbot architecture should inherit from this class
to ensure consistent access to shared state like rate limiting and
    localization.
    """

    def __init__(self, monitor):
        """
        Initialize the BaseHandler with shared state from MessageMonitor.

        Args:
            monitor: The MessageMonitor instance that owns this handler
        """
        self.monitor = monitor
        self.rate_limiter = monitor.rate_limiter
        self._localization = monitor.loc
        self.client = monitor.client
        self._shown_lists = {}
        self._delete_choices = {}

    def _list_actor(self, message):
        actor = current_request()
        if actor:
            return actor.user_id, actor.channel_id, actor.guild_id, actor.channel_kind
        return str(message.author.id), str(message.channel.id), str(self.get_guild_id(message)), 'message'

    @staticmethod
    def _list_digest(records):
        return json.dumps(records, sort_keys=True, ensure_ascii=False)

    def remember_list(self, message, records, indices):
        now = time.monotonic()
        self._shown_lists = {key: entry for key, entry in self._shown_lists.items() if entry[0] > now}
        self._shown_lists[self._list_actor(message)] = (now + 300, self._list_digest(records), frozenset(indices))
        while len(self._shown_lists) > 128:
            self._shown_lists.pop(next(iter(self._shown_lists)))

    def displayed_index(self, message, records, index):
        shown = self._shown_lists.get(self._list_actor(message))
        if (not shown or shown[0] <= time.monotonic() or shown[1] != self._list_digest(records)
                or type(index) is not int or index not in shown[2] or not 1 <= index <= len(records)):
            raise ValueError('Listen mangler, er endret eller er utløpt. Vis listen på nytt i denne kanalen før du velger nummer.')
        return index

    async def reviewed_delete(self, message, records, index, label, title_key):
        cleaned = re.sub(r'<@!?\d+>|@inebotten', '', message.content, flags=re.I).strip()
        match = re.fullmatch(rf'bekreft sletting {re.escape(label)} ([A-Za-z0-9_-]{{24}})', cleaned, re.I)
        now = time.monotonic()
        self._delete_choices = {token: entry for token, entry in self._delete_choices.items() if entry[0] > now}
        if match:
            entry = self._delete_choices.get(match.group(1))
            if not entry or entry[1] != self._list_actor(message) or entry[2] != self._list_digest(records):
                raise ValueError('Sletteforslaget mangler, er utløpt eller er endret. Vis listen på nytt og lag et nytt forslag.')
            self._delete_choices.pop(match.group(1))
            return entry[3]
        index = self.displayed_index(message, records, index)
        token = secrets.token_urlsafe(18)
        self._delete_choices[token] = (now + 300, self._list_actor(message), self._list_digest(records), index)
        while len(self._delete_choices) > 32:
            self._delete_choices.pop(next(iter(self._delete_choices)))
        title = records[index - 1][title_key]
        title = title if len(title) <= 200 else title[:199] + '…'
        sent = await self.send_response(message, f'Slett nummer {index}: **{title}**? Dette kan ikke angres her. '
            f'Bekreft innen fem minutter med `@inebotten bekreft sletting {label} {token}`. Ingenting er slettet ennå.')
        if sent is None:
            self._delete_choices.pop(token, None)
        return None

    @property
    def loc(self):
        return request_localization(self._localization)

    @property
    def request_context(self):
        return current_request()

    async def send_response(
        self,
        message: discord.Message,
        content: str,
        mention_author: bool = False
    ) -> Optional[discord.Message]:
        """
        Send a response to a message with proper channel type handling.

        Handles DM, Group DM, and Guild channels consistently.
        Also records rate limiter stats automatically.

        Args:
            message: The original message to respond to
            content: Response content to send
            mention_author: Whether to mention the author (only for guild channels)

        Returns:
            The sent message object, or None if failed
        """
        result = await monitor_sender(self.monitor).reply(message, content, mention_author=mention_author)
        if result.status == 'delivered' and result.reason_code == 'remote_message':
            if hasattr(self.monitor, 'response_count'):
                self.monitor.response_count += 1
            return result.message
        self.logger.warning('Response delivery: %s (%s)', result.status, result.reason_code)
        return None

    async def check_rate_limit(self) -> tuple[bool, Optional[str]]:
        """
        Check if the bot can send a response.

        Returns:
            tuple: (can_send: bool, reason: str or None)
        """
        return self.rate_limiter.can_send()

    async def wait_if_needed(self) -> bool:
        """
        Wait if rate limit requires it.

        Returns:
            bool: True if can proceed, False if should drop
        """
        return await self.rate_limiter.wait_if_needed()

    def get_channel_type(self, channel) -> str:
        """
        Determine the channel type.

        Args:
            channel: Discord channel object

        Returns:
            str: DM, GROUP_DM, GUILD_TEXT, or UNKNOWN
        """
        if isinstance(channel, discord.DMChannel):
            return "DM"
        elif isinstance(channel, discord.GroupChannel):
            return "GROUP_DM"
        elif isinstance(channel, discord.TextChannel):
            return "GUILD_TEXT"
        else:
            return "UNKNOWN"

    def get_guild_id(self, message: discord.Message) -> int:
        """
        Get the guild ID from a message.
        For DMs/Group DMs, returns the channel ID as the "guild" identifier.

        Args:
            message: Discord message

        Returns:
            int: Guild ID or channel ID for DMs
        """
        return message.guild.id if message.guild else message.channel.id

    def extract_number(self, content: str) -> Optional[int]:
        """
        Extract the first number from a message content.
        Removes Discord mentions first.

        Args:
            content: Message content

        Returns:
            int or None: The extracted number
        """
        # Remove Discord mentions
        content_clean = re.sub(r"<@!?\d+>", "", content).strip()

        # Extract number
        num_match = re.search(r"\b(\d+)\b", content_clean)
        if num_match:
            return int(num_match.group(1))
        return None

    def log(self, message: str) -> None:
        """
        Log a message with the handler name prefix.
        Deprecated: Use self.logger instead

        Args:
            message: Message to log
        """
        self.logger.info(message)

    def get_stats(self) -> dict:
        """
        Get handler statistics. Override in subclasses.

        Returns:
            dict: Handler statistics
        """
        return {"handler": self.__class__.__name__}
