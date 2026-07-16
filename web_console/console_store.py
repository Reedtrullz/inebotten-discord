"""Persistent storage for web console data across restarts."""

from __future__ import annotations

# pyright: reportAny=false

import hashlib
import json
import os
import secrets
import threading
import time
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from core.intent_models import BotIntent
from core.nlu_metrics import ALLOWED_METRIC_KEYS
from utils.json_storage import hermes_discord_data_dir, write_json_atomic


STATS_SCHEMA_VERSION = 3
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_COMPACT_TARGET_BYTES = MAX_LOG_FILE_BYTES // 2
MAX_LOG_READ_RECORDS = 2_000
MAX_LOG_LINE_CHARS = 16_384
LOG_TAIL_CHUNK_BYTES = 64 * 1024
STORE_ERROR_CODES = frozenset(
    {
        "load_stats",
        "load_logs",
        "save_stats",
        "append_logs",
        "read_error",
        "unsupported_stats_schema",
        "other",
    }
)
REMINDER_STATUS_VALUES = frozenset({"starting", "ok", "degraded", "stopped"})
REMINDER_RUNTIME_ERROR_VALUES = frozenset(
    {"cycle_error", "gcal_sync_error", "delivery_failure", "storage_error"}
)
REMINDER_STAT_KEYS = frozenset(
    {
        "cycles",
        "warning_30m_sent",
        "due_sent",
        "digest_sent",
        "delivery_failures",
        "skipped_missing_channel",
        "malformed_legacy_due_at",
        "legacy_due_mismatch",
        "missed_outside_catchup",
        "gcal_sync_errors",
        "cycle_errors",
    }
)
INTENT_STAT_NAMES = frozenset(intent.value for intent in BotIntent) | {
    "unknown"
}
INTENT_COUNTER_KEYS = ("count", "low_confidence", "errors")


class UnsupportedStatsSchemaError(ValueError):
    """Raised internally when a stats file must remain byte-identical."""


def _empty_stats() -> dict[str, Any]:
    return {
        "version": STATS_SCHEMA_VERSION,
        "intents": {},
        "rate_limits": {},
        "nlu": {},
        "reminder_runtime": {},
        "last_saved": None,
    }


def _iso_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def sanitize_nlu_stats(raw: Mapping[str, object]) -> dict[str, dict[str, int]]:
    """Project persisted NLU counters onto the finite privacy-safe schema."""

    safe: dict[str, dict[str, int]] = {}
    for section in sorted(ALLOWED_METRIC_KEYS):
        values = raw.get(section)
        if not isinstance(values, Mapping):
            continue
        counters = {
            key: value
            for key in sorted(ALLOWED_METRIC_KEYS[section])
            if (
                isinstance((value := values.get(key)), int)
                and not isinstance(value, bool)
                and value >= 0
            )
        }
        if counters:
            safe[section] = counters
    return safe


def sanitize_intent_stats(
    raw: Mapping[str, object],
) -> dict[str, dict[str, int]]:
    """Keep only finite route names and their exact legacy counters."""

    safe: dict[str, dict[str, int]] = {}
    for intent in sorted(INTENT_STAT_NAMES):
        values = raw.get(intent)
        if not isinstance(values, Mapping):
            continue
        safe[intent] = {
            key: _nonnegative_int(values.get(key))
            for key in INTENT_COUNTER_KEYS
        }
    return safe


def sanitize_rate_limit_stats(raw: Mapping[str, object]) -> dict[str, int]:
    """Keep only bounded ASCII-decimal user identifiers and counters."""

    return {
        user: value
        for user, value in sorted(raw.items(), key=lambda item: str(item[0]))
        if (
            isinstance(user, str)
            and 1 <= len(user) <= 32
            and user.isascii()
            and user.isdigit()
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        )
    }


def sanitize_reminder_runtime(raw: Mapping[str, object]) -> dict[str, object]:
    """Project checker health onto one bounded, content-free schema."""

    empty_stats = {key: 0 for key in sorted(REMINDER_STAT_KEYS)}
    safe_degraded: dict[str, object] = {
        "status": "degraded",
        "running": False,
        "stale": True,
        "last_check_at": None,
        "last_success_at": None,
        "last_error_at": None,
        "last_error_code": None,
        "consecutive_errors": 0,
        "stats": empty_stats,
    }
    try:
        status = raw.get("status")
        raw_stats = raw.get("stats")
        stats = raw_stats if isinstance(raw_stats, Mapping) else {}
        error = raw.get("last_error_code")
        valid_status = (
            status if isinstance(status, str) and status in REMINDER_STATUS_VALUES else None
        )
        if valid_status is None:
            return safe_degraded
        return {
            "status": valid_status,
            "running": (
                raw.get("running")
                if isinstance(raw.get("running"), bool)
                else False
            ),
            "stale": (
                raw.get("stale") if isinstance(raw.get("stale"), bool) else True
            ),
            "last_check_at": _iso_or_none(raw.get("last_check_at")),
            "last_success_at": _iso_or_none(raw.get("last_success_at")),
            "last_error_at": _iso_or_none(raw.get("last_error_at")),
            "last_error_code": (
                error
                if isinstance(error, str)
                and error in REMINDER_RUNTIME_ERROR_VALUES
                else None
            ),
            "consecutive_errors": _nonnegative_int(raw.get("consecutive_errors")),
            "stats": {
                key: _nonnegative_int(stats.get(key))
                for key in sorted(REMINDER_STAT_KEYS)
            },
        }
    except Exception:
        return safe_degraded


class ConsoleStore:
    """Bounded JSONL log storage plus cumulative console statistics."""

    def __init__(self, *, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir if data_dir is not None else hermes_discord_data_dir() / "console"
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
        self._health_errors: dict[str, str] = {}
        self._last_stats_saved_at: str | None = None
        self._last_log_write_at: str | None = None
        self._pending_log_rollback_offset: int | None = None

        if not self._first_start_file.exists():
            self._first_start_file.write_text(datetime.now().isoformat(), encoding="utf-8")

    def append_logs(self, lines: list[str]) -> bool:
        if not lines:
            return True
        with self._lock:
            try:
                timestamp = datetime.now().isoformat()
                serialized = "".join(
                    json.dumps(
                        {
                            "line": str(line)[:MAX_LOG_LINE_CHARS],
                            "ts": timestamp,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                    for line in lines
                )
                payload = serialized.encode("utf-8")
                self._finish_pending_log_rollback_unlocked()
                self._repair_incomplete_log_tail_unlocked()
                start_offset = (
                    self._logs_file.stat().st_size
                    if self._logs_file.exists()
                    else 0
                )
                try:
                    self._write_log_payload_unlocked(payload)
                except Exception:
                    self._pending_log_rollback_offset = start_offset
                    try:
                        self._truncate_log_unlocked(start_offset)
                    except Exception:
                        pass
                    else:
                        self._pending_log_rollback_offset = None
                    raise
                try:
                    os.chmod(self._logs_file, 0o600)
                except OSError:
                    pass
                self._record_success_unlocked("logs_write")
            except Exception as exc:
                self._record_error_unlocked("append_logs", exc)
                return False

            # A compaction failure must not make LogBuffer retry lines that
            # were already appended successfully. Keep the store degraded and
            # retry compaction on a later write instead.
            try:
                if self._logs_file.stat().st_size > MAX_LOG_FILE_BYTES:
                    self._compact_logs_unlocked()
            except Exception as exc:
                self._record_error_unlocked("append_logs", exc)
            return True

    def _write_log_payload_unlocked(self, payload: bytes) -> None:
        """Append one complete UTF-8 payload or raise for caller rollback."""
        with self._logs_file.open("ab") as handle:
            written = handle.write(payload)
            if written != len(payload):
                raise OSError("incomplete_log_append")
            handle.flush()

    def _truncate_log_unlocked(self, offset: int) -> None:
        """Restore the byte boundary from before a failed append."""
        if not self._logs_file.exists():
            return
        with self._logs_file.open("r+b") as handle:
            handle.truncate(max(0, offset))
            handle.flush()

    def _finish_pending_log_rollback_unlocked(self) -> None:
        """Resolve an ambiguous earlier append before accepting a retry."""
        offset = self._pending_log_rollback_offset
        if offset is None:
            return
        self._truncate_log_unlocked(offset)
        self._pending_log_rollback_offset = None

    def _repair_incomplete_log_tail_unlocked(self) -> None:
        """Drop a prior torn tail before retrying its logical record."""
        if not self._logs_file.exists():
            return
        size = self._logs_file.stat().st_size
        if size <= 0:
            return
        with self._logs_file.open("r+b") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) == b"\n":
                return
            position = size
            boundary = 0
            while position > 0:
                chunk_size = min(LOG_TAIL_CHUNK_BYTES, position)
                position -= chunk_size
                handle.seek(position)
                chunk = handle.read(chunk_size)
                separator = chunk.rfind(b"\n")
                if separator >= 0:
                    boundary = position + separator + 1
                    break
            handle.seek(boundary)
            tail = handle.read(size - boundary)
            try:
                record = json.loads(tail)
                complete_record = bool(
                    isinstance(record, dict)
                    and isinstance(record.get("line"), str)
                )
            except Exception:
                complete_record = False
            if complete_record:
                handle.seek(0, os.SEEK_END)
                handle.write(b"\n")
            else:
                handle.truncate(boundary)
            handle.flush()

    def load_logs(self, count: int = 200) -> list[str]:
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            return []
        bounded_count = min(count, MAX_LOG_READ_RECORDS)
        with self._lock:
            try:
                scan_records = min(
                    MAX_LOG_READ_RECORDS,
                    max(64, bounded_count * 2),
                )
                raw_lines = self._tail_log_records_unlocked(
                    max_records=scan_records,
                    max_bytes=MAX_LOG_FILE_BYTES,
                )
                parsed: list[str] = []
                malformed = False
                for raw in raw_lines:
                    try:
                        record = json.loads(raw)
                        line = record.get("line") if isinstance(record, dict) else None
                        if isinstance(line, str):
                            parsed.append(line)
                        else:
                            malformed = True
                    except Exception:
                        malformed = True
                if malformed:
                    self._record_error_unlocked(
                        "load_logs",
                        ValueError("invalid_log_record"),
                    )
                else:
                    self._record_success_unlocked("logs_read")
                return parsed[-bounded_count:]
            except Exception as exc:
                self._record_error_unlocked("load_logs", exc)
                return []

    def _compact_logs_unlocked(self) -> None:
        """Retain a bounded, complete tail of the append-only log."""

        raw_lines = self._tail_log_records_unlocked(
            max_records=MAX_LOG_READ_RECORDS,
            max_bytes=LOG_COMPACT_TARGET_BYTES,
        )
        temporary = self._logs_file.with_suffix(".jsonl.tmp")
        try:
            with temporary.open("wb") as handle:
                for raw in raw_lines:
                    handle.write(raw.rstrip(b"\r\n") + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self._logs_file)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _tail_log_records_unlocked(
        self,
        *,
        max_records: int,
        max_bytes: int,
    ) -> list[bytes]:
        """Read complete JSONL records from the tail without loading the file."""

        if not self._logs_file.exists() or max_records <= 0 or max_bytes <= 0:
            return []

        file_size = self._logs_file.stat().st_size
        position = file_size
        chunks: list[bytes] = []
        bytes_read = 0
        newline_count = 0
        with self._logs_file.open("rb") as handle:
            while (
                position > 0
                and bytes_read < max_bytes
                and newline_count <= max_records
            ):
                chunk_size = min(
                    LOG_TAIL_CHUNK_BYTES,
                    position,
                    max_bytes - bytes_read,
                )
                position -= chunk_size
                handle.seek(position)
                chunk = handle.read(chunk_size)
                chunks.append(chunk)
                bytes_read += len(chunk)
                newline_count += chunk.count(b"\n")

        raw = b"".join(reversed(chunks))
        if position > 0:
            # The first bytes are likely the suffix of a record that began
            # before the bounded read window. Never expose or persist it as a
            # malformed record.
            separator = raw.find(b"\n")
            raw = raw[separator + 1 :] if separator >= 0 else b""
        return raw.splitlines()[-max_records:]

    def save_stats(
        self,
        intent_stats: Mapping[str, Mapping[str, int]],
        rate_limit_stats: Mapping[str, int],
        *,
        nlu_stats: Mapping[str, Mapping[str, int]] | None = None,
        reminder_runtime: Mapping[str, object] | None = None,
    ) -> bool:
        """Atomically merge bounded deltas and the latest checker projection."""

        with self._lock:
            try:
                existing = self._load_stats_raw_unlocked()
                for intent, delta in intent_stats.items():
                    if (
                        not isinstance(intent, str)
                        or intent not in INTENT_STAT_NAMES
                        or not isinstance(delta, Mapping)
                    ):
                        continue
                    current = existing["intents"].setdefault(
                        intent,
                        {"count": 0, "low_confidence": 0, "errors": 0},
                    )
                    if not isinstance(current, dict):
                        current = {"count": 0, "low_confidence": 0, "errors": 0}
                        existing["intents"][intent] = current
                    for key in INTENT_COUNTER_KEYS:
                        value = delta.get(key, 0)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            current[key] = _nonnegative_int(current.get(key)) + value

                for user, value in rate_limit_stats.items():
                    user_key = str(user)
                    if (
                        not 1 <= len(user_key) <= 32
                        or not user_key.isascii()
                        or not user_key.isdigit()
                    ):
                        continue
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        current = _nonnegative_int(existing["rate_limits"].get(user_key))
                        existing["rate_limits"][user_key] = current + value

                for section, values in (nlu_stats or {}).items():
                    if section not in ALLOWED_METRIC_KEYS or not isinstance(values, Mapping):
                        continue
                    target = existing["nlu"].setdefault(section, {})
                    if not isinstance(target, dict):
                        target = {}
                        existing["nlu"][section] = target
                    for key, value in values.items():
                        if (
                            key in ALLOWED_METRIC_KEYS[section]
                            and isinstance(value, int)
                            and not isinstance(value, bool)
                            and value >= 0
                        ):
                            target[key] = _nonnegative_int(target.get(key)) + value

                # The file may predate the allowlist or have been edited by an
                # operator.  Re-project the complete cumulative subtree before
                # every write so unknown/raw-shaped keys can never survive a
                # successful merge.
                existing["nlu"] = sanitize_nlu_stats(existing["nlu"])
                existing["intents"] = sanitize_intent_stats(
                    existing["intents"]
                )
                existing["rate_limits"] = sanitize_rate_limit_stats(
                    existing["rate_limits"]
                )

                if reminder_runtime is not None:
                    existing["reminder_runtime"] = sanitize_reminder_runtime(
                        reminder_runtime
                    )
                elif existing["reminder_runtime"]:
                    existing["reminder_runtime"] = sanitize_reminder_runtime(
                        existing["reminder_runtime"]
                    )
                existing["version"] = STATS_SCHEMA_VERSION
                existing["last_saved"] = datetime.now().isoformat()
                write_json_atomic(self._stats_file, existing, indent=None)
                self._record_success_unlocked("stats_write")
                return True
            except UnsupportedStatsSchemaError:
                return False
            except Exception as exc:
                self._record_error_unlocked("save_stats", exc)
                return False

    def persist_nlu_metrics(
        self, delta: Mapping[str, Mapping[str, int]]
    ) -> bool:
        return self.save_stats({}, {}, nlu_stats=delta)

    def load_stats(self) -> dict[str, Any]:
        with self._lock:
            try:
                data = self._load_stats_raw_unlocked()
                self._record_success_unlocked("stats_read")
                return deepcopy(data)
            except UnsupportedStatsSchemaError:
                return _empty_stats()
            except Exception as exc:
                self._record_error_unlocked("load_stats", exc)
                return _empty_stats()

    def load_intent_stats(self) -> dict[str, dict[str, int]]:
        return self.load_stats().get("intents", {})

    def load_rate_limit_stats(self) -> dict[str, int]:
        return self.load_stats().get("rate_limits", {})

    def load_nlu_stats(self) -> dict[str, dict[str, int]]:
        return self.load_stats().get("nlu", {})

    def load_reminder_runtime(self) -> dict[str, object]:
        return self.load_stats().get("reminder_runtime", {})

    def _load_stats_raw_unlocked(self) -> dict[str, Any]:
        if not self._stats_file.exists():
            return _empty_stats()
        with self._stats_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or data.get("version") not in {2, 3}:
            self._record_error_unlocked(
                "unsupported_stats_schema",
                UnsupportedStatsSchemaError("unsupported_stats_schema"),
            )
            raise UnsupportedStatsSchemaError("unsupported_stats_schema")
        version = data.get("version")
        raw_intents = data.get("intents")
        raw_rates = data.get("rate_limits")
        raw_nlu = data.get("nlu") if version == STATS_SCHEMA_VERSION else {}
        raw_runtime = (
            data.get("reminder_runtime")
            if version == STATS_SCHEMA_VERSION
            else {}
        )
        runtime = (
            sanitize_reminder_runtime(raw_runtime)
            if isinstance(raw_runtime, Mapping) and raw_runtime
            else {}
        )
        # Reconstruct instead of mutating the decoded object: unknown root
        # fields and malformed timestamps must never reach readback or a later
        # unrelated rewrite.
        return {
            "version": STATS_SCHEMA_VERSION,
            "intents": sanitize_intent_stats(
                raw_intents if isinstance(raw_intents, Mapping) else {}
            ),
            "rate_limits": sanitize_rate_limit_stats(
                raw_rates if isinstance(raw_rates, Mapping) else {}
            ),
            "nlu": sanitize_nlu_stats(
                raw_nlu if isinstance(raw_nlu, Mapping) else {}
            ),
            "reminder_runtime": runtime,
            "last_saved": _iso_or_none(data.get("last_saved")),
        }

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

    def health(self) -> dict[str, Any]:
        """Return non-secret diagnostics for console persistence."""
        self._stats_read_error()
        self._logs_read_error()
        with self._lock:
            error_code, error_at = self._selected_health_error_unlocked()
            return {
                "status": "degraded" if self._health_errors else "ok",
                "stats_schema_version": STATS_SCHEMA_VERSION,
                "last_stats_saved_at": self._last_stats_saved_at,
                "last_log_write_at": self._last_log_write_at,
                "error_code": error_code,
                "last_error_at": error_at,
            }

    def _stats_read_error(self) -> str | None:
        with self._lock:
            if not self._stats_file.exists():
                self._last_stats_saved_at = None
                self._record_success_unlocked("stats_read")
                return None
            try:
                persisted = self._load_stats_raw_unlocked()
                # A new process has no in-memory write timestamp yet. Project
                # only the canonical timestamp reconstructed from the durable
                # schema; malformed or raw-shaped values become ``None``.
                self._last_stats_saved_at = persisted["last_saved"]
                self._record_success_unlocked("stats_read")
                return None
            except UnsupportedStatsSchemaError:
                return "unsupported_stats_schema"
            except Exception as exc:
                self._record_error_unlocked("read_error", exc)
                return "read_error"

    def _logs_read_error(self) -> str | None:
        with self._lock:
            if not self._logs_file.exists():
                self._record_success_unlocked("logs_read")
                return None
            try:
                raw_lines = self._tail_log_records_unlocked(
                    max_records=MAX_LOG_READ_RECORDS,
                    max_bytes=MAX_LOG_FILE_BYTES,
                )
                for raw in raw_lines:
                    record = json.loads(raw)
                    if not isinstance(record, dict) or not isinstance(
                        record.get("line"), str
                    ):
                        raise ValueError("invalid_log_record")
                self._record_success_unlocked("logs_read")
                return None
            except Exception as exc:
                self._record_error_unlocked("load_logs", exc)
                return "load_logs"

    def _selected_health_error_unlocked(self) -> tuple[str | None, str | None]:
        if not self._health_errors:
            return None, None
        code, at = max(
            self._health_errors.items(),
            key=lambda item: (item[1], item[0]),
        )
        return code, at

    def _record_success_unlocked(self, operation: str) -> None:
        now = datetime.now().isoformat()
        if operation == "stats_read":
            for code in ("load_stats", "read_error", "unsupported_stats_schema"):
                self._health_errors.pop(code, None)
        elif operation == "stats_write":
            for code in (
                "load_stats",
                "save_stats",
                "read_error",
                "unsupported_stats_schema",
            ):
                self._health_errors.pop(code, None)
            self._last_stats_saved_at = now
        elif operation == "logs_write":
            self._health_errors.pop("append_logs", None)
            self._last_log_write_at = now
        elif operation == "logs_read":
            self._health_errors.pop("load_logs", None)

    def _record_error_unlocked(self, operation: str, exc: Exception) -> None:
        del exc
        code = operation if operation in STORE_ERROR_CODES else "other"
        self._health_errors[code] = datetime.now().isoformat()

    def _record_success(self, operation: str) -> None:
        with self._lock:
            aliases = {"stats": "stats_write", "logs": "logs_write"}
            self._record_success_unlocked(aliases.get(operation, operation))

    def _record_error(self, operation: str, exc: Exception) -> None:
        with self._lock:
            self._record_error_unlocked(operation, exc)


_store: ConsoleStore | None = None


def get_console_store() -> ConsoleStore:
    global _store
    if _store is None:
        _store = ConsoleStore()
    return _store
