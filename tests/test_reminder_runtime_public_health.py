from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import web_console.state_collector as state_collector


PUBLIC_RUNTIME = {
    "status": "ok",
    "running": True,
    "stale": False,
    "last_success_at": "2026-07-15T12:00:00+02:00",
}
SAFE_DEGRADED_RUNTIME = {
    "status": "degraded",
    "running": False,
    "stale": True,
    "last_success_at": None,
}


class _RaisingReminderCheckerMonitor:
    def __init__(self):
        self.__dict__.update(_monitor().__dict__)

    @property
    def reminder_checker(self):
        raise RuntimeError("SECRET_MONITOR_PROPERTY")


class _RaisingGetHealthChecker:
    @property
    def get_health(self):
        raise RuntimeError("SECRET_CHECKER_PROPERTY")


class _RaisingHealthMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("SECRET_MAPPING_GETITEM")

    def __iter__(self) -> Iterator[str]:
        return iter(("status",))

    def __len__(self) -> int:
        return 1

    def get(self, key: str, default=None):
        raise RuntimeError("SECRET_MAPPING_GET")


def _monitor(checker=...):
    client = SimpleNamespace(
        user=SimpleNamespace(id=42),
        guilds=[],
        start_time=None,
        latency=0.1,
        is_ready=lambda: True,
        is_closed=lambda: False,
        config=SimpleNamespace(AI_PROVIDER="openrouter"),
    )
    monitor = SimpleNamespace(
        client=client,
        calendar=None,
        get_task_health=lambda: {},
    )
    if checker is not ...:
        monitor.reminder_checker = checker
    return monitor


async def _collect_surfaces(monkeypatch, monitor):
    monkeypatch.setattr(
        state_collector,
        "_collect_persistence_health",
        lambda *_args, **_kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        state_collector,
        "collect_bridge_health",
        AsyncMock(return_value={"status": "healthy"}),
    )
    monkeypatch.setattr(
        state_collector,
        "collect_calendar_data",
        lambda _monitor: {},
    )
    monkeypatch.setattr(
        state_collector,
        "collect_poll_data",
        lambda _monitor: {},
    )
    monkeypatch.setattr(
        state_collector,
        "collect_rate_limits",
        lambda _monitor, **_kwargs: {},
    )
    monkeypatch.setattr(
        state_collector,
        "collect_intent_stats",
        lambda _monitor, **_kwargs: {},
    )
    monkeypatch.setattr(
        state_collector,
        "collect_memory_stats",
        lambda _monitor: {},
    )
    monkeypatch.setattr(state_collector, "collect_logs", lambda **_kwargs: {})

    return (
        state_collector.collect_bot_status(monitor),
        await state_collector.collect_console_health(monitor, port=8080),
        await state_collector.StateCollector(monitor).collect_all(),
    )


@pytest.mark.asyncio
async def test_all_public_surfaces_expose_only_allowlisted_reminder_health(
    monkeypatch,
):
    raw_health = {
        **PUBLIC_RUNTIME,
        "last_check_at": "2026-07-15T12:00:01+02:00",
        "last_error_at": "2026-07-15T11:59:00+02:00",
        "last_error_code": "delivery_failure",
        "consecutive_errors": 4,
        "stats": {"due_sent": 99, "delivery_failures": 4},
        "last_error": "SECRET_RAW_EXCEPTION",
        "reminder_text": "SECRET_REMINDER_TEXT",
        "channel_id": "SECRET_CHANNEL_ID",
    }
    checker = SimpleNamespace(get_health=lambda: raw_health)

    surfaces = await _collect_surfaces(monkeypatch, _monitor(checker))

    for surface in surfaces:
        projection = surface["reminder_runtime"]
        assert projection == PUBLIC_RUNTIME
        assert set(projection) == {
            "status",
            "running",
            "stale",
            "last_success_at",
        }
        assert projection is not raw_health
        rendered = repr(projection)
        assert "SECRET_RAW_EXCEPTION" not in rendered
        assert "SECRET_REMINDER_TEXT" not in rendered
        assert "SECRET_CHANNEL_ID" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "checker",
    [
        ...,
        None,
        SimpleNamespace(),
        SimpleNamespace(get_health=None),
    ],
)
async def test_health_marks_missing_reminder_runtime_degraded_without_guessing_liveness(
    monkeypatch,
    checker,
):
    bot, health, collected = await _collect_surfaces(
        monkeypatch, _monitor(checker)
    )

    assert "reminder_runtime" not in bot
    assert "reminder_runtime" not in collected
    assert health["reminder_runtime"] == SAFE_DEGRADED_RUNTIME
    assert health["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_failure_uses_fixed_bounded_projection_without_error_text(
    monkeypatch,
):
    def fail_health():
        raise RuntimeError("SECRET_GET_HEALTH_FAILURE")

    surfaces = await _collect_surfaces(
        monkeypatch,
        _monitor(SimpleNamespace(get_health=fail_health)),
    )

    for surface in surfaces:
        assert surface["reminder_runtime"] == SAFE_DEGRADED_RUNTIME
        assert "SECRET_GET_HEALTH_FAILURE" not in repr(surface["reminder_runtime"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "monitor",
    [
        _RaisingReminderCheckerMonitor(),
        _monitor(_RaisingGetHealthChecker()),
        _monitor(
            SimpleNamespace(get_health=lambda: _RaisingHealthMapping())
        ),
    ],
)
async def test_adversarial_health_access_is_bounded_across_all_surfaces(
    monkeypatch,
    monitor,
):
    surfaces = await _collect_surfaces(monkeypatch, monitor)

    for surface in surfaces:
        assert surface["reminder_runtime"] == SAFE_DEGRADED_RUNTIME
        assert "SECRET" not in repr(surface["reminder_runtime"])


@pytest.mark.asyncio
async def test_public_surfaces_drop_raw_task_items_and_error_content(monkeypatch):
    marker = "SECRET_REMINDER_TEXT_AND_CHANNEL"
    monitor = _monitor(SimpleNamespace(get_health=lambda: PUBLIC_RUNTIME))
    monitor.get_task_health = lambda: {
        "reminder-checker": {
            "state": "failed",
            "last_error": marker,
            "exception_type": "SecretException",
            "channel_id": "123",
        }
    }

    bot, health, collected = await _collect_surfaces(monkeypatch, monitor)

    expected_counts = {
        "cancelled": 0,
        "completed": 0,
        "degraded": 0,
        "failed": 1,
        "other": 0,
        "running": 0,
    }
    assert bot["tasks"] == {"status": "degraded", "counts": expected_counts}
    assert health["tasks"] == {"status": "degraded", "counts": expected_counts}
    assert collected["status"]["tasks"] == {
        "status": "degraded",
        "counts": expected_counts,
    }
    for surface in (bot, health, collected):
        rendered = repr(surface)
        assert marker not in rendered
        assert "SecretException" not in rendered
        assert "last_error" not in rendered
        assert "channel_id" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_health",
    [
        None,
        [],
        {
            "status": [],
            "running": True,
            "stale": False,
            "last_success_at": None,
        },
        {
            "status": "SECRET_STATUS",
            "running": "yes",
            "stale": 1,
            "last_success_at": "SECRET_TIMESTAMP",
            "stats": {"SECRET_COUNTER": 99},
        },
    ],
)
async def test_malformed_health_never_passes_raw_values_through(
    monkeypatch,
    raw_health,
):
    checker = SimpleNamespace(get_health=lambda: raw_health)

    surfaces = await _collect_surfaces(monkeypatch, _monitor(checker))

    for surface in surfaces:
        assert surface["reminder_runtime"] == SAFE_DEGRADED_RUNTIME
        assert "SECRET" not in repr(surface["reminder_runtime"])


def test_bot_status_exposes_runtime_even_when_monitor_client_is_not_ready():
    checker = SimpleNamespace(get_health=lambda: PUBLIC_RUNTIME)
    monitor = SimpleNamespace(reminder_checker=checker)

    status = state_collector.collect_bot_status(monitor)

    assert status == {
        "status": "degraded",
        "monitor_ready": False,
        "reminder_runtime": PUBLIC_RUNTIME,
    }
