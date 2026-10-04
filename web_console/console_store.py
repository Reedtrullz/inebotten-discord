"""Persistent storage for web console data across restarts."""

from __future__ import annotations

# pyright: reportAny=false

import hashlib
import os
import secrets
import threading
import time
from datetime import datetime
from typing import Any

from utils.json_storage import hermes_discord_data_dir, write_json_atomic
from utils.storage_contract import DocumentOwner, StorageLoad, StorageMutationError


STATS_SCHEMA_VERSION = 2


def _empty_stats() -> dict[str, Any]:
    return {"version": STATS_SCHEMA_VERSION, "intents": {}, "rate_limits": {}, "last_saved": None}


class ConsoleStore:
    """Bounded diagnostic logs, cumulative stats and private browser sessions."""

    def __init__(self, *, max_log_bytes: int = 8 * 1024 * 1024, log_retention_days: int = 7) -> None:
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
        from web_console.log_store import DiagnosticLogs
        self.max_log_bytes = max_log_bytes
        self._diagnostic_logs = DiagnosticLogs(self._logs_file, max_log_bytes, log_retention_days)
        self._stats_storage = DocumentOwner(self._stats_file, lambda d: (
            d.get("version") == STATS_SCHEMA_VERSION and isinstance(d.get("intents", {}), dict)
            and isinstance(d.get("rate_limits", {}), dict)))
        self._sessions_storage = DocumentOwner(self._sessions_file, lambda d: all(
            isinstance(value, dict) and type(value.get("expires_at")) in (int, float)
            for value in d.values()))
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._last_stats_saved_at: str | None = None
        self._last_log_write_at: str | None = None

        if not self._first_start_file.exists():
            self._first_start_file.write_text(datetime.now().isoformat(), encoding="utf-8")

    def append_logs(self, lines: list[str]) -> None:
        if not lines:
            return
        try:
            with self._lock:
                for line in lines:
                    self._diagnostic_logs.append(line=line)
            self._record_success("logs")
        except Exception as exc:
            self._record_error("append_logs", exc)

    def load_logs(self, count: int = 200) -> list[str]:
        try:
            page = self.read_log_page(None, max_bytes=65536, filters={})
            return [row['line'] for row in reversed(page['records'][:max(1, min(count, 2000))])]
        except Exception:
            return []

    def append_record(self, **record) -> None:
        with self._lock:
            self._diagnostic_logs.append(**record)
        self._record_success('logs')

    def read_log_page(self, cursor: str | None, *, max_bytes: int, filters: dict) -> dict:
        with self._lock:
            return self._diagnostic_logs.read(cursor, max_bytes, filters)

    def close(self) -> None:
        with self._lock:
            self._diagnostic_logs.close()
            self._stats_storage.close()
            self._sessions_storage.close()

    def save_stats(self, intent_stats: dict[str, Any], rate_limit_stats: dict[str, int]) -> bool:
        try:
            with self._lock:
                self._stats_storage.claim()
                existing = self._load_stats_raw()
                self._stats_storage.require_writable()
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

                result = self._stats_storage.commit(existing, writer=write_json_atomic)
                if not result.ok:
                    raise StorageMutationError(result.error_code)
            self._record_success("stats")
            return True
        except Exception as exc:
            self._record_error("save_stats", exc)
            return False

    def load_intent_stats(self) -> dict[str, dict[str, int]]:
        return self._load_stats_raw().get("intents", {})

    def load_rate_limit_stats(self) -> dict[str, int]:
        return self._load_stats_raw().get("rate_limits", {})

    def _load_stats_raw(self) -> dict[str, Any]:
        with self._lock:
            data = self._stats_storage.load()
            if self._stats_storage.state.status == "corrupt" and data == {}:
                # A payload version mismatch is unsupported, not permission to reset.
                from utils.storage_contract import load_document
                raw = load_document(self._stats_file, 1)
                if raw.status == "valid" and raw.document.get("version") != STATS_SCHEMA_VERSION:
                    self._stats_storage.state = StorageLoad("unsupported", error_code="unsupported_stats_schema")
            state = self._stats_storage.state
            if state.status in ("corrupt", "unsupported"):
                self._record_error("load_stats", StorageMutationError(state.error_code))
                return _empty_stats()
            if self._last_error and self._last_error.startswith("load_stats:"):
                self._last_error = self._last_error_at = None
            return data or _empty_stats()

    def create_session(self, ttl_seconds: int, binding_hash: str | None = None) -> str:
        """Create and persist a browser session token; returns the raw token."""
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + max(1, ttl_seconds)
        with self._lock:
            self._sessions_storage.claim()
            sessions = self._load_sessions_raw_unlocked()
            self._sessions_storage.require_writable()
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
                self._sessions_storage.claim()
                sessions.pop(token_hash, None)
                self._save_sessions_unlocked(sessions)
                return False
            if session.get("binding_hash") != binding_hash:
                self._sessions_storage.claim()
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
            self._sessions_storage.claim()
            sessions = self._load_sessions_raw_unlocked()
            if token_hash in sessions:
                sessions.pop(token_hash, None)
                self._save_sessions_unlocked(sessions)

    def prune_expired_sessions(self) -> None:
        """Remove expired browser sessions."""
        with self._lock:
            self._sessions_storage.claim()
            sessions = self._load_sessions_raw_unlocked()
            if self._prune_sessions_unlocked(sessions):
                self._save_sessions_unlocked(sessions)

    def _load_sessions_raw_unlocked(self) -> dict[str, dict[str, Any]]:
        data = self._sessions_storage.load()
        if self._sessions_storage.state.status in ("corrupt", "unsupported"):
            self._record_error("load_sessions", StorageMutationError(self._sessions_storage.state.error_code))
        return data

    def _save_sessions_unlocked(self, sessions: dict[str, dict[str, Any]]) -> None:
        result = self._sessions_storage.commit(sessions, writer=write_json_atomic)
        if not result.ok:
            self._record_error("save_sessions", StorageMutationError(result.error_code))
            raise StorageMutationError(result.error_code)

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

    def health(self) -> dict[str, Any]:
        """Return non-secret diagnostics for console persistence."""
        stats_read_error = self._stats_read_error()
        if not stats_read_error and self._last_error and self._last_error.startswith("load_stats:"):
            self._last_error = None
            self._last_error_at = None
        return {
            "status": "degraded" if self._last_error or stats_read_error else "ok",
            "stats_schema_version": STATS_SCHEMA_VERSION,
            "stats_storage_status": self._stats_storage.state.status,
            "sessions_storage_status": self._sessions_storage.state.status,
            "last_stats_saved_at": self._last_stats_saved_at,
            "last_log_write_at": self._last_log_write_at,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "stats_read_error": stats_read_error,
        }

    def _stats_read_error(self) -> str | None:
        self._load_stats_raw()
        return self._stats_storage.state.error_code

    def _record_success(self, operation: str) -> None:
        now = datetime.now().isoformat()
        if operation == "stats":
            self._last_stats_saved_at = now
        elif operation == "logs":
            self._last_log_write_at = now
        self._last_error = None
        self._last_error_at = None

    def _record_error(self, operation: str, exc: Exception) -> None:
        self._last_error = f"{operation}: {exc}"
        self._last_error_at = datetime.now().isoformat()


_store: ConsoleStore | None = None


def get_console_store() -> ConsoleStore:
    global _store
    if _store is None:
        _store = ConsoleStore()
    return _store
