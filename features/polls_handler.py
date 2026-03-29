#!/usr/bin/env python3
"""
PollsHandler - Handles poll creation and voting for the selfbot.

Commands:
- Create polls with options
- Vote on active polls
"""

from typing import Dict, Any

from features.base_handler import BaseHandler


class PollsHandler(BaseHandler):
    """Handler for poll-related commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.poll = monitor.poll

    async def handle_poll(self, message, poll_cmd: Dict[str, Any]) -> None:
        """
        Handle poll creation.

        Args:
            message: The Discord message
            poll_cmd: Parsed poll command with 'question' and 'options'
        """
        try:
            guild_id = self.get_guild_id(message)
            lang = poll_cmd.get("lang", self.loc.current_lang)

            poll = self.poll.create_poll(
                guild_id=guild_id,
                question=poll_cmd["question"],
                options=poll_cmd["options"],
                created_by=message.author.name,
            )

            response_text = self.poll.format_poll(poll, lang)
            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error creating poll: {e}")

    async def handle_vote(self, message, vote: Dict[str, Any]) -> None:
        """
        Handle voting on polls.

        Args:
            message: The Discord message
            vote: Parsed vote with 'option_index'
        """
        try:
            guild_id = self.get_guild_id(message)
            lang = self.loc.current_lang

            # Get active polls
            active_polls = self.poll.get_active_polls(guild_id)

            if not active_polls:
                response_text = self.loc.t("no_active_polls") + " 📊"
            else:
                # Vote on the most recent poll
                poll = active_polls[-1]
                success, msg = self.poll.vote(
                    guild_id,
                    poll["id"],
                    vote["option_index"],
                    message.author.id,
                    message.author.name,
                )

                if success:
                    response_text = self.loc.t("vote_registered", num=vote["option_index"])
                else:
                    response_text = self.loc.t("vote_error", error=msg)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling vote: {e}")
