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
            page = re.search(r'\bside (\d+)\b', message.content, re.I)
            offset = (max(1, int(page.group(1))) - 1) * 8 if page else 0
            for idx, q in enumerate(quotes[offset:offset + 8], start=offset + 1):
                text = q.get("text", "")
                text = text if len(text) <= 140 else text[:139] + '…'
                author = q.get("author", "Ukjent")
                author = author if len(author) <= 40 else author[:39] + '…'
                lines.append(f"{idx}. \"{text}\" — {author}")

            lines.append(f'{len(quotes)} sitater · side {offset // 8 + 1}/{max(1, (len(quotes) + 7) // 8)}. Bruk `@inebotten liste sitater side {offset // 8 + 2}` for neste side; vis listen før endring eller sletting.')
            if await self.send_response(message, "\n".join(lines)) is not None:
                self.remember_list(message, quotes, range(offset + 1, min(len(quotes), offset + 8) + 1))

        except Exception as e:
            self.log(f"Error listing quotes: {e}")
            await self.send_response(message, 'Listen kunne ikke hentes. Prøv `@inebotten liste sitater` igjen.')

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
                self.displayed_index(message, self.quote.list_quotes(guild_id), index)
                success = self.quote.update_quote(guild_id, index, text=text, author=author)
            except ValueError as error:
                await self.send_response(
                    message, f'{error} Bruk `@inebotten liste sitater`.'
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
            await self.send_response(message, 'Endringen kunne ikke bekreftes. Vis `@inebotten liste sitater` og kontroller sitatet før du prøver igjen.')

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

            try:
                index = await self.reviewed_delete(message, self.quote.list_quotes(guild_id), index, 'sitat', 'text')
                if index is None:
                    return
                success = self.quote.delete_quote(guild_id, index)
            except ValueError as error:
                await self.send_response(
                    message, f'{error} Bruk `@inebotten liste sitater`.'
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
            await self.send_response(message, 'Slettingen kunne ikke lagres. Vis listen og kontroller status før du prøver igjen.')
