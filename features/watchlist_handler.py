#!/usr/bin/env python3
"""Typed watchlist dispatch with rollback-safe manager adapters."""

from __future__ import annotations

from datetime import datetime
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
from features.watchlist_manager import parse_watchlist_command


_MANAGER_ERROR_CODES = frozenset(
    {"cancelled", "commit_state_unknown", "storage_write_failed"}
)


class WatchlistHandler(BaseHandler):
    """Handle all watchlist actions from one canonical family payload."""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.watchlist = monitor.watchlist

    def _payload(
        self,
        message,
        typed_value,
        *,
        reference_time: datetime | None,
    ):
        used_legacy = typed_value is None
        payload = typed_or_legacy_payload(
            monitor=self.monitor,
            family="watchlist",
            typed_value=typed_value,
            legacy_factory=lambda: parse_watchlist_command(
                message.content,
                reference_time=reference_time,
            ),
        )
        if not used_legacy or not isinstance(payload, dict):
            return payload
        try:
            return validate_intent_payload(BotIntent.WATCHLIST, payload)
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

    async def handle_watchlist(
        self,
        message,
        watchlist_cmd: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Dispatch one typed action; only ``None`` invokes the legacy parser."""
        payload = self._payload(
            message,
            watchlist_cmd,
            reference_time=reference_time,
        )
        if not isinstance(payload, dict):
            return await self._finish(
                message,
                self.loc.t("watchlist_help"),
                DispatchOutcome.failure("invalid_payload"),
            )

        action = payload.get("action")
        if action == "remove":
            return await self.handle_watchlist_remove(
                message,
                payload,
                reference_time=reference_time,
            )
        if action == "edit":
            return await self.handle_watchlist_edit(
                message,
                payload,
                reference_time=reference_time,
            )

        lang = payload.get("lang", self.loc.current_lang)
        guild_id = self.get_guild_id(message)
        if action == "suggest":
            try:
                suggestion = self.watchlist.get_random_suggestion(
                    payload.get("type"),
                    payload.get("genre"),
                    guild_id=guild_id,
                )
                response_text = (
                    self.watchlist.format_suggestion(suggestion, lang)
                    if suggestion
                    else self.loc.t("no_suggestions")
                )
                base = DispatchOutcome.success(mutated=False)
            except Exception:
                response_text = self.loc.t("error_generic")
                base = DispatchOutcome.failure(
                    "manager_rejected",
                    retryable=True,
                )
            return await self._finish(message, response_text, base)

        if action == "status":
            try:
                response_text = self.watchlist.format_watchlist_status(
                    lang,
                    guild_id=guild_id,
                )
                base = DispatchOutcome.success(mutated=False)
            except Exception:
                response_text = self.loc.t("error_generic")
                base = DispatchOutcome.failure(
                    "manager_rejected",
                    retryable=True,
                )
            return await self._finish(message, response_text, base)

        if action != "add" or not isinstance(payload.get("title"), str):
            return await self._finish(
                message,
                self.loc.t("watchlist_help"),
                DispatchOutcome.failure("invalid_payload"),
            )

        title = payload["title"].strip()
        if not title:
            return await self._finish(
                message,
                self.loc.t("watchlist_help"),
                DispatchOutcome.failure("invalid_payload"),
            )
        content_type = payload.get("type") or "movie"
        extra = {
            key: payload[key]
            for key in ("genre", "comment")
            if key in payload and payload[key] is not None
        }
        try:
            success = await self.watchlist.add_watchlist_result(
                title,
                content_type=content_type,
                guild_id=guild_id,
                **extra,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if success:
            response_text = (
                f"✅ Lagt til **{title}** til watchlista!"
                if lang == "no"
                else f"✅ Added **{title}** to watchlist!"
            )
            base = DispatchOutcome.success(mutated=True)
        else:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure("manager_rejected")
        return await self._finish(message, response_text, base)

    async def handle_watchlist_remove(
        self,
        message,
        payload: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        canonical = self._payload(
            message,
            payload,
            reference_time=reference_time,
        )
        index = canonical.get("index") if isinstance(canonical, dict) else None
        if (
            not isinstance(canonical, dict)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index <= 0
        ):
            return await self._finish(
                message,
                self.loc.t("watchlist_help"),
                DispatchOutcome.failure("invalid_payload"),
            )

        lang = canonical.get("lang", self.loc.current_lang)
        guild_id = self.get_guild_id(message)
        try:
            item = await self.watchlist.remove_watchlist_result(
                index,
                guild_id=guild_id,
            )
        except ValueError:
            response_text = (
                "❌ Fant ikke noe med det nummeret."
                if lang == "no"
                else "❌ Could not find an item with that number."
            )
            return await self._finish(
                message,
                response_text,
                DispatchOutcome.failure("not_found", retryable=True),
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if item:
            title = item.get("title", "")
            response_text = (
                f"✅ Fjernet **{title}** fra watchlista!"
                if lang == "no"
                else f"✅ Removed **{title}** from watchlist!"
            )
            base = DispatchOutcome.success(mutated=True)
        else:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure("not_found")
        return await self._finish(message, response_text, base)

    async def handle_watchlist_edit(
        self,
        message,
        payload: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        canonical = self._payload(
            message,
            payload,
            reference_time=reference_time,
        )
        index = canonical.get("index") if isinstance(canonical, dict) else None
        if (
            not isinstance(canonical, dict)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index <= 0
        ):
            return await self._finish(
                message,
                self.loc.t("watchlist_help"),
                DispatchOutcome.failure("invalid_payload"),
            )

        changes = {
            key: canonical.get(key)
            for key in ("title", "type", "genre", "comment")
            if key in canonical
        }
        if not changes:
            return await self._finish(
                message,
                self.loc.t("watchlist_help"),
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        lang = canonical.get("lang", self.loc.current_lang)
        try:
            item = await self.watchlist.edit_watchlist_result(
                index,
                guild_id=guild_id,
                **changes,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if item is None:
            response_text = (
                "❌ Fant ikke noe med det nummeret."
                if lang == "no"
                else "❌ Could not find an item with that number."
            )
            base = DispatchOutcome.failure("not_found")
        else:
            title = item.get("title", "")
            response_text = (
                f"✅ Endret **{title}**!"
                if lang == "no"
                else f"✅ Updated **{title}**!"
            )
            base = DispatchOutcome.success(mutated=True)
        return await self._finish(message, response_text, base)
