#!/usr/bin/env python3
"""
PollsHandler - Handles poll creation and voting for the selfbot.

Commands:
- Create polls with options
- Vote on active polls
"""

from typing import Dict, Any
import re

from features.base_handler import BaseHandler
from features.poll_manager import PollStorageError


class PollsHandler(BaseHandler):
    """Handler for poll-related commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.poll = monitor.poll

    async def _refresh_poll_post(self, poll):
        try:
            await self.monitor.refresh_poll_post(poll)
        except Exception as e:
            self.log(f"Could not refresh poll post: {e}")

    async def handle_poll_list(self, message) -> None:
        """
        Handle listing active polls.

        Args:
            message: The Discord message
        """
        try:
            guild_id = self.get_guild_id(message)
            match = re.search(r'\bside (\d+)\b', message.content, re.I)
            page = max(1, int(match.group(1))) if match else 1
            if self._is_results_command(message):
                closed_polls = self.poll.get_closed_polls(guild_id)
                if not closed_polls:
                    response_text = (
                        "Ingen lukkede avstemninger med resultater."
                    )
                else:
                    page = min(page, len(closed_polls))
                    response_text = "🔒 Lukket\n" + self.poll.format_poll(closed_polls[page - 1])
                    response_text += f'\n{len(closed_polls)} resultater · side {page}/{len(closed_polls)}. Neste: `@inebotten poll resultater side {page + 1}`.'
                await self.send_response(message, response_text)
                return

            active_polls = self.poll.get_active_polls(guild_id)
            page = min(page, max(1, (len(active_polls) + 7) // 8))
            offset = (page - 1) * 8

            if not active_polls:
                response_text = self.loc.t("no_active_polls")
            else:
                lines = [self.loc.t("poll_list_title")]
                lines.append("")
                for i, poll in enumerate(active_polls[offset:offset + 8], start=offset + 1):
                    votes = sum(len(opt["votes"]) for opt in poll["options"])
                    vote_word = "stemme" if votes == 1 else "stemmer"
                    question = poll.get('question', '?')
                    question = question if len(question) <= 100 else question[:99] + '…'
                    lines.append(f"{i}. {question} ({votes} {vote_word}) · #{poll['id']}")
                lines.append("")
                lines.append(self.loc.t("poll_list_hint"))
                lines.append(f'{len(active_polls)} aktive · side {page}/{max(1, (len(active_polls) + 7) // 8)}. Neste: `@inebotten polls side {page + 1}`.')
                response_text = "\n".join(lines)

            if await self.send_response(message, response_text) is not None:
                self.remember_list(message, active_polls, range(offset + 1, min(len(active_polls), offset + 8) + 1))

        except Exception as e:
            self.log(f"Error listing polls: {e}")
            await self.send_response(message, 'Listen kunne ikke hentes. Prøv `@inebotten polls` igjen.')

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
            sent = await self.send_response(message, response_text)
            if sent is not None:
                try:
                    self.poll.set_message_id(guild_id, poll["id"], sent.id, sent.channel.id)
                except Exception as e:
                    self.log(f"Could not link poll to message: {e}")
                for option in poll["options"]:
                    try:
                        await sent.add_reaction(option["emoji"])
                    except Exception as e:
                        self.log(f"Could not add poll reaction: {e}")

        except PollStorageError:
            await self.send_response(message, "❌ Kunne ikke lagre avstemningen; ingen opprettelse er bekreftet.")
        except ValueError:
            await self.send_response(message, 'Bruk et spørsmål og 2–10 ulike alternativer: `@inebotten poll Middag? / Pizza / Burger`. Ingen avstemning er opprettet.')
        except Exception as e:
            self.log(f"Error creating poll: {e}")
            await self.send_response(message, 'Avstemningen kunne ikke publiseres. Se `@inebotten polls` før du prøver igjen; bruk tekstkommandoen for å stemme.')

    async def handle_vote(self, message, vote: Dict[str, Any] | int) -> None:
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
            poll_ref = vote.get("poll_ref") if isinstance(vote, dict) else None
            if poll_ref is not None and self._resolve_poll_id(guild_id, poll_ref, message) is None:
                await self.send_response(message, self.loc.t('poll_not_found') + ' Bruk `@inebotten polls` for listen.')
                return

            # Get active polls
            active_polls = self.poll.get_active_polls(guild_id)

            if not active_polls:
                response_text = self.loc.t("no_active_polls") + " 📊"
            elif len(active_polls) > 1:
                poll_id = self._resolve_poll_id(guild_id, poll_ref, message)
                if poll_id is None:
                    lines = [
                        "📊 Det er flere aktive avstemninger. Stem med `@inebotten stem [avstemning] [tall]`, f.eks. `@inebotten stem 3 1`."
                    ]
                    for i, p in enumerate(active_polls[:8], 1):
                        votes = sum(len(opt["votes"]) for opt in p["options"])
                        vote_word = "stemme" if votes == 1 else "stemmer"
                        question = p.get('question', '?')
                        question = question if len(question) <= 100 else question[:99] + '…'
                        lines.append(f"{i}. {question} ({votes} {vote_word})")
                    lines.append(f'{len(active_polls)} aktive. Alle sider: `@inebotten polls`.')
                    if await self.send_response(message, "\n".join(lines)) is not None:
                        self.remember_list(message, active_polls, range(1, min(len(active_polls), 8) + 1))
                    return
                poll = next(p for p in active_polls if p["id"] == poll_id)
                success, msg = self.poll.vote(
                    guild_id,
                    poll["id"],
                    option_index,
                    message.author.id,
                    message.author.name,
                )
                if success:
                    fresh = self.poll.get_poll(guild_id, poll["id"])
                    if fresh is not None:
                        await self._refresh_poll_post(fresh)
                    response_text = self.loc.t("vote_registered", num=option_index)
                else:
                    response_text = self.loc.t("vote_error", error=self._poll_error(msg))
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
                    fresh = self.poll.get_poll(guild_id, poll["id"])
                    if fresh is not None:
                        await self._refresh_poll_post(fresh)
                    response_text = self.loc.t("vote_registered", num=option_index)
                else:
                    response_text = self.loc.t("vote_error", error=self._poll_error(msg))

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling vote: {e}")
            await self.send_response(message, str(e) + ' Bruk `@inebotten polls`.' if isinstance(e, ValueError) else 'Stemmen kunne ikke bekreftes. Se `@inebotten polls` og kontroller resultatet før du prøver igjen.')

    def _resolve_poll_id(self, guild_id, ref, message=None):
        """Resolve a poll reference to a poll_id. ref can be None, 'siste', or a 1-based index."""
        active_polls = self.poll.get_active_polls(guild_id)
        if not active_polls:
            return None
        if ref == "siste":
            return active_polls[-1]["id"]
        if ref is None:
            if len(active_polls) == 1:
                return active_polls[-1]["id"]
            return None
        if isinstance(ref, int) and 1 <= ref <= len(active_polls):
            if message is not None:
                self.displayed_index(message, active_polls, ref)
            return active_polls[ref - 1]["id"]
        if isinstance(ref, str):
            return next((poll['id'] for poll in active_polls if poll['id'] == ref.lstrip('#')), None)
        return None

    def _poll_target_response(self, guild_id, ref, action_label: str) -> str:
        active_polls = self.poll.get_active_polls(guild_id)
        if ref is None and len(active_polls) > 1:
            lines = [
                (
                    f"📊 Det er flere aktive avstemninger. Vis `@inebotten polls` før du bruker nummer, f.eks. "
                    f"`@inebotten {action_label} poll 1`, eller skriv `siste`."
                )
            ]
            for i, poll in enumerate(active_polls[:8], 1):
                question = poll.get('question', '?')
                question = question if len(question) <= 100 else question[:99] + '…'
                lines.append(f"{i}. {question}")
            lines.append(f'{len(active_polls)} aktive. Alle sider: `@inebotten polls`.')
            return "\n".join(lines)
        return self.loc.t("poll_not_found")

    @staticmethod
    def _is_results_command(message) -> bool:
        content = re.sub(r"<@!?\d+>", "", getattr(message, "content", "")).replace("@inebotten", "").strip()
        return bool(
            re.fullmatch(
                r"(?:poll results?|poll resultater|resultater poll|"
                r"resultater avstemning|vis resultater(?: for)? "
                r"(?:poll|avstemning)|avstemning resultater)(?: side \d+)?",
                content.strip(), flags=re.IGNORECASE,
            )
        )

    def _poll_error(self, error):
        if self.loc.current_lang == 'en':
            return error
        if 'expired' in error.lower():
            return 'Avstemningen er utløpt; den kan ikke endres eller motta stemmer.'
        if 'owner' in error.lower() or 'actor' in error.lower():
            return 'Bare avstemningens eier kan bekrefte denne endringen.'
        if 'stale' in error.lower() or 'preview' in error.lower():
            return 'Forhåndsvisningen er utløpt eller endret. Lag en ny forhåndsvisning.'
        if 'saved' in error.lower():
            return 'Endringen kunne ikke lagres; ingen endring er bekreftet.'
        if 'confirmation' in error.lower():
            return 'Denne valgendringen krever bekreftelse på nullstilling av stemmene.'
        return 'Avstemningsendringen er ugyldig eller utilgjengelig. Kontroller valg og status.'

    async def handle_poll_edit(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle poll editing.

        Args:
            message: The Discord message
            payload: Dict with 'target' (None, 'siste', or int index)
        """
        try:
            guild_id = self.get_guild_id(message)
            if payload.get("confirm_token"):
                success, result = self.poll.apply_poll_edit(
                    guild_id, None, message.author.id,
                    payload["confirm_token"],
                    confirm_reset=payload.get("confirm_reset", False),
                    username=message.author.name,
                )
                if success:
                    response_text = (
                        self.loc.t("poll_edited")
                        + "\n\n"
                        + self.poll.format_poll(result)
                    )
                else:
                    response_text = self._poll_error(result)
                await self.send_response(message, response_text)
                return

            target = payload.get("target")
            poll_id = self._resolve_poll_id(guild_id, target, message)
            if poll_id is None:
                await self.send_response(
                    message,
                    self._poll_target_response(guild_id, target, "endre"),
                )
                return

            changes = payload.get("changes", {})
            if not changes:
                response_text = (
                    "Skriv `endre poll N spørsmål: ...`, `etikett OPTION_ID: ...` for navn, eller `valg: A/B` for erstatning. "
                    "Strukturelle valgendringer krever `bekreft poll endring "
                    "TOKEN reset`."
                )
                await self.send_response(message, response_text)
                return

            preview = self.poll.preview_poll_edit(
                guild_id, poll_id, changes,
                message.author.id, message.author.name,
            )
            if not preview.get("ok"):
                response_text = self._poll_error(preview["error"])
            elif preview["requires_confirmation"]:
                labels = ", ".join(
                    option["text"] for option in preview["options"]
                )
                response_text = (
                    "Endringen vil nullstille stemmene (også ved like mange nye valg) "
                    f"(revisjon {preview['revision']}). "
                    f"Nye valg: {labels}. Forhåndsvisningen varer fem minutter. Bekreft med `@inebotten bekreft poll endring "
                    f"{preview['token']} reset`."
                )
            else:
                success, result = self.poll.apply_poll_edit(
                    guild_id, poll_id, message.author.id,
                    preview["token"],
                    username=message.author.name,
                )
                response_text = (
                    self.loc.t("poll_edited")
                    + "\n\n"
                    + self.poll.format_poll(result)
                    if success else self._poll_error(result)
                )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error editing poll: {e}")
            await self.send_response(message, str(e) + ' Bruk `@inebotten polls`.' if isinstance(e, ValueError) else 'Endringen kunne ikke lagres. Se `@inebotten polls` før du prøver igjen.')

    async def handle_poll_delete(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle poll deletion.

        Args:
            message: The Discord message
            payload: Dict with 'target' (None, 'siste', or int index)
        """
        try:
            guild_id = self.get_guild_id(message)
            target = payload.get("target")
            poll_id = self._resolve_poll_id(guild_id, target, message)
            if poll_id is None:
                await self.send_response(message, self._poll_target_response(guild_id, target, "slett"))
                return

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
                    response_text = self._poll_error(result)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error deleting poll: {e}")
            await self.send_response(message, str(e) + ' Bruk `@inebotten polls`.' if isinstance(e, ValueError) else 'Slettingen kunne ikke lagres. Se `@inebotten polls` før du prøver igjen.')

    async def handle_poll_close(self, message, payload: Dict[str, Any]) -> None:
        """
        Handle poll closing.

        Args:
            message: The Discord message
            payload: Dict with 'target' (None, 'siste', or int index)
        """
        try:
            guild_id = self.get_guild_id(message)
            target = payload.get("target")
            poll_id = self._resolve_poll_id(guild_id, target, message)
            if poll_id is None:
                await self.send_response(message, self._poll_target_response(guild_id, target, "lukk"))
                return

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
                    response_text = self._poll_error(result)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error closing poll: {e}")
            await self.send_response(message, str(e) + ' Bruk `@inebotten polls`.' if isinstance(e, ValueError) else 'Lukkingen kunne ikke lagres. Se `@inebotten polls` før du prøver igjen.')
