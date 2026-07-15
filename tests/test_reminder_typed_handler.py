"""Typed reminder handler truth and no-reparse contracts."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    ManagerMutationCancelled,
    ManagerMutationError,
    MessageSendCancelled,
    MessageSendResult,
)
from features.reminder_handler import ReminderHandler


REFERENCE_TIME = datetime.fromisoformat("2026-07-15T10:30:00+02:00")


class TypedMessage:
    guild = SimpleNamespace(id=123)
    channel = SimpleNamespace(id=456)
    author = SimpleNamespace(id=7, name="Tester")

    @property
    def content(self):
        raise AssertionError("typed reminder path read message.content")


def make_handler(send_result=None):
    reminders = SimpleNamespace(
        clock=SimpleNamespace(now=Mock(return_value=REFERENCE_TIME)),
        _require_aware=lambda value: value,
        add_reminder_result=AsyncMock(return_value="rem_exact"),
        complete_reminder_result=AsyncMock(
            return_value=(True, "Ring legen", None)
        ),
        edit_reminder_result=AsyncMock(
            return_value={"id": "rem_exact", "text": "Ring tannlegen"}
        ),
        delete_reminder_result=AsyncMock(return_value=True),
        snapshot_pending_items=Mock(
            return_value=({"id": "rem_from_number", "text": "En"},)
        ),
        format_reminders_list=Mock(return_value="⬜ **1.** Ring legen"),
        format_search_results=Mock(return_value="🔎 Ring legen"),
    )
    metrics = SimpleNamespace(record_legacy_payload_fallback=Mock())
    monitor = SimpleNamespace(
        reminders=reminders,
        rate_limiter=SimpleNamespace(),
        loc=SimpleNamespace(
            current_lang="no",
            t=lambda key, **values: f"{key}:{values}",
        ),
        client=SimpleNamespace(),
        nlu_metrics=metrics,
    )
    handler = ReminderHandler(monitor)
    handler.send_response_result = AsyncMock(
        return_value=send_result
        or MessageSendResult(DeliveryState.DELIVERED)
    )
    return handler, reminders, metrics


@pytest.mark.asyncio
async def test_all_typed_actions_use_exact_adapters_without_raw_reparse():
    handler, reminders, metrics = make_handler()
    message = TypedMessage()
    handler._parse_edit_command = Mock(side_effect=AssertionError("edit reparse"))
    handler._parse_search_query = Mock(side_effect=AssertionError("search reparse"))
    handler.extract_number = Mock(side_effect=AssertionError("number reparse"))

    with patch(
        "features.reminder_handler.parse_reminder_command",
        side_effect=AssertionError("raw reminder reparse"),
    ):
        create = await handler.handle_reminder_create(
            message,
            {
                "action": "add",
                "text": " Ring legen ",
                "due_date": "20.07.2026",
                "recurrence": "weekly",
            },
            reference_time=REFERENCE_TIME,
        )
        listed = await handler.handle_reminder_list(
            message,
            {"action": "list"},
            reference_time=REFERENCE_TIME,
        )
        searched = await handler.handle_reminder_search(
            message,
            {"action": "search", "query": " lege "},
            reference_time=REFERENCE_TIME,
        )
        completed = await handler.handle_reminder_complete(
            message,
            {"action": "complete", "reminder_id": "rem_exact"},
            reference_time=REFERENCE_TIME,
        )
        edited = await handler.handle_reminder_edit(
            message,
            {
                "action": "edit",
                "reminder_id": "rem_exact",
                "changes": {
                    "text": "Ring tannlegen",
                    "due_date": "21.07.2026",
                    "time": "14:00",
                    "recurrence": "monthly",
                },
            },
            reference_time=REFERENCE_TIME,
        )
        deleted = await handler.handle_reminder_delete(
            message,
            {"action": "delete", "reminder_id": "rem_exact"},
            reference_time=REFERENCE_TIME,
        )

    assert all(
        outcome.ok
        for outcome in (create, listed, searched, completed, edited, deleted)
    )
    assert [
        outcome.mutated
        for outcome in (create, listed, searched, completed, edited, deleted)
    ] == [True, False, False, True, True, True]
    assert all(outcome.response_sent for outcome in (
        create,
        listed,
        searched,
        completed,
        edited,
        deleted,
    ))
    assert handler.send_response_result.await_count == 6
    metrics.record_legacy_payload_fallback.assert_not_called()
    reminders.clock.now.assert_not_called()
    reminders.add_reminder_result.assert_awaited_once_with(
        123,
        7,
        "Tester",
        "Ring legen",
        "20.07.2026",
        "weekly",
        channel_id=456,
        reference_time=REFERENCE_TIME,
    )
    reminders.format_reminders_list.assert_called_once_with(
        123,
        show_completed=True,
        reference_time=REFERENCE_TIME,
    )
    reminders.format_search_results.assert_called_once_with(123, "lege", "no")
    reminders.complete_reminder_result.assert_awaited_once_with(
        123,
        reminder_num=None,
        reminder_id="rem_exact",
        reference_time=REFERENCE_TIME,
    )
    reminders.edit_reminder_result.assert_awaited_once_with(
        123,
        index=None,
        title="Ring tannlegen",
        date="21.07.2026",
        time="14:00",
        recurrence="monthly",
        reminder_id="rem_exact",
        reference_time=REFERENCE_TIME,
    )
    reminders.snapshot_pending_items.assert_not_called()
    reminders.delete_reminder_result.assert_awaited_once_with(
        123,
        reminder_id="rem_exact",
        reference_time=REFERENCE_TIME,
    )


@pytest.mark.asyncio
async def test_none_payload_uses_one_legacy_parse_and_one_bounded_metric():
    handler, reminders, metrics = make_handler()
    message = SimpleNamespace(
        content="legacy sentinel",
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=7, name="Tester"),
    )
    parser = Mock(return_value={"action": "add", "text": "Ring legen"})

    with patch("features.reminder_handler.parse_reminder_command", parser):
        outcome = await handler.handle_reminder_create(
            message,
            None,
            reference_time=REFERENCE_TIME,
        )

    assert outcome.ok and outcome.mutated and outcome.response_sent
    parser.assert_called_once_with("legacy sentinel", now=REFERENCE_TIME)
    metrics.record_legacy_payload_fallback.assert_called_once_with("reminder")
    reminders.add_reminder_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_typed_payload_is_authoritative_and_never_falls_back():
    handler, reminders, metrics = make_handler()

    with patch(
        "features.reminder_handler.parse_reminder_command",
        side_effect=AssertionError("typed payload fell back"),
    ):
        outcome = await handler.handle_reminder_create(
            TypedMessage(),
            {},
            reference_time=REFERENCE_TIME,
        )

    assert not outcome.ok
    assert outcome.error_code == "invalid_payload"
    assert not outcome.mutated
    assert outcome.response_sent
    metrics.record_legacy_payload_fallback.assert_not_called()
    reminders.add_reminder_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsupported_temporal_fields_are_rejected_before_any_write():
    handler, reminders, _ = make_handler()

    create = await handler.handle_reminder_create(
        TypedMessage(),
        {
            "action": "add",
            "text": "Ring legen",
            "due_at": "2026-07-15T14:00:00+02:00",
            "due_date": "15.07.2026",
            "time": "14:00",
            "timezone": "Europe/Oslo",
        },
        reference_time=REFERENCE_TIME,
    )
    edit = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "number": 1,
            "changes": {"timezone": "Europe/Oslo", "time": "15:00"},
        },
        reference_time=REFERENCE_TIME,
    )

    for outcome in (create, edit):
        assert not outcome.ok
        assert outcome.error_code == "unsupported_temporal_field"
        assert not outcome.mutated
        assert outcome.response_sent
    reminders.add_reminder_result.assert_not_awaited()
    reminders.edit_reminder_result.assert_not_awaited()
    assert handler.send_response_result.await_count == 2


@pytest.mark.asyncio
async def test_numbered_delete_freezes_stable_id_before_mutation():
    handler, reminders, _ = make_handler()

    outcome = await handler.handle_reminder_delete(
        TypedMessage(),
        {"action": "delete", "number": 1},
        reference_time=REFERENCE_TIME,
    )

    assert outcome.ok and outcome.mutated
    reminders.snapshot_pending_items.assert_called_once_with(123)
    reminders.delete_reminder_result.assert_awaited_once_with(
        123,
        reminder_id="rem_from_number",
        reference_time=REFERENCE_TIME,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("delivery", "response_sent"),
    [
        (MessageSendResult(DeliveryState.DELIVERED), True),
        (MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"), False),
        (MessageSendResult(DeliveryState.UNKNOWN, "timeout"), False),
    ],
)
async def test_all_terminal_delivery_states_preserve_committed_mutation(
    delivery,
    response_sent,
):
    handler, reminders, _ = make_handler(delivery)

    outcome = await handler.handle_reminder_create(
        TypedMessage(),
        {"action": "add", "text": "Ring legen"},
        reference_time=REFERENCE_TIME,
    )

    assert outcome.ok
    assert outcome.mutated
    assert outcome.response_sent is response_sent
    assert not outcome.retryable
    assert outcome.delivery_result == delivery
    reminders.add_reminder_result.assert_awaited_once()
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_cancellation_carries_exact_committed_delivery_truth():
    delivery = MessageSendResult(DeliveryState.UNKNOWN, "send_task_cancelled")
    handler, reminders, _ = make_handler()
    handler.send_response_result.side_effect = MessageSendCancelled(delivery)

    with pytest.raises(DispatchCancelled) as caught:
        await handler.handle_reminder_create(
            TypedMessage(),
            {"action": "add", "text": "Ring legen"},
            reference_time=REFERENCE_TIME,
        )

    outcome = caught.value.outcome
    assert outcome.ok
    assert outcome.mutated
    assert not outcome.response_sent
    assert not outcome.retryable
    assert outcome.delivery_result == delivery
    reminders.add_reminder_result.assert_awaited_once()
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_errors_and_cancellation_keep_bounded_mutation_truth():
    handler, reminders, _ = make_handler()
    reminders.add_reminder_result.side_effect = ManagerMutationError(
        "storage_write_failed",
        mutated=False,
    )

    rolled_back = await handler.handle_reminder_create(
        TypedMessage(),
        {"action": "add", "text": "Ring legen"},
        reference_time=REFERENCE_TIME,
    )

    assert not rolled_back.ok
    assert not rolled_back.mutated
    assert rolled_back.retryable
    assert rolled_back.error_code == "storage_write_failed"
    assert rolled_back.response_sent
    handler.send_response_result.assert_awaited_once()

    handler.send_response_result.reset_mock()
    reminders.add_reminder_result.reset_mock()
    reminders.add_reminder_result.side_effect = ManagerMutationCancelled(
        "cancelled",
        mutated=True,
        retryable=False,
    )

    with pytest.raises(DispatchCancelled) as caught:
        await handler.handle_reminder_create(
            TypedMessage(),
            {"action": "add", "text": "Ring legen"},
            reference_time=REFERENCE_TIME,
        )

    assert not caught.value.outcome.ok
    assert caught.value.outcome.mutated
    assert not caught.value.outcome.retryable
    assert caught.value.outcome.error_code == "cancelled"
    assert caught.value.outcome.delivery_result is None
    handler.send_response_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_maps_bounded_invalid_recurrence_before_write():
    handler, reminders, _ = make_handler()
    reminders.edit_reminder_result.side_effect = ValueError(
        "invalid_recurrence"
    )

    outcome = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "number": 1,
            "changes": {"recurrence": "weekly"},
        },
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.error_code == "invalid_payload"
    assert outcome.response_sent


@pytest.mark.asyncio
async def test_unbounded_manager_error_code_fails_closed():
    handler, reminders, _ = make_handler()
    reminders.add_reminder_result.side_effect = ManagerMutationError(
        "secret_detail",
        mutated=True,
    )

    outcome = await handler.handle_reminder_create(
        TypedMessage(),
        {"action": "add", "text": "Ring legen"},
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert outcome.mutated
    assert not outcome.retryable
    assert outcome.commit_unknown
    assert outcome.error_code == "commit_state_unknown"
    assert outcome.response_sent


@pytest.mark.asyncio
async def test_unclassified_mutator_exception_is_terminal_commit_unknown():
    handler, reminders, _ = make_handler()
    reminders.delete_reminder_result.side_effect = RuntimeError("secret detail")

    outcome = await handler.handle_reminder_delete(
        TypedMessage(),
        {"action": "delete", "reminder_id": "rem_exact"},
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.commit_unknown
    assert outcome.error_code == "commit_state_unknown"
    assert outcome.response_sent
    handler.send_response_result.assert_awaited_once()
