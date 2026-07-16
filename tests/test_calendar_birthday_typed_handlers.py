from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from cal_system.calendar_manager import CalendarSyncResult
from cal_system.google_calendar_manager import ExternalOperationCancelled
from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
    MessageSendResult,
)
from core.mutation_coordinator import MutationCoordinator
from core.mutation_coordinator import CALENDAR_SHARED_SCOPE
from features.birthday_handler import BirthdayHandler
from features.birthday_manager import BirthdayWriteResult
from features.calendar_handler import CalendarHandler


NOW = datetime(2026, 7, 15, 9, 30, tzinfo=ZoneInfo("Europe/Oslo"))


class StrictMessage:
    def __init__(self):
        self.guild = SimpleNamespace(id=123)
        self.channel = SimpleNamespace(id=456)
        self.author = SimpleNamespace(id=7, name="Kari")

    @property
    def content(self):
        raise AssertionError("typed handler must not read message.content")


def _loc():
    return SimpleNamespace(
        current_lang="no",
        t=lambda key, **kwargs: {
            "calendar_edit_invalid": "Ugyldig redigeringsformat",
            "calendar_edit_success": f"Oppdatert: {kwargs.get('title')}",
            "birthday_edit_success": "Bursdag oppdatert",
        }.get(key, key),
    )


def _metrics():
    return SimpleNamespace(record_legacy_payload_fallback=Mock())


def _calendar(rows=()):
    return SimpleNamespace(
        mutation_coordinator=MutationCoordinator(),
        snapshot_pending_items=Mock(return_value=tuple(rows)),
        snapshot_all_item_ids=Mock(return_value=tuple(row["id"] for row in rows)),
        search_items=Mock(return_value=[]),
        add_item_result=AsyncMock(
            return_value={
                "id": "created",
                "title": "Møte",
                "date": "16.07.2026",
                "time": "10:00",
            }
        ),
        edit_item_result=AsyncMock(),
        delete_item_result=AsyncMock(),
        complete_item_result=AsyncMock(),
        clear_calendar_result=AsyncMock(),
        sync_from_gcal_result=AsyncMock(),
        format_single_item=Mock(return_value="Lagt til"),
        gcal=None,
    )


def _calendar_handler(calendar, delivery=None):
    monitor = SimpleNamespace(
        calendar=calendar,
        nlp_parser=SimpleNamespace(
            temporal_resolver=None,
            parse_event=Mock(side_effect=AssertionError("legacy parser called")),
        ),
        rate_limiter=SimpleNamespace(),
        loc=_loc(),
        client=None,
        nlu_metrics=_metrics(),
    )
    handler = CalendarHandler(monitor)
    handler.send_response_result = AsyncMock(
        return_value=delivery or MessageSendResult(DeliveryState.DELIVERED)
    )
    return handler, monitor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delivery",
    [
        MessageSendResult(DeliveryState.DELIVERED),
        MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    ],
)
async def test_calendar_typed_create_passes_exact_reference_and_delivery(delivery):
    calendar = _calendar()
    handler, monitor = _calendar_handler(calendar, delivery)
    message = StrictMessage()

    outcome = await handler.handle_calendar_item(
        message,
        {"title": "Møte", "date": "16.07.2026", "time": "10:00"},
        reference_time=NOW,
    )

    assert outcome.ok is True
    assert outcome.mutated is True
    assert outcome.delivery_result is delivery
    kwargs = calendar.add_item_result.await_args.kwargs
    assert kwargs["reference_time"] is NOW
    monitor.nlp_parser.parse_event.assert_not_called()
    monitor.nlu_metrics.record_legacy_payload_fallback.assert_not_called()
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_calendar_invalid_create_stops_before_manager():
    calendar = _calendar()
    handler, _ = _calendar_handler(calendar)

    outcome = await handler.handle_calendar_item(
        StrictMessage(),
        {"title": "Møte", "date": "32.13.2026", "time": "10:00"},
        reference_time=NOW,
    )

    assert outcome.ok is False
    assert outcome.error_code == "invalid_payload"
    calendar.add_item_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_edit_resolves_position_to_stable_id_and_clears_recurrence():
    row = {
        "id": "calendar-stable-id",
        "title": "Møte",
        "date": "16.07.2026",
        "time": "10:00",
        "recurrence": "weekly",
    }
    calendar = _calendar([row])
    calendar.edit_item_result.return_value = {**row, "recurrence": None}
    handler, _ = _calendar_handler(calendar)

    outcome = await handler.handle_edit(
        StrictMessage(),
        {"target": "1", "changes": {"recurrence": None}},
        reference_time=NOW,
    )

    assert outcome == outcome.with_delivery(outcome.delivery_result)
    assert outcome.ok is True and outcome.mutated is True
    calendar.snapshot_pending_items.assert_called_once_with(reference_time=NOW)
    calendar.edit_item_result.assert_awaited_once_with(
        item_id="calendar-stable-id",
        reference_time=NOW,
        recurrence=None,
    )


@pytest.mark.asyncio
async def test_calendar_ambiguous_title_never_mutates():
    rows = [
        {"id": "one", "title": "Møte med Ola", "date": "16.07.2026", "time": "10:00"},
        {"id": "two", "title": "Møte med Kari", "date": "17.07.2026", "time": "10:00"},
    ]
    calendar = _calendar(rows)
    handler, _ = _calendar_handler(calendar)

    outcome = await handler.handle_delete(
        StrictMessage(),
        {"target": "møte"},
        reference_time=NOW,
    )

    assert outcome.error_code == "ambiguous_target"
    assert outcome.mutated is False
    calendar.snapshot_pending_items.assert_called_once_with(reference_time=NOW)
    calendar.delete_item_result.assert_not_awaited()
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_calendar_delete_maps_external_pending_marker_truth():
    row = {"id": "one", "title": "Møte", "date": "16.07.2026", "time": "10:00"}
    calendar = _calendar([row])
    calendar.delete_item_result.return_value = {
        "requested_count": 1,
        "deleted_count": 0,
        "pending_count": 1,
    }
    handler, _ = _calendar_handler(calendar)

    outcome = await handler.handle_delete(
        StrictMessage(),
        {"number": 1},
        reference_time=NOW,
    )

    assert outcome.ok is False
    assert outcome.error_code == "external_delete_pending"
    assert outcome.mutated is True
    calendar.delete_item_result.assert_awaited_once_with(
        123,
        item_id="one",
        reference_time=NOW,
    )


@pytest.mark.asyncio
async def test_calendar_legacy_bulk_preserves_prior_commit_when_later_write_fails():
    rows = [
        {"id": "one", "title": "Møte A", "date": "16.07.2026", "time": "10:00"},
        {"id": "two", "title": "Møte B", "date": "17.07.2026", "time": "10:00"},
    ]
    calendar = _calendar(rows)
    calendar.delete_item_result.side_effect = [
        {"requested_count": 1, "deleted_count": 1, "pending_count": 0},
        ManagerMutationError("storage_write_failed", mutated=False),
    ]
    handler, monitor = _calendar_handler(calendar)
    message = SimpleNamespace(
        content="@inebotten slett alle møte",
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=7, name="Kari"),
    )

    outcome = await handler.handle_delete(message, None, reference_time=NOW)

    assert outcome.error_code == "storage_write_failed"
    assert outcome.mutated is True
    assert outcome.retryable is False
    assert calendar.delete_item_result.await_count == 2
    monitor.nlu_metrics.record_legacy_payload_fallback.assert_called_once_with(
        "calendar"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["delete", "complete"])
async def test_calendar_legacy_bulk_preserves_prior_commit_on_unexpected_failure(
    action,
):
    rows = [
        {"id": "one", "title": "Møte A", "date": "16.07.2026", "time": "10:00"},
        {"id": "two", "title": "Møte B", "date": "17.07.2026", "time": "10:00"},
    ]
    calendar = _calendar(rows)
    handler, _ = _calendar_handler(calendar)
    message = SimpleNamespace(
        content=f"@inebotten {action} alle møte",
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=7, name="Kari"),
    )
    if action == "delete":
        calendar.delete_item_result.side_effect = [
            {"requested_count": 1, "deleted_count": 1, "pending_count": 0},
            RuntimeError("private provider detail"),
        ]
        outcome = await handler.handle_delete(message, None, reference_time=NOW)
    else:
        calendar.complete_item_result.side_effect = [
            (True, "Møte A", None),
            RuntimeError("private provider detail"),
        ]
        outcome = await handler.handle_complete(message, None, reference_time=NOW)

    assert outcome.error_code == "commit_state_unknown"
    assert outcome.mutated is True
    assert outcome.retryable is False
    assert outcome.commit_unknown is True


@pytest.mark.asyncio
async def test_calendar_clear_typed_payload_does_not_parse_confirmation_text():
    calendar = _calendar([{"id": "one"}])
    calendar.clear_calendar_result.return_value = {
        "requested_count": 1,
        "deleted_count": 1,
        "failed_count": 0,
    }
    handler, monitor = _calendar_handler(calendar)

    outcome = await handler.handle_clear(
        StrictMessage(),
        {"all": True},
        reference_time=NOW,
    )

    assert outcome.ok is True and outcome.mutated is True
    calendar.clear_calendar_result.assert_awaited_once_with(123, reference_time=NOW)
    monitor.nlu_metrics.record_legacy_payload_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_prewrite_retryable_failure_becomes_terminal_on_unknown_send():
    calendar = _calendar()
    calendar.add_item_result.side_effect = ManagerMutationError(
        "storage_write_failed",
        mutated=False,
    )
    delivery = MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    handler, _ = _calendar_handler(calendar, delivery)

    outcome = await handler.handle_calendar_item(
        StrictMessage(),
        {"title": "Møte", "date": "16.07.2026", "time": "10:00"},
        reference_time=NOW,
    )

    assert outcome.error_code == "storage_write_failed"
    assert outcome.retryable is False
    assert outcome.delivery_result is delivery


@pytest.mark.asyncio
async def test_calendar_send_cancellation_carries_committed_mutation_truth():
    calendar = _calendar()
    handler, _ = _calendar_handler(calendar)
    delivery = MessageSendResult(DeliveryState.UNKNOWN, "send_task_cancelled")
    handler.send_response_result.side_effect = MessageSendCancelled(delivery)

    with pytest.raises(DispatchCancelled) as captured:
        await handler.handle_calendar_item(
            StrictMessage(),
            {"title": "Møte", "date": "16.07.2026", "time": "10:00"},
            reference_time=NOW,
        )

    assert captured.value.outcome.mutated is True
    assert captured.value.outcome.delivery_result is delivery


@pytest.mark.asyncio
async def test_calendar_sync_returns_one_terminal_summary():
    calendar = _calendar()
    calendar.sync_from_gcal_result.return_value = CalendarSyncResult(
        True,
        True,
        added=1,
        updated=2,
    )
    handler, _ = _calendar_handler(calendar)

    outcome = await handler.handle_sync(StrictMessage(), reference_time=NOW)

    assert outcome.ok is True and outcome.mutated is True
    calendar.sync_from_gcal_result.assert_awaited_once_with(
        default_guild_id=123,
        default_channel_id=456,
        reference_time=NOW,
    )
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_calendar_auth_external_cancellation_carries_provider_truth():
    external = ExternalMutationResult(
        True,
        ExternalCommitState.CHANGED,
        value="https://auth.example",
    )
    gcal = SimpleNamespace(
        get_auth_url_result=AsyncMock(side_effect=ExternalOperationCancelled(external)),
    )
    calendar = _calendar()
    calendar.gcal = gcal
    handler, _ = _calendar_handler(calendar)

    with pytest.raises(DispatchCancelled) as captured:
        await handler.handle_auth(StrictMessage(), {}, reference_time=NOW)

    assert captured.value.outcome.ok is True
    assert captured.value.outcome.mutated is True
    handler.send_response_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_auth_missing_credentials_is_bounded_setup_failure():
    external = ExternalMutationResult(
        False,
        ExternalCommitState.UNCHANGED,
        error_code="missing_credentials",
    )
    calendar = _calendar()
    calendar.gcal = SimpleNamespace(
        get_auth_url_result=AsyncMock(return_value=external),
    )
    handler, _ = _calendar_handler(calendar)

    outcome = await handler.handle_auth(StrictMessage(), {}, reference_time=NOW)

    assert outcome.error_code == "missing_credentials"
    assert outcome.commit_unknown is False
    assert outcome.mutated is False


@pytest.mark.asyncio
async def test_calendar_auth_sync_cancellation_retains_successful_exchange_mutation():
    exchanged = ExternalMutationResult(
        True,
        ExternalCommitState.CHANGED,
        value="ok",
    )
    calendar = _calendar()
    calendar.gcal = SimpleNamespace(
        exchange_code_result=AsyncMock(return_value=exchanged),
    )
    calendar.sync_from_gcal_result.side_effect = ManagerMutationCancelled(
        "storage_write_failed",
        mutated=False,
        retryable=True,
    )
    handler, _ = _calendar_handler(calendar)

    with pytest.raises(DispatchCancelled) as captured:
        await handler.handle_auth(
            StrictMessage(),
            {"auth_code": "code"},
            reference_time=NOW,
        )

    assert captured.value.outcome.mutated is True
    assert captured.value.outcome.retryable is False


@pytest.mark.asyncio
async def test_calendar_auth_flow_serializes_against_calendar_create():
    calendar = _calendar()
    auth_entered = asyncio.Event()
    release_auth = asyncio.Event()
    create_entered = asyncio.Event()

    async def blocked_auth(**_kwargs):
        auth_entered.set()
        await release_auth.wait()
        return ExternalMutationResult(
            True,
            ExternalCommitState.CHANGED,
            value="https://auth.example",
        )

    async def coordinated_create(*_args, **_kwargs):
        async with calendar.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
            create_entered.set()
            return {
                "id": "created",
                "title": "Møte",
                "date": "16.07.2026",
                "time": "10:00",
            }

    calendar.gcal = SimpleNamespace(get_auth_url_result=blocked_auth)
    calendar.add_item_result.side_effect = coordinated_create
    auth_handler, _ = _calendar_handler(calendar)
    create_handler, _ = _calendar_handler(calendar)

    auth_task = asyncio.create_task(
        auth_handler.handle_auth(StrictMessage(), {}, reference_time=NOW)
    )
    await auth_entered.wait()
    create_task = asyncio.create_task(
        create_handler.handle_calendar_item(
            StrictMessage(),
            {"title": "Møte", "date": "16.07.2026", "time": "10:00"},
            reference_time=NOW,
        )
    )
    await asyncio.sleep(0)
    assert create_entered.is_set() is False

    release_auth.set()
    auth_outcome, create_outcome = await asyncio.gather(auth_task, create_task)

    assert auth_outcome.ok is True
    assert create_outcome.ok is True
    assert create_entered.is_set() is True


def _birthday_manager():
    return SimpleNamespace(
        create_birthday_result=AsyncMock(),
        edit_birthday_by_user_id_result=AsyncMock(),
        format_birthday_list=Mock(return_value="Alle bursdager"),
        format_upcoming_birthdays=Mock(return_value="Kommende bursdager"),
        format_birthday_for_user=Mock(return_value="Din bursdag"),
        birthdays={},
    )


def _birthday_handler(manager, delivery=None):
    monitor = SimpleNamespace(
        birthdays=manager,
        rate_limiter=SimpleNamespace(),
        loc=_loc(),
        client=None,
        nlu_metrics=_metrics(),
        reminder_clock=SimpleNamespace(now=Mock(return_value=NOW)),
    )
    handler = BirthdayHandler(monitor)
    handler.send_response_result = AsyncMock(
        return_value=delivery or MessageSendResult(DeliveryState.DELIVERED)
    )
    return handler, monitor


@pytest.mark.asyncio
async def test_birthday_create_uses_typed_user_identity_and_exact_reference():
    manager = _birthday_manager()
    manager.create_birthday_result.return_value = BirthdayWriteResult(
        True,
        True,
        False,
    )
    handler, monitor = _birthday_handler(manager)

    outcome = await handler.handle_birthday_create(
        StrictMessage(),
        {
            "action": "add",
            "user_id": 99,
            "display_name": "Ola",
            "day": 15,
            "month": 5,
        },
        reference_time=NOW,
    )

    assert outcome.ok is True and outcome.mutated is True
    manager.create_birthday_result.assert_awaited_once_with(
        123,
        99,
        "Ola",
        15,
        5,
        None,
        reference_time=NOW,
    )
    monitor.nlu_metrics.record_legacy_payload_fallback.assert_not_called()
    monitor.reminder_clock.now.assert_not_called()


@pytest.mark.asyncio
async def test_birthday_existing_create_is_bounded_non_mutating_failure():
    manager = _birthday_manager()
    manager.create_birthday_result.return_value = BirthdayWriteResult(
        False,
        False,
        False,
        "already_exists",
    )
    handler, _ = _birthday_handler(manager)

    outcome = await handler.handle_birthday_create(
        StrictMessage(),
        {
            "action": "add",
            "user_id": 99,
            "display_name": "Ola",
            "day": 15,
            "month": 5,
        },
        reference_time=NOW,
    )

    assert outcome.ok is False
    assert outcome.error_code == "already_exists"
    assert outcome.mutated is False


@pytest.mark.asyncio
async def test_birthday_pending_external_sync_preserves_local_mutation_on_unknown_send():
    manager = _birthday_manager()
    manager.edit_birthday_by_user_id_result.return_value = BirthdayWriteResult(
        False,
        True,
        True,
        "external_sync_pending",
    )
    delivery = MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    handler, _ = _birthday_handler(manager, delivery)

    outcome = await handler.handle_birthday_edit(
        StrictMessage(),
        {"action": "edit", "user_id": 99, "day": 20, "month": 5},
        reference_time=NOW,
    )

    assert outcome.error_code == "external_sync_pending"
    assert outcome.mutated is True
    assert outcome.delivery_result is delivery
    manager.edit_birthday_by_user_id_result.assert_awaited_once_with(
        123,
        99,
        20,
        5,
        None,
        reference_time=NOW,
    )


@pytest.mark.asyncio
async def test_birthday_external_change_then_local_save_failure_is_terminal():
    manager = _birthday_manager()
    manager.edit_birthday_by_user_id_result.return_value = BirthdayWriteResult(
        False,
        True,
        True,
        "external_state_changed_storage_failed",
    )
    handler, _ = _birthday_handler(manager)

    outcome = await handler.handle_birthday_edit(
        StrictMessage(),
        {"action": "edit", "user_id": 99, "day": 20, "month": 5},
        reference_time=NOW,
    )

    assert outcome.error_code == "external_state_changed_storage_failed"
    assert outcome.mutated is True
    assert outcome.retryable is False
    assert outcome.commit_unknown is False


@pytest.mark.asyncio
async def test_birthday_upcoming_list_selects_exact_formatter_and_is_read_only():
    manager = _birthday_manager()
    handler, _ = _birthday_handler(manager)

    outcome = await handler.handle_birthday_list(
        StrictMessage(),
        {"action": "list", "scope": "upcoming"},
        reference_time=NOW,
    )

    assert outcome.ok is True and outcome.mutated is False
    manager.format_upcoming_birthdays.assert_called_once_with(
        123,
        days=30,
        reference_time=NOW,
    )
    manager.format_birthday_list.assert_not_called()


@pytest.mark.asyncio
async def test_birthday_self_list_reads_only_the_message_author():
    manager = _birthday_manager()
    handler, _ = _birthday_handler(manager)

    outcome = await handler.handle_birthday_list(
        StrictMessage(),
        {"action": "list", "scope": "self"},
        reference_time=NOW,
    )

    assert outcome.ok is True and outcome.mutated is False
    manager.format_birthday_for_user.assert_called_once_with(123, 7)
    manager.format_upcoming_birthdays.assert_not_called()
    manager.format_birthday_list.assert_not_called()
