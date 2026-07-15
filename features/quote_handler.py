#!/usr/bin/env python3
"""Typed quote list/edit/delete dispatch."""

from __future__ import annotations

import re
from typing import Any

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


class QuoteHandler(BaseHandler):
    """Manage quote records without reading raw text on typed paths."""

    _EDIT_FIELD_PATTERN = re.compile(
        r"\b(?:tekst|text|forfatter|author)\b\s*:",
        flags=re.IGNORECASE,
    )

    def __init__(self, monitor):
        super().__init__(monitor)
        self.quote = monitor.quote

    def _payload(self, message, typed_value, *, intent: BotIntent):
        # The imported parser is intentionally called only by this fallback
        # factory.  An empty mapping is authoritative typed input.
        used_legacy = typed_value is None
        payload = typed_or_legacy_payload(
            monitor=self.monitor,
            family="quote",
            typed_value=typed_value,
            legacy_factory=lambda: parse_quote_command(message.content),
        )
        if not used_legacy or not isinstance(payload, dict):
            return payload
        try:
            return validate_intent_payload(intent, payload)
        except PayloadValidationError:
            return None

    async def _finish(
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

    @staticmethod
    def _manager_failure(exc: ManagerMutationError) -> DispatchOutcome:
        if exc.code not in _MANAGER_ERROR_CODES:
            return DispatchOutcome.failure(
                "commit_state_unknown",
                mutated=exc.mutated,
                commit_unknown=True,
            )
        return DispatchOutcome.failure(
            exc.code,
            mutated=exc.mutated,
            retryable=(
                exc.code == "storage_write_failed"
                and not exc.mutated
                and not exc.commit_unknown
            ),
            commit_unknown=exc.commit_unknown,
        )

    @staticmethod
    def _raise_manager_cancel(exc: ManagerMutationCancelled) -> None:
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

    async def _mutation_exception(self, message, exc) -> DispatchOutcome:
        if isinstance(exc, ManagerMutationCancelled):
            self._raise_manager_cancel(exc)
        if isinstance(exc, ManagerMutationError):
            base = self._manager_failure(exc)
        else:
            base = DispatchOutcome.failure(
                "commit_state_unknown",
                commit_unknown=True,
            )
        return await self._finish(message, self.loc.t("error_generic"), base)

    # Kept for one-release direct-call compatibility and explicit sentinel
    # assertions. Canonical typed paths never call these helpers.
    def _extract_index_from_payload(self, payload) -> int | None:
        if isinstance(payload, dict):
            return payload.get("index")
        if isinstance(payload, int):
            return payload
        return None

    def _extract_text_from_payload(self, payload) -> str | None:
        return payload.get("text") if isinstance(payload, dict) else None

    def _extract_author_from_payload(self, payload) -> str | None:
        return payload.get("author") if isinstance(payload, dict) else None

    def _extract_edit_fields_from_content(
        self,
        content: str,
    ) -> tuple[str | None, str | None]:
        parsed = parse_quote_command(content)
        if not isinstance(parsed, dict) or parsed.get("action") != "edit":
            return None, None
        return parsed.get("text"), parsed.get("author")

    async def handle_quote_list(
        self,
        message,
        payload: dict[str, Any] | None = None,
    ) -> DispatchOutcome:
        canonical = self._payload(
            message,
            payload,
            intent=BotIntent.QUOTE_LIST,
        )
        if not isinstance(canonical, dict) or canonical.get("action") != "list":
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            quotes = self.quote.list_quotes(self.get_guild_id(message))
            if not quotes:
                response_text = self.loc.t("quote_list_empty")
            else:
                lines = [self.loc.t("quote_list_title")]
                for index, quote in enumerate(quotes, start=1):
                    text = quote.get("text", "")
                    author = quote.get("author", "Ukjent")
                    lines.append(f'{index}. "{text}" — {author}')
                response_text = "\n".join(lines)
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure(
                "manager_rejected",
                retryable=True,
            )
        return await self._finish(message, response_text, base)

    async def handle_quote_edit(
        self,
        message,
        payload: dict[str, Any] | None,
    ) -> DispatchOutcome:
        canonical = self._payload(
            message,
            payload,
            intent=BotIntent.QUOTE_EDIT,
        )
        if not isinstance(canonical, dict) or canonical.get("action") != "edit":
            return await self._finish(
                message,
                self.loc.t("calendar_edit_invalid"),
                DispatchOutcome.failure("invalid_payload"),
            )
        index = canonical.get("index")
        text = canonical.get("text")
        author = canonical.get("author")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index <= 0
            or (text is None and author is None)
        ):
            return await self._finish(
                message,
                self.loc.t("calendar_edit_invalid"),
                DispatchOutcome.failure("invalid_payload"),
            )

        try:
            success = await self.quote.update_quote_result(
                self.get_guild_id(message),
                index,
                text=text,
                author=author,
            )
        except ValueError:
            return await self._finish(
                message,
                self.loc.t("quote_edit_not_found", num=index),
                DispatchOutcome.failure("not_found", retryable=True),
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        base = (
            DispatchOutcome.success(mutated=True)
            if success
            else DispatchOutcome.failure("manager_rejected")
        )
        response_text = (
            self.loc.t("quote_edit_success")
            if success
            else self.loc.t("quote_edit_not_found", num=index)
        )
        return await self._finish(message, response_text, base)

    async def handle_quote_delete(
        self,
        message,
        payload: dict[str, Any] | None,
    ) -> DispatchOutcome:
        canonical = self._payload(
            message,
            payload,
            intent=BotIntent.QUOTE_DELETE,
        )
        if not isinstance(canonical, dict) or canonical.get("action") != "delete":
            return await self._finish(
                message,
                self.loc.t("invalid_event_num"),
                DispatchOutcome.failure("invalid_payload"),
            )
        index = canonical.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index <= 0:
            return await self._finish(
                message,
                self.loc.t("invalid_event_num"),
                DispatchOutcome.failure("invalid_payload"),
            )

        try:
            success = await self.quote.delete_quote_result(
                self.get_guild_id(message),
                index,
            )
        except ValueError:
            return await self._finish(
                message,
                self.loc.t("quote_delete_not_found", num=index),
                DispatchOutcome.failure("not_found", retryable=True),
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        base = (
            DispatchOutcome.success(mutated=True)
            if success
            else DispatchOutcome.failure("manager_rejected")
        )
        response_text = (
            self.loc.t("quote_delete_success")
            if success
            else self.loc.t("quote_delete_not_found", num=index)
        )
        return await self._finish(message, response_text, base)
