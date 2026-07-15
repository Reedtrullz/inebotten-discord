"""Transactional UserMemory and injected daily-digest regressions."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import memory.user_memory as user_memory_module
from cal_system.temporal_resolver import OSLO
from core.dispatch_result import ManagerMutationCancelled, ManagerMutationError
from core.mutation_coordinator import MutationCoordinator
from features.daily_digest_manager import DailyDigestManager
from memory.user_memory import UserMemory, get_user_memory


NOW = datetime(2026, 7, 15, 8, 30, tzinfo=OSLO)


async def _memory(path: Path, coordinator=None) -> UserMemory:
    memory = UserMemory(path, mutation_coordinator=coordinator)
    await memory.setup()
    return memory


def _seed(memory: UserMemory, *user_ids: str) -> None:
    memory.memory = {
        user_id: memory._new_user(user_id.upper(), NOW)
        for user_id in user_ids
    }
    memory._save_memory_sync(memory.memory)


@pytest.mark.asyncio
async def test_constructor_preserves_positional_path_and_binds_coordinator(tmp_path):
    coordinator = MutationCoordinator()
    path = tmp_path / "memory.json"
    memory = await _memory(path, coordinator)

    assert memory.storage_path == path
    assert memory.mutation_coordinator is coordinator


@pytest.mark.asyncio
async def test_timestamped_results_require_one_aware_reference(tmp_path):
    memory = await _memory(tmp_path / "memory.json")

    with pytest.raises(TypeError):
        await memory.get_or_create_user_result("u1", "Ola")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="reference_time_must_be_aware"):
        await memory.get_or_create_user_result(
            "u1",
            "Ola",
            reference_time=datetime(2026, 7, 15, 8, 30),
        )
    with pytest.raises(ValueError, match="reference_time_must_be_aware"):
        await memory.update_last_interaction_result(
            "u1",
            reference_time=datetime(2026, 7, 15, 8, 30),
        )

    assert memory.memory == {}
    assert not memory.storage_path.exists()


@pytest.mark.asyncio
async def test_get_or_create_and_username_fill_publish_after_persist(tmp_path):
    path = tmp_path / "memory.json"
    memory = await _memory(path)

    created = await memory.get_or_create_user_result(
        "u1", None, reference_time=NOW
    )
    assert created["first_seen"] == NOW.isoformat()
    assert created["username"] is None

    filled = await memory.get_or_create_user_result(
        "u1", "Ola", reference_time=NOW
    )
    assert filled["username"] == "Ola"
    assert json.loads(path.read_text())["u1"]["username"] == "Ola"

    filled["preferences"]["formality"] = "mutated-outside"
    assert memory.snapshot_user("u1")["preferences"]["formality"] == "casual"


@pytest.mark.asyncio
async def test_get_user_and_snapshots_are_detached_and_never_create_or_fill(tmp_path):
    path = tmp_path / "memory.json"
    memory = await _memory(path)
    _seed(memory, "u1")
    memory.memory["u1"]["username"] = None
    memory._save_memory_sync(memory.memory)
    before_bytes = path.read_bytes()
    before_root = copy.deepcopy(memory.memory)

    missing = await memory.get_user("missing", "Ignored")
    existing = await memory.get_user("u1", "Must not fill")
    snapshot = memory.snapshot_pending_user("u1")
    assert missing == {}
    assert existing["username"] is None
    assert snapshot is not None
    snapshot["interests"].append("outside")

    assert memory.memory == before_root
    assert path.read_bytes() == before_bytes
    assert memory.snapshot_user("missing") is None


@pytest.mark.asyncio
async def test_every_result_writer_has_explicit_changed_truth(tmp_path):
    path = tmp_path / "memory.json"
    memory = await _memory(path)
    await memory.get_or_create_user_result("u1", "Ola", reference_time=NOW)

    assert await memory.update_last_interaction_result(
        "u1", reference_time=NOW, topic=["RBK", "Python"]
    )
    assert await memory.add_interest_result("u1", "Fotball")
    assert not await memory.add_interest_result("u1", "fotball")
    assert await memory.set_preference_result("u1", "formality", "formal")
    assert not await memory.set_preference_result("u1", "formality", "formal")
    assert await memory.set_location_result("u1", "Trondheim")
    assert not await memory.set_location_result("u1", "Trondheim")
    assert await memory.delete_user_memory_result("u1")
    assert not await memory.delete_user_memory_result("u1")

    assert json.loads(path.read_text()) == {}


@pytest.mark.parametrize(
    "operation",
    (
        "create",
        "username_fill",
        "interaction",
        "interest",
        "preference",
        "location",
        "delete",
    ),
)
@pytest.mark.asyncio
async def test_every_writer_rolls_back_memory_and_bytes_on_save_failure(
    tmp_path,
    operation,
):
    path = tmp_path / f"{operation}.json"
    memory = await _memory(path)
    if operation != "create":
        _seed(memory, "u1")
    if operation == "username_fill":
        memory.memory["u1"]["username"] = None
        memory._save_memory_sync(memory.memory)

    before_root = copy.deepcopy(memory.memory)
    before_bytes = path.read_bytes() if path.exists() else None

    def fail(_candidate):
        raise OSError("sentinel")

    memory._save_memory_sync = fail
    calls = {
        "create": lambda: memory.get_or_create_user_result(
            "u2", "Kari", reference_time=NOW
        ),
        "username_fill": lambda: memory.get_or_create_user_result(
            "u1", "Ola", reference_time=NOW
        ),
        "interaction": lambda: memory.update_last_interaction_result(
            "u1", reference_time=NOW
        ),
        "interest": lambda: memory.add_interest_result("u1", "Fotball"),
        "preference": lambda: memory.set_preference_result(
            "u1", "formality", "formal"
        ),
        "location": lambda: memory.set_location_result("u1", "Trondheim"),
        "delete": lambda: memory.delete_user_memory_result("u1"),
    }

    with pytest.raises(ManagerMutationError) as error:
        await calls[operation]()

    assert error.value.code == "storage_write_failed"
    assert error.value.mutated is False
    assert memory.memory == before_root
    assert (path.read_bytes() if path.exists() else None) == before_bytes


@pytest.mark.asyncio
async def test_lazy_creation_race_and_two_user_fifo_writes_survive(tmp_path):
    path = tmp_path / "memory.json"
    memory = await _memory(path)
    original_save = memory._save_memory_sync
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

    memory._save_memory_sync = blocking_save
    create = asyncio.create_task(
        memory.get_or_create_user_result("u1", "Ola", reference_time=NOW)
    )
    assert await asyncio.to_thread(entered.wait, 2)
    preference = asyncio.create_task(
        memory.set_preference_result("u1", "formality", "formal")
    )
    await asyncio.sleep(0)
    assert not preference.done()
    release.set()
    await asyncio.gather(create, preference)

    await memory.get_or_create_user_result("u2", "Kari", reference_time=NOW)
    await asyncio.gather(
        memory.set_location_result("u1", "Trondheim"),
        memory.set_location_result("u2", "Oslo"),
    )

    stored = json.loads(path.read_text())
    assert stored["u1"]["preferences"]["formality"] == "formal"
    assert stored["u1"]["location"] == "Trondheim"
    assert stored["u2"]["location"] == "Oslo"


@pytest.mark.asyncio
async def test_blocked_save_exposes_old_snapshot_then_complete_new_snapshot(tmp_path):
    path = tmp_path / "memory.json"
    memory = await _memory(path)
    _seed(memory, "u1")
    original_save = memory._save_memory_sync
    entered = threading.Event()
    release = threading.Event()

    def blocking_save(candidate):
        entered.set()
        assert release.wait(5)
        original_save(candidate)

    memory._save_memory_sync = blocking_save
    task = asyncio.create_task(memory.set_location_result("u1", "Trondheim"))
    assert await asyncio.to_thread(entered.wait, 2)
    assert memory.snapshot_user("u1")["location"] is None
    release.set()
    assert await task is True
    assert memory.snapshot_user("u1")["location"] == "Trondheim"


@pytest.mark.asyncio
async def test_cancelled_owned_save_settles_and_carries_committed_truth(tmp_path):
    path = tmp_path / "memory.json"
    memory = await _memory(path)
    _seed(memory, "u1")
    original_save = memory._save_memory_sync
    entered = threading.Event()
    release = threading.Event()

    def blocking_save(candidate):
        entered.set()
        assert release.wait(5)
        original_save(candidate)

    memory._save_memory_sync = blocking_save
    task = asyncio.create_task(memory.set_location_result("u1", "Trondheim"))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()

    with pytest.raises(ManagerMutationCancelled) as error:
        await task
    assert error.value.code == "cancelled"
    assert error.value.mutated is True
    assert error.value.retryable is False
    assert memory.snapshot_user("u1")["location"] == "Trondheim"
    assert json.loads(path.read_text())["u1"]["location"] == "Trondheim"


@pytest.mark.asyncio
async def test_independently_cancelled_memory_writer_is_commit_unknown(
    tmp_path,
    monkeypatch,
):
    memory = await _memory(tmp_path / "memory.json")

    async def cancel_owned_work(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "to_thread", cancel_owned_work)

    with pytest.raises(ManagerMutationCancelled) as cancelled:
        await memory.get_or_create_user_result(
            "u1",
            "Ola",
            reference_time=NOW,
        )

    assert cancelled.value.code == "commit_state_unknown"
    assert cancelled.value.mutated is False
    assert cancelled.value.retryable is False
    assert cancelled.value.commit_unknown is True
    assert memory.memory == {}
    assert not memory.storage_path.exists()


@pytest.mark.asyncio
async def test_async_legacy_projections_preserve_historical_shapes(tmp_path):
    memory = await _memory(tmp_path / "memory.json")

    assert await memory.set_location("u1", "Trondheim") is None
    assert await memory.add_interest("u1", "RBK") is None
    assert await memory.set_preference("u1", "formality", "formal") is None
    assert await memory.update_last_interaction("u1", "fotball") is None
    assert await memory.delete_user_memory("u1") is True
    assert await memory.delete_user_memory("u1") is False


def test_singleton_binds_first_explicit_coordinator_and_rejects_mismatch(
    monkeypatch,
):
    monkeypatch.setattr(user_memory_module, "_user_memory", None)
    first = MutationCoordinator()
    second = MutationCoordinator()

    memory = get_user_memory(first)
    assert memory.mutation_coordinator is first
    assert get_user_memory() is memory
    assert get_user_memory(first) is memory
    with pytest.raises(RuntimeError, match="mutation_coordinator_identity_mismatch"):
        get_user_memory(second)


@pytest.mark.asyncio
async def test_daily_digest_uses_injected_snapshot_and_exact_reference(
    monkeypatch,
):
    weather = AsyncMock(return_value=None)
    monkeypatch.setattr("features.weather_api.get_weather_for_city", weather)

    class SnapshotMemory:
        def __init__(self):
            self.calls = []

        def snapshot_user(self, user_id):
            self.calls.append(user_id)
            return {"location": "Trondheim"}

    class Events:
        def __init__(self):
            self.references = []

        def get_upcoming(self, guild_id, days, *, reference_time):
            self.references.append(reference_time)
            return [
                {"title": "Møte", "date": "15.07.2026", "time": "09:00"},
                {"title": "Senere", "date": "16.07.2026", "time": "09:00"},
            ]

    user_memory = SnapshotMemory()
    events = Events()
    manager = DailyDigestManager(events, user_memory=user_memory)

    text = await manager.generate_digest(
        123,
        "no",
        user_id=7,
        reference_time=NOW,
    )

    assert "15.07.2026" in text
    assert "Møte" in text
    assert "Senere" not in text
    assert user_memory.calls == [7]
    assert events.references == [NOW]
    weather.assert_awaited_once_with("Trondheim")


@pytest.mark.asyncio
async def test_daily_digest_rejects_naive_reference_before_any_read(monkeypatch):
    weather = AsyncMock(return_value=None)
    monkeypatch.setattr("features.weather_api.get_weather_for_city", weather)

    class SnapshotMemory:
        def snapshot_user(self, _user_id):
            raise AssertionError("snapshot must not run")

    manager = DailyDigestManager(user_memory=SnapshotMemory())
    with pytest.raises(ValueError, match="reference_time_must_be_aware"):
        await manager.generate_digest(
            123,
            user_id=7,
            reference_time=datetime(2026, 7, 15, 8, 30),
        )
    weather.assert_not_awaited()
