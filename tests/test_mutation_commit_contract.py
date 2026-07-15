"""Transactional persistence contracts for JSON-backed domain managers."""

from __future__ import annotations

import ast
import asyncio
import copy
import json
import threading
import textwrap
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MutationCoordinator
from features.poll_manager import PollManager
from features.quote_manager import QuoteManager
from features.watchlist_manager import WatchlistManager


OSLO = ZoneInfo("Europe/Oslo")
FIXED_NOW = datetime(2026, 7, 15, 9, 30, tzinfo=OSLO)


class FixedClock:
    def __init__(self, value=FIXED_NOW):
        self.value = value
        self.now_calls = 0

    def now(self):
        self.now_calls += 1
        return self.value

    def epoch(self):
        return self.value.timestamp()


def assert_storage_rollback(manager, before_root, before_bytes):
    root = (
        manager.polls
        if isinstance(manager, PollManager)
        else manager.watchlist
        if isinstance(manager, WatchlistManager)
        else manager.quotes
    )
    assert root == before_root
    assert manager.storage_path.read_bytes() == before_bytes


def install_failing_writer(manager, private_name):
    def fail(_candidate):
        raise OSError("sentinel")

    setattr(manager, private_name, fail)


@pytest.mark.asyncio
async def test_poll_create_and_delete_roll_back_on_atomic_writer_failure(tmp_path):
    manager = PollManager(tmp_path / "polls.json")
    seeded = await manager.create_poll_result(
        1,
        "Første?",
        ["Ja", "Nei"],
        "Ola",
        created_by_id=7,
        reference_time=FIXED_NOW,
    )
    before_root = copy.deepcopy(manager.polls)
    before_bytes = manager.storage_path.read_bytes()
    install_failing_writer(manager, "_save_polls")

    with pytest.raises(ManagerMutationError) as created:
        await manager.create_poll_result(
            2,
            "Andre?",
            ["A", "B"],
            "Kari",
            reference_time=FIXED_NOW,
        )
    assert created.value.code == "storage_write_failed"
    assert created.value.mutated is False
    assert created.value.commit_unknown is False
    assert_storage_rollback(manager, before_root, before_bytes)

    with pytest.raises(ManagerMutationError) as deleted:
        await manager.delete_poll_result(1, seeded["id"], 7, "Ola")
    assert deleted.value.code == "storage_write_failed"
    assert deleted.value.mutated is False
    assert deleted.value.commit_unknown is False
    assert_storage_rollback(manager, before_root, before_bytes)


@pytest.mark.asyncio
async def test_watchlist_create_and_update_roll_back_on_writer_failure(tmp_path):
    manager = WatchlistManager(tmp_path / "watchlist.json")
    assert await manager.add_watchlist_result("Arrival", guild_id=1) is True
    before_root = copy.deepcopy(manager.watchlist)
    before_bytes = manager.storage_path.read_bytes()
    install_failing_writer(manager, "_save_watchlist")

    with pytest.raises(ManagerMutationError) as created:
        await manager.add_watchlist_result("Dark", content_type="series", guild_id=2)
    assert created.value.code == "storage_write_failed"
    assert created.value.mutated is False
    assert_storage_rollback(manager, before_root, before_bytes)

    with pytest.raises(ManagerMutationError) as edited:
        await manager.edit_watchlist_result(1, title="Arrival 2", guild_id=1)
    assert edited.value.code == "storage_write_failed"
    assert edited.value.mutated is False
    assert_storage_rollback(manager, before_root, before_bytes)


@pytest.mark.asyncio
async def test_quote_create_and_delete_roll_back_on_writer_failure(tmp_path):
    manager = QuoteManager(tmp_path / "quotes.json")
    assert await manager.add_quote_result(1, "Første", "Ola") is True
    before_root = copy.deepcopy(manager.quotes)
    before_bytes = manager.storage_path.read_bytes()
    install_failing_writer(manager, "_save_quotes")

    with pytest.raises(ManagerMutationError) as created:
        await manager.add_quote_result(2, "Andre", "Kari")
    assert created.value.code == "storage_write_failed"
    assert created.value.mutated is False
    assert_storage_rollback(manager, before_root, before_bytes)

    with pytest.raises(ManagerMutationError) as deleted:
        await manager.delete_quote_result(1, 1)
    assert deleted.value.code == "storage_write_failed"
    assert deleted.value.mutated is False
    assert_storage_rollback(manager, before_root, before_bytes)


@pytest.mark.asyncio
async def test_every_auxiliary_result_api_preserves_historical_success_shapes(tmp_path):
    poll = PollManager(tmp_path / "polls.json")
    first = await poll.create_poll_result(
        1,
        "Pizza?",
        ["Ja", "Nei"],
        "Ola",
        created_by_id=7,
        reference_time=FIXED_NOW,
    )
    assert (await poll.vote_result(1, first["id"], 2, 8, "Kari"))[0] is True
    edited = await poll.edit_poll_result(
        1,
        first["id"],
        7,
        "Ola",
        question="Taco?",
    )
    assert edited[0] is True
    assert edited[1]["question"] == "Taco?"
    assert (await poll.close_poll_result(1, first["id"], 7, "Ola"))[0] is True
    second = await poll.create_poll_result(
        1,
        "Slette?",
        ["Ja", "Nei"],
        "Ola",
        created_by_id=7,
        reference_time=FIXED_NOW,
    )
    assert (await poll.delete_poll_result(1, second["id"], 7, "Ola")) == (
        True,
        "Poll deleted",
    )

    watchlist = WatchlistManager(tmp_path / "watchlist.json")
    assert await watchlist.add_watchlist_result("Arrival", guild_id=1) is True
    assert await watchlist.add_watchlist_result(
        "Dark", content_type="series", guild_id=1
    ) is True
    watch_edit = await watchlist.edit_watchlist_result(
        1,
        title="Arrival 2",
        guild_id=1,
    )
    assert watch_edit["title"] == "Arrival 2"
    await watchlist.edit_watchlist_result(
        1,
        genre="Sci-Fi",
        comment="Se snart",
        guild_id=1,
    )
    watch_clear = await watchlist.edit_watchlist_result(
        1,
        genre=None,
        comment=None,
        guild_id=1,
    )
    assert watch_clear["genre"] is None
    assert watch_clear["comment"] is None
    removed = await watchlist.remove_watchlist_result(2, guild_id=1)
    assert removed["title"] == "Dark"

    quote = QuoteManager(tmp_path / "quotes.json")
    assert await quote.add_quote_result(1, "Første", "Ola") is True
    assert await quote.add_quote_result(1, "Andre", "Kari") is True
    assert await quote.update_quote_result(1, 1, author="Per") is True
    assert quote.list_quotes(1)[0]["author"] == "Per"
    assert await quote.delete_quote_result(1, 2) is True


@pytest.mark.asyncio
async def test_snapshots_are_ordered_detached_and_missing_scope_is_inert(tmp_path):
    poll = PollManager(tmp_path / "polls.json")
    poll_row = await poll.create_poll_result(
        10,
        "Pizza?",
        ["Ja", "Nei"],
        "Ola",
        reference_time=FIXED_NOW,
    )
    poll_before = copy.deepcopy(poll.polls)
    poll_snapshot = poll.snapshot_pending_items(10, reference_time=FIXED_NOW)
    assert poll_snapshot[0]["poll_id"] == poll_row["id"]
    poll_snapshot[0]["options"][0]["text"] = "MUTATED"
    assert poll.polls == poll_before
    assert poll.snapshot_pending_items(
        10,
        reference_time=FIXED_NOW + timedelta(days=7),
    ) == ()

    watchlist = WatchlistManager(tmp_path / "watchlist.json")
    await watchlist.add_watchlist_result("Serie", content_type="series", guild_id=10)
    await watchlist.add_watchlist_result("Film", content_type="movie", guild_id=10)
    watch_before = copy.deepcopy(watchlist.watchlist)
    watch_snapshot = watchlist.snapshot_pending_items(10)
    assert [row["title"] for row in watch_snapshot] == ["Film", "Serie"]
    watch_snapshot[0]["title"] = "MUTATED"
    assert watchlist.watchlist == watch_before

    quote = QuoteManager(tmp_path / "quotes.json")
    await quote.add_quote_result(10, "Første", "Ola")
    await quote.add_quote_result(10, "Andre", "Kari")
    quote_before = copy.deepcopy(quote.quotes)
    quote_snapshot = quote.snapshot_pending_items(10)
    assert [row["text"] for row in quote_snapshot] == ["Første", "Andre"]
    quote_snapshot[0]["text"] = "MUTATED"
    assert quote.quotes == quote_before

    roots_before = (
        copy.deepcopy(poll.polls),
        copy.deepcopy(watchlist.watchlist),
        copy.deepcopy(quote.quotes),
    )
    bytes_before = (
        poll.storage_path.read_bytes(),
        watchlist.storage_path.read_bytes(),
        quote.storage_path.read_bytes(),
    )
    assert poll.snapshot_pending_items(999, reference_time=FIXED_NOW) == ()
    assert watchlist.snapshot_pending_items(999) == ()
    assert quote.snapshot_pending_items(999) == ()
    assert watchlist.get_watchlist(999) == []
    assert watchlist.get_watchlist_summary(999) == {
        "movies_total": 0,
        "movies_unwatched": 0,
        "series_total": 0,
        "series_unwatched": 0,
    }
    assert (poll.polls, watchlist.watchlist, quote.quotes) == roots_before
    assert (
        poll.storage_path.read_bytes(),
        watchlist.storage_path.read_bytes(),
        quote.storage_path.read_bytes(),
    ) == bytes_before


async def exercise_blocked_cross_scope_writes(manager, first_call, second_call, root):
    private_name = (
        "_save_polls"
        if isinstance(manager, PollManager)
        else "_save_watchlist"
        if isinstance(manager, WatchlistManager)
        else "_save_quotes"
    )
    original = getattr(manager, private_name)
    entered = threading.Event()
    release = threading.Event()
    writes = []
    before_root = copy.deepcopy(root())

    def blocked(candidate):
        writes.append(copy.deepcopy(candidate))
        if len(writes) == 1:
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("writer barrier")
        original(candidate)

    setattr(manager, private_name, blocked)
    first = asyncio.create_task(first_call())
    assert await asyncio.to_thread(entered.wait, 2)
    second = asyncio.create_task(second_call())
    await asyncio.sleep(0.03)
    assert second.done() is False
    assert root() == before_root
    release.set()
    await asyncio.gather(first, second)
    assert len(writes) == 2
    assert json.loads(manager.storage_path.read_text(encoding="utf-8")) == root()


@pytest.mark.asyncio
async def test_shared_store_scope_serializes_cross_guild_writers_fifo(tmp_path):
    poll = PollManager(tmp_path / "polls.json")
    await exercise_blocked_cross_scope_writes(
        poll,
        lambda: poll.create_poll_result(
            1, "En?", ["A", "B"], "Ola", reference_time=FIXED_NOW
        ),
        lambda: poll.create_poll_result(
            2, "To?", ["A", "B"], "Kari", reference_time=FIXED_NOW
        ),
        lambda: poll.polls,
    )
    assert set(poll.polls) == {"1", "2"}

    watchlist = WatchlistManager(tmp_path / "watchlist.json")
    await exercise_blocked_cross_scope_writes(
        watchlist,
        lambda: watchlist.add_watchlist_result("En", guild_id=1),
        lambda: watchlist.add_watchlist_result("To", guild_id=2),
        lambda: watchlist.watchlist,
    )
    assert set(watchlist.watchlist["scopes"]) == {"1", "2"}

    quote = QuoteManager(tmp_path / "quotes.json")
    await exercise_blocked_cross_scope_writes(
        quote,
        lambda: quote.add_quote_result(1, "En", "Ola"),
        lambda: quote.add_quote_result(2, "To", "Kari"),
        lambda: quote.quotes,
    )
    assert set(quote.quotes) == {"1", "2"}


@pytest.mark.asyncio
async def test_cancelled_owned_writer_settles_then_publishes_exact_truth(tmp_path):
    manager = QuoteManager(tmp_path / "quotes.json")
    original = manager._save_quotes
    entered = threading.Event()
    release = threading.Event()

    def blocked(candidate):
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("writer barrier")
        original(candidate)

    manager._save_quotes = blocked
    task = asyncio.create_task(manager.add_quote_result(1, "En", "Ola"))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0.03)
    assert task.done() is False
    assert manager.quotes == {}
    release.set()
    with pytest.raises(ManagerMutationCancelled) as cancelled:
        await task
    assert cancelled.value.code == "cancelled"
    assert cancelled.value.mutated is True
    assert cancelled.value.retryable is False
    assert cancelled.value.commit_unknown is False
    assert manager.quotes["1"][0]["text"] == "En"
    assert json.loads(manager.storage_path.read_text(encoding="utf-8")) == manager.quotes


@pytest.mark.asyncio
async def test_cancelled_failed_writer_retains_prewrite_retryable_truth(tmp_path):
    manager = QuoteManager(tmp_path / "quotes.json")
    await manager.add_quote_result(1, "Første", "Ola")
    before_root = copy.deepcopy(manager.quotes)
    before_bytes = manager.storage_path.read_bytes()
    entered = threading.Event()
    release = threading.Event()

    def blocked_failure(_candidate):
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("writer barrier")
        raise OSError("sentinel")

    manager._save_quotes = blocked_failure
    task = asyncio.create_task(manager.update_quote_result(1, 1, text="Ny"))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(ManagerMutationCancelled) as cancelled:
        await task
    assert cancelled.value.code == "storage_write_failed"
    assert cancelled.value.mutated is False
    assert cancelled.value.retryable is True
    assert cancelled.value.commit_unknown is False
    assert_storage_rollback(manager, before_root, before_bytes)


@pytest.mark.asyncio
async def test_independently_cancelled_writer_is_commit_unknown(
    tmp_path,
    monkeypatch,
):
    manager = QuoteManager(tmp_path / "quotes.json")

    async def cancel_owned_work(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "to_thread", cancel_owned_work)

    with pytest.raises(ManagerMutationCancelled) as cancelled:
        await manager.add_quote_result(1, "En", "Ola")

    assert cancelled.value.code == "commit_state_unknown"
    assert cancelled.value.mutated is False
    assert cancelled.value.retryable is False
    assert cancelled.value.commit_unknown is True
    assert manager.quotes == {}
    assert not manager.storage_path.exists()


@pytest.mark.asyncio
async def test_sync_mutation_wrappers_reject_inside_running_loop(tmp_path):
    poll = PollManager(tmp_path / "polls.json")
    watchlist = WatchlistManager(tmp_path / "watchlist.json")
    quote = QuoteManager(tmp_path / "quotes.json")
    calls = (
        lambda: poll.create_poll(1, "Q?", ["A", "B"], "Ola"),
        lambda: poll.vote(1, "missing", 1, 7, "Ola"),
        lambda: poll.edit_poll(1, "missing", 7),
        lambda: poll.delete_poll(1, "missing", 7),
        lambda: poll.close_poll(1, "missing"),
        lambda: watchlist.add_from_discord_message("Arrival", guild_id=1),
        lambda: watchlist.edit_watchlist_entry(1, title="Ny", guild_id=1),
        lambda: watchlist.remove_from_watchlist(1, guild_id=1),
        lambda: watchlist.mark_as_watched("Arrival", guild_id=1),
        lambda: quote.add_quote(1, "En", "Ola"),
        lambda: quote.update_quote(1, 1, text="Ny"),
        lambda: quote.delete_quote(1, 1),
    )
    for call in calls:
        with pytest.raises(RuntimeError) as rejected:
            call()
        assert rejected.value.args == ("use_async_result_api",)


def test_positional_constructors_offline_projections_and_dependency_identity(tmp_path):
    coordinator = MutationCoordinator()
    clock = FixedClock()
    poll = PollManager(
        tmp_path / "polls.json",
        clock=clock,
        mutation_coordinator=coordinator,
    )
    watchlist = WatchlistManager(
        tmp_path / "watchlist.json",
        mutation_coordinator=coordinator,
    )
    quote = QuoteManager(
        tmp_path / "quotes.json",
        mutation_coordinator=coordinator,
    )
    assert poll.clock is clock
    assert poll.mutation_coordinator is coordinator
    assert watchlist.mutation_coordinator is coordinator
    assert quote.mutation_coordinator is coordinator

    created = poll.create_poll(1, "Q?", ["A", "B"], "Ola")
    assert clock.now_calls == 1
    assert created["created_at"] == FIXED_NOW.isoformat()
    assert watchlist.add_from_discord_message("Arrival", guild_id=1) is True
    assert quote.add_quote(1, "En", "Ola") is True


@pytest.mark.asyncio
async def test_poll_result_and_snapshot_require_aware_reference_time(tmp_path):
    manager = PollManager(tmp_path / "polls.json")
    naive = datetime(2026, 7, 15, 9, 30)
    with pytest.raises(ValueError) as create_error:
        await manager.create_poll_result(
            1, "Q?", ["A", "B"], "Ola", reference_time=naive
        )
    assert create_error.value.args == ("reference_time_must_be_aware",)
    with pytest.raises(ValueError) as snapshot_error:
        manager.snapshot_pending_items(1, reference_time=naive)
    assert snapshot_error.value.args == ("reference_time_must_be_aware",)
    assert manager.polls == {}


def test_no_auxiliary_writer_bypasses_transaction_commit_helper():
    for manager_type, private_name in (
        (PollManager, "_save_polls"),
        (WatchlistManager, "_save_watchlist"),
        (QuoteManager, "_save_quotes"),
    ):
        tree = ast.parse(textwrap.dedent(inspect_source(manager_type)))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == private_name
            and isinstance(node.ctx, ast.Load)
        ]
        assert len(calls) == 1


def inspect_source(value):
    import inspect

    return inspect.getsource(value)
