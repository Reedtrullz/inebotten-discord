#!/usr/bin/env python3
"""Typed birthday dispatch with user-ID targeting and truthful outcomes."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.dispatch_result import (
    DispatchCancelled,
    DispatchOutcome,
    ManagerMutationCancelled,
    MessageSendCancelled,
)
from core.intent_payloads import (
    PayloadValidationError,
    typed_or_legacy_payload,
    validate_intent_payload,
)
from core.intent_router import BotIntent
from features.base_handler import BaseHandler
from features.birthday_manager import parse_birthday_command


OSLO = ZoneInfo("Europe/Oslo")
_BIRTHDAY_ERROR_CODES = frozenset(
    {
        "already_exists",
        "cancelled_after_external_commit",
        "cancelled_after_storage_commit",
        "commit_state_unknown",
        "external_commit_unknown",
        "external_state_changed_storage_failed",
        "external_sync_pending",
        "not_found",
        "storage_write_failed",
    }
)


class BirthdayHandler(BaseHandler):
    """Execute validated birthday create/list/edit payloads exactly once."""

    def __init__(self, monitor):
        super().__init__(monitor)
        self.birthdays = monitor.birthdays

    def _turn_time(self, reference_time: datetime | None) -> datetime:
        if reference_time is None:
            clock = getattr(self.monitor, "reminder_clock", None)
            now = getattr(clock, "now", None)
            reference_time = now() if callable(now) else datetime.now(OSLO)
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("birthday_reference_must_be_aware")
        return reference_time

    def _payload(
        self,
        message,
        typed_value,
        *,
        intent: BotIntent,
        legacy_factory,
    ):
        used_legacy = typed_value is None
        payload = typed_or_legacy_payload(
            monitor=self.monitor,
            family="birthday",
            typed_value=typed_value,
            legacy_factory=legacy_factory,
        )
        if not used_legacy or payload is None:
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
    def _raise_manager_cancel(exc: ManagerMutationCancelled) -> None:
        code = exc.code if exc.code in _BIRTHDAY_ERROR_CODES else "commit_state_unknown"
        raise DispatchCancelled(
            DispatchOutcome.failure(
                code,
                mutated=exc.mutated,
                retryable=(
                    exc.retryable
                    and not exc.mutated
                    and code != "commit_state_unknown"
                ),
                commit_unknown=(exc.commit_unknown or code == "commit_state_unknown"),
            )
        ) from None

    @staticmethod
    def _base_from_write(result) -> DispatchOutcome:
        if bool(result.commit_unknown):
            return DispatchOutcome.failure(
                "external_commit_unknown",
                mutated=bool(result.mutated),
                commit_unknown=True,
            )
        if bool(result.success):
            return DispatchOutcome.success(mutated=bool(result.mutated))
        code = result.error_code
        if code not in _BIRTHDAY_ERROR_CODES:
            return DispatchOutcome.failure(
                "commit_state_unknown",
                mutated=bool(result.mutated),
                commit_unknown=True,
            )
        if code == "external_state_changed_storage_failed":
            return DispatchOutcome.failure(
                code,
                mutated=bool(result.mutated),
            )
        if bool(result.mutated) and bool(result.sync_pending):
            return DispatchOutcome.failure(
                "external_sync_pending",
                mutated=True,
            )
        return DispatchOutcome.failure(
            code,
            mutated=bool(result.mutated),
            retryable=(code in {"storage_write_failed", "not_found"} and not result.mutated),
        )

    @staticmethod
    def _response_for_write(base: DispatchOutcome, *, success: str) -> str:
        if base.ok:
            return success
        if base.error_code == "already_exists":
            return "⚠️ Denne personen har allerede en registrert bursdag. Bruk redigering for å endre den."
        if base.error_code == "not_found":
            return "❌ Fant ingen bursdag for denne personen."
        if base.error_code == "external_sync_pending":
            return "⚠️ Bursdagen er lagret lokalt, men Google Calendar-synkronisering venter."
        if base.error_code == "external_state_changed_storage_failed":
            return "⚠️ Google Calendar ble endret, men den lokale sluttstatusen kunne ikke lagres."
        if base.commit_unknown:
            return "⚠️ Det er uklart om hele bursdagsendringen ble fullført. Jeg prøver ikke på nytt automatisk."
        return "❌ Bursdagen kunne ikke lagres."

    def _legacy_add_or_list(self, message, *, intent: BotIntent):
        parsed = parse_birthday_command(message.content)
        if not isinstance(parsed, dict):
            return None
        if intent is BotIntent.BIRTHDAY_CREATE and parsed.get("action") == "add":
            return {
                **parsed,
                "user_id": message.author.id,
                "display_name": message.author.name,
            }
        if intent is BotIntent.BIRTHDAY_LIST and parsed.get("action") == "list":
            return {"action": "list", "scope": "all"}
        return None

    @staticmethod
    def _parse_birthday_edit(content: str) -> dict[str, Any] | None:
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = re.sub(r"@inebotten\b[:,]?", "", cleaned, flags=re.I).strip()
        for keyword in (
            "endre bursdag",
            "rediger bursdag",
            "oppdater bursdag",
            "edit birthday",
            "update birthday",
        ):
            cleaned = re.sub(re.escape(keyword), "", cleaned, flags=re.I)
        match = re.search(r"(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?", cleaned)
        if not match:
            return None
        name = re.sub(r"[:\-–—]\s*$", "", cleaned[: match.start()]).strip()
        if not name:
            return None
        year = int(match.group(3)) if match.group(3) else None
        if year is not None and year < 100:
            year += 1900 if year >= 50 else 2000
        return {
            "name": name,
            "day": int(match.group(1)),
            "month": int(match.group(2)),
            "year": year,
        }

    def _legacy_edit(self, message):
        parsed = self._parse_birthday_edit(message.content)
        if parsed is None:
            return None
        bucket = getattr(self.birthdays, "birthdays", {}).get(
            str(self.get_guild_id(message)),
            {},
        )
        matches = [
            int(user_id)
            for user_id, record in bucket.items()
            if str(record.get("username", "")).casefold() == parsed["name"].casefold()
            and str(user_id).isdigit()
        ]
        if len(matches) != 1:
            return None
        return {
            "action": "edit",
            "user_id": matches[0],
            "day": parsed["day"],
            "month": parsed["month"],
            **({"year": parsed["year"]} if parsed["year"] is not None else {}),
        }

    async def handle_birthday_create(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        now = self._turn_time(reference_time)
        canonical = self._payload(
            message,
            payload,
            intent=BotIntent.BIRTHDAY_CREATE,
            legacy_factory=lambda: self._legacy_add_or_list(
                message,
                intent=BotIntent.BIRTHDAY_CREATE,
            ),
        )
        if not isinstance(canonical, dict) or canonical.get("action") != "add":
            return await self._finish(
                message,
                "🎂 Skriv bursdagen som dag og måned, for eksempel 15.05.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            result = await self.birthdays.create_birthday_result(
                self.get_guild_id(message),
                canonical["user_id"],
                canonical["display_name"],
                canonical["day"],
                canonical["month"],
                canonical.get("year"),
                reference_time=now,
            )
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(exc)
        except (KeyError, TypeError, ValueError):
            return await self._finish(
                message,
                "🎂 Bursdagsdatoen er ugyldig.",
                DispatchOutcome.failure("invalid_payload"),
            )
        except Exception:
            return await self._finish(
                message,
                "⚠️ Det er uklart om bursdagen ble lagret. Jeg prøver ikke på nytt automatisk.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )
        base = self._base_from_write(result)
        date_text = f"{canonical['day']:02d}.{canonical['month']:02d}"
        if canonical.get("year") is not None:
            date_text += f".{canonical['year']}"
        copy = self._response_for_write(
            base,
            success=f"✅ Bursdagen til **{canonical['display_name']}** er lagret: {date_text}.",
        )
        return await self._finish(message, copy, base)

    async def handle_birthday_list(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        now = self._turn_time(reference_time)
        canonical = self._payload(
            message,
            payload,
            intent=BotIntent.BIRTHDAY_LIST,
            legacy_factory=lambda: self._legacy_add_or_list(
                message,
                intent=BotIntent.BIRTHDAY_LIST,
            ),
        )
        if not isinstance(canonical, dict) or canonical.get("action") != "list":
            return await self._finish(
                message,
                "🎂 Jeg forstod ikke hvilken bursdagsliste du ville se.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            scope = canonical.get("scope", "all")
            if scope == "self":
                copy = self.birthdays.format_birthday_for_user(
                    self.get_guild_id(message),
                    message.author.id,
                )
            elif scope == "upcoming":
                copy = self.birthdays.format_upcoming_birthdays(
                    self.get_guild_id(message),
                    days=30,
                    reference_time=now,
                )
            else:
                copy = self.birthdays.format_birthday_list(
                    self.get_guild_id(message)
                )
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            copy = "❌ Bursdagslista kunne ikke leses akkurat nå."
            base = DispatchOutcome.failure("manager_rejected", retryable=True)
        return await self._finish(message, copy, base)

    async def handle_birthday_edit(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        now = self._turn_time(reference_time)
        canonical = self._payload(
            message,
            payload,
            intent=BotIntent.BIRTHDAY_EDIT,
            legacy_factory=lambda: self._legacy_edit(message),
        )
        if not isinstance(canonical, dict) or canonical.get("action") != "edit":
            return await self._finish(
                message,
                "❌ Jeg trenger en entydig person og en gyldig bursdagsdato.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            result = await self.birthdays.edit_birthday_by_user_id_result(
                self.get_guild_id(message),
                canonical["user_id"],
                canonical["day"],
                canonical["month"],
                canonical.get("year"),
                reference_time=now,
            )
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(exc)
        except (KeyError, TypeError, ValueError):
            return await self._finish(
                message,
                "🎂 Bursdagsdatoen er ugyldig.",
                DispatchOutcome.failure("invalid_payload"),
            )
        except Exception:
            return await self._finish(
                message,
                "⚠️ Det er uklart om bursdagen ble oppdatert. Jeg prøver ikke på nytt automatisk.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )
        base = self._base_from_write(result)
        return await self._finish(
            message,
            self._response_for_write(
                base,
                success=self.loc.t("birthday_edit_success"),
            ),
            base,
        )
