"""RED contracts for the one-pass reminder-checker cycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from cal_system.calendar_manager import CalendarSyncResult
from cal_system.reminder_checker import ReminderChecker


OSLO = ZoneInfo("Europe/Oslo")
REFERENCE = datetime(2026, 7, 15, 10, 0, tzinfo=OSLO)


class _MutableClock:
    def __init__(self, value: datetime):
        self.value = value
        self.now_calls = 0

    def now(self) -> datetime:
        self.now_calls += 1
        return self.value

    def epoch(self) -> float:
        raise AssertionError("cycle code must never read clock.epoch()")


def _checker(tmp_path, *, calendar=None, reminders=None, clock=None, sleep=None):
    return ReminderChecker(
        calendar_manager=calendar,
        reminder_manager=reminders,
        storage_path=tmp_path / "sent.json",
        clock=clock or _MutableClock(REFERENCE),
        sleep_func=sleep or AsyncMock(),
        interval_seconds=60.0,
    )


def _stub_delivery_phases(checker: ReminderChecker) -> None:
    checker.check_alerts_once = AsyncMock(return_value=())
    checker.check_morning_digest = AsyncMock(return_value=None)


def _stub_legacy_loop_phases(checker: ReminderChecker) -> None:
    checker.check_upcoming_30min = AsyncMock()
    checker.check_event_now = AsyncMock()
    checker.check_event_passed = AsyncMock()
    checker.check_morning_digest = AsyncMock()


@pytest.mark.asyncio
async def test_check_once_reuses_supplied_reference_across_every_phase(tmp_path):
    clock = _MutableClock(REFERENCE + timedelta(days=1))
    diagnostics = Mock(
        return_value={
            "malformed_legacy_due_at": 0,
            "legacy_due_mismatch": 0,
        }
    )
    reminders = SimpleNamespace(snapshot_delivery_diagnostics=diagnostics)
    sync = AsyncMock(return_value=CalendarSyncResult(True, False))
    calendar = SimpleNamespace(gcal_enabled=True, sync_from_gcal_result=sync)
    checker = _checker(
        tmp_path,
        calendar=calendar,
        reminders=reminders,
        clock=clock,
    )
    _stub_delivery_phases(checker)
    checker._last_gcal_sync = REFERENCE.timestamp() - 900

    await checker.check_once(reference_time=REFERENCE)

    assert diagnostics.call_count == 1
    assert diagnostics.call_args.kwargs["reference_time"] is REFERENCE
    assert checker.check_alerts_once.await_args.kwargs["reference_time"] is REFERENCE
    assert checker.check_morning_digest.await_args.kwargs["reference_time"] is REFERENCE
    assert sync.await_args.kwargs["reference_time"] is REFERENCE
    assert clock.now_calls == 0


@pytest.mark.asyncio
async def test_gcal_cadence_baselines_then_uses_exact_failed_attempt_interval(
    tmp_path,
):
    sync = AsyncMock(
        side_effect=(
            CalendarSyncResult(False, False, error_code="external_read_failed"),
            CalendarSyncResult(True, False),
        )
    )
    calendar = SimpleNamespace(gcal_enabled=True, sync_from_gcal_result=sync)
    checker = _checker(tmp_path, calendar=calendar)
    _stub_delivery_phases(checker)

    for offset in (0, 899, 900, 1799, 1800):
        await checker.check_once(reference_time=REFERENCE + timedelta(seconds=offset))

    assert sync.await_count == 2
    sync_references = [
        call.kwargs["reference_time"] for call in sync.await_args_list
    ]
    assert sync_references == [
        REFERENCE + timedelta(seconds=900),
        REFERENCE + timedelta(seconds=1800),
    ]


@pytest.mark.asyncio
async def test_operational_gcal_failure_is_degraded_but_cycle_is_successful(
    tmp_path,
):
    sync = AsyncMock(
        return_value=CalendarSyncResult(
            False,
            False,
            error_code="external_read_failed",
        )
    )
    calendar = SimpleNamespace(gcal_enabled=True, sync_from_gcal_result=sync)
    checker = _checker(tmp_path, calendar=calendar)
    _stub_delivery_phases(checker)
    checker._last_gcal_sync = REFERENCE.timestamp() - 900

    await checker.check_once(reference_time=REFERENCE)

    health = checker.get_health()
    assert health["status"] == "degraded"
    assert health["last_check_at"] == REFERENCE.isoformat()
    assert health["last_success_at"] == REFERENCE.isoformat()
    assert health["last_error_at"] == REFERENCE.isoformat()
    assert health["last_error_code"] == "gcal_sync_error"
    assert health["consecutive_errors"] == 0
    assert health["stats"]["cycles"] == 1
    assert health["stats"]["gcal_sync_errors"] == 1


@pytest.mark.asyncio
async def test_uncaught_cycle_phase_records_error_then_next_cycle_recovers(tmp_path):
    checker = _checker(tmp_path)
    checker.check_alerts_once = AsyncMock(
        side_effect=(RuntimeError("SECRET_PHASE_DETAIL"), ())
    )
    checker.check_morning_digest = AsyncMock(return_value=None)

    await checker.check_once(reference_time=REFERENCE)

    failed = checker.get_health()
    assert failed["status"] == "degraded"
    assert failed["last_success_at"] is None
    assert failed["last_error_at"] == REFERENCE.isoformat()
    assert failed["last_error_code"] == "cycle_error"
    assert failed["consecutive_errors"] == 1
    assert "SECRET_PHASE_DETAIL" not in repr(failed)

    recovered_at = REFERENCE + timedelta(minutes=1)
    await checker.check_once(reference_time=recovered_at)

    recovered = checker.get_health()
    assert recovered["status"] == "ok"
    assert recovered["last_success_at"] == recovered_at.isoformat()
    assert recovered["last_error_code"] is None
    assert recovered["consecutive_errors"] == 0
    assert recovered["stats"]["cycles"] == 2
    assert recovered["stats"]["cycle_errors"] == 1


@pytest.mark.asyncio
async def test_get_health_computes_live_staleness_and_stop_clears_it(tmp_path):
    clock = _MutableClock(REFERENCE + timedelta(seconds=151))
    checker = _checker(tmp_path, clock=clock)
    checker.running = True
    checker._health_status = "ok"
    checker._last_check_at = REFERENCE.isoformat()
    checker._last_success_at = REFERENCE.isoformat()

    stale = checker.get_health()
    checker.stop()
    stopped = checker.get_health()

    assert stale["running"] is True
    assert stale["stale"] is True
    assert stale["status"] == "degraded"
    assert stopped["running"] is False
    assert stopped["stale"] is False
    assert stopped["status"] == "stopped"
    assert clock.now_calls == 1


@pytest.mark.asyncio
async def test_start_checks_immediately_then_uses_injected_interval_sleep(tmp_path):
    order = []
    checker = None

    async def sleep_once(seconds):
        order.append(("sleep", seconds))
        checker.stop()

    checker = _checker(tmp_path, sleep=sleep_once)
    checker.check_once = AsyncMock(side_effect=lambda: order.append(("check", None)))
    _stub_legacy_loop_phases(checker)

    await asyncio.wait_for(checker.start(), timeout=0.25)

    assert order == [("check", None), ("sleep", 60.0)]
    checker.check_once.assert_awaited_once_with()
    assert checker.running is False
    assert checker.get_health()["status"] == "stopped"


@pytest.mark.asyncio
async def test_start_cancellation_always_leaves_checker_stopped(tmp_path):
    sleep_entered = asyncio.Event()

    async def blocked_sleep(_seconds):
        sleep_entered.set()
        await asyncio.Future()

    checker = _checker(tmp_path, sleep=blocked_sleep)
    checker.check_once = AsyncMock(return_value=None)
    _stub_legacy_loop_phases(checker)
    task = asyncio.create_task(checker.start())
    try:
        await asyncio.wait_for(sleep_entered.wait(), timeout=0.25)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    health = checker.get_health()
    assert health["running"] is False
    assert health["stale"] is False
    assert health["status"] == "stopped"


@pytest.mark.asyncio
async def test_legacy_wrappers_capture_once_and_only_forward_unified_alerts(tmp_path):
    clock = _MutableClock(REFERENCE)
    checker = _checker(tmp_path, clock=clock)
    checker.check_alerts_once = AsyncMock(return_value=())
    checker._send_item_reminder = AsyncMock()
    checker._send_reminder_remind = AsyncMock()

    await checker.check_upcoming_30min()
    await checker.check_event_now()
    await checker.check_event_passed()

    assert clock.now_calls == 3
    assert checker.check_alerts_once.await_count == 3
    for call in checker.check_alerts_once.await_args_list:
        assert call.args == ()
        assert set(call.kwargs) == {"reference_time"}
        assert call.kwargs["reference_time"] is REFERENCE
        assert "passed" not in repr(call)
    checker._send_item_reminder.assert_not_awaited()
    checker._send_reminder_remind.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_once_captures_once_and_naive_reference_has_zero_side_effects(
    tmp_path,
):
    clock = _MutableClock(REFERENCE)
    diagnostics = Mock(return_value={})
    checker = _checker(
        tmp_path,
        reminders=SimpleNamespace(
            snapshot_delivery_diagnostics=diagnostics
        ),
        clock=clock,
    )
    _stub_delivery_phases(checker)

    await checker.check_once()

    captured = diagnostics.call_args.kwargs["reference_time"]
    assert clock.now_calls == 1
    assert checker.check_alerts_once.await_args.kwargs["reference_time"] is captured
    assert checker.check_morning_digest.await_args.kwargs["reference_time"] is captured

    invalid = _checker(tmp_path / "invalid", clock=clock)
    _stub_delivery_phases(invalid)
    with pytest.raises(ValueError, match="^reference_time_must_be_aware$"):
        await invalid.check_once(reference_time=datetime(2026, 7, 15, 10, 0))
    assert invalid.stats["cycles"] == 0
    assert invalid.get_health()["last_check_at"] is None
    invalid.check_alerts_once.assert_not_awaited()
    invalid.check_morning_digest.assert_not_awaited()
    assert clock.now_calls == 1

    non_datetime_clock = _MutableClock("SECRET_NOT_A_DATETIME")
    non_datetime = _checker(
        tmp_path / "non-datetime",
        clock=non_datetime_clock,
    )
    _stub_delivery_phases(non_datetime)
    with pytest.raises(ValueError, match="^reference_time_must_be_aware$"):
        await non_datetime.check_once()
    assert non_datetime_clock.now_calls == 1
    assert "SECRET_NOT_A_DATETIME" not in repr(non_datetime.get_health())


@pytest.mark.asyncio
async def test_diagnostics_add_only_exact_nonnegative_integer_counters(tmp_path):
    diagnostics = Mock(
        side_effect=(
            {
                "malformed_legacy_due_at": 2,
                "legacy_due_mismatch": 3,
                "cycle_errors": 999,
            },
            {
                "malformed_legacy_due_at": True,
                "legacy_due_mismatch": -1,
            },
            {"malformed_legacy_due_at": 4.0},
        )
    )
    checker = _checker(
        tmp_path,
        reminders=SimpleNamespace(
            snapshot_delivery_diagnostics=diagnostics
        ),
    )
    _stub_delivery_phases(checker)

    for offset in range(3):
        await checker.check_once(
            reference_time=REFERENCE + timedelta(minutes=offset)
        )

    assert checker.stats["malformed_legacy_due_at"] == 2
    assert checker.stats["legacy_due_mismatch"] == 3
    assert checker.stats["cycle_errors"] == 0
    assert diagnostics.call_count == 3


@pytest.mark.asyncio
async def test_gcal_dynamic_enable_baseline_and_getter_failure_backoff(tmp_path):
    structured = AsyncMock(return_value=SimpleNamespace(ok=True))
    legacy = AsyncMock()
    calendar = SimpleNamespace(
        gcal_enabled=False,
        sync_from_gcal_result=structured,
        sync_from_gcal=legacy,
    )
    checker = _checker(tmp_path, calendar=calendar)
    _stub_delivery_phases(checker)

    await checker.check_once(reference_time=REFERENCE)
    calendar.gcal_enabled = True
    await checker.check_once(reference_time=REFERENCE + timedelta(seconds=1))
    await checker.check_once(reference_time=REFERENCE + timedelta(seconds=901))

    structured.assert_awaited_once()
    assert structured.await_args.kwargs["reference_time"] == (
        REFERENCE + timedelta(seconds=901)
    )
    legacy.assert_not_awaited()

    class FailingEnabled:
        def __init__(self):
            self.calls = 0

        @property
        def gcal_enabled(self):
            self.calls += 1
            raise RuntimeError("SECRET_GCAL_PROPERTY")

    failing_calendar = FailingEnabled()
    failing = _checker(tmp_path / "failing", calendar=failing_calendar)
    _stub_delivery_phases(failing)
    for seconds in (0, 899, 900):
        await failing.check_once(
            reference_time=REFERENCE + timedelta(seconds=seconds)
        )
    assert failing_calendar.calls == 2
    assert failing.stats["gcal_sync_errors"] == 2
    assert "SECRET_GCAL_PROPERTY" not in repr(failing.get_health())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ("missing", "malformed", "raised"))
async def test_gcal_failures_are_bounded_and_never_use_legacy_sync(
    tmp_path,
    failure_mode,
):
    legacy = AsyncMock()
    calendar = SimpleNamespace(gcal_enabled=True, sync_from_gcal=legacy)
    structured = None
    if failure_mode == "malformed":
        structured = AsyncMock(return_value=SimpleNamespace(ok=1))
        calendar.sync_from_gcal_result = structured
    elif failure_mode == "raised":
        structured = AsyncMock(
            side_effect=RuntimeError("SECRET_GCAL_FAILURE")
        )
        calendar.sync_from_gcal_result = structured
    checker = _checker(tmp_path, calendar=calendar)
    _stub_delivery_phases(checker)
    checker._last_gcal_sync = REFERENCE.timestamp() - 900

    await checker.check_once(reference_time=REFERENCE)

    health = checker.get_health()
    assert health["status"] == "degraded"
    assert health["last_success_at"] == REFERENCE.isoformat()
    assert health["last_error_code"] == "gcal_sync_error"
    assert health["stats"]["gcal_sync_errors"] == 1
    assert "SECRET_GCAL_FAILURE" not in repr(health)
    if structured is not None:
        structured.assert_awaited_once_with(reference_time=REFERENCE)
    legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_overlapping_gcal_cycles_stamp_before_await_and_sync_once(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_sync(*, reference_time):
        entered.set()
        await release.wait()
        return SimpleNamespace(ok=True)

    sync = AsyncMock(side_effect=blocked_sync)
    checker = _checker(
        tmp_path,
        calendar=SimpleNamespace(
            gcal_enabled=True,
            sync_from_gcal_result=sync,
        ),
    )
    _stub_delivery_phases(checker)
    checker._last_gcal_sync = REFERENCE.timestamp() - 900
    first = asyncio.create_task(checker.check_once(reference_time=REFERENCE))
    try:
        await asyncio.wait_for(entered.wait(), timeout=0.25)
        await checker.check_once(reference_time=REFERENCE)
        assert sync.await_count == 1
        assert checker._last_gcal_sync == REFERENCE.timestamp()
    finally:
        release.set()
        await asyncio.wait_for(first, timeout=0.25)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", ("delivery_failure", "storage_error"))
async def test_operational_delivery_errors_degrade_then_recover_cleanly(
    tmp_path,
    error_code,
):
    checker = _checker(tmp_path)

    async def degraded_alerts(*, reference_time):
        checker._record_bounded_error(
            error_code,
            reference_time=reference_time,
        )
        return ()

    checker.check_alerts_once = AsyncMock(side_effect=degraded_alerts)
    checker.check_morning_digest = AsyncMock(return_value=None)
    await checker.check_once(reference_time=REFERENCE)
    degraded = checker.get_health()
    assert degraded["status"] == "degraded"
    assert degraded["last_error_code"] == error_code
    assert degraded["last_success_at"] == REFERENCE.isoformat()

    checker.check_alerts_once = AsyncMock(return_value=())
    recovered_at = REFERENCE + timedelta(minutes=1)
    await checker.check_once(reference_time=recovered_at)
    recovered = checker.get_health()
    assert recovered["status"] == "ok"
    assert recovered["last_error_code"] is None
    assert recovered["last_error_at"] == REFERENCE.isoformat()
    assert recovered["last_success_at"] == recovered_at.isoformat()


def test_health_staleness_is_exact_live_utc_and_fail_bounded(tmp_path):
    clock = _MutableClock(REFERENCE + timedelta(seconds=150))
    checker = _checker(tmp_path, clock=clock)
    checker.running = True
    checker._health_status = "ok"
    checker._last_success_at = REFERENCE.astimezone(timezone.utc).isoformat()

    assert checker.get_health()["stale"] is False
    clock.value = REFERENCE + timedelta(seconds=150, microseconds=1)
    assert checker.get_health()["status"] == "degraded"
    clock.value = REFERENCE + timedelta(seconds=149)
    recovered = checker.get_health()
    assert recovered["stale"] is False
    assert recovered["status"] == "ok"

    checker._last_success_at = "SECRET_MALFORMED_BASELINE"
    malformed = checker.get_health()
    assert malformed["stale"] is True
    assert malformed["last_success_at"] is None
    assert "SECRET_MALFORMED_BASELINE" not in repr(malformed)

    checker.stats["cycles"] = True
    checker.stats["delivery_failures"] = -1
    checker.stats["SECRET_STATS_KEY"] = "SECRET_STATS_VALUE"
    bounded_stats = checker.get_health()["stats"]
    assert set(bounded_stats) == {
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
    }
    assert bounded_stats["cycles"] == 0
    assert bounded_stats["delivery_failures"] == 0
    assert "SECRET_STATS" not in repr(bounded_stats)

    class FailingClock:
        def now(self):
            raise RuntimeError("SECRET_CLOCK_FAILURE")

    failing = _checker(tmp_path / "clock", clock=FailingClock())
    failing.running = True
    failing._health_status = "ok"
    failing._last_success_at = REFERENCE.isoformat()
    bounded = failing.get_health()
    assert bounded["stale"] is True
    assert bounded["status"] == "degraded"
    assert "SECRET_CLOCK_FAILURE" not in repr(bounded)

    checker.running = "SECRET_RUNNING_SENTINEL"
    bounded_running = checker.get_health()
    assert bounded_running["running"] is False
    assert "SECRET_RUNNING_SENTINEL" not in repr(bounded_running)


@pytest.mark.asyncio
async def test_private_passed_alias_uses_due_copy_not_a_third_family(tmp_path):
    checker = _checker(tmp_path)
    checker._send_mentions_item = AsyncMock(
        return_value=SimpleNamespace(state="delivered")
    )

    await checker._send_item_reminder(
        {"title": "Møte", "time": "10:00", "channel_id": "42"},
        "passed",
    )
    await checker._send_reminder_remind(
        {"text": "Ring legen", "channel_id": "42"},
        "passed",
    )

    messages = [call.args[2] for call in checker._send_mentions_item.await_args_list]
    assert "Starter nå" in messages[0]
    assert "**Nå:" in messages[1]
    assert all("ferdig" not in message.casefold() for message in messages)


@pytest.mark.asyncio
async def test_start_cancellation_during_check_always_stops(tmp_path):
    entered = asyncio.Event()

    async def blocked_check():
        entered.set()
        await asyncio.Future()

    checker = _checker(tmp_path)
    checker.check_once = AsyncMock(side_effect=blocked_check)
    task = asyncio.create_task(checker.start())
    await asyncio.wait_for(entered.wait(), timeout=0.25)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert checker.get_health()["status"] == "stopped"
    checker.sleep_func.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_during_check_skips_sleep_and_stop_is_idempotent(tmp_path):
    checker = _checker(tmp_path)

    async def stop_during_check():
        checker.stop()

    checker.check_once = AsyncMock(side_effect=stop_during_check)
    await checker.start()
    checker.stop()
    checker.stop()

    checker.check_once.assert_awaited_once_with()
    checker.sleep_func.assert_not_awaited()
    assert checker.get_health()["status"] == "stopped"


def test_find_digest_channel_forwards_reference_without_coercion(tmp_path):
    class HostileChannel:
        def __init__(self):
            self.int_calls = 0

        def __int__(self):
            self.int_calls += 1
            return 99

    hostile = HostileChannel()
    calendar = SimpleNamespace(
        get_upcoming=Mock(
            return_value=(
                "SECRET_NON_DICT_ROW",
                {"channel_id": hostile},
                {"channel_id": "42"},
            )
        )
    )
    clock = _MutableClock(REFERENCE + timedelta(days=1))
    checker = _checker(tmp_path, calendar=calendar, clock=clock)

    channel_id = checker._find_digest_channel(
        "shared",
        reference_time=REFERENCE,
    )

    assert channel_id == 42
    assert hostile.int_calls == 0
    calendar.get_upcoming.assert_called_once_with(
        "shared",
        days=1,
        reference_time=REFERENCE,
    )
    assert clock.now_calls == 0
