"""Retry-safe, privacy-bounded console metric lifecycle contracts."""

from __future__ import annotations

import asyncio
import json
import threading
from collections import defaultdict
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.dispatch_result import ExternalCommitState
from core.intent_models import BotIntent, IntentSource
from core.message_monitor import MessageMonitor
from core.nlu_metrics import NLUMetrics


class RecordingStore:
    def __init__(self, *, persisted_nlu=None, outcomes=()):
        self.persisted_nlu = deepcopy(persisted_nlu or {})
        self.outcomes = list(outcomes)
        self.load_calls = 0
        self.calls = []
        self._lock = threading.Lock()

    def load_nlu_stats(self):
        with self._lock:
            self.load_calls += 1
            return deepcopy(self.persisted_nlu)

    def save_stats(
        self,
        intent_stats,
        rate_limit_stats,
        *,
        nlu_stats=None,
        reminder_runtime=None,
    ):
        with self._lock:
            self.calls.append(
                {
                    "intents": deepcopy(intent_stats),
                    "rates": deepcopy(rate_limit_stats),
                    "nlu": deepcopy(nlu_stats or {}),
                    "reminder_runtime": deepcopy(reminder_runtime or {}),
                }
            )
            outcome = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def reminder_health(**overrides):
    health = {
        "status": "ok",
        "running": True,
        "stale": False,
        "last_check_at": "2026-07-16T10:00:00+02:00",
        "last_success_at": "2026-07-16T10:00:00+02:00",
        "last_error_at": None,
        "last_error_code": None,
        "consecutive_errors": 0,
        "stats": {"cycles": 2},
    }
    health.update(overrides)
    return health


def make_runtime_monitor(store: RecordingStore) -> MessageMonitor:
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.console_store = store
    monitor.nlu_metrics = NLUMetrics()
    monitor.intent_stats = defaultdict(
        lambda: {"count": 0, "low_confidence": 0, "errors": 0}
    )
    monitor.rate_limiter = SimpleNamespace(
        get_stats=lambda: {"user_stats": {}}
    )
    monitor.reminder_checker = SimpleNamespace(
        get_health=lambda: reminder_health(),
        stop=Mock(),
    )
    monitor._last_persisted_intent_stats = {}
    monitor._last_persisted_rate_stats = {}
    monitor._last_persisted_nlu_stats = {}
    monitor._last_persisted_reminder_runtime = {}
    monitor._console_persist_lock = asyncio.Lock()
    monitor._console_write_task = None
    monitor._nlu_metrics_hydrated = False
    monitor._final_stats_flushed = False
    monitor._background_tasks = set()
    monitor._tasks_by_name = {}
    monitor._task_health = {}
    monitor._setup_lock = asyncio.Lock()
    monitor._close_lock = asyncio.Lock()
    monitor._closed = False
    return monitor


def test_full_monitor_shares_one_metrics_identity(tmp_path, monkeypatch):
    from tests.test_reminder_runtime_lifecycle import _build_monitor

    monitor, _reminders, _clock, _coordinator, checker = _build_monitor(
        tmp_path,
        monkeypatch,
    )

    assert monitor.nlu_metrics is monitor.intent_router.metrics
    assert monitor.nlu_metrics is monitor.pending_actions.metrics
    assert monitor.nlu_metrics is monitor.ai_action_handler.metrics
    assert monitor.nlu_metrics is monitor.ai_action_handler.bridge.metrics
    assert monitor.nlu_metrics is checker.metrics


@pytest.mark.asyncio
async def test_failed_checker_setup_publishes_nothing_and_retry_starts_once(
    tmp_path,
    monkeypatch,
):
    from tests.test_reminder_runtime_lifecycle import _build_monitor

    monitor, _reminders, _clock, _coordinator, checker = _build_monitor(
        tmp_path,
        monkeypatch,
    )
    monitor.calendar.setup = AsyncMock()
    monitor.user_memory.setup = AsyncMock()
    monitor.calendar.ensure_gcal_configured = AsyncMock(
        return_value=SimpleNamespace(
            ok=True,
            state=ExternalCommitState.UNCHANGED,
        )
    )
    sync_started = asyncio.Event()

    async def initial_sync(*, reference_time):
        sync_started.set()
        await asyncio.Event().wait()

    monitor.calendar.sync_from_gcal_result = initial_sync

    async def flaky_checker_setup():
        checker.setup_calls += 1
        if checker.setup_calls == 1:
            raise RuntimeError("checker-setup-failed")

    checker.setup = flaky_checker_setup

    with pytest.raises(RuntimeError, match="checker-setup-failed"):
        await monitor.setup()

    assert monitor._setup_complete is False
    assert monitor._background_tasks == set()
    assert monitor._tasks_by_name == {}
    assert monitor.reminder_checker_task is None
    assert sync_started.is_set() is False

    try:
        await monitor.setup()
        await asyncio.sleep(0)

        assert checker.setup_calls == 2
        assert checker.start_calls == 1
        assert sync_started.is_set() is True
        assert set(monitor._tasks_by_name) == {
            "initial-gcal-sync",
            "console-persistence",
            "reminder-checker",
        }
    finally:
        await monitor.close()


@pytest.mark.asyncio
async def test_setup_publication_failure_settles_attempt_tasks_before_retry(
    tmp_path,
    monkeypatch,
):
    from tests.test_reminder_runtime_lifecycle import _build_monitor

    monitor, _reminders, _clock, _coordinator, checker = _build_monitor(
        tmp_path,
        monkeypatch,
    )
    monitor.calendar.setup = AsyncMock()
    monitor.user_memory.setup = AsyncMock()
    monitor.calendar.ensure_gcal_configured = AsyncMock(
        return_value=SimpleNamespace(
            ok=True,
            state=ExternalCommitState.UNCHANGED,
        )
    )

    async def initial_sync(*, reference_time):
        await asyncio.Event().wait()

    monitor.calendar.sync_from_gcal_result = initial_sync
    original_track = monitor._track_background_task
    original_set_health = monitor._set_task_health
    published = []

    def fail_reminder_health(name, **updates):
        original_set_health(name, **updates)
        if name == "reminder-checker" and updates.get("state") == "running":
            raise RuntimeError("task-publication-failed")

    def record_track(coro, name):
        try:
            task = original_track(coro, name)
        except BaseException:
            task = monitor._tasks_by_name.get(name)
            if task is not None:
                published.append(task)
            raise
        published.append(task)
        return task

    monitor._set_task_health = fail_reminder_health
    monitor._track_background_task = record_track

    with pytest.raises(RuntimeError, match="task-publication-failed"):
        await monitor.setup()

    assert len(published) == 3
    assert all(task.done() for task in published)
    assert monitor._setup_complete is False
    assert monitor._background_tasks == set()
    assert monitor._tasks_by_name == {}
    assert monitor.reminder_checker_task is None
    assert checker.stop_calls == 1

    monitor._set_task_health = original_set_health
    monitor._track_background_task = original_track
    try:
        await monitor.setup()
        await asyncio.sleep(0)

        assert checker.setup_calls == 2
        assert checker.start_calls == 1
        assert set(monitor._tasks_by_name) == {
            "initial-gcal-sync",
            "console-persistence",
            "reminder-checker",
        }
    finally:
        await monitor.close()


@pytest.mark.asyncio
async def test_setup_rollback_defers_cancellation_until_owned_tasks_settle():
    monitor = make_runtime_monitor(RecordingStore())
    stop_started = asyncio.Event()
    release_stop = asyncio.Event()

    async def stop_checker():
        stop_started.set()
        await release_stop.wait()

    monitor.reminder_checker = SimpleNamespace(stop=stop_checker)

    async def producer():
        await asyncio.Event().wait()

    owned = asyncio.create_task(producer(), name="reminder-checker")
    monitor._background_tasks.add(owned)
    monitor._tasks_by_name["reminder-checker"] = owned
    monitor.reminder_checker_task = owned
    rollback = asyncio.create_task(
        monitor._rollback_setup_tasks((owned,))
    )

    try:
        await asyncio.wait_for(stop_started.wait(), timeout=1)
        rollback.cancel("caller-canceled-during-rollback")
        await asyncio.sleep(0)

        assert rollback.done() is False
        assert monitor._tasks_by_name["reminder-checker"] is owned
        assert monitor.reminder_checker_task is owned

        release_stop.set()
        with pytest.raises(
            asyncio.CancelledError,
            match="caller-canceled-during-rollback",
        ):
            await asyncio.wait_for(rollback, timeout=1)

        assert owned.done() is True
        assert monitor._background_tasks == set()
        assert monitor._tasks_by_name == {}
        assert monitor.reminder_checker_task is None
    finally:
        release_stop.set()
        if not rollback.done():
            rollback.cancel()
        if not owned.done():
            owned.cancel()
        await asyncio.gather(rollback, owned, return_exceptions=True)


@pytest.mark.asyncio
async def test_hydration_runs_once_and_flushes_only_new_nlu_delta():
    persisted = NLUMetrics()
    persisted.record_pending("staged")
    store = RecordingStore(persisted_nlu=persisted.snapshot())
    monitor = make_runtime_monitor(store)

    await monitor._hydrate_nlu_metrics_once()
    await monitor._hydrate_nlu_metrics_once()

    assert store.load_calls == 1
    assert monitor.nlu_metrics.snapshot() == persisted.snapshot()
    assert monitor._last_persisted_nlu_stats == persisted.snapshot()

    monitor.nlu_metrics.record_pending("confirmed")
    await monitor._persist_console_stats_once()

    assert len(store.calls) == 1
    assert store.calls[0]["nlu"] == {"pending": {"confirmed": 1}}
    assert store.calls[0]["reminder_runtime"]["status"] == "ok"


class BlockingLoadStore(RecordingStore):
    def __init__(self, *, persisted_nlu):
        super().__init__(persisted_nlu=persisted_nlu)
        self.load_started = threading.Event()
        self.release_load = threading.Event()

    def load_nlu_stats(self):
        self.load_started.set()
        assert self.release_load.wait(timeout=5)
        return super().load_nlu_stats()


@pytest.mark.asyncio
async def test_hydration_race_keeps_live_increment_above_durable_baseline():
    persisted = NLUMetrics()
    persisted.record_pending("staged")
    store = BlockingLoadStore(persisted_nlu=persisted.snapshot())
    monitor = make_runtime_monitor(store)

    hydration = asyncio.create_task(monitor._hydrate_nlu_metrics_once())
    assert await asyncio.to_thread(store.load_started.wait, 5)
    monitor.nlu_metrics.record_pending("confirmed")
    store.release_load.set()
    await hydration

    assert monitor._last_persisted_nlu_stats == persisted.snapshot()
    await monitor._persist_console_stats_once()
    assert store.calls[0]["nlu"] == {"pending": {"confirmed": 1}}


@pytest.mark.asyncio
async def test_no_change_flushes_are_noops_and_concurrent_delta_writes_once():
    store = RecordingStore()
    monitor = make_runtime_monitor(store)
    monitor._last_persisted_reminder_runtime = (
        monitor._bounded_reminder_runtime_snapshot()
    )

    await monitor._persist_console_stats_once()
    await monitor._persist_console_stats_once()
    assert store.calls == []

    monitor.nlu_metrics.record_decision(
        intent=BotIntent.HELP,
        source=IntentSource.DETERMINISTIC,
        outcome="routed",
    )
    await asyncio.gather(
        monitor._persist_console_stats_once(),
        monitor._persist_console_stats_once(),
    )

    assert len(store.calls) == 1
    assert sum(store.calls[0]["nlu"]["decisions"].values()) == 1


@pytest.mark.asyncio
async def test_failed_save_retains_baseline_and_retries_identical_delta():
    store = RecordingStore(outcomes=(False, True))
    monitor = make_runtime_monitor(store)
    monitor._last_persisted_reminder_runtime = (
        monitor._bounded_reminder_runtime_snapshot()
    )
    monitor.nlu_metrics.record_pending("staged")

    with pytest.raises(RuntimeError, match="console_stats_save_failed"):
        await monitor._persist_console_stats_once()
    assert monitor._last_persisted_nlu_stats == {}

    await monitor._persist_console_stats_once()

    assert len(store.calls) == 2
    assert store.calls[0]["nlu"] == store.calls[1]["nlu"] == {
        "pending": {"staged": 1}
    }


@pytest.mark.asyncio
async def test_close_stops_producers_then_flushes_their_final_increment_once():
    store = RecordingStore()
    monitor = make_runtime_monitor(store)
    monitor._last_persisted_reminder_runtime = (
        monitor._bounded_reminder_runtime_snapshot()
    )
    order = []
    monitor.reminder_checker.stop = Mock(side_effect=lambda: order.append("stop"))

    async def producer():
        try:
            await asyncio.Event().wait()
        finally:
            order.append("producer-stopped")
            monitor.nlu_metrics.record_pending("canceled")

    task = asyncio.create_task(producer(), name="console-persistence")
    monitor._background_tasks.add(task)
    monitor._tasks_by_name["console-persistence"] = task
    await asyncio.sleep(0)

    await monitor.close()
    await monitor.close()

    assert order == ["stop", "producer-stopped"]
    assert monitor.reminder_checker.stop.call_count == 1
    assert len(store.calls) == 1
    assert store.calls[0]["nlu"] == {"pending": {"canceled": 1}}
    assert monitor._background_tasks == set()
    assert monitor._tasks_by_name == {}
    assert monitor._final_stats_flushed is True


class BlockingStore(RecordingStore):
    def __init__(self, outcome=True):
        super().__init__(outcomes=(outcome,))
        self.started = threading.Event()
        self.release = threading.Event()

    def save_stats(self, *args, **kwargs):
        self.started.set()
        assert self.release.wait(timeout=5)
        return super().save_stats(*args, **kwargs)


@pytest.mark.asyncio
async def test_canceled_inflight_write_settles_before_close_without_duplicate():
    store = BlockingStore()
    monitor = make_runtime_monitor(store)
    monitor._last_persisted_reminder_runtime = (
        monitor._bounded_reminder_runtime_snapshot()
    )
    monitor.nlu_metrics.record_pending("staged")

    periodic = asyncio.create_task(monitor._persist_console_stats_once())
    assert await asyncio.to_thread(store.started.wait, 5)
    periodic.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await periodic

    await monitor.close()

    assert len(store.calls) == 1
    assert store.calls[0]["nlu"] == {"pending": {"staged": 1}}
    assert "CANARY" not in json.dumps(store.calls)


@pytest.mark.asyncio
async def test_directly_canceled_inner_write_does_not_spin_forever():
    store = BlockingStore()
    monitor = make_runtime_monitor(store)
    monitor._last_persisted_reminder_runtime = (
        monitor._bounded_reminder_runtime_snapshot()
    )
    monitor.nlu_metrics.record_pending("staged")

    periodic = asyncio.create_task(monitor._persist_console_stats_once())
    assert await asyncio.to_thread(store.started.wait, 5)
    assert monitor._console_write_task is not None
    monitor._console_write_task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(periodic, timeout=1)
    finally:
        store.release.set()

    assert monitor._last_persisted_nlu_stats == {}


@pytest.mark.parametrize(
    "outcome",
    [False, RuntimeError("CANARY-WORKER-EXCEPTION")],
    ids=["returned-false", "raised"],
)
@pytest.mark.asyncio
async def test_canceled_failed_write_is_retried_once_by_final_close(outcome):
    store = BlockingStore(outcome)
    monitor = make_runtime_monitor(store)
    monitor._last_persisted_reminder_runtime = (
        monitor._bounded_reminder_runtime_snapshot()
    )
    monitor.nlu_metrics.record_pending("staged")

    periodic = asyncio.create_task(monitor._persist_console_stats_once())
    assert await asyncio.to_thread(store.started.wait, 5)
    periodic.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await periodic

    await monitor.close()

    assert len(store.calls) == 2
    assert [call["nlu"] for call in store.calls] == [
        {"pending": {"staged": 1}},
        {"pending": {"staged": 1}},
    ]
    assert monitor._last_persisted_nlu_stats == monitor.nlu_metrics.snapshot()
    assert "CANARY" not in json.dumps(store.calls)
