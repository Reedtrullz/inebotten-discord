#!/usr/bin/env python3
"""
Birthday Manager for Inebotten
Tracks birthdays for Discord group members with Google Calendar sync
"""

import asyncio
import json
import re
import warnings
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Required, TypedDict

from core.dispatch_result import (
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationCancelled,
)
from cal_system.google_calendar_manager import (
    ExternalOperationCancelled,
    GoogleCalendarManager,
)
from core.mutation_coordinator import BIRTHDAY_STORE_SCOPE, MutationCoordinator
from core.message_context import RoutingContext
from utils.json_storage import hermes_discord_data_path, write_json_atomic

# Suppress requests/urllib3 version warnings
warnings.filterwarnings("ignore", category=UserWarning, module="requests")


@dataclass(frozen=True, slots=True)
class BirthdayWriteResult:
    success: bool
    mutated: bool
    sync_pending: bool
    error_code: str | None = None
    commit_unknown: bool = False

    def __bool__(self) -> bool:
        return self.success or self.mutated


@dataclass(frozen=True, slots=True)
class _SettledBirthdayExternal:
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


class BirthdayManager:
    """
    Manages birthdays for Discord group members with Google Calendar sync
    """

    def __init__(
        self,
        storage_path=None,
        *,
        mutation_coordinator: MutationCoordinator | None = None,
        gcal_manager=None,
    ):
        if storage_path is None:
            storage_path = hermes_discord_data_path("birthdays.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.birthdays = self._load_birthdays()
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()
        self.gcal = gcal_manager

    @property
    def gcal_enabled(self) -> bool:
        if self.gcal is None:
            return False
        enabled = getattr(self.gcal, "enabled", None)
        if enabled is not None:
            return bool(enabled)
        configured = getattr(self.gcal, "is_configured", None)
        return bool(configured()) if callable(configured) else True

    @gcal_enabled.setter
    def gcal_enabled(self, value: bool) -> None:
        # Old tests explicitly set this after clearing ``gcal``.
        if value and self.gcal is None:
            raise AttributeError("missing_gcal_manager")

    def _load_birthdays(self):
        """Load birthdays from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[FEATURES] Birthday load error: {e}")
                return {}
        return {}

    def _save_birthdays(self, candidate=None):
        """Save birthdays to storage"""
        write_json_atomic(
            self.storage_path,
            self.birthdays if candidate is None else candidate,
        )

    async def _persist_candidate(self, candidate):
        writer = asyncio.create_task(
            asyncio.to_thread(self._save_birthdays, candidate)
        )
        outer_cancelled = False
        while True:
            try:
                await asyncio.shield(writer)
                break
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is None or current.cancelling() == 0:
                    return BirthdayWriteResult(
                        False,
                        False,
                        False,
                        "commit_state_unknown",
                        True,
                    )
                outer_cancelled = True
                current.uncancel()
                if writer.done():
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
                return BirthdayWriteResult(
                    False,
                    False,
                    False,
                    "storage_write_failed",
                )
        if writer.cancelled():
            if outer_cancelled:
                raise ManagerMutationCancelled(
                    "commit_state_unknown",
                    mutated=False,
                    retryable=False,
                    commit_unknown=True,
                )
            return BirthdayWriteResult(
                False,
                False,
                False,
                "commit_state_unknown",
                True,
            )
        if writer.exception() is not None:
            if outer_cancelled:
                raise ManagerMutationCancelled(
                    "storage_write_failed",
                    mutated=False,
                    retryable=True,
                ) from writer.exception()
            return BirthdayWriteResult(
                False,
                False,
                False,
                "storage_write_failed",
            )
        self.birthdays = candidate
        if outer_cancelled:
            raise ManagerMutationCancelled(
                "cancelled_after_storage_commit",
                mutated=True,
                retryable=False,
            )
        return None

    @staticmethod
    def _run_offline(factory):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(factory())
        raise RuntimeError("use_async_result_api")

    def _validate_birthday_date(self, day, month, year=None):
        try:
            datetime(int(year) if year else 2000, int(month), int(day))
        except (TypeError, ValueError):
            raise ValueError(f"Ugyldig bursdagsdato: {day}.{month}")

    def _birthday_date_for_year(self, year, month, day):
        """Return the observed birthday date for a year.

        Leap-day birthdays are observed on 28 February in non-leap years.
        """
        try:
            return datetime(year, month, day)
        except ValueError:
            if int(month) == 2 and int(day) == 29:
                return datetime(year, 2, 28)
            raise

    @staticmethod
    def _aware_reference(reference_time=None):
        from zoneinfo import ZoneInfo

        oslo = ZoneInfo("Europe/Oslo")
        if reference_time is None:
            value = datetime.now(oslo)
            return value if value.tzinfo is not None else value.replace(tzinfo=oslo)
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("reference_time_must_be_aware")
        return reference_time.astimezone(oslo)

    async def _call_gcal_result(self, result_name, legacy_name, *args, **kwargs):
        if self.gcal is None or not self.gcal_enabled:
            return _SettledBirthdayExternal(
                ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="integration_disabled",
                )
            )
        expects_delete = result_name == "delete_event_result"

        def valid_success(value):
            return (
                value is True
                if expects_delete
                else isinstance(value, dict) and bool(value.get("id"))
            )

        def normalize(value):
            if not isinstance(value, ExternalMutationResult):
                if valid_success(value):
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
            if value.ok and not (
                value.state is ExternalCommitState.CHANGED
                and valid_success(value.value)
            ):
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNKNOWN,
                    error_code="external_commit_unknown",
                )
            return value

        method = getattr(self.gcal, result_name, None)
        if callable(method):
            try:
                value = method(*args, **kwargs)
                if hasattr(value, "__await__"):
                    value = await value
                return _SettledBirthdayExternal(normalize(value))
            except ExternalOperationCancelled as exc:
                return _SettledBirthdayExternal(
                    normalize(exc.result),
                    cancelled=True,
                )
            except Exception:
                return _SettledBirthdayExternal(
                    ExternalMutationResult(
                        False,
                        ExternalCommitState.UNKNOWN,
                        error_code="external_commit_unknown",
                    )
                )
        legacy = getattr(self.gcal, legacy_name, None)
        if not callable(legacy):
            return _SettledBirthdayExternal(
                ExternalMutationResult(
                    False,
                    ExternalCommitState.UNKNOWN,
                    error_code="external_commit_unknown",
                )
            )
        try:
            value = await GoogleCalendarManager._await_worker(
                legacy,
                *args,
                **kwargs,
            )
        except ExternalOperationCancelled as exc:
            return _SettledBirthdayExternal(
                normalize(exc.result),
                cancelled=True,
            )
        except Exception:
            value = None
        return _SettledBirthdayExternal(normalize(value))

    @staticmethod
    def _raise_external_cancellation(external, *, mutated, default_code):
        if not external.cancelled:
            return
        if external.state is ExternalCommitState.UNKNOWN:
            raise ManagerMutationCancelled(
                "external_commit_unknown",
                mutated=mutated,
                retryable=False,
                commit_unknown=True,
            )
        raise ManagerMutationCancelled(
            default_code,
            mutated=mutated,
            retryable=False,
        )

    @staticmethod
    def _translate_post_external_cancel(exc):
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

    def _birthday_event_parameters(
        self,
        username,
        day,
        month,
        year,
        *,
        reference_time,
    ):
        current_year = reference_time.year
        birthday = self._birthday_date_for_year(current_year, month, day).replace(
            hour=9,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=reference_time.tzinfo,
        )
        if birthday < reference_time:
            birthday = self._birthday_date_for_year(
                current_year + 1,
                month,
                day,
            ).replace(
                hour=9,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=reference_time.tzinfo,
            )
        description = f"🎂 Bursdag for {username}"
        if year:
            next_age = birthday.year - int(year)
            description += f"\nBlir {next_age} år gammel!"
        return {
            "title": f"🎂 {username}",
            "start_time": birthday.isoformat(),
            "end_time": birthday.replace(hour=23, minute=59).isoformat(),
            "description": description,
            "recurrence": "yearly",
        }

    async def _write_birthday_result(
        self,
        guild_id,
        user_id,
        username,
        day,
        month,
        year,
        *,
        create_only,
        allow_replace,
        reference_time=None,
    ) -> BirthdayWriteResult:
        self._validate_birthday_date(day, month, year)
        reference_time = self._aware_reference(reference_time)
        guild_key = str(guild_id)
        user_key = str(user_id)

        async with self.mutation_coordinator.hold(BIRTHDAY_STORE_SCOPE):
            existing = self.birthdays.get(guild_key, {}).get(user_key)
            if create_only and existing is not None:
                return BirthdayWriteResult(
                    False,
                    False,
                    False,
                    "already_exists",
                )
            if not allow_replace and not create_only and existing is None:
                return BirthdayWriteResult(
                    False,
                    False,
                    False,
                    "not_found",
                )

            candidate = deepcopy(self.birthdays)
            bucket = candidate.setdefault(guild_key, {})
            if username is None and existing is not None:
                username = existing.get("username") or str(user_id)
            old_gcal_event_id = existing.get("gcal_event_id") if existing else None
            record = deepcopy(existing) if existing else {}
            stored_year = (
                existing.get("year")
                if existing is not None and year is None
                else (int(year) if year is not None else None)
            )
            record.update(
                {
                    "username": username,
                    "day": int(day),
                    "month": int(month),
                    "year": stored_year,
                    "gcal_event_id": old_gcal_event_id,
                }
            )
            if existing is None:
                record["added_at"] = reference_time.isoformat()
            else:
                record["updated_at"] = reference_time.isoformat()
            wants_external = self.gcal_enabled
            record["gcal_sync_pending"] = wants_external
            bucket[user_key] = record
            first_save_error = await self._persist_candidate(candidate)
            if first_save_error is not None:
                return first_save_error
            if not wants_external:
                return BirthdayWriteResult(True, True, False)

            external_changed = False
            if old_gcal_event_id:
                deleted = await self._call_gcal_result(
                    "delete_event_result",
                    "delete_event",
                    old_gcal_event_id,
                )
                if deleted.state is ExternalCommitState.UNKNOWN:
                    self._raise_external_cancellation(
                        deleted,
                        mutated=True,
                        default_code="external_commit_unknown",
                    )
                    return BirthdayWriteResult(
                        False,
                        True,
                        True,
                        "external_commit_unknown",
                        True,
                    )
                delete_absent = (
                    deleted.state is ExternalCommitState.UNCHANGED
                    and deleted.error_code == "external_not_found"
                )
                if not deleted.ok and not delete_absent:
                    self._raise_external_cancellation(
                        deleted,
                        mutated=True,
                        default_code="external_sync_pending",
                    )
                    return BirthdayWriteResult(
                        False,
                        True,
                        True,
                        "external_sync_pending",
                    )
                external_changed = external_changed or deleted.ok
                cleared_candidate = deepcopy(self.birthdays)
                cleared_record = cleared_candidate[guild_key][user_key]
                cleared_record["gcal_event_id"] = None
                try:
                    clear_save_error = await self._persist_candidate(
                        cleared_candidate
                    )
                except ManagerMutationCancelled as exc:
                    raise self._translate_post_external_cancel(exc) from exc
                if clear_save_error is not None:
                    if deleted.cancelled:
                        raise ManagerMutationCancelled(
                            (
                                "commit_state_unknown"
                                if clear_save_error.commit_unknown
                                else "external_state_changed_storage_failed"
                            ),
                            mutated=True,
                            retryable=False,
                            commit_unknown=clear_save_error.commit_unknown,
                        )
                    return BirthdayWriteResult(
                        False,
                        True,
                        True,
                        (
                            "external_state_changed_storage_failed"
                            if external_changed
                            else "storage_write_failed"
                        ),
                    )
                self._raise_external_cancellation(
                    deleted,
                    mutated=True,
                    default_code="cancelled_after_external_commit",
                )

            parameters = self._birthday_event_parameters(
                username,
                int(day),
                int(month),
                stored_year,
                reference_time=reference_time,
            )
            created = await self._call_gcal_result(
                "create_event_result",
                "create_event",
                **parameters,
            )
            if created.state is ExternalCommitState.UNKNOWN:
                self._raise_external_cancellation(
                    created,
                    mutated=True,
                    default_code="external_commit_unknown",
                )
                return BirthdayWriteResult(
                    False,
                    True,
                    True,
                    "external_commit_unknown",
                    True,
                )
            if not created.ok or created.state is not ExternalCommitState.CHANGED:
                self._raise_external_cancellation(
                    created,
                    mutated=True,
                    default_code="external_sync_pending",
                )
                return BirthdayWriteResult(
                    False,
                    True,
                    True,
                    "external_sync_pending",
                )
            external_changed = True

            final_candidate = deepcopy(self.birthdays)
            final_record = final_candidate[guild_key][user_key]
            value = created.value if isinstance(created.value, dict) else {}
            final_record["gcal_event_id"] = value.get("id")
            final_record["gcal_sync_pending"] = False
            try:
                second_save_error = await self._persist_candidate(final_candidate)
            except ManagerMutationCancelled as exc:
                raise self._translate_post_external_cancel(exc) from exc
            if second_save_error is not None:
                if created.cancelled:
                    raise ManagerMutationCancelled(
                        (
                            "commit_state_unknown"
                            if second_save_error.commit_unknown
                            else "external_state_changed_storage_failed"
                        ),
                        mutated=True,
                        retryable=False,
                        commit_unknown=second_save_error.commit_unknown,
                    )
                return BirthdayWriteResult(
                    False,
                    True,
                    True,
                    "external_state_changed_storage_failed",
                )
            self._raise_external_cancellation(
                created,
                mutated=True,
                default_code="cancelled_after_external_commit",
            )
            return BirthdayWriteResult(True, True, False)

    async def create_birthday_result(
        self,
        guild_id,
        user_id,
        display_name,
        day,
        month,
        year=None,
        *,
        reference_time=None,
    ) -> BirthdayWriteResult:
        return await self._write_birthday_result(
            guild_id,
            user_id,
            display_name,
            day,
            month,
            year,
            create_only=True,
            allow_replace=False,
            reference_time=reference_time,
        )

    async def edit_birthday_by_user_id_result(
        self,
        guild_id,
        user_id,
        day,
        month,
        year=None,
        *,
        reference_time=None,
    ) -> BirthdayWriteResult:
        return await self._write_birthday_result(
            guild_id,
            user_id,
            None,
            day,
            month,
            year,
            create_only=False,
            allow_replace=False,
            reference_time=reference_time,
        )

    def snapshot_pending_user(self, scope_id, user_id):
        record = self.birthdays.get(str(scope_id), {}).get(str(user_id))
        return deepcopy(record) if record is not None else None

    def add_birthday(self, guild_id, user_id, username, day, month, year=None):
        """
        Add a birthday for a user

        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            username: Display name
            day: Day of month (1-31)
            month: Month (1-12)
            year: Optional birth year

        Returns:
            True if successful
        """
        try:
            result = self._run_offline(
                lambda: self._write_birthday_result(
                    guild_id,
                    user_id,
                    username,
                    day,
                    month,
                    year,
                    create_only=False,
                    allow_replace=True,
                )
            )
        except ValueError:
            return False
        return bool(result)

    def _sync_birthday_to_gcal(self, username, day, month, year=None):
        """
        Create a recurring yearly birthday event in Google Calendar

        Args:
            username: Name of the person
            day: Day of month
            month: Month (1-12)
            year: Optional birth year

        Returns:
            Google Calendar event dict or None
        """
        if not self.gcal or not self.gcal_enabled:
            return None

        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        current_year = datetime.now().year

        # Create the birthday event for this year (or next if passed)
        try:
            birthday_this_year = datetime(
                current_year, month, day, 9, 0, 0, tzinfo=ZoneInfo("Europe/Oslo")
            )
            if birthday_this_year < datetime.now(ZoneInfo("Europe/Oslo")):
                # Birthday already passed this year, start from next year
                birthday_this_year = datetime(
                    current_year + 1,
                    month,
                    day,
                    9,
                    0,
                    0,
                    tzinfo=ZoneInfo("Europe/Oslo"),
                )
        except Exception as e:
            print(f"[FEATURES] Birthday parse error: {e}")
            return None

        # End time (all-day event or specific time)
        end_time = birthday_this_year.replace(hour=23, minute=59)

        # Build description
        description = f"🎂 Bursdag for {username}"
        if year:
            age = current_year - year
            if (datetime.now().month, datetime.now().day) < (month, day):
                age -= 1
            description += f"\nBlir {age + 1} år gammel!"

        result = self.gcal.create_event(
            title=f"🎂 {username}",
            start_time=birthday_this_year.isoformat(),
            end_time=end_time.isoformat(),
            description=description,
            recurrence="yearly",
        )

        return result

    def remove_birthday(self, guild_id, user_id):
        """Remove a user's birthday"""
        result = self._run_offline(
            lambda: self.remove_birthday_result(guild_id, user_id)
        )
        return bool(result)

    async def remove_birthday_result(self, guild_id, user_id):
        guild_key = str(guild_id)
        user_key = str(user_id)
        async with self.mutation_coordinator.hold(BIRTHDAY_STORE_SCOPE):
            existing = self.birthdays.get(guild_key, {}).get(user_key)
            if existing is None:
                return BirthdayWriteResult(False, False, False, "not_found")
            event_id = existing.get("gcal_event_id")
            if not (self.gcal_enabled and event_id):
                candidate = deepcopy(self.birthdays)
                del candidate[guild_key][user_key]
                failed = await self._persist_candidate(candidate)
                return failed or BirthdayWriteResult(True, True, False)

            pending_candidate = deepcopy(self.birthdays)
            pending_candidate[guild_key][user_key]["gcal_sync_pending"] = True
            failed = await self._persist_candidate(pending_candidate)
            if failed is not None:
                return failed
            deleted = await self._call_gcal_result(
                "delete_event_result",
                "delete_event",
                event_id,
            )
            if deleted.state is ExternalCommitState.UNKNOWN:
                self._raise_external_cancellation(
                    deleted,
                    mutated=True,
                    default_code="external_commit_unknown",
                )
                return BirthdayWriteResult(
                    False, True, True, "external_commit_unknown", True
                )
            if not deleted.ok and deleted.error_code != "external_not_found":
                self._raise_external_cancellation(
                    deleted,
                    mutated=True,
                    default_code="external_sync_pending",
                )
                return BirthdayWriteResult(
                    False, True, True, "external_sync_pending"
                )
            final_candidate = deepcopy(self.birthdays)
            del final_candidate[guild_key][user_key]
            try:
                failed = await self._persist_candidate(final_candidate)
            except ManagerMutationCancelled as exc:
                raise self._translate_post_external_cancel(exc) from exc
            if failed is not None:
                return BirthdayWriteResult(
                    False,
                    True,
                    True,
                    (
                        "external_state_changed_storage_failed"
                        if deleted.ok
                        else "storage_write_failed"
                    ),
                )
            self._raise_external_cancellation(
                deleted,
                mutated=True,
                default_code="cancelled_after_external_commit",
            )
            return BirthdayWriteResult(True, True, False)

    def edit_birthday(self, guild_id, name, day, month, year=None):
        """
        Edit a birthday by username (case-insensitive)

        Args:
            guild_id: Discord guild ID
            name: Username to search for
            day: New day of month (1-31)
            month: New month (1-12)
            year: Optional new birth year

        Returns:
            Updated birthday dict

        Raises:
            ValueError: If username not found
        """
        guild_key = str(guild_id)
        if guild_key not in self.birthdays:
            raise ValueError(f"Birthday for {name} not found")

        self._validate_birthday_date(day, month, year)

        name_lower = name.lower()
        target_user_id = None
        for user_id, data in self.birthdays[guild_key].items():
            if data.get("username", "").lower() == name_lower:
                target_user_id = user_id
                break

        if target_user_id is None:
            raise ValueError(f"Birthday for {name} not found")
        result = self._run_offline(
            lambda: self.edit_birthday_by_user_id_result(
                guild_id,
                target_user_id,
                day,
                month,
                year,
            )
        )
        if not result:
            raise RuntimeError(result.error_code or "birthday_update_failed")
        updated = self.snapshot_pending_user(guild_id, target_user_id)
        if updated is None:
            raise RuntimeError("birthday_update_missing")
        return updated

    def edit_birthday_by_user_id(
        self,
        guild_id,
        user_id,
        day,
        month,
        year=None,
    ):
        result = self._run_offline(
            lambda: self.edit_birthday_by_user_id_result(
                guild_id,
                user_id,
                day,
                month,
                year,
            )
        )
        if not result:
            raise ValueError(f"Birthday for {user_id} not found")
        updated = self.snapshot_pending_user(guild_id, user_id)
        if updated is None:
            raise ValueError(f"Birthday for {user_id} not found")
        return updated

    def get_todays_birthdays(self, guild_id, *, reference_time=None):
        """
        Get birthdays for today

        Returns:
            List of (username, age) tuples
        """
        today = self._aware_reference(reference_time)
        return self._get_birthdays_for_date(
            guild_id,
            today.month,
            today.day,
            reference_time=today,
        )

    def get_upcoming_birthdays(
        self,
        guild_id,
        days=30,
        *,
        reference_time=None,
    ):
        """
        Get upcoming birthdays within N days

        Returns:
            List of dicts with birthday info
        """
        reference = self._aware_reference(reference_time)
        today = reference.replace(tzinfo=None)
        upcoming = []

        guild_key = str(guild_id)
        if guild_key not in self.birthdays:
            return upcoming

        for user_id, data in self.birthdays[guild_key].items():
            birthday_date = self._birthday_date_for_year(today.year, data["month"], data["day"])

            # If birthday passed this year, check next year
            if birthday_date < today:
                birthday_date = self._birthday_date_for_year(today.year + 1, data["month"], data["day"])

            days_until = (birthday_date.date() - today.date()).days

            if 0 <= days_until <= days:
                age = None
                if data.get("year"):
                    age = today.year - data["year"]
                    this_year_birthday = self._birthday_date_for_year(today.year, data["month"], data["day"])
                    if today.date() < this_year_birthday.date():
                        age -= 1

                upcoming.append(
                    {
                        "username": data["username"],
                        "day": data["day"],
                        "month": data["month"],
                        "days_until": days_until,
                        "age": age,
                        "turning": age + 1 if age else None,
                    }
                )

        # Sort by days until
        upcoming.sort(key=lambda x: x["days_until"])
        return upcoming

    def _get_birthdays_for_date(
        self,
        guild_id,
        month,
        day,
        *,
        reference_time=None,
    ):
        """Get birthdays for a specific date"""
        guild_key = str(guild_id)

        if guild_key not in self.birthdays:
            return []

        matches = []
        today = self._aware_reference(reference_time).replace(tzinfo=None)

        for user_id, data in self.birthdays[guild_key].items():
            if data["month"] == month and data["day"] == day:
                age = None
                if data.get("year"):
                    age = today.year - data["year"]
                    if (today.month, today.day) < (data["month"], data["day"]):
                        age -= 1

                matches.append((data["username"], age))

        return matches

    def format_birthday_greeting(self, username, age=None):
        """Format a birthday greeting"""
        import random

        greetings = [
            "Gratulerer med dagen! 🎉",
            "Hurra for deg! 🎂",
            "God bursdag! 🎈",
            "Tillykke med fødselsdagen! 🎁",
            "Ha en fin bursdag! 🎊",
        ]

        greeting = random.choice(greetings)

        lines = [
            f"🎂 **Bursdag i dag!**",
            "",
            f"{greeting}",
            f"**{username}** feirer bursdag i dag!",
        ]

        if age:
            lines.append(f"🎉 {age} år! 🎉")

        lines.append("")
        lines.append("— *🎈🎁🎂*")

        return "\n".join(lines)

    def format_upcoming_birthdays(
        self,
        guild_id,
        days=30,
        *,
        reference_time=None,
    ):
        """Format upcoming birthdays list"""
        upcoming = self.get_upcoming_birthdays(
            guild_id,
            days,
            reference_time=reference_time,
        )

        if not upcoming:
            return "🎂 **Kommende bursdager**\n\nIngen bursdager de neste 30 dagene."

        lines = ["🎂 **Kommende bursdager**", ""]

        months = [
            "",
            "januar",
            "februar",
            "mars",
            "april",
            "mai",
            "juni",
            "juli",
            "august",
            "september",
            "oktober",
            "november",
            "desember",
        ]

        for b in upcoming[:10]:
            date_str = f"{b['day']}. {months[b['month']]}"

            if b["days_until"] == 0:
                when = "I dag! 🎉"
            elif b["days_until"] == 1:
                when = "I morgen"
            else:
                when = f"Om {b['days_until']} dager"

            age_str = f" (blir {b['turning']})" if b["turning"] else ""

            lines.append(f"• **{b['username']}**{age_str} - {date_str} ({when})")

        return "\n".join(lines)

    def format_birthday_list(self, guild_id):
        """Format all registered birthdays"""
        guild_key = str(guild_id)

        if guild_key not in self.birthdays or not self.birthdays[guild_key]:
            return "🎂 **Bursdager**\n\nIngen bursdager registrert.\n\nBruk: `@inebotten bursdag DD.MM [år]`"

        months = [
            "",
            "januar",
            "februar",
            "mars",
            "april",
            "mai",
            "juni",
            "juli",
            "august",
            "september",
            "oktober",
            "november",
            "desember",
        ]

        lines = ["🎂 **Registrerte bursdager**", ""]

        # Sort by month/day
        sorted_birthdays = sorted(
            self.birthdays[guild_key].items(),
            key=lambda x: (x[1]["month"], x[1]["day"]),
        )

        for user_id, data in sorted_birthdays:
            date_str = f"{data['day']}. {months[data['month']]}"
            year_str = f" ({data['year']})" if data.get("year") else ""
            lines.append(f"• **{data['username']}**{year_str} - {date_str}")

        return "\n".join(lines)

    def format_birthday_for_user(self, guild_id, user_id):
        """Format one caller-owned birthday without exposing another user."""

        record = self.birthdays.get(str(guild_id), {}).get(str(user_id))
        if not isinstance(record, dict):
            return (
                "🎂 Bursdagen din er ikke registrert ennå. "
                "Du kan lagre den med for eksempel `bursdagen min er 15.05`."
            )
        months = (
            "",
            "januar",
            "februar",
            "mars",
            "april",
            "mai",
            "juni",
            "juli",
            "august",
            "september",
            "oktober",
            "november",
            "desember",
        )
        try:
            day = int(record["day"])
            month = int(record["month"])
            validate_birthday_date(day, month, record.get("year"))
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid_stored_birthday") from None
        date_text = f"{day}. {months[month]}"
        if record.get("year") is not None:
            date_text += f" {int(record['year'])}"
        return f"🎂 Bursdagen din er **{date_text}**."


class BirthdayCommand(TypedDict, total=False):
    action: Required[Literal["add", "edit", "list", "clarify"]]
    user_id: int
    display_name: str
    day: int
    month: int
    year: int
    scope: Literal["all", "upcoming", "self"]
    reason: str


_BIRTHDAY_BOT_INVOCATION = re.compile(
    r"^\s*@inebotten\b\s*[,;:]?\s*", re.I
)
_BIRTHDAY_MONTHS = {
    "januar": 1,
    "january": 1,
    "jan": 1,
    "februar": 2,
    "february": 2,
    "feb": 2,
    "mars": 3,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juni": 6,
    "june": 6,
    "jun": 6,
    "juli": 7,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "oktober": 10,
    "october": 10,
    "okt": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "desember": 12,
    "december": 12,
    "des": 12,
    "dec": 12,
}
_BIRTHDAY_MONTH_NAME = "|".join(
    sorted(map(re.escape, _BIRTHDAY_MONTHS), key=len, reverse=True)
)
_BIRTHDAY_NUMERIC_DATE_PATTERN = (
    r"\d{1,2}[.]\d{1,2}(?:[.](?:\d{2}|\d{4}))?"
)
_BIRTHDAY_DAY_FIRST_PATTERN = (
    rf"\d{{1,2}}(?:[.]\s*|\s+)(?:{_BIRTHDAY_MONTH_NAME})[.]?"
    r"(?:\s*,?\s*(?:\d{2}|\d{4}))?"
)
_BIRTHDAY_MONTH_FIRST_PATTERN = (
    rf"(?:{_BIRTHDAY_MONTH_NAME})[.]?\s+\d{{1,2}}"
    r"(?:\s*,?\s*(?:\d{2}|\d{4}))?"
)
_BIRTHDAY_DATE_PATTERN = (
    rf"(?:{_BIRTHDAY_NUMERIC_DATE_PATTERN}|"
    rf"{_BIRTHDAY_DAY_FIRST_PATTERN}|{_BIRTHDAY_MONTH_FIRST_PATTERN})"
)
_BIRTHDAY_NUMERIC_DATE = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})[.](?P<month>\d{1,2})"
    r"(?:[.](?P<year>\d{2}|\d{4}))?(?!\d)"
)
_BIRTHDAY_DAY_FIRST_DATE = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})(?:[.]\s*|\s+)"
    rf"(?P<month_name>{_BIRTHDAY_MONTH_NAME})[.]?"
    r"(?:\s*,?\s*(?P<year>\d{2}|\d{4}))?(?!\w)",
    re.I,
)
_BIRTHDAY_MONTH_FIRST_DATE = re.compile(
    rf"(?<!\w)(?P<month_name>{_BIRTHDAY_MONTH_NAME})[.]?\s+"
    r"(?P<day>\d{1,2})(?:\s*,?\s*(?P<year>\d{2}|\d{4}))?(?!\d)",
    re.I,
)
_BIRTHDAY_EDIT = r"endre|rediger|oppdater|edit|update|change"
_BIRTHDAY_ADD = (
    r"legg\s+til|legge\s+til|legg\s+inn|legge\s+inn|"
    r"lagre|add|save|register"
)
_BIRTHDAY_POLITE = (
    r"(?:(?:(?:kan|kunne)\s+du|(?:could|would)\s+you|please)\s+)?"
)
_BIRTHDAY_DOMAIN = re.compile(
    r"\b(?:bursdag(?:en|er|ene|ar|ane)?|birthday(?:s)?)\b", re.I
)
_BIRTHDAY_UPCOMING_LIST = re.compile(
    r"^(?:(?:hvem|kven)\s+har\s+bursdag|who\s+has\s+(?:a\s+)?birthday)"
    r"\s+(?:snart|kommende|komande|soon|upcoming|coming\s+up)\s*\??$|"
    rf"^{_BIRTHDAY_POLITE}(?:vis|vise|list|show)\s+"
    r"(?:(?:meg|mæ|me)\s+)?(?:kommende|komande|upcoming)\s+"
    r"(?:bursdager|bursdagar|birthdays)\s*\??$",
    re.I,
)
_BIRTHDAY_ALL_LIST = re.compile(
    r"^(?:(?:vis|list|show)\s+)?(?:alle\s+|all\s+)?"
    r"(?:bursdager|bursdagar|birthdays)\s*\??$|"
    r"^(?:(?:hvem|kven)\s+har\s+bursdag|who\s+has\s+(?:a\s+)?birthday)"
    r"\s*\??$",
    re.I,
)
_BIRTHDAY_SELF_LIST = re.compile(
    r"^(?:(?:når|kva\s+tid|hva\s+tid)\s+er\s+bursdagen\s+min|"
    r"når\s+har\s+(?:jeg|eg|æ)\s+bursdag|"
    r"(?:when|what)(?:\s+is|['’]s)\s+my\s+birthday)\s*\??$",
    re.I,
)


def validate_birthday_date(
    day: int,
    month: int,
    year: int | None = None,
) -> None:
    """Raise ValueError for an impossible or unsupported birthday date."""

    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (day, month)
    ):
        raise ValueError("invalid_birthday_date")
    if year is not None and (
        isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100
    ):
        raise ValueError("invalid_birthday_date")
    try:
        date(year or 2000, month, day)
    except (OverflowError, ValueError):
        raise ValueError("invalid_birthday_date") from None


def _birthday_date_fields(match: re.Match[str]) -> dict[str, int]:
    day = int(match.group("day"))
    raw_month = match.groupdict().get("month")
    month_name = match.groupdict().get("month_name")
    month = (
        int(raw_month)
        if raw_month is not None
        else _BIRTHDAY_MONTHS[month_name.casefold()]
    )
    raw_year = match.group("year")
    year = int(raw_year) if raw_year is not None else None
    if year is not None and year < 100:
        year += 1900 if year >= 50 else 2000
    validate_birthday_date(day, month, year)
    fields = {"day": day, "month": month}
    if year is not None:
        fields["year"] = year
    return fields


def _birthday_date_matches(content: str) -> tuple[re.Match[str], ...]:
    matches = [
        *list(_BIRTHDAY_NUMERIC_DATE.finditer(content)),
        *list(_BIRTHDAY_DAY_FIRST_DATE.finditer(content)),
        *list(_BIRTHDAY_MONTH_FIRST_DATE.finditer(content)),
    ]
    matches.sort(
        key=lambda value: (
            value.start(),
            -(value.end() - value.start()),
        )
    )
    accepted: list[re.Match[str]] = []
    for match in matches:
        if any(
            match.start() < existing.end()
            and existing.start() < match.end()
            for existing in accepted
        ):
            continue
        accepted.append(match)
    return tuple(accepted)


def parse_birthday_command(
    message_content: str,
    *,
    routing_context: RoutingContext | None = None,
) -> BirthdayCommand | None:
    """Parse one birthday operation without guessing a user's identity."""

    if not isinstance(message_content, str):
        return None
    content = _BIRTHDAY_BOT_INVOCATION.sub("", message_content, count=1).strip()
    if _BIRTHDAY_SELF_LIST.fullmatch(content):
        return {"action": "list", "scope": "self"}
    if _BIRTHDAY_UPCOMING_LIST.fullmatch(content):
        return {"action": "list", "scope": "upcoming"}
    if _BIRTHDAY_ALL_LIST.fullmatch(content):
        return {"action": "list", "scope": "all"}
    if _BIRTHDAY_DOMAIN.search(content) is None:
        return None

    date_pattern = _BIRTHDAY_DATE_PATTERN
    direct_edit = re.match(
        rf"^{_BIRTHDAY_POLITE}(?:{_BIRTHDAY_EDIT})\s+"
        r"(?:bursdag(?:en)?|birthday)\b",
        content,
        re.I,
    )
    direct_add = re.match(
        rf"^{_BIRTHDAY_POLITE}(?:{_BIRTHDAY_ADD})\s+"
        r"(?:bursdagen\s+min|min\s+bursdag|my\s+birthday)\b",
        content,
        re.I,
    )
    direct_named_add = re.match(
        rf"^{_BIRTHDAY_POLITE}(?:{_BIRTHDAY_ADD})\s+"
        r"(?:(?:en|ein|a)\s+)?(?:bursdag|birthday)\b",
        content,
        re.I,
    )
    direct_frame = bool(
        direct_edit
        or direct_add
        or direct_named_add
        or re.match(
            r"^(?:bursdag(?:en)?|birthday)\b", content, re.I
        )
        or re.match(
            r"^(?:min\s+bursdag|(?:jeg|eg)\s+har\s+bursdag|"
            r"my\s+birthday)\b",
            content,
            re.I,
        )
        or re.fullmatch(
            rf"^.+?\s+(?:har\s+bursdag|has\s+(?:a\s+)?birthday)"
            rf"\s*[:=]?\s*{date_pattern}\s*[.!?]?$",
            content,
            re.I,
        )
        or re.fullmatch(
            rf"^(?:bursdagen\s+til\s+.+?\s+er|"
            rf"my\s+.+?\s+birthday\s+is)\s*[:=]?\s*"
            rf"{date_pattern}\s*[.!?]?$",
            content,
            re.I,
        )
    )
    if not direct_frame:
        return None

    matches = _birthday_date_matches(content)
    if len(matches) != 1:
        return {"action": "clarify", "reason": "unresolved_target"}
    try:
        date_fields = _birthday_date_fields(matches[0])
    except ValueError:
        return {"action": "clarify", "reason": "unresolved_target"}

    mention_tokens = tuple(re.findall(r"<@!?(\d+)>", content))
    is_edit = direct_edit is not None
    if mention_tokens:
        mention_frame = re.fullmatch(
            rf"^(?:{_BIRTHDAY_POLITE}(?:{_BIRTHDAY_EDIT})\s+)?"
            rf"(?:bursdag(?:en)?|birthday)\s+<@!?\d+>"
            rf"\s*[:=]?\s*{date_pattern}\s*[.!?]?$|"
            rf"^<@!?\d+>\s+(?:har\s+bursdag|has\s+(?:a\s+)?birthday)"
            rf"\s*[:=]?\s*{date_pattern}\s*[.!?]?$|"
            rf"^(?:bursdagen\s+til\s+<@!?\d+>\s+er|"
            rf"<@!?\d+>'s\s+birthday\s+is)\s*[:=]?\s*"
            rf"{date_pattern}\s*[.!?]?$",
            content,
            re.I,
        )
        if (
            mention_frame is None
            or len(mention_tokens) != 1
            or routing_context is None
        ):
            return {"action": "clarify", "reason": "unresolved_target"}
        mentioned_id = int(mention_tokens[0])
        resolved = [
            mention
            for mention in routing_context.mentions
            if mention.user_id == mentioned_id
        ]
        if len(resolved) != 1:
            return {"action": "clarify", "reason": "unresolved_target"}
        action: Literal["add", "edit"] = "edit" if is_edit else "add"
        result: BirthdayCommand = {
            "action": action,
            "user_id": mentioned_id,
            **date_fields,
        }
        if action == "add":
            result["display_name"] = resolved[0].display_name
        return result

    optional_edit = (
        rf"(?:{_BIRTHDAY_POLITE}(?:(?P<edit>{_BIRTHDAY_EDIT})|"
        rf"(?:{_BIRTHDAY_ADD}))\s+)?"
    )
    self_patterns = (
        re.compile(
            rf"^{optional_edit}(?:bursdagen\s+min|min\s+bursdag|bursdag(?:en)?)"
            rf"(?:\s+(?:er|til))?\s*[:=]?\s*{date_pattern}\s*[.!?]?$",
            re.I,
        ),
        re.compile(
            rf"^{optional_edit}(?:jeg|eg)\s+har\s+bursdag"
            rf"\s*[:=]?\s*{date_pattern}\s*[.!?]?$",
            re.I,
        ),
        re.compile(
            rf"^{optional_edit}my\s+birthday(?:\s+(?:is|to))?"
            rf"\s*[:=]?\s*{date_pattern}\s*[.!?]?$",
            re.I,
        ),
    )
    self_match = None
    for pattern in self_patterns:
        self_match = pattern.fullmatch(content)
        if self_match is not None:
            break
    if self_match is None or routing_context is None:
        return {"action": "clarify", "reason": "unresolved_target"}
    action = "edit" if self_match.group("edit") else "add"
    result: BirthdayCommand = {
        "action": action,
        "user_id": routing_context.author.user_id,
        **date_fields,
    }
    if action == "add":
        result["display_name"] = routing_context.author.display_name
    return result


if __name__ == "__main__":
    # Test
    print("=== Birthday Manager Test ===\n")

    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as tmp:
        storage_path = tmp.name
    manager = BirthdayManager(storage_path=storage_path)

    # Add test birthdays
    manager.add_birthday("guild1", "user1", "Ola Nordmann", 17, 3, 1990)
    manager.add_birthday("guild1", "user2", "Kari Nordmann", 20, 3)

    # Test today's birthdays (silent unless needed)
    today_bdays = manager.get_todays_birthdays("guild1")
    if today_bdays:
        print(f"Found {len(today_bdays)} birthdays today.")

    # Cleanup
    manager.storage_path.unlink(missing_ok=True)
