#!/usr/bin/env python3
"""Typed reminder dispatch with rollback-safe manager adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from cal_system.reminder_manager import parse_reminder_command
from core.dispatch_result import (
    DispatchCancelled,
    DispatchOutcome,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
)
from core.intent_models import BotIntent
from core.intent_payloads import (
    PayloadValidationError,
    typed_or_legacy_payload,
    validate_intent_payload,
)
from features.base_handler import BaseHandler


_MANAGER_ERROR_CODES = frozenset(
    {
        "cancelled",
        "commit_state_unknown",
        "external_commit_unknown",
        "external_state_changed_storage_failed",
        "storage_write_failed",
    }
)
_MANAGER_PAYLOAD_ERROR_CODES = frozenset(
    {
        "blank_value",
        "invalid_date",
        "invalid_due_at",
        "invalid_recurrence",
        "invalid_time",
        "invalid_timezone",
        "missing_date",
    }
)


class ReminderHandler(BaseHandler):
    """Handle one canonical reminder action without reparsing typed input."""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.reminders = monitor.reminders
        # MessageMonitor constructs NaturalLanguageParser before handlers and
        # IntentRouter inherits this exact resolver.  Reusing it keeps the
        # one-release raw fallback on the same temporal policy as routing.
        self.temporal_resolver = monitor.nlp_parser.temporal_resolver

    @staticmethod
    def _turn_time(reference_time: datetime) -> datetime:
        if (
            not isinstance(reference_time, datetime)
            or reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time_must_be_aware")
        # Preserve object identity. The manager validates/converts internally,
        # but every handler call receives the exact turn-captured value.
        return reference_time

    def _payload(
        self,
        message,
        typed_value,
        *,
        intent: BotIntent,
        reference_time: datetime,
    ):
        # ``typed_value`` is authoritative even when it is an empty mapping.
        # Only the explicit compatibility path may inspect the raw message.
        canonical = typed_or_legacy_payload(
            monitor=self.monitor,
            family="reminder",
            typed_value=typed_value,
            legacy_factory=lambda: parse_reminder_command(
                message.content,
                now=reference_time,
                temporal_resolver=self.temporal_resolver,
            ),
        )
        if typed_value is not None:
            return canonical
        return validate_intent_payload(intent, canonical)

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

    @staticmethod
    def _valid_positive_number(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @staticmethod
    def _valid_stable_id(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @classmethod
    def _valid_selector(cls, payload: dict[str, Any]) -> bool:
        has_number = cls._valid_positive_number(payload.get("number"))
        has_id = cls._valid_stable_id(payload.get("reminder_id"))
        return has_number is not has_id

    async def handle_reminder_search(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Search reminder text from one canonical query."""
        now = self._turn_time(reference_time)
        try:
            canonical = self._payload(
                message,
                payload,
                intent=BotIntent.REMINDER_SEARCH,
                reference_time=now,
            )
        except PayloadValidationError:
            return await self._finish(
                message,
                "🔎 Skriv hva du vil søke etter i påminnelser.",
                DispatchOutcome.failure("invalid_payload"),
            )
        query = canonical.get("query") if isinstance(canonical, dict) else None
        if (
            not isinstance(canonical, dict)
            or canonical.get("action") != "search"
            or not isinstance(query, str)
            or not query.strip()
        ):
            return await self._finish(
                message,
                "🔎 Skriv hva du vil søke etter i påminnelser.",
                DispatchOutcome.failure("invalid_payload"),
            )

        try:
            response_text = self.reminders.format_search_results(
                self.get_guild_id(message),
                query.strip(),
                getattr(self.loc, "current_lang", "no"),
            )
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure("manager_rejected", retryable=True)
        return await self._finish(message, response_text, base)

    async def handle_reminder_create(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Create one canonical reminder without re-resolving its schedule."""
        now = self._turn_time(reference_time)
        try:
            canonical = self._payload(
                message,
                payload,
                intent=BotIntent.REMINDER_CREATE,
                reference_time=now,
            )
        except PayloadValidationError:
            return await self._finish(
                message,
                "🔔 Skriv hva jeg skal minne deg på, f.eks. "
                "`@inebotten påminnelse ring legen 20.06`.",
                DispatchOutcome.failure("invalid_payload"),
            )
        text = canonical.get("text") if isinstance(canonical, dict) else None
        if (
            not isinstance(canonical, dict)
            or canonical.get("action") != "add"
            or not isinstance(text, str)
            or not text.strip()
        ):
            return await self._finish(
                message,
                "🔔 Skriv hva jeg skal minne deg på, f.eks. "
                "`@inebotten påminnelse ring legen 20.06`.",
                DispatchOutcome.failure("invalid_payload"),
            )
        guild_id = self.get_guild_id(message)
        temporal_kwargs = {
            key: canonical[key]
            for key in ("due_at", "time", "timezone")
            if key in canonical
        }
        try:
            reminder_id = await self.reminders.add_reminder_result(
                guild_id,
                message.author.id,
                message.author.name,
                text.strip(),
                canonical.get("due_date"),
                canonical.get("recurrence"),
                channel_id=getattr(getattr(message, "channel", None), "id", None),
                reference_time=now,
                **temporal_kwargs,
            )
        except ValueError as exc:
            if exc.args and exc.args[0] in _MANAGER_PAYLOAD_ERROR_CODES:
                return await self._finish(
                    message,
                    self.loc.t("error_generic"),
                    DispatchOutcome.failure("invalid_payload"),
                )
            return await self._mutation_exception(message, exc)
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if reminder_id:
            due = (
                f"\n📅 Frist: {canonical['due_date']}"
                if canonical.get("due_date")
                else ""
            )
            response_text = f"✅ **Påminnelse lagt til!**\n{text.strip()}{due}"
            base = DispatchOutcome.success(mutated=True)
        else:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure("manager_rejected")
        return await self._finish(message, response_text, base)

    async def handle_reminder_list(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """List active and recently completed reminders."""
        now = self._turn_time(reference_time)
        try:
            canonical = self._payload(
                message,
                payload,
                intent=BotIntent.REMINDER_LIST,
                reference_time=now,
            )
        except PayloadValidationError:
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )
        if not isinstance(canonical, dict) or canonical.get("action") != "list":
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            reminders_text = self.reminders.format_reminders_list(
                self.get_guild_id(message),
                show_completed=True,
                reference_time=now,
            )
            response_text = (
                f"🔔 **Påminnelser:**\n{reminders_text}"
                if reminders_text
                else "📭 Ingen aktive påminnelser."
            )
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            response_text = self.loc.t("error_generic")
            base = DispatchOutcome.failure("manager_rejected", retryable=True)
        return await self._finish(message, response_text, base)

    async def handle_reminder_complete(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Complete by one numbered or exact stable-ID selector."""
        now = self._turn_time(reference_time)
        try:
            canonical = self._payload(
                message,
                payload,
                intent=BotIntent.REMINDER_COMPLETE,
                reference_time=now,
            )
        except PayloadValidationError:
            return await self._finish(
                message,
                "📝 Hvilken påminnelse er ferdig? Bruk et nummer eller en ID.",
                DispatchOutcome.failure("invalid_payload"),
            )
        if (
            not isinstance(canonical, dict)
            or canonical.get("action") != "complete"
            or not self._valid_selector(canonical)
        ):
            return await self._finish(
                message,
                "📝 Hvilken påminnelse er ferdig? Bruk et nummer eller en ID.",
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        number = canonical.get("number")
        reminder_id = canonical.get("reminder_id")
        if isinstance(reminder_id, str):
            reminder_id = reminder_id.strip()
        try:
            completed = await self.reminders.complete_reminder_result(
                guild_id,
                reminder_num=number,
                reminder_id=reminder_id,
                reference_time=now,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        # The production manager retains its historical three-value result;
        # accept the documented two-value projection for one compatibility
        # release without weakening mutation truth for malformed results.
        if not isinstance(completed, tuple) or len(completed) not in {2, 3}:
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )
        success, reminder_text = completed[:2]
        next_date = completed[2] if len(completed) == 3 else None

        selector = reminder_id if reminder_id is not None else number
        if not success:
            return await self._finish(
                message,
                f"❌ Fant ikke påminnelse {selector}.",
                DispatchOutcome.failure("not_found", retryable=True),
            )
        response_text = f"✅ **Fullført! {reminder_text}**"
        if next_date:
            response_text += f"\n📅 Neste gang: {next_date}"
        return await self._finish(
            message,
            response_text,
            DispatchOutcome.success(mutated=True),
        )

    async def handle_reminder_edit(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Edit one reminder without deriving a second target from raw text."""
        now = self._turn_time(reference_time)
        try:
            canonical = self._payload(
                message,
                payload,
                intent=BotIntent.REMINDER_EDIT,
                reference_time=now,
            )
        except PayloadValidationError:
            return await self._finish(
                message,
                self.loc.t("calendar_edit_invalid"),
                DispatchOutcome.failure("invalid_payload"),
            )
        changes = canonical.get("changes") if isinstance(canonical, dict) else None
        if (
            not isinstance(canonical, dict)
            or canonical.get("action") != "edit"
            or not self._valid_selector(canonical)
            or not isinstance(changes, dict)
            or not changes
        ):
            return await self._finish(
                message,
                self.loc.t("calendar_edit_invalid"),
                DispatchOutcome.failure("invalid_payload"),
            )
        guild_id = self.get_guild_id(message)
        reminder_id = canonical.get("reminder_id")
        if isinstance(reminder_id, str):
            reminder_id = reminder_id.strip()
        edit_kwargs = {
            key: changes[key]
            for key in (
                "text",
                "due_at",
                "due_date",
                "time",
                "timezone",
                "recurrence",
            )
            if key in changes
        }
        try:
            updated = await self.reminders.edit_reminder_result(
                guild_id,
                index=canonical.get("number"),
                reminder_id=reminder_id,
                reference_time=now,
                **edit_kwargs,
            )
        except ValueError as exc:
            if exc.args and exc.args[0] in _MANAGER_PAYLOAD_ERROR_CODES:
                return await self._finish(
                    message,
                    self.loc.t("calendar_edit_invalid"),
                    DispatchOutcome.failure("invalid_payload"),
                )
            if exc.args == ("not_found",):
                selector = reminder_id or canonical.get("number", "?")
                return await self._finish(
                    message,
                    self.loc.t("reminder_edit_not_found", num=selector),
                    DispatchOutcome.failure("not_found", retryable=True),
                )
            return await self._mutation_exception(message, exc)
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if not isinstance(updated, Mapping):
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )
        if not updated:
            return await self._finish(
                message,
                self.loc.t("error_generic"),
                DispatchOutcome.failure("manager_rejected"),
            )
        return await self._finish(
            message,
            self.loc.t("reminder_edit_success", title=updated.get("text", "")),
            DispatchOutcome.success(mutated=True),
        )

    async def handle_reminder_delete(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime,
    ) -> DispatchOutcome:
        """Resolve a number once, then delete only by the stable record ID."""
        now = self._turn_time(reference_time)
        try:
            canonical = self._payload(
                message,
                payload,
                intent=BotIntent.REMINDER_DELETE,
                reference_time=now,
            )
        except PayloadValidationError:
            return await self._finish(
                message,
                self.loc.t("reminder_delete_not_found", num="?"),
                DispatchOutcome.failure("invalid_payload"),
            )
        if (
            not isinstance(canonical, dict)
            or canonical.get("action") != "delete"
            or not self._valid_selector(canonical)
        ):
            return await self._finish(
                message,
                self.loc.t("reminder_delete_not_found", num="?"),
                DispatchOutcome.failure("invalid_payload"),
            )

        guild_id = self.get_guild_id(message)
        reminder_id = canonical.get("reminder_id")
        if isinstance(reminder_id, str):
            reminder_id = reminder_id.strip()
        if reminder_id is None:
            number = canonical["number"]
            try:
                pending = self.reminders.snapshot_pending_items(guild_id)
            except Exception:
                return await self._finish(
                    message,
                    self.loc.t("error_generic"),
                    DispatchOutcome.failure("manager_rejected", retryable=True),
                )
            if number > len(pending):
                return await self._finish(
                    message,
                    self.loc.t("reminder_delete_not_found", num=number),
                    DispatchOutcome.failure("not_found", retryable=True),
                )
            reminder_id = pending[number - 1].get("id")
            if not self._valid_stable_id(reminder_id):
                return await self._finish(
                    message,
                    self.loc.t("error_generic"),
                    DispatchOutcome.failure("manager_rejected"),
                )

        try:
            deleted = await self.reminders.delete_reminder_result(
                guild_id,
                reminder_id=reminder_id,
                reference_time=now,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if not deleted:
            return await self._finish(
                message,
                self.loc.t("reminder_delete_not_found", num=reminder_id),
                DispatchOutcome.failure("not_found", retryable=True),
            )
        return await self._finish(
            message,
            self.loc.t("reminder_delete_success"),
            DispatchOutcome.success(mutated=True),
        )
