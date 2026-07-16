#!/usr/bin/env python3
"""
Simple Calendar Manager for Inebotten
Everything is just a calendar item with a date
"""

import json
import re
import uuid
import asyncio
import inspect
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
from zoneinfo import ZoneInfo

from cal_system.reminder_clock import ReminderClock, SystemReminderClock
from cal_system.google_calendar_manager import (
    ExternalOperationCancelled,
    GoogleCalendarManager,
)
from core.dispatch_result import (
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationCancelled,
    ManagerMutationError,
)
from core.mutation_coordinator import CALENDAR_SHARED_SCOPE, MutationCoordinator
from utils.json_storage import hermes_discord_data_path, write_json_atomic


OSLO = ZoneInfo("Europe/Oslo")
_MISSING = object()
_CANCEL_CODES = frozenset(
    {
        "external_commit_unknown",
        "external_sync_pending",
        "external_delete_pending",
        "external_read_failed",
        "cancelled_after_external_commit",
        "cancelled_after_external_read",
        "cancelled_after_credential_refresh",
        "external_state_changed_storage_failed",
        "commit_state_unknown",
        "not_configured",
    }
)


@dataclass(frozen=True, slots=True)
class CalendarSyncResult:
    ok: bool
    mutated: bool
    added: int = 0
    updated: int = 0
    removed: int = 0
    error_code: str | None = None
    commit_unknown: bool = False


@dataclass(frozen=True, slots=True)
class _SettledExternal:
    result: ExternalMutationResult
    cancelled: bool = False

    @property
    def ok(self):
        return self.result.ok

    @property
    def state(self):
        return self.result.state

    @property
    def value(self):
        return self.result.value

    @property
    def error_code(self):
        return self.result.error_code


class AwaitableDict(dict):
    """Dictionary result that can also be awaited by async handlers."""

    def __await__(self):
        async def _return():
            return self
        return _return().__await__()


class AwaitableValue:
    """Generic result wrapper that can be awaited without breaking sync callers."""

    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _return():
            return self.value
        return _return().__await__()

    def __bool__(self):
        return bool(self.value)

    def __iter__(self):
        return iter(self.value)

    def __getitem__(self, key):
        return self.value[key]

    def __repr__(self):
        return repr(self.value)


class CalendarDeleteResult(dict):
    """Structured delete result that still unpacks like the legacy tuples."""

    def __iter__(self):
        if self.get("bulk"):
            yield int(self.get("deleted_count", 0))
            yield list(self.get("deleted_titles", []))
        else:
            yield bool(self.get("success"))
            yield self.get("title")

    def __bool__(self):
        return bool(self.get("success") or int(self.get("deleted_count", 0)) > 0)

    def __getitem__(self, key):
        if isinstance(key, int):
            values = list(iter(self))
            return values[key]
        return super().__getitem__(key)


class CalendarManager:
    """
    Manages calendar items - everything is just something happening on a date
    """

    SHARED_KEY = "shared"

    def __init__(
        self,
        storage_path=None,
        gcal_manager=None,
        owner_email=None,
        owner_name=None,
        *,
        clock: ReminderClock | None = None,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        if storage_path is None:
            storage_path = hermes_discord_data_path("calendar.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.gcal = gcal_manager
        self.clock = clock or SystemReminderClock()
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()
        self.owner_email = owner_email
        self.owner_name = owner_name
        self.last_gcal_sync_error = None
        self.items = {}  # Will be transitioned to {self.SHARED_KEY: [...]}

    @property
    def gcal_enabled(self) -> bool:
        """Compatibility view over the injected manager's live state."""
        if self.gcal is None:
            return False
        enabled = getattr(self.gcal, "enabled", None)
        if enabled is not None:
            return bool(enabled)
        configured = getattr(self.gcal, "is_configured", None)
        return bool(configured()) if callable(configured) else True

    @gcal_enabled.setter
    def gcal_enabled(self, value: bool) -> None:
        # Compatibility for old tests which explicitly disable a fake.  Real
        # configured managers remain the source of truth.
        if self.gcal is None and value:
            raise AttributeError("missing_gcal_manager")

    async def ensure_gcal_configured(self) -> ExternalMutationResult:
        """Refresh the one injected Google Calendar manager in place."""
        if self.gcal is None:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="integration_disabled",
            )
        refresh = getattr(self.gcal, "refresh_configuration_result", None)
        if callable(refresh):
            return await refresh()
        if self.gcal_enabled:
            return ExternalMutationResult(
                True,
                ExternalCommitState.UNCHANGED,
                value=True,
            )
        return ExternalMutationResult(
            False,
            ExternalCommitState.UNCHANGED,
            error_code="not_configured",
        )

    async def setup(self):
        """Async initialization and migration to shared calendar"""
        loaded = await self._load_data()
        self.items = loaded
        
        # Migration to shared calendar if multiple buckets exist or if only old guild-specific buckets exist
        keys = list(self.items.keys())
        if self.items and (len(keys) > 1 or (len(keys) == 1 and keys[0] != self.SHARED_KEY)):
            print(f"[CAL] Migrating {len(keys)} channel-specific calendars to one grand shared calendar...")
            merged = []
            seen_ids = set()
            
            # Extract all items from all buckets
            for guild_id, guild_items in self.items.items():
                for item in guild_items:
                    if item.get("id") not in seen_ids:
                        merged.append(item)
                        seen_ids.add(item.get("id"))
            
            candidate = {self.SHARED_KEY: merged}
            async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
                await self._persist_candidate(candidate)
            print(f"[CAL] Migration complete: {len(merged)} items moved to '{self.SHARED_KEY}'")
            
        print(f"[CAL] Calendar system initialized with {sum(len(v) for v in self.items.values())} items")

    async def _load_data(self) -> Dict:
        """Load calendar data from JSON file asynchronously"""
        if not self.storage_path.exists():
            return {}

        def _read():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CAL] Error loading calendar data: {e}")
                return {}

        return await asyncio.to_thread(_read)

    async def _save_data(self, candidate=None):
        """Save calendar data to JSON file atomically and asynchronously"""
        await asyncio.to_thread(
            self._save_data_sync,
            self.items if candidate is None else candidate,
        )

    def _save_data_sync(self, candidate=None):
        """Save calendar data to JSON file atomically."""
        write_json_atomic(
            self.storage_path,
            self.items if candidate is None else candidate,
            indent=2,
        )

    @staticmethod
    def _require_aware(reference_time: datetime) -> datetime:
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("reference_time_must_be_aware")
        return reference_time

    async def _persist_candidate(
        self,
        candidate: dict[str, list[dict[str, Any]]],
        *,
        mutated_if_cancelled: bool = True,
    ) -> None:
        """Persist a detached root and publish only after known completion."""
        writer = asyncio.create_task(
            asyncio.to_thread(self._save_data_sync, candidate)
        )
        outer_cancelled = False
        while True:
            try:
                await asyncio.shield(writer)
                break
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is None or current.cancelling() == 0:
                    raise ManagerMutationError(
                        "commit_state_unknown",
                        mutated=False,
                        commit_unknown=True,
                    )
                outer_cancelled = True
                current.uncancel()
                if writer.done():
                    # Record outer cancellation first, then settle the writer's
                    # independently known result.
                    try:
                        writer.result()
                    except asyncio.CancelledError as exc:
                        raise ManagerMutationCancelled(
                            "commit_state_unknown",
                            mutated=False,
                            retryable=False,
                            commit_unknown=True,
                        ) from exc
                    except Exception as exc:
                        raise ManagerMutationCancelled(
                            "storage_write_failed",
                            mutated=False,
                            retryable=True,
                        ) from exc
                    break
                continue
            except Exception as exc:
                if outer_cancelled:
                    raise ManagerMutationCancelled(
                        "storage_write_failed",
                        mutated=False,
                        retryable=True,
                    ) from exc
                raise ManagerMutationError(
                    "storage_write_failed",
                    mutated=False,
                ) from exc

        if writer.cancelled():
            raise ManagerMutationError(
                "commit_state_unknown",
                mutated=False,
                commit_unknown=True,
            )
        failure = writer.exception()
        if failure is not None:
            if outer_cancelled:
                raise ManagerMutationCancelled(
                    "storage_write_failed",
                    mutated=False,
                    retryable=True,
                ) from failure
            raise ManagerMutationError(
                "storage_write_failed",
                mutated=False,
            ) from failure

        self.items = candidate
        if outer_cancelled:
            raise ManagerMutationCancelled(
                "cancelled_after_storage_commit",
                mutated=mutated_if_cancelled,
                retryable=False,
            )

    @staticmethod
    def _run_offline(factory):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(factory())
        raise RuntimeError("use_async_result_api")

    @staticmethod
    def _external_result_from_legacy(
        value,
        *,
        mutation: bool,
        expected: str | None = None,
    ) -> ExternalMutationResult:
        if isinstance(value, ExternalMutationResult):
            return value
        if mutation:
            valid = (
                value is True
                if expected == "bool"
                else isinstance(value, dict) and bool(value.get("id"))
            )
            if valid:
                return ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    value=value,
                )
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNKNOWN,
                error_code="external_commit_unknown",
            )
        if value is None:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="external_read_failed",
            )
        return ExternalMutationResult(
            True,
            ExternalCommitState.UNCHANGED,
            value=value,
        )

    async def _call_gcal(self, result_name: str, legacy_name: str, *args, **kwargs):
        if self.gcal is None:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="integration_disabled",
            )
        result_method = getattr(self.gcal, result_name, None)
        mutation = result_name not in {
            "list_upcoming_events_result",
            "get_event_result",
        }
        expected = (
            "bool"
            if result_name == "delete_event_result"
            else ("dict" if mutation else None)
        )

        def normalize(result):
            if not isinstance(result, ExternalMutationResult):
                return self._external_result_from_legacy(
                    result,
                    mutation=mutation,
                    expected=expected,
                )
            if mutation and result.ok:
                valid = (
                    result.value is True
                    if expected == "bool"
                    else isinstance(result.value, dict)
                    and bool(result.value.get("id"))
                )
                if result.state is not ExternalCommitState.CHANGED or not valid:
                    return ExternalMutationResult(
                        False,
                        ExternalCommitState.UNKNOWN,
                        error_code="external_commit_unknown",
                    )
            return result

        def compatible_kwargs(method):
            """Drop only the new optional clock keyword for old test/fake APIs."""
            if "reference_time" not in kwargs:
                return kwargs
            try:
                parameters = inspect.signature(method).parameters.values()
            except (TypeError, ValueError):
                return kwargs
            if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
                return kwargs
            if any(parameter.name == "reference_time" for parameter in parameters):
                return kwargs
            compatible = dict(kwargs)
            compatible.pop("reference_time")
            return compatible

        if callable(result_method):
            try:
                result = result_method(
                    *args,
                    **compatible_kwargs(result_method),
                )
                if hasattr(result, "__await__"):
                    result = await result
                result = normalize(result)
                return _SettledExternal(result)
            except ExternalOperationCancelled as exc:
                return _SettledExternal(normalize(exc.result), cancelled=True)
            except Exception:
                return _SettledExternal(
                    ExternalMutationResult(
                        False,
                        (
                            ExternalCommitState.UNKNOWN
                            if mutation
                            else ExternalCommitState.UNCHANGED
                        ),
                        error_code=(
                            "external_commit_unknown"
                            if mutation
                            else "external_read_failed"
                        ),
                    )
                )
        legacy = getattr(self.gcal, legacy_name, None)
        if not callable(legacy):
            return _SettledExternal(
                ExternalMutationResult(
                    False,
                    (
                        ExternalCommitState.UNKNOWN
                        if mutation
                        else ExternalCommitState.UNCHANGED
                    ),
                    error_code=(
                        "external_commit_unknown"
                        if mutation
                        else "external_read_failed"
                    ),
                )
            )
        try:
            value = await GoogleCalendarManager._await_worker(
                legacy,
                *args,
                **compatible_kwargs(legacy),
            )
        except ExternalOperationCancelled as exc:
            return _SettledExternal(normalize(exc.result), cancelled=True)
        except Exception:
            return _SettledExternal(
                ExternalMutationResult(
                    False,
                    (
                        ExternalCommitState.UNKNOWN
                        if mutation
                        else ExternalCommitState.UNCHANGED
                    ),
                    error_code=(
                        "external_commit_unknown"
                        if mutation
                        else "external_read_failed"
                    ),
                )
            )
        return _SettledExternal(normalize(value))

    @staticmethod
    def _raise_external_cancellation(
        external: _SettledExternal,
        *,
        mutated: bool,
        default_code: str,
    ) -> None:
        if not external.cancelled:
            return
        if external.state is ExternalCommitState.UNKNOWN:
            raise ManagerMutationCancelled(
                "external_commit_unknown",
                mutated=mutated,
                retryable=False,
                commit_unknown=True,
            )
        code = (
            default_code
            if default_code in _CANCEL_CODES
            else "cancelled_after_external_commit"
        )
        raise ManagerMutationCancelled(
            code,
            mutated=mutated,
            retryable=False,
        )

    @staticmethod
    def _translate_post_external_cancel(
        exc: ManagerMutationCancelled,
    ) -> ManagerMutationCancelled:
        if exc.commit_unknown:
            return ManagerMutationCancelled(
                "commit_state_unknown",
                mutated=True,
                retryable=False,
                commit_unknown=True,
            )
        if exc.mutated:
            return ManagerMutationCancelled(
                "cancelled_after_external_commit",
                mutated=True,
                retryable=False,
            )
        return ManagerMutationCancelled(
            "external_state_changed_storage_failed",
            mutated=True,
            retryable=False,
        )

    @staticmethod
    def _translate_cancelled_external_storage_error(exc):
        return ManagerMutationCancelled(
            (
                "commit_state_unknown"
                if exc.commit_unknown
                else "external_state_changed_storage_failed"
            ),
            mutated=True,
            retryable=False,
            commit_unknown=exc.commit_unknown,
        )

    def _event_times(self, date_str: str, time_str: str | None) -> tuple[str, str]:
        day, month, year = date_str.split(".")
        hour, minute = (time_str or "12:00").split(":")
        start = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            tzinfo=OSLO,
        )
        return start.isoformat(), (start + timedelta(hours=1)).isoformat()

    def _validate_item_state(self, item: dict[str, Any]) -> None:
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("invalid_title")
        if not self._validate_date_format(item.get("date")):
            raise ValueError("invalid_date")
        time_value = item.get("time")
        if time_value is not None:
            try:
                datetime.strptime(time_value, "%H:%M")
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_time") from exc
        recurrence = item.get("recurrence")
        if recurrence not in {None, "daily", "weekly", "biweekly", "monthly", "yearly"}:
            raise ValueError("invalid_recurrence")
        if item.get("type", "event") not in {"event", "task"}:
            raise ValueError("invalid_item_type")
        description = item.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("invalid_description")

    async def add_item_result(
        self,
        guild_id,
        user_id,
        username,
        title,
        date_str,
        time_str=None,
        recurrence=None,
        recurrence_day=None,
        *,
        channel_id=None,
        item_type="event",
        description=None,
        rrule_day=None,
        reference_time: datetime,
        gcal_event_id=None,
        gcal_link=None,
    ) -> dict[str, Any]:
        """Create one durable record, then settle optional external sync."""
        reference_time = self._require_aware(reference_time)
        normalized_date = self._normalize_date_format(date_str)
        if not self._validate_date_format(normalized_date):
            raise ValueError("invalid_date")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("invalid_title")
        if item_type not in {"event", "task"}:
            raise ValueError("invalid_item_type")

        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            candidate = deepcopy(self.items)
            bucket = candidate.setdefault(self.SHARED_KEY, [])
            wants_external = bool(
                self.gcal_enabled and gcal_event_id is None
            )
            item = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "username": username,
                "title": title.strip(),
                "date": normalized_date,
                "time": time_str,
                "type": item_type,
                "description": description,
                "recurrence": recurrence,
                "recurrence_day": recurrence_day,
                "rrule_day": rrule_day,
                "created_at": reference_time.isoformat(),
                "completed": False,
                "gcal_event_id": gcal_event_id,
                "gcal_link": gcal_link,
                "gcal_sync_pending": wants_external,
                "channel_id": str(channel_id) if channel_id is not None else None,
            }
            self._validate_item_state(item)
            bucket.append(item)
            await self._persist_candidate(candidate)

            if not wants_external:
                return deepcopy(item)

            start_time, end_time = self._event_times(normalized_date, time_str)
            external = await self._call_gcal(
                "create_event_result",
                "create_event",
                title.strip(),
                start_time,
                end_time,
                description,
                None,
                None,
                recurrence,
                rrule_day or recurrence_day,
                user_id,
                username,
            )
            if external.state is ExternalCommitState.UNKNOWN:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_commit_unknown",
                )
                raise ManagerMutationError(
                    "external_commit_unknown",
                    mutated=True,
                    commit_unknown=True,
                )
            if not external.ok or external.state is not ExternalCommitState.CHANGED:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_sync_pending",
                )
                raise ManagerMutationError(
                    "external_sync_pending",
                    mutated=True,
                )

            value = external.value if isinstance(external.value, dict) else {}
            final_candidate = deepcopy(self.items)
            final_item = self._find_item(final_candidate, item["id"])
            final_item["gcal_event_id"] = value.get("id")
            final_item["gcal_link"] = value.get("htmlLink")
            final_item["gcal_sync_pending"] = False
            try:
                await self._persist_candidate(final_candidate)
            except ManagerMutationCancelled as exc:
                raise self._translate_post_external_cancel(exc) from exc
            except ManagerMutationError as exc:
                if external.cancelled:
                    raise self._translate_cancelled_external_storage_error(exc) from exc
                raise ManagerMutationError(
                    "external_state_changed_storage_failed",
                    mutated=True,
                ) from exc
            self._raise_external_cancellation(
                external,
                mutated=True,
                default_code="cancelled_after_external_commit",
            )
            return deepcopy(final_item)

    @staticmethod
    def _find_item(candidate, item_id):
        for item in candidate.get(CalendarManager.SHARED_KEY, []):
            if item.get("id") == item_id:
                return item
        raise ValueError("not_found")

    async def edit_item_result(
        self,
        *,
        item_id,
        reference_time: datetime,
        title=None,
        date=None,
        time=None,
        recurrence=_MISSING,
        description=None,
        type=None,
    ) -> dict[str, Any]:
        reference_time = self._require_aware(reference_time)
        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            candidate = deepcopy(self.items)
            item = self._find_item(candidate, item_id)
            self._apply_item_updates(
                item,
                title,
                date,
                time,
                recurrence,
                description,
                item_type=type,
            )
            self._validate_item_state(item)
            item["updated_at"] = reference_time.isoformat()
            wants_external = bool(self.gcal_enabled and item.get("gcal_event_id"))
            if wants_external:
                item["gcal_sync_pending"] = True
            await self._persist_candidate(candidate)
            if not wants_external:
                return deepcopy(item)

            external = await self._call_gcal(
                "update_event_result",
                "update_event",
                item["gcal_event_id"],
                item.get("title"),
                item.get("description"),
                False,
                item.get("date"),
                item.get("time"),
                item.get("recurrence"),
                item.get("rrule_day") or item.get("recurrence_day"),
            )
            if external.state is ExternalCommitState.UNKNOWN:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_commit_unknown",
                )
                raise ManagerMutationError(
                    "external_commit_unknown",
                    mutated=True,
                    commit_unknown=True,
                )
            if not external.ok or external.state is not ExternalCommitState.CHANGED:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_sync_pending",
                )
                raise ManagerMutationError("external_sync_pending", mutated=True)

            final_candidate = deepcopy(self.items)
            final_item = self._find_item(final_candidate, item_id)
            if isinstance(external.value, dict):
                final_item["gcal_event_id"] = (
                    external.value.get("id") or final_item.get("gcal_event_id")
                )
                final_item["gcal_link"] = (
                    external.value.get("htmlLink") or final_item.get("gcal_link")
                )
            final_item["gcal_sync_pending"] = False
            try:
                await self._persist_candidate(final_candidate)
            except ManagerMutationCancelled as exc:
                raise self._translate_post_external_cancel(exc) from exc
            except ManagerMutationError as exc:
                if external.cancelled:
                    raise self._translate_cancelled_external_storage_error(exc) from exc
                raise ManagerMutationError(
                    "external_state_changed_storage_failed",
                    mutated=True,
                ) from exc
            self._raise_external_cancellation(
                external,
                mutated=True,
                default_code="cancelled_after_external_commit",
            )
            return deepcopy(final_item)

    async def complete_item_result(
        self,
        guild_id,
        *,
        item_id,
        reference_time: datetime,
    ) -> tuple[bool, str | None, str | None]:
        reference_time = self._require_aware(reference_time)
        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            candidate = deepcopy(self.items)
            item = self._find_item(candidate, item_id)
            title = item.get("title")
            next_date = None
            if item.get("recurrence"):
                next_date = self._calculate_next_date(
                    item.get("date"), item.get("recurrence")
                )
                if not next_date:
                    raise ValueError("invalid_recurrence")
                item["date"] = next_date
            else:
                item["completed"] = True
            self._validate_item_state(item)
            item["updated_at"] = reference_time.isoformat()
            wants_external = bool(self.gcal_enabled and item.get("gcal_event_id"))
            if wants_external:
                item["gcal_sync_pending"] = True
            await self._persist_candidate(candidate)
            if not wants_external:
                return True, title, next_date

            external = await self._call_gcal(
                "update_event_result",
                "update_event",
                item["gcal_event_id"],
                item.get("title"),
                item.get("description"),
                not bool(item.get("recurrence")),
                item.get("date") if item.get("recurrence") else None,
                item.get("time"),
                item.get("recurrence"),
                item.get("rrule_day") or item.get("recurrence_day"),
            )
            if external.state is ExternalCommitState.UNKNOWN:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_commit_unknown",
                )
                raise ManagerMutationError(
                    "external_commit_unknown",
                    mutated=True,
                    commit_unknown=True,
                )
            if not external.ok or external.state is not ExternalCommitState.CHANGED:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_sync_pending",
                )
                raise ManagerMutationError("external_sync_pending", mutated=True)
            final_candidate = deepcopy(self.items)
            final_item = self._find_item(final_candidate, item_id)
            final_item["gcal_sync_pending"] = False
            try:
                await self._persist_candidate(final_candidate)
            except ManagerMutationCancelled as exc:
                raise self._translate_post_external_cancel(exc) from exc
            except ManagerMutationError as exc:
                if external.cancelled:
                    raise self._translate_cancelled_external_storage_error(exc) from exc
                raise ManagerMutationError(
                    "external_state_changed_storage_failed",
                    mutated=True,
                ) from exc
            self._raise_external_cancellation(
                external,
                mutated=True,
                default_code="cancelled_after_external_commit",
            )
            return True, title, next_date

    @staticmethod
    def _delete_result(*, title=None, requested=0, deleted=0, pending=0):
        return CalendarDeleteResult(
            {
                "success": bool(deleted) and not pending,
                "title": title,
                "requested_count": requested,
                "deleted_count": deleted,
                "deleted_titles": [title] if deleted and title else [],
                "pending_count": pending,
                "pending_titles": [title] if pending and title else [],
                "pending_errors": ({title: "external_delete_pending"} if pending and title else {}),
            }
        )

    async def delete_item_result(
        self,
        guild_id,
        *,
        item_id,
        reference_time: datetime,
    ) -> CalendarDeleteResult:
        reference_time = self._require_aware(reference_time)
        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            try:
                current = self._find_item(self.items, item_id)
            except ValueError:
                return self._delete_result(requested=0)
            title = current.get("title", "Uten tittel")
            wants_external = bool(self.gcal_enabled and current.get("gcal_event_id"))
            if not wants_external:
                candidate = deepcopy(self.items)
                candidate[self.SHARED_KEY] = [
                    row
                    for row in candidate.get(self.SHARED_KEY, [])
                    if row.get("id") != item_id
                ]
                await self._persist_candidate(candidate)
                return self._delete_result(
                    title=title,
                    requested=1,
                    deleted=1,
                )

            pending_candidate = deepcopy(self.items)
            pending_item = self._find_item(pending_candidate, item_id)
            self._mark_delete_pending(
                pending_item,
                "external_delete_pending",
                reference_time.isoformat(),
            )
            await self._persist_candidate(pending_candidate)
            external = await self._call_gcal(
                "delete_event_result",
                "delete_event",
                pending_item["gcal_event_id"],
            )
            authoritative_absence = (
                external.state is ExternalCommitState.UNCHANGED
                and external.error_code == "external_not_found"
            )
            if (
                external.ok
                and external.state is ExternalCommitState.CHANGED
            ) or authoritative_absence:
                final_candidate = deepcopy(self.items)
                final_candidate[self.SHARED_KEY] = [
                    row
                    for row in final_candidate.get(self.SHARED_KEY, [])
                    if row.get("id") != item_id
                ]
                try:
                    await self._persist_candidate(final_candidate)
                except ManagerMutationCancelled as exc:
                    raise self._translate_post_external_cancel(exc) from exc
                except ManagerMutationError as exc:
                    if external.cancelled:
                        raise self._translate_cancelled_external_storage_error(exc) from exc
                    raise ManagerMutationError(
                        (
                            "external_state_changed_storage_failed"
                            if external.ok
                            else "storage_write_failed"
                        ),
                        mutated=True,
                    ) from exc
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="cancelled_after_external_commit",
                )
                return self._delete_result(
                    title=title,
                    requested=1,
                    deleted=1,
                )
            if external.state is ExternalCommitState.UNKNOWN:
                self._raise_external_cancellation(
                    external,
                    mutated=True,
                    default_code="external_commit_unknown",
                )
                raise ManagerMutationError(
                    "external_commit_unknown",
                    mutated=True,
                    commit_unknown=True,
                )
            self._raise_external_cancellation(
                external,
                mutated=True,
                default_code="external_delete_pending",
            )
            return self._delete_result(
                title=title,
                requested=1,
                pending=1,
            )

    async def clear_calendar_result(
        self,
        guild_id,
        *,
        reference_time: datetime,
    ) -> dict[str, Any]:
        reference_time = self._require_aware(reference_time)
        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            current_items = deepcopy(self.items.get(self.SHARED_KEY, []))
            if not current_items:
                return {
                    "requested_count": 0,
                    "deleted_count": 0,
                    "failed_count": 0,
                    "pending_titles": [],
                }

            external_items = [
                row
                for row in current_items
                if self.gcal_enabled and row.get("gcal_event_id")
            ]
            if external_items:
                pending_candidate = deepcopy(self.items)
                for row in pending_candidate.get(self.SHARED_KEY, []):
                    if row.get("gcal_event_id"):
                        self._mark_delete_pending(
                            row,
                            "external_delete_pending",
                            reference_time.isoformat(),
                        )
                await self._persist_candidate(pending_candidate)

            deleted_ids = {
                row.get("id")
                for row in current_items
                if row not in external_items
            }
            pending_titles: list[str] = []
            commit_unknown = False
            external_changed = False
            cancelled_external = None
            for index, row in enumerate(external_items):
                external = await self._call_gcal(
                    "delete_event_result",
                    "delete_event",
                    row["gcal_event_id"],
                )
                authoritative_absence = (
                    external.state is ExternalCommitState.UNCHANGED
                    and external.error_code == "external_not_found"
                )
                if (
                    external.ok
                    and external.state is ExternalCommitState.CHANGED
                ) or authoritative_absence:
                    deleted_ids.add(row.get("id"))
                    external_changed = external_changed or external.ok
                else:
                    pending_titles.append(row.get("title", "Uten tittel"))
                    commit_unknown = (
                        commit_unknown
                        or external.state is ExternalCommitState.UNKNOWN
                    )
                if external.cancelled:
                    cancelled_external = external
                    pending_titles.extend(
                        item.get("title", "Uten tittel")
                        for item in external_items[index + 1 :]
                    )
                    break

            final_candidate = deepcopy(self.items)
            final_candidate[self.SHARED_KEY] = [
                row
                for row in final_candidate.get(self.SHARED_KEY, [])
                if row.get("id") not in deleted_ids
            ]
            # A local-only clear still needs exactly one durable publish.
            if final_candidate != self.items:
                try:
                    await self._persist_candidate(final_candidate)
                except ManagerMutationCancelled as exc:
                    if commit_unknown:
                        raise ManagerMutationCancelled(
                            "external_commit_unknown",
                            mutated=True,
                            retryable=False,
                            commit_unknown=True,
                        ) from exc
                    raise self._translate_post_external_cancel(exc) from exc
                except ManagerMutationError as exc:
                    if commit_unknown:
                        if cancelled_external is not None:
                            raise ManagerMutationCancelled(
                                "external_commit_unknown",
                                mutated=True,
                                retryable=False,
                                commit_unknown=True,
                            ) from exc
                        raise ManagerMutationError(
                            "external_commit_unknown",
                            mutated=True,
                            commit_unknown=True,
                        ) from exc
                    if cancelled_external is not None:
                        raise self._translate_cancelled_external_storage_error(exc) from exc
                    if external_changed:
                        raise ManagerMutationError(
                            "external_state_changed_storage_failed",
                            mutated=True,
                        ) from exc
                    if external_items:
                        raise ManagerMutationError(
                            "storage_write_failed",
                            mutated=True,
                        ) from exc
                    raise
            if commit_unknown:
                if cancelled_external is not None:
                    raise ManagerMutationCancelled(
                        "external_commit_unknown",
                        mutated=True,
                        retryable=False,
                        commit_unknown=True,
                    )
                raise ManagerMutationError(
                    "external_commit_unknown",
                    mutated=bool(external_items),
                    commit_unknown=True,
                )
            if cancelled_external is not None:
                self._raise_external_cancellation(
                    cancelled_external,
                    mutated=True,
                    default_code="external_delete_pending",
                )
            return {
                "requested_count": len(current_items),
                "deleted_count": len(deleted_ids),
                "failed_count": len(pending_titles),
                "pending_titles": pending_titles,
            }

    def add_item(
        self,
        guild_id,
        user_id,
        username,
        title,
        date_str,
        time_str=None,
        recurrence=None,
        recurrence_day=None,
        gcal_event_id=None,
        gcal_link=None,
        channel_id=None,
        item_type="event",
        description=None,
        rrule_day=None,
    ):
        """Offline compatibility projection over ``add_item_result``."""
        result = self._run_offline(
            lambda: self.add_item_result(
                guild_id,
                user_id,
                username,
                title,
                date_str,
                time_str,
                recurrence,
                recurrence_day,
                channel_id=channel_id,
                item_type=item_type,
                description=description,
                rrule_day=rrule_day,
                reference_time=self.clock.now(),
                gcal_event_id=gcal_event_id,
                gcal_link=gcal_link,
            )
        )
        return AwaitableDict(result)

    def _mark_delete_pending(self, item, error=None, now=None):
        now = now or datetime.now().isoformat()
        item["delete_pending"] = True
        item["delete_requested_at"] = item.get("delete_requested_at") or now
        item["delete_last_attempt_at"] = now
        item["delete_error"] = error or "Google Calendar deletion returned false"

    def delete_item(self, guild_id, item_num):
        """Delete an item by its list number (ignoring guild_id for shared calendar)"""
        guild_key = self.SHARED_KEY
        items = self.get_upcoming(guild_key, days=365)

        if item_num is not None and 1 <= item_num <= len(items):
            item_id = items[item_num - 1].get("id")
            result = self._run_offline(
                lambda: self.delete_item_result(
                    guild_id,
                    item_id=item_id,
                    reference_time=self.clock.now(),
                )
            )
            return AwaitableValue(result)

        return AwaitableValue(
            CalendarDeleteResult(
                {
                    "success": False,
                    "title": None,
                    "requested_count": 0,
                    "deleted_count": 0,
                    "deleted_titles": [],
                    "pending_count": 0,
                    "pending_titles": [],
                    "pending_errors": {},
                }
            )
        )

    async def delete_item_by_title(self, guild_id, title_search):
        """Delete a single item by title matching (ignoring guild_id for shared calendar)"""
        title_search = title_search.lower()
        for item in self.items.get(self.SHARED_KEY, []):
            if title_search in item.get("title", "").lower():
                return await self.delete_item_result(
                    guild_id,
                    item_id=item.get("id"),
                    reference_time=self.clock.now(),
                )

        return CalendarDeleteResult(
            {
                "success": False,
                "title": None,
                "requested_count": 0,
                "deleted_count": 0,
                "deleted_titles": [],
                "pending_count": 0,
                "pending_titles": [],
                "pending_errors": {},
            }
        )

    async def delete_items_by_title(self, guild_id, title_search):
        """Awaitable compatibility projection over exact result transactions."""
        reference_time = self.clock.now()
        title_search = title_search.lower()
        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            requested = [
                (item.get("id"), item.get("title", "Uten tittel"))
                for item in self.items.get(self.SHARED_KEY, [])
                if title_search in item.get("title", "").lower()
            ]
            deleted_titles = []
            pending_titles = []
            pending_errors = {}
            for item_id, title in requested:
                result = await self.delete_item_result(
                    guild_id,
                    item_id=item_id,
                    reference_time=reference_time,
                )
                if result.get("deleted_count"):
                    deleted_titles.append(title)
                if result.get("pending_count"):
                    pending_titles.append(title)
                    pending_errors[title] = "external_delete_pending"

            return CalendarDeleteResult(
                {
                    "bulk": True,
                    "success": bool(deleted_titles) and not pending_titles,
                    "requested_count": len(requested),
                    "deleted_count": len(deleted_titles),
                    "deleted_titles": deleted_titles,
                    "pending_count": len(pending_titles),
                    "pending_titles": pending_titles,
                    "pending_errors": pending_errors,
                }
            )

    async def clear_calendar(self, guild_id):
        """Awaitable compatibility delegator over ``clear_calendar_result``."""
        return await self.clear_calendar_result(
            guild_id,
            reference_time=self.clock.now(),
        )

    def complete_item(self, guild_id, item_num=None, item_id=None):
        """Mark an item as complete (ignoring guild_id for shared calendar)"""
        guild_key = self.SHARED_KEY
        items = self.get_upcoming(guild_key, days=365)

        if item_id:
            for item in items:
                if item.get("id") == item_id:
                    return AwaitableValue(
                        self._run_offline(
                            lambda: self.complete_item_result(
                                guild_id,
                                item_id=item_id,
                                reference_time=self.clock.now(),
                            )
                        )
                    )
            return AwaitableValue((False, None, None))

        if item_num is not None and 1 <= item_num <= len(items):
            item = items[item_num - 1]
            return AwaitableValue(
                self._run_offline(
                    lambda: self.complete_item_result(
                        guild_id,
                        item_id=item.get("id"),
                        reference_time=self.clock.now(),
                    )
                )
            )

        return AwaitableValue((False, None, None))

    async def complete_item_by_title(self, guild_id, title_search):
        """Mark an item as complete by title matching (ignoring guild_id for shared calendar)"""
        guild_key = self.SHARED_KEY
        items = self.get_upcoming(guild_key, days=365)

        title_search = title_search.lower()
        for item in items:
            if title_search in item["title"].lower():
                return await self.complete_item_result(
                    guild_id,
                    item_id=item.get("id"),
                    reference_time=self.clock.now(),
                )

        return False, None, None

    async def complete_items_by_title(self, guild_id, title_search):
        """Mark multiple items as complete by title matching (ignoring guild_id for shared calendar)"""
        guild_key = self.SHARED_KEY
        items = self.get_upcoming(guild_key, days=365)

        title_search = title_search.lower()
        count = 0
        completed_titles = []
        has_recurring = False

        for item in items:
            if title_search in item["title"].lower():
                success, title, next_date = await self.complete_item_result(
                    guild_id,
                    item_id=item.get("id"),
                    reference_time=self.clock.now(),
                )
                if success:
                    count += 1
                    completed_titles.append(title)
                    if next_date:
                        has_recurring = True

        return count, completed_titles, has_recurring

    def edit_item(self, index, title=None, date=None, time=None, recurrence=None, description=None):
        """Edit a calendar item by its list number (1-based, matching delete/complete patterns)"""
        guild_key = self.SHARED_KEY
        items = self.get_upcoming(guild_key, days=365)

        if index is None or not (1 <= index <= len(items)):
            raise ValueError(f"Ugyldig indeks: {index}")

        item_id = items[index - 1].get("id")
        changes = {
            "title": title,
            "date": date,
            "time": time,
            "description": description,
        }
        if recurrence is not None:
            changes["recurrence"] = recurrence
        return self._legacy_edit_item_by_id(item_id, **changes)

    def edit_item_by_id(self, item_id, title=None, date=None, time=None, recurrence=None, description=None):
        """Edit a calendar item by stable ID, including past/non-upcoming entries."""
        changes = {
            "title": title,
            "date": date,
            "time": time,
            "description": description,
        }
        if recurrence is not None:
            changes["recurrence"] = recurrence
        return self._legacy_edit_item_by_id(item_id, **changes)

    def _legacy_edit_item_by_id(self, item_id, **changes):
        try:
            item = self._run_offline(
                lambda: self.edit_item_result(
                    item_id=item_id,
                    reference_time=self.clock.now(),
                    **changes,
                )
            )
        except ValueError as exc:
            raise ValueError(
                f"Fant ikke kalenderoppføring med ID: {item_id}"
            ) from exc
        return AwaitableDict(item)

    def _apply_item_updates(
        self,
        item,
        title=None,
        date=None,
        time=None,
        recurrence=_MISSING,
        description=None,
        *,
        item_type=None,
    ):
        if title is not None:
            item["title"] = title
        if date is not None:
            item["date"] = self._normalize_date_format(date)
        if time is not None:
            item["time"] = time
        if recurrence is not _MISSING:
            item["recurrence"] = recurrence
        if description is not None:
            item["description"] = description
        if item_type is not None:
            if item_type not in {"event", "task"}:
                raise ValueError("invalid_item_type")
            item["type"] = item_type

    def search_items(self, query):
        """Search calendar items by title (case-insensitive substring match)"""
        guild_key = self.SHARED_KEY
        items = self.items.get(guild_key, [])

        query = query.lower()
        matching = [
            item for item in items
            if not item.get("delete_pending") and query in item.get("title", "").lower()
        ]

        return matching

    def format_search_results(self, query):
        """Format calendar search results for Discord."""
        matches = self.search_items(query)
        if not matches:
            return f"🔎 Fant ingen kalenderoppføringer som matcher **{query}**."

        lines = [f"🔎 **Kalenderoppføringer som matcher \"{query}\":**"]
        upcoming_index_by_id = {
            item.get("id"): index
            for index, item in enumerate(self.get_upcoming(self.SHARED_KEY, days=365), 1)
        }
        for item in matches[:10]:
            time_str = f" kl. {item['time']}" if item.get("time") else ""
            status = "✅" if item.get("completed") else "📌"
            index = upcoming_index_by_id.get(item.get("id"))
            prefix = f"**{index}.** " if index is not None else ""
            lines.append(f"{status} {prefix}{item.get('title', '')} — _{item.get('date', '')}{time_str}_")

        if len(matches) > 10:
            lines.append(f"\n… og {len(matches) - 10} til.")

        lines.append("\nNumrene matcher `@inebotten kalender`-lista.")
        return "\n".join(lines)

    def _calculate_next_date(self, current_date_str, recurrence):
        """Calculate next occurrence date with month-end safety"""
        try:
            current_date = datetime.strptime(current_date_str, "%d.%m.%Y")
            
            if recurrence == "daily":
                next_date = current_date + timedelta(days=1)
            elif recurrence == "weekly":
                next_date = current_date + timedelta(weeks=1)
            elif recurrence == "biweekly":
                next_date = current_date + timedelta(weeks=2)
            elif recurrence == "monthly":
                # Handle month transition safely
                year = current_date.year + (current_date.month // 12)
                month = (current_date.month % 12) + 1
                day = current_date.day
                
                # Clamp day to max days in next month
                import calendar as py_cal
                last_day = py_cal.monthrange(year, month)[1]
                next_date = datetime(year, month, min(day, last_day))
            elif recurrence == "yearly":
                try:
                    next_date = current_date.replace(year=current_date.year + 1)
                except ValueError:
                    # Feb 29 leap year case
                    next_date = current_date.replace(year=current_date.year + 1, day=28)
            else:
                return None
                
            return next_date.strftime("%d.%m.%Y")
        except Exception as e:
            print(f"[CALENDAR] Calendar parse error: {e}")
            return None

    async def sync_from_gcal_result(
        self,
        default_guild_id=None,
        default_channel_id=None,
        *,
        reference_time: datetime,
    ) -> CalendarSyncResult:
        reference_time = self._require_aware(reference_time)
        self.last_gcal_sync_error = None
        async with self.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            credential_mutated = False
            if not self.gcal_enabled:
                try:
                    configured = await self.ensure_gcal_configured()
                    configured_call = _SettledExternal(configured)
                except ExternalOperationCancelled as exc:
                    configured = exc.result
                    configured_call = _SettledExternal(
                        configured,
                        cancelled=True,
                    )
                credential_mutated = configured.state is ExternalCommitState.CHANGED
                if not configured.ok:
                    self.last_gcal_sync_error = (
                        "Google Calendar er ikke konfigurert eller koblet til ennå."
                    )
                    self._raise_external_cancellation(
                        configured_call,
                        mutated=credential_mutated,
                        default_code=configured.error_code or "not_configured",
                    )
                    return CalendarSyncResult(
                        False,
                        credential_mutated,
                        error_code=configured.error_code or "not_configured",
                        commit_unknown=(
                            configured.state is ExternalCommitState.UNKNOWN
                        ),
                    )
                self._raise_external_cancellation(
                    configured_call,
                    mutated=credential_mutated,
                    default_code="cancelled_after_credential_refresh",
                )

            listed = await self._call_gcal(
                "list_upcoming_events_result",
                "list_upcoming_events",
                90,
                reference_time=reference_time,
            )
            credential_mutated = (
                credential_mutated
                or listed.state is ExternalCommitState.CHANGED
            )
            if not listed.ok or not isinstance(listed.value, list):
                self.last_gcal_sync_error = (
                    "Kunne ikke hente hendelser fra Google Calendar."
                )
                self._raise_external_cancellation(
                    listed,
                    mutated=credential_mutated,
                    default_code=listed.error_code or "external_read_failed",
                )
                return CalendarSyncResult(
                    False,
                    credential_mutated,
                    error_code=listed.error_code or "external_read_failed",
                    commit_unknown=(listed.state is ExternalCommitState.UNKNOWN),
                )

            try:
                candidate, added, updated, removed = self._build_sync_candidate(
                    listed.value,
                    default_channel_id=default_channel_id,
                    reference_time=reference_time,
                )
            except Exception:
                self._raise_external_cancellation(
                    listed,
                    mutated=credential_mutated,
                    default_code="cancelled_after_external_read",
                )
                return CalendarSyncResult(
                    False,
                    credential_mutated,
                    error_code="sync_transform_failed",
                    commit_unknown=False,
                )

            if candidate != self.items:
                try:
                    await self._persist_candidate(candidate)
                except ManagerMutationCancelled as exc:
                    if credential_mutated:
                        raise self._translate_post_external_cancel(exc) from exc
                    raise
                except ManagerMutationError as exc:
                    if listed.cancelled:
                        if credential_mutated:
                            raise self._translate_cancelled_external_storage_error(exc) from exc
                        raise ManagerMutationCancelled(
                            (
                                "commit_state_unknown"
                                if exc.commit_unknown
                                else "storage_write_failed"
                            ),
                            mutated=False,
                            retryable=False,
                            commit_unknown=exc.commit_unknown,
                        ) from exc
                    if credential_mutated:
                        raise ManagerMutationError(
                            "external_state_changed_storage_failed",
                            mutated=True,
                        ) from exc
                    raise
            self._raise_external_cancellation(
                listed,
                mutated=credential_mutated or bool(added or updated or removed),
                default_code="cancelled_after_external_read",
            )
            return CalendarSyncResult(
                True,
                credential_mutated or bool(added or updated or removed),
                added=added,
                updated=updated,
                removed=removed,
            )

    def _build_sync_candidate(
        self,
        gcal_events,
        *,
        default_channel_id,
        reference_time,
    ):
        candidate = deepcopy(self.items)
        bucket = candidate.setdefault(self.SHARED_KEY, [])
        by_gcal_id = {
            row.get("gcal_event_id"): row
            for row in bucket
            if row.get("gcal_event_id")
        }
        processed_recurring: set[str] = set()
        seen_ids: set[str] = set()
        added = updated = 0

        for event in gcal_events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            if not isinstance(event_id, str) or not event_id:
                continue
            canonical_id = event.get("recurringEventId") or event_id
            seen_ids.update({event_id, canonical_id})
            if event.get("recurringEventId"):
                if canonical_id in processed_recurring:
                    continue
                processed_recurring.add(canonical_id)

            summary = event.get("summary") or "Uten tittel"
            completed = summary.endswith(" [FERDIG]")
            if completed:
                summary = summary.removesuffix(" [FERDIG]").strip()
            start = event.get("start") or {}
            try:
                if start.get("dateTime"):
                    local = datetime.fromisoformat(
                        start["dateTime"].replace("Z", "+00:00")
                    ).astimezone(OSLO)
                    date_str = local.strftime("%d.%m.%Y")
                    time_str = local.strftime("%H:%M")
                elif start.get("date"):
                    local = datetime.strptime(start["date"], "%Y-%m-%d")
                    date_str = local.strftime("%d.%m.%Y")
                    time_str = None
                else:
                    continue
            except (TypeError, ValueError):
                continue

            ext = event.get("extendedProperties", {}).get("private", {})
            creator = event.get("creator", {})
            organizer = event.get("organizer", {})
            username = ext.get("discord_username")
            user_id = ext.get("discord_user_id") or "gcal_sync"
            if not username or str(username).lower() == "inebotten":
                username = creator.get("displayName") or organizer.get("displayName")
                email = creator.get("email") or organizer.get("email")
                if not username and email and self.owner_email and self.owner_name:
                    if email.lower() == self.owner_email.lower():
                        username = self.owner_name
                if not username and email:
                    username = email.split("@", 1)[0]
            username = username or self.owner_name or "Google Calendar"

            row = by_gcal_id.get(canonical_id) or by_gcal_id.get(event_id)
            if row is None:
                row = {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "username": username,
                    "title": summary,
                    "date": date_str,
                    "time": time_str,
                    "type": "event",
                    "description": event.get("description"),
                    "recurrence": None,
                    "recurrence_day": None,
                    "rrule_day": None,
                    "created_at": reference_time.isoformat(),
                    "completed": completed,
                    "gcal_event_id": canonical_id,
                    "gcal_link": event.get("htmlLink"),
                    "gcal_sync_pending": False,
                    "channel_id": (
                        str(default_channel_id)
                        if default_channel_id is not None
                        else None
                    ),
                }
                bucket.append(row)
                by_gcal_id[canonical_id] = row
                added += 1
                continue

            changes = {
                "gcal_event_id": canonical_id,
                "title": summary,
                "date": date_str,
                "time": time_str,
                "completed": completed,
                "gcal_link": event.get("htmlLink") or row.get("gcal_link"),
                "gcal_sync_pending": False,
            }
            if row.get("username") == "Google Calendar":
                changes["username"] = username
            if row.get("user_id") == "gcal_sync":
                changes["user_id"] = user_id
            if not row.get("channel_id") and default_channel_id is not None:
                changes["channel_id"] = str(default_channel_id)
            if any(row.get(key) != value for key, value in changes.items()):
                row.update(changes)
                updated += 1

        today = reference_time.astimezone(OSLO).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=None,
        )
        cutoff = today + timedelta(days=90)
        kept = []
        removed = 0
        for row in bucket:
            gcal_id = row.get("gcal_event_id")
            if not gcal_id or gcal_id in seen_ids:
                kept.append(row)
                continue
            try:
                row_date = datetime.strptime(row.get("date", ""), "%d.%m.%Y")
            except (TypeError, ValueError):
                kept.append(row)
                continue
            if today <= row_date <= cutoff:
                removed += 1
            else:
                kept.append(row)
        candidate[self.SHARED_KEY] = kept
        return candidate, added, updated, removed

    async def sync_from_gcal(self, default_guild_id=None, default_channel_id=None):
        """Legacy count projection over the structured atomic sync."""
        result = await self.sync_from_gcal_result(
            default_guild_id,
            default_channel_id,
            reference_time=self.clock.now(),
        )
        return result.added + result.updated + result.removed if result.ok else 0

    def snapshot_pending_items(
        self,
        *,
        reference_time: datetime,
    ) -> tuple[dict[str, object], ...]:
        reference_time = self._require_aware(reference_time)
        bucket = self.items.get(self.SHARED_KEY, [])
        if not isinstance(bucket, list):
            raise ValueError("invalid_target_state")
        for item in bucket:
            if not isinstance(item, dict):
                raise ValueError("invalid_target_state")
            if type(item.get("completed", False)) is not bool:
                raise ValueError("invalid_target_state")
            if type(item.get("delete_pending", False)) is not bool:
                raise ValueError("invalid_target_state")
        return tuple(
            deepcopy(
                self.get_upcoming(
                    self.SHARED_KEY,
                    days=365,
                    reference_time=reference_time,
                )
            )
        )

    def snapshot_target_items(
        self,
        *,
        reference_time: datetime,
    ) -> tuple[dict[str, object], ...]:
        """Return every future target in stable display order, without a horizon."""

        aware = self._require_aware(reference_time)
        today = aware.astimezone(OSLO).date()
        bucket = self.items.get(self.SHARED_KEY, [])
        if not isinstance(bucket, list):
            raise ValueError("invalid_target_state")
        rows: list[tuple[datetime, int, dict[str, object]]] = []
        for position, item in enumerate(bucket):
            if not isinstance(item, dict):
                raise ValueError("invalid_target_state")
            if type(item.get("completed", False)) is not bool:
                raise ValueError("invalid_target_state")
            if type(item.get("delete_pending", False)) is not bool:
                raise ValueError("invalid_target_state")
            if item.get("completed") or item.get("delete_pending"):
                continue
            try:
                item_date = datetime.strptime(
                    str(item.get("date", "")), "%d.%m.%Y"
                )
            except ValueError:
                continue
            if item_date.date() >= today:
                rows.append((item_date, position, item))
        rows.sort(key=lambda row: (row[0], row[1]))
        return tuple(deepcopy(item) for _, _, item in rows)

    @staticmethod
    def _canonical_delivery_due_at(item: dict[str, object]) -> datetime | None:
        """Project one stored calendar wall time to one unambiguous Oslo instant."""
        date_value = item.get("date")
        time_value = item.get("time")
        if not isinstance(date_value, str):
            return None
        if time_value in (None, ""):
            canonical_time = "09:00"
        elif isinstance(time_value, str):
            canonical_time = time_value
        else:
            return None

        try:
            date_part = datetime.strptime(date_value, "%d.%m.%Y")
            time_part = datetime.strptime(canonical_time, "%H:%M")
        except (TypeError, ValueError):
            return None
        wall_time = date_part.replace(
            hour=time_part.hour,
            minute=time_part.minute,
            second=0,
            microsecond=0,
        )

        # A stored calendar row has no fold/offset field.  Fail closed when
        # that wall time maps to zero or two UTC instants rather than silently
        # selecting the wrong occurrence.  Normal wall times yield the same
        # instant for both fold probes and are deduplicated below.
        candidates: dict[datetime, datetime] = {}
        for fold in (0, 1):
            aware = wall_time.replace(tzinfo=OSLO, fold=fold)
            instant = aware.astimezone(timezone.utc)
            round_trip = instant.astimezone(OSLO).replace(tzinfo=None)
            if round_trip == wall_time:
                candidates.setdefault(instant, aware)
        if len(candidates) != 1:
            return None
        return next(iter(candidates.values()))

    def _delivery_occurrence_rows(
        self,
        *,
        reference_time: datetime,
    ) -> list[dict[str, object]]:
        """Build the detached canonical rows shared by snapshot and claim checks."""
        self._require_aware(reference_time)
        bucket = self.items.get(self.SHARED_KEY, [])
        if not isinstance(bucket, list):
            return []

        id_counts: dict[str, int] = {}
        for item in bucket:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if (
                isinstance(item_id, str)
                and bool(item_id)
                and item_id == item_id.strip()
                and ":" not in item_id
            ):
                id_counts[item_id] = id_counts.get(item_id, 0) + 1

        rows: list[dict[str, object]] = []
        for item in bucket:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if (
                not isinstance(item_id, str)
                or ":" in item_id
                or id_counts.get(item_id) != 1
            ):
                continue
            completed = item.get("completed", False)
            delete_pending = item.get("delete_pending", False)
            if completed is not False or delete_pending is not False:
                continue
            title = item.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            due_at = self._canonical_delivery_due_at(item)
            if due_at is None:
                continue

            stored_time = item.get("time")
            rows.append(
                {
                    "source_kind": "calendar",
                    "id": item_id,
                    "due_at": due_at,
                    "status": "active",
                    "delete_pending": False,
                    "user_id": deepcopy(item.get("user_id")),
                    "channel_id": deepcopy(item.get("channel_id")),
                    "title": title.strip(),
                    "time": (
                        None
                        if stored_time in (None, "")
                        else due_at.strftime("%H:%M")
                    ),
                }
            )

        rows.sort(
            key=lambda row: (
                row["due_at"].astimezone(timezone.utc),
                row["id"],
            )
        )
        return rows

    def snapshot_delivery_occurrences(
        self,
        *,
        reference_time: datetime,
    ) -> tuple[dict[str, object], ...]:
        """Return detached active occurrences eligible for checker delivery."""
        return tuple(
            deepcopy(
                self._delivery_occurrence_rows(
                    reference_time=reference_time,
                )
            )
        )

    def matches_delivery_fingerprint(
        self,
        fingerprint,
        *,
        reference_time: datetime,
    ) -> bool:
        """Revalidate one frozen occurrence while the caller holds its scope."""
        self._require_aware(reference_time)
        assert_held = getattr(self.mutation_coordinator, "assert_held", None)
        if callable(assert_held):
            assert_held(CALENDAR_SHARED_SCOPE)

        if not isinstance(fingerprint, tuple) or len(fingerprint) != 4:
            return False
        item_id, due_at, status, delete_pending = fingerprint
        if (
            not isinstance(item_id, str)
            or not item_id
            or item_id != item_id.strip()
            or ":" in item_id
            or not isinstance(due_at, datetime)
            or due_at.tzinfo is None
            or due_at.utcoffset() is None
            or due_at.microsecond
            or status != "active"
            or delete_pending is not False
        ):
            return False

        for row in self._delivery_occurrence_rows(
            reference_time=reference_time,
        ):
            if row["id"] != item_id:
                continue
            current = (
                row["id"],
                row["due_at"],
                row["status"],
                row["delete_pending"],
            )
            return current == fingerprint
        return False

    def snapshot_all_item_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        seen: set[str] = set()
        bucket = self.items.get(self.SHARED_KEY, [])
        if not isinstance(bucket, list):
            raise ValueError("invalid_target_state")
        for item in bucket:
            if not isinstance(item, dict):
                raise ValueError("invalid_target_state")
            item_id = item.get("id")
            if (
                not isinstance(item_id, str)
                or not item_id.strip()
                or item_id != item_id.strip()
                or item_id in seen
            ):
                raise ValueError("invalid_target_state")
            seen.add(item_id)
            ids.append(item_id)
        return tuple(sorted(ids))

    def get_upcoming(
        self,
        guild_id,
        days=30,
        include_completed=False,
        *,
        reference_time=None,
    ):
        """
        Get upcoming calendar items (ignoring guild_id for shared calendar)
        """
        guild_key = self.SHARED_KEY

        if reference_time is None:
            now = self.clock.now().astimezone(OSLO).replace(tzinfo=None)
        else:
            if (
                reference_time.tzinfo is None
                or reference_time.utcoffset() is None
            ):
                raise ValueError("reference_time_must_be_aware")
            now = reference_time.astimezone(OSLO).replace(tzinfo=None)

        if guild_key not in self.items:
            return []

        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = today + timedelta(days=days)

        upcoming = []
        for item in self.items[guild_key]:
            if item.get("delete_pending"):
                continue
            if not include_completed and item.get("completed"):
                continue

            if item.get("date"):
                try:
                    item_date = datetime.strptime(item["date"], "%d.%m.%Y")
                    if include_completed or (today <= item_date <= cutoff):
                        upcoming.append(item)
                except Exception as e:
                    print(f"[CALENDAR] Calendar loop error: {e}")
                    continue

        # Sort by date
        upcoming.sort(key=lambda x: datetime.strptime(x["date"], "%d.%m.%Y"))
        return upcoming

    def format_list(self, guild_id, days=90, show_completed=False, footer=None):
        """
        Format calendar items for display (ignoring guild_id for shared calendar)
        """
        items = self.get_upcoming(self.SHARED_KEY, days=days, include_completed=False)

        if not items:
            return None

        lines = ["📅 **Kalender:**"]

        for i, item in enumerate(items[:10], 1):
            time_str = f" kl. {item['time']}" if item.get("time") else ""

            if item.get("completed"):
                status_indicator = "✓"
            elif item.get("gcal_event_id") or item.get("gcal_link"):
                status_indicator = "📅"
            else:
                status_indicator = "📌"

            recurrence_str = ""
            if item.get("recurrence"):
                labels = {
                    "weekly": "uke",
                    "biweekly": "2uker",
                    "monthly": "mnd",
                    "yearly": "år",
                }
                if item.get("recurrence_day"):
                    recurrence_str = f" 🔄 {item['recurrence_day'][:3].lower()} {labels.get(item['recurrence'], '')}"
                else:
                    recurrence_str = f" 🔄 {labels.get(item['recurrence'], '')}"

            title_display = (
                f"~~{item['title']}~~" if item.get("completed") else item["title"]
            )
            
            creator_str = f" ({item.get('username', 'Ukjent')})"

            lines.append(
                f"{status_indicator} **{i}.** {title_display} — _{item['date']}{time_str}_{creator_str}{recurrence_str}"
            )

        if show_completed:
            all_items = self.items.get(str(guild_id), [])
            completed = [i for i in all_items if i.get("completed")][:3]
            if completed:
                lines.append("\n✅ **Nylig fullført:**")
                for item in completed:
                    lines.append(f"  ✓ ~~{item['title']}~~")

        return "\n".join(lines)

    def format_single_item(self, item):
        """Format a single item for display"""
        time_str = f" kl. {item['time']}" if item.get("time") else ""

        lines = [
            f"✅ **Lagt til i kalenderen!**",
            "",
            f"📌 **{item['title']}**",
            f"📅 {item['date']}{time_str}",
            f"👤 Lagt til av: {item.get('username', 'Ukjent')}",
        ]

        if item.get("recurrence"):
            labels = {
                "weekly": "hver uke",
                "biweekly": "annenhver uke",
                "monthly": "hver måned",
                "yearly": "hvert år",
            }
            if item.get("recurrence_day"):
                lines.append(
                    f"🔄 Gjentas hver {item['recurrence_day']} ({labels.get(item['recurrence'], item['recurrence'])})"
                )
            else:
                lines.append(
                    f"🔄 Gjentas {labels.get(item['recurrence'], item['recurrence'])}"
                )

        if item.get("gcal_link"):
            lines.append("")
            lines.append(f"📅 [Se i Google Calendar]({item['gcal_link']})")

        lines.append("")
        lines.append("— *Bruk `@inebotten kalender` for å se alt*")

        return "\n".join(lines)

    def _validate_date_format(self, date_str):
        """Validate DD.MM.YYYY format"""
        try:
            datetime.strptime(date_str, "%d.%m.%Y")
            return True
        except (ValueError, TypeError):
            return False

    def _normalize_date_format(self, date_str):
        """Normalize date-ish values to DD.MM.YYYY when possible."""
        if not isinstance(date_str, str):
            return date_str

        value = date_str.strip().replace("/", ".")
        if self._validate_date_format(value):
            return datetime.strptime(value, "%d.%m.%Y").strftime("%d.%m.%Y")

        match = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", value)
        if not match:
            return date_str

        day = int(match.group(1))
        month = int(match.group(2))
        year_value = match.group(3)
        if year_value is None:
            year = datetime.now().year
        elif len(year_value) == 2:
            year = 2000 + int(year_value)
        else:
            year = int(year_value)

        try:
            return datetime(year, month, day).strftime("%d.%m.%Y")
        except ValueError:
            return date_str


if __name__ == "__main__":
    # Test
    print("=== Calendar Manager Test ===\n")

    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as tmp:
        storage_path = tmp.name
    manager = CalendarManager(storage_path=storage_path)

    # Add various items
    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Grillfest",
        date_str="28.03.2026",
        time_str="18:00",
    )
    print("Added: Grillfest")

    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Sende meldekort",
        date_str="04.04.2026",
        time_str="10:00",
        recurrence="biweekly",
        recurrence_day="lørdag",
    )
    print("Added: Sende meldekort (recurring)")

    manager.add_item(
        guild_id="test",
        user_id="user1",
        username="Ola",
        title="Kjøpe melk",
        date_str="29.03.2026",
    )
    print("Added: Kjøpe melk")

    print("\n--- Calendar ---")
    print(manager.format_list("test"))

    print("\n--- Complete item #2 ---")
    success, title, next_date = manager.complete_item("test", item_num=2)
    print(f"Completed: {title}, next: {next_date}")

    print("\n--- Calendar after ---")
    print(manager.format_list("test"))

    manager.storage_path.unlink(missing_ok=True)
