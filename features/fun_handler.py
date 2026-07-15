#!/usr/bin/env python3
"""
FunHandler - Handles fun/entertainment commands for the selfbot.

Commands:
- Word of the day
- Quotes (save/get)
- Compliments/roasts
- Horoscopes
"""

from typing import Dict, Any, Optional

import discord

from core.dispatch_result import (
    DispatchCancelled,
    DispatchOutcome,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
)
from core.intent_payloads import (
    PayloadValidationError,
    typed_or_legacy_payload,
    validate_intent_payload,
)
from core.intent_router import BotIntent
from features.base_handler import BaseHandler
from features.quote_manager import parse_quote_command


_MANAGER_ERROR_CODES = frozenset(
    {"cancelled", "commit_state_unknown", "storage_write_failed"}
)


class FunHandler(BaseHandler):
    """Handler for fun/entertainment commands"""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.wod = monitor.wod
        self.quote = monitor.quote
        self.compliments = monitor.compliments
        self.horoscope = monitor.horoscope

    async def handle_word_of_day(self, message) -> None:
        """Handle word of the day request."""
        try:
            lang = self.loc.current_lang
            word = self.wod.get_word_of_day(lang)
            response_text = self.wod.format_word(word, lang)
            await self.send_response(message, response_text)
        except Exception as e:
            self.log(f"Error handling word of day: {e}")

    async def _finish_quote(
        self,
        message,
        response_text: str,
        base: DispatchOutcome,
    ) -> DispatchOutcome:
        try:
            delivery = await self.send_response_result(message, response_text)
        except MessageSendCancelled as exc:
            raise DispatchCancelled(base.with_delivery(exc.result)) from None
        return base.with_delivery(delivery)

    async def handle_quote_command(
        self,
        message,
        quote_cmd: Dict[str, Any] | None,
    ) -> DispatchOutcome:
        """
        Handle quote commands.

        Args:
            message: The Discord message
            quote_cmd: Parsed quote command with 'action' and optional 'text'
        """
        used_legacy = quote_cmd is None
        payload = typed_or_legacy_payload(
            monitor=self.monitor,
            family="quote",
            typed_value=quote_cmd,
            legacy_factory=lambda: parse_quote_command(message.content),
        )
        if used_legacy and isinstance(payload, dict):
            try:
                payload = validate_intent_payload(BotIntent.QUOTE, payload)
            except PayloadValidationError:
                payload = None
        if not isinstance(payload, dict) or payload.get("action") not in {
            "save",
            "get",
        }:
            return await self._finish_quote(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        lang = payload.get("lang", self.loc.current_lang)
        if payload["action"] == "get":
            try:
                author = payload.get("author")
                quote = (
                    self.quote.get_quote_by_author(guild_id, author)
                    if author
                    else self.quote.get_random_quote(guild_id)
                )
                response_text = (
                    self.quote.format_quote(quote, lang)
                    if quote
                    else self.loc.t("no_quotes")
                )
                base = DispatchOutcome.success(mutated=False)
            except Exception:
                response_text = self.loc.t("error_generic")
                base = DispatchOutcome.failure(
                    "manager_rejected",
                    retryable=True,
                )
            return await self._finish_quote(message, response_text, base)

        quote_text = payload.get("text")
        if not isinstance(quote_text, str) or not quote_text.strip():
            return await self._finish_quote(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            success = await self.quote.add_quote_result(
                guild_id=guild_id,
                text=quote_text,
                author=payload.get("author") or message.author.name,
            )
        except ManagerMutationCancelled as exc:
            if exc.code not in _MANAGER_ERROR_CODES:
                raise DispatchCancelled(
                    DispatchOutcome.failure(
                        "commit_state_unknown",
                        mutated=exc.mutated,
                        commit_unknown=True,
                    )
                ) from None
            raise DispatchCancelled(
                DispatchOutcome.failure(
                    exc.code,
                    mutated=exc.mutated,
                    retryable=exc.retryable,
                    commit_unknown=exc.commit_unknown,
                )
            ) from None
        except ManagerMutationError as exc:
            if exc.code not in _MANAGER_ERROR_CODES:
                base = DispatchOutcome.failure(
                    "commit_state_unknown",
                    mutated=exc.mutated,
                    commit_unknown=True,
                )
            else:
                base = DispatchOutcome.failure(
                    exc.code,
                    mutated=exc.mutated,
                    retryable=(
                        exc.code == "storage_write_failed"
                        and not exc.mutated
                        and not exc.commit_unknown
                    ),
                    commit_unknown=exc.commit_unknown,
                )
            return await self._finish_quote(
                message,
                self.loc.t("error_generic"),
                base,
            )
        except Exception:
            return await self._finish_quote(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )

        base = (
            DispatchOutcome.success(mutated=True)
            if success
            else DispatchOutcome.failure("manager_rejected")
        )
        if success:
            try:
                response_text = self.quote.format_confirmation(quote_text, lang)
            except Exception:
                response_text = self.loc.t("error_generic")
        else:
            response_text = self.loc.t("error_generic")
        return await self._finish_quote(message, response_text, base)

    async def handle_compliment(self, message, compliment_cmd: Dict[str, Any]) -> None:
        """
        Handle compliment/roast commands.

        Args:
            message: The Discord message
            compliment_cmd: Parsed command with 'action' and optional 'user'
        """
        try:
            lang = self.loc.current_lang

            if compliment_cmd["action"] == "compliment":
                text = self.compliments.get_compliment(lang)
                response_text = self.compliments.format_compliment(
                    text, compliment_cmd.get("user"), lang
                )
            else:  # roast
                text = self.compliments.get_roast(lang)
                response_text = self.compliments.format_roast(
                    text, compliment_cmd.get("user"), lang
                )

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling compliment: {e}")

    async def handle_horoscope(self, message, horoscope_cmd: Dict[str, Any]) -> None:
        """
        Handle horoscope requests.

        Args:
            message: The Discord message
            horoscope_cmd: Parsed command with 'sign'
        """
        try:
            lang = self.loc.current_lang

            horoscope_data = self.horoscope.get_horoscope(horoscope_cmd["sign"], lang)
            response_text = self.horoscope.format_horoscope(horoscope_data, lang)

            await self.send_response(message, response_text)

        except Exception as e:
            self.log(f"Error handling horoscope: {e}")
