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

    async def handle_poll_list(self, message) -> None:
        """
        Handle listing active polls.

        Args:
            message: The Discord message
        """
        try:
            guild_id = self.get_guild_id(message)
            active_polls = self.poll.get_active_polls(guild_id)

            if not active_polls:
                response_text = self.loc.t("no_active_polls")
            else:
                lines = [self.loc.t("poll_list_title")]
                lines.append("")
                for i, poll in enumerate(active_polls, start=1):
                    lines.append(self.loc.t("poll_list_item", num=i, question=poll.get("question", "?")))
                lines.append("")
                lines.append(self.loc.t("poll_list_hint"))
                response_text = "\n".join(lines)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error listing polls: {e}")

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
                created_by_id=message.author.id,
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

            option_index = (
                vote.get("option_index")
                if isinstance(vote, dict)
                else int(vote)
            )

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
                    option_index,
                    message.author.id,
                    message.author.name,
                )

                if success:
                    response_text = self.loc.t("vote_registered", num=option_index)
                else:
                    response_text = self.loc.t("vote_error", error=msg)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling vote: {e}")

    async def handle_poll_edit(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle poll editing.

        Args:
            message: The Discord message
            payload: Dict with 'poll_id' and optionally 'question' and/or 'options'
        """
        try:
            guild_id = self.get_guild_id(message)
            poll_id = payload.get("poll_id")
            question = payload.get("question")
            options = payload.get("options")

            success, result = self.poll.edit_poll(
                guild_id=guild_id,
                poll_id=poll_id,
                user_id=message.author.id,
                username=message.author.name,
                question=question,
                options=options,
            )

            if success:
                response_text = self.loc.t("poll_edited") + "\n\n" + self.poll.format_poll(result)
            else:
                if result == "Poll not found":
                    response_text = self.loc.t("poll_not_found")
                elif result == "Poll is closed":
                    response_text = self.loc.t("poll_closed_already")
                elif "owner" in result.lower():
                    response_text = self.loc.t("poll_not_owner")
                else:
                    response_text = result

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error editing poll: {e}")

    async def handle_poll_delete(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle poll deletion.

        Args:
            message: The Discord message
            payload: Dict with 'poll_id'
        """
        try:
            guild_id = self.get_guild_id(message)
            poll_id = payload.get("poll_id")

            success, result = self.poll.delete_poll(
                guild_id=guild_id,
                poll_id=poll_id,
                user_id=message.author.id,
                username=message.author.name,
            )

            if success:
                response_text = self.loc.t("poll_deleted")
            else:
                if result == "Poll not found":
                    response_text = self.loc.t("poll_not_found")
                elif "owner" in result.lower():
                    response_text = self.loc.t("poll_not_owner")
                else:
                    response_text = result

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error deleting poll: {e}")

    async def handle_poll_close(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle poll closing.

        Args:
            message: The Discord message
            payload: Dict with 'poll_id'
        """
        try:
            guild_id = self.get_guild_id(message)
            poll_id = payload.get("poll_id")

            success, result = self.poll.close_poll(
                guild_id=guild_id,
                poll_id=poll_id,
                user_id=message.author.id,
                username=message.author.name,
            )

            if success:
                response_text = self.loc.t("poll_closed") + "\n\n" + self.poll.format_poll(result)
            else:
                if result == "Poll not found":
                    response_text = self.loc.t("poll_not_found")
                elif result == "Poll is already closed":
                    response_text = self.loc.t("poll_closed_already")
                elif "owner" in result.lower():
                    response_text = self.loc.t("poll_not_owner")
                else:
                    response_text = result

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error closing poll: {e}")
