from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.intent_models import BotIntent, IntentSource
from core.message_monitor import (
    MessageMonitor,
    _counter_stats_delta,
    _flat_counter_delta,
    _nested_counter_delta,
)
from core.nlu_metrics import NLUMetrics
from web_console.console_store import (
    ConsoleStore,
    STATS_SCHEMA_VERSION,
    sanitize_reminder_runtime,
)
from web_console.server import ConsoleServer
from web_console.state_collector import (
    StateCollector,
    collect_authenticated_status,
    collect_bot_status,
    collect_console_health,
    collect_intent_stats,
    collect_rate_limits,
)


def test_console_store_accepts_keyword_only_data_dir(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    assert store._data_dir == tmp_path


def test_console_server_uses_injected_store(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    server = ConsoleServer(api_key="test-key", store=store)
    assert server.store is store


def test_bot_status_uptime_keeps_the_injected_store(tmp_path, monkeypatch):
    store = ConsoleStore(data_dir=tmp_path)
    first_start = Mock(return_value=datetime.now())
    monkeypatch.setattr(store, "first_start_time", first_start)
    monkeypatch.setattr(
        "web_console.state_collector.get_console_store",
        Mock(side_effect=AssertionError("global_store_used")),
    )
    client = SimpleNamespace(
        user=SimpleNamespace(id=7),
        guilds=[],
        start_time=datetime.now(),
        latency=0.1,
        is_ready=lambda: True,
        is_closed=lambda: False,
    )
    monitor = SimpleNamespace(
        client=client,
        calendar=None,
        get_task_health=lambda: {},
    )

    status = collect_bot_status(monitor, store=store)

    assert status["monitor_ready"] is True
    first_start.assert_called_once_with()


def test_v2_stats_migrate_without_losing_totals(tmp_path):
    (tmp_path / "stats.json").write_text(
        json.dumps(
            {
                "version": 2,
                "intents": {
                    "help": {"count": 4, "low_confidence": 0, "errors": 0}
                },
                "rate_limits": {"7": 3},
                "last_saved": "2026-07-14T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    store = ConsoleStore(data_dir=tmp_path)

    stats = store.load_stats()

    assert stats["version"] == STATS_SCHEMA_VERSION == 3
    assert stats["intents"]["help"]["count"] == 4
    assert stats["rate_limits"]["7"] == 3
    assert stats["nlu"] == {}
    assert stats["reminder_runtime"] == {}


def test_future_stats_schema_is_read_only_and_reports_bounded_error(tmp_path):
    stats_file = tmp_path / "stats.json"
    original = b'{"version":4,"private":"DO-NOT-OVERWRITE"}\n'
    stats_file.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    store = ConsoleStore(data_dir=tmp_path)

    assert store.load_stats()["version"] == 3
    assert store.save_stats({"help": {"count": 1}}, {}) is False

    assert stats_file.read_bytes() == original
    assert hashlib.sha256(stats_file.read_bytes()).hexdigest() == digest
    health = store.health()
    assert health["status"] == "degraded"
    assert health["error_code"] == "unsupported_stats_schema"
    assert "DO-NOT-OVERWRITE" not in json.dumps(health)


def test_nlu_persistence_accepts_only_allowlisted_counters(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    metrics = NLUMetrics()
    metrics.record_decision(
        intent=BotIntent.HELP,
        source=IntentSource.DETERMINISTIC,
        outcome="routed",
    )
    snapshot = metrics.snapshot()
    snapshot["decisions"]["CANARY-RAW-UTTERANCE"] = 99
    snapshot["unknown"] = {"CANARY-PRIVATE": 1}

    assert store.persist_nlu_metrics(snapshot) is True

    persisted = store.load_nlu_stats()
    assert sum(persisted["decisions"].values()) == 1
    rendered = json.dumps(store.load_stats(), sort_keys=True)
    assert "CANARY" not in rendered


def test_current_schema_nlu_readback_and_rewrite_drop_unknown_raw_keys(tmp_path):
    decision_key = "intent=help|source=deterministic|outcome=routed"
    (tmp_path / "stats.json").write_text(
        json.dumps(
            {
                "version": STATS_SCHEMA_VERSION,
                "intents": {},
                "rate_limits": {},
                "nlu": {
                    "decisions": {
                        decision_key: 7,
                        "PRIVATE-UTTERANCE-CANARY": 99,
                    },
                    "pending": {
                        "staged": True,
                        "confirmed": -1,
                        "canceled": "4",
                    },
                    "raw_utterance": "PRIVATE-RAW-TEXT-CANARY",
                },
                "reminder_runtime": {},
                "last_saved": "2026-07-16T10:00:00+02:00",
            }
        ),
        encoding="utf-8",
    )
    store = ConsoleStore(data_dir=tmp_path)

    assert store.load_nlu_stats() == {
        "decisions": {decision_key: 7},
    }
    assert store.persist_nlu_metrics(
        {"decisions": {decision_key: 1}}
    ) is True

    persisted = store.load_stats()
    assert persisted["nlu"] == {
        "decisions": {decision_key: 8},
    }
    rendered = json.dumps(persisted, sort_keys=True)
    assert "PRIVATE" not in rendered
    assert "raw_utterance" not in rendered


def test_current_schema_reminder_readback_and_rewrite_drop_raw_health(tmp_path):
    raw_runtime = {
        "status": "ok",
        "running": True,
        "stale": False,
        "last_error": "PRIVATE-REMINDER-ERROR-CANARY",
        "last_error_code": "PRIVATE-ERROR-CODE-CANARY",
        "stats": {
            "cycles": 3,
            "PRIVATE-REMINDER-TITLE-CANARY": 9,
        },
    }
    (tmp_path / "stats.json").write_text(
        json.dumps(
            {
                "version": STATS_SCHEMA_VERSION,
                "intents": {},
                "rate_limits": {},
                "nlu": {},
                "reminder_runtime": raw_runtime,
                "last_saved": "2026-07-16T10:00:00+02:00",
            }
        ),
        encoding="utf-8",
    )
    store = ConsoleStore(data_dir=tmp_path)
    expected = sanitize_reminder_runtime(raw_runtime)

    assert store.load_reminder_runtime() == expected
    assert store.save_stats(
        {"help": {"count": 1, "low_confidence": 0, "errors": 0}},
        {},
    ) is True

    persisted = store.load_stats()
    assert persisted["reminder_runtime"] == expected
    rendered = json.dumps(persisted, sort_keys=True)
    assert "PRIVATE" not in rendered
    assert "last_error\"" not in rendered


def test_current_schema_stats_root_and_legacy_counters_are_canonical(tmp_path):
    (tmp_path / "stats.json").write_text(
        json.dumps(
            {
                "version": STATS_SCHEMA_VERSION,
                "intents": {
                    "help": {
                        "count": 3,
                        "low_confidence": True,
                        "errors": -1,
                        "raw": "PRIVATE-INTENT-LEAF-CANARY",
                    },
                    "PRIVATE RAW UTTERANCE": {
                        "count": 9,
                        "low_confidence": 0,
                        "errors": 0,
                    },
                },
                "rate_limits": {
                    "7": 4,
                    "PRIVATE-RATE-CANARY": 8,
                    "１２": 5,
                    "8": True,
                },
                "nlu": {},
                "reminder_runtime": {},
                "last_saved": "PRIVATE-TIMESTAMP-CANARY",
                "raw_utterance": "PRIVATE-TOP-LEVEL-CANARY",
            }
        ),
        encoding="utf-8",
    )
    store = ConsoleStore(data_dir=tmp_path)

    loaded = store.load_stats()
    assert set(loaded) == {
        "version",
        "intents",
        "rate_limits",
        "nlu",
        "reminder_runtime",
        "last_saved",
    }
    assert loaded["intents"] == {
        "help": {"count": 3, "low_confidence": 0, "errors": 0}
    }
    assert loaded["rate_limits"] == {"7": 4}
    assert loaded["last_saved"] is None

    assert store.persist_nlu_metrics({}) is True
    persisted = store.load_stats()
    assert persisted["intents"] == loaded["intents"]
    assert persisted["rate_limits"] == {"7": 4}
    assert persisted["last_saved"] is not None
    assert "PRIVATE" not in json.dumps(persisted, sort_keys=True)


@pytest.mark.parametrize(
    ("persisted_timestamp", "expected_timestamp"),
    [
        ("2026-07-16T10:00:00+02:00", "2026-07-16T10:00:00+02:00"),
        ("PRIVATE-TIMESTAMP-CANARY", None),
    ],
    ids=["valid-iso", "malformed-private"],
)
def test_fresh_store_health_projects_only_canonical_persisted_timestamp(
    tmp_path,
    persisted_timestamp,
    expected_timestamp,
):
    (tmp_path / "stats.json").write_text(
        json.dumps(
            {
                "version": STATS_SCHEMA_VERSION,
                "intents": {},
                "rate_limits": {},
                "nlu": {},
                "reminder_runtime": {},
                "last_saved": persisted_timestamp,
                "raw_utterance": "PRIVATE-TOP-LEVEL-CANARY",
            }
        ),
        encoding="utf-8",
    )

    health = ConsoleStore(data_dir=tmp_path).health()

    assert health["last_stats_saved_at"] == expected_timestamp
    assert "PRIVATE" not in json.dumps(health, sort_keys=True)
    assert "raw_utterance" not in health


def test_concurrent_legacy_and_nlu_deltas_are_not_lost(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    metrics = NLUMetrics()
    metrics.record_pending("staged")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            store.save_stats,
            {"help": {"count": 2, "low_confidence": 0, "errors": 0}},
            {"7": 3},
        )
        second = pool.submit(store.persist_nlu_metrics, metrics.snapshot())
        assert first.result() is True
        assert second.result() is True

    stats = store.load_stats()
    assert stats["intents"]["help"]["count"] == 2
    assert stats["rate_limits"]["7"] == 3
    assert stats["nlu"]["pending"]["staged"] == 1


def test_dashboard_counters_add_only_unsaved_live_deltas(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    assert store.save_stats(
        {"help": {"count": 5, "low_confidence": 1, "errors": 0}},
        {"7": 5},
    )
    monitor = SimpleNamespace(
        get_unsaved_rate_stats=lambda: {"7": 2},
        get_unsaved_intent_stats=lambda: {
            "help": {"count": 2, "low_confidence": 1, "errors": 0}
        },
    )

    rates = collect_rate_limits(monitor, store=store)
    intents = collect_intent_stats(monitor, store=store)

    assert rates == {
        "user_stats": {"user_1": {"requests": 7}},
        "summary": {"total_requests": 7},
    }
    assert intents == {
        "intent_counts": {"help": 7},
        "fallback_count": 2,
    }


def test_dashboard_intent_projection_drops_unknown_live_names(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    monitor = SimpleNamespace(
        get_unsaved_intent_stats=lambda: {
            "help": {"count": 2, "low_confidence": 1, "errors": 0},
            "PRIVATE LIVE UTTERANCE": {
                "count": 4,
                "low_confidence": 9,
                "errors": 0,
            },
        }
    )

    assert collect_intent_stats(monitor, store=store) == {
        "intent_counts": {"help": 2},
        "fallback_count": 1,
    }


def test_full_live_counter_fallback_is_not_added_to_persisted_prefix(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    assert store.save_stats(
        {"help": {"count": 5, "low_confidence": 1, "errors": 0}},
        {"7": 5},
    )
    monitor = SimpleNamespace(
        rate_limiter=SimpleNamespace(
            get_stats=lambda: {"user_stats": {"7": {"requests": 5}}}
        ),
        get_intent_stats=lambda: {
            "help": {"count": 5, "low_confidence": 1, "errors": 0}
        },
    )

    assert collect_rate_limits(monitor, store=store)["summary"] == {
        "total_requests": 5
    }
    assert collect_intent_stats(monitor, store=store) == {
        "intent_counts": {"help": 5},
        "fallback_count": 1,
    }


def test_state_collector_retains_the_injected_store(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    collector = StateCollector(store=store)

    assert collector.store is store


def test_reminder_runtime_projection_drops_content_and_bad_values():
    sanitized = sanitize_reminder_runtime(
        {
            "status": "ok",
            "running": True,
            "stale": False,
            "last_check_at": "2026-07-16T01:00:00+02:00",
            "last_success_at": "not-a-date",
            "last_error_at": None,
            "last_error_code": "RAW-EXCEPTION",
            "last_error": "CANARY-PRIVATE-ERROR",
            "consecutive_errors": -1,
            "stats": {"cycles": 4, "due_sent": True, "unknown": 99},
        }
    )

    assert sanitized["status"] == "ok"
    assert sanitized["last_success_at"] is None
    assert sanitized["last_error_code"] is None
    assert sanitized["consecutive_errors"] == 0
    assert sanitized["stats"]["cycles"] == 4
    assert sanitized["stats"]["due_sent"] == 0
    assert "unknown" not in sanitized["stats"]
    assert "CANARY" not in json.dumps(sanitized)


def test_runtime_delta_helpers_bound_resets_and_invalid_counter_types():
    maximum = 2**63 - 1
    assert _counter_stats_delta(
        {
            "help": {
                "count": 2,
                "low_confidence": True,
                "errors": maximum + 99,
            }
        },
        {"help": {"count": 9, "low_confidence": 4, "errors": 0}},
    ) == {
        "help": {
            "count": 2,
            "low_confidence": 0,
            "errors": maximum,
        }
    }
    assert _flat_counter_delta(
        {"7": 3, "8": -1, "9": True},
        {"7": 10, "8": 0, "9": 0},
    ) == {"7": 3}

    metrics = NLUMetrics()
    metrics.record_pending("staged")
    assert _nested_counter_delta(metrics.snapshot(), {}) == {
        "pending": {"staged": 1}
    }


def test_monitor_reminder_snapshot_is_always_bounded_and_content_free():
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.reminder_checker = SimpleNamespace(
        get_health=lambda: {
            "status": "ok",
            "running": True,
            "stale": False,
            "last_error": "CANARY-RAW-REMINDER",
            "stats": {"cycles": 4, "private": 99},
        }
    )

    normal = monitor._bounded_reminder_runtime_snapshot()
    assert normal["status"] == "ok"
    assert normal["stats"]["cycles"] == 4
    assert "CANARY" not in json.dumps(normal)

    monitor.reminder_checker.get_health = Mock(
        side_effect=RuntimeError("CANARY-EXCEPTION")
    )
    degraded = monitor._bounded_reminder_runtime_snapshot()
    assert degraded["status"] == "degraded"
    assert degraded["running"] is False
    assert "CANARY" not in json.dumps(degraded)

    monitor.reminder_checker = None
    missing = monitor._bounded_reminder_runtime_snapshot()
    assert missing["status"] == "degraded"
    assert "CANARY" not in json.dumps(missing)


def test_monitor_counter_snapshots_are_deterministic_and_fixed_size():
    monitor = MessageMonitor.__new__(MessageMonitor)
    intent_rows = {
        f"intent-{index:03d}": {"count": index}
        for index in reversed(range(300))
    }
    rate_rows = {
        str(index): {"requests": index}
        for index in reversed(range(1, 1101))
    }
    monitor.intent_stats = intent_rows
    monitor.rate_limiter = SimpleNamespace(
        get_stats=lambda: {"user_stats": rate_rows}
    )

    intents = monitor._bounded_intent_snapshot()
    rates = monitor._bounded_rate_snapshot()
    monitor.intent_stats = dict(reversed(list(intent_rows.items())))
    rate_rows = dict(reversed(list(rate_rows.items())))

    assert len(intents) == 256
    assert intents == monitor._bounded_intent_snapshot()
    assert list(intents) == [f"intent-{index:03d}" for index in range(256)]
    assert len(rates) == 1000
    assert rates == monitor._bounded_rate_snapshot()
    assert list(rates) == [str(index) for index in range(1, 1001)]


@pytest.mark.asyncio
async def test_authenticated_status_exposes_bounded_nlu_and_public_health_omits_it(
    tmp_path,
    monkeypatch,
):
    store = ConsoleStore(data_dir=tmp_path)
    metrics = NLUMetrics()
    metrics.record_decision(
        intent=BotIntent.HELP,
        source=IntentSource.DETERMINISTIC,
        outcome="routed",
    )
    checker = SimpleNamespace(
        get_health=lambda: {
            "status": "ok",
            "running": True,
            "stale": False,
            "last_check_at": "2026-07-16T01:00:00+02:00",
            "last_success_at": "2026-07-16T01:00:00+02:00",
            "last_error_at": None,
            "last_error_code": None,
            "last_error": "CANARY-RAW-EXCEPTION",
            "consecutive_errors": 0,
            "stats": {"cycles": 2},
        }
    )
    client = SimpleNamespace(
        user=SimpleNamespace(id=7),
        guilds=[],
        start_time=None,
        latency=0.1,
        is_ready=lambda: True,
        is_closed=lambda: False,
        config=SimpleNamespace(AI_PROVIDER="openrouter"),
    )
    monitor = SimpleNamespace(
        client=client,
        nlu_metrics=metrics,
        reminder_checker=checker,
        calendar=SimpleNamespace(
            gcal_enabled=True,
            last_gcal_sync_error="CANARY-CALENDAR-EXCEPTION",
        ),
        get_task_health=lambda: {
            "worker": {
                "state": "running",
                "last_error": "CANARY-TASK-EXCEPTION",
            }
        },
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_bridge_health",
        AsyncMock(
            return_value={
                "status": "healthy",
                "lm_studio": "connected",
                "requests": 2,
                "errors": 0,
                "body": "CANARY-BRIDGE-BODY",
            }
        ),
    )

    authenticated = collect_authenticated_status(monitor, store=store)
    public = await collect_console_health(monitor, port=8080, store=store)

    assert set(authenticated) == {
        "status",
        "bot",
        "tasks",
        "persistence",
        "calendar_sync",
        "nlu",
        "reminder_runtime",
    }
    assert authenticated["nlu"] == metrics.snapshot()
    assert set(public) == {
        "status",
        "timestamp",
        "console",
        "ai_provider",
        "bot",
        "bridge",
        "persistence",
        "tasks",
        "calendar_sync",
        "reminder_runtime",
    }
    assert "nlu" not in public
    assert set(public["reminder_runtime"]) == {
        "status",
        "running",
        "stale",
        "last_success_at",
    }
    rendered = json.dumps(
        {"authenticated": authenticated, "public": public},
        sort_keys=True,
    )
    assert "CANARY" not in rendered
    def nested_keys(value):
        if isinstance(value, dict):
            return set(value).union(
                *(nested_keys(item) for item in value.values())
            )
        if isinstance(value, list):
            return set().union(*(nested_keys(item) for item in value))
        return set()

    observed_keys = nested_keys(
        {"authenticated": authenticated, "public": public}
    )
    for forbidden in ("last_error", "read_errors", "stats_read_error", "items"):
        assert forbidden not in observed_keys


def test_persisted_nlu_and_reminder_readback_survive_store_restart(tmp_path):
    first = ConsoleStore(data_dir=tmp_path)
    metrics = NLUMetrics()
    metrics.record_pending("staged")
    assert first.save_stats(
        {},
        {},
        nlu_stats=metrics.snapshot(),
        reminder_runtime={
            "status": "ok",
            "running": True,
            "stale": False,
            "last_success_at": "2026-07-16T01:00:00+02:00",
            "stats": {"cycles": 3},
        },
    )

    second = ConsoleStore(data_dir=tmp_path)

    assert second.load_nlu_stats()["pending"]["staged"] == 1
    reminder = second.load_reminder_runtime()
    assert reminder["status"] == "ok"
    assert reminder["stats"]["cycles"] == 3
