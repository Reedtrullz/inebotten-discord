"""Focused runtime boundaries for ReminderChecker delivery adapters."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import discord
import pytest

from cal_system.reminder_checker import ReminderChecker, select_alert_kind
from core.dispatch_result import DeliveryState, MessageSendResult


OSLO = ZoneInfo("Europe/Oslo")
EXPECTED_STATS = {
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


class _Response:
    reason = "bounded-test"
    headers = {}

    def __init__(self, status: int):
        self.status = status


class _CountingClock:
    def __init__(self, value: datetime):
        self.value = value
        self.now_calls = 0

    def now(self) -> datetime:
        self.now_calls += 1
        return self.value

    def epoch(self) -> float:
        raise AssertionError("checker must not read clock.epoch()")


class _HostileChannelId:
    def __init__(self):
        self.int_calls = 0

    def __int__(self) -> int:
        self.int_calls += 1
        return 42


@pytest.mark.parametrize(
    ("delta", "expected"),
    (
        (timedelta(minutes=35), "warning_30m"),
        (timedelta(minutes=25), None),
        (timedelta(minutes=1), "due"),
        (timedelta(0), "due"),
        (-timedelta(minutes=10), "due"),
        (-timedelta(minutes=10, seconds=1), None),
    ),
)
def test_select_alert_kind_has_exact_non_overlapping_boundaries(delta, expected):
    assert select_alert_kind(delta) == expected


def test_constructor_injects_runtime_dependencies_and_bounded_health(tmp_path):
    clock = _CountingClock(datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc))
    coordinator = object()
    sleep_func = AsyncMock()

    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        clock=clock,
        mutation_coordinator=coordinator,
        sleep_func=sleep_func,
        interval_seconds=2.5,
    )

    assert checker.clock is clock
    assert checker.mutation_coordinator is coordinator
    assert checker.sleep_func is sleep_func
    assert checker.interval_seconds == 2.5
    assert set(checker.stats) == EXPECTED_STATS
    assert all(value == 0 for value in checker.stats.values())
    assert checker.get_health() == {
        "status": "starting",
        "running": False,
        "stale": False,
        "last_check_at": None,
        "last_success_at": None,
        "last_error_at": None,
        "last_error_code": None,
        "consecutive_errors": 0,
        "stats": {key: 0 for key in checker.stats},
    }
    assert clock.now_calls == 0


def test_capture_reference_time_reads_one_aware_value_and_converts_to_oslo(tmp_path):
    instant = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
    clock = _CountingClock(instant)
    checker = ReminderChecker(storage_path=tmp_path / "sent.json", clock=clock)

    reference_time = checker._capture_reference_time()

    assert reference_time == datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)
    assert reference_time.tzinfo is OSLO
    assert clock.now_calls == 1


def test_capture_reference_time_rejects_naive_clock_value(tmp_path):
    clock = _CountingClock(datetime(2026, 7, 15, 10, 0))
    checker = ReminderChecker(storage_path=tmp_path / "sent.json", clock=clock)

    with pytest.raises(ValueError, match="^reference_time_must_be_aware$"):
        checker._capture_reference_time()

    assert clock.now_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("channel_id", (None, ""))
async def test_send_to_channel_reports_missing_without_touching_adapters(
    tmp_path,
    channel_id,
):
    get_channel = Mock()
    fallback = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        channel_id,
        "hei",
        allowed_mentions=discord.AllowedMentions.none(),
    )

    assert result == MessageSendResult(DeliveryState.NOT_DELIVERED, "missing_channel")
    assert checker.stats["skipped_missing_channel"] == 1
    get_channel.assert_not_called()
    fallback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel_id",
    (
        0,
        -1,
        True,
        False,
        2**64,
        "abc",
        "-42",
        42.0,
        Decimal("42"),
        pytest.param("9" * 1_000, id="oversized-decimal"),
    ),
)
async def test_send_to_channel_rejects_noncanonical_ids_before_adapters(
    tmp_path,
    channel_id,
):
    get_channel = Mock()
    fallback = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        channel_id,
        "hei",
        allowed_mentions=discord.AllowedMentions.none(),
    )

    assert result == MessageSendResult(DeliveryState.NOT_DELIVERED, "invalid_channel")
    assert checker.stats["skipped_missing_channel"] == 0
    get_channel.assert_not_called()
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_to_channel_never_coerces_attacker_controlled_id(tmp_path):
    hostile = _HostileChannelId()
    get_channel = Mock()
    fallback = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        hostile,
        "hei",
        allowed_mentions=discord.AllowedMentions.none(),
    )

    assert result == MessageSendResult(DeliveryState.NOT_DELIVERED, "invalid_channel")
    assert hostile.int_calls == 0
    get_channel.assert_not_called()
    fallback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel_id", (42, " 42 "))
async def test_send_to_channel_direct_delivery_reuses_one_normalized_id(
    tmp_path,
    channel_id,
):
    send = AsyncMock()
    get_channel = Mock(return_value=SimpleNamespace(send=send))
    fallback = AsyncMock()
    allowed_mentions = object()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        channel_id,
        "hei",
        allowed_mentions=allowed_mentions,
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    get_channel.assert_called_once_with(42)
    send.assert_awaited_once_with(
        "hei",
        allowed_mentions=allowed_mentions,
        suppress_embeds=True,
    )
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_to_channel_uses_fallback_with_hardened_kwargs(tmp_path):
    get_channel = Mock(return_value=None)
    fallback = AsyncMock()
    allowed_mentions = object()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        " 42 ",
        "hei",
        allowed_mentions=allowed_mentions,
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    get_channel.assert_called_once_with(42)
    fallback.assert_awaited_once_with(
        42,
        "hei",
        allowed_mentions=allowed_mentions,
        suppress_embeds=True,
    )


@pytest.mark.asyncio
async def test_get_channel_failure_is_definite_pre_attempt_transport(tmp_path):
    get_channel = Mock(side_effect=RuntimeError("secret lookup failure"))
    fallback = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        42,
        "hei",
        allowed_mentions=discord.AllowedMentions.none(),
    )

    assert result == MessageSendResult(DeliveryState.NOT_DELIVERED, "transport")
    fallback.assert_not_awaited()
    assert "secret" not in repr(result)


@pytest.mark.asyncio
async def test_send_to_channel_reports_missing_adapter(tmp_path):
    checker = ReminderChecker(storage_path=tmp_path / "sent.json")

    result = await checker._send_to_channel(
        42,
        "hei",
        allowed_mentions=discord.AllowedMentions.none(),
    )

    assert result == MessageSendResult(DeliveryState.NOT_DELIVERED, "missing_adapter")


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ("direct", "fallback"))
@pytest.mark.parametrize(
    ("failure_factory", "expected"),
    (
        (
            lambda: discord.errors.Forbidden(_Response(403), "secret forbidden"),
            MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
        ),
        (
            lambda: discord.errors.HTTPException(_Response(429), "secret http"),
            MessageSendResult(DeliveryState.UNKNOWN, "http"),
        ),
        (
            lambda: RuntimeError("secret transport"),
            MessageSendResult(DeliveryState.UNKNOWN, "transport"),
        ),
    ),
)
async def test_started_send_failures_have_exact_tri_state_semantics(
    tmp_path,
    adapter,
    failure_factory,
    expected,
):
    send = AsyncMock(side_effect=failure_factory())
    if adapter == "direct":
        get_channel = Mock(return_value=SimpleNamespace(send=send))
        fallback = AsyncMock()
    else:
        get_channel = Mock(return_value=None)
        fallback = send
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=get_channel,
        send_channel_message_func=fallback,
    )

    result = await checker._send_to_channel(
        42,
        "hei",
        allowed_mentions=discord.AllowedMentions.none(),
    )

    assert result == expected
    assert "secret" not in repr(result)


@pytest.mark.asyncio
async def test_send_mentions_item_allows_only_trusted_creator_for_malicious_text(
    tmp_path,
):
    send = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=Mock(return_value=SimpleNamespace(send=send)),
    )
    malicious = (
        "@everyone <@999> <@&888> <#777> "
        "https://example.invalid/tracker"
    )

    result = await checker._send_mentions_item(
        42,
        {"user_id": "123"},
        malicious,
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    sent_message = send.await_args.args[0]
    send_kwargs = send.await_args.kwargs
    allowed_mentions = send_kwargs["allowed_mentions"]
    assert sent_message == f"<@123>\n\n{malicious}"
    assert [user.id for user in allowed_mentions.users] == [123]
    assert allowed_mentions.roles is False
    assert allowed_mentions.everyone is False
    assert allowed_mentions.replied_user is False
    assert send_kwargs["suppress_embeds"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "expected_prefix"),
    (("gcal_sync", "📅 **Google Calendar Sync**\n\n"), (None, "")),
)
async def test_send_mentions_item_disables_mentions_without_a_creator(
    tmp_path,
    user_id,
    expected_prefix,
):
    send = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=Mock(return_value=SimpleNamespace(send=send)),
    )
    malicious = "@everyone <@999> <@&888> <#777> https://example.invalid"

    result = await checker._send_mentions_item(
        42,
        {"user_id": user_id},
        malicious,
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    assert send.await_args.args[0] == f"{expected_prefix}{malicious}"
    allowed_mentions = send.await_args.kwargs["allowed_mentions"]
    assert allowed_mentions.users is False
    assert allowed_mentions.roles is False
    assert allowed_mentions.everyone is False
    assert allowed_mentions.replied_user is False
    assert send.await_args.kwargs["suppress_embeds"] is True


@pytest.mark.asyncio
async def test_parallel_creator_sends_keep_separate_mention_allowlists(tmp_path):
    captured = []

    async def send(message, **kwargs):
        await asyncio.sleep(0)
        captured.append((message, kwargs))

    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=Mock(
            return_value=SimpleNamespace(send=AsyncMock(side_effect=send))
        ),
    )

    results = await asyncio.gather(
        checker._send_mentions_item(42, {"user_id": "123"}, "første"),
        checker._send_mentions_item(42, {"user_id": "456"}, "andre"),
    )

    assert results == [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.DELIVERED),
    ]
    by_message = {message: kwargs for message, kwargs in captured}
    first_mentions = by_message["<@123>\n\nførste"]["allowed_mentions"]
    second_mentions = by_message["<@456>\n\nandre"]["allowed_mentions"]
    assert [user.id for user in first_mentions.users] == [123]
    assert [user.id for user in second_mentions.users] == [456]
    assert first_mentions is not second_mentions
    assert by_message["<@123>\n\nførste"]["suppress_embeds"] is True
    assert by_message["<@456>\n\nandre"]["suppress_embeds"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id",
    (
        0,
        -1,
        True,
        123.0,
        Decimal("123"),
        "-123",
        "abc",
        pytest.param("9" * 1_000, id="oversized-decimal"),
    ),
)
async def test_malformed_creator_id_uses_no_mentions(tmp_path, user_id):
    send = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=Mock(return_value=SimpleNamespace(send=send)),
    )

    result = await checker._send_mentions_item(
        42,
        {"user_id": user_id},
        "@everyone <@999>",
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    assert send.await_args.args[0] == "@everyone <@999>"
    allowed_mentions = send.await_args.kwargs["allowed_mentions"]
    assert allowed_mentions.users is False
    assert allowed_mentions.roles is False
    assert allowed_mentions.everyone is False
    assert allowed_mentions.replied_user is False


@pytest.mark.asyncio
async def test_hostile_creator_id_is_not_coerced_and_uses_no_mentions(tmp_path):
    hostile = _HostileChannelId()
    send = AsyncMock()
    checker = ReminderChecker(
        storage_path=tmp_path / "sent.json",
        get_channel_func=Mock(return_value=SimpleNamespace(send=send)),
    )

    result = await checker._send_mentions_item(
        42,
        {"user_id": hostile},
        "trygg tekst",
    )

    assert result == MessageSendResult(DeliveryState.DELIVERED)
    assert hostile.int_calls == 0
    assert send.await_args.args[0] == "trygg tekst"
    assert send.await_args.kwargs["allowed_mentions"].users is False
