from datetime import datetime, timedelta, timezone

import pytest

from core.calendar_fact_check_store import (
    CalendarFactCheckPhase,
    CalendarFactCheckStore,
    CalendarFactCheckTarget,
)
from core.message_context import ConversationKey


class Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


def target(number: int) -> CalendarFactCheckTarget:
    return CalendarFactCheckTarget(
        stable_id=f"calendar-{number}",
        revision=f"revision-{number}",
        title=f"Kamp {number}",
        date="27.07.2026",
        time="19:00",
    )


def test_one_target_is_ready_and_exact_key_isolated():
    store = CalendarFactCheckStore(now_provider=Clock())
    key = ConversationKey(1, 2, 3)
    inquiry = store.begin(key, (target(1),))
    assert inquiry.phase is CalendarFactCheckPhase.READY
    assert store.lookup(key).inquiry == inquiry
    assert store.lookup(ConversationKey(1, 2, 4)).inquiry is None


def test_multiple_targets_require_bounded_selection():
    store = CalendarFactCheckStore(now_provider=Clock())
    key = ConversationKey(1, 2, 3)
    inquiry = store.begin(key, (target(1), target(2)))
    assert inquiry.phase is CalendarFactCheckPhase.CHOOSING_TARGET
    selected = store.select(key, 2)
    assert selected.phase is CalendarFactCheckPhase.READY
    assert selected.targets == (target(2),)


def test_expiry_is_reported_once_and_payload_is_removed():
    clock = Clock()
    store = CalendarFactCheckStore(now_provider=clock)
    key = ConversationKey(1, 2, 3)
    store.begin(key, (target(1),))
    clock.value += timedelta(minutes=10)
    assert store.lookup(key).expired is True
    assert store.lookup(key).expired is False


def test_cancel_and_replacement_are_scoped():
    store = CalendarFactCheckStore(now_provider=Clock())
    key = ConversationKey(1, 2, 3)
    first = store.begin(key, (target(1),))
    second = store.begin(key, (target(2),))
    assert second != first
    assert store.cancel(key) is True
    assert store.cancel(key) is False
    assert store.lookup(key).inquiry is None


def test_global_cap_evicts_deterministically():
    clock = Clock()
    store = CalendarFactCheckStore(now_provider=clock, max_inquiries=2)
    first = ConversationKey(1, 1, 1)
    second = ConversationKey(1, 1, 2)
    third = ConversationKey(1, 1, 3)
    store.begin(first, (target(1),))
    clock.value += timedelta(seconds=1)
    store.begin(second, (target(2),))
    clock.value += timedelta(seconds=1)
    store.begin(third, (target(3),))
    assert store.lookup(first).inquiry is None
    assert store.lookup(second).inquiry is not None
    assert store.lookup(third).inquiry is not None


@pytest.mark.parametrize("targets", ((), tuple(target(i) for i in range(1, 7))))
def test_invalid_candidate_counts_fail_closed(targets):
    store = CalendarFactCheckStore(now_provider=Clock())
    with pytest.raises(ValueError):
        store.begin(ConversationKey(1, 2, 3), targets)


def test_invalid_selection_and_naive_clock_fail_closed():
    store = CalendarFactCheckStore(now_provider=Clock())
    key = ConversationKey(1, 2, 3)
    store.begin(key, (target(1), target(2)))
    with pytest.raises(ValueError):
        store.select(key, 0)
    with pytest.raises(ValueError):
        CalendarFactCheckStore(
            now_provider=lambda: datetime(2026, 7, 16, 18, 0)
        ).begin(key, (target(1),))
