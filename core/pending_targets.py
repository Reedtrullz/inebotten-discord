"""Freeze mutable display targets and revalidate them before dispatch."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime

from core.intent_models import BotIntent, IntentResult
from core.message_context import ConversationKey, RoutingContext, domain_scope_id
from core.mutation_coordinator import (
    BIRTHDAY_STORE_SCOPE,
    CALENDAR_SHARED_SCOPE,
    MEMORY_STORE_SCOPE,
    POLL_STORE_SCOPE,
    QUOTE_STORE_SCOPE,
    REMINDER_STORE_SCOPE,
    WATCHLIST_STORE_SCOPE,
    MutationCoordinator,
    MutationScope,
)
from core.pending_actions import PendingTargetFamily, PendingTargetGuard


@dataclass(frozen=True, slots=True)
class FrozenPendingRoute:
    """A detached route paired with the proposition the user will confirm."""

    route: IntentResult
    guard: PendingTargetGuard | None


class PendingTargetError(ValueError):
    """Typed fail-closed target resolution error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PendingTargetResolver:
    """Convert mutable positions to stable delayed-action capabilities."""

    _CALENDAR_FIELDS = (
        "title",
        "date",
        "time",
        "type",
        "description",
        "completed",
        "recurrence",
        "recurrence_day",
        "rrule_day",
        "recurrence_sequence",
    )
    _REMINDER_FIELDS = (
        "text",
        "due_at",
        "due_date",
        "time",
        "timezone",
        "recurrence",
        "recurrence_anchor_local",
        "recurrence_day",
        "rrule_day",
        "recurrence_sequence",
        "completed",
    )
    _POLL_FIELDS = ("question", "options", "status")
    _WATCHLIST_FIELDS = ("title", "type", "genre", "comment")
    _QUOTE_FIELDS = ("text", "author")
    _DETAIL_LABELS = {
        "title": "tittel",
        "text": "tekst",
        "date": "dato",
        "time": "tid",
        "due_at": "tidspunkt",
        "due_date": "dato",
        "timezone": "tidssone",
        "type": "type",
        "description": "beskrivelse",
        "completed": "status",
        "recurrence": "gjentakelse",
        "recurrence_anchor_local": "gjentakelsesstart",
        "recurrence_day": "gjentakelsesdag",
        "rrule_day": "gjentakelsesdag",
        "recurrence_sequence": "forekomst",
        "question": "spørsmål",
        "options": "alternativer",
        "status": "status",
        "genre": "sjanger",
        "comment": "kommentar",
        "author": "forfatter",
    }

    _TARGETED = frozenset(
        {
            BotIntent.CALENDAR_EDIT,
            BotIntent.CALENDAR_DELETE,
            BotIntent.CALENDAR_COMPLETE,
            BotIntent.CALENDAR_CLEAR,
            BotIntent.REMINDER_EDIT,
            BotIntent.REMINDER_DELETE,
            BotIntent.REMINDER_COMPLETE,
            BotIntent.POLL_VOTE,
            BotIntent.POLL_EDIT,
            BotIntent.POLL_DELETE,
            BotIntent.POLL_CLOSE,
            BotIntent.QUOTE_EDIT,
            BotIntent.QUOTE_DELETE,
            BotIntent.BIRTHDAY_CREATE,
            BotIntent.BIRTHDAY_EDIT,
            BotIntent.MEMORY_DELETE,
        }
    )

    _MUTATION_SCOPES: tuple[
        tuple[frozenset[BotIntent], MutationScope], ...
    ] = (
        (
            frozenset(
                {
                    BotIntent.CALENDAR_ITEM,
                    BotIntent.CALENDAR_EDIT,
                    BotIntent.CALENDAR_DELETE,
                    BotIntent.CALENDAR_COMPLETE,
                    BotIntent.CALENDAR_CLEAR,
                    BotIntent.CALENDAR_SYNC,
                    BotIntent.CALENDAR_AUTH,
                }
            ),
            CALENDAR_SHARED_SCOPE,
        ),
        (
            frozenset(
                {
                    BotIntent.REMINDER_CREATE,
                    BotIntent.REMINDER_EDIT,
                    BotIntent.REMINDER_DELETE,
                    BotIntent.REMINDER_COMPLETE,
                }
            ),
            REMINDER_STORE_SCOPE,
        ),
        (
            frozenset(
                {
                    BotIntent.POLL_CREATE,
                    BotIntent.POLL_VOTE,
                    BotIntent.POLL_EDIT,
                    BotIntent.POLL_DELETE,
                    BotIntent.POLL_CLOSE,
                }
            ),
            POLL_STORE_SCOPE,
        ),
        (frozenset({BotIntent.WATCHLIST}), WATCHLIST_STORE_SCOPE),
        (
            frozenset(
                {BotIntent.QUOTE, BotIntent.QUOTE_EDIT, BotIntent.QUOTE_DELETE}
            ),
            QUOTE_STORE_SCOPE,
        ),
        (
            frozenset({BotIntent.BIRTHDAY_CREATE, BotIntent.BIRTHDAY_EDIT}),
            BIRTHDAY_STORE_SCOPE,
        ),
        (
            frozenset({BotIntent.MEMORY_DELETE, BotIntent.SET_LOCATION}),
            MEMORY_STORE_SCOPE,
        ),
        (frozenset({BotIntent.PROFILE}), ("profile", "global")),
    )

    def __init__(
        self,
        monitor,
        *,
        coordinator: MutationCoordinator,
    ) -> None:
        self.monitor = monitor
        self.coordinator = coordinator

    @staticmethod
    def _aware(reference_time: datetime) -> None:
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise PendingTargetError("naive_reference_time")

    @staticmethod
    def _project(
        row: Mapping[str, object],
        fields: tuple[str, ...],
    ) -> dict[str, object]:
        return {field: copy.deepcopy(row.get(field)) for field in fields}

    @staticmethod
    def _rows(value: object) -> tuple[dict[str, object], ...]:
        if not isinstance(value, tuple):
            raise PendingTargetError("invalid_target_state")
        rows: list[dict[str, object]] = []
        for row in value:
            if not isinstance(row, Mapping):
                raise PendingTargetError("invalid_target_state")
            rows.append(copy.deepcopy(dict(row)))
        return tuple(rows)

    @staticmethod
    def _poll_projection(row: Mapping[str, object]) -> dict[str, object]:
        raw_options = row.get("options")
        if not isinstance(raw_options, list):
            raise PendingTargetError("invalid_target_state")
        options: list[str] = []
        for option in raw_options:
            value = option.get("text") if isinstance(option, Mapping) else option
            if not isinstance(value, str) or not value.strip():
                raise PendingTargetError("invalid_target_state")
            options.append(value.strip())
        return {
            "question": copy.deepcopy(row.get("question")),
            "options": options,
            "status": copy.deepcopy(row.get("status")),
        }

    @staticmethod
    def _digest(value: object) -> str:
        try:
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise PendingTargetError("invalid_target_state") from None
        return hashlib.sha256(canonical).hexdigest()

    def _proposition_hash(self, route: IntentResult) -> str:
        return self._digest(
            {
                "intent": route.intent.value,
                "payload": route.payload,
            }
        )

    def rebind_corrected(
        self,
        old_route: IntentResult,
        new_route: IntentResult,
        guard: PendingTargetGuard,
    ) -> PendingTargetGuard:
        """Bind a validated correction while preserving its frozen target."""

        if not isinstance(guard, PendingTargetGuard):
            raise PendingTargetError("target_changed")
        if (
            old_route.intent is not new_route.intent
            or self._expected_guard_family(old_route) is not guard.family
            or self._expected_guard_family(new_route) is not guard.family
            or guard.proposition_hash != self._proposition_hash(old_route)
        ):
            raise PendingTargetError("target_changed")
        binding = {
            BotIntent.CALENDAR_EDIT: ("calendar_edit", ("target",)),
            BotIntent.REMINDER_EDIT: (
                "reminder",
                ("action", "reminder_id"),
            ),
            BotIntent.POLL_EDIT: ("poll_edit", ("poll_id",)),
        }.get(old_route.intent)
        if binding is None:
            raise PendingTargetError("unsupported_correction")
        key, immutable_fields = binding
        old_inner = self._inner(old_route, key)
        new_inner = self._inner(new_route, key)
        if any(
            old_inner.get(field) != new_inner.get(field)
            for field in immutable_fields
        ):
            raise PendingTargetError("target_changed")
        return replace(
            guard,
            proposition_hash=self._proposition_hash(new_route),
        )

    @staticmethod
    def _inner(route: IntentResult, key: str) -> dict[str, object]:
        value = route.payload.get(key)
        if not isinstance(value, Mapping):
            raise PendingTargetError("invalid_target_payload")
        return copy.deepcopy(dict(value))

    @staticmethod
    def _replace_inner(
        route: IntentResult,
        key: str,
        inner: Mapping[str, object],
    ) -> IntentResult:
        payload = copy.deepcopy(route.payload)
        payload[key] = copy.deepcopy(dict(inner))
        return replace(route, payload=payload)

    @staticmethod
    def _id(row: Mapping[str, object], *names: str) -> str:
        for name in names:
            value = row.get(name)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                shown = str(value).strip()
                if shown:
                    return shown
        raise PendingTargetError("invalid_target_state")

    @staticmethod
    def _position(value: object, size: int) -> int | None:
        if value == "siste":
            return size - 1 if size else None
        if isinstance(value, int) and not isinstance(value, bool):
            return value - 1 if 1 <= value <= size else None
        if isinstance(value, str) and value.isdecimal():
            number = int(value)
            return number - 1 if 1 <= number <= size else None
        return None

    def _select(
        self,
        rows: tuple[dict[str, object], ...],
        selector: object,
        *,
        id_names: tuple[str, ...],
        title_field: str,
    ) -> tuple[int, dict[str, object]]:
        position = self._position(selector, len(rows))
        if position is not None:
            selected = rows[position]
            title = selected.get(title_field)
            if not isinstance(title, str) or not title.strip():
                raise PendingTargetError("invalid_target_state")
            return position, selected
        if not isinstance(selector, str) or not selector.strip():
            raise PendingTargetError("target_not_found")
        folded = selector.strip().casefold()
        matches = [
            (index, row)
            for index, row in enumerate(rows)
            if any(
                str(row.get(name, "")).casefold() == folded
                for name in id_names
            )
            or str(row.get(title_field, "")).strip().casefold() == folded
        ]
        if not matches:
            matches = [
                (index, row)
                for index, row in enumerate(rows)
                if folded
                in str(row.get(title_field, "")).strip().casefold()
            ]
        if not matches:
            raise PendingTargetError("target_not_found")
        if len(matches) != 1:
            raise PendingTargetError("ambiguous_target")
        selected_position, selected = matches[0]
        title = selected.get(title_field)
        if not isinstance(title, str) or not title.strip():
            raise PendingTargetError("invalid_target_state")
        return selected_position, selected

    @staticmethod
    def _detail_value(field: str, value: object) -> str:
        if field == "completed" and isinstance(value, bool):
            return "fullført" if value else "ikke fullført"
        if isinstance(value, list):
            return "; ".join(
                f"{index}. {item}"
                for index, item in enumerate(value, start=1)
            )
        return str(value)

    @classmethod
    def _detail(
        cls,
        row: Mapping[str, object],
        fields: tuple[str, ...],
    ) -> str:
        parts = []
        for field in fields:
            value = row.get(field)
            if value in (None, "", [], {}):
                continue
            label = cls._DETAIL_LABELS.get(field, field)
            parts.append(f"{label}: {cls._detail_value(field, value)}")
        return "; ".join(parts) or "valgt element"

    def _requires_guard(self, route: IntentResult) -> bool:
        return self._expected_guard_family(route) is not None

    def _expected_guard_family(
        self,
        route: IntentResult,
    ) -> PendingTargetFamily | None:
        if route.intent in {
            BotIntent.CALENDAR_EDIT,
            BotIntent.CALENDAR_DELETE,
            BotIntent.CALENDAR_COMPLETE,
            BotIntent.CALENDAR_CLEAR,
        }:
            return PendingTargetFamily.CALENDAR
        if route.intent in {
            BotIntent.REMINDER_EDIT,
            BotIntent.REMINDER_DELETE,
            BotIntent.REMINDER_COMPLETE,
        }:
            return PendingTargetFamily.REMINDER
        if route.intent in {
            BotIntent.POLL_VOTE,
            BotIntent.POLL_EDIT,
            BotIntent.POLL_DELETE,
            BotIntent.POLL_CLOSE,
        }:
            return PendingTargetFamily.POLL
        if route.intent is BotIntent.WATCHLIST:
            return (
                PendingTargetFamily.WATCHLIST
                if self._inner(route, "watchlist").get("action")
                in {"edit", "remove"}
                else None
            )
        if route.intent in {BotIntent.QUOTE_EDIT, BotIntent.QUOTE_DELETE}:
            return PendingTargetFamily.QUOTE
        if route.intent in {BotIntent.BIRTHDAY_CREATE, BotIntent.BIRTHDAY_EDIT}:
            return PendingTargetFamily.BIRTHDAY
        if route.intent is BotIntent.MEMORY_DELETE:
            return PendingTargetFamily.MEMORY
        return None

    def _require_unique_id(
        self,
        rows: tuple[dict[str, object], ...],
        stable_id: str,
        *id_names: str,
    ) -> None:
        matches = sum(
            self._id(row, *id_names) == stable_id
            for row in rows
        )
        if matches != 1:
            raise PendingTargetError("ambiguous_target")

    def _calendar_rows(
        self,
        reference_time: datetime,
    ) -> tuple[dict[str, object], ...]:
        return self._rows(
            self.monitor.calendar.snapshot_pending_items(
                reference_time=reference_time
            )
        )

    def _reminder_rows(self, scope_id: int) -> tuple[dict[str, object], ...]:
        return self._rows(
            self.monitor.reminders.snapshot_pending_items(scope_id)
        )

    def _poll_rows(
        self,
        scope_id: int,
        reference_time: datetime,
    ) -> tuple[dict[str, object], ...]:
        return self._rows(
            self.monitor.poll.snapshot_pending_items(
                scope_id,
                reference_time=reference_time,
            )
        )

    def _freeze_calendar(
        self,
        route: IntentResult,
        reference_time: datetime,
    ) -> FrozenPendingRoute:
        if route.intent is BotIntent.CALENDAR_CLEAR:
            ids = sorted(self.monitor.calendar.snapshot_all_item_ids())
            frozen_route = copy.deepcopy(route)
            guard = PendingTargetGuard(
                PendingTargetFamily.CALENDAR,
                None,
                None,
                self._digest({"ids": ids}),
                None,
                "hele kalenderen",
                f"hele kalenderen; {len(ids)} oppføringer",
                self._proposition_hash(frozen_route),
            )
            return FrozenPendingRoute(frozen_route, guard)
        rows = self._calendar_rows(reference_time)
        key = (
            "calendar_edit"
            if route.intent is BotIntent.CALENDAR_EDIT
            else "calendar_target"
        )
        inner = self._inner(route, key)
        selector = inner.get("target", inner.get("number"))
        position, row = self._select(
            rows,
            selector,
            id_names=("id", "item_id"),
            title_field="title",
        )
        stable_id = self._id(row, "id", "item_id")
        self._require_unique_id(rows, stable_id, "id", "item_id")
        revision = self._digest(self._project(row, self._CALENDAR_FIELDS))
        inner["target"] = stable_id
        inner.pop("number", None)
        frozen = self._replace_inner(route, key, inner)
        guard = PendingTargetGuard(
            PendingTargetFamily.CALENDAR,
            stable_id,
            position + 1,
            None,
            revision,
            str(row.get("title") or "kalenderoppføring"),
            self._detail(row, self._CALENDAR_FIELDS),
            self._proposition_hash(frozen),
        )
        return FrozenPendingRoute(frozen, guard)

    def _freeze_reminder(
        self,
        route: IntentResult,
        scope_id: int,
    ) -> FrozenPendingRoute:
        rows = self._reminder_rows(scope_id)
        inner = self._inner(route, "reminder")
        selector = inner.get("reminder_id", inner.get("number"))
        position, row = self._select(
            rows,
            selector,
            id_names=("reminder_id", "id"),
            title_field="text",
        )
        stable_id = self._id(row, "reminder_id", "id")
        self._require_unique_id(rows, stable_id, "reminder_id", "id")
        revision = self._digest(self._project(row, self._REMINDER_FIELDS))
        inner["reminder_id"] = stable_id
        inner.pop("number", None)
        frozen = self._replace_inner(route, "reminder", inner)
        guard = PendingTargetGuard(
            PendingTargetFamily.REMINDER,
            stable_id,
            position + 1,
            None,
            revision,
            str(row.get("text") or "påminnelse"),
            self._detail(row, self._REMINDER_FIELDS),
            self._proposition_hash(frozen),
        )
        return FrozenPendingRoute(frozen, guard)

    def _freeze_poll(
        self,
        route: IntentResult,
        scope_id: int,
        reference_time: datetime,
    ) -> FrozenPendingRoute:
        rows = self._poll_rows(scope_id, reference_time)
        key = {
            BotIntent.POLL_VOTE: "vote",
            BotIntent.POLL_EDIT: "poll_edit",
            BotIntent.POLL_DELETE: "poll_delete",
            BotIntent.POLL_CLOSE: "poll_close",
        }[route.intent]
        inner = self._inner(route, key)
        selector = inner.get("poll_id", inner.get("target"))
        if selector is None:
            if len(rows) != 1:
                raise PendingTargetError(
                    "target_not_found" if not rows else "ambiguous_target"
                )
            position, row = 0, rows[0]
        else:
            position, row = self._select(
                rows,
                selector,
                id_names=("poll_id", "id"),
                title_field="question",
            )
        stable_id = self._id(row, "poll_id", "id")
        self._require_unique_id(rows, stable_id, "poll_id", "id")
        projection = self._poll_projection(row)
        revision = self._digest(projection)
        detail = self._detail(projection, self._POLL_FIELDS)
        if route.intent is BotIntent.POLL_VOTE:
            option = inner.get("option")
            options = projection["options"]
            if (
                not isinstance(option, int)
                or isinstance(option, bool)
                or not isinstance(options, list)
                or not 1 <= option <= len(options)
            ):
                raise PendingTargetError("target_not_found")
            detail += f"; valgt alternativ: {options[option - 1]}"
        inner["poll_id"] = stable_id
        inner.pop("target", None)
        frozen = self._replace_inner(route, key, inner)
        guard = PendingTargetGuard(
            PendingTargetFamily.POLL,
            stable_id,
            position + 1,
            None,
            revision,
            str(row.get("question") or "avstemning"),
            detail,
            self._proposition_hash(frozen),
        )
        return FrozenPendingRoute(frozen, guard)

    def _freeze_fingerprint_family(
        self,
        route: IntentResult,
        *,
        family: PendingTargetFamily,
        key: str,
        rows: tuple[dict[str, object], ...],
        fields: tuple[str, ...],
        label_field: str,
    ) -> FrozenPendingRoute:
        inner = self._inner(route, key)
        position = self._position(inner.get("index"), len(rows))
        if position is None:
            raise PendingTargetError("target_not_found")
        row = rows[position]
        label = row.get(label_field)
        if not isinstance(label, str) or not label.strip():
            raise PendingTargetError("invalid_target_state")
        fingerprint = self._digest(self._project(row, fields))
        fingerprints = [
            self._digest(self._project(candidate, fields)) for candidate in rows
        ]
        if fingerprints.count(fingerprint) != 1:
            raise PendingTargetError("ambiguous_target")
        collection_revision = self._digest(sorted(fingerprints))
        frozen = copy.deepcopy(route)
        guard = PendingTargetGuard(
            family,
            None,
            position + 1,
            fingerprint,
            collection_revision,
            label,
            self._detail(row, fields),
            self._proposition_hash(frozen),
        )
        return FrozenPendingRoute(frozen, guard)

    def _freeze_birthday(
        self,
        route: IntentResult,
        scope_id: int,
    ) -> FrozenPendingRoute:
        inner = self._inner(route, "birthday")
        user_id = inner.get("user_id")
        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or user_id <= 0
        ):
            raise PendingTargetError("target_not_found")
        record = self.monitor.birthdays.snapshot_pending_user(scope_id, user_id)
        if record is not None and not isinstance(record, Mapping):
            raise PendingTargetError("invalid_target_state")
        creating = route.intent is BotIntent.BIRTHDAY_CREATE
        if creating and record is not None:
            raise PendingTargetError("target_changed")
        if not creating and record is None:
            raise PendingTargetError("target_not_found")
        revision = self._digest(
            {"state": "absent"} if record is None else {"record": record}
        )
        label = (
            inner.get("display_name")
            or (record.get("display_name") if isinstance(record, Mapping) else None)
            or (record.get("username") if isinstance(record, Mapping) else None)
            or "bursdag"
        )
        day = inner.get("day") if creating else record.get("day")
        month = inner.get("month") if creating else record.get("month")
        year = inner.get("year") if creating else record.get("year")
        if (
            not isinstance(day, int)
            or isinstance(day, bool)
            or not isinstance(month, int)
            or isinstance(month, bool)
            or (
                year is not None
                and (
                    not isinstance(year, int)
                    or isinstance(year, bool)
                    or not 1900 <= year <= 2100
                )
            )
        ):
            raise PendingTargetError("invalid_target_state")
        try:
            date(year or 2000, month, day)
        except (OverflowError, ValueError):
            raise PendingTargetError("invalid_target_state") from None
        date_detail = f"{day:02d}.{month:02d}" + (
            f".{year}" if isinstance(year, int) else ""
        )
        frozen = copy.deepcopy(route)
        guard = PendingTargetGuard(
            PendingTargetFamily.BIRTHDAY,
            str(user_id),
            None,
            None,
            revision,
            str(label),
            f"person: {label}; dato: {date_detail}",
            self._proposition_hash(frozen),
        )
        return FrozenPendingRoute(frozen, guard)

    def _freeze_memory(
        self,
        route: IntentResult,
        user_id: int,
    ) -> FrozenPendingRoute:
        record = self.monitor.user_memory.snapshot_pending_user(user_id)
        if record is not None and not isinstance(record, Mapping):
            raise PendingTargetError("invalid_target_state")
        fingerprint = self._digest(
            {"state": "absent"} if record is None else {"record": record}
        )
        frozen = copy.deepcopy(route)
        guard = PendingTargetGuard(
            PendingTargetFamily.MEMORY,
            None,
            None,
            fingerprint,
            None,
            "lagret brukerminne",
            "lagret brukerminne",
            self._proposition_hash(frozen),
        )
        return FrozenPendingRoute(frozen, guard)

    def freeze(
        self,
        route: IntentResult,
        routing: RoutingContext,
        *,
        reference_time: datetime,
    ) -> FrozenPendingRoute:
        """Freeze one route and normalize manager/preview boundary failures."""

        try:
            return self._freeze_impl(
                route,
                routing,
                reference_time=reference_time,
            )
        except PendingTargetError:
            raise
        except (TypeError, ValueError) as exc:
            code = (
                "confirmation_preview_too_large"
                if str(exc) == "pending_detail_too_large"
                else "invalid_target_state"
            )
            raise PendingTargetError(code) from None

    def _freeze_impl(
        self,
        route: IntentResult,
        routing: RoutingContext,
        *,
        reference_time: datetime,
    ) -> FrozenPendingRoute:
        self._aware(reference_time)
        scope_id = domain_scope_id(routing.key)
        if route.intent in {
            BotIntent.CALENDAR_EDIT,
            BotIntent.CALENDAR_DELETE,
            BotIntent.CALENDAR_COMPLETE,
            BotIntent.CALENDAR_CLEAR,
        }:
            return self._freeze_calendar(route, reference_time)
        if route.intent in {
            BotIntent.REMINDER_EDIT,
            BotIntent.REMINDER_DELETE,
            BotIntent.REMINDER_COMPLETE,
        }:
            return self._freeze_reminder(route, scope_id)
        if route.intent in {
            BotIntent.POLL_VOTE,
            BotIntent.POLL_EDIT,
            BotIntent.POLL_DELETE,
            BotIntent.POLL_CLOSE,
        }:
            return self._freeze_poll(route, scope_id, reference_time)
        if route.intent is BotIntent.WATCHLIST:
            inner = self._inner(route, "watchlist")
            if inner.get("action") not in {"edit", "remove"}:
                return FrozenPendingRoute(copy.deepcopy(route), None)
            return self._freeze_fingerprint_family(
                route,
                family=PendingTargetFamily.WATCHLIST,
                key="watchlist",
                rows=self._rows(
                    self.monitor.watchlist.snapshot_pending_items(scope_id)
                ),
                fields=self._WATCHLIST_FIELDS,
                label_field="title",
            )
        if route.intent in {BotIntent.QUOTE_EDIT, BotIntent.QUOTE_DELETE}:
            return self._freeze_fingerprint_family(
                route,
                family=PendingTargetFamily.QUOTE,
                key="quote",
                rows=self._rows(
                    self.monitor.quote.snapshot_pending_items(scope_id)
                ),
                fields=self._QUOTE_FIELDS,
                label_field="text",
            )
        if route.intent in {BotIntent.BIRTHDAY_CREATE, BotIntent.BIRTHDAY_EDIT}:
            return self._freeze_birthday(route, scope_id)
        if route.intent is BotIntent.MEMORY_DELETE:
            return self._freeze_memory(route, routing.key.user_id)
        if self._requires_guard(route):
            raise PendingTargetError("unsupported_pending_target")
        return FrozenPendingRoute(copy.deepcopy(route), None)

    def revalidate(
        self,
        route: IntentResult,
        guard: PendingTargetGuard | None,
        routing: RoutingContext,
        *,
        reference_time: datetime,
    ) -> IntentResult:
        """Revalidate one route and normalize manager boundary failures."""

        try:
            return self._revalidate_impl(
                route,
                guard,
                routing,
                reference_time=reference_time,
            )
        except PendingTargetError:
            raise
        except (TypeError, ValueError):
            raise PendingTargetError("invalid_target_state") from None

    def _revalidate_impl(
        self,
        route: IntentResult,
        guard: PendingTargetGuard | None,
        routing: RoutingContext,
        *,
        reference_time: datetime,
    ) -> IntentResult:
        self._aware(reference_time)
        expected_family = self._expected_guard_family(route)
        if guard is None:
            if expected_family is not None:
                raise PendingTargetError("missing_target_guard")
            return copy.deepcopy(route)
        if expected_family is not guard.family:
            raise PendingTargetError("target_changed")
        if (
            guard.proposition_hash is None
            or self._proposition_hash(route) != guard.proposition_hash
        ):
            raise PendingTargetError("target_changed")
        scope_id = domain_scope_id(routing.key)
        if guard.family is PendingTargetFamily.CALENDAR:
            if route.intent is BotIntent.CALENDAR_CLEAR:
                current = self._digest(
                    {"ids": sorted(self.monitor.calendar.snapshot_all_item_ids())}
                )
                if current != guard.fingerprint:
                    raise PendingTargetError("target_changed")
                return copy.deepcopy(route)
            rows = self._calendar_rows(reference_time)
            matches = [
                row
                for row in rows
                if self._id(row, "id", "item_id") == guard.stable_id
            ]
            fields = self._CALENDAR_FIELDS
            key = (
                "calendar_edit"
                if route.intent is BotIntent.CALENDAR_EDIT
                else "calendar_target"
            )
        elif guard.family is PendingTargetFamily.REMINDER:
            rows = self._reminder_rows(scope_id)
            matches = [
                row
                for row in rows
                if self._id(row, "reminder_id", "id") == guard.stable_id
            ]
            fields = self._REMINDER_FIELDS
            key = "reminder"
        elif guard.family is PendingTargetFamily.POLL:
            rows = self._poll_rows(scope_id, reference_time)
            matches = [
                row
                for row in rows
                if self._id(row, "poll_id", "id") == guard.stable_id
            ]
            fields = self._POLL_FIELDS
            key = {
                BotIntent.POLL_VOTE: "vote",
                BotIntent.POLL_EDIT: "poll_edit",
                BotIntent.POLL_DELETE: "poll_delete",
                BotIntent.POLL_CLOSE: "poll_close",
            }.get(route.intent, "")
            if not key:
                raise PendingTargetError("target_changed")
        elif guard.family in {
            PendingTargetFamily.WATCHLIST,
            PendingTargetFamily.QUOTE,
        }:
            manager = (
                self.monitor.watchlist
                if guard.family is PendingTargetFamily.WATCHLIST
                else self.monitor.quote
            )
            rows = self._rows(manager.snapshot_pending_items(scope_id))
            fields = (
                self._WATCHLIST_FIELDS
                if guard.family is PendingTargetFamily.WATCHLIST
                else self._QUOTE_FIELDS
            )
            fingerprints = [
                self._digest(self._project(row, fields)) for row in rows
            ]
            if self._digest(sorted(fingerprints)) != guard.revision:
                raise PendingTargetError("target_changed")
            matches = [
                row
                for row, fingerprint in zip(rows, fingerprints, strict=True)
                if fingerprint == guard.fingerprint
            ]
            if len(matches) != 1:
                raise PendingTargetError("target_changed")
            current_index = rows.index(matches[0]) + 1
            key = (
                "watchlist"
                if guard.family is PendingTargetFamily.WATCHLIST
                else "quote"
            )
            inner = self._inner(route, key)
            inner["index"] = current_index
            return self._replace_inner(route, key, inner)
        elif guard.family is PendingTargetFamily.BIRTHDAY:
            inner = self._inner(route, "birthday")
            user_id = int(guard.stable_id or "0")
            record = self.monitor.birthdays.snapshot_pending_user(scope_id, user_id)
            current = self._digest(
                {"state": "absent"} if record is None else {"record": record}
            )
            if current != guard.revision or inner.get("user_id") != user_id:
                raise PendingTargetError("target_changed")
            return copy.deepcopy(route)
        elif guard.family is PendingTargetFamily.MEMORY:
            record = self.monitor.user_memory.snapshot_pending_user(
                routing.key.user_id
            )
            if record is not None and not isinstance(record, Mapping):
                raise PendingTargetError("invalid_target_state")
            current = self._digest(
                {"state": "absent"} if record is None else {"record": record}
            )
            if current != guard.fingerprint:
                raise PendingTargetError("target_changed")
            return copy.deepcopy(route)
        else:
            raise PendingTargetError("target_changed")

        if len(matches) != 1:
            raise PendingTargetError("target_changed")
        row = matches[0]
        projection = (
            self._poll_projection(row)
            if guard.family is PendingTargetFamily.POLL
            else self._project(row, fields)
        )
        if self._digest(projection) != guard.revision:
            raise PendingTargetError("target_changed")
        inner = self._inner(route, key)
        if guard.family is PendingTargetFamily.CALENDAR:
            inner["target"] = guard.stable_id
            inner.pop("number", None)
        elif guard.family is PendingTargetFamily.REMINDER:
            inner["reminder_id"] = guard.stable_id
            inner.pop("number", None)
        else:
            inner["poll_id"] = guard.stable_id
            inner.pop("target", None)
        return self._replace_inner(route, key, inner)

    def mutation_context(
        self,
        route: IntentResult,
        key: ConversationKey,
    ) -> AbstractAsyncContextManager[None]:
        return self.coordinator.hold(self.mutation_scope(route, key))

    def mutation_scope(
        self,
        route: IntentResult,
        key: ConversationKey,
    ) -> MutationScope:
        del key
        for intents, scope in self._MUTATION_SCOPES:
            if route.intent in intents:
                return scope
        raise PendingTargetError("unsupported_mutation_scope")


def conversation_turn_scope(key: ConversationKey) -> tuple[str, str]:
    """Return the fair serialization scope for one conversation."""

    guild = f"guild:{key.guild_id}" if key.guild_id is not None else "dm"
    return (
        "conversation_turn",
        f"{guild}:channel:{key.channel_id}:user:{key.user_id}",
    )
