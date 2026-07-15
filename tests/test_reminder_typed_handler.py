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
from core.intent_models import BotIntent
from core.intent_payloads import validate_intent_payload
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
    temporal_resolver = Mock(name="shared_temporal_resolver")
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
        nlp_parser=SimpleNamespace(temporal_resolver=temporal_resolver),
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

    with (
        patch(
            "features.reminder_handler.parse_reminder_command",
            side_effect=AssertionError("raw reminder reparse"),
        ),
        patch(
            "features.reminder_handler.validate_intent_payload",
            side_effect=AssertionError("typed reminder was revalidated"),
        ),
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
    assert (
        reminders.add_reminder_result.await_args.kwargs["reference_time"]
        is REFERENCE_TIME
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
        text="Ring tannlegen",
        due_date="21.07.2026",
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

    with (
        patch("features.reminder_handler.parse_reminder_command", parser),
        patch(
            "features.reminder_handler.validate_intent_payload",
            wraps=validate_intent_payload,
        ) as validator,
    ):
        outcome = await handler.handle_reminder_create(
            message,
            None,
            reference_time=REFERENCE_TIME,
        )

    assert outcome.ok and outcome.mutated and outcome.response_sent
    parser.assert_called_once_with(
        "legacy sentinel",
        now=REFERENCE_TIME,
        temporal_resolver=handler.temporal_resolver,
    )
    assert parser.call_args.kwargs["now"] is REFERENCE_TIME
    assert (
        parser.call_args.kwargs["temporal_resolver"]
        is handler.temporal_resolver
    )
    validator.assert_called_once_with(
        BotIntent.REMINDER_CREATE,
        {"action": "add", "text": "Ring legen"},
    )
    metrics.record_legacy_payload_fallback.assert_called_once_with("reminder")
    reminders.add_reminder_result.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "intent", "raw"),
    [
        (
            "handle_reminder_create",
            BotIntent.REMINDER_CREATE,
            {"action": "add", "text": "Ring legen"},
        ),
        (
            "handle_reminder_list",
            BotIntent.REMINDER_LIST,
            {"action": "list"},
        ),
        (
            "handle_reminder_search",
            BotIntent.REMINDER_SEARCH,
            {"action": "search", "query": "lege"},
        ),
        (
            "handle_reminder_complete",
            BotIntent.REMINDER_COMPLETE,
            {"action": "complete", "reminder_id": "rem_exact"},
        ),
        (
            "handle_reminder_edit",
            BotIntent.REMINDER_EDIT,
            {
                "action": "edit",
                "reminder_id": "rem_exact",
                "changes": {"text": "Ring tannlegen"},
            },
        ),
        (
            "handle_reminder_delete",
            BotIntent.REMINDER_DELETE,
            {"action": "delete", "reminder_id": "rem_exact"},
        ),
    ],
)
async def test_each_legacy_fallback_validates_for_its_exact_intent(
    method_name,
    intent,
    raw,
):
    handler, _, metrics = make_handler()
    message = SimpleNamespace(
        content="legacy sentinel",
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=7, name="Tester"),
    )

    with (
        patch(
            "features.reminder_handler.parse_reminder_command",
            return_value=raw,
        ),
        patch(
            "features.reminder_handler.validate_intent_payload",
            wraps=validate_intent_payload,
        ) as validator,
    ):
        outcome = await getattr(handler, method_name)(
            message,
            None,
            reference_time=REFERENCE_TIME,
        )

    assert outcome.ok
    validator.assert_called_once_with(intent, raw)
    metrics.record_legacy_payload_fallback.assert_called_once_with("reminder")


@pytest.mark.asyncio
async def test_malformed_legacy_fallback_is_bounded_before_any_manager_call():
    handler, reminders, metrics = make_handler()
    message = SimpleNamespace(
        content="legacy sentinel",
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=7, name="Tester"),
    )

    with patch(
        "features.reminder_handler.parse_reminder_command",
        return_value={
            "action": "add",
            "text": "Ring legen",
            "unknown": "must-not-reach-manager",
        },
    ):
        outcome = await handler.handle_reminder_create(
            message,
            None,
            reference_time=REFERENCE_TIME,
        )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.error_code == "invalid_payload"
    assert outcome.response_sent
    reminders.add_reminder_result.assert_not_awaited()
    metrics.record_legacy_payload_fallback.assert_called_once_with("reminder")
    handler.send_response_result.assert_awaited_once()


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
async def test_canonical_temporal_fields_reach_create_and_edit_unchanged():
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
    edit_due_at = "2026-07-16T15:00:00+02:00"
    edit = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "number": 1,
            "changes": {
                "due_at": edit_due_at,
                "due_date": "16.07.2026",
                "time": "15:00",
                "timezone": "Europe/Oslo",
            },
        },
        reference_time=REFERENCE_TIME,
    )

    for outcome in (create, edit):
        assert outcome.ok
        assert outcome.mutated
        assert outcome.response_sent
    reminders.add_reminder_result.assert_awaited_once_with(
        123,
        7,
        "Tester",
        "Ring legen",
        "15.07.2026",
        None,
        channel_id=456,
        due_at="2026-07-15T14:00:00+02:00",
        time="14:00",
        timezone="Europe/Oslo",
        reference_time=REFERENCE_TIME,
    )
    reminders.edit_reminder_result.assert_awaited_once_with(
        123,
        index=1,
        due_at=edit_due_at,
        due_date="16.07.2026",
        time="15:00",
        timezone="Europe/Oslo",
        reminder_id=None,
        reference_time=REFERENCE_TIME,
    )
    assert handler.send_response_result.await_count == 2


@pytest.mark.asyncio
async def test_edit_omission_is_absent_but_explicit_none_is_forwarded():
    handler, reminders, _ = make_handler()

    text_only = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "reminder_id": "rem_exact",
            "changes": {"text": "Ny tekst"},
        },
        reference_time=REFERENCE_TIME,
    )
    explicit_clear = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "reminder_id": "rem_exact",
            "changes": {"due_at": None, "recurrence": None},
        },
        reference_time=REFERENCE_TIME,
    )

    assert text_only.ok and text_only.mutated
    assert explicit_clear.ok and explicit_clear.mutated
    assert reminders.edit_reminder_result.await_args_list[0].kwargs == {
        "index": None,
        "reminder_id": "rem_exact",
        "reference_time": REFERENCE_TIME,
        "text": "Ny tekst",
    }
    assert reminders.edit_reminder_result.await_args_list[1].kwargs == {
        "index": None,
        "reminder_id": "rem_exact",
        "reference_time": REFERENCE_TIME,
        "due_at": None,
        "recurrence": None,
    }
    for call in reminders.edit_reminder_result.await_args_list:
        assert "title" not in call.kwargs
        assert "date" not in call.kwargs


@pytest.mark.asyncio
async def test_handler_requires_the_turn_reference_and_never_reads_manager_clock():
    handler, reminders, _ = make_handler()

    with pytest.raises(TypeError, match="reference_time"):
        await handler.handle_reminder_create(
            TypedMessage(),
            {"action": "add", "text": "Ring legen"},
        )
    with pytest.raises(ValueError, match="reference_time_must_be_aware"):
        await handler.handle_reminder_create(
            TypedMessage(),
            {"action": "add", "text": "Ring legen"},
            reference_time=datetime(2026, 7, 15, 10, 30),
        )

    reminders.clock.now.assert_not_called()
    reminders.add_reminder_result.assert_not_awaited()


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
async def test_create_maps_bounded_temporal_rejection_to_invalid_payload():
    handler, reminders, _ = make_handler()
    reminders.add_reminder_result.side_effect = ValueError(
        "invalid_recurrence"
    )

    outcome = await handler.handle_reminder_create(
        TypedMessage(),
        {
            "action": "add",
            "text": "Ring legen",
            "recurrence": "weekly",
        },
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.error_code == "invalid_payload"
    assert outcome.response_sent


@pytest.mark.asyncio
async def test_missing_date_edit_rejection_is_bounded_invalid_payload():
    handler, reminders, _ = make_handler()
    reminders.edit_reminder_result.side_effect = ValueError("missing_date")

    outcome = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "reminder_id": "rem_exact",
            "changes": {"time": "14:00"},
        },
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.error_code == "invalid_payload"
    assert outcome.response_sent


@pytest.mark.asyncio
async def test_only_exact_lookup_error_maps_to_retryable_not_found():
    handler, reminders, _ = make_handler()
    reminders.edit_reminder_result.side_effect = ValueError("not_found")

    outcome = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "reminder_id": "rem_exact",
            "changes": {"text": "Ring tannlegen"},
        },
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert outcome.retryable
    assert outcome.error_code == "not_found"
    assert outcome.response_sent


@pytest.mark.asyncio
async def test_unknown_edit_value_error_fails_closed_as_commit_unknown():
    handler, reminders, _ = make_handler()
    reminders.edit_reminder_result.side_effect = ValueError("secret_detail")

    outcome = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "reminder_id": "rem_exact",
            "changes": {"text": "Ring tannlegen"},
        },
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.commit_unknown
    assert outcome.error_code == "commit_state_unknown"
    assert outcome.response_sent
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_truthy_non_mapping_edit_result_is_bounded_commit_unknown():
    handler, reminders, _ = make_handler()
    reminders.edit_reminder_result.return_value = ["unexpected", "result"]

    outcome = await handler.handle_reminder_edit(
        TypedMessage(),
        {
            "action": "edit",
            "reminder_id": "rem_exact",
            "changes": {"text": "Ring tannlegen"},
        },
        reference_time=REFERENCE_TIME,
    )

    assert not outcome.ok
    assert not outcome.mutated
    assert not outcome.retryable
    assert outcome.commit_unknown
    assert outcome.error_code == "commit_state_unknown"
    assert outcome.response_sent
    reminders.edit_reminder_result.assert_awaited_once()
    handler.send_response_result.assert_awaited_once()


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
