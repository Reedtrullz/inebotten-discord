"""Persistent storage for web console data across restarts."""

from __future__ import annotations

# pyright: reportAny=false

import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime
from typing import Any

from utils.json_storage import hermes_discord_data_dir, write_json_atomic


STATS_SCHEMA_VERSION = 2


def _empty_stats() -> dict[str, Any]:
    return {"version": STATS_SCHEMA_VERSION, "intents": {}, "rate_limits": {}, "last_saved": None}


class ConsoleStore:
    """Append-only JSONL store for logs and cumulative stats."""

    def __init__(self) -> None:
        self._data_dir = hermes_discord_data_dir() / "console"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._data_dir, 0o700)
        except OSError:
            pass

        self._logs_file = self._data_dir / "logs.jsonl"
        self._stats_file = self._data_dir / "stats.json"
        self._sessions_file = self._data_dir / "sessions.json"
        self._first_start_file = self._data_dir / "first_start.txt"
        self._lock = threading.RLock()

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
                try:
                    os.chmod(self._logs_file, 0o600)
                except OSError:
                    pass
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
            existing["version"] = STATS_SCHEMA_VERSION
            existing.setdefault("intents", {})
            existing.setdefault("rate_limits", {})

            for intent, stats in intent_stats.items():
                if intent not in existing["intents"]:
                    existing["intents"][intent] = {"count": 0, "low_confidence": 0, "errors": 0}
                existing["intents"][intent]["count"] += int(stats.get("count", 0))
                existing["intents"][intent]["low_confidence"] += int(stats.get("low_confidence", 0))
                existing["intents"][intent]["errors"] += int(stats.get("errors", 0))

            for user, count in rate_limit_stats.items():
                existing["rate_limits"][user] = existing["rate_limits"].get(user, 0) + int(count)

            existing["last_saved"] = datetime.now().isoformat()

            with self._lock:
                write_json_atomic(self._stats_file, existing, indent=None)
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
                    data = json.load(handle)
                if not isinstance(data, dict) or data.get("version") != STATS_SCHEMA_VERSION:
                    return _empty_stats()
                data.setdefault("intents", {})
                data.setdefault("rate_limits", {})
                data.setdefault("last_saved", None)
                return data
        except Exception:
            pass
        return _empty_stats()

    def create_session(self, ttl_seconds: int, binding_hash: str | None = None) -> str:
        """Create and persist a browser session token; returns the raw token."""
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + max(1, ttl_seconds)
        with self._lock:
            sessions = self._load_sessions_raw_unlocked()
            self._prune_sessions_unlocked(sessions)
            sessions[self._hash_token(token)] = {
                "created_at": int(time.time()),
                "expires_at": expires_at,
                "binding_hash": binding_hash,
            }
            self._save_sessions_unlocked(sessions)
        return token

    def validate_session(self, token: str | None, binding_hash: str | None = None) -> bool:
        """Return True if a session token exists and has not expired."""
        if not token:
            return False
        token_hash = self._hash_token(token)
        with self._lock:
            sessions = self._load_sessions_raw_unlocked()
            session = sessions.get(token_hash)
            if not session:
                return False
            if int(session.get("expires_at", 0)) <= int(time.time()):
                sessions.pop(token_hash, None)
                self._save_sessions_unlocked(sessions)
                return False
            if session.get("binding_hash") != binding_hash:
                sessions.pop(token_hash, None)
                self._save_sessions_unlocked(sessions)
                return False
            return True

    def delete_session(self, token: str | None) -> None:
        """Delete a persisted browser session token if present."""
        if not token:
            return
        token_hash = self._hash_token(token)
        with self._lock:
            sessions = self._load_sessions_raw_unlocked()
            if token_hash in sessions:
                sessions.pop(token_hash, None)
                self._save_sessions_unlocked(sessions)

    def prune_expired_sessions(self) -> None:
        """Remove expired browser sessions."""
        with self._lock:
            sessions = self._load_sessions_raw_unlocked()
            if self._prune_sessions_unlocked(sessions):
                self._save_sessions_unlocked(sessions)

    def _load_sessions_raw_unlocked(self) -> dict[str, dict[str, Any]]:
        try:
            if self._sessions_file.exists():
                with self._sessions_file.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return {
                        str(key): value
                        for key, value in data.items()
                        if isinstance(value, dict)
                    }
        except Exception:
            pass
        return {}

    def _save_sessions_unlocked(self, sessions: dict[str, dict[str, Any]]) -> None:
        write_json_atomic(self._sessions_file, sessions)

    def _prune_sessions_unlocked(self, sessions: dict[str, dict[str, Any]]) -> bool:
        now = int(time.time())
        before = len(sessions)
        expired = [
            token_hash
            for token_hash, session in sessions.items()
            if int(session.get("expires_at", 0)) <= now
        ]
        for token_hash in expired:
            sessions.pop(token_hash, None)
        return len(sessions) != before

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

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
