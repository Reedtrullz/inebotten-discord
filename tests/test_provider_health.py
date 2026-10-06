"""Offline regressions for provider-aware readiness diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from core.message_monitor import MessageMonitor
from web_console import state_collector


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _stamp(value: datetime) -> str:
    return value.isoformat()


def _monitor(
    provider: str = "openrouter",
    *,
    probe_ok: bool | None = True,
    inference_status: str | None = "success",
    inference_provider: str | None = None,
    inference_at: datetime | None = NOW,
    gcal_enabled: bool = False,
    task_health: dict | None = None,
):
    config = SimpleNamespace(
        AI_PROVIDER=provider,
        AI_FALLBACK_PROVIDER=None,
        OPENROUTER_API_KEY="synthetic-provider-key" if provider == "openrouter" else "",
        GCAL_ENABLED=gcal_enabled,
    )
    return SimpleNamespace(
        client=SimpleNamespace(config=config, reminder_checker=object()),
        calendar=SimpleNamespace(
            gcal_enabled=gcal_enabled,
            last_gcal_sync_error=None,
        ),
        _provider_readiness={
            "probe": {"ok": probe_ok, "checked_at": _stamp(NOW)},
            "inference": (
                {
                    "status": inference_status,
                    "provider": inference_provider or provider,
                    "fallback": False,
                    "checked_at": _stamp(inference_at),
                }
                if inference_status is not None and inference_at is not None
                else None
            ),
        },
        get_task_health=lambda: task_health or {
            "reminder-checker": {"state": "running", "last_ok": _stamp(NOW)}
        },
    )


def _patch_local_state(monkeypatch, monitor, *, now=NOW, stale_scheduler=False, patch_calendar=True):
    tasks = monitor.get_task_health()
    if stale_scheduler:
        tasks["reminder-checker"]["last_ok"] = _stamp(now - timedelta(minutes=10))
    monkeypatch.setattr(
        state_collector,
        "_collect_task_health",
        lambda _monitor: {"status": "ok", "items": tasks},
    )
    monkeypatch.setattr(
        state_collector,
        "_collect_persistence_health",
        lambda: {"status": "ok"},
    )
    if patch_calendar:
        monkeypatch.setattr(
            state_collector,
            "_collect_calendar_sync_health",
            lambda _monitor, *, now=None: {
                "enabled": False,
                "required": False,
                "status": "disabled",
                "checked_at": _stamp(now),
                "reason_code": "google_calendar_disabled",
                "recovery_action": None,
            },
        )


@pytest.mark.asyncio
async def test_model_catalog_success_does_not_claim_inference_acceptance(monkeypatch):
    monitor = _monitor("lm_studio", inference_status=None, inference_at=None)
    _patch_local_state(monkeypatch, monitor)

    result = await state_collector.collect_provider_readiness(
        monitor,
        bridge_health={"status": "healthy", "lm_studio": "connected"},
        now=NOW,
    )

    provider = result["components"]["provider"]
    assert provider["transport_status"] == "reachable"
    assert provider["model_discovery_status"] == "catalog_reachable"
    assert provider["inference_acceptance_status"] == "not_observed"
    assert provider["status"] == "stale"
    assert provider["reason_code"] == "inference_acceptance_unobserved"


@pytest.mark.asyncio
async def test_cloud_only_readiness_ignores_disabled_google_and_unreachable_bridge(monkeypatch):
    monitor = _monitor("openrouter")
    _patch_local_state(monkeypatch, monitor)

    result = await state_collector.collect_provider_readiness(
        monitor,
        bridge_health={"status": "unavailable", "lm_studio": "unknown"},
        now=NOW,
    )

    assert result["status"] == "ready"
    assert result["components"]["provider"]["status"] == "ready"
    assert result["components"]["provider"]["model_discovery_status"] == "catalog_reachable"
    assert result["components"]["provider"]["inference_acceptance_status"] == "accepted"
    assert result["components"]["bridge"]["status"] == "disabled"
    assert result["components"]["bridge"]["required"] is False
    assert result["components"]["google_calendar"]["status"] == "disabled"
    assert result["components"]["google_calendar"]["required"] is False


@pytest.mark.asyncio
async def test_stale_scheduler_has_actionable_status_without_raw_error(monkeypatch):
    monitor = _monitor("openrouter")
    monitor.calendar.last_gcal_sync_error = "PRIVATE_EVENT_TITLE / token-like-detail"
    _patch_local_state(monkeypatch, monitor, stale_scheduler=True)

    result = await state_collector.collect_provider_readiness(
        monitor,
        bridge_health={"status": "unavailable"},
        now=NOW,
    )

    scheduler = result["components"]["scheduler"]
    assert scheduler["status"] == "stale"
    assert scheduler["reason_code"] == "scheduler_heartbeat_stale"
    assert scheduler["recovery_action"]
    encoded = json.dumps(result)
    assert "PRIVATE_EVENT_TITLE" not in encoded
    assert "token-like-detail" not in encoded


@pytest.mark.asyncio
async def test_enabled_google_sync_failure_is_actionable_and_redacted(monkeypatch):
    monitor = _monitor("openrouter", gcal_enabled=True)
    monitor.calendar.last_gcal_sync_error = "PRIVATE_EVENT_TITLE / synthetic-token"
    _patch_local_state(monkeypatch, monitor, patch_calendar=False)

    result = await state_collector.collect_provider_readiness(
        monitor,
        bridge_health={"status": "unavailable"},
        now=NOW,
    )

    sync = result["components"]["calendar_sync"]
    assert sync["enabled"] is True
    assert sync["required"] is True
    assert sync["status"] == "degraded"
    assert sync["recovery_action"]
    assert result["status"] == "degraded"
    assert "PRIVATE_EVENT_TITLE" not in json.dumps(result)
    assert "synthetic-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_each_readiness_component_has_the_health_contract(monkeypatch):
    monitor = _monitor("openrouter")
    _patch_local_state(monkeypatch, monitor)

    result = await state_collector.collect_provider_readiness(
        monitor,
        bridge_health={"status": "unavailable"},
        now=NOW,
    )

    allowed = {"ready", "degraded", "unavailable", "stale", "disabled"}
    for component in result["components"].values():
        assert {"enabled", "required", "status", "checked_at", "reason_code", "recovery_action"} <= component.keys()
        assert component["status"] in allowed
        assert component["checked_at"]


def test_task_health_removes_raw_exception_details():
    monitor = SimpleNamespace(
        get_task_health=lambda: {
            "reminder-checker": {
                "state": "failed",
                "last_error": "PRIVATE_PROMPT and synthetic-token",
                "exception_type": "RuntimeError",
            }
        }
    )

    result = state_collector._collect_task_health(monitor)

    assert result["status"] == "degraded"
    assert "PRIVATE_PROMPT" not in json.dumps(result)
    assert "synthetic-token" not in json.dumps(result)


def test_store_health_removes_raw_paths_and_exception_details(monkeypatch):
    class FakeStore:
        def health(self):
            return {
                "status": "degraded",
                "last_error": "PRIVATE_PROMPT synthetic-token",
                "stats_read_error": "private/path: corrupted",
            }

    monkeypatch.setattr(
        state_collector,
        "_probe_json_files",
        lambda: {"/private/user-store.json": "PRIVATE_PROMPT synthetic-token"},
    )
    monkeypatch.setattr("web_console.console_store.get_console_store", lambda: FakeStore())

    result = state_collector._collect_persistence_health()

    assert result["status"] == "degraded"
    encoded = json.dumps(result)
    assert "PRIVATE_PROMPT" not in encoded
    assert "synthetic-token" not in encoded
    assert "/private/" not in encoded


def test_monitor_readiness_records_outcome_without_prompt_or_response():
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor._provider_readiness = {"probe": None, "inference": None}

    monitor.record_provider_inference(
        SimpleNamespace(
            status="success",
            text="PRIVATE_RESPONSE_TEXT",
            provider="openrouter",
            fallback=False,
        )
    )
    snapshot = monitor.get_provider_readiness()

    assert snapshot["inference"]["accepted"] is True
    assert snapshot["inference"]["provider"] == "openrouter"
    assert "PRIVATE_RESPONSE_TEXT" not in json.dumps(snapshot)


@pytest.mark.asyncio
async def test_unknown_required_provider_cannot_disappear_from_aggregate(monkeypatch):
    monitor = _monitor('unsupported', inference_status=None, inference_at=None)
    _patch_local_state(monkeypatch, monitor)
    result = await state_collector.collect_provider_readiness(monitor, now=NOW)
    assert result['components']['provider']['status'] == 'unavailable'
    assert result['status'] == 'unavailable'


@pytest.mark.asyncio
async def test_future_provider_and_scheduler_evidence_is_not_fresh(monkeypatch):
    monitor = _monitor(inference_at=NOW + timedelta(hours=2))
    monitor.get_task_health = lambda: {'reminder-checker': {'state': 'running', 'last_ok': _stamp(NOW + timedelta(hours=2))}}
    _patch_local_state(monkeypatch, monitor)
    result = await state_collector.collect_provider_readiness(monitor, now=NOW)
    assert result['components']['provider']['status'] != 'ready'
    assert result['components']['scheduler']['status'] == 'stale'


@pytest.mark.asyncio
async def test_hung_scheduler_cannot_gain_success_from_timer():
    import asyncio
    monitor = MessageMonitor.__new__(MessageMonitor)
    old = _stamp(NOW - timedelta(minutes=10))
    monitor._task_health = {'reminder-checker': {'state': 'running', 'last_ok': old}}
    blocked = asyncio.Event()
    monitor._background_tasks = set()
    task = monitor._track_background_task(blocked.wait(), 'reminder-checker')
    await asyncio.sleep(.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert monitor._task_health['reminder-checker']['last_ok'] == old


@pytest.mark.asyncio
async def test_fallback_acceptance_is_not_primary_transport_proof(monkeypatch):
    monitor = _monitor('lm_studio', probe_ok=False, inference_provider='openrouter')
    _patch_local_state(monkeypatch, monitor)
    result = await state_collector.collect_provider_readiness(monitor, bridge_health={'status': 'unavailable', 'lm_studio': 'disconnected'}, now=NOW)
    assert result['components']['provider']['transport_status'] == 'unavailable'
    assert result['components']['provider']['status'] != 'ready'


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', [False, True])
async def test_real_checker_reports_completed_iteration_and_failure(tmp_path, failed):
    from unittest.mock import AsyncMock
    from cal_system.reminder_checker import ReminderChecker
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor._task_health = {}
    checker = ReminderChecker(storage_path=tmp_path / 'synthetic.json',
                              health_callback=monitor.record_scheduler_iteration)
    try:
        checker.check_upcoming_30min = AsyncMock(side_effect=ValueError('synthetic') if failed else None)
        checker.check_event_now = AsyncMock()
        checker.check_event_passed = AsyncMock()
        checker.check_morning_digest = AsyncMock()
        def stop_after_completion(successful):
            monitor.record_scheduler_iteration(successful)
            checker.running = False
        checker.health_callback = stop_after_completion
        await checker.start()
        health = monitor.get_task_health()['reminder-checker']
        if failed:
            assert health['state'] == 'degraded' and 'last_ok' not in health
        else:
            assert health['state'] == 'running'
            assert datetime.fromisoformat(health['last_ok']).utcoffset() == timedelta(0)
    finally:
        checker.close_storage()


@pytest.mark.asyncio
async def test_failed_bridge_probe_closes_owned_writer(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    reader = SimpleNamespace(read=AsyncMock(side_effect=TimeoutError('synthetic')))
    writer = SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock(), wait_closed=AsyncMock())
    monkeypatch.setattr(state_collector.asyncio, 'open_connection', AsyncMock(return_value=(reader, writer)))
    result = await state_collector.collect_bridge_health(_monitor('lm_studio'))
    assert result['status'] == 'unavailable'
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_or_future_catalogue_probe_is_unverified(monkeypatch):
    for checked in (NOW - timedelta(days=1), NOW + timedelta(hours=1)):
        monitor = _monitor(inference_status=None, inference_at=None)
        monitor._provider_readiness['probe']['checked_at'] = _stamp(checked)
        _patch_local_state(monkeypatch, monitor)
        result = await state_collector.collect_provider_readiness(monitor, now=NOW)
        assert result['components']['provider']['transport_status'] == 'unverified'
        assert result['components']['provider']['model_discovery_status'] == 'unverified'
