#!/usr/bin/env python3
"""
Calendar Reminder Checker for Inebotten

Background asyncio task that:
1. Checks every minute for events/reminders coming up in 30 minutes
   and pings the event creator in the original channel
2. Sends one due alert across the bounded now/catch-up window
3. Sends a morning digest at 09:00 Europe/Oslo with today's events

Tracks sent reminders in a JSON file to avoid duplicate pings.
"""

import json
import asyncio
import copy
import math
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

from cal_system.reminder_clock import OSLO, ReminderClock, SystemReminderClock
from core.dispatch_result import DeliveryState, MessageSendResult
from core.mutation_coordinator import (
    CALENDAR_SHARED_SCOPE,
    REMINDER_SENT_LOG_SCOPE,
    REMINDER_STORE_SCOPE,
    MutationCoordinator,
)
from core.nlu_metrics import NLUMetrics
from utils.json_storage import hermes_discord_data_path, write_json_atomic


SleepFunction = Callable[[float], Awaitable[None]]
ALERT_SEND_TIMEOUT_SECONDS = 15.0
IN_FLIGHT = "in_flight"
SENT = "sent"
SUPPRESSED_UNKNOWN = "suppressed_unknown"
_TERMINAL_OCCURRENCE_STATES = frozenset({SENT, SUPPRESSED_UNKNOWN})
_CANONICAL_OCCURRENCE_KEY = re.compile(
    r"^(calendar|reminder):([^:]+):(.+):(warning_30m|due)$"
)
_OLD_CALENDAR_SENT_KEY = re.compile(r"^([^:]+):(30min|now|passed)$")
_SENT_RECORD_RETENTION_SECONDS = 2 * 24 * 60 * 60
_DIGEST_RECORD_RETENTION_SECONDS = 30 * 24 * 60 * 60
_BOUNDED_ERROR_CODES = frozenset(
    {"cycle_error", "delivery_failure", "gcal_sync_error", "storage_error"}
)
_STAT_KEYS = (
    "cycles",
    "warning_30m_sent",
    "due_sent",
    "digest_sent",
    "delivery_failures",
    "skipped_missing_channel",
    "malformed_legacy_due_at",
    "legacy_due_mismatch",
    "missed_outside_catchup",
    "gcal_sync_errors",
    "cycle_errors",
)
_REMINDER_METRIC_ERROR_CODES = {
    "missing_channel": "channel_missing",
    "invalid_channel": "channel_missing",
    "missing_adapter": "channel_missing",
    "forbidden": "send_forbidden",
    "http": "send_http",
    "empty": "manager_error",
    "daily_quota": "manager_error",
    "timeout": "manager_error",
    "transport": "manager_error",
    "send_task_cancelled": "manager_error",
    "send_task_exception": "manager_error",
    "partial_send": "manager_error",
}


def reminder_metric_error_code(error_code: str | None) -> str:
    """Project one shared send code onto the finite reminder registry."""
    return _REMINDER_METRIC_ERROR_CODES.get(error_code, "manager_error")


def select_alert_kind(delta: timedelta) -> str | None:
    """Select the one alert window containing an occurrence delta."""
    if timedelta(minutes=25) < delta <= timedelta(minutes=35):
        return "warning_30m"
    if -timedelta(minutes=10) <= delta <= timedelta(minutes=1):
        return "due"
    return None


class ReminderChecker:
    """
    Proactive calendar reminder checker that pings users in Discord
    when canonical calendar or reminder occurrences approach or become due.
    Also sends a morning digest.
    """

    def __init__(
        self,
        calendar_manager=None,
        reminder_manager=None,
        event_manager=None,
        get_channel_func=None,
        send_channel_message_func=None,
        send_ping_message_func=None,
        storage_path=None,
        *,
        clock: ReminderClock | None = None,
        mutation_coordinator: MutationCoordinator | None = None,
        sleep_func: SleepFunction = asyncio.sleep,
        interval_seconds: float = 60.0,
        metrics: NLUMetrics | None = None,
    ):
        self.calendar = calendar_manager
        self.reminders = reminder_manager
        self.events = event_manager
        self.get_channel = get_channel_func
        self.send_channel_message = send_channel_message_func
        self.send_ping_message = send_ping_message_func
        self.clock = clock or SystemReminderClock()
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()
        self.sleep_func = sleep_func
        self.interval_seconds = interval_seconds
        self.metrics = metrics if isinstance(metrics, NLUMetrics) else NLUMetrics()
        self.running = False
        self._last_gcal_sync: float | None = None
        self._last_gcal_probe_error: float | None = None

        self._health_status = "starting"
        self._health_stale = False
        self._started_at = None
        self._last_check_at = None
        self._last_success_at = None
        self._last_error_at = None
        self._last_error_code = None
        self._consecutive_errors = 0
        self._occurrence_states: dict[str, str] = {}
        self._digest_states: dict[str, str] = {}
        self._owned_send_tasks: set[asyncio.Task] = set()
        self._sent_log_normalized = False
        self._sent_log_dirty = False

        self.stats = {key: 0 for key in _STAT_KEYS}

        if storage_path is None:
            storage_path = hermes_discord_data_path("reminder_log.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.sent_log = {"reminders_sent": {}, "digest_log": {}}

    def _capture_reference_time(self) -> datetime:
        """Read one aware clock value and normalize it to Europe/Oslo."""
        reference_time = self.clock.now()
        if (
            not isinstance(reference_time, datetime)
            or reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time_must_be_aware")
        return reference_time.astimezone(OSLO)

    @staticmethod
    def _bounded_health_timestamp(value) -> str | None:
        if type(value) is not str:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if (
            parsed.tzinfo is None
            or parsed.utcoffset() is None
            or parsed.isoformat() != value
        ):
            return None
        return value

    def get_health(self) -> dict[str, object]:
        """Return the bounded, live internal runtime-health projection."""
        running = self.running is True
        stale = False
        if running:
            try:
                reference_time = self._capture_reference_time()
                baseline_raw = self._last_success_at or self._started_at
                baseline = self._bounded_health_timestamp(baseline_raw)
                if baseline_raw is not None and baseline is None:
                    raise ValueError("invalid_health_baseline")
                if baseline is not None:
                    baseline_time = datetime.fromisoformat(baseline)
                    elapsed = (
                        reference_time.astimezone(timezone.utc)
                        - baseline_time.astimezone(timezone.utc)
                    ).total_seconds()
                    interval = float(self.interval_seconds)
                    if not math.isfinite(interval) or interval < 0:
                        raise ValueError("invalid_health_interval")
                    threshold = max(150.0, interval * 2.5)
                    stale = elapsed > threshold
            except Exception:
                stale = True
        self._health_stale = stale
        status = "degraded" if stale else self._health_status
        if type(status) is not str or status not in {
            "starting",
            "ok",
            "degraded",
            "stopped",
        }:
            status = "degraded"
        error_code = self._last_error_code
        if error_code is not None and (
            type(error_code) is not str
            or error_code not in _BOUNDED_ERROR_CODES
        ):
            error_code = "cycle_error"
        consecutive_errors = self._consecutive_errors
        if type(consecutive_errors) is not int or consecutive_errors < 0:
            consecutive_errors = 0
        stats = {}
        for key in _STAT_KEYS:
            value = self.stats.get(key)
            stats[key] = value if type(value) is int and value >= 0 else 0
        return {
            "status": status,
            "running": running,
            "stale": stale,
            "last_check_at": self._bounded_health_timestamp(
                self._last_check_at
            ),
            "last_success_at": self._bounded_health_timestamp(
                self._last_success_at
            ),
            "last_error_at": self._bounded_health_timestamp(
                self._last_error_at
            ),
            "last_error_code": error_code,
            "consecutive_errors": consecutive_errors,
            "stats": stats,
        }

    @staticmethod
    def _require_aware_reference(reference_time: datetime) -> datetime:
        if (
            not isinstance(reference_time, datetime)
            or reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time_must_be_aware")
        return reference_time

    @staticmethod
    def _occurrence_key(item, alert_kind: str) -> str:
        source_kind = item.get("source_kind")
        item_id = item.get("id")
        due_at = item.get("due_at")
        if source_kind not in {"calendar", "reminder"}:
            raise ValueError("invalid_occurrence_source")
        if (
            not isinstance(item_id, str)
            or not item_id
            or item_id != item_id.strip()
            or ":" in item_id
        ):
            raise ValueError("invalid_occurrence_id")
        if (
            not isinstance(due_at, datetime)
            or due_at.tzinfo is None
            or due_at.utcoffset() is None
        ):
            raise ValueError("occurrence_due_at_must_be_aware")
        if due_at.microsecond:
            raise ValueError("occurrence_due_at_must_be_canonical")
        if alert_kind not in {"warning_30m", "due"}:
            raise ValueError("invalid_alert_kind")
        return f"{source_kind}:{item_id}:{due_at.isoformat()}:{alert_kind}"

    @staticmethod
    def _occurrence_fingerprint(item) -> tuple[object, ...]:
        source_kind = item.get("source_kind")
        if source_kind == "calendar":
            return (
                item.get("id"),
                item.get("due_at"),
                item.get("status"),
                item.get("delete_pending"),
            )
        if source_kind == "reminder":
            return (
                item.get("id"),
                item.get("due_at"),
                item.get("recurrence_anchor_local"),
                item.get("recurrence_sequence"),
                item.get("completed"),
            )
        raise ValueError("invalid_occurrence_source")

    @staticmethod
    def _normalized_epoch(value) -> float | None:
        if type(value) not in {int, float}:
            return None
        try:
            normalized = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        if not math.isfinite(normalized) or normalized < 0:
            return None
        return normalized

    @staticmethod
    def _parse_canonical_occurrence_key(key) -> tuple[str, str, datetime, str] | None:
        if type(key) is not str:
            return None
        match = _CANONICAL_OCCURRENCE_KEY.fullmatch(key)
        if match is None:
            return None
        source_kind, item_id, due_text, alert_kind = match.groups()
        if not item_id or item_id != item_id.strip():
            return None
        try:
            due_at = datetime.fromisoformat(due_text)
        except (TypeError, ValueError):
            return None
        if (
            due_at.tzinfo is None
            or due_at.utcoffset() is None
            or due_at.microsecond
            or due_text != due_at.isoformat()
        ):
            return None
        return source_kind, item_id, due_at, alert_kind

    @classmethod
    def _normalized_terminal_record(cls, record) -> dict[str, object] | None:
        if type(record) is not dict or set(record) != {"state", "at"}:
            return None
        state = record.get("state")
        if type(state) is not str or state not in _TERMINAL_OCCURRENCE_STATES:
            return None
        at = cls._normalized_epoch(record.get("at"))
        if at is None:
            return None
        return {"state": state, "at": at}

    @classmethod
    def _valid_terminal_record(cls, record) -> str | None:
        normalized = cls._normalized_terminal_record(record)
        return None if normalized is None else normalized["state"]

    @staticmethod
    def _parse_digest_date(key) -> datetime | None:
        """Parse one exact persisted Oslo digest-date key."""
        if type(key) is not str:
            return None
        try:
            parsed = datetime.strptime(key, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None
        if parsed.strftime("%Y-%m-%d") != key:
            return None
        return parsed

    @classmethod
    def _is_canonical_snowflake_text(cls, value) -> bool:
        if type(value) is not str:
            return False
        normalized = cls._normalize_snowflake(value)
        return normalized is not None and value == str(normalized)

    @classmethod
    def _parse_legacy_digest_key(cls, key) -> tuple[str, str] | None:
        """Accept only the one-release guild/channel digest key shape."""
        if type(key) is not str or key.count(":") != 1:
            return None
        scope_id, channel_id = key.split(":", 1)
        if scope_id != "shared" and not cls._is_canonical_snowflake_text(
            scope_id
        ):
            return None
        if not cls._is_canonical_snowflake_text(channel_id):
            return None
        return scope_id, channel_id

    @classmethod
    def _normalize_digest_log_in_memory(cls, raw_records) -> dict[str, dict]:
        """Normalize digest records without pruning or touching storage."""
        if type(raw_records) is not dict:
            return {}

        normalized: dict[str, dict[str, object]] = {}
        for key, value in raw_records.items():
            if cls._parse_digest_date(key) is None:
                continue
            if type(value) in {int, float}:
                at = cls._normalized_epoch(value)
                record = None if at is None else {"state": SENT, "at": at}
            else:
                record = cls._normalized_terminal_record(value)
            if record is not None:
                normalized[key] = record

        for key, value in raw_records.items():
            if cls._parse_legacy_digest_key(key) is None:
                continue
            parsed_date = cls._parse_digest_date(value)
            if parsed_date is None:
                continue
            canonical_key = parsed_date.strftime("%Y-%m-%d")
            if canonical_key in normalized:
                continue
            try:
                at = parsed_date.replace(
                    hour=9,
                    minute=0,
                    second=0,
                    microsecond=0,
                    tzinfo=OSLO,
                ).timestamp()
            except (OSError, OverflowError, ValueError):
                continue
            at = cls._normalized_epoch(at)
            if at is None:
                continue
            normalized[canonical_key] = {"state": SENT, "at": at}
        return normalized

    @staticmethod
    def _bounded_sent_log_root(raw) -> dict[str, dict]:
        if (
            type(raw) is not dict
            or set(raw) != {"reminders_sent", "digest_log"}
            or type(raw.get("reminders_sent")) is not dict
            or type(raw.get("digest_log")) is not dict
        ):
            return {"reminders_sent": {}, "digest_log": {}}
        return {
            "reminders_sent": copy.deepcopy(raw["reminders_sent"]),
            "digest_log": copy.deepcopy(raw["digest_log"]),
        }

    @classmethod
    def _calendar_occurrences_by_id(cls, calendar_occurrences):
        rows_by_id: dict[str, list[dict]] = {}
        for row in calendar_occurrences:
            if type(row) is not dict or row.get("source_kind") != "calendar":
                continue
            item_id = row.get("id")
            due_at = row.get("due_at")
            if (
                not isinstance(item_id, str)
                or not item_id
                or item_id != item_id.strip()
                or ":" in item_id
                or not isinstance(due_at, datetime)
                or due_at.tzinfo is None
                or due_at.utcoffset() is None
                or due_at.microsecond
            ):
                continue
            rows_by_id.setdefault(item_id, []).append(row)
        return rows_by_id

    def _normalize_sent_log_in_memory(
        self,
        *,
        reference_time: datetime,
        calendar_occurrences,
    ) -> None:
        cutoff = reference_time.timestamp() - _SENT_RECORD_RETENTION_SECONDS
        root = self._bounded_sent_log_root(self.sent_log)
        raw_records = root["reminders_sent"]
        normalized: dict[str, dict[str, object]] = {}
        old_candidates: dict[str, float] = {}
        rows_by_id = self._calendar_occurrences_by_id(calendar_occurrences)

        for key, value in raw_records.items():
            if self._parse_canonical_occurrence_key(key) is not None:
                if type(value) in {int, float}:
                    at = self._normalized_epoch(value)
                    record = (
                        None
                        if at is None
                        else {"state": SENT, "at": at}
                    )
                else:
                    record = self._normalized_terminal_record(value)
                if record is not None and record["at"] > cutoff:
                    normalized[key] = record
                continue

            old_match = (
                _OLD_CALENDAR_SENT_KEY.fullmatch(key)
                if type(key) is str
                else None
            )
            if old_match is None:
                continue
            item_id, old_kind = old_match.groups()
            at = self._normalized_epoch(value)
            if at is not None and at <= cutoff:
                continue
            matches = rows_by_id.get(item_id, [])
            if at is None or len(matches) != 1:
                self.stats["malformed_legacy_due_at"] += 1
                continue
            alert_kind = (
                "warning_30m" if old_kind == "30min" else "due"
            )
            try:
                canonical_key = self._occurrence_key(matches[0], alert_kind)
            except (TypeError, ValueError):
                self.stats["malformed_legacy_due_at"] += 1
                continue
            previous = old_candidates.get(canonical_key)
            if previous is None or at > previous:
                old_candidates[canonical_key] = at

        for key, at in old_candidates.items():
            existing = normalized.get(key)
            if existing is None or at > existing["at"]:
                normalized[key] = {"state": SENT, "at": at}

        self.sent_log = {
            "reminders_sent": normalized,
            "digest_log": self._normalize_digest_log_in_memory(
                root["digest_log"]
            ),
        }
        self._discard_unpersisted_terminal_states()

    async def _normalize_sent_log_once(
        self,
        *,
        reference_time: datetime,
        calendar_occurrences,
        refresh_alert_retention: bool = True,
    ) -> None:
        self._require_aware_reference(reference_time)
        async with self.mutation_coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            if self._sent_log_normalized:
                if refresh_alert_retention:
                    self._prune_sent_records(reference_time=reference_time)
                return
            self._normalize_sent_log_in_memory(
                reference_time=reference_time,
                calendar_occurrences=calendar_occurrences,
            )
            self._sent_log_normalized = True

    def _discard_unpersisted_terminal_states(self) -> None:
        records = self.sent_log.get("reminders_sent")
        retained_keys = set(records) if type(records) is dict else set()
        for key, state in tuple(self._occurrence_states.items()):
            if state in _TERMINAL_OCCURRENCE_STATES and key not in retained_keys:
                self._occurrence_states.pop(key, None)

        digest_records = self.sent_log.get("digest_log")
        retained_digest_keys = (
            set(digest_records) if type(digest_records) is dict else set()
        )
        for key, state in tuple(self._digest_states.items()):
            if (
                state in _TERMINAL_OCCURRENCE_STATES
                and key not in retained_digest_keys
            ):
                self._digest_states.pop(key, None)

    def _prune_sent_records(self, *, reference_time: datetime) -> None:
        self._require_aware_reference(reference_time)
        cutoff = reference_time.timestamp() - _SENT_RECORD_RETENTION_SECONDS
        records = self.sent_log.get("reminders_sent")
        retained: dict[str, dict[str, object]] = {}
        if type(records) is dict:
            for key, record in records.items():
                if self._parse_canonical_occurrence_key(key) is None:
                    continue
                normalized = self._normalized_terminal_record(record)
                if normalized is None or normalized["at"] <= cutoff:
                    continue
                retained[key] = normalized
        self.sent_log["reminders_sent"] = retained
        self._discard_unpersisted_terminal_states()

    def _prune_digest_records(self, *, reference_time: datetime) -> None:
        self._require_aware_reference(reference_time)
        cutoff = (
            reference_time.timestamp() - _DIGEST_RECORD_RETENTION_SECONDS
        )
        records = self.sent_log.get("digest_log")
        retained: dict[str, dict[str, object]] = {}
        if type(records) is dict:
            for key, record in records.items():
                if self._parse_digest_date(key) is None:
                    continue
                normalized = self._normalized_terminal_record(record)
                if normalized is None or normalized["at"] <= cutoff:
                    continue
                retained[key] = normalized
        self.sent_log["digest_log"] = retained
        self._discard_unpersisted_terminal_states()

    def _prune_terminal_records(self, *, reference_time: datetime) -> None:
        self._prune_sent_records(reference_time=reference_time)
        self._prune_digest_records(reference_time=reference_time)

    def _persisted_terminal_state(
        self,
        occurrence_key: str,
        *,
        reference_time: datetime,
    ) -> str | None:
        if type(self.sent_log) is not dict:
            return None
        records = self.sent_log.get("reminders_sent")
        if type(records) is not dict:
            return None
        record = self._normalized_terminal_record(
            records.get(occurrence_key)
        )
        cutoff = reference_time.timestamp() - _SENT_RECORD_RETENTION_SECONDS
        if record is None or record["at"] <= cutoff:
            return None
        return record["state"]

    def _persisted_digest_state(
        self,
        digest_key: str,
        *,
        reference_time: datetime,
    ) -> str | None:
        records = self.sent_log.get("digest_log")
        if type(records) is not dict:
            return None
        record = self._normalized_terminal_record(records.get(digest_key))
        cutoff = (
            reference_time.timestamp() - _DIGEST_RECORD_RETENTION_SECONDS
        )
        if record is None or record["at"] <= cutoff:
            return None
        return record["state"]

    async def _claim_digest(
        self,
        digest_key: str,
        *,
        reference_time: datetime,
    ) -> bool:
        published = False
        try:
            async with self.mutation_coordinator.hold(
                REMINDER_SENT_LOG_SCOPE
            ):
                state = self._digest_states.get(digest_key)
                if state == IN_FLIGHT:
                    return False
                persisted = self._persisted_digest_state(
                    digest_key,
                    reference_time=reference_time,
                )
                if state in _TERMINAL_OCCURRENCE_STATES:
                    if persisted is not None:
                        return False
                    self._digest_states.pop(digest_key, None)
                if persisted is not None:
                    self._digest_states[digest_key] = persisted
                    return False
                self._digest_states[digest_key] = IN_FLIGHT
                published = True
                return True
        except asyncio.CancelledError:
            if published:
                cleanup = asyncio.create_task(
                    self._release_digest_in_flight(digest_key)
                )
                await self._await_owned_task(cleanup)
            raise

    async def _release_digest_in_flight(self, digest_key: str) -> None:
        async with self.mutation_coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            if self._digest_states.get(digest_key) == IN_FLIGHT:
                self._digest_states.pop(digest_key, None)

    async def _claim_occurrence(
        self,
        manager,
        family_scope,
        fingerprint,
        occurrence_key: str,
        *,
        reference_time: datetime,
    ) -> bool:
        published = False
        try:
            async with self.mutation_coordinator.hold(family_scope):
                if not manager.matches_delivery_fingerprint(
                    fingerprint,
                    reference_time=reference_time,
                ):
                    return False
                async with self.mutation_coordinator.hold(
                    REMINDER_SENT_LOG_SCOPE
                ):
                    state = self._occurrence_states.get(occurrence_key)
                    if state == IN_FLIGHT:
                        return False
                    persisted = self._persisted_terminal_state(
                        occurrence_key,
                        reference_time=reference_time,
                    )
                    if state in _TERMINAL_OCCURRENCE_STATES:
                        if persisted is not None:
                            self.metrics.record_reminder_delivery("deduplicated")
                            return False
                        self._occurrence_states.pop(occurrence_key, None)
                    if persisted is not None:
                        self._occurrence_states[occurrence_key] = persisted
                        self.metrics.record_reminder_delivery("deduplicated")
                        return False
                    self._occurrence_states[occurrence_key] = IN_FLIGHT
                    published = True
                    return True
        except asyncio.CancelledError:
            if published:
                cleanup = asyncio.create_task(
                    self._release_in_flight(occurrence_key)
                )
                await self._await_owned_task(cleanup)
            raise

    async def _release_in_flight(self, occurrence_key: str) -> None:
        async with self.mutation_coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            if self._occurrence_states.get(occurrence_key) == IN_FLIGHT:
                self._occurrence_states.pop(occurrence_key, None)

    async def _persist_new_schema_log(self) -> None:
        snapshot = copy.deepcopy(self.sent_log)
        await asyncio.to_thread(
            write_json_atomic,
            self.storage_path,
            snapshot,
        )

    def _mark_sent_log_persisted(self) -> None:
        """Clear the sticky durability failure after a complete atomic write."""
        self._sent_log_dirty = False
        if self._last_error_code == "storage_error":
            self._last_error_code = None

    async def _persist_dirty_sent_log_locked(
        self,
        *,
        reference_time: datetime,
    ) -> bool:
        """Persist the current snapshot without releasing its lock early.

        ``asyncio.to_thread`` workers continue after their awaiting coroutine
        is cancelled.  Keep the write owned and the mutation scope held until
        that worker settles so an older snapshot can never finish after a
        newer acknowledgement.
        """
        self.mutation_coordinator.assert_held(REMINDER_SENT_LOG_SCOPE)
        persistence = asyncio.create_task(self._persist_new_schema_log())
        try:
            await asyncio.shield(persistence)
        except asyncio.CancelledError:
            await self._await_owned_task(persistence)
            if not persistence.cancelled():
                try:
                    persistence.result()
                except Exception:
                    self._record_bounded_error(
                        "storage_error",
                        reference_time=reference_time,
                    )
                else:
                    self._mark_sent_log_persisted()
            raise
        except Exception:
            self._record_bounded_error(
                "storage_error",
                reference_time=reference_time,
            )
            return False
        self._mark_sent_log_persisted()
        return True

    async def _retry_dirty_sent_log(
        self,
        *,
        reference_time: datetime,
    ) -> bool:
        """Retry an acknowledgement that is terminal only in process memory."""
        self._require_aware_reference(reference_time)
        async with self.mutation_coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            if not self._sent_log_dirty:
                return True
            return await self._persist_dirty_sent_log_locked(
                reference_time=reference_time
            )

    def _record_bounded_error(
        self,
        code: str,
        *,
        reference_time: datetime,
    ) -> None:
        self._last_error_code = (
            code
            if type(code) is str and code in _BOUNDED_ERROR_CODES
            else "cycle_error"
        )
        self._last_error_at = reference_time.isoformat()

    async def _settle_occurrence(
        self,
        occurrence_key: str,
        alert_kind: str,
        result: MessageSendResult,
        *,
        reference_time: datetime,
    ) -> None:
        async with self.mutation_coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            if result.state is DeliveryState.NOT_DELIVERED:
                if self._occurrence_states.get(occurrence_key) == IN_FLIGHT:
                    self._occurrence_states.pop(occurrence_key, None)
                self.stats["delivery_failures"] += 1
                self._record_bounded_error(
                    "delivery_failure",
                    reference_time=reference_time,
                )
                return

            terminal_state = (
                SENT
                if result.state is DeliveryState.DELIVERED
                else SUPPRESSED_UNKNOWN
            )
            self._occurrence_states[occurrence_key] = terminal_state
            records = self.sent_log.get("reminders_sent")
            if type(records) is not dict:
                records = {}
                self.sent_log["reminders_sent"] = records
            records[occurrence_key] = {
                "state": terminal_state,
                "at": reference_time.timestamp(),
            }

            if result.state is DeliveryState.DELIVERED:
                counter = (
                    "warning_30m_sent"
                    if alert_kind == "warning_30m"
                    else "due_sent"
                )
                self.stats[counter] += 1
            else:
                self.stats["delivery_failures"] += 1
                self._record_bounded_error(
                    "delivery_failure",
                    reference_time=reference_time,
                )

            self._prune_terminal_records(reference_time=reference_time)
            self._sent_log_dirty = True
            await self._persist_dirty_sent_log_locked(
                reference_time=reference_time
            )

    async def _settle_digest(
        self,
        digest_key: str,
        result: MessageSendResult,
        *,
        reference_time: datetime,
    ) -> None:
        async with self.mutation_coordinator.hold(REMINDER_SENT_LOG_SCOPE):
            if result.state is DeliveryState.NOT_DELIVERED:
                if self._digest_states.get(digest_key) == IN_FLIGHT:
                    self._digest_states.pop(digest_key, None)
                self.stats["delivery_failures"] += 1
                self._record_bounded_error(
                    "delivery_failure",
                    reference_time=reference_time,
                )
                return

            terminal_state = (
                SENT
                if result.state is DeliveryState.DELIVERED
                else SUPPRESSED_UNKNOWN
            )
            self._digest_states[digest_key] = terminal_state
            records = self.sent_log.get("digest_log")
            if type(records) is not dict:
                records = {}
                self.sent_log["digest_log"] = records
            records[digest_key] = {
                "state": terminal_state,
                "at": reference_time.timestamp(),
            }

            if result.state is DeliveryState.DELIVERED:
                self.stats["digest_sent"] += 1
            else:
                self.stats["delivery_failures"] += 1
                self._record_bounded_error(
                    "delivery_failure",
                    reference_time=reference_time,
                )

            self._prune_terminal_records(reference_time=reference_time)
            self._sent_log_dirty = True
            await self._persist_dirty_sent_log_locked(
                reference_time=reference_time
            )

    @staticmethod
    async def _await_owned_task(task: asyncio.Task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.cancelled():
            return None
        try:
            return task.result()
        except Exception:
            return None

    def _consume_owned_send(self, task: asyncio.Task) -> None:
        self._owned_send_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def _track_owned_send(self, task: asyncio.Task) -> None:
        self._owned_send_tasks.add(task)
        task.add_done_callback(self._consume_owned_send)

    @staticmethod
    def _owned_send_result(task: asyncio.Task) -> MessageSendResult:
        if task.cancelled():
            return MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_cancelled",
            )
        try:
            result = task.result()
        except asyncio.CancelledError:
            return MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_cancelled",
            )
        except Exception:
            return MessageSendResult(DeliveryState.UNKNOWN, "transport")
        if not isinstance(result, MessageSendResult):
            return MessageSendResult(DeliveryState.UNKNOWN, "transport")
        return result

    async def _run_owned_send(
        self,
        send: Awaitable[MessageSendResult],
    ) -> MessageSendResult:
        """Run one separately owned send with a hard bounded wait."""
        send_task = asyncio.create_task(send)
        self._track_owned_send(send_task)
        try:
            done, _ = await asyncio.wait(
                {send_task},
                timeout=ALERT_SEND_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            # The attempt is normally shielded. If it is independently torn
            # down, leave the separately owned child tracked to completion.
            raise
        if send_task in done:
            return self._owned_send_result(send_task)
        send_task.cancel()
        return MessageSendResult(DeliveryState.UNKNOWN, "timeout")

    async def _run_alert_send(self, item, alert_kind: str) -> MessageSendResult:
        send = (
            self._send_item_reminder(item, alert_kind)
            if item.get("source_kind") == "calendar"
            else self._send_reminder_remind(item, alert_kind)
        )
        return await self._run_owned_send(send)

    async def _run_digest_send(
        self,
        channel_id,
        message: str,
    ) -> MessageSendResult:
        return await self._run_owned_send(
            self._send_to_channel(
                channel_id,
                message,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        )

    async def _settle_owned(
        self,
        occurrence_key: str,
        alert_kind: str,
        result: MessageSendResult,
        *,
        reference_time: datetime,
    ) -> None:
        settlement = asyncio.create_task(
            self._settle_occurrence(
                occurrence_key,
                alert_kind,
                result,
                reference_time=reference_time,
            )
        )
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            await self._await_owned_task(settlement)
            raise

    async def _settle_owned_digest(
        self,
        digest_key: str,
        result: MessageSendResult,
        *,
        reference_time: datetime,
    ) -> None:
        settlement = asyncio.create_task(
            self._settle_digest(
                digest_key,
                result,
                reference_time=reference_time,
            )
        )
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            await self._await_owned_task(settlement)
            raise

    async def _deliver_claimed_occurrence(
        self,
        item,
        occurrence_key: str,
        alert_kind: str,
        *,
        reference_time: datetime,
    ) -> MessageSendResult:
        catchup = (
            alert_kind == "due"
            and item["due_at"].astimezone(timezone.utc)
            < reference_time.astimezone(timezone.utc)
        )
        attempt = asyncio.create_task(self._run_alert_send(item, alert_kind))
        try:
            result = await asyncio.shield(attempt)
        except asyncio.CancelledError:
            await self._await_owned_task(attempt)
            cancelled_result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_cancelled",
            )
            self._record_delivery_result(
                cancelled_result,
                digest=False,
                catchup=catchup,
            )
            settlement = asyncio.create_task(
                self._settle_occurrence(
                    occurrence_key,
                    alert_kind,
                    cancelled_result,
                    reference_time=reference_time,
                )
            )
            await self._await_owned_task(settlement)
            raise

        self._record_delivery_result(result, digest=False, catchup=catchup)
        await self._settle_owned(
            occurrence_key,
            alert_kind,
            result,
            reference_time=reference_time,
        )
        return result

    async def _deliver_claimed_digest(
        self,
        channel_id,
        message: str,
        digest_key: str,
        *,
        reference_time: datetime,
    ) -> MessageSendResult:
        attempt = asyncio.create_task(
            self._run_digest_send(channel_id, message)
        )
        try:
            result = await asyncio.shield(attempt)
        except asyncio.CancelledError:
            await self._await_owned_task(attempt)
            cancelled_result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_cancelled",
            )
            self._record_delivery_result(
                cancelled_result,
                digest=True,
                catchup=False,
            )
            settlement = asyncio.create_task(
                self._settle_digest(
                    digest_key,
                    cancelled_result,
                    reference_time=reference_time,
                )
            )
            await self._await_owned_task(settlement)
            raise

        self._record_delivery_result(result, digest=True, catchup=False)
        await self._settle_owned_digest(
            digest_key,
            result,
            reference_time=reference_time,
        )
        return result

    def _record_delivery_result(
        self,
        result: MessageSendResult,
        *,
        digest: bool,
        catchup: bool,
    ) -> None:
        """Record one bounded acknowledgement outcome without message data."""
        if result.state is DeliveryState.DELIVERED:
            if digest:
                event = "digest_sent"
            elif catchup:
                event = "catchup_sent"
            else:
                event = "sent"
            self.metrics.record_reminder_delivery(event)
            return
        event = "digest_failed" if digest else "send_failed"
        self.metrics.record_reminder_delivery(
            event,
            error_code=reminder_metric_error_code(result.error_code),
        )

    async def _process_occurrence(
        self,
        manager,
        family_scope,
        item,
        alert_kind: str,
        *,
        reference_time: datetime,
    ) -> MessageSendResult | None:
        occurrence_key = self._occurrence_key(item, alert_kind)
        fingerprint = self._occurrence_fingerprint(item)
        claimed = await self._claim_occurrence(
            manager,
            family_scope,
            fingerprint,
            occurrence_key,
            reference_time=reference_time,
        )
        if not claimed:
            return None
        return await self._deliver_claimed_occurrence(
            item,
            occurrence_key,
            alert_kind,
            reference_time=reference_time,
        )

    async def check_alerts_once(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> tuple[MessageSendResult, ...]:
        """Select, claim, and settle canonical alert occurrences once."""
        if reference_time is None:
            reference_time = self._capture_reference_time()
        else:
            self._require_aware_reference(reference_time)

        calendar_rows = ()
        if self.calendar is not None:
            calendar_snapshot = getattr(
                self.calendar,
                "snapshot_delivery_occurrences",
                None,
            )
            if callable(calendar_snapshot):
                calendar_rows = tuple(
                    calendar_snapshot(reference_time=reference_time)
                )

        reminder_rows = ()
        if self.reminders is not None:
            reminder_snapshot = getattr(
                self.reminders,
                "snapshot_delivery_occurrences",
                None,
            )
            if callable(reminder_snapshot):
                reminder_rows = tuple(
                    reminder_snapshot(reference_time=reference_time)
                )

        await self._normalize_sent_log_once(
            reference_time=reference_time,
            calendar_occurrences=calendar_rows,
        )

        families = (
            (
                self.calendar,
                CALENDAR_SHARED_SCOPE,
                calendar_rows,
                "calendar",
            ),
            (
                self.reminders,
                REMINDER_STORE_SCOPE,
                reminder_rows,
                "reminder",
            ),
        )
        results = []
        reference_utc = reference_time.astimezone(timezone.utc)
        for manager, family_scope, rows, expected_source in families:
            if manager is None:
                continue
            for item in rows:
                if type(item) is not dict:
                    continue
                item_id = item.get("id")
                due_at = item.get("due_at")
                if (
                    item.get("source_kind") != expected_source
                    or not isinstance(item_id, str)
                    or not item_id
                    or item_id != item_id.strip()
                    or ":" in item_id
                ):
                    continue
                if (
                    not isinstance(due_at, datetime)
                    or due_at.tzinfo is None
                    or due_at.utcoffset() is None
                    or due_at.microsecond
                ):
                    self.metrics.record_reminder_delivery(
                        "send_failed",
                        error_code="invalid_due_at",
                    )
                    continue
                delta = due_at.astimezone(timezone.utc) - reference_utc
                alert_kind = select_alert_kind(delta)
                if alert_kind is None:
                    if delta < -timedelta(minutes=10):
                        self.stats["missed_outside_catchup"] += 1
                    continue
                result = await self._process_occurrence(
                    manager,
                    family_scope,
                    item,
                    alert_kind,
                    reference_time=reference_time,
                )
                if result is not None:
                    results.append(result)
        return tuple(results)

    def _snapshot_delivery_diagnostics(
        self,
        *,
        reference_time: datetime,
    ) -> None:
        """Accumulate the two exact manager-owned diagnostic counters."""
        if self.reminders is None:
            return
        snapshot = getattr(
            self.reminders,
            "snapshot_delivery_diagnostics",
            None,
        )
        if not callable(snapshot):
            return
        diagnostics = snapshot(reference_time=reference_time)
        if type(diagnostics) is not dict:
            return
        for counter in ("malformed_legacy_due_at", "legacy_due_mismatch"):
            value = diagnostics.get(counter)
            if type(value) is int and value >= 0:
                self.stats[counter] += value

    async def _maybe_sync_gcal(
        self,
        *,
        reference_time: datetime,
    ) -> None:
        """Run one structured GCal pull when the cycle cadence is due."""
        if self.calendar is None:
            return
        try:
            reference_epoch = reference_time.timestamp()
            if (
                self._last_gcal_probe_error is not None
                and reference_epoch - self._last_gcal_probe_error < 900
            ):
                return
            try:
                enabled = getattr(self.calendar, "gcal_enabled", False)
            except Exception:
                self._last_gcal_probe_error = reference_epoch
                raise
            self._last_gcal_probe_error = None
            if enabled is not True:
                return
            if self._last_gcal_sync is None:
                self._last_gcal_sync = reference_epoch
                return
            if reference_epoch - self._last_gcal_sync < 900:
                return

            # Advance before awaiting so failures and cancellations cannot cause
            # an immediate retry storm.
            self._last_gcal_sync = reference_epoch
            sync = getattr(self.calendar, "sync_from_gcal_result", None)
            if not callable(sync):
                raise TypeError("structured_gcal_sync_adapter_missing")
            result = await sync(reference_time=reference_time)
            if getattr(result, "ok", None) is not True:
                raise ValueError("structured_gcal_sync_failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.stats["gcal_sync_errors"] += 1
            self._record_bounded_error(
                "gcal_sync_error",
                reference_time=reference_time,
            )

    async def check_once(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> None:
        """Run one bounded checker cycle using one shared reference instant."""
        if reference_time is None:
            reference_time = self._capture_reference_time()
        else:
            self._require_aware_reference(reference_time)

        reference_text = reference_time.isoformat()
        self.stats["cycles"] += 1
        self._last_check_at = reference_text
        self._last_error_code = None
        self._health_stale = False
        if self.running and self._started_at is None:
            self._started_at = reference_text

        try:
            await self._retry_dirty_sent_log(
                reference_time=reference_time
            )
            self._snapshot_delivery_diagnostics(
                reference_time=reference_time
            )
            await self.check_alerts_once(reference_time=reference_time)
            await self.check_morning_digest(reference_time=reference_time)
            await self._maybe_sync_gcal(reference_time=reference_time)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.stats["cycle_errors"] += 1
            self._consecutive_errors += 1
            self._record_bounded_error(
                "cycle_error",
                reference_time=reference_time,
            )
            self._health_status = "degraded"
            return

        self._last_success_at = reference_text
        self._consecutive_errors = 0
        self._health_status = (
            "degraded" if self._last_error_code is not None else "ok"
        )

    async def setup(self):
        """Async initialization"""
        self.sent_log = await self._load_sent_log()
        self._sent_log_normalized = False
        self._sent_log_dirty = False

    async def _load_sent_log(self):
        """Load a bounded detached root off-loop without exposing failures."""
        def _read():
            try:
                if not self.storage_path.exists():
                    return None
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None

        raw = await asyncio.to_thread(_read)
        return self._bounded_sent_log_root(raw)

    async def _run_legacy_alert_wrapper(
        self,
        *,
        reference_time: datetime | None,
    ) -> tuple[MessageSendResult, ...]:
        """Forward one compatibility entry point to the unified alert pass."""
        if reference_time is None:
            reference_time = self._capture_reference_time()
        else:
            self._require_aware_reference(reference_time)
        return await self.check_alerts_once(reference_time=reference_time)

    async def check_upcoming_30min(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> tuple[MessageSendResult, ...]:
        return await self._run_legacy_alert_wrapper(
            reference_time=reference_time
        )

    async def check_event_now(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> tuple[MessageSendResult, ...]:
        return await self._run_legacy_alert_wrapper(
            reference_time=reference_time
        )

    async def check_event_passed(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> tuple[MessageSendResult, ...]:
        return await self._run_legacy_alert_wrapper(
            reference_time=reference_time
        )

    # ---- Morning digest at 09:00 ----

    async def check_morning_digest(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> MessageSendResult | None:
        """Claim and acknowledge today's one global Oslo morning digest."""
        if reference_time is None:
            reference_time = self._capture_reference_time()
        else:
            self._require_aware_reference(reference_time)
        local_reference = reference_time.astimezone(OSLO)
        if not 9 <= local_reference.hour < 10:
            return None

        pending_rows = ()
        if self.calendar is not None:
            pending_snapshot = getattr(
                self.calendar,
                "snapshot_pending_items",
                None,
            )
            if callable(pending_snapshot):
                pending_rows = tuple(
                    pending_snapshot(reference_time=reference_time)
                )

        calendar_occurrences = ()
        if not self._sent_log_normalized and self.calendar is not None:
            delivery_snapshot = getattr(
                self.calendar,
                "snapshot_delivery_occurrences",
                None,
            )
            if callable(delivery_snapshot):
                calendar_occurrences = tuple(
                    delivery_snapshot(reference_time=reference_time)
                )
        await self._normalize_sent_log_once(
            reference_time=reference_time,
            calendar_occurrences=calendar_occurrences,
            refresh_alert_retention=False,
        )

        today = local_reference.strftime("%d.%m.%Y")
        today_items = tuple(
            item
            for item in pending_rows
            if (
                type(item) is dict
                and item.get("date") == today
                and isinstance(item.get("title"), str)
                and bool(item["title"].strip())
                and (
                    item.get("time") is None
                    or isinstance(item.get("time"), str)
                )
            )
        )
        if not today_items:
            return None

        channel_id = self._select_digest_channel(today_items)
        message = self._format_morning_digest(today_items, local_reference)
        digest_key = local_reference.strftime("%Y-%m-%d")
        claimed = await self._claim_digest(
            digest_key,
            reference_time=reference_time,
        )
        if not claimed:
            return None
        return await self._deliver_claimed_digest(
            channel_id,
            message,
            digest_key,
            reference_time=reference_time,
        )

    # ---- Helpers ----

    def _find_digest_channel(
        self,
        guild_id,
        *,
        reference_time: datetime | None = None,
    ) -> int | None:
        """Compatibility lookup using the canonical channel selector."""
        if self.calendar is None:
            return None
        get_upcoming = getattr(self.calendar, "get_upcoming", None)
        if not callable(get_upcoming):
            return None
        kwargs = {"days": 1}
        if reference_time is not None:
            self._require_aware_reference(reference_time)
            kwargs["reference_time"] = reference_time
        items = get_upcoming(guild_id, **kwargs)
        return self._select_digest_channel(items)

    @classmethod
    def _select_digest_channel(cls, items) -> int | None:
        for item in items:
            if type(item) is not dict:
                continue
            channel_id = cls._normalize_snowflake(item.get("channel_id"))
            if channel_id is not None:
                return channel_id
        return None

    def _format_morning_digest(self, items, now):
        """Format morning digest message in Norwegian"""
        day_names = [
            "mandag", "tirsdag", "onsdag", "torsdag",
            "fredag", "lørdag", "søndag",
        ]
        day_name = day_names[now.weekday()]
        date_str = now.strftime("%d.%m.%Y")

        lines = [
            f"☀️ **God morgen!** {day_name} {date_str}",
            "",
        ]
        for item in items[:8]:
            time_str = f" kl. {item['time']}" if item.get("time") else ""
            creator_str = f" ({item.get('username', 'Ukjent')})"
            lines.append(f"  {item['title']}{time_str}{creator_str}")

        if len(items) > 8:
            lines.append(f"  ...og {len(items) - 8} til. Bruk @inebotten kalender for hele listen.")

        lines.append("")
        lines.append("Ha ein fin dag! ✨")
        return "\n".join(lines)

    async def _send_item_reminder(
        self,
        item,
        remind_type,
        label=None,
    ) -> MessageSendResult:
        """Send one calendar alert without claiming or recording it."""
        channel_id = item.get("channel_id")
        time_str = f" kl. {item['time']}" if item.get("time") else ""

        # Different messages based on reminder type
        if remind_type in {"30min", "warning_30m"}:
            label = label or "30 minutter"
            message = (
                f"⏰ **Påminnelse: {item['title']}**\n\n"
                f"Det er {label} til!{time_str}\n\n"
                f"Klar? 😊"
            )
        elif remind_type in {"now", "due", "passed"}:
            message = (
                f"🔔 **Starter nå: {item['title']}**\n\n"
                f"Det er på tide!{time_str}\n\n"
                f"Lykke til! 🎉"
            )
        else:
            message = f"⏰ **{item['title']}** - {label}{time_str}"

        return await self._send_mentions_item(channel_id, item, message)

    async def _send_reminder_remind(
        self,
        reminder,
        remind_type,
        label=None,
    ) -> MessageSendResult:
        """Send one reminder alert without claiming or recording it."""
        channel_id = reminder.get("channel_id")

        # Different messages based on reminder type
        if remind_type in {"30min", "warning_30m"}:
            label = label or "30 minutter"
            message = (
                f"⏰ **Påminnelse: {reminder['text']}**\n\n"
                f"Det er {label} til!\n\n"
                f"Klar? 😊"
            )
        elif remind_type in {"now", "due", "passed"}:
            message = (
                f"🔔 **Nå: {reminder['text']}**\n\n"
                f"Det er på tide!\n\n"
                f"Lykke til! 🎉"
            )
        else:
            message = f"⏰ **{reminder['text']}** - {label}"

        return await self._send_mentions_item(channel_id, reminder, message)

    async def _send_mentions_item(self, channel_id, item, message):
        """Send while allowing only the canonical stored creator mention."""
        user_id = item.get("user_id")
        if type(user_id) is str and user_id == "gcal_sync":
            message = f"📅 **Google Calendar Sync**\n\n{message}"
            allowed_mentions = discord.AllowedMentions.none()
        else:
            normalized_user_id = self._normalize_snowflake(user_id)
            if normalized_user_id is None:
                allowed_mentions = discord.AllowedMentions.none()
            else:
                message = f"<@{normalized_user_id}>\n\n{message}"
                allowed_mentions = discord.AllowedMentions(
                    users=[discord.Object(id=normalized_user_id)],
                    roles=False,
                    everyone=False,
                    replied_user=False,
                )

        return await self._send_to_channel(
            channel_id,
            message,
            allowed_mentions=allowed_mentions,
        )

    @staticmethod
    def _normalize_snowflake(value) -> int | None:
        """Normalize canonical integer/decimal snowflakes without coercion hooks."""
        if type(value) is int:
            normalized = value
        elif type(value) is str:
            candidate = value.strip()
            if (
                not candidate
                or len(candidate) > 20
                or not candidate.isascii()
                or not candidate.isdecimal()
            ):
                return None
            normalized = int(candidate)
        else:
            return None
        if not 0 < normalized < 2**64:
            return None
        return normalized

    async def _send_to_channel(
        self,
        channel_id,
        message,
        *,
        allowed_mentions,
    ) -> MessageSendResult:
        """Attempt one hardened channel send and report delivery certainty."""
        if channel_id is None or (type(channel_id) is str and channel_id == ""):
            self.stats["skipped_missing_channel"] += 1
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "missing_channel",
            )

        normalized_channel_id = self._normalize_snowflake(channel_id)
        if normalized_channel_id is None:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "invalid_channel",
            )

        channel = None
        try:
            if self.get_channel is not None:
                channel = self.get_channel(normalized_channel_id)
        except Exception:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "transport",
            )

        if channel is not None:
            try:
                self.metrics.record_reminder_delivery("attempted")
                await channel.send(
                    message,
                    allowed_mentions=allowed_mentions,
                    suppress_embeds=True,
                )
            except discord.errors.Forbidden:
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "forbidden",
                )
            except discord.errors.HTTPException:
                return MessageSendResult(DeliveryState.UNKNOWN, "http")
            except Exception:
                return MessageSendResult(DeliveryState.UNKNOWN, "transport")
            return MessageSendResult(DeliveryState.DELIVERED)

        if self.send_channel_message is not None:
            try:
                self.metrics.record_reminder_delivery("attempted")
                await self.send_channel_message(
                    normalized_channel_id,
                    message,
                    allowed_mentions=allowed_mentions,
                    suppress_embeds=True,
                )
            except discord.errors.Forbidden:
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "forbidden",
                )
            except discord.errors.HTTPException:
                return MessageSendResult(DeliveryState.UNKNOWN, "http")
            except Exception:
                return MessageSendResult(DeliveryState.UNKNOWN, "transport")
            return MessageSendResult(DeliveryState.DELIVERED)

        return MessageSendResult(
            DeliveryState.NOT_DELIVERED,
            "missing_adapter",
        )

    # ---- Main loop ----

    async def start(self):
        """Run immediate checker cycles separated by the injected interval."""
        if self.running:
            return
        self.running = True
        self._health_status = "starting"
        self._health_stale = False
        self._started_at = None
        try:
            while self.running:
                await self.check_once()
                if self.running:
                    await self.sleep_func(self.interval_seconds)
        finally:
            self.running = False
            self._health_status = "stopped"
            self._health_stale = False

    def stop(self):
        """Request a synchronous, idempotent checker stop."""
        self.running = False
        self._health_status = "stopped"
        self._health_stale = False
