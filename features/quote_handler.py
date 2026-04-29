#!/usr/bin/env python3
"""
QuoteHandler - Handles quote list, update, and delete commands for the selfbot.

Commands:
- List all quotes
- Update a quote by index
- Delete a quote by index
"""

import re

from features.base_handler import BaseHandler


class QuoteHandler(BaseHandler):
    """Handler for quote management commands"""

    _EDIT_FIELD_PATTERN = re.compile(
        r"\b(?:tekst|text|forfatter|author)\b\s*:",
        flags=re.IGNORECASE,
    )

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

    def _extract_edit_fields_from_content(self, content: str) -> tuple[str | None, str | None]:
        cleaned = re.sub(r"^(?:<@!?\d+>|@\S+)\s*", "", content).strip()

        matches = list(self._EDIT_FIELD_PATTERN.finditer(cleaned))
        if not matches:
            return None, None

        text = None
        author = None
        for idx, match in enumerate(matches):
            label = match.group(0).split(":", 1)[0].strip().lower()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned)
            value = cleaned[start:end].strip() or None

            if label in {"tekst", "text"}:
                text = value
            else:
                author = value

        return text or None, author or None

    async def handle_quote_list(self, message) -> None:
        """List all quotes for the current guild with numbered indices."""
        try:
            guild_id = self.get_guild_id(message)
            quotes = self.quote.list_quotes(guild_id)

            if not quotes:
                await self.send_response(message, self.loc.t("quote_list_empty"))
                return

            lines = [self.loc.t("quote_list_title")]
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
                await self.send_response(
                    message, self.loc.t("invalid_event_num")
                )
                return

            text = self._extract_text_from_payload(payload)
            author = self._extract_author_from_payload(payload)

            if text is None and author is None:
                text, author = self._extract_edit_fields_from_content(message.content)

            if text is None and author is None:
                await self.send_response(
                    message, self.loc.t("calendar_edit_invalid")
                )
                return

            try:
                success = self.quote.update_quote(guild_id, index, text=text, author=author)
            except ValueError:
                await self.send_response(
                    message, self.loc.t("quote_edit_not_found", num=index)
                )
                return

            if success:
                await self.send_response(
                    message, self.loc.t("quote_edit_success")
                )
            else:
                await self.send_response(
                    message, self.loc.t("quote_edit_not_found", num=index)
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
                await self.send_response(
                    message, self.loc.t("invalid_event_num")
                )
                return

            try:
                success = self.quote.delete_quote(guild_id, index)
            except ValueError:
                await self.send_response(
                    message, self.loc.t("quote_delete_not_found", num=index)
                )
                return

            if success:
                await self.send_response(
                    message, self.loc.t("quote_delete_success")
                )
            else:
                await self.send_response(
                    message, self.loc.t("quote_delete_not_found", num=index)
                )

        except Exception as e:
            self.log(f"Error deleting quote: {e}")
