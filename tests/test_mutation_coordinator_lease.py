import asyncio
import gc
import weakref

import pytest

from core.mutation_coordinator import MutationCoordinator


SCOPE = ("test", "lease")
OTHER_SCOPE = ("test", "other")


def test_assert_held_without_running_task_fails_without_creating_lock():
    coordinator = MutationCoordinator()

    with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
        coordinator.assert_held(SCOPE)

    assert len(coordinator._locks) == 0


@pytest.mark.asyncio
async def test_assert_held_succeeds_only_inside_owned_lease():
    coordinator = MutationCoordinator()

    with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
        coordinator.assert_held(SCOPE)

    async with coordinator.hold(SCOPE):
        coordinator.assert_held(SCOPE)

    with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
        coordinator.assert_held(SCOPE)


@pytest.mark.asyncio
async def test_assert_held_tracks_nested_reentrant_depth_without_changing_it():
    coordinator = MutationCoordinator()

    async with coordinator.hold(SCOPE):
        coordinator.assert_held(SCOPE)
        lock = coordinator._locks[SCOPE]
        assert lock._depth == 1

        async with coordinator.hold(SCOPE):
            coordinator.assert_held(SCOPE)
            assert lock._depth == 2

        coordinator.assert_held(SCOPE)
        assert lock._depth == 1

    with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
        coordinator.assert_held(SCOPE)


@pytest.mark.asyncio
async def test_assert_held_fails_in_different_task_while_owner_holds_scope():
    coordinator = MutationCoordinator()

    async def assert_from_other_task() -> str:
        with pytest.raises(RuntimeError) as error:
            coordinator.assert_held(SCOPE)
        return str(error.value)

    async with coordinator.hold(SCOPE):
        coordinator.assert_held(SCOPE)
        assert await asyncio.create_task(assert_from_other_task()) == (
            "mutation_scope_not_owned"
        )
        coordinator.assert_held(SCOPE)


@pytest.mark.asyncio
async def test_assert_held_rejects_other_scope_without_creating_it():
    coordinator = MutationCoordinator()

    async with coordinator.hold(SCOPE):
        coordinator.assert_held(SCOPE)
        assert set(coordinator._locks) == {SCOPE}

        with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
            coordinator.assert_held(OTHER_SCOPE)

        assert set(coordinator._locks) == {SCOPE}
        coordinator.assert_held(SCOPE)


@pytest.mark.asyncio
async def test_assert_held_does_not_change_waiter_queue_depth_or_fifo_order():
    coordinator = MutationCoordinator()
    entered: list[str] = []

    async def writer(label: str) -> None:
        async with coordinator.hold(SCOPE):
            entered.append(label)

    async def rejected_assertion() -> str:
        with pytest.raises(RuntimeError) as error:
            coordinator.assert_held(SCOPE)
        return str(error.value)

    async with coordinator.hold(SCOPE):
        first = asyncio.create_task(writer("first"))
        await asyncio.sleep(0)

        lock = coordinator._locks[SCOPE]
        first_ticket = lock._waiters[0]
        state_before = (lock._owner, lock._depth, tuple(lock._waiters))

        coordinator.assert_held(SCOPE)
        assert await asyncio.create_task(rejected_assertion()) == (
            "mutation_scope_not_owned"
        )
        assert (lock._owner, lock._depth, tuple(lock._waiters)) == state_before

        second = asyncio.create_task(writer("second"))
        await asyncio.sleep(0)
        coordinator.assert_held(SCOPE)
        assert lock._depth == 1
        assert len(lock._waiters) == 2
        assert lock._waiters[0] is first_ticket

    await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
    assert entered == ["first", "second"]


@pytest.mark.asyncio
async def test_assert_held_does_not_keep_or_resurrect_weak_lock():
    coordinator = MutationCoordinator()

    async with coordinator.hold(SCOPE):
        coordinator.assert_held(SCOPE)
        lock_ref = weakref.ref(coordinator._locks[SCOPE])

    gc.collect()
    await asyncio.sleep(0)
    assert lock_ref() is None
    assert len(coordinator._locks) == 0

    with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
        coordinator.assert_held(SCOPE)
    assert len(coordinator._locks) == 0
