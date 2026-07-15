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

import asyncio
import discord
import re
from typing import Optional

from core.dispatch_result import (
    DeliveryState,
    MessageSendCancelled,
    MessageSendResult,
)
from core.send_receipt import _settle_owned_send, record_send_result
from utils.logger import LoggerMixin


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
        self.loc = monitor.loc
        self.client = monitor.client

    async def send_response(
        self,
        message: discord.Message,
        content: str,
        mention_author: bool = False
    ) -> bool | None:
        """
        Compatibility projection over the canonical tri-state sender.

        Args:
            message: The original message to respond to
            content: Response content to send
            mention_author: Retained for one-release call compatibility.  The
                canonical sender always disables author mentions.

        Returns:
            True only when Discord delivery is definite, otherwise None.
        """
        del mention_author
        result = await self.send_response_result(message, content)
        return True if result.state is DeliveryState.DELIVERED else None

    async def send_response_result(
        self,
        message: discord.Message,
        content: str,
    ) -> MessageSendResult:
        """Delegate once to the monitor-owned sender and settle cancellation."""

        sender = getattr(self.monitor, "discord_sender", None)
        adapter = getattr(sender, "send_result", None)
        if not callable(adapter):
            result = MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "missing_adapter",
            )
            record_send_result(result)
            return result

        try:
            awaitable = adapter(message, content)
        except Exception:
            result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_exception",
            )
            record_send_result(result)
            return result
        if not asyncio.iscoroutine(awaitable):
            result = MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "missing_adapter",
            )
            record_send_result(result)
            return result

        owned_send = asyncio.create_task(awaitable)
        try:
            result = await _settle_owned_send(owned_send)
        except MessageSendCancelled as exc:
            self._record_delivered_response(
                message,
                content,
                exc.result,
            )
            raise
        self._record_delivered_response(message, content, result)
        return result

    def _record_delivered_response(
        self,
        message: discord.Message,
        content: str,
        result: MessageSendResult,
    ) -> None:
        if result.state is not DeliveryState.DELIVERED:
            return
        response_count = getattr(self.monitor, "response_count", None)
        if isinstance(response_count, int) and not isinstance(
            response_count,
            bool,
        ):
            self.monitor.response_count = response_count + 1

        recorder = getattr(self.monitor, "record_outbound", None)
        if not callable(recorder):
            return
        try:
            recorder(message, content)
        except Exception:
            # Conversation history is best-effort bookkeeping. Discord has
            # already committed the response, so a recording failure must not
            # rewrite definite delivery truth.
            self.logger.warning(
                "Could not record outbound conversation turn"
            )

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
