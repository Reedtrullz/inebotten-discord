"""Truthful typed dispatch tests for poll, watchlist, and quote handlers."""

from __future__ import annotations

from datetime import datetime, timedelta
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

import features.fun_handler as fun_handler_module
import features.quote_handler as quote_handler_module
import features.watchlist_handler as watchlist_handler_module
from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    MessageSendCancelled,
    MessageSendResult,
    ManagerMutationError,
)
from features.fun_handler import FunHandler
from features.poll_manager import PollManager
from features.polls_handler import PollsHandler
from features.quote_handler import QuoteHandler
from features.quote_manager import QuoteManager
from features.watchlist_handler import WatchlistHandler
from features.watchlist_manager import WatchlistManager


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)


def _loc():
    return SimpleNamespace(
        current_lang="no",
        t=lambda key, **values: key if not values else f"{key}:{values}",
    )


def _metrics():
    return SimpleNamespace(record_legacy_payload_fallback=Mock())


def _message(content="SENTINEL RAW CONTENT THAT MUST NOT BE PARSED"):
    return SimpleNamespace(
        content=content,
        guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=456),
        author=SimpleNamespace(id=789, name="Avsender"),
    )


def _base_monitor(**values):
    return SimpleNamespace(
        rate_limiter=object(),
        loc=_loc(),
        client=None,
        nlu_metrics=_metrics(),
        **values,
    )


DELIVERIES = (
    MessageSendResult(DeliveryState.DELIVERED),
    MessageSendResult(DeliveryState.UNKNOWN, "timeout"),
    MessageSendResult(DeliveryState.NOT_DELIVERED, "forbidden"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", DELIVERIES)
async def test_real_quote_edit_is_typed_and_finalizes_all_delivery_states(
    tmp_path,
    monkeypatch,
    delivery,
):
    manager = QuoteManager(tmp_path / "quotes.json")
    seeded = await manager.add_quote_result(123, "Gammel tekst", "Ola")
    assert seeded is True
    monitor = _base_monitor(quote=manager)
    handler = QuoteHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=delivery)
    handler.extract_number = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    handler._extract_edit_fields_from_content = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    monkeypatch.setattr(
        quote_handler_module,
        "parse_quote_command",
        Mock(side_effect=AssertionError("raw content was reparsed")),
    )

    outcome = await handler.handle_quote_edit(
        _message(),
        {
            "action": "edit",
            "index": 1,
            "text": "Ny tekst",
            "author": "Kari",
            "lang": "no",
        },
    )

    assert outcome == DispatchOutcome.success(mutated=True).with_delivery(delivery)
    assert manager.list_quotes(123)[0]["text"] == "Ny tekst"
    assert manager.list_quotes(123)[0]["author"] == "Kari"
    handler.send_response_result.assert_awaited_once()
    handler.extract_number.assert_not_called()
    handler._extract_edit_fields_from_content.assert_not_called()
    quote_handler_module.parse_quote_command.assert_not_called()
    assert monitor.nlu_metrics.record_legacy_payload_fallback.call_count == 0


@pytest.mark.asyncio
async def test_quote_send_cancellation_carries_committed_mutation_truth(tmp_path):
    manager = QuoteManager(tmp_path / "quotes.json")
    await manager.add_quote_result(123, "Gammel", "Ola")
    handler = QuoteHandler(_base_monitor(quote=manager))
    delivery = MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    handler.send_response_result = AsyncMock(
        side_effect=MessageSendCancelled(delivery)
    )

    with pytest.raises(DispatchCancelled) as cancelled:
        await handler.handle_quote_edit(
            _message(),
            {"action": "edit", "index": 1, "text": "Ny", "lang": "no"},
        )

    assert cancelled.value.outcome == DispatchOutcome.success(
        mutated=True
    ).with_delivery(delivery)
    assert manager.list_quotes(123)[0]["text"] == "Ny"
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_quote_none_uses_exactly_one_legacy_parse(tmp_path, monkeypatch):
    manager = QuoteManager(tmp_path / "quotes.json")
    await manager.add_quote_result(123, "Gammel", "Ola")
    monitor = _base_monitor(quote=manager)
    handler = QuoteHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])
    parser = Mock(
        return_value={
            "action": "edit",
            "index": 1,
            "text": "Fra fallback",
            "lang": "no",
        }
    )
    monkeypatch.setattr(quote_handler_module, "parse_quote_command", parser)

    outcome = await handler.handle_quote_edit(
        _message("endre sitat 1 tekst: Fra fallback"),
        None,
    )

    assert outcome.ok is True
    assert manager.list_quotes(123)[0]["text"] == "Fra fallback"
    parser.assert_called_once_with("endre sitat 1 tekst: Fra fallback")
    monitor.nlu_metrics.record_legacy_payload_fallback.assert_called_once_with(
        "quote"
    )


@pytest.mark.asyncio
async def test_fun_quote_save_uses_typed_author_and_async_result(
    tmp_path,
    monkeypatch,
):
    manager = QuoteManager(tmp_path / "quotes.json")
    monitor = _base_monitor(
        quote=manager,
        wod=object(),
        compliments=object(),
        horoscope=object(),
    )
    parser = Mock(side_effect=AssertionError("raw content was reparsed"))
    monkeypatch.setattr(fun_handler_module, "parse_quote_command", parser)
    handler = FunHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_quote_command(
        _message(),
        {
            "action": "save",
            "text": "Sitat",
            "author": "Kari",
            "lang": "no",
        },
    )

    assert outcome == DispatchOutcome.success(mutated=True).with_delivery(
        DELIVERIES[0]
    )
    assert manager.list_quotes(123)[0]["author"] == "Kari"
    parser.assert_not_called()


@pytest.mark.asyncio
async def test_quote_not_found_unknown_delivery_is_terminal(tmp_path):
    manager = QuoteManager(tmp_path / "quotes.json")
    handler = QuoteHandler(_base_monitor(quote=manager))
    unknown = MessageSendResult(DeliveryState.UNKNOWN, "timeout")
    handler.send_response_result = AsyncMock(return_value=unknown)

    outcome = await handler.handle_quote_delete(
        _message(),
        {"action": "delete", "index": 1, "lang": "no"},
    )

    assert outcome.ok is False
    assert outcome.error_code == "not_found"
    assert outcome.mutated is False
    assert outcome.retryable is False
    assert outcome.delivery_result == unknown
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchlist_typed_add_edit_remove_never_reparse(
    tmp_path,
    monkeypatch,
):
    manager = WatchlistManager(tmp_path / "watchlist.json")
    monitor = _base_monitor(watchlist=manager)
    handler = WatchlistHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])
    parser = Mock(side_effect=AssertionError("raw content was reparsed"))
    monkeypatch.setattr(
        watchlist_handler_module,
        "parse_watchlist_command",
        parser,
    )
    message = _message()

    added = await handler.handle_watchlist(
        message,
        {
            "action": "add",
            "title": "Arrival",
            "type": "movie",
            "genre": "Sci-Fi",
            "lang": "no",
        },
    )
    edited = await handler.handle_watchlist_edit(
        message,
        {
            "action": "edit",
            "index": 1,
            "title": "Arrival (2016)",
            "lang": "no",
        },
    )
    removed = await handler.handle_watchlist_remove(
        message,
        {"action": "remove", "index": 1, "lang": "no"},
    )

    expected = DispatchOutcome.success(mutated=True).with_delivery(DELIVERIES[0])
    assert added == expected
    assert edited == expected
    assert removed == expected
    assert manager.get_watchlist(123) == []
    parser.assert_not_called()
    assert handler.send_response_result.await_count == 3


@pytest.mark.asyncio
async def test_watchlist_false_and_none_results_are_nonmutating_failures(
    monkeypatch,
):
    manager = SimpleNamespace(
        add_watchlist_result=AsyncMock(return_value=False),
        edit_watchlist_result=AsyncMock(return_value=None),
    )
    handler = WatchlistHandler(_base_monitor(watchlist=manager))
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])
    monkeypatch.setattr(
        watchlist_handler_module,
        "parse_watchlist_command",
        Mock(side_effect=AssertionError("raw content was reparsed")),
    )

    added = await handler.handle_watchlist(
        _message(),
        {"action": "add", "title": "Arrival", "lang": "no"},
    )
    edited = await handler.handle_watchlist_edit(
        _message(),
        {"action": "edit", "index": 1, "title": "Ny", "lang": "no"},
    )

    assert added.ok is False and added.mutated is False
    assert added.error_code == "manager_rejected"
    assert edited.ok is False and edited.mutated is False
    assert edited.error_code == "not_found"


@pytest.mark.asyncio
async def test_watchlist_edit_forwards_only_present_fields_and_can_clear_null(
    tmp_path,
):
    manager = WatchlistManager(tmp_path / "watchlist.json")
    await manager.add_watchlist_result(
        "Arrival",
        content_type="movie",
        guild_id=123,
        genre="Sci-Fi",
        comment="Se igjen",
    )
    handler = WatchlistHandler(_base_monitor(watchlist=manager))
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_watchlist_edit(
        _message(),
        {
            "action": "edit",
            "index": 1,
            "genre": None,
            "lang": "no",
        },
    )

    assert outcome == DispatchOutcome.success(mutated=True).with_delivery(
        DELIVERIES[0]
    )
    item = manager.get_watchlist(123)[0]
    assert item["genre"] is None
    assert item["comment"] == "Se igjen"
    assert item["title"] == "Arrival"


@pytest.mark.asyncio
async def test_watchlist_reads_are_truthful_and_side_effect_free(tmp_path):
    manager = WatchlistManager(tmp_path / "watchlist.json")
    monitor = _base_monitor(watchlist=manager)
    handler = WatchlistHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])
    before = deepcopy(manager.watchlist)

    status = await handler.handle_watchlist(
        _message(),
        {"action": "status", "lang": "no"},
    )
    suggestion = await handler.handle_watchlist(
        _message(),
        {"action": "suggest", "type": "movie", "lang": "no"},
    )

    expected = DispatchOutcome.success(mutated=False).with_delivery(DELIVERIES[0])
    assert status == expected
    assert suggestion == expected
    assert manager.watchlist == before


@pytest.mark.asyncio
async def test_poll_target_snapshot_failure_is_bounded_and_not_retried():
    snapshot = Mock(side_effect=RuntimeError("private storage detail"))
    manager = SimpleNamespace(
        clock=SimpleNamespace(now=lambda: NOW),
        _require_aware=lambda value: value,
        snapshot_pending_items=snapshot,
        delete_poll_result=AsyncMock(),
    )
    handler = PollsHandler(_base_monitor(poll=manager))
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_poll_delete(
        _message(),
        {"target": 1},
        reference_time=NOW,
    )

    assert outcome.error_code == "manager_rejected"
    assert outcome.mutated is False
    assert outcome.retryable is True
    assert outcome.response_sent is True
    snapshot.assert_called_once_with(123, reference_time=NOW)
    manager.delete_poll_result.assert_not_awaited()
    handler.send_response_result.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ("poll", "watchlist", "quote"))
async def test_storage_rollback_maps_to_retryable_nonmutation(
    family,
):
    error = ManagerMutationError("storage_write_failed", mutated=False)
    if family == "poll":
        manager = SimpleNamespace(
            clock=SimpleNamespace(now=lambda: NOW),
            _require_aware=lambda value: value,
            create_poll_result=AsyncMock(side_effect=error),
        )
        handler = PollsHandler(
            _base_monitor(
                poll=manager,
                parse_poll_command=Mock(
                    side_effect=AssertionError("raw content was reparsed")
                ),
            )
        )
        call = handler.handle_poll(
            _message(),
            {"question": "Velg?", "options": ["A", "B"]},
            reference_time=NOW,
        )
    elif family == "watchlist":
        manager = SimpleNamespace(
            add_watchlist_result=AsyncMock(side_effect=error)
        )
        handler = WatchlistHandler(_base_monitor(watchlist=manager))
        call = handler.handle_watchlist(
            _message(),
            {"action": "add", "title": "Arrival", "lang": "no"},
        )
    else:
        manager = SimpleNamespace(
            update_quote_result=AsyncMock(side_effect=error)
        )
        handler = QuoteHandler(_base_monitor(quote=manager))
        call = handler.handle_quote_edit(
            _message(),
            {"action": "edit", "index": 1, "text": "Ny", "lang": "no"},
        )
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await call

    assert outcome.ok is False
    assert outcome.error_code == "storage_write_failed"
    assert outcome.mutated is False
    assert outcome.retryable is True
    assert outcome.commit_unknown is False
    assert outcome.response_sent is True


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ("poll", "watchlist", "quote", "quote_save"))
async def test_unbounded_auxiliary_manager_errors_fail_closed(family):
    error = ManagerMutationError("provider_secret_detail", mutated=True)
    if family == "poll":
        manager = SimpleNamespace(
            clock=SimpleNamespace(now=lambda: NOW),
            _require_aware=lambda value: value,
            create_poll_result=AsyncMock(side_effect=error),
        )
        handler = PollsHandler(
            _base_monitor(
                poll=manager,
                parse_poll_command=Mock(
                    side_effect=AssertionError("raw content was reparsed")
                ),
            )
        )
        call = handler.handle_poll(
            _message(),
            {"question": "Velg?", "options": ["A", "B"]},
            reference_time=NOW,
        )
    elif family == "watchlist":
        manager = SimpleNamespace(
            add_watchlist_result=AsyncMock(side_effect=error)
        )
        handler = WatchlistHandler(_base_monitor(watchlist=manager))
        call = handler.handle_watchlist(
            _message(),
            {"action": "add", "title": "Arrival", "lang": "no"},
        )
    elif family == "quote":
        manager = SimpleNamespace(
            update_quote_result=AsyncMock(side_effect=error)
        )
        handler = QuoteHandler(_base_monitor(quote=manager))
        call = handler.handle_quote_edit(
            _message(),
            {"action": "edit", "index": 1, "text": "Ny", "lang": "no"},
        )
    else:
        manager = SimpleNamespace(
            add_quote_result=AsyncMock(side_effect=error)
        )
        handler = FunHandler(
            _base_monitor(
                quote=manager,
                wod=object(),
                compliments=object(),
                horoscope=object(),
            )
        )
        call = handler.handle_quote_command(
            _message(),
            {"action": "save", "text": "Sitat", "lang": "no"},
        )
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await call

    assert outcome.ok is False
    assert outcome.error_code == "commit_state_unknown"
    assert outcome.mutated is True
    assert outcome.retryable is False
    assert outcome.commit_unknown is True
    assert outcome.response_sent is True


@pytest.mark.asyncio
async def test_poll_typed_vote_uses_frozen_active_id_and_reference_time(
    tmp_path,
):
    manager = PollManager(tmp_path / "polls.json")
    poll = await manager.create_poll_result(
        123,
        "Velg?",
        ["A", "B"],
        "Avsender",
        created_by_id=789,
        reference_time=NOW,
    )
    monitor = _base_monitor(
        poll=manager,
        parse_vote=Mock(side_effect=AssertionError("raw content was reparsed")),
        parse_poll_command=Mock(
            side_effect=AssertionError("raw content was reparsed")
        ),
    )
    handler = PollsHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_vote(
        _message(),
        {"option": 2, "poll_id": poll["id"]},
        reference_time=NOW,
    )

    assert outcome == DispatchOutcome.success(mutated=True).with_delivery(
        DELIVERIES[0]
    )
    stored = manager.get_poll(123, poll["id"])
    assert stored["options"][1]["votes"] == ["789"]
    monitor.parse_vote.assert_not_called()


@pytest.mark.asyncio
async def test_poll_expired_frozen_id_is_rejected_before_vote(tmp_path):
    manager = PollManager(tmp_path / "polls.json")
    poll = await manager.create_poll_result(
        123,
        "Gammel?",
        ["A", "B"],
        "Avsender",
        created_by_id=789,
        reference_time=NOW - timedelta(days=8),
    )
    original_vote = manager.vote_result
    manager.vote_result = AsyncMock(wraps=original_vote)
    handler = PollsHandler(
        _base_monitor(
            poll=manager,
            parse_vote=Mock(side_effect=AssertionError("raw content was reparsed")),
        )
    )
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_vote(
        _message(),
        {"option": 1, "poll_id": poll["id"]},
        reference_time=NOW,
    )

    assert outcome.ok is False
    assert outcome.mutated is False
    assert outcome.error_code == "manager_rejected"
    manager.vote_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_create_uses_typed_payload_and_turn_reference(tmp_path):
    manager = PollManager(tmp_path / "polls.json")
    monitor = _base_monitor(
        poll=manager,
        parse_poll_command=Mock(
            side_effect=AssertionError("raw content was reparsed")
        ),
    )
    handler = PollsHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_poll(
        _message(),
        {"question": "Velg?", "options": ["A", "B"], "lang": "no"},
        reference_time=NOW,
    )

    assert outcome == DispatchOutcome.success(mutated=True).with_delivery(
        DELIVERIES[0]
    )
    stored = manager.get_active_polls(123, reference_time=NOW)
    assert len(stored) == 1
    assert stored[0]["created_at"] == NOW.isoformat()
    monitor.parse_poll_command.assert_not_called()


@pytest.mark.asyncio
async def test_poll_edit_close_delete_use_async_result_adapters(tmp_path):
    manager = PollManager(tmp_path / "polls.json")
    edit_poll = await manager.create_poll_result(
        123,
        "Gammel?",
        ["A", "B"],
        "Avsender",
        created_by_id=789,
        reference_time=NOW,
    )
    close_poll = await manager.create_poll_result(
        123,
        "Lukk?",
        ["A", "B"],
        "Avsender",
        created_by_id=789,
        reference_time=NOW,
    )
    delete_poll = await manager.create_poll_result(
        123,
        "Slett?",
        ["A", "B"],
        "Avsender",
        created_by_id=789,
        reference_time=NOW,
    )
    monitor = _base_monitor(poll=manager)
    handler = PollsHandler(monitor)
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])
    handler._legacy_target = Mock(
        side_effect=AssertionError("raw content was reparsed")
    )
    message = _message()

    edited = await handler.handle_poll_edit(
        message,
        {
            "poll_id": edit_poll["id"],
            "question": "Ny?",
            "options": ["Ja", "Nei"],
        },
        reference_time=NOW,
    )
    closed = await handler.handle_poll_close(
        message,
        {"poll_id": close_poll["id"]},
        reference_time=NOW,
    )
    deleted = await handler.handle_poll_delete(
        message,
        {"poll_id": delete_poll["id"]},
        reference_time=NOW,
    )

    expected = DispatchOutcome.success(mutated=True).with_delivery(DELIVERIES[0])
    assert edited == expected
    assert closed == expected
    assert deleted == expected
    assert manager.get_poll(123, edit_poll["id"])["question"] == "Ny?"
    assert manager.get_poll(123, close_poll["id"])["status"] == "closed"
    assert manager.get_poll(123, delete_poll["id"]) is None
    assert handler.send_response_result.await_count == 3
    handler._legacy_target.assert_not_called()


@pytest.mark.asyncio
async def test_poll_manager_rejection_does_not_claim_mutation(tmp_path):
    manager = PollManager(tmp_path / "polls.json")
    poll = await manager.create_poll_result(
        123,
        "Eid av noen andre?",
        ["A", "B"],
        "Eier",
        created_by_id=1,
        reference_time=NOW,
    )
    handler = PollsHandler(_base_monitor(poll=manager))
    handler.send_response_result = AsyncMock(return_value=DELIVERIES[0])

    outcome = await handler.handle_poll_edit(
        _message(),
        {"poll_id": poll["id"], "question": "Uautorisert?"},
        reference_time=NOW,
    )

    assert outcome.ok is False
    assert outcome.mutated is False
    assert outcome.error_code == "manager_rejected"
    assert manager.get_poll(123, poll["id"])["question"] == "Eid av noen andre?"
