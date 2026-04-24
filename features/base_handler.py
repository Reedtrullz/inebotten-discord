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
from typing import Optional, Union
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
        try:
            if isinstance(message.channel, (discord.DMChannel, discord.GroupChannel)):
                sent = await message.channel.send(content)
            else:
                sent = await message.reply(content, mention_author=mention_author)

            # Record successful send
            self.rate_limiter.record_sent()
            if hasattr(self.monitor, 'response_count'):
                self.monitor.response_count += 1

            return sent
        except discord.errors.Forbidden:
            self.logger.warning("Forbidden: Cannot send message in this channel")
            self.rate_limiter.record_failure()
        except discord.errors.HTTPException as e:
            self.logger.error(f"HTTP error sending message: {e}")
            self.rate_limiter.record_failure(is_rate_limit=(e.status == 429))
        except Exception as e:
            self.logger.error(f"Error sending response: {e}")
            self.rate_limiter.record_failure()

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
