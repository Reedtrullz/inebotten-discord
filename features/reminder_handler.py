#!/usr/bin/env python3
"""Typed reminder dispatch with rollback-safe manager adapters."""

from __future__ import annotations

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
from core.intent_payloads import typed_or_legacy_payload
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


class ReminderHandler(BaseHandler):
    """Handle one canonical reminder action without reparsing typed input."""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.reminders = monitor.reminders

    def _turn_time(self, reference_time: datetime | None) -> datetime:
        if reference_time is None:
            reference_time = self.reminders.clock.now()
        return self.reminders._require_aware(reference_time)

    def _payload(
        self,
        message,
        typed_value,
        *,
        reference_time: datetime,
    ):
        # ``typed_value`` is authoritative even when it is an empty mapping.
        # Only the explicit compatibility path may inspect the raw message.
        return typed_or_legacy_payload(
            monitor=self.monitor,
            family="reminder",
            typed_value=typed_value,
            legacy_factory=lambda: parse_reminder_command(
                message.content,
                now=reference_time,
            ),
        )

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
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Search reminder text from one canonical query."""
        now = self._turn_time(reference_time)
        canonical = self._payload(message, payload, reference_time=now)
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
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Create a reminder through the current Task 3 temporal boundary."""
        now = self._turn_time(reference_time)
        canonical = self._payload(message, payload, reference_time=now)
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
        if "due_at" in canonical or "timezone" in canonical:
            return await self._finish(
                message,
                "🔔 Tidspunktet kan ikke lagres trygt ennå. Ingenting ble endret.",
                DispatchOutcome.failure("unsupported_temporal_field"),
            )

        guild_id = self.get_guild_id(message)
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
            )
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
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """List active and recently completed reminders."""
        now = self._turn_time(reference_time)
        canonical = self._payload(message, payload, reference_time=now)
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
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Complete by one numbered or exact stable-ID selector."""
        now = self._turn_time(reference_time)
        canonical = self._payload(message, payload, reference_time=now)
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
            success, reminder_text, next_date = (
                await self.reminders.complete_reminder_result(
                    guild_id,
                    reminder_num=number,
                    reminder_id=reminder_id,
                    reference_time=now,
                )
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

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
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Edit one reminder without deriving a second target from raw text."""
        now = self._turn_time(reference_time)
        canonical = self._payload(message, payload, reference_time=now)
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
        if "due_at" in changes or "timezone" in changes:
            return await self._finish(
                message,
                "🔔 Tidspunktet kan ikke lagres trygt ennå. Ingenting ble endret.",
                DispatchOutcome.failure("unsupported_temporal_field"),
            )

        guild_id = self.get_guild_id(message)
        reminder_id = canonical.get("reminder_id")
        if isinstance(reminder_id, str):
            reminder_id = reminder_id.strip()
        try:
            updated = await self.reminders.edit_reminder_result(
                guild_id,
                index=canonical.get("number"),
                title=changes.get("text"),
                date=changes.get("due_date"),
                time=changes.get("time"),
                recurrence=changes.get("recurrence"),
                reminder_id=reminder_id,
                reference_time=now,
            )
        except ValueError as exc:
            if exc.args == ("invalid_recurrence",):
                return await self._finish(
                    message,
                    self.loc.t("calendar_edit_invalid"),
                    DispatchOutcome.failure("invalid_payload"),
                )
            selector = reminder_id or canonical.get("number", "?")
            return await self._finish(
                message,
                self.loc.t("reminder_edit_not_found", num=selector),
                DispatchOutcome.failure("not_found", retryable=True),
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)

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
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        """Resolve a number once, then delete only by the stable record ID."""
        now = self._turn_time(reference_time)
        canonical = self._payload(message, payload, reference_time=now)
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
