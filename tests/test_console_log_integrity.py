from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from utils.logger import LogBuffer
from web_console import console_store
from web_console.console_store import ConsoleStore, STATS_SCHEMA_VERSION
from web_console.state_collector import StateCollector, collect_intent_stats, collect_logs


def test_log_buffer_does_not_duplicate_successfully_persisted_lines(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    buffer = LogBuffer(store=store)

    buffer.append("one")
    buffer.append("two")

    assert buffer.get_lines() == ["one", "two"]


def test_log_buffer_keeps_failed_writes_visible_until_retry(tmp_path, monkeypatch):
    store = ConsoleStore(data_dir=tmp_path)
    buffer = LogBuffer(store=store)
    real_append = store.append_logs
    attempts = 0

    def fail_once(lines):
        nonlocal attempts
        attempts += 1
        return False if attempts == 1 else real_append(lines)

    monkeypatch.setattr(store, "append_logs", fail_once)
    buffer.append("waiting")
    assert buffer.get_lines() == ["waiting"]

    buffer.append("persisted")
    assert buffer.get_lines() == ["waiting", "persisted"]


def test_torn_log_append_rolls_back_before_log_buffer_retry(
    tmp_path,
    monkeypatch,
):
    store = ConsoleStore(data_dir=tmp_path)
    buffer = LogBuffer(store=store)
    real_write = store._write_log_payload_unlocked
    attempts = 0

    def tear_once(payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            with store._logs_file.open("ab") as handle:
                handle.write(payload[: max(1, len(payload) // 2)])
                handle.flush()
            raise OSError("private torn-write detail")
        real_write(payload)

    monkeypatch.setattr(store, "_write_log_payload_unlocked", tear_once)

    buffer.append("one")

    assert buffer.get_lines() == ["one"]
    assert store._logs_file.read_bytes() == b""
    assert store.health()["status"] == "degraded"
    assert store.health()["error_code"] == "append_logs"

    buffer.append("two")

    assert buffer.get_lines() == ["one", "two"]
    health = store.health()
    assert health["status"] == "ok"
    assert health["error_code"] is None
    for raw in store._logs_file.read_bytes().splitlines():
        assert isinstance(json.loads(raw), dict)


def test_uncertain_complete_append_is_rolled_back_before_retry(
    tmp_path,
    monkeypatch,
):
    store = ConsoleStore(data_dir=tmp_path)
    real_write = store._write_log_payload_unlocked
    real_truncate = store._truncate_log_unlocked
    write_attempts = 0
    rollback_attempts = 0

    def write_then_raise_once(payload):
        nonlocal write_attempts
        write_attempts += 1
        real_write(payload)
        if write_attempts == 1:
            raise OSError("private ambiguous flush detail")

    def fail_first_rollback(offset):
        nonlocal rollback_attempts
        rollback_attempts += 1
        if rollback_attempts == 1:
            raise OSError("private rollback detail")
        real_truncate(offset)

    monkeypatch.setattr(
        store,
        "_write_log_payload_unlocked",
        write_then_raise_once,
    )
    monkeypatch.setattr(
        store,
        "_truncate_log_unlocked",
        fail_first_rollback,
    )

    assert store.append_logs(["same"]) is False
    assert store.load_logs() == ["same"]
    assert store.health()["status"] == "degraded"

    assert store.append_logs(["same"]) is True

    assert store.load_logs() == ["same"]
    health = store.health()
    assert health["status"] == "ok"
    assert health["error_code"] is None
    assert write_attempts == 2
    assert rollback_attempts == 2


def test_valid_final_json_record_without_newline_survives_next_append(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    store._logs_file.write_bytes(
        json.dumps({"line": "valid-without-newline"}).encode("utf-8")
    )

    assert store.load_logs() == ["valid-without-newline"]
    assert store.health()["status"] == "ok"
    assert store.append_logs(["next"]) is True

    assert store.load_logs() == ["valid-without-newline", "next"]
    assert store._logs_file.read_bytes().endswith(b"\n")
    assert store.health()["status"] == "ok"


def test_log_read_failure_is_bounded_in_health_and_recovers(
    tmp_path,
    monkeypatch,
):
    store = ConsoleStore(data_dir=tmp_path)
    assert store.append_logs(["one"]) is True
    real_tail = store._tail_log_records_unlocked

    def fail_tail(*, max_records, max_bytes):
        del max_records, max_bytes
        raise OSError("private read detail")

    monkeypatch.setattr(store, "_tail_log_records_unlocked", fail_tail)

    assert store.load_logs() == []
    degraded = store.health()
    assert degraded["status"] == "degraded"
    assert degraded["error_code"] == "load_logs"
    assert "private read detail" not in repr(degraded)

    monkeypatch.setattr(store, "_tail_log_records_unlocked", real_tail)
    recovered = store.health()
    assert recovered["status"] == "ok"
    assert recovered["error_code"] is None


def test_log_buffer_serializes_pending_retry_across_threads():
    class ConcurrentStore:
        def __init__(self):
            self.calls = 0
            self.lines = []
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def append_logs(self, lines):
            with self.lock:
                self.calls += 1
                if self.calls == 1:
                    return False
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.01)
            with self.lock:
                self.lines.extend(lines)
                self.active -= 1
            return True

        def load_logs(self, count):
            with self.lock:
                return list(self.lines[-count:])

    store = ConcurrentStore()
    buffer = LogBuffer(store=store)
    buffer.append("waiting")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(buffer.append, [f"line-{index}" for index in range(8)]))

    assert store.max_active == 1
    assert store.lines.count("waiting") == 1
    assert sorted(store.lines[1:]) == [f"line-{index}" for index in range(8)]
    assert sorted(buffer.get_lines(100)[1:]) == [
        f"line-{index}" for index in range(8)
    ]


def test_collect_logs_uses_only_the_injected_store(tmp_path):
    first = ConsoleStore(data_dir=tmp_path / "first")
    second = ConsoleStore(data_dir=tmp_path / "second")
    first.append_logs(["first-only"])
    second.append_logs(["second-only"])

    assert collect_logs(store=second) == {"logs": ["second-only"]}


@pytest.mark.asyncio
async def test_state_collector_passes_its_store_to_logs(tmp_path, monkeypatch):
    store = ConsoleStore(data_dir=tmp_path)
    store.append_logs(["injected"])
    collector = StateCollector(store=store)

    monkeypatch.setattr(
        "web_console.state_collector.collect_bridge_health",
        lambda _monitor: _async_value({}),
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_bot_status",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_calendar_data",
        lambda _monitor: {},
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_poll_data",
        lambda _monitor: {},
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_rate_limits",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_intent_stats",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "web_console.state_collector.collect_memory_stats",
        lambda _monitor: {},
    )

    assert (await collector.collect_all())["logs"] == {"logs": ["injected"]}


async def _async_value(value):
    return value


def test_corrupt_persisted_intent_row_is_ignored_before_monitor_ready(tmp_path):
    stats_file = tmp_path / "stats.json"
    stats_file.write_text(
        json.dumps(
            {
                "version": STATS_SCHEMA_VERSION,
                "intents": {
                    "help": {"count": 2, "low_confidence": 1},
                    "corrupt": "not-a-counter-row",
                },
                "rate_limits": {},
                "nlu": {},
                "reminder_runtime": {},
                "last_saved": None,
            }
        ),
        encoding="utf-8",
    )
    store = ConsoleStore(data_dir=tmp_path)

    assert collect_intent_stats(None, store=store) == {
        "intent_counts": {"help": 2},
        "fallback_count": 1,
    }


def test_log_store_compacts_and_loads_only_the_bounded_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(console_store, "MAX_LOG_FILE_BYTES", 600)
    monkeypatch.setattr(console_store, "LOG_COMPACT_TARGET_BYTES", 300)
    monkeypatch.setattr(console_store, "LOG_TAIL_CHUNK_BYTES", 64)
    store = ConsoleStore(data_dir=tmp_path)

    for index in range(40):
        assert store.append_logs([f"line-{index:02d}-" + ("x" * 40)]) is True

    logs_file = tmp_path / "logs.jsonl"
    assert logs_file.stat().st_size <= 600
    loaded = store.load_logs(2_000)
    assert loaded[-1].startswith("line-39-")
    assert len(loaded) < 40


def test_log_tail_reader_skips_corrupt_and_partial_records(tmp_path):
    store = ConsoleStore(data_dir=tmp_path)
    logs_file = tmp_path / "logs.jsonl"
    logs_file.write_bytes(
        b'partial-prefix\n{"line":"valid-one"}\nnot-json\n'
        b'{"line":"valid-two"}\n'
    )

    assert store.load_logs(2) == ["valid-one", "valid-two"]
