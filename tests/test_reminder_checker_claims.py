"""Claim, delivery, and settlement truth for canonical reminder occurrences."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import discord
import pytest

import cal_system.reminder_checker as checker_module
from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_checker import ReminderChecker
from cal_system.reminder_manager import ReminderManager
from core.dispatch_result import DeliveryState, MessageSendResult
from core.mutation_coordinator import (
    CALENDAR_SHARED_SCOPE,
    REMINDER_SENT_LOG_SCOPE,
    REMINDER_STORE_SCOPE,
    MutationCoordinator,
)


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)


class _ExplodingClock:
    def now(self):
        raise AssertionError("supplied cycle reference must be reused")

    def epoch(self):
        raise AssertionError("checker must not read clock.epoch()")


class _Response:
    reason = "bounded-test"
    headers = {}

    def __init__(self, status: int):
        self.status = status


class _TrackingCoordinator(MutationCoordinator):
    def __init__(self):
        super().__init__()
        self.active = []
        self.entries = []

    @asynccontextmanager
    async def hold(self, scope):
        async with super().hold(scope):
            self.entries.append((scope, tuple(self.active)))
            self.active.append(scope)
            try:
                yield
            finally:
                assert self.active.pop() == scope


class _SnapshotCalendar:
    def __init__(self, rows, coordinator):
        self.rows = tuple(copy.deepcopy(rows))
        self.mutation_coordinator = coordinator
        self.snapshot_calls = 0
        self.references = []

    def snapshot_delivery_occurrences(self, *, reference_time):
        self.snapshot_calls += 1
        self.references.append(reference_time)
        return tuple(copy.deepcopy(self.rows))

    def matches_delivery_fingerprint(self, fingerprint, *, reference_time):
        self.mutation_coordinator.assert_held(CALENDAR_SHARED_SCOPE)
        return False


def _calendar_item(
    item_id: str = "cal-1",
    *,
    due_at: datetime = NOW + timedelta(minutes=30),
    channel_id="99",
    user_id="42",
):
    local = due_at.astimezone(OSLO)
    return {
        "id": item_id,
        "title": "Legetime",
        "date": local.strftime("%d.%m.%Y"),
        "time": local.strftime("%H:%M"),
        "completed": False,
        "delete_pending": False,
        "channel_id": channel_id,
        "user_id": user_id,
    }


def _reminder(
    reminder_id: str = "rem-1",
    *,
    due_at: datetime = NOW,
    channel_id="99",
    user_id="42",
    recurrence=None,
    anchor=None,
    sequence=None,
):
    return {
        "id": reminder_id,
        "text": "Ta medisinen",
        "due_at": due_at.isoformat(timespec="seconds"),
        "due_date": due_at.astimezone(OSLO).strftime("%d.%m.%Y"),
        "time": due_at.astimezone(OSLO).strftime("%H:%M"),
        "timezone": "Europe/Oslo",
        "recurrence": recurrence,
        "recurrence_anchor_local": anchor,
        "recurrence_sequence": sequence,
        "completed": False,
        "channel_id": channel_id,
        "user_id": user_id,
    }


def _calendar_manager(tmp_path, coordinator, item=None):
    manager = CalendarManager(
        tmp_path / "calendar.json",
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.items = {manager.SHARED_KEY: [item or _calendar_item()]}
    return manager


def _reminder_manager(tmp_path, coordinator, reminder=None):
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.reminders = {"1": [reminder or _reminder()]}
    return manager


def _checker(
    tmp_path,
    coordinator,
    *,
    calendar=None,
    reminders=None,
    send=None,
):
    send = send or AsyncMock()
    channel = SimpleNamespace(send=send)
    checker = ReminderChecker(
        calendar_manager=calendar,
        reminder_manager=reminders,
        get_channel_func=Mock(return_value=channel),
        storage_path=tmp_path / "sent.json",
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    return checker, send


def test_occurrence_key_and_fingerprints_are_exact_and_reject_naive_due(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    reminders = _reminder_manager(tmp_path, coordinator)
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        reminders=reminders,
    )
    calendar_row = calendar.snapshot_delivery_occurrences(reference_time=NOW)[0]
    reminder_row = reminders.snapshot_delivery_occurrences(reference_time=NOW)[0]

    assert checker._occurrence_key(calendar_row, "warning_30m") == (
        "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    )
    assert checker._occurrence_fingerprint(calendar_row) == (
        "cal-1",
        calendar_row["due_at"],
        "active",
        False,
    )
    assert checker._occurrence_fingerprint(reminder_row) == (
        "rem-1",
        reminder_row["due_at"],
        None,
        None,
        False,
    )
    malformed = dict(calendar_row, due_at=datetime(2026, 7, 15, 12, 30))
    with pytest.raises(ValueError, match="^occurrence_due_at_must_be_aware$"):
        checker._occurrence_key(malformed, "warning_30m")
    microsecond = dict(
        calendar_row,
        due_at=datetime(2026, 7, 15, 12, 30, 0, 1, tzinfo=OSLO),
    )
    with pytest.raises(ValueError, match="^occurrence_due_at_must_be_canonical$"):
        checker._occurrence_key(microsecond, "warning_30m")


@pytest.mark.asyncio
async def test_check_alerts_uses_utc_delta_and_selects_once_per_row(
    tmp_path,
    monkeypatch,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    reminders = _reminder_manager(
        tmp_path,
        coordinator,
        _reminder("outside", due_at=NOW + timedelta(minutes=5)),
    )
    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        reminders=reminders,
    )
    calls = []
    real_select = checker_module.select_alert_kind

    def counting_select(delta):
        calls.append(delta)
        return real_select(delta)

    monkeypatch.setattr(checker_module, "select_alert_kind", counting_select)

    results = await checker.check_alerts_once(reference_time=NOW)

    assert calls == [timedelta(minutes=30), timedelta(minutes=5)]
    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_spring_forward_calendar_warning_uses_instant_delta(tmp_path):
    now = datetime(2026, 3, 29, 1, 30, tzinfo=OSLO)
    due = datetime(2026, 3, 29, 3, 0, tzinfo=OSLO)
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item("spring", due_at=due),
    )
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)

    results = await checker.check_alerts_once(reference_time=now)

    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 1
    key = "calendar:spring:2026-03-29T03:00:00+02:00:warning_30m"
    assert checker.sent_log["reminders_sent"][key] == {
        "state": "sent",
        "at": now.timestamp(),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("minute", "expected_sends"),
    ((59, 1), (55, 0)),
)
async def test_autumn_fold_reminder_due_window_uses_instant_delta(
    tmp_path,
    minute,
    expected_sends,
):
    now = datetime(2026, 10, 25, 2, minute, tzinfo=OSLO, fold=0)
    due = datetime(2026, 10, 25, 2, 0, tzinfo=OSLO, fold=1)
    coordinator = MutationCoordinator()
    reminders = _reminder_manager(
        tmp_path,
        coordinator,
        _reminder("fold", due_at=due),
    )
    checker, send = _checker(tmp_path, coordinator, reminders=reminders)

    results = await checker.check_alerts_once(reference_time=now)

    assert len(results) == expected_sends
    assert send.await_count == expected_sends
    if expected_sends:
        key = "reminder:fold:2026-10-25T02:00:00+01:00:due"
        assert checker.sent_log["reminders_sent"][key]["state"] == "sent"


@pytest.mark.asyncio
async def test_claim_uses_family_then_sent_scope_and_releases_before_io(tmp_path):
    coordinator = _TrackingCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)

    async def send(*_args, **_kwargs):
        assert coordinator.active == []

    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=AsyncMock(side_effect=send),
    )

    await checker.check_alerts_once(reference_time=NOW)

    assert coordinator.entries[0] == (REMINDER_SENT_LOG_SCOPE, ())
    assert coordinator.entries[1] == (CALENDAR_SHARED_SCOPE, ())
    assert coordinator.entries[2] == (
        REMINDER_SENT_LOG_SCOPE,
        (CALENDAR_SHARED_SCOPE,),
    )
    assert coordinator.entries[3] == (REMINDER_SENT_LOG_SCOPE, ())


@pytest.mark.asyncio
async def test_two_overlapping_cycles_claim_once_and_send_once(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    send_started = asyncio.Event()
    release_send = asyncio.Event()

    async def blocked_send(*_args, **_kwargs):
        send_started.set()
        await release_send.wait()

    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=AsyncMock(side_effect=blocked_send),
    )

    first = asyncio.create_task(checker.check_alerts_once(reference_time=NOW))
    await asyncio.wait_for(send_started.wait(), timeout=1)
    second_result = await asyncio.wait_for(
        checker.check_alerts_once(reference_time=NOW),
        timeout=1,
    )
    release_send.set()
    first_result = await asyncio.wait_for(first, timeout=1)

    assert first_result == (MessageSendResult(DeliveryState.DELIVERED),)
    assert second_result == ()
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_calendar_and_reminder_settlements_preserve_both_keys(
    tmp_path,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    reminders = _reminder_manager(tmp_path, coordinator)
    both_started = asyncio.Event()
    release = asyncio.Event()
    started = 0

    async def blocked_send(*_args, **_kwargs):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await release.wait()

    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        reminders=reminders,
        send=AsyncMock(side_effect=blocked_send),
    )
    calendar_row = calendar.snapshot_delivery_occurrences(reference_time=NOW)[0]
    reminder_row = reminders.snapshot_delivery_occurrences(reference_time=NOW)[0]

    deliveries = asyncio.gather(
        checker._process_occurrence(
            calendar,
            CALENDAR_SHARED_SCOPE,
            calendar_row,
            "warning_30m",
            reference_time=NOW,
        ),
        checker._process_occurrence(
            reminders,
            REMINDER_STORE_SCOPE,
            reminder_row,
            "due",
            reference_time=NOW,
        ),
    )
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()
    results = await asyncio.wait_for(deliveries, timeout=1)

    assert results == [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.DELIVERED),
    ]
    assert send.await_count == 2
    assert checker.sent_log["reminders_sent"] == {
        "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m": {
            "state": "sent",
            "at": NOW.timestamp(),
        },
        "reminder:rem-1:2026-07-15T12:00:00+02:00:due": {
            "state": "sent",
            "at": NOW.timestamp(),
        },
    }


@pytest.mark.asyncio
async def test_writer_before_claim_prevents_stale_send(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    snapshotted = asyncio.Event()
    original_snapshot = calendar.snapshot_delivery_occurrences

    def snapshot(*, reference_time):
        rows = original_snapshot(reference_time=reference_time)
        snapshotted.set()
        return rows

    calendar.snapshot_delivery_occurrences = snapshot
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)

    async with coordinator.hold(CALENDAR_SHARED_SCOPE):
        cycle = asyncio.create_task(checker.check_alerts_once(reference_time=NOW))
        await asyncio.wait_for(snapshotted.wait(), timeout=1)
        calendar.items[calendar.SHARED_KEY][0]["time"] = "12:31"

    assert await asyncio.wait_for(cycle, timeout=1) == ()
    assert send.await_count == 0
    assert checker.sent_log["reminders_sent"] == {}


@pytest.mark.asyncio
async def test_writer_after_claim_does_not_wait_for_discord_io(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    send_started = asyncio.Event()
    release_send = asyncio.Event()

    async def blocked_send(*_args, **_kwargs):
        send_started.set()
        await release_send.wait()

    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=AsyncMock(side_effect=blocked_send),
    )
    cycle = asyncio.create_task(checker.check_alerts_once(reference_time=NOW))
    await asyncio.wait_for(send_started.wait(), timeout=1)

    async def writer():
        async with coordinator.hold(CALENDAR_SHARED_SCOPE):
            calendar.items[calendar.SHARED_KEY][0]["completed"] = True

    await asyncio.wait_for(writer(), timeout=0.2)
    assert not cycle.done()
    release_send.set()

    assert await asyncio.wait_for(cycle, timeout=1) == (
        MessageSendResult(DeliveryState.DELIVERED),
    )
    assert send.await_count == 1
    assert calendar.items[calendar.SHARED_KEY][0]["completed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ("calendar", "reminder"))
async def test_send_helpers_return_receipt_without_marking_counting_or_mutating(
    tmp_path,
    source_kind,
):
    coordinator = MutationCoordinator()
    checker, send = _checker(tmp_path, coordinator)
    before_stats = copy.deepcopy(checker.stats)
    before_log = copy.deepcopy(checker.sent_log)
    if source_kind == "calendar":
        row = {
            **_calendar_item(),
            "due_at": NOW + timedelta(minutes=30),
            "source_kind": "calendar",
        }
        result = await checker._send_item_reminder(row, "warning_30m")
    else:
        row = {
            **_reminder(),
            "due_at": NOW,
            "source_kind": "reminder",
        }
        result = await checker._send_reminder_remind(row, "due")

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    assert checker.stats == before_stats
    assert checker.sent_log == before_log
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_definite_failure_releases_claim_for_one_later_retry(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item(channel_id=None),
    )
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)

    first = await checker.check_alerts_once(reference_time=NOW)
    calendar.items[calendar.SHARED_KEY][0]["channel_id"] = "99"
    second = await checker.check_alerts_once(reference_time=NOW)

    assert first == (
        MessageSendResult(DeliveryState.NOT_DELIVERED, "missing_channel"),
    )
    assert second == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_unknown_send_is_suppressed_and_never_retried_blindly(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    send = AsyncMock(side_effect=RuntimeError("SECRET_TRANSPORT"))
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=send,
    )

    first = await checker.check_alerts_once(reference_time=NOW)
    second = await checker.check_alerts_once(reference_time=NOW)

    key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    assert first == (MessageSendResult(DeliveryState.UNKNOWN, "transport"),)
    assert second == ()
    assert send.await_count == 1
    assert checker.sent_log["reminders_sent"][key] == {
        "state": "suppressed_unknown",
        "at": NOW.timestamp(),
    }
    assert "SECRET_TRANSPORT" not in repr(checker.get_health())


@pytest.mark.asyncio
async def test_forbidden_is_definite_and_releases_claim(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    failure = discord.errors.Forbidden(_Response(403), "SECRET_FORBIDDEN")
    send = AsyncMock(side_effect=[failure, None])
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=send,
    )

    first = await checker.check_alerts_once(reference_time=NOW)
    second = await checker.check_alerts_once(reference_time=NOW)

    assert first == (
        MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
    )
    assert second == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_send_timeout_suppresses_unknown_and_owns_only_one_send(
    tmp_path,
    monkeypatch,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    started = asyncio.Event()

    async def never_finishes(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    send = AsyncMock(side_effect=never_finishes)
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=send,
    )
    monkeypatch.setattr(checker_module, "ALERT_SEND_TIMEOUT_SECONDS", 0.01)

    first = await checker.check_alerts_once(reference_time=NOW)
    second = await checker.check_alerts_once(reference_time=NOW)

    assert started.is_set()
    assert first == (MessageSendResult(DeliveryState.UNKNOWN, "timeout"),)
    assert second == ()
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_hard_timeout_does_not_wait_for_cancellation_resistant_send(
    tmp_path,
    monkeypatch,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def cancellation_resistant_send(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()

    send = AsyncMock(side_effect=cancellation_resistant_send)
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=send,
    )
    monkeypatch.setattr(checker_module, "ALERT_SEND_TIMEOUT_SECONDS", 0.01)

    first = await asyncio.wait_for(
        checker.check_alerts_once(reference_time=NOW),
        timeout=0.2,
    )
    await asyncio.wait_for(cancellation_seen.wait(), timeout=0.2)

    assert started.is_set()
    assert first == (MessageSendResult(DeliveryState.UNKNOWN, "timeout"),)
    assert len(checker._owned_send_tasks) == 1
    assert await checker.check_alerts_once(reference_time=NOW) == ()
    assert send.await_count == 1

    release.set()

    async def wait_until_drained():
        while checker._owned_send_tasks:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_until_drained(), timeout=0.2)
    assert checker._owned_send_tasks == set()


@pytest.mark.asyncio
async def test_outer_cancellation_stops_waiting_at_hard_send_deadline(
    tmp_path,
    monkeypatch,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()

    async def cancellation_resistant_send(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()

    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=AsyncMock(side_effect=cancellation_resistant_send),
    )
    monkeypatch.setattr(checker_module, "ALERT_SEND_TIMEOUT_SECONDS", 0.01)
    cycle = asyncio.create_task(checker.check_alerts_once(reference_time=NOW))
    await asyncio.wait_for(started.wait(), timeout=0.2)

    cycle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(cycle, timeout=0.2)
    await asyncio.wait_for(cancellation_seen.wait(), timeout=0.2)

    assert len(checker._owned_send_tasks) == 1
    key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    assert checker.sent_log["reminders_sent"][key]["state"] == (
        "suppressed_unknown"
    )

    release.set()
    while checker._owned_send_tasks:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_independent_child_send_cancellation_is_bounded_unknown(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    send = AsyncMock(side_effect=asyncio.CancelledError())
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=send,
    )

    first = await checker.check_alerts_once(reference_time=NOW)
    second = await checker.check_alerts_once(reference_time=NOW)

    assert first == (
        MessageSendResult(DeliveryState.UNKNOWN, "send_task_cancelled"),
    )
    assert second == ()
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_cancellation_waits_for_owned_send_then_suppresses_and_reraises(
    tmp_path,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(*_args, **_kwargs):
        started.set()
        await release.wait()

    send = AsyncMock(side_effect=blocked_send)
    checker, _ = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        send=send,
    )
    cycle = asyncio.create_task(checker.check_alerts_once(reference_time=NOW))
    await asyncio.wait_for(started.wait(), timeout=1)

    cycle.cancel()
    await asyncio.sleep(0)
    assert not cycle.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(cycle, timeout=1)

    key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    assert checker.sent_log["reminders_sent"][key] == {
        "state": "suppressed_unknown",
        "at": NOW.timestamp(),
    }
    assert await checker.check_alerts_once(reference_time=NOW) == ()
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_storage_failure_keeps_terminal_memory_and_original_delivery_truth(
    tmp_path,
    monkeypatch,
    capsys,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)

    def fail_write(*_args, **_kwargs):
        raise OSError("SECRET_STORAGE_PATH")

    monkeypatch.setattr(checker_module, "write_json_atomic", fail_write)

    first = await checker.check_alerts_once(reference_time=NOW)
    second = await checker.check_alerts_once(reference_time=NOW)

    assert first == (MessageSendResult(DeliveryState.DELIVERED),)
    assert second == ()
    assert send.await_count == 1
    assert checker.get_health()["last_error_code"] == "storage_error"
    assert "SECRET_STORAGE_PATH" not in repr(checker.get_health())
    captured = capsys.readouterr()
    assert "SECRET_STORAGE_PATH" not in captured.out
    assert "SECRET_STORAGE_PATH" not in captured.err


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ("sent", "suppressed_unknown"))
async def test_valid_new_schema_record_suppresses_after_setup(tmp_path, state):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    path = tmp_path / "sent.json"
    path.write_text(
        json.dumps(
            {
                "reminders_sent": {
                    key: {"state": state, "at": NOW.timestamp()},
                },
                "digest_log": {},
            }
        ),
        encoding="utf-8",
    )
    send = AsyncMock()
    checker = ReminderChecker(
        calendar_manager=calendar,
        get_channel_func=Mock(return_value=SimpleNamespace(send=send)),
        storage_path=path,
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    await checker.setup()

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == ()
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_state",
    (pytest.param([], id="list"), pytest.param({}, id="mapping")),
)
async def test_unhashable_persisted_state_is_ignored_without_breaking_claim(
    tmp_path,
    malformed_state,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    path = tmp_path / "sent.json"
    path.write_text(
        json.dumps(
            {
                "reminders_sent": {
                    key: {"state": malformed_state, "at": NOW.timestamp()},
                },
                "digest_log": {},
            }
        ),
        encoding="utf-8",
    )
    send = AsyncMock()
    checker = ReminderChecker(
        calendar_manager=calendar,
        get_channel_func=Mock(return_value=SimpleNamespace(send=send)),
        storage_path=path,
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    await checker.setup()

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    send.assert_awaited_once()
    assert checker.sent_log["reminders_sent"][key] == {
        "state": "sent",
        "at": NOW.timestamp(),
    }


@pytest.mark.asyncio
async def test_delivery_never_mutates_calendar_or_reminder_schedule(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    reminders = _reminder_manager(tmp_path, coordinator)
    before_calendar = copy.deepcopy(calendar.items)
    before_reminders = copy.deepcopy(reminders.reminders)
    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        reminders=reminders,
    )

    results = await checker.check_alerts_once(reference_time=NOW)

    assert len(results) == 2
    assert all(result.state is DeliveryState.DELIVERED for result in results)
    assert send.await_count == 2
    assert calendar.items == before_calendar
    assert reminders.reminders == before_reminders


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    (
        pytest.param([], id="list-root"),
        pytest.param(
            {"reminders_sent": [], "digest_log": {}},
            id="invalid-reminders-container",
        ),
        pytest.param(
            {"reminders_sent": {}, "digest_log": []},
            id="invalid-digest-container",
        ),
    ),
)
async def test_setup_bounds_malformed_top_level_without_rewriting(tmp_path, raw):
    path = tmp_path / "sent.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    checker = ReminderChecker(storage_path=path)

    await checker.setup()

    assert checker.sent_log == {"reminders_sent": {}, "digest_log": {}}
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_canonical_numeric_record_migrates_in_memory_and_suppresses(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    recent_at = NOW.timestamp() - 60
    raw = {"reminders_sent": {key: recent_at}, "digest_log": {}}
    path = tmp_path / "sent.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    checker.storage_path = path
    await checker.setup()

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == ()
    send.assert_not_awaited()
    assert checker.sent_log["reminders_sent"] == {
        key: {"state": "sent", "at": recent_at}
    }
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_all_old_calendar_suffixes_migrate_and_collisions_keep_newest(
    tmp_path,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    recent_base = NOW.timestamp() - 300
    checker.sent_log = {
        "reminders_sent": {
            "cal-1:30min": recent_base + 100,
            "cal-1:now": recent_base + 200,
            "cal-1:passed": recent_base + 300,
        },
        "digest_log": {},
    }

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == ()
    send.assert_not_awaited()
    assert checker.sent_log["reminders_sent"] == {
        "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m": {
            "state": "sent",
            "at": recent_base + 100,
        },
        "calendar:cal-1:2026-07-15T12:30:00+02:00:due": {
            "state": "sent",
            "at": recent_base + 300,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rows", "old_key"),
    (
        pytest.param((), "missing:30min", id="missing"),
        pytest.param(
            (
                {
                    "source_kind": "calendar",
                    "id": "duplicate",
                    "due_at": NOW + timedelta(minutes=5),
                    "status": "active",
                    "delete_pending": False,
                },
                {
                    "source_kind": "calendar",
                    "id": "duplicate",
                    "due_at": NOW + timedelta(minutes=6),
                    "status": "active",
                    "delete_pending": False,
                },
            ),
            "duplicate:now",
            id="duplicate-or-ambiguous",
        ),
        pytest.param(
            (
                {
                    "source_kind": "calendar",
                    "id": "naive",
                    "due_at": datetime(2026, 7, 15, 12, 5),
                    "status": "active",
                    "delete_pending": False,
                },
            ),
            "naive:passed",
            id="currently-unresolvable",
        ),
    ),
)
async def test_unresolvable_old_calendar_key_is_discarded_and_counted(
    tmp_path,
    rows,
    old_key,
):
    coordinator = MutationCoordinator()
    calendar = _SnapshotCalendar(rows, coordinator)
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    checker.sent_log = {
        "reminders_sent": {old_key: NOW.timestamp()},
        "digest_log": {},
    }

    await checker.check_alerts_once(reference_time=NOW)

    assert checker.sent_log["reminders_sent"] == {}
    assert checker.stats["malformed_legacy_due_at"] == 1
    assert calendar.snapshot_calls == 1
    assert calendar.references == [NOW]
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_at",
    (
        pytest.param(True, id="bool"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinite"),
        pytest.param(-1, id="negative"),
        pytest.param({"state": "sent", "at": 1}, id="record-not-numeric"),
    ),
)
async def test_old_calendar_key_with_invalid_timestamp_is_counted_and_discarded(
    tmp_path,
    invalid_at,
):
    coordinator = MutationCoordinator()
    due = NOW + timedelta(minutes=5)
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item(due_at=due),
    )
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    checker.sent_log = {
        "reminders_sent": {"cal-1:now": invalid_at},
        "digest_log": {},
    }

    assert await checker.check_alerts_once(reference_time=NOW) == ()

    assert checker.sent_log["reminders_sent"] == {}
    assert checker.stats["malformed_legacy_due_at"] == 1
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_reminder_style_key_and_impossible_keys_never_migrate(tmp_path):
    coordinator = MutationCoordinator()
    reminders = _reminder_manager(tmp_path, coordinator)
    checker, send = _checker(tmp_path, coordinator, reminders=reminders)
    checker.sent_log = {
        "reminders_sent": {
            "rem-1:now": NOW.timestamp(),
            "calendar:cal-1:not-a-date:due": NOW.timestamp(),
            "cal-1:future": NOW.timestamp(),
        },
        "digest_log": {},
    }

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 1
    assert "rem-1:now" not in checker.sent_log["reminders_sent"]
    assert "calendar:cal-1:not-a-date:due" not in (
        checker.sent_log["reminders_sent"]
    )
    assert "cal-1:future" not in checker.sent_log["reminders_sent"]
    assert checker.stats["malformed_legacy_due_at"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_record",
    (
        pytest.param(True, id="numeric-bool"),
        pytest.param(
            {"state": "sent", "at": True},
            id="record-bool-at",
        ),
        pytest.param(
            {"state": "sent", "at": float("nan")},
            id="record-nan-at",
        ),
        pytest.param(
            {"state": "sent", "at": float("inf")},
            id="record-infinite-at",
        ),
        pytest.param(
            {"state": "sent", "at": -1},
            id="record-negative-at",
        ),
        pytest.param(
            {"state": "unknown", "at": 1},
            id="unknown-state",
        ),
        pytest.param(
            {"state": "sent", "at": 1, "extra": True},
            id="extra-field",
        ),
        pytest.param(
            {"state": [], "at": 1},
            id="list-state",
        ),
        pytest.param(
            {"state": {}, "at": 1},
            id="mapping-state",
        ),
    ),
)
async def test_malformed_canonical_record_is_deterministically_discarded(
    tmp_path,
    malformed_record,
):
    coordinator = MutationCoordinator()
    due = NOW + timedelta(minutes=5)
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item(due_at=due),
    )
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    key = "calendar:cal-1:2026-07-15T12:05:00+02:00:due"
    checker.sent_log = {
        "reminders_sent": {key: malformed_record},
        "digest_log": {},
    }

    assert await checker.check_alerts_once(reference_time=NOW) == ()

    assert checker.sent_log["reminders_sent"] == {}
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_write_prunes_at_exact_two_day_cutoff(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    cutoff = NOW.timestamp() - 2 * 24 * 60 * 60
    exact_key = "calendar:old-exact:2026-01-01T09:00:00+01:00:due"
    kept_key = "reminder:old-kept:2026-01-01T09:00:00+01:00:due"
    older_key = "calendar:old-older:2026-01-01T09:00:00+01:00:warning_30m"
    checker.sent_log = {
        "reminders_sent": {
            exact_key: {"state": "sent", "at": cutoff},
            kept_key: {"state": "suppressed_unknown", "at": cutoff + 0.001},
            older_key: {"state": "sent", "at": cutoff - 1},
        },
        "digest_log": {},
    }

    results = await checker.check_alerts_once(reference_time=NOW)

    new_key = "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 1
    assert set(checker.sent_log["reminders_sent"]) == {kept_key, new_key}
    assert json.loads(checker.storage_path.read_text(encoding="utf-8")) == (
        checker.sent_log
    )


@pytest.mark.asyncio
async def test_ordinary_terminal_write_persists_lazy_migration(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    reminders = _reminder_manager(tmp_path, coordinator)
    path = tmp_path / "sent.json"
    raw = {
        "reminders_sent": {"cal-1:30min": NOW.timestamp()},
        "digest_log": {},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        reminders=reminders,
    )
    checker.storage_path = path
    await checker.setup()

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    assert send.await_count == 1
    assert path.read_bytes() != before
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "cal-1:30min" not in persisted["reminders_sent"]
    assert set(persisted["reminders_sent"]) == {
        "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m",
        "reminder:rem-1:2026-07-15T12:00:00+02:00:due",
    }


@pytest.mark.asyncio
async def test_definite_failure_keeps_lazy_migration_memory_only(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item(channel_id=None),
    )
    path = tmp_path / "sent.json"
    raw = {
        "reminders_sent": {"cal-1:now": NOW.timestamp()},
        "digest_log": {},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    checker.storage_path = path
    await checker.setup()

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == (
        MessageSendResult(DeliveryState.NOT_DELIVERED, "missing_channel"),
    )
    send.assert_not_awaited()
    assert "cal-1:now" not in checker.sent_log["reminders_sent"]
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_normalization_reuses_one_calendar_snapshot_and_reference_object(
    tmp_path,
):
    coordinator = MutationCoordinator()
    row = {
        "source_kind": "calendar",
        "id": "single",
        "due_at": NOW + timedelta(minutes=5),
        "status": "active",
        "delete_pending": False,
    }
    calendar = _SnapshotCalendar((row,), coordinator)
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    recent_at = NOW.timestamp() - 60
    checker.sent_log = {
        "reminders_sent": {"single:now": recent_at},
        "digest_log": {},
    }

    assert await checker.check_alerts_once(reference_time=NOW) == ()

    assert calendar.snapshot_calls == 1
    assert calendar.references[0] is NOW
    assert checker.sent_log["reminders_sent"] == {
        "calendar:single:2026-07-15T12:05:00+02:00:due": {
            "state": "sent",
            "at": recent_at,
        }
    }
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_shape", (False, True), ids=("canonical", "old"))
async def test_stale_record_at_cutoff_never_suppresses_current_occurrence(
    tmp_path,
    legacy_shape,
):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(tmp_path, coordinator)
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    cutoff = NOW.timestamp() - 2 * 24 * 60 * 60
    canonical_key = (
        "calendar:cal-1:2026-07-15T12:30:00+02:00:warning_30m"
    )
    if legacy_shape:
        records = {"cal-1:30min": cutoff}
    else:
        records = {
            canonical_key: {"state": "sent", "at": cutoff},
        }
    checker.sent_log = {"reminders_sent": records, "digest_log": {}}

    results = await checker.check_alerts_once(reference_time=NOW)

    assert results == (MessageSendResult(DeliveryState.DELIVERED),)
    send.assert_awaited_once()
    assert checker.sent_log["reminders_sent"] == {
        canonical_key: {"state": "sent", "at": NOW.timestamp()}
    }


@pytest.mark.asyncio
async def test_later_reference_expires_normalized_record_and_cached_state(tmp_path):
    coordinator = MutationCoordinator()
    due = NOW + timedelta(minutes=5)
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item(due_at=due),
    )
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    key = "calendar:cal-1:2026-07-15T12:05:00+02:00:due"
    checker.sent_log = {
        "reminders_sent": {
            key: {"state": "sent", "at": NOW.timestamp()},
        },
        "digest_log": {},
    }

    assert await checker.check_alerts_once(reference_time=NOW) == ()
    checker._occurrence_states[key] = "sent"
    later = NOW + timedelta(days=2, seconds=1)
    rows = calendar.snapshot_delivery_occurrences(reference_time=later)

    await checker._normalize_sent_log_once(
        reference_time=later,
        calendar_occurrences=rows,
    )

    assert checker.sent_log["reminders_sent"] == {}
    assert key not in checker._occurrence_states
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("canonical_at", "canonical_state", "legacy_at", "expected_at", "expected_state"),
    (
        pytest.param(100.0, "suppressed_unknown", 200.0, 200.0, "sent", id="newer-old"),
        pytest.param(300.0, "suppressed_unknown", 200.0, 300.0, "suppressed_unknown", id="newer-canonical"),
        pytest.param(200.0, "suppressed_unknown", 200.0, 200.0, "suppressed_unknown", id="tie-canonical"),
    ),
)
async def test_canonical_and_old_collision_uses_newest_with_canonical_tie_break(
    tmp_path,
    canonical_at,
    canonical_state,
    legacy_at,
    expected_at,
    expected_state,
):
    coordinator = MutationCoordinator()
    due = NOW + timedelta(minutes=5)
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item(due_at=due),
    )
    checker, send = _checker(tmp_path, coordinator, calendar=calendar)
    recent_base = NOW.timestamp() - 60
    canonical_at = recent_base + canonical_at
    legacy_at = recent_base + legacy_at
    expected_at = recent_base + expected_at
    key = "calendar:cal-1:2026-07-15T12:05:00+02:00:due"
    checker.sent_log = {
        "reminders_sent": {
            key: {"state": canonical_state, "at": canonical_at},
            "cal-1:now": legacy_at,
        },
        "digest_log": {},
    }

    assert await checker.check_alerts_once(reference_time=NOW) == ()

    assert checker.sent_log["reminders_sent"] == {
        key: {"state": expected_state, "at": expected_at}
    }
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_colon_ids_fail_closed_without_send_state_or_persistence(tmp_path):
    coordinator = MutationCoordinator()
    calendar = _calendar_manager(
        tmp_path,
        coordinator,
        _calendar_item("cal:colon"),
    )
    reminders = _reminder_manager(
        tmp_path,
        coordinator,
        _reminder("rem:colon"),
    )
    checker, send = _checker(
        tmp_path,
        coordinator,
        calendar=calendar,
        reminders=reminders,
    )

    assert await checker.check_alerts_once(reference_time=NOW) == ()

    send.assert_not_awaited()
    assert checker._occurrence_states == {}
    assert checker.sent_log == {"reminders_sent": {}, "digest_log": {}}
    assert not checker.storage_path.exists()
