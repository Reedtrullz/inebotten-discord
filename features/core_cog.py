#!/usr/bin/env python3
"""
CoreCog - Core message routing and mention detection.

This Cog handles:
- Mention detection (is_mention)
- Channel type detection
- Message routing to appropriate handlers
- Stats tracking

This replaces the core routing logic previously in MessageMonitor.
"""

import discord
from discord.ext import commands
from features._base import BaseCog


class CoreCog(BaseCog):
    """
    Core Cog for message routing and mention detection.

    Handles the fundamental bot mention detection that drives all
    other feature Cogs.
    """

    def __init__(self, bot, bot_name="inebotten"):
        super().__init__(bot)
        self.bot_name = bot_name
        self.bot_mention = f"@{bot_name}"

        # Track mentions
        self.mention_count = 0

    def is_mention(self, message):
        """
        Check if message mentions the bot.

        Args:
            message: Discord message object

        Returns:
            bool: True if bot was mentioned
        """
        content = message.content.lower()

        # Check @inebotten
        if self.bot_mention.lower() in content:
            return True

        # Check Discord mention syntax
        if self.bot.user:
            mention_strings = [
                f"<@{self.bot.user.id}>",
                f"<@!{self.bot.user.id}>",
            ]
            for mention in mention_strings:
                if mention in message.content:
                    return True

        return False

    def get_channel_type(self, channel):
        """
        Determine channel type.

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
            else:
                return "GUILD_TEXT"
        return "UNKNOWN"


async def setup(bot):
    """Setup function for CoreCog."""
    await bot.add_cog(CoreCog(bot))
