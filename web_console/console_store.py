"""Persistent storage for web console data across restarts."""

from __future__ import annotations

# pyright: reportAny=false

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class ConsoleStore:
    """Append-only JSONL store for logs and cumulative stats."""

    def __init__(self) -> None:
        self._data_dir = Path.home() / ".hermes" / "discord" / "data" / "console"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._logs_file = self._data_dir / "logs.jsonl"
        self._stats_file = self._data_dir / "stats.json"
        self._first_start_file = self._data_dir / "first_start.txt"
        self._lock = threading.Lock()

        if not self._first_start_file.exists():
            self._first_start_file.write_text(datetime.now().isoformat(), encoding="utf-8")

    def append_logs(self, lines: list[str]) -> None:
        if not lines:
            return
        try:
            with self._lock, self._logs_file.open("a", encoding="utf-8") as handle:
                for line in lines:
                    record = {"line": line, "ts": datetime.now().isoformat()}
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def load_logs(self, count: int = 200) -> list[str]:
        try:
            if not self._logs_file.exists():
                return []
            with self._lock, self._logs_file.open("r", encoding="utf-8") as handle:
                raw_lines = handle.readlines()
            parsed: list[str] = []
            for raw in raw_lines[-count:]:
                try:
                    parsed.append(json.loads(raw)["line"])
                except Exception:
                    continue
            return parsed
        except Exception:
            return []

    def save_stats(self, intent_stats: dict[str, Any], rate_limit_stats: dict[str, int]) -> None:
        try:
            existing = self._load_stats_raw()

            for intent, stats in intent_stats.items():
                if intent not in existing["intents"]:
                    existing["intents"][intent] = {"count": 0, "low_confidence": 0, "errors": 0}
                existing["intents"][intent]["count"] += int(stats.get("count", 0))
                existing["intents"][intent]["low_confidence"] += int(stats.get("low_confidence", 0))
                existing["intents"][intent]["errors"] += int(stats.get("errors", 0))

            for user, count in rate_limit_stats.items():
                existing["rate_limits"][user] = existing["rate_limits"].get(user, 0) + int(count)

            existing["last_saved"] = datetime.now().isoformat()

            with self._lock, self._stats_file.open("w", encoding="utf-8") as handle:
                json.dump(existing, handle, ensure_ascii=False)
        except Exception:
            pass

    def load_intent_stats(self) -> dict[str, dict[str, int]]:
        return self._load_stats_raw().get("intents", {})

    def load_rate_limit_stats(self) -> dict[str, int]:
        return self._load_stats_raw().get("rate_limits", {})

    def _load_stats_raw(self) -> dict[str, Any]:
        try:
            if self._stats_file.exists():
                with self._lock, self._stats_file.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
        except Exception:
            pass
        return {"intents": {}, "rate_limits": {}, "last_saved": None}

    def first_start_time(self) -> datetime:
        try:
            if self._first_start_file.exists():
                return datetime.fromisoformat(self._first_start_file.read_text(encoding="utf-8").strip())
        except Exception:
            pass
        return datetime.now()


_store: ConsoleStore | None = None


def get_console_store() -> ConsoleStore:
    global _store
    if _store is None:
        _store = ConsoleStore()
    return _store
