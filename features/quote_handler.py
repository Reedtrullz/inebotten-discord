#!/usr/bin/env python3
"""
QuoteHandler - Handles quote list, update, and delete commands for the selfbot.

Commands:
- List all quotes
- Update a quote by index
- Delete a quote by index
"""

from features.base_handler import BaseHandler


class QuoteHandler(BaseHandler):
    """Handler for quote management commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.quote = monitor.quote

    def _extract_index_from_payload(self, payload) -> int | None:
        if isinstance(payload, dict):
            return payload.get("index")
        if isinstance(payload, int):
            return payload
        return None

    def _extract_text_from_payload(self, payload) -> str | None:
        if isinstance(payload, dict):
            return payload.get("text")
        return None

    def _extract_author_from_payload(self, payload) -> str | None:
        if isinstance(payload, dict):
            return payload.get("author")
        return None

    async def handle_quote_list(self, message) -> None:
        """List all quotes for the current guild with numbered indices."""
        try:
            guild_id = self.get_guild_id(message)
            quotes = self.quote.list_quotes(guild_id)

            if not quotes:
                # TODO(Task 12): Replace with localization key
                await self.send_response(message, "📭 Ingen sitater lagret ennå.")
                return

            lines = ["📚 **Sitater**"]
            for idx, q in enumerate(quotes, start=1):
                text = q.get("text", "")
                author = q.get("author", "Ukjent")
                lines.append(f"{idx}. \"{text}\" — {author}")

            await self.send_response(message, "\n".join(lines))

        except Exception as e:
            self.log(f"Error listing quotes: {e}")

    async def handle_quote_edit(self, message, payload) -> None:
        """
        Update a quote by index.

        Args:
            message: The Discord message
            payload: Parsed command with optional 'index', 'text', 'author'
        """
        try:
            guild_id = self.get_guild_id(message)
            index = self._extract_index_from_payload(payload)

            if index is None:
                index = self.extract_number(message.content)

            if index is None:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, "❌ Vennligst oppgi et sitatnummer å redigere."
                )
                return

            text = self._extract_text_from_payload(payload)
            author = self._extract_author_from_payload(payload)

            if text is None and author is None:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, "❌ Ingen endringer oppgitt. Send ny tekst eller forfatter."
                )
                return

            success = self.quote.update_quote(guild_id, index, text=text, author=author)

            if success:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, f"✏️ Sitat {index} er oppdatert."
                )
            else:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, f"❌ Fant ikke sitat {index}."
                )

        except Exception as e:
            self.log(f"Error editing quote: {e}")

    async def handle_quote_delete(self, message, payload) -> None:
        """
        Delete a quote by index.

        Args:
            message: The Discord message
            payload: Parsed command with optional 'index'
        """
        try:
            guild_id = self.get_guild_id(message)
            index = self._extract_index_from_payload(payload)

            if index is None:
                index = self.extract_number(message.content)

            if index is None:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, "❌ Vennligst oppgi et sitatnummer å slette."
                )
                return

            success = self.quote.delete_quote(guild_id, index)

            if success:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, f"🗑️ Sitat {index} er slettet."
                )
            else:
                # TODO(Task 12): Replace with localization key
                await self.send_response(
                    message, f"❌ Fant ikke sitat {index}."
                )

        except Exception as e:
            self.log(f"Error deleting quote: {e}")
