#!/usr/bin/env python3
"""
AICog - AI response generation and fallback handling.

This Cog handles the fallback behavior when no command matches:
- Checks if user wants dashboard vs chat
- Uses Hermes connector for AI responses
- Falls back to dashboard with weather, calendar, etc.
- Manages conversation history and user memory.
"""

import asyncio
import logging
from discord.ext import commands
from features._base import BaseCog

logger = logging.getLogger(__name__)


class AICog(BaseCog):
    """
    AI response generator for the bot.

    This Cog provides the fallback "AI chat" functionality when
    no specific command matches. It integrates with Hermes/LM Studio
    for local AI generation.
    """

    def __init__(
        self,
        bot,
        hermes_connector,
        response_generator,
        user_memory,
        conversation,
        conv_gen,
        get_system_prompt,
    ):
        super().__init__(bot)
        self.hermes = hermes_connector
        self.response_gen = response_generator
        self.user_memory = user_memory
        self.conversation = conversation
        self.conv_gen = conv_gen
        self.get_system_prompt = get_system_prompt

        # Track responses
        self.response_count = 0

    async def send_ai_response(self, message):
        """Generate and send AI response."""
        try:
            # Determine channel type
            channel = message.channel
            channel_type = self.get_channel_type(channel)

            # Check if should show dashboard
            should_show = self.conversation.should_show_dashboard(message.author.id)

            # Add message to conversation
            self.conversation.add_message(message.author.id, message.content, "user")

            # Get user context for prompt
            user_data = self.user_memory.get_user(
                message.author.id, message.author.name
            )
            user_context = {
                "username": user_data.get("username"),
                "location": user_data.get("location"),
                "interests": user_data.get("interests", [])[:3],
                "conversation_count": user_data.get("conversation_count", 0),
            }

            # Build system prompt if no custom one
            system_prompt = self.get_system_prompt(user_context=user_context)

            # Try HermesAI
            success, response = await self.hermes.generate_response(
                message_content=message.content,
                author_name=message.author.name,
                channel_type=channel_type,
                is_mention=True,
                system_prompt=system_prompt,
            )

            if success:
                response_text = response
            else:
                # Fallback to template
                response_text = response

            # Send reply
            await message.reply(response_text)

            # Record sent
            if self.rate_limiter:
                self.rate_limiter.record_sent()

            self.response_count += 1

            # Add bot response to conversation
            self.conversation.add_message(message.author.id, response_text, "assistant")

            # Update user memory
            self.user_memory.update_last_interaction(
                message.author.id, topic=None, username=message.author.name
            )

            return True

        except Exception as e:
            logger.error(f"Error sending AI response: {e}")
            return False


async def setup(
    bot,
    hermes_connector=None,
    response_generator=None,
    user_memory=None,
    conversation=None,
    conv_gen=None,
    get_system_prompt=None,
):
    """
    Setup function for AICog.

    Requires passing in all the dependencies that were previously
    managed by MessageMonitor.
    """
    cog = AICog(
        bot,
        hermes_connector or bot.hermes,
        response_generator or getattr(bot, "response_gen", None),
        user_memory or bot.user_memory,
        conversation or bot.conversation,
        conv_gen or bot.conv_gen,
        get_system_prompt or bot.get_system_prompt,
    )
    await bot.add_cog(cog)
    return cog
