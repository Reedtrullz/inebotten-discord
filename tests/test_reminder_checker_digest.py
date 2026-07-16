"""RED contract tests for the typed morning-digest delivery path."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

import cal_system.reminder_checker as checker_module
from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_checker import ReminderChecker
from core.dispatch_result import DeliveryState, MessageSendResult
from core.mutation_coordinator import MutationCoordinator


OSLO = ZoneInfo("Europe/Oslo")
MORNING = datetime(2026, 7, 15, 9, 15, tzinfo=OSLO)


class _ExplodingClock:
    def now(self):
        raise AssertionError("supplied digest reference must be reused")

    def epoch(self):
        raise AssertionError("digest must not read clock.epoch()")


class _DigestCalendar:
    def __init__(self, rows=()):
        self.rows = tuple(copy.deepcopy(rows))
        self.snapshot_calls = 0
        self.references = []

    def snapshot_pending_items(self, *, reference_time):
        self.snapshot_calls += 1
        self.references.append(reference_time)
        return tuple(copy.deepcopy(self.rows))


def _item(
    title: str,
    *,
    reference_time: datetime = MORNING,
    day_offset: int = 0,
    time_value: str | None = "11:00",
    channel_id: object = "99",
    item_id: str | None = None,
):
    local_day = reference_time.astimezone(OSLO) + timedelta(days=day_offset)
    return {
        "id": item_id or title.lower().replace(" ", "-"),
        "title": title,
        "date": local_day.strftime("%d.%m.%Y"),
        "time": time_value,
        "completed": False,
        "delete_pending": False,
        "channel_id": channel_id,
        "user_id": "42",
        "username": "Testbruker",
    }


def _checker(
    tmp_path,
    calendar,
    *,
    send=None,
    get_channel=None,
    coordinator=None,
):
    send = send or AsyncMock()
    if get_channel is None:
        get_channel = Mock(return_value=SimpleNamespace(send=send))
    checker = ReminderChecker(
        calendar_manager=calendar,
        get_channel_func=get_channel,
        storage_path=tmp_path / "sent.json",
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator or MutationCoordinator(),
    )
    return checker, send, get_channel


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference_time", "expected_snapshots"),
    (
        (datetime(2026, 7, 15, 8, 59, 59, tzinfo=OSLO), 0),
        (datetime(2026, 7, 15, 7, 0, 0, tzinfo=timezone.utc), 1),
        (datetime(2026, 7, 15, 9, 59, 59, tzinfo=OSLO), 1),
        (datetime(2026, 7, 15, 10, 0, 0, tzinfo=OSLO), 0),
    ),
)
async def test_digest_uses_exact_oslo_window_and_one_supplied_reference(
    tmp_path,
    reference_time,
    expected_snapshots,
):
    calendar = _DigestCalendar()
    checker, send, _ = _checker(tmp_path, calendar)

    await checker.check_morning_digest(reference_time=reference_time)

    assert calendar.snapshot_calls == expected_snapshots
    assert calendar.references == [reference_time] * expected_snapshots
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_digest_filters_today_and_chooses_first_valid_today_channel(tmp_path):
    calendar = _DigestCalendar(
        (
            _item("I går", day_offset=-1, channel_id="11"),
            _item("I dag uten kanal", channel_id=None),
            _item("I dag med kanal", channel_id="22"),
            _item("I morgen", day_offset=1, channel_id="33"),
        )
    )
    checker, send, get_channel = _checker(tmp_path, calendar)

    await checker.check_morning_digest(reference_time=MORNING)

    get_channel.assert_called_once_with(22)
    send.assert_awaited_once()
    message = send.await_args.args[0]
    assert "I dag uten kanal" in message
    assert "I dag med kanal" in message
    assert "I går" not in message
    assert "I morgen" not in message
    assert calendar.references == [MORNING]


@pytest.mark.asyncio
async def test_delivered_digest_records_exact_date_time_count_and_safe_send(tmp_path):
    calendar = _DigestCalendar((_item("Legetime"),))
    checker, send, _ = _checker(tmp_path, calendar)

    await checker.check_morning_digest(reference_time=MORNING)

    assert checker.sent_log["digest_log"] == {
        "2026-07-15": {"state": "sent", "at": MORNING.timestamp()}
    }
    assert checker.stats["digest_sent"] == 1
    send.assert_awaited_once()
    kwargs = send.await_args.kwargs
    allowed_mentions = kwargs["allowed_mentions"]
    assert allowed_mentions.users is False
    assert allowed_mentions.roles is False
    assert allowed_mentions.everyone is False
    assert allowed_mentions.replied_user is False
    assert kwargs["suppress_embeds"] is True
    assert json.loads(checker.storage_path.read_text(encoding="utf-8")) == (
        checker.sent_log
    )


@pytest.mark.asyncio
async def test_definite_digest_failure_retries_without_write_or_prune(tmp_path):
    calendar = _DigestCalendar((_item("Legetime"),))
    get_channel = Mock(return_value=None)
    checker, send, _ = _checker(
        tmp_path,
        calendar,
        get_channel=get_channel,
    )
    exact_cutoff = MORNING.timestamp() - 30 * 24 * 60 * 60
    checker.sent_log["digest_log"] = {
        "2026-06-15": {"state": "sent", "at": exact_cutoff}
    }

    await checker.check_morning_digest(reference_time=MORNING)

    assert checker.sent_log["digest_log"] == {
        "2026-06-15": {"state": "sent", "at": exact_cutoff}
    }
    assert checker.stats["digest_sent"] == 0
    assert not checker.storage_path.exists()
    send.assert_not_awaited()

    get_channel.return_value = SimpleNamespace(send=send)
    await checker.check_morning_digest(reference_time=MORNING)

    send.assert_awaited_once()
    assert checker.sent_log["digest_log"]["2026-07-15"] == {
        "state": "sent",
        "at": MORNING.timestamp(),
    }


@pytest.mark.asyncio
async def test_digest_without_canonical_today_channel_is_definite_and_retryable(
    tmp_path,
):
    calendar = _DigestCalendar(
        (
            _item("Uten kanal", channel_id=None),
            _item("Ugyldig kanal", channel_id="not-a-channel"),
        )
    )
    checker, send, get_channel = _checker(tmp_path, calendar)

    first = await checker.check_morning_digest(reference_time=MORNING)
    second = await checker.check_morning_digest(reference_time=MORNING)

    assert first == second == MessageSendResult(
        DeliveryState.NOT_DELIVERED,
        "missing_channel",
    )
    send.assert_not_awaited()
    get_channel.assert_not_called()
    assert checker.stats["skipped_missing_channel"] == 2
    assert checker.stats["delivery_failures"] == 2
    assert checker.get_health()["last_error_code"] == "delivery_failure"
    assert checker.sent_log["digest_log"] == {}
    assert not checker.storage_path.exists()


@pytest.mark.asyncio
async def test_unknown_digest_delivery_is_suppressed_without_blind_retry(tmp_path):
    calendar = _DigestCalendar((_item("Legetime"),))
    send = AsyncMock(side_effect=RuntimeError("uncertain transport"))
    checker, _, _ = _checker(tmp_path, calendar, send=send)

    await checker.check_morning_digest(reference_time=MORNING)
    await checker.check_morning_digest(reference_time=MORNING)

    send.assert_awaited_once()
    assert checker.sent_log["digest_log"] == {
        "2026-07-15": {
            "state": "suppressed_unknown",
            "at": MORNING.timestamp(),
        }
    }
    assert checker.stats["digest_sent"] == 0


@pytest.mark.asyncio
async def test_overlapping_digest_cycles_publish_one_claim_and_send_once(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(*_args, **_kwargs):
        started.set()
        await release.wait()

    calendar = _DigestCalendar((_item("Legetime"),))
    send = AsyncMock(side_effect=blocked_send)
    checker, _, _ = _checker(tmp_path, calendar, send=send)

    first = asyncio.create_task(
        checker.check_morning_digest(reference_time=MORNING)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    second = asyncio.create_task(
        checker.check_morning_digest(reference_time=MORNING)
    )
    await asyncio.wait_for(second, timeout=1)
    assert not first.done()
    release.set()
    await asyncio.wait_for(first, timeout=1)

    send.assert_awaited_once()
    assert checker.sent_log["digest_log"]["2026-07-15"]["state"] == "sent"


@pytest.mark.asyncio
async def test_digest_timeout_is_hard_and_terminal_when_child_resists_cancel(
    tmp_path,
    monkeypatch,
):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def cancellation_resistant_send(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    monkeypatch.setattr(checker_module, "ALERT_SEND_TIMEOUT_SECONDS", 0.01)
    calendar = _DigestCalendar((_item("Legetime"),))
    send = AsyncMock(side_effect=cancellation_resistant_send)
    checker, _, _ = _checker(tmp_path, calendar, send=send)

    await asyncio.wait_for(
        checker.check_morning_digest(reference_time=MORNING),
        timeout=0.5,
    )
    await asyncio.wait_for(cancelled.wait(), timeout=0.5)
    await checker.check_morning_digest(reference_time=MORNING)

    send.assert_awaited_once()
    assert checker.sent_log["digest_log"]["2026-07-15"] == {
        "state": "suppressed_unknown",
        "at": MORNING.timestamp(),
    }

    release.set()
    for _ in range(100):
        if not checker._owned_send_tasks:
            break
        await asyncio.sleep(0)
    assert not checker._owned_send_tasks


@pytest.mark.asyncio
async def test_cancelled_digest_waits_for_attempt_then_suppresses_and_reraises(
    tmp_path,
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_send(*_args, **_kwargs):
        started.set()
        await release.wait()

    calendar = _DigestCalendar((_item("Legetime"),))
    send = AsyncMock(side_effect=blocked_send)
    checker, _, _ = _checker(tmp_path, calendar, send=send)
    cycle = asyncio.create_task(
        checker.check_morning_digest(reference_time=MORNING)
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    cycle.cancel()
    await asyncio.sleep(0)
    assert not cycle.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(cycle, timeout=1)

    assert checker.sent_log["digest_log"]["2026-07-15"] == {
        "state": "suppressed_unknown",
        "at": MORNING.timestamp(),
    }
    await checker.check_morning_digest(reference_time=MORNING)
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_digest", "expected_record"),
    (
        pytest.param(
            {
                "2026-07-15": {
                    "state": "suppressed_unknown",
                    "at": MORNING.timestamp() - 120,
                },
                "shared:99": "2026-07-15",
            },
            {
                "state": "suppressed_unknown",
                "at": MORNING.timestamp() - 120,
            },
            id="canonical",
        ),
        pytest.param(
            {"2026-07-15": MORNING.timestamp() - 60},
            {"state": "sent", "at": MORNING.timestamp() - 60},
            id="canonical-numeric",
        ),
        pytest.param(
            {"shared:99": "2026-07-15"},
            {
                "state": "sent",
                "at": datetime(2026, 7, 15, 9, 0, tzinfo=OSLO).timestamp(),
            },
            id="legacy-channel-date",
        ),
        pytest.param(
            {"123:99": "2026-07-15"},
            {
                "state": "sent",
                "at": datetime(2026, 7, 15, 9, 0, tzinfo=OSLO).timestamp(),
            },
            id="legacy-snowflake-scope-date",
        ),
    ),
)
async def test_digest_schema_normalizes_lazily_without_eager_rewrite(
    tmp_path,
    raw_digest,
    expected_record,
):
    path = tmp_path / "sent.json"
    path.write_text(
        json.dumps({"reminders_sent": {}, "digest_log": raw_digest}),
        encoding="utf-8",
    )
    before = path.read_bytes()
    calendar = _DigestCalendar((_item("Legetime"),))
    checker, send, _ = _checker(tmp_path, calendar)
    await checker.setup()

    await checker.check_morning_digest(reference_time=MORNING)

    send.assert_not_awaited()
    assert checker.sent_log["digest_log"] == {
        "2026-07-15": expected_record
    }
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_invalid_digest_keys_and_records_are_discarded_without_rewrite(
    tmp_path,
):
    calendar = _DigestCalendar()
    checker, send, _ = _checker(tmp_path, calendar)
    checker.sent_log = {
        "reminders_sent": {},
        "digest_log": {
            "2026-02-30": {"state": "sent", "at": 1},
            "2026-07-14": {"state": "other", "at": 1},
            "2026-07-13": {"state": "sent", "at": True},
            "2026-07-12": {"state": "sent", "at": float("nan")},
            "2026-07-11": {"state": "sent", "at": -1},
            "2026-07-10": {"state": "sent", "at": 1, "extra": True},
            "shared:99": "not-a-date",
            "shared:98": "1960-01-01",
            "0123:99": "2026-07-15",
            "shared:099": "2026-07-15",
            "not-a-key": [],
        },
    }

    await checker.check_morning_digest(reference_time=MORNING)

    assert checker.sent_log["digest_log"] == {}
    send.assert_not_awaited()
    assert not checker.storage_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_date", ("0001-01-01", "1900-01-01"))
async def test_pre_epoch_legacy_digest_date_is_discarded_without_eager_write(
    tmp_path,
    legacy_date,
):
    path = tmp_path / "sent.json"
    path.write_text(
        json.dumps(
            {
                "reminders_sent": {},
                "digest_log": {"shared:99": legacy_date},
            }
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    calendar = _DigestCalendar()
    checker, send, _ = _checker(tmp_path, calendar)
    await checker.setup()

    await checker.check_morning_digest(reference_time=MORNING)

    assert checker.sent_log["digest_log"] == {}
    assert path.read_bytes() == before
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_digest_terminal_write_prunes_exact_thirty_day_cutoff(tmp_path):
    reference_time = datetime(2026, 7, 31, 9, 30, tzinfo=OSLO)
    cutoff = reference_time.timestamp() - 30 * 24 * 60 * 60
    calendar = _DigestCalendar(
        (_item("Legetime", reference_time=reference_time),)
    )
    checker, send, _ = _checker(tmp_path, calendar)
    checker.sent_log["digest_log"] = {
        "2026-06-29": {"state": "sent", "at": cutoff - 1},
        "2026-06-30": {"state": "sent", "at": cutoff},
        "2026-07-01": {
            "state": "suppressed_unknown",
            "at": cutoff + 0.001,
        },
        "2026-07-31": {"state": "sent", "at": cutoff},
    }

    await checker.check_morning_digest(reference_time=reference_time)

    send.assert_awaited_once()
    assert set(checker.sent_log["digest_log"]) == {
        "2026-07-01",
        "2026-07-31",
    }
    assert checker.sent_log["digest_log"]["2026-07-31"] == {
        "state": "sent",
        "at": reference_time.timestamp(),
    }


@pytest.mark.asyncio
async def test_digest_storage_failure_keeps_process_local_suppression(
    tmp_path,
    monkeypatch,
):
    def fail_write(*_args, **_kwargs):
        raise OSError("private storage detail")

    monkeypatch.setattr(checker_module, "write_json_atomic", fail_write)
    calendar = _DigestCalendar((_item("Legetime"),))
    checker, send, _ = _checker(tmp_path, calendar)

    await checker.check_morning_digest(reference_time=MORNING)
    await checker.check_morning_digest(reference_time=MORNING)

    send.assert_awaited_once()
    assert checker.sent_log["digest_log"]["2026-07-15"] == {
        "state": "sent",
        "at": MORNING.timestamp(),
    }
    assert checker._sent_log_dirty is True
    assert checker.get_health()["last_error_code"] == "storage_error"


@pytest.mark.asyncio
async def test_direct_digest_write_never_persists_raw_reminder_record(tmp_path):
    coordinator = MutationCoordinator()
    calendar = CalendarManager(
        tmp_path / "calendar.json",
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    calendar.items = {
        calendar.SHARED_KEY: [
            _item(
                "Legetime",
                time_value="08:00",
                item_id="existing",
            )
        ]
    }
    checker, send, _ = _checker(
        tmp_path,
        calendar,
        coordinator=coordinator,
    )
    reminder_key = "calendar:existing:2026-07-15T08:00:00+02:00:due"
    checker.sent_log = {
        "reminders_sent": {"existing:now": MORNING.timestamp()},
        "digest_log": {},
    }

    await checker.check_morning_digest(reference_time=MORNING)

    send.assert_awaited_once()
    persisted = json.loads(checker.storage_path.read_text(encoding="utf-8"))
    assert persisted["reminders_sent"] == {
        reminder_key: {"state": "sent", "at": MORNING.timestamp()}
    }
    assert "existing:now" not in persisted["reminders_sent"]


@pytest.mark.asyncio
async def test_concurrent_alert_and_digest_settlements_preserve_both_logs(tmp_path):
    coordinator = MutationCoordinator()
    calendar = CalendarManager(
        tmp_path / "calendar.json",
        clock=_ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    calendar.items = {
        calendar.SHARED_KEY: [
            _item(
                "Samtidig",
                reference_time=MORNING,
                time_value="09:15",
                item_id="both",
            )
        ]
    }
    send = AsyncMock()
    checker, _, _ = _checker(
        tmp_path,
        calendar,
        send=send,
        coordinator=coordinator,
    )

    digest_attempt = checker.check_morning_digest(reference_time=MORNING)
    alert_attempt = checker.check_alerts_once(reference_time=MORNING)
    alert_results, _ = await asyncio.gather(alert_attempt, digest_attempt)

    assert len(alert_results) == 1
    assert send.await_count == 2
    reminder_key = "calendar:both:2026-07-15T09:15:00+02:00:due"
    assert checker.sent_log["reminders_sent"][reminder_key] == {
        "state": "sent",
        "at": MORNING.timestamp(),
    }
    assert checker.sent_log["digest_log"]["2026-07-15"] == {
        "state": "sent",
        "at": MORNING.timestamp(),
    }
    assert json.loads(checker.storage_path.read_text(encoding="utf-8")) == (
        checker.sent_log
    )
