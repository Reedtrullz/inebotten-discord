"""Transactional contracts for the Task 3 ReminderManager foundation."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cal_system.reminder_checker import ReminderChecker
from cal_system.reminder_manager import ReminderManager
from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MutationCoordinator


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 9, 30, tzinfo=OSLO)


class FixedClock:
    def __init__(self, value=NOW):
        self.value = value
        self.now_calls = 0

    def now(self):
        self.now_calls += 1
        return self.value

    def epoch(self):
        return self.value.timestamp()


async def seed_manager(path):
    manager = ReminderManager(path)
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Første",
        reference_time=NOW,
    )
    return manager, reminder_id


def assert_storage_rollback(manager, before_root, before_bytes):
    assert manager.reminders == before_root
    assert manager.storage_path.read_bytes() == before_bytes


def install_failing_writer(manager):
    def fail(_candidate):
        raise OSError("sentinel")

    manager._save_reminders = fail


def test_constructor_injection_is_additive_for_manager_and_checker(tmp_path):
    clock = FixedClock()
    coordinator = MutationCoordinator()
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=clock,
        mutation_coordinator=coordinator,
    )
    checker = ReminderChecker(
        manager,
        storage_path=tmp_path / "sent.json",
        clock=clock,
        mutation_coordinator=coordinator,
    )

    assert manager.clock is clock
    assert manager.mutation_coordinator is coordinator
    assert checker.clock is clock
    assert checker.mutation_coordinator is coordinator


@pytest.mark.parametrize(
    "bucket",
    [
        "malformed",
        ["malformed"],
        [{"id": "rem-1", "text": "Bad", "completed": ""}],
        [{"id": "rem-1", "text": "Bad", "completed": 0}],
    ],
)
def test_pending_snapshot_rejects_corrupt_reminder_state(tmp_path, bucket):
    manager = ReminderManager(tmp_path / "reminders.json")
    manager.reminders = {"1": bucket}

    with pytest.raises(ValueError, match="invalid_target_state"):
        manager.snapshot_pending_items(1)


@pytest.mark.asyncio
async def test_result_apis_require_an_aware_reference_before_mutation(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    naive = datetime(2026, 7, 15, 9, 30)

    with pytest.raises(TypeError):
        await manager.add_reminder_result(1, 7, "Ola", "Mangler")
    with pytest.raises(ValueError, match="reference_time_must_be_aware"):
        await manager.add_reminder_result(
            1,
            7,
            "Ola",
            "Naiv",
            reference_time=naive,
        )

    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Første",
        reference_time=NOW,
    )
    before = copy.deepcopy(manager.reminders)
    before_bytes = manager.storage_path.read_bytes()

    calls = (
        lambda: manager.edit_reminder_result(
            1,
            1,
            title="Naiv",
            reference_time=naive,
        ),
        lambda: manager.complete_reminder_result(
            1,
            reminder_id=reminder_id,
            reference_time=naive,
        ),
        lambda: manager.delete_reminder_result(
            1,
            reminder_id,
            reference_time=naive,
        ),
    )
    for call in calls:
        with pytest.raises(ValueError, match="reference_time_must_be_aware"):
            await call()

    assert_storage_rollback(manager, before, before_bytes)


@pytest.mark.asyncio
async def test_result_apis_preserve_historical_success_shapes(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    first_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Første",
        reference_time=NOW,
    )
    assert isinstance(first_id, str)
    assert manager.reminders["1"][0]["created_at"] == NOW.isoformat()

    edited = await manager.edit_reminder_result(
        1,
        reminder_id=first_id,
        title="Oppdatert",
        reference_time=NOW,
    )
    assert edited["id"] == first_id
    assert edited["text"] == "Oppdatert"

    completed = await manager.complete_reminder_result(
        1,
        reminder_id=first_id,
        reference_time=NOW,
    )
    assert completed == (True, "Oppdatert", None)
    assert manager.reminders["1"][0]["completed_at"] == NOW.isoformat()

    second_id = await manager.add_reminder_result(
        1,
        8,
        "Kari",
        "Andre",
        reference_time=NOW,
    )
    assert await manager.delete_reminder_result(
        1,
        second_id,
        reference_time=NOW,
    ) is True
    assert await manager.delete_reminder_result(
        1,
        "rem_1_missing",
        reference_time=NOW,
    ) is False


@pytest.mark.asyncio
async def test_completed_filter_uses_supplied_aware_reference_without_clock_read(
    tmp_path,
):
    clock = FixedClock(NOW.replace(year=2030))
    manager = ReminderManager(tmp_path / "reminders.json", clock=clock)
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Første",
        reference_time=NOW,
    )
    await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=NOW,
    )

    completed = manager.get_completed_reminders(
        1,
        days=3,
        reference_time=NOW,
    )
    formatted = manager.format_reminders_list(
        1,
        show_completed=True,
        reference_time=NOW,
    )

    assert [row["id"] for row in completed] == [reminder_id]
    assert "Første" in formatted
    assert clock.now_calls == 0


@pytest.mark.parametrize("operation", ("create", "edit", "complete", "delete"))
@pytest.mark.asyncio
async def test_every_result_write_rolls_back_root_and_bytes_on_save_failure(
    tmp_path,
    operation,
):
    manager, reminder_id = await seed_manager(tmp_path / f"{operation}.json")
    before_root = copy.deepcopy(manager.reminders)
    before_bytes = manager.storage_path.read_bytes()
    install_failing_writer(manager)

    calls = {
        "create": lambda: manager.add_reminder_result(
            2,
            8,
            "Kari",
            "Andre",
            reference_time=NOW,
        ),
        "edit": lambda: manager.edit_reminder_result(
            1,
            reminder_id=reminder_id,
            title="Skal rulles tilbake",
            reference_time=NOW,
        ),
        "complete": lambda: manager.complete_reminder_result(
            1,
            reminder_id=reminder_id,
            reference_time=NOW,
        ),
        "delete": lambda: manager.delete_reminder_result(
            1,
            reminder_id,
            reference_time=NOW,
        ),
    }

    with pytest.raises(ManagerMutationError) as failure:
        await calls[operation]()

    assert failure.value.code == "storage_write_failed"
    assert failure.value.mutated is False
    assert failure.value.commit_unknown is False
    assert_storage_rollback(manager, before_root, before_bytes)


@pytest.mark.asyncio
async def test_blocked_cross_scope_writer_exposes_old_then_complete_roots(tmp_path):
    path = tmp_path / "reminders.json"
    manager = ReminderManager(path)
    original_save = manager._save_reminders
    entered = threading.Event()
    release = threading.Event()
    save_count = 0

    def blocking_save(candidate):
        nonlocal save_count
        save_count += 1
        if save_count == 1:
            entered.set()
            assert release.wait(5)
        original_save(candidate)

    manager._save_reminders = blocking_save
    first = asyncio.create_task(
        manager.add_reminder_result(
            1,
            7,
            "Ola",
            "Første",
            reference_time=NOW,
        )
    )
    assert await asyncio.to_thread(entered.wait, 2)
    assert manager.snapshot_pending_items(1) == ()

    second = asyncio.create_task(
        manager.add_reminder_result(
            2,
            8,
            "Kari",
            "Andre",
            reference_time=NOW,
        )
    )
    await asyncio.sleep(0)
    assert not second.done()
    assert manager.snapshot_pending_items(2) == ()

    release.set()
    await asyncio.gather(first, second)

    assert [row["text"] for row in manager.snapshot_pending_items(1)] == [
        "Første"
    ]
    assert [row["text"] for row in manager.snapshot_pending_items(2)] == [
        "Andre"
    ]
    stored = json.loads(path.read_text())
    assert stored["1"][0]["text"] == "Første"
    assert stored["2"][0]["text"] == "Andre"


@pytest.mark.asyncio
async def test_outer_cancellation_settles_writer_then_carries_durable_truth(tmp_path):
    path = tmp_path / "reminders.json"
    manager = ReminderManager(path)
    original_save = manager._save_reminders
    entered = threading.Event()
    release = threading.Event()

    def blocking_save(candidate):
        entered.set()
        assert release.wait(5)
        original_save(candidate)

    manager._save_reminders = blocking_save
    task = asyncio.create_task(
        manager.add_reminder_result(
            1,
            7,
            "Ola",
            "Første",
            reference_time=NOW,
        )
    )
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()

    release.set()
    with pytest.raises(ManagerMutationCancelled) as carried:
        await task

    assert carried.value.code == "cancelled"
    assert carried.value.mutated is True
    assert carried.value.retryable is False
    assert manager.snapshot_pending_items(1)[0]["text"] == "Første"
    assert json.loads(path.read_text())["1"][0]["text"] == "Første"


@pytest.mark.asyncio
async def test_independently_cancelled_writer_is_not_outer_cancellation(
    tmp_path,
    monkeypatch,
):
    manager = ReminderManager(tmp_path / "reminders.json")

    async def cancel_owned_writer(_func, _candidate):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "to_thread", cancel_owned_writer)
    with pytest.raises(ManagerMutationCancelled) as carried:
        await manager.add_reminder_result(
            1,
            7,
            "Ola",
            "Første",
            reference_time=NOW,
        )

    assert carried.value.code == "commit_state_unknown"
    assert carried.value.mutated is False
    assert carried.value.retryable is False
    assert carried.value.commit_unknown is True
    assert manager.reminders == {}


@pytest.mark.asyncio
async def test_snapshot_is_stable_detached_and_missing_scope_is_inert(tmp_path):
    path = tmp_path / "reminders.json"
    manager = ReminderManager(path)
    first_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Første",
        reference_time=NOW,
    )
    second_id = await manager.add_reminder_result(
        1,
        8,
        "Kari",
        "Andre",
        reference_time=NOW,
    )
    before_root = copy.deepcopy(manager.reminders)
    before_bytes = path.read_bytes()

    snapshot = manager.snapshot_pending_items(1)
    assert [row["id"] for row in snapshot] == [first_id, second_id]
    snapshot[0]["text"] = "MUTATED"
    assert manager.reminders == before_root

    assert manager.snapshot_pending_items(999) == ()
    assert manager.reminders == before_root
    assert path.read_bytes() == before_bytes


def test_offline_legacy_wrappers_project_exact_historical_shapes(tmp_path):
    clock = FixedClock()
    manager = ReminderManager(tmp_path / "reminders.json", clock=clock)

    reminder_id = manager.add_reminder(1, 7, "Ola", "Første")
    edited = manager.edit_reminder(1, 1, title="Oppdatert")
    completed = manager.complete_reminder(1, reminder_id=reminder_id)
    second_id = manager.add_reminder(1, 8, "Kari", "Andre")
    deleted = manager.delete_reminder_by_id(1, 1)

    assert isinstance(reminder_id, str)
    assert edited["text"] == "Oppdatert"
    assert completed == (True, "Oppdatert", None)
    assert deleted["id"] == second_id
    assert clock.now_calls == 5


@pytest.mark.asyncio
async def test_sync_legacy_wrappers_reject_inside_a_running_loop(tmp_path):
    manager, reminder_id = await seed_manager(tmp_path / "reminders.json")

    calls = (
        lambda: manager.add_reminder(1, 7, "Ola", "Andre"),
        lambda: manager.edit_reminder(1, 1, title="Nei"),
        lambda: manager.complete_reminder(1, reminder_id=reminder_id),
        lambda: manager.delete_reminder_by_id(1, 1),
    )
    for call in calls:
        with pytest.raises(RuntimeError, match="use_async_result_api"):
            call()
