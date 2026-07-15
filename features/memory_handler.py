#!/usr/bin/env python3
"""Typed Discord-facing controls for user memory."""

from __future__ import annotations

import json

from core.action_authorization import (
    ClaimedActionAuthorization,
    validate_claimed_action_authorization,
)
from core.dispatch_result import (
    DispatchCancelled,
    DispatchOutcome,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
)
from core.message_context import conversation_key_from_message
from features.base_handler import BaseHandler


_MANAGER_ERROR_CODES = frozenset(
    {"cancelled", "commit_state_unknown", "storage_write_failed"}
)
_GENERIC_ERROR = "Beklager, noe gikk galt. Prøv igjen senere."


class MemoryHandler(BaseHandler):
    """Handle view/export/delete commands for the current user's memory."""

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

    async def handle_memory(
        self,
        message,
        payload=None,
        *,
        authorization: ClaimedActionAuthorization | None = None,
    ) -> DispatchOutcome:
        action = (payload or {}).get("action", "view")

        if action == "export":
            return await self._handle_export(message)
        if action == "delete":
            return await self._handle_delete(
                message,
                authorization=authorization,
            )
        return await self._handle_view(message)

    async def _handle_view(self, message) -> DispatchOutcome:
        try:
            text = await self.monitor.user_memory.format_user_memory_for_user(
                message.author.id,
                getattr(message.author, "name", None),
            )
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            text = _GENERIC_ERROR
            base = DispatchOutcome.failure("manager_rejected", retryable=True)
        return await self._finish(message, text, base)

    async def _handle_export(self, message) -> DispatchOutcome:
        try:
            data = await self.monitor.user_memory.export_user_memory(
                message.author.id
            )
        except Exception:
            return await self._finish(
                message,
                _GENERIC_ERROR,
                DispatchOutcome.failure("manager_rejected", retryable=True),
            )
        if not data:
            text = "Jeg har ikke lagret noe brukerminne om deg ennå."
        else:
            serialized = json.dumps(data, ensure_ascii=False, indent=2)
            if len(serialized) > 1_800:
                serialized = serialized[:1_800] + "\n... (forkortet)"
            text = f"```json\n{serialized}\n```"
        return await self._finish(
            message,
            text,
            DispatchOutcome.success(mutated=False),
        )

    async def _handle_delete(
        self,
        message,
        *,
        authorization: ClaimedActionAuthorization | None,
    ) -> DispatchOutcome:
        pending_actions = getattr(self.monitor, "pending_actions", None)
        if pending_actions is None or not validate_claimed_action_authorization(
            authorization,
            key=conversation_key_from_message(message),
            pending_actions=pending_actions,
        ):
            return DispatchOutcome.failure(
                "confirmation_required",
                retryable=False,
            )

        try:
            deleted = await self.monitor.user_memory.delete_user_memory_result(
                message.author.id
            )
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(exc)
        except ManagerMutationError as exc:
            return await self._finish(
                message,
                _GENERIC_ERROR,
                self._manager_failure(exc),
            )
        except Exception:
            return await self._finish(
                message,
                _GENERIC_ERROR,
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )

        if deleted:
            text = "✅ Ferdig. Jeg har slettet brukerminnet ditt."
            base = DispatchOutcome.success(mutated=True)
        else:
            text = "Jeg hadde ikke noe brukerminne lagret om deg."
            base = DispatchOutcome.success(mutated=False)
        return await self._finish(message, text, base)
