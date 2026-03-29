#!/usr/bin/env python3
"""
BaseCog - Foundation class for all Cogs in the Inebotten Discord bot.

Provides shared utilities common to all Cogs:
- Access to rate limiter
- Access to localization
- Unified response methods
- Rate limit checking helpers

This class should be inherited by all new Cogs.
"""

import discord
from discord.ext import commands


class BaseCog(commands.Cog):
    """
    Base Cog class providing shared utilities for all feature Cogs.

    All Cogs in the refactored architecture should inherit from this class
    to ensure consistent access to shared state like rate limiting and
    localization.
    """

    def __init__(self, bot):
        """
        Initialize the BaseCog with shared bot state.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot

    @property
    def rate_limiter(self):
        """Access the rate limiter from bot instance."""
        return getattr(self.bot, "rate_limiter", None)

    @property
    def localization(self):
        """Access the localization system from bot instance."""
        return getattr(self.bot, "localization", None)

    async def respond(self, ctx, content, *, reply=True):
        """
        Send a response to a message.

        Handles DM, Group DM, and Guild channels consistently.

        Args:
            ctx: Message context
            content: Response content to send
            reply: Whether to reply to the message (vs send new message)
        """
        if reply:
            await ctx.reply(content)
        else:
            await ctx.send(content)

    async def check_rate_limit(self):
        """
        Check if the bot can send a response.

        Returns:
            tuple: (can_send: bool, reason: str or None)
        """
        if self.rate_limiter:
            return self.rate_limiter.can_send()
        return True, None

    async def wait_if_needed(self):
        """
        Wait if rate limit requires it.

        Returns:
            bool: True if can proceed, False if should drop
        """
        if self.rate_limiter:
            return await self.rate_limiter.wait_if_needed()
        return True

    def get_channel_type(self, channel):
        """
        Determine the channel type.

        Args:
            channel: Discord channel object

        Returns:
            str: DM, GROUP_DM, GUILD_TEXT, or UNKNOWN
        """
        if hasattr(channel, "type"):
            if channel.type == discord.ChannelType.private:
                return "DM"
            elif channel.type == discord.ChannelType.group:
                return "GROUP_DM"
            elif hasattr(discord.ChannelType, "guild_text"):
                if channel.type == discord.ChannelType.guild_text:
                    return "GUILD_TEXT"
            return "UNKNOWN"
        return "UNKNOWN"
