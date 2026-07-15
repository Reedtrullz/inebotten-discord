#!/usr/bin/env python3
"""Typed poll dispatch with truthful mutation and delivery outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

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


_MANAGER_ERROR_CODES = frozenset(
    {"cancelled", "commit_state_unknown", "storage_write_failed"}
)


class PollsHandler(BaseHandler):
    """Handle poll reads and mutations without reparsing typed payloads."""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.poll = monitor.poll

    def _turn_time(self, reference_time: datetime | None) -> datetime:
        """Use one aware instant for every time-sensitive read in this call."""
        if reference_time is None:
            reference_time = self.poll.clock.now()
        return self.poll._require_aware(reference_time)

    def _payload(
        self,
        message,
        typed_value,
        legacy_factory: Callable[[], Any],
        *,
        intent: BotIntent,
    ):
        used_legacy = typed_value is None
        payload = typed_or_legacy_payload(
            monitor=self.monitor,
            family="poll",
            typed_value=typed_value,
            legacy_factory=legacy_factory,
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
        retryable = (
            exc.code == "storage_write_failed"
            and not exc.mutated
            and not exc.commit_unknown
        )
        return DispatchOutcome.failure(
            exc.code,
            mutated=exc.mutated,
            retryable=retryable,
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

    async def _manager_error_response(
        self,
        message,
        exc: ManagerMutationError,
    ) -> DispatchOutcome:
        return await self._finish(
            message,
            self.loc.t("error_generic"),
            self._manager_failure(exc),
        )

    async def handle_poll_list(
        self,
        message,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """List active polls at the turn's captured instant."""
        now = self._turn_time(reference_time)
        guild_id = self.get_guild_id(message)
        try:
            active_polls = self.poll.get_active_polls(
                guild_id,
                reference_time=now,
            )
            if not active_polls:
                response_text = self.loc.t("no_active_polls")
            else:
                lines = [self.loc.t("poll_list_title"), ""]
                for index, poll in enumerate(active_polls, start=1):
                    lines.append(
                        self.loc.t(
                            "poll_list_item",
                            num=index,
                            question=poll.get("question", "?"),
                        )
                    )
                lines.extend(("", self.loc.t("poll_list_hint")))
                response_text = "\n".join(lines)
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure(
                "manager_rejected",
                mutated=False,
                retryable=True,
            )
        return await self._finish(message, response_text, base)

    async def handle_poll(
        self,
        message,
        poll_cmd: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Create a poll from a canonical payload or one legacy parse."""
        now = self._turn_time(reference_time)
        payload = self._payload(
            message,
            poll_cmd,
            lambda: self.monitor.parse_poll_command(message.content),
            intent=BotIntent.POLL_CREATE,
        )
        if not isinstance(payload, dict) or not {
            "question",
            "options",
        }.issubset(payload):
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        lang = payload.get("lang", self.loc.current_lang)
        try:
            poll = await self.poll.create_poll_result(
                guild_id=guild_id,
                question=payload["question"],
                options=payload["options"],
                created_by=message.author.name,
                created_by_id=message.author.id,
                reference_time=now,
            )
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(exc)
        except ManagerMutationError as exc:
            return await self._manager_error_response(message, exc)
        except Exception:
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )

        if poll:
            base = DispatchOutcome.success(mutated=True)
            try:
                response_text = self.poll.format_poll(poll, lang)
            except Exception:
                response_text = self.loc.t("error_generic")
        else:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure("manager_rejected")
        return await self._finish(message, response_text, base)

    async def handle_vote(
        self,
        message,
        vote: dict[str, Any] | int | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Vote against the route-frozen poll ID when one is present."""
        now = self._turn_time(reference_time)

        def legacy_vote():
            parsed = self.monitor.parse_vote(message.content)
            return {"option": parsed} if isinstance(parsed, int) else None

        payload = self._payload(
            message,
            vote,
            legacy_vote,
            intent=BotIntent.POLL_VOTE,
        )
        if isinstance(payload, int):
            payload = {"option": payload}
        if not isinstance(payload, dict):
            return await self._finish(
                message,
                self.loc.t("vote_error", error="invalid_payload"),
                DispatchOutcome.failure("invalid_payload"),
            )
        option = payload.get("option", payload.get("option_index"))
        if not isinstance(option, int) or isinstance(option, bool) or option <= 0:
            return await self._finish(
                message,
                self.loc.t("vote_error", error="invalid_payload"),
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        poll_id = payload.get("poll_id")
        if not isinstance(poll_id, str) or not poll_id:
            try:
                active_polls = self.poll.snapshot_pending_items(
                    guild_id,
                    reference_time=now,
                )
            except Exception:
                return await self._finish(
                    message,
                    self.loc.t("error_generic"),
                    DispatchOutcome.failure(
                        "manager_rejected",
                        retryable=True,
                    ),
                )
            if not active_polls:
                return await self._finish(
                    message,
                    self.loc.t("no_active_polls") + " 📊",
                    DispatchOutcome.failure("manager_rejected"),
                )
            if len(active_polls) > 1:
                lines = [
                    "📊 Det er flere aktive avstemninger. Bruk `@inebotten polls` og stem med en tydelig avstemning først."
                ]
                lines.extend(
                    f"{index}. {poll.get('question', '?')}"
                    for index, poll in enumerate(active_polls, 1)
                )
                return await self._finish(
                    message,
                    "\n".join(lines),
                    DispatchOutcome.failure("manager_rejected"),
                )
            poll_id = active_polls[0].get("poll_id")

        else:
            try:
                active_polls = self.poll.snapshot_pending_items(
                    guild_id,
                    reference_time=now,
                )
            except Exception:
                active_polls = ()
            if not any(
                candidate.get("poll_id") == poll_id
                for candidate in active_polls
            ):
                poll_id = None

        if not isinstance(poll_id, str) or not poll_id:
            return await self._finish(
                message,
                self.loc.t("poll_not_found"),
                DispatchOutcome.failure("manager_rejected"),
            )

        try:
            success, result = await self.poll.vote_result(
                guild_id,
                poll_id,
                option,
                message.author.id,
                message.author.name,
            )
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(exc)
        except ManagerMutationError as exc:
            return await self._manager_error_response(message, exc)
        except Exception:
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )

        if success:
            response_text = self.loc.t("vote_registered", num=option)
            base = DispatchOutcome.success(mutated=True)
        else:
            response_text = self.loc.t("vote_error", error=result)
            base = DispatchOutcome.failure("manager_rejected")
        return await self._finish(message, response_text, base)

    def _legacy_target(self, message) -> dict[str, Any] | None:
        """Use the existing target parser once for old direct callers."""
        router = getattr(self.monitor, "intent_router", None)
        parser = getattr(router, "_parse_poll_reference", None)
        if not callable(parser):
            return None
        parsed = parser(message.content.casefold())
        return parsed if isinstance(parsed, dict) else None

    def _resolve_poll_id(
        self,
        active_polls,
        payload: dict[str, Any],
    ):
        poll_id = payload.get("poll_id")
        if isinstance(poll_id, str) and poll_id:
            return (
                poll_id
                if any(
                    candidate.get("poll_id") == poll_id
                    for candidate in active_polls
                )
                else None
            )
        ref = payload.get("target")
        if not active_polls:
            return None
        if ref == "siste":
            return active_polls[-1]["poll_id"]
        if ref is None:
            return (
                active_polls[-1]["poll_id"]
                if len(active_polls) == 1
                else None
            )
        if (
            isinstance(ref, int)
            and not isinstance(ref, bool)
            and 1 <= ref <= len(active_polls)
        ):
            return active_polls[ref - 1]["poll_id"]
        return None

    def _poll_target_response(
        self,
        active_polls,
        ref,
        action_label: str,
    ) -> str:
        if ref is None and len(active_polls) > 1:
            lines = [
                f"📊 Det er flere aktive avstemninger. Bruk nummer, f.eks. `@inebotten {action_label} poll 1`, eller skriv `siste`."
            ]
            lines.extend(
                f"{index}. {poll.get('question', '?')}"
                for index, poll in enumerate(active_polls, 1)
            )
            return "\n".join(lines)
        return self.loc.t("poll_not_found")

    def _poll_result_text(self, action: str, success: bool, result) -> str:
        if success:
            if action == "edit":
                return self.loc.t("poll_edited") + "\n\n" + self.poll.format_poll(result)
            if action == "close":
                return self.loc.t("poll_closed") + "\n\n" + self.poll.format_poll(result)
            return self.loc.t("poll_deleted")
        if result == "Poll not found":
            return self.loc.t("poll_not_found")
        if result in {"Poll is closed", "Poll is already closed"}:
            return self.loc.t("poll_closed_already")
        if isinstance(result, str) and "owner" in result.casefold():
            return self.loc.t("poll_not_owner")
        return self.loc.t("error_generic")

    async def _handle_target_mutation(
        self,
        message,
        typed_payload: dict[str, Any] | None,
        *,
        action: str,
        reference_time: datetime | None,
    ) -> DispatchOutcome:
        now = self._turn_time(reference_time)
        payload = self._payload(
            message,
            typed_payload,
            lambda: self._legacy_target(message),
            intent={
                "edit": BotIntent.POLL_EDIT,
                "delete": BotIntent.POLL_DELETE,
                "close": BotIntent.POLL_CLOSE,
            }[action],
        )
        if not isinstance(payload, dict):
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        try:
            active_polls = self.poll.snapshot_pending_items(
                guild_id,
                reference_time=now,
            )
        except Exception:
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure(
                    "manager_rejected",
                    retryable=True,
                ),
            )
        poll_id = self._resolve_poll_id(active_polls, payload)
        if poll_id is None:
            return await self._finish(
                message,
                self._poll_target_response(
                    active_polls,
                    payload.get("target"),
                    {"edit": "endre", "delete": "slett", "close": "lukk"}[action],
                ),
                DispatchOutcome.failure("manager_rejected"),
            )

        try:
            if action == "edit":
                success, result = await self.poll.edit_poll_result(
                    guild_id=guild_id,
                    poll_id=poll_id,
                    user_id=message.author.id,
                    username=message.author.name,
                    question=payload.get("question"),
                    options=payload.get("options"),
                )
            elif action == "delete":
                success, result = await self.poll.delete_poll_result(
                    guild_id=guild_id,
                    poll_id=poll_id,
                    user_id=message.author.id,
                    username=message.author.name,
                )
            else:
                success, result = await self.poll.close_poll_result(
                    guild_id=guild_id,
                    poll_id=poll_id,
                    user_id=message.author.id,
                    username=message.author.name,
                )
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(exc)
        except ManagerMutationError as exc:
            return await self._manager_error_response(message, exc)
        except Exception:
            return await self._finish(
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
        try:
            response_text = self._poll_result_text(action, success, result)
        except Exception:
            response_text = self.loc.t("error_generic")
        return await self._finish(message, response_text, base)

    async def handle_poll_edit(
        self,
        message,
        payload: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        return await self._handle_target_mutation(
            message,
            payload,
            action="edit",
            reference_time=reference_time,
        )

    async def handle_poll_delete(
        self,
        message,
        payload: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        return await self._handle_target_mutation(
            message,
            payload,
            action="delete",
            reference_time=reference_time,
        )

    async def handle_poll_close(
        self,
        message,
        payload: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        return await self._handle_target_mutation(
            message,
            payload,
            action="close",
            reference_time=reference_time,
        )
