#!/usr/bin/env python3
"""Typed calendar dispatch with stable targets and truthful outcomes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable

from cal_system.google_calendar_manager import ExternalOperationCancelled
from cal_system.temporal_resolver import OSLO, TemporalResolver
from core.dispatch_result import (
    DispatchCancelled,
    DispatchOutcome,
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
)
from core.intent_payloads import (
    PayloadValidationError,
    typed_or_legacy_payload,
    validate_intent_payload,
)
from core.list_read_filters import is_supported_calendar_read_date
from core.intent_router import BotIntent
from core.mutation_coordinator import CALENDAR_SHARED_SCOPE
from features.base_handler import BaseHandler


_MANAGER_ERROR_CODES = frozenset(
    {
        "cancelled",
        "cancelled_after_external_commit",
        "cancelled_after_storage_commit",
        "commit_state_unknown",
        "external_commit_unknown",
        "external_read_failed",
        "external_state_changed_storage_failed",
        "external_sync_pending",
        "integration_disabled",
        "not_configured",
        "storage_write_failed",
        "sync_transform_failed",
    }
)

_AUTH_ERROR_CODES = frozenset(
    {
        "auth_flow_expired",
        "auth_flow_failed",
        "channel_mismatch",
        "external_commit_unknown",
        "integration_disabled",
        "invalid_auth_code",
        "invalid_auth_flow",
        "missing_credentials",
        "missing_auth_flow",
        "requester_mismatch",
        "token_storage_failed",
    }
)


class CalendarHandler(BaseHandler):
    """Execute one already-routed calendar action without reparsing typed input."""

    CLEAR_CONFIRM_KEYWORDS = ("bekreft", "confirm")
    DELETE_COMMANDS = r"(?:slett|slette|delete|fjern|fjerne)"
    COMPLETE_COMMANDS = r"(?:ferdig|done|complete|fullfør|fullføre|fullført)"
    MUTATION_PREFIX = r"(?:(?:kan du|kunne du|vennligst|please)\s+)?"
    TEMPORAL_CLARIFICATION = (
        "⚠️ Jeg trenger en gyldig og entydig dato og tid før jeg kan "
        "endre kalenderen."
    )

    _EDIT_FIELD_MAP = {
        "tittel": "title",
        "title": "title",
        "dato": "date",
        "date": "date",
        "tid": "time",
        "time": "time",
        "kl": "time",
        "klokken": "time",
        "gjentakelse": "recurrence",
        "recurrence": "recurrence",
        "gjenta": "recurrence",
        "beskrivelse": "description",
        "description": "description",
        "desc": "description",
        "type": "type",
    }

    def __init__(
        self,
        monitor,
        *,
        temporal_resolver: TemporalResolver | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        super().__init__(monitor)
        self.calendar = monitor.calendar
        self.nlp_parser = monitor.nlp_parser
        inherited = getattr(self.nlp_parser, "temporal_resolver", None)
        self.temporal_resolver = temporal_resolver or inherited or TemporalResolver()
        clock = getattr(self.calendar, "clock", None)
        clock_now = getattr(clock, "now", None)
        self._now_provider = now_provider or (
            clock_now if callable(clock_now) else lambda: datetime.now(OSLO)
        )

    def _capture_reference(self, reference_time: datetime | None) -> datetime:
        captured = self._now_provider() if reference_time is None else reference_time
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("calendar_reference_must_be_aware")
        # An explicit turn reference is passed to managers by identity, not
        # recaptured or replaced by an equivalent datetime.
        return captured

    def _typed_or_legacy(
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
            family="calendar",
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
                exc.code in {"storage_write_failed", "external_read_failed"}
                and not exc.mutated
                and not exc.commit_unknown
            ),
            commit_unknown=exc.commit_unknown,
        )

    @staticmethod
    def _raise_manager_cancel(
        exc: ManagerMutationCancelled,
        *,
        prior_mutated: bool = False,
    ) -> None:
        code = exc.code if exc.code in _MANAGER_ERROR_CODES else "commit_state_unknown"
        raise DispatchCancelled(
            DispatchOutcome.failure(
                code,
                mutated=(exc.mutated or prior_mutated),
                retryable=(
                    exc.retryable
                    and not (exc.mutated or prior_mutated)
                    and code != "commit_state_unknown"
                ),
                commit_unknown=(exc.commit_unknown or code == "commit_state_unknown"),
            )
        ) from None

    async def _mutation_exception(
        self,
        message,
        exc,
        *,
        prior_mutated: bool = False,
    ) -> DispatchOutcome:
        if isinstance(exc, ManagerMutationCancelled):
            self._raise_manager_cancel(exc, prior_mutated=prior_mutated)
        if isinstance(exc, ManagerMutationError):
            base = self._manager_failure(exc)
            if prior_mutated and not base.mutated:
                base = DispatchOutcome.failure(
                    base.error_code or "commit_state_unknown",
                    mutated=True,
                    retryable=False,
                    commit_unknown=base.commit_unknown,
                )
            if exc.code == "external_sync_pending" and exc.mutated:
                copy = (
                    "⚠️ Endringen er lagret lokalt, men synkronisering med "
                    "Google Calendar venter."
                )
            elif exc.commit_unknown:
                copy = (
                    "⚠️ Det er uklart om hele kalenderendringen ble fullført. "
                    "Jeg prøver ikke på nytt automatisk."
                )
            else:
                copy = "❌ Kalenderendringen kunne ikke fullføres."
        else:
            base = DispatchOutcome.failure(
                "commit_state_unknown",
                mutated=prior_mutated,
                commit_unknown=True,
            )
            copy = (
                "⚠️ Det er uklart om kalenderendringen ble fullført. "
                "Jeg prøver ikke på nytt automatisk."
            )
        return await self._finish(message, copy, base)

    @staticmethod
    def _strip_wrapping_quotes(value: str) -> str:
        stripped = value.strip()
        for left, right in (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’")):
            if stripped.startswith(left) and stripped.endswith(right) and len(stripped) >= 2:
                return stripped[1:-1].strip()
        return stripped

    def _normalize_calendar_target(self, target: str) -> str:
        target = re.sub(
            r"\s+(?:i|fra)\s+(?:kalender(?:en)?|calendar|gcal)\s*$",
            "",
            target.strip(),
            flags=re.IGNORECASE,
        )
        target = self._strip_wrapping_quotes(target.strip(" ."))
        bulk = re.match(r"^(alle?|all|every|both)\s+(.+)$", target, re.I)
        if bulk:
            return f"{bulk.group(1)} {self._strip_wrapping_quotes(bulk.group(2))}".strip()
        return target

    def _extract_search_text(self, content: str) -> str | None:
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = cleaned.replace("@inebotten", "").strip()
        command = rf"(?:{self.DELETE_COMMANDS}|{self.COMPLETE_COMMANDS})"
        calendar = r"(?:kalender(?:en)?|calendar|gcal)"
        for pattern in (
            rf"^{self.MUTATION_PREFIX}(?:{calendar})\s+{command}\s+(.+)$",
            rf"^{self.MUTATION_PREFIX}{command}\s+(.+)$",
        ):
            match = re.match(pattern, cleaned, re.I)
            if match:
                target = self._normalize_calendar_target(match.group(1))
                return target or None
        return None

    @staticmethod
    def _extract_target_index(search_text: str | None) -> int | None:
        if not search_text:
            return None
        if re.fullmatch(r"\d+", search_text.strip()):
            return int(search_text)
        scoped = re.fullmatch(r"(?:nummer|nr\.?)\s+(\d+)", search_text, re.I)
        return int(scoped.group(1)) if scoped else None

    def _legacy_target_payload(self, message) -> dict[str, Any] | None:
        target = self._extract_search_text(message.content)
        number = self._extract_target_index(target)
        if number:
            return {"number": number}
        return {"target": target} if target else None

    def _extract_calendar_search_query(self, content: str) -> str | None:
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = cleaned.replace("@inebotten", "").strip()
        match = re.match(
            r"^(?:søk|search)\s+(?:kalender|calendar)\s+(.+)$",
            cleaned,
            re.I,
        )
        if not match:
            return None
        query = match.group(1).strip()
        if query.lower().startswith(("på nett ", "web ", "nettet ")):
            return None
        return query or None

    def _parse_edit_command(
        self,
        content: str,
        *,
        reference_time: datetime,
    ) -> dict[str, Any] | None:
        cleaned = re.sub(r"<@!?\d+>", "", content or "")
        cleaned = cleaned.replace("@inebotten", "").strip()
        for keyword in (
            "kalender oppdater",
            "kalender oppdatere",
            "kalender rediger",
            "kalender redigere",
            "kalender endre",
            "oppdater",
            "oppdatere",
            "endre",
            "rediger",
            "redigere",
            "edit",
        ):
            if cleaned.lower().startswith(keyword):
                cleaned = cleaned[len(keyword) :].strip()
                break
        if ":" not in cleaned:
            return None
        prefix, raw_value = (part.strip() for part in cleaned.split(":", 1))
        if not raw_value:
            return None
        field = None
        target = prefix
        for label in sorted(self._EDIT_FIELD_MAP, key=len, reverse=True):
            pattern = rf"\b{re.escape(label)}$"
            if re.search(pattern, prefix, re.I):
                field = self._EDIT_FIELD_MAP[label]
                target = re.sub(pattern, "", prefix, flags=re.I).strip()
                break
        if not field or not target:
            return None
        value: Any = raw_value
        if field == "date":
            resolved = self.temporal_resolver.resolve(
                raw_value,
                reference=reference_time,
            )
            if resolved.errors or resolved.date is None:
                return None
            value = resolved.date
        elif field == "time":
            value = self.temporal_resolver.validate_time(raw_value)
            if value is None:
                return None
        elif field == "recurrence" and raw_value.casefold() in {
            "ingen",
            "none",
            "stopp",
            "av",
        }:
            value = None
        return {"target": target, "changes": {field: value}}

    def _snapshot(self, reference_time: datetime) -> tuple[dict[str, Any], ...]:
        rows = self.calendar.snapshot_pending_items(reference_time=reference_time)
        return tuple(dict(row) for row in rows)

    def _target_snapshot(
        self, reference_time: datetime
    ) -> tuple[dict[str, Any], ...]:
        snapshot = getattr(self.calendar, "snapshot_target_items", None)
        if not callable(snapshot):
            return self._snapshot(reference_time)
        rows = snapshot(reference_time=reference_time)
        return tuple(dict(row) for row in rows)

    def _resolve_target(
        self,
        payload: dict[str, Any],
        *,
        reference_time: datetime,
        allow_legacy_bulk: bool = False,
    ) -> tuple[str, list[dict[str, Any]]]:
        rows = list(self._target_snapshot(reference_time))
        for index, row in enumerate(rows, 1):
            row["_visible_index"] = index
        number = payload.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            return (
                ("found", [rows[number - 1]])
                if 1 <= number <= len(rows)
                else ("not_found", [])
            )
        target = payload.get("target")
        if not isinstance(target, str) or not target.strip():
            return "invalid", []
        normalized = target.strip()
        if normalized.isdigit():
            index = int(normalized)
            return (
                ("found", [rows[index - 1]])
                if 1 <= index <= len(rows)
                else ("not_found", [])
            )
        bulk = re.fullmatch(r"(?:alle?|all|every|both)\s+(.+)", normalized, re.I)
        if bulk and allow_legacy_bulk:
            normalized = self._strip_wrapping_quotes(bulk.group(1))
            bulk_mode = True
        else:
            bulk_mode = False
        exact_id = [row for row in rows if row.get("id") == normalized]
        if exact_id:
            return "found", exact_id
        folded = normalized.casefold()
        matches = [
            row
            for row in rows
            if folded in str(row.get("title", "")).casefold()
        ]
        if not matches:
            return "not_found", []
        if bulk_mode:
            return "bulk", matches
        return ("found", matches) if len(matches) == 1 else ("ambiguous", matches)

    @staticmethod
    def _format_match_prompt(query: str, matches, *, action: str) -> str:
        command = {"delete": "slett", "complete": "ferdig", "edit": "rediger"}[action]
        lines = [f'📋 Fant {len(matches)} treff for "{query}" i kalenderen:']
        for index, item in matches[:10]:
            time_text = f" kl. {item['time']}" if item.get("time") else ""
            lines.append(
                f"📅 {index}. {item.get('title', 'Uten tittel')} — "
                f"{item.get('date', '')}{time_text}"
            )
        lines.append(f"\nBruk `@inebotten {command} [nummer]` for å velge én bestemt.")
        return "\n".join(lines)

    def _indexed_matches(self, matches: list[dict[str, Any]]):
        return [
            (int(row.get("_visible_index", 0)), row)
            for row in matches
        ]

    def _format_list(
        self,
        reference_time: datetime,
        *,
        date_filter: str | None = None,
    ) -> str:
        snapshot = (
            self._target_snapshot(reference_time)
            if date_filter is not None
            else self._snapshot(reference_time)
        )
        rows = tuple(enumerate(snapshot, 1))
        if date_filter is not None:
            rows = tuple(
                (index, item)
                for index, item in rows
                if item.get("date") == date_filter
            )
        if not rows:
            if date_filter is not None:
                return (
                    "📭 **Ingen kalenderoppføringer "
                    f"{date_filter}.**"
                )
            return (
                "📭 **Kalenderen er tom**\n\n"
                "Du kan bare skrive hva som skal skje og når, for eksempel "
                "«møte med Kari i morgen klokka 10»."
            )
        lines = ["📅 **Kalender:**"]
        recurrence_labels = {
            "daily": "dag",
            "weekly": "uke",
            "biweekly": "2 uker",
            "monthly": "måned",
            "yearly": "år",
        }
        for index, item in rows[:10]:
            time_text = f" kl. {item['time']}" if item.get("time") else ""
            recurrence = (
                f" 🔄 {recurrence_labels.get(item.get('recurrence'), item.get('recurrence'))}"
                if item.get("recurrence")
                else ""
            )
            creator = f" ({item.get('username', 'Ukjent')})"
            marker = "📅" if item.get("gcal_event_id") or item.get("gcal_link") else "📌"
            lines.append(
                f"{marker} **{index}.** {item.get('title', 'Uten tittel')} — "
                f"_{item.get('date', '')}{time_text}_{creator}{recurrence}"
            )
        if len(rows) > 10:
            lines.append(f"\n… og {len(rows) - 10} til.")
        return "\n".join(lines)

    def _format_search(self, query: str, reference_time: datetime) -> str:
        query_folded = query.casefold()
        rows = [
            dict(row)
            for row in self.calendar.search_items(query)
            if query_folded in str(row.get("title", "")).casefold()
        ]
        if not rows:
            return f"🔎 Fant ingen kalenderoppføringer som matcher **{query}**."
        positions = {
            row.get("id"): index
            for index, row in enumerate(self._snapshot(reference_time), 1)
        }
        lines = [f'🔎 **Kalenderoppføringer som matcher "{query}":**']
        for row in rows[:10]:
            time_text = f" kl. {row['time']}" if row.get("time") else ""
            position = positions.get(row.get("id"))
            prefix = f"**{position}.** " if position is not None else ""
            marker = "✅" if row.get("completed") else "📌"
            lines.append(
                f"{marker} {prefix}{row.get('title', '')} — "
                f"_{row.get('date', '')}{time_text}_"
            )
        if len(rows) > 10:
            lines.append(f"\n… og {len(rows) - 10} til.")
        lines.append("\nNumrene matcher kalenderlista.")
        return "\n".join(lines)

    async def handle_save_request(
        self,
        message,
        title,
        date,
        time,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        clean_title = re.sub(
            r"^(?:å|at|om)\s+|\s+(?:på|kl|i|ved|om)\s*$",
            "",
            str(title).strip(),
            flags=re.I,
        )
        payload = {
            "title": clean_title[:1].upper() + clean_title[1:] if clean_title else "Uten tittel",
            "date": date,
            "time": time if time and ":" in str(time) else "09:00",
        }
        return await self.handle_calendar_item(
            message,
            payload,
            reference_time=reference_time,
        )

    async def handle_calendar_item(
        self,
        message,
        item_data: dict[str, Any] | None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        parser = getattr(self.nlp_parser, "parse_event", None)
        payload = self._typed_or_legacy(
            message,
            item_data,
            intent=BotIntent.CALENDAR_ITEM,
            legacy_factory=lambda: (
                parser(message.content, reference_time=captured)
                if callable(parser)
                else None
            ),
        )
        if not isinstance(payload, dict):
            return await self._finish(
                message,
                self.TEMPORAL_CLARIFICATION,
                DispatchOutcome.failure("invalid_payload"),
            )

        canonical = dict(payload)
        offset = canonical.pop("days_offset", None)
        if offset is not None:
            if isinstance(offset, bool) or not isinstance(offset, int):
                return await self._finish(
                    message,
                    self.TEMPORAL_CLARIFICATION,
                    DispatchOutcome.failure("invalid_payload"),
                )
            offset_date = (
                captured.astimezone(OSLO).date() + timedelta(days=offset)
            ).strftime("%d.%m.%Y")
            if canonical.get("date") not in {None, offset_date}:
                return await self._finish(
                    message,
                    self.TEMPORAL_CLARIFICATION,
                    DispatchOutcome.failure("invalid_payload"),
                )
            canonical["date"] = offset_date

        validation = self.temporal_resolver.validate_fields(
            canonical.get("date"),
            canonical.get("time"),
            reference=captured,
        )
        title = canonical.get("title")
        if (
            not isinstance(title, str)
            or not title.strip()
            or validation.errors
            or validation.date is None
        ):
            return await self._finish(
                message,
                self.TEMPORAL_CLARIFICATION,
                DispatchOutcome.failure("invalid_payload"),
            )

        try:
            item = await self.calendar.add_item_result(
                self.get_guild_id(message),
                message.author.id,
                message.author.name,
                title.strip(),
                validation.date,
                validation.time,
                canonical.get("recurrence"),
                canonical.get("recurrence_day"),
                channel_id=getattr(getattr(message, "channel", None), "id", None),
                item_type=canonical.get("type", "event"),
                description=canonical.get("description"),
                rrule_day=canonical.get("rrule_day"),
                reference_time=captured,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except ValueError:
            return await self._finish(
                message,
                self.TEMPORAL_CLARIFICATION,
                DispatchOutcome.failure("invalid_payload"),
            )
        except Exception as exc:
            return await self._mutation_exception(message, exc)

        if not isinstance(item, dict) or not item:
            return await self._finish(
                message,
                "❌ Kalenderoppføringen ble ikke lagret.",
                DispatchOutcome.failure("manager_rejected"),
            )
        return await self._finish(
            message,
            self.calendar.format_single_item(item),
            DispatchOutcome.success(mutated=True),
        )

    async def handle_list(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        try:
            canonical = (
                validate_intent_payload(BotIntent.CALENDAR_LIST, payload)
                if payload is not None
                else {}
            )
        except (PayloadValidationError, TypeError, ValueError):
            return await self._finish(
                message,
                "❌ Kalenderfilteret er ugyldig.",
                DispatchOutcome.failure("invalid_payload"),
            )
        date_filter = canonical.get("date")
        if date_filter is not None and not is_supported_calendar_read_date(
            date_filter,
            reference_time=captured,
        ):
            return await self._finish(
                message,
                (
                    "📅 Kalenderlisten viser i dag og fremover. "
                    "Velg en dato fra i dag eller senere."
                ),
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            copy = self._format_list(captured, date_filter=date_filter)
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            copy = "❌ Kalenderen kunne ikke leses akkurat nå."
            base = DispatchOutcome.failure("manager_rejected", retryable=True)
        return await self._finish(message, copy, base)

    async def handle_search(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        if payload is None:
            self.monitor.nlu_metrics.record_legacy_payload_fallback("calendar")
            query = self._extract_calendar_search_query(message.content)
        else:
            query = payload.get("query") if isinstance(payload, dict) else None
        if not isinstance(query, str) or not query.strip():
            return await self._finish(
                message,
                "🔎 Skriv hva du vil søke etter i kalenderen.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            copy = self._format_search(query.strip(), captured)
            base = DispatchOutcome.success(mutated=False)
        except Exception:
            copy = "❌ Kalenderen kunne ikke søkes i akkurat nå."
            base = DispatchOutcome.failure("manager_rejected", retryable=True)
        return await self._finish(message, copy, base)

    async def handle_delete(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        legacy = payload is None
        canonical = self._typed_or_legacy(
            message,
            payload,
            intent=BotIntent.CALENDAR_DELETE,
            legacy_factory=lambda: self._legacy_target_payload(message),
        )
        if not isinstance(canonical, dict):
            return await self._finish(
                message,
                "🗑️ Si hvilken kalenderoppføring du vil slette.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            status, matches = self._resolve_target(
                canonical,
                reference_time=captured,
                allow_legacy_bulk=legacy,
            )
        except Exception:
            return await self._finish(
                message,
                "❌ Kalenderen kunne ikke leses akkurat nå.",
                DispatchOutcome.failure("manager_rejected", retryable=True),
            )
        query = str(canonical.get("target") or canonical.get("number") or "")
        if status == "ambiguous":
            return await self._finish(
                message,
                self._format_match_prompt(
                    query,
                    self._indexed_matches(matches),
                    action="delete",
                ),
                DispatchOutcome.failure("ambiguous_target"),
            )
        if status == "not_found":
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i kalenderen.',
                DispatchOutcome.failure("not_found", retryable=True),
            )
        if status not in {"found", "bulk"} or not matches:
            return await self._finish(
                message,
                "🗑️ Si hvilken kalenderoppføring du vil slette.",
                DispatchOutcome.failure("invalid_payload"),
            )

        results = []
        prior_mutated = False
        try:
            for row in matches:
                result = await self.calendar.delete_item_result(
                    self.get_guild_id(message),
                    item_id=row["id"],
                    reference_time=captured,
                )
                results.append(result)
                prior_mutated = prior_mutated or bool(
                    int(result.get("deleted_count", 0))
                    or int(result.get("pending_count", 0))
                )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(
                message,
                exc,
                prior_mutated=prior_mutated,
            )
        except ValueError:
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i kalenderen.',
                DispatchOutcome.failure(
                    "not_found",
                    mutated=prior_mutated,
                    retryable=not prior_mutated,
                ),
            )
        except Exception as exc:
            return await self._mutation_exception(
                message,
                exc,
                prior_mutated=prior_mutated,
            )

        requested = sum(int(result.get("requested_count", 0)) for result in results)
        deleted = sum(int(result.get("deleted_count", 0)) for result in results)
        pending = sum(int(result.get("pending_count", 0)) for result in results)
        if requested == 0:
            base = DispatchOutcome.failure("not_found", retryable=True)
            copy = f'❌ Fant ikke "{query}" i kalenderen.'
        elif pending:
            base = DispatchOutcome.failure(
                "partial_delete_pending" if deleted else "external_delete_pending",
                mutated=True,
            )
            copy = (
                f"⚠️ Slettet {deleted}, men {pending} venter på "
                "Google Calendar-sletting."
            )
        else:
            base = DispatchOutcome.success(mutated=deleted > 0)
            title = matches[0].get("title", "oppføringen")
            copy = (
                f"✅ **Slettet {deleted} oppføringer!**"
                if len(matches) > 1
                else f"✅ **Slettet! {title}**"
            )
        return await self._finish(message, copy, base)

    async def handle_complete(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        legacy = payload is None
        canonical = self._typed_or_legacy(
            message,
            payload,
            intent=BotIntent.CALENDAR_COMPLETE,
            legacy_factory=lambda: self._legacy_target_payload(message),
        )
        if not isinstance(canonical, dict):
            return await self._finish(
                message,
                "✅ Si hvilken kalenderoppføring som er fullført.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            status, matches = self._resolve_target(
                canonical,
                reference_time=captured,
                allow_legacy_bulk=legacy,
            )
        except Exception:
            return await self._finish(
                message,
                "❌ Kalenderen kunne ikke leses akkurat nå.",
                DispatchOutcome.failure("manager_rejected", retryable=True),
            )
        query = str(canonical.get("target") or canonical.get("number") or "")
        if status == "ambiguous":
            return await self._finish(
                message,
                self._format_match_prompt(
                    query,
                    self._indexed_matches(matches),
                    action="complete",
                ),
                DispatchOutcome.failure("ambiguous_target"),
            )
        if status == "not_found":
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i kalenderen.',
                DispatchOutcome.failure("not_found", retryable=True),
            )
        if status not in {"found", "bulk"} or not matches:
            return await self._finish(
                message,
                "✅ Si hvilken kalenderoppføring som er fullført.",
                DispatchOutcome.failure("invalid_payload"),
            )

        completed = []
        recurring = False
        try:
            for row in matches:
                success, title, next_date = await self.calendar.complete_item_result(
                    self.get_guild_id(message),
                    item_id=row["id"],
                    reference_time=captured,
                )
                if success:
                    completed.append(title or row.get("title", "oppføringen"))
                    recurring = recurring or bool(next_date)
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(
                message,
                exc,
                prior_mutated=bool(completed),
            )
        except ValueError:
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i kalenderen.',
                DispatchOutcome.failure(
                    "not_found",
                    mutated=bool(completed),
                    retryable=not completed,
                ),
            )
        except Exception as exc:
            return await self._mutation_exception(
                message,
                exc,
                prior_mutated=bool(completed),
            )

        if not completed:
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i kalenderen.',
                DispatchOutcome.failure("not_found", retryable=True),
            )
        if len(completed) == 1:
            copy = f"✅ **Fullført! {completed[0]}**\n\nBra jobba! 🎉"
        else:
            copy = f"✅ **Fullført {len(completed)}!**\n" + ", ".join(completed[:3])
        if recurring:
            copy += "\n🔄 Gjentakende oppføringer er flyttet til neste dato."
        return await self._finish(
            message,
            copy,
            DispatchOutcome.success(mutated=True),
        )

    async def handle_edit(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        canonical = self._typed_or_legacy(
            message,
            payload,
            intent=BotIntent.CALENDAR_EDIT,
            legacy_factory=lambda: self._parse_edit_command(
                message.content,
                reference_time=captured,
            ),
        )
        if not isinstance(canonical, dict) or not isinstance(canonical.get("changes"), dict):
            return await self._finish(
                message,
                self.loc.t("calendar_edit_invalid"),
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            status, matches = self._resolve_target(
                {"target": canonical.get("target")},
                reference_time=captured,
            )
        except Exception:
            return await self._finish(
                message,
                "❌ Kalenderen kunne ikke leses akkurat nå.",
                DispatchOutcome.failure("manager_rejected", retryable=True),
            )
        query = str(canonical.get("target") or "")
        if status == "ambiguous":
            return await self._finish(
                message,
                self._format_match_prompt(
                    query,
                    self._indexed_matches(matches),
                    action="edit",
                ),
                DispatchOutcome.failure("ambiguous_target"),
            )
        if status != "found" or not matches:
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i den synlige kalenderlisten.',
                DispatchOutcome.failure("not_found", retryable=True),
            )
        target = matches[0]
        changes = dict(canonical["changes"])
        if "date" in changes or "time" in changes:
            validation = self.temporal_resolver.validate_fields(
                changes.get("date", target.get("date")),
                changes.get("time", target.get("time")),
                reference=captured,
            )
            if validation.errors or validation.date is None:
                return await self._finish(
                    message,
                    self.TEMPORAL_CLARIFICATION,
                    DispatchOutcome.failure("invalid_payload"),
                )
            if "date" in changes:
                changes["date"] = validation.date
            if "time" in changes:
                changes["time"] = validation.time
        try:
            updated = await self.calendar.edit_item_result(
                item_id=target["id"],
                reference_time=captured,
                **changes,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except ValueError:
            return await self._finish(
                message,
                f'❌ Fant ikke "{query}" i kalenderen.',
                DispatchOutcome.failure("not_found", retryable=True),
            )
        except Exception as exc:
            return await self._mutation_exception(message, exc)
        if not isinstance(updated, dict) or not updated:
            return await self._finish(
                message,
                "❌ Kalenderoppføringen ble ikke oppdatert.",
                DispatchOutcome.failure("manager_rejected"),
            )
        return await self._finish(
            message,
            self.loc.t("calendar_edit_success", title=updated.get("title", "")),
            DispatchOutcome.success(mutated=True),
        )

    def _legacy_clear_payload(self, message) -> dict[str, Any] | None:
        cleaned = re.sub(r"<@!?\d+>", "", message.content or "")
        cleaned = cleaned.replace("@inebotten", "").lower()
        confirmed = any(
            re.search(rf"\b{re.escape(keyword)}\b", cleaned)
            for keyword in self.CLEAR_CONFIRM_KEYWORDS
        )
        count_match = re.search(r"\b(?:bekreft|confirm)\s+(\d+)\b", cleaned)
        if not confirmed or count_match is None:
            return None
        try:
            expected = len(self.calendar.snapshot_all_item_ids())
        except Exception:
            return None
        return {"all": True} if int(count_match.group(1)) == expected else None

    async def handle_clear(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        if payload is None:
            self.monitor.nlu_metrics.record_legacy_payload_fallback("calendar")
            canonical = self._legacy_clear_payload(message)
            if canonical is None:
                try:
                    count = len(self.calendar.snapshot_all_item_ids())
                except Exception:
                    count = 0
                return await self._finish(
                    message,
                    "⚠️ **Dette sletter hele kalenderen.**\n"
                    f"Akkurat nå ligger det {count} elementer der.\n"
                    f"Send `@inebotten tøm kalender bekreft {count}` hvis du virkelig vil gjøre det.",
                    DispatchOutcome.failure("confirmation_required"),
                )
        else:
            canonical = payload
        if not isinstance(canonical, dict) or canonical.get("all") is not True:
            return await self._finish(
                message,
                "⚠️ Hele kalenderen ble ikke tømt fordi bekreftelsen manglet.",
                DispatchOutcome.failure("invalid_payload"),
            )
        try:
            result = await self.calendar.clear_calendar_result(
                self.get_guild_id(message),
                reference_time=captured,
            )
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)
        requested = int(result.get("requested_count", 0))
        deleted = int(result.get("deleted_count", 0))
        failed = int(result.get("failed_count", 0))
        if requested == 0:
            base = DispatchOutcome.success(mutated=False)
            copy = "📭 Kalenderen er allerede tom."
        elif failed:
            base = DispatchOutcome.failure(
                "partial_delete_pending" if deleted else "external_delete_pending",
                mutated=True,
            )
            copy = f"⚠️ Slettet {deleted}, men {failed} venter på Google Calendar-sletting."
        else:
            base = DispatchOutcome.success(mutated=deleted > 0)
            copy = f"🗑️ **Kalenderen er tømt!** Slettet {deleted} elementer."
        return await self._finish(message, copy, base)

    @staticmethod
    def _sync_base(result) -> DispatchOutcome:
        if result.ok:
            return DispatchOutcome.success(mutated=bool(result.mutated))
        code = result.error_code or "external_read_failed"
        bounded = code if code in _MANAGER_ERROR_CODES else "commit_state_unknown"
        commit_unknown = bool(result.commit_unknown or bounded == "commit_state_unknown")
        return DispatchOutcome.failure(
            bounded,
            mutated=bool(result.mutated),
            retryable=(
                bounded in {"external_read_failed", "storage_write_failed"}
                and not result.mutated
                and not commit_unknown
            ),
            commit_unknown=commit_unknown,
        )

    async def _sync_once(
        self,
        message,
        *,
        reference_time: datetime,
    ):
        return await self.calendar.sync_from_gcal_result(
            default_guild_id=self.get_guild_id(message),
            default_channel_id=getattr(getattr(message, "channel", None), "id", None),
            reference_time=reference_time,
        )

    async def handle_sync(
        self,
        message,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        try:
            result = await self._sync_once(message, reference_time=captured)
        except (ManagerMutationCancelled, ManagerMutationError) as exc:
            return await self._mutation_exception(message, exc)
        except Exception as exc:
            return await self._mutation_exception(message, exc)
        base = self._sync_base(result)
        if result.ok:
            changed = int(result.added) + int(result.updated) + int(result.removed)
            copy = (
                f"✅ Synkronisering ferdig. Oppdaterte {changed} elementer."
                if changed
                else "✅ Synkronisering ferdig. Ingen nye endringer funnet."
            )
        elif result.commit_unknown:
            copy = "⚠️ Det er uklart om Google Calendar-synkroniseringen ble fullført."
        elif result.error_code in {"integration_disabled", "not_configured"}:
            copy = "❌ Google Calendar er ikke konfigurert eller koblet til ennå."
        else:
            copy = "❌ Kunne ikke hente kalenderendringer fra Google akkurat nå."
        return await self._finish(message, copy, base)

    @staticmethod
    def _external_auth_base(
        result: ExternalMutationResult,
        *,
        exchange: bool,
    ) -> DispatchOutcome:
        mutated = result.state is ExternalCommitState.CHANGED or (
            exchange and result.state is ExternalCommitState.UNKNOWN
        )
        if result.ok and result.state is ExternalCommitState.CHANGED:
            return DispatchOutcome.success(mutated=True)
        code = result.error_code if result.error_code in _AUTH_ERROR_CODES else "commit_state_unknown"
        commit_unknown = result.state is ExternalCommitState.UNKNOWN or code == "commit_state_unknown"
        return DispatchOutcome.failure(
            code,
            mutated=mutated,
            commit_unknown=commit_unknown,
        )

    @staticmethod
    def _auth_error_copy(code: str | None) -> str:
        if code in {"missing_auth_flow", "auth_flow_expired", "invalid_auth_flow"}:
            return "❌ Start en ny Google Calendar-pålogging og bruk den nye koden."
        if code in {"missing_credentials", "integration_disabled"}:
            return "❌ Google Calendar-oppsettet mangler nødvendige klientopplysninger."
        if code in {"requester_mismatch", "channel_mismatch"}:
            return "❌ Denne kalenderkoden hører til en annen påloggingsøkt."
        if code == "token_storage_failed":
            return "⚠️ Google godtok koden, men tokenet kunne ikke lagres. Start på nytt."
        if code == "external_commit_unknown":
            return "⚠️ Det er uklart om Google godtok koden. Start en ny påloggingsøkt."
        return "❌ Google Calendar-påloggingen kunne ikke fullføres."

    async def handle_auth(
        self,
        message,
        payload: dict[str, Any] | None = None,
        *,
        reference_time: datetime | None = None,
    ) -> DispatchOutcome:
        captured = self._capture_reference(reference_time)
        if payload is None:
            self.monitor.nlu_metrics.record_legacy_payload_fallback("calendar")
            cleaned = re.sub(r"<@!?\d+>", "", message.content or "")
            match = re.search(r"(?:kode|code|auth|login)\s+([^\s]+)\s*$", cleaned, re.I)
            canonical = {"auth_code": match.group(1)} if match else {}
        elif isinstance(payload, dict):
            canonical = payload
        else:
            canonical = {}
        code = canonical.get("auth_code")
        if code is not None and (not isinstance(code, str) or not code.strip()):
            return await self._finish(
                message,
                "❌ Kalenderkoden er ugyldig.",
                DispatchOutcome.failure("invalid_payload"),
            )
        gcal = getattr(self.calendar, "gcal", None)
        if gcal is None:
            return await self._finish(
                message,
                "❌ Google Calendar-integrasjonen er ikke tilgjengelig.",
                DispatchOutcome.failure("integration_disabled"),
            )
        requester_id = getattr(getattr(message, "author", None), "id", None)
        channel_id = getattr(getattr(message, "channel", None), "id", None)
        exchange = isinstance(code, str)
        monitor_coordinator = getattr(self.monitor, "mutation_coordinator", None)
        calendar_coordinator = getattr(self.calendar, "mutation_coordinator", None)
        if (
            monitor_coordinator is not None
            and calendar_coordinator is not None
            and monitor_coordinator is not calendar_coordinator
        ):
            return await self._finish(
                message,
                "❌ Kalenderintegrasjonen har en intern koordineringsfeil.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )
        coordinator = monitor_coordinator or calendar_coordinator
        if coordinator is None:
            return await self._finish(
                message,
                "❌ Kalenderintegrasjonen mangler skrivekoordinering.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )

        external: ExternalMutationResult | None = None
        sync = None
        try:
            async with coordinator.hold(CALENDAR_SHARED_SCOPE):
                if exchange:
                    external = await gcal.exchange_code_result(
                        code.strip(),
                        requester_id=requester_id,
                        channel_id=channel_id,
                    )
                else:
                    external = await gcal.get_auth_url_result(
                        requester_id=requester_id,
                        channel_id=channel_id,
                    )
                if exchange and external.ok:
                    # The coordinator is task-reentrant, so sync re-enters the
                    # same calendar scope without opening an auth/create race.
                    sync = await self._sync_once(
                        message,
                        reference_time=captured,
                    )
        except ExternalOperationCancelled as exc:
            raise DispatchCancelled(
                self._external_auth_base(exc.result, exchange=exchange)
            ) from None
        except ManagerMutationCancelled as exc:
            self._raise_manager_cancel(
                exc,
                prior_mutated=bool(
                    exchange
                    and external is not None
                    and external.state is ExternalCommitState.CHANGED
                ),
            )
        except ManagerMutationError as exc:
            prior_mutated = bool(
                exchange
                and external is not None
                and external.state is ExternalCommitState.CHANGED
            )
            return await self._mutation_exception(
                message,
                exc,
                prior_mutated=prior_mutated,
            )
        except Exception:
            prior_mutated = bool(
                exchange
                and external is not None
                and external.state is ExternalCommitState.CHANGED
            )
            return await self._finish(
                message,
                "⚠️ Det er uklart om Google Calendar-påloggingen ble endret.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    mutated=prior_mutated,
                    commit_unknown=True,
                ),
            )

        if external is None:
            return await self._finish(
                message,
                "⚠️ Det er uklart om Google Calendar-påloggingen ble endret.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    commit_unknown=True,
                ),
            )
        base = self._external_auth_base(external, exchange=exchange)
        if not external.ok:
            return await self._finish(
                message,
                self._auth_error_copy(external.error_code),
                base,
            )
        if not exchange:
            auth_url = external.value if isinstance(external.value, str) else None
            if not auth_url:
                return await self._finish(
                    message,
                    "❌ Google Calendar-påloggingen kunne ikke startes.",
                    DispatchOutcome.failure("auth_flow_failed"),
                )
            copy = (
                "🔐 **Koble til Google Calendar**\n\n"
                f"Åpne lenken og logg inn:\n{auth_url}\n\n"
                "Send deretter koden med `@inebotten kalender kode <kode>`."
            )
            return await self._finish(message, copy, base)

        if sync is None:
            return await self._finish(
                message,
                "✅ Google Calendar er koblet til, men første synkronisering er uklar.",
                DispatchOutcome.failure(
                    "commit_state_unknown",
                    mutated=True,
                    commit_unknown=True,
                ),
            )
        if sync.ok:
            changed = int(sync.added) + int(sync.updated) + int(sync.removed)
            return await self._finish(
                message,
                f"✅ Google Calendar er koblet til og synkronisert ({changed} endringer).",
                DispatchOutcome.success(mutated=True),
            )
        sync_base = self._sync_base(sync)
        combined = DispatchOutcome.failure(
            sync_base.error_code or "commit_state_unknown",
            mutated=True,
            commit_unknown=sync_base.commit_unknown,
        )
        return await self._finish(
            message,
            "✅ Google Calendar er koblet til, men første synkronisering feilet.",
            combined,
        )
