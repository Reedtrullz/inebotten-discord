"""State collection helpers for the web console."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportAttributeAccessIssue=false, reportUnannotatedClassAttribute=false, reportUnusedParameter=false

import asyncio
import json
import math
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.nlu_metrics import NLUMetrics
from utils.json_storage import hermes_discord_data_path
from web_console.console_store import (
    INTENT_STAT_NAMES,
    STORE_ERROR_CODES,
    STATS_SCHEMA_VERSION,
    ConsoleStore,
    get_console_store,
    sanitize_reminder_runtime,
)

_JSON_READ_ERRORS: dict[str, str] = {}
_TASK_STATES = frozenset(
    {"running", "completed", "cancelled", "degraded", "failed", "other"}
)
DEGRADED_REASON_CODES = frozenset(
    {
        "discord_user_missing",
        "discord_not_ready",
        "discord_closed",
        "tasks_degraded",
        "persistence_degraded",
        "calendar_sync_degraded",
    }
)
BOT_STATUS_VALUES = frozenset({"starting", "online", "degraded", "unknown"})
COMPONENT_STATUS_VALUES = frozenset(
    {
        "starting",
        "ok",
        "healthy",
        "degraded",
        "disabled",
        "stopped",
        "unknown",
        "error",
        "unavailable",
        "unhealthy",
    }
)
CONNECTION_STATUS_VALUES = frozenset({"connected", "disconnected", "unknown"})
AI_PROVIDER_VALUES = frozenset({"lm_studio", "openrouter", "unknown"})
PUBLIC_REMINDER_KEYS = ("status", "running", "stale", "last_success_at")


def _bounded_value(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _nonnegative_number_or_none(value: object) -> int | float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return value


def _iso_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            _JSON_READ_ERRORS.pop(str(path), None)
            return default
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        _JSON_READ_ERRORS.pop(str(path), None)
        return data
    except Exception as exc:
        _JSON_READ_ERRORS[str(path)] = str(exc)
        return default


def _probe_json_files() -> dict[str, str]:
    errors = dict(_JSON_READ_ERRORS)
    for name in (
        "calendar.json",
        "reminders.json",
        "birthdays.json",
        "polls.json",
        "watchlist.json",
        "quotes.json",
        "user_memory.json",
        "events.json",
        "reminder_log.json",
    ):
        path = hermes_discord_data_path(name)
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
            errors.pop(str(path), None)
            _JSON_READ_ERRORS.pop(str(path), None)
        except Exception as exc:
            errors[str(path)] = str(exc)
            _JSON_READ_ERRORS[str(path)] = str(exc)
    return errors


def _configured_ai_provider(monitor: object | None = None) -> str:
    try:
        config = getattr(getattr(monitor, "client", None), "config", None)
        provider = getattr(config, "AI_PROVIDER", None)
        if provider:
            return str(provider).strip().lower()
    except Exception:
        pass
    return os.getenv("AI_PROVIDER", "lm_studio").strip().lower()


def _bridge_endpoint() -> tuple[str, int]:
    host = os.getenv("HERMES_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    connect_host = os.getenv("HERMES_BRIDGE_HEALTH_HOST", "").strip()
    if not connect_host:
        connect_host = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    port = int(os.getenv("HERMES_BRIDGE_PORT", "3000"))
    return connect_host, port


def _flatten_calendar_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items: list[dict[str, Any]] = []
        for value in data.values():
            if isinstance(value, list):
                items.extend(item for item in value if isinstance(item, dict))
        return items
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.strip())
    except Exception:
        return None


def _sanitize_user_stats(stats: Any) -> dict[str, dict[str, int]]:
    if not isinstance(stats, dict):
        return {}

    cleaned: dict[str, dict[str, int]] = {}
    for user_id, raw in stats.items():
        if not isinstance(raw, dict):
            continue
        cleaned[str(user_id)] = {
            key: int(value)
            for key, value in raw.items()
            if isinstance(value, (int, float))
        }
    return cleaned


def _anonymize_user_ids(user_stats: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    sorted_keys = sorted(user_stats.keys(), key=lambda k: str(k))
    return {f"user_{i+1}": user_stats[k] for i, k in enumerate(sorted_keys)}


def _collect_task_health(monitor: object | None = None) -> dict[str, Any]:
    counts = {state: 0 for state in sorted(_TASK_STATES)}
    if monitor is None:
        return {"status": "unknown", "counts": counts}
    try:
        get_task_health = getattr(monitor, "get_task_health", None)
        if not callable(get_task_health):
            return {"status": "unknown", "counts": counts}
        items = get_task_health()
        if not isinstance(items, Mapping):
            return {"status": "degraded", "counts": counts}
        degraded_states = {"cancelled", "degraded", "failed"}
        degraded = False
        for task in items.values():
            state = task.get("state") if isinstance(task, Mapping) else None
            key = state if isinstance(state, str) and state in _TASK_STATES else "other"
            counts[key] += 1
            degraded = degraded or key in degraded_states
        return {"status": "degraded" if degraded else "ok", "counts": counts}
    except Exception:
        return {"status": "degraded", "counts": counts}


def _bot_projection(raw: Mapping[str, object]) -> dict[str, object]:
    reasons = raw.get("degraded_reasons")
    reason_values = reasons if isinstance(reasons, list) else []
    return {
        "status": _bounded_value(raw.get("status"), BOT_STATUS_VALUES),
        "monitor_ready": raw.get("monitor_ready") is True,
        "discord_connected": raw.get("discord_connected") is True,
        "discord_ready": raw.get("discord_ready") is True,
        "discord_closed": raw.get("discord_closed") is True,
        "uptime_seconds": _nonnegative_int(raw.get("uptime_seconds")),
        "guilds": _nonnegative_int(raw.get("guilds")),
        "users": _nonnegative_int(raw.get("users")),
        "latency": _nonnegative_number_or_none(raw.get("latency")),
        "degraded_reasons": sorted(
            {
                value
                for value in reason_values
                if isinstance(value, str) and value in DEGRADED_REASON_CODES
            }
        ),
    }


def _task_projection(raw: Mapping[str, object]) -> dict[str, object]:
    raw_counts = raw.get("counts")
    counts = {
        state: _nonnegative_int(
            raw_counts.get(state) if isinstance(raw_counts, Mapping) else 0
        )
        for state in sorted(_TASK_STATES)
    }
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "counts": counts,
    }


def _persistence_projection(raw: Mapping[str, object]) -> dict[str, object]:
    error = raw.get("error_code")
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "stats_schema_version": STATS_SCHEMA_VERSION,
        "last_stats_saved_at": _iso_or_none(raw.get("last_stats_saved_at")),
        "last_log_write_at": _iso_or_none(raw.get("last_log_write_at")),
        "error_code": (
            error if isinstance(error, str) and error in STORE_ERROR_CODES else None
        ),
        "last_error_at": _iso_or_none(raw.get("last_error_at")),
    }


def _calendar_projection(raw: Mapping[str, object]) -> dict[str, object]:
    has_error = raw.get("last_error") is not None or raw.get("error_code") is not None
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "gcal_enabled": raw.get("gcal_enabled") is True,
        "error_code": "sync_failed" if has_error else None,
    }


def _bridge_projection(raw: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": _bounded_value(raw.get("status"), COMPONENT_STATUS_VALUES),
        "lm_studio": _bounded_value(
            raw.get("lm_studio"), CONNECTION_STATUS_VALUES
        ),
        "requests": _nonnegative_int(raw.get("requests")),
        "errors": _nonnegative_int(raw.get("errors")),
    }


def _collect_public_reminder_runtime(
    monitor: object | None = None,
) -> dict[str, object] | None:
    safe_degraded: dict[str, object] = {
        "status": "degraded",
        "running": False,
        "stale": True,
        "last_success_at": None,
    }
    if monitor is None:
        return None

    try:
        checker = getattr(monitor, "reminder_checker", None)
        if checker is None:
            return None
        get_health = getattr(checker, "get_health", None)
        if not callable(get_health):
            return None
        health = get_health()
        if not isinstance(health, Mapping):
            return safe_degraded

        status = health.get("status")
        running = health.get("running")
        stale = health.get("stale")
        last_success_at = health.get("last_success_at")
        if (
            not isinstance(status, str)
            or status not in {"starting", "ok", "degraded", "stopped"}
            or type(running) is not bool
            or type(stale) is not bool
        ):
            return safe_degraded

        if last_success_at is not None:
            if not isinstance(last_success_at, str) or len(last_success_at) > 64:
                return safe_degraded
            parsed_success = datetime.fromisoformat(last_success_at)
            if parsed_success.tzinfo is None or parsed_success.utcoffset() is None:
                return safe_degraded

        return {
            "status": status,
            "running": running,
            "stale": stale,
            "last_success_at": last_success_at,
        }
    except Exception:
        return safe_degraded


def _collect_persistence_health(
    store: ConsoleStore | None = None,
) -> dict[str, object]:
    read_errors = _probe_json_files()
    try:
        active_store = store if store is not None else get_console_store()
        health = active_store.health()
        bounded = _persistence_projection(
            health if isinstance(health, Mapping) else {}
        )
        if read_errors:
            bounded["status"] = "degraded"
            bounded["error_code"] = "read_error"
        return bounded
    except Exception:
        return _persistence_projection(
            {"status": "degraded", "error_code": "read_error"}
        )


def _collect_calendar_sync_health(monitor: object | None = None) -> dict[str, Any]:
    calendar = getattr(monitor, "calendar", None)
    if calendar is None:
        return _calendar_projection(
            {"status": "unknown", "gcal_enabled": False}
        )

    last_error = getattr(calendar, "last_gcal_sync_error", None)
    gcal_enabled = bool(getattr(calendar, "gcal_enabled", False))
    return _calendar_projection(
        {
            "status": (
                "degraded" if last_error else ("ok" if gcal_enabled else "disabled")
            ),
            "gcal_enabled": gcal_enabled,
            "last_error": last_error,
        }
    )


def collect_bot_status(
    monitor: object | None = None,
    *,
    store: ConsoleStore | None = None,
) -> dict[str, Any]:
    reminder_runtime = _collect_public_reminder_runtime(monitor)
    if monitor is None:
        return {"status": "starting", "monitor_ready": False}

    try:
        client = getattr(monitor, "client", None) or getattr(monitor, "bot", None)
        if client is None:
            result: dict[str, Any] = {
                "status": "degraded",
                "monitor_ready": False,
            }
            if reminder_runtime is not None:
                result["reminder_runtime"] = reminder_runtime
            return result

        user = getattr(client, "user", None)
        guilds = list(getattr(client, "guilds", []) or [])
        start_time = getattr(client, "start_time", None)
        is_ready_fn = getattr(client, "is_ready", None)
        is_closed_fn = getattr(client, "is_closed", None)
        is_ready = bool(is_ready_fn()) if callable(is_ready_fn) else user is not None
        is_closed = bool(is_closed_fn()) if callable(is_closed_fn) else False
        latency = getattr(client, "latency", None)

        uptime_seconds = 0
        if start_time:
            try:
                active_store = store if store is not None else get_console_store()
                first_start = active_store.first_start_time()
                total_uptime = max(0, int((datetime.now() - first_start).total_seconds()))
                uptime_seconds = total_uptime
            except Exception:
                uptime_seconds = 0

        users = 0
        for guild in guilds:
            member_count = getattr(guild, "member_count", None)
            if isinstance(member_count, int) and member_count > 0:
                users += member_count
                continue
            members = getattr(guild, "members", None)
            if members:
                try:
                    users += len(members)
                except Exception:
                    pass

        if users <= 0 and user is not None:
            users = 1

        tasks = _collect_task_health(monitor)
        persistence = (
            _collect_persistence_health(store)
            if store is not None
            else _collect_persistence_health()
        )
        calendar_sync = _collect_calendar_sync_health(monitor)
        discord_connected = bool(user is not None and is_ready and not is_closed)
        degraded_reasons = []
        if user is None:
            degraded_reasons.append("discord_user_missing")
        if not is_ready:
            degraded_reasons.append("discord_not_ready")
        if is_closed:
            degraded_reasons.append("discord_closed")

        status = "online" if discord_connected else "degraded"
        if (
            tasks.get("status") == "degraded"
            or persistence.get("status") == "degraded"
            or calendar_sync.get("status") == "degraded"
        ):
            status = "degraded"
            if tasks.get("status") == "degraded":
                degraded_reasons.append("tasks_degraded")
            if persistence.get("status") == "degraded":
                degraded_reasons.append("persistence_degraded")
            if calendar_sync.get("status") == "degraded":
                degraded_reasons.append("calendar_sync_degraded")

        result = {
            "status": status,
            "uptime_seconds": uptime_seconds,
            "guilds": len(guilds),
            "users": users,
            "discord_connected": discord_connected,
            "discord_ready": is_ready,
            "discord_closed": is_closed,
            "latency": latency,
            "degraded_reasons": degraded_reasons,
            "monitor_ready": True,
            "tasks": tasks,
            "persistence": persistence,
            "calendar_sync": calendar_sync,
        }
        if reminder_runtime is not None:
            result["reminder_runtime"] = reminder_runtime
        return result
    except Exception:
        result = {"status": "degraded", "monitor_ready": False}
        if reminder_runtime is not None:
            result["reminder_runtime"] = reminder_runtime
        return result


def collect_nlu_stats(
    monitor: object | None,
    *,
    store: ConsoleStore,
) -> dict[str, dict[str, int]]:
    metrics = getattr(monitor, "nlu_metrics", None)
    try:
        raw = (
            metrics.snapshot()
            if isinstance(metrics, NLUMetrics)
            else store.load_nlu_stats()
        )
    except Exception:
        raw = {}
    sanitized = NLUMetrics()
    sanitized.merge_snapshot(raw if isinstance(raw, Mapping) else {})
    return sanitized.snapshot()


def collect_reminder_runtime(
    monitor: object | None,
    *,
    store: ConsoleStore,
    public: bool = False,
    reference: datetime | None = None,
) -> dict[str, object]:
    try:
        checker = getattr(monitor, "reminder_checker", None)
        get_health = getattr(checker, "get_health", None)
        live = callable(get_health)
        raw = get_health() if live else store.load_reminder_runtime()
    except Exception:
        live = False
        raw = {
            "status": "degraded",
            "running": False,
            "stale": True,
            "last_error_code": "cycle_error",
        }
    full = sanitize_reminder_runtime(raw if isinstance(raw, Mapping) else {})
    if not live:
        now = reference or datetime.now().astimezone()
        last_success = full["last_success_at"]
        try:
            parsed_success = (
                datetime.fromisoformat(last_success.replace("Z", "+00:00"))
                if isinstance(last_success, str)
                else None
            )
        except ValueError:
            parsed_success = None
        full["running"] = False
        full["stale"] = (
            parsed_success is None
            or (
                now.astimezone(timezone.utc)
                - parsed_success.astimezone(timezone.utc)
            )
            > timedelta(seconds=150)
        )
        full["status"] = "starting" if monitor is None else "degraded"
    if not public:
        return full
    return {key: full[key] for key in PUBLIC_REMINDER_KEYS}


def collect_authenticated_status(
    monitor: object | None,
    *,
    store: ConsoleStore,
) -> dict[str, object]:
    raw_bot = collect_bot_status(monitor, store=store)
    bot = _bot_projection(raw_bot)
    return {
        "status": bot["status"],
        "bot": bot,
        "tasks": _task_projection(_collect_task_health(monitor)),
        "persistence": _collect_persistence_health(store),
        "calendar_sync": _collect_calendar_sync_health(monitor),
        "nlu": collect_nlu_stats(monitor, store=store),
        "reminder_runtime": collect_reminder_runtime(
            monitor,
            store=store,
            public=False,
        ),
    }


async def collect_console_health(
    monitor: object | None = None,
    *,
    port: int | None = None,
    store: ConsoleStore | None = None,
) -> dict[str, Any]:
    active_store = store if store is not None else get_console_store()
    raw_bot = collect_bot_status(monitor, store=active_store)
    bot = _bot_projection(raw_bot)
    tasks = _task_projection(_collect_task_health(monitor))
    persistence = (
        _collect_persistence_health(active_store)
        if store is not None
        else _collect_persistence_health()
    )
    calendar_sync = _collect_calendar_sync_health(monitor)
    bridge = _bridge_projection(await collect_bridge_health(monitor))
    reminder_runtime = collect_reminder_runtime(
        monitor,
        store=active_store,
        public=True,
    )
    provider = _configured_ai_provider(monitor)
    starting = bot["status"] == "starting" or reminder_runtime["status"] == "starting"
    degraded = any(
        value["status"] in {"degraded", "error", "unavailable", "unhealthy"}
        for value in (bot, tasks, persistence, calendar_sync)
    )
    if (
        reminder_runtime["status"] in {"degraded", "stopped"}
        or reminder_runtime["stale"] is True
        or reminder_runtime["running"] is False
    ):
        degraded = True
    if provider == "lm_studio" and bridge["status"] in {
        "degraded",
        "error",
        "unavailable",
        "unhealthy",
    }:
        degraded = True
    return {
        "status": "starting" if starting else ("degraded" if degraded else "healthy"),
        "timestamp": datetime.now().isoformat(),
        "console": {
            "status": "running",
            "port": port if isinstance(port, int) and 0 <= port <= 65535 else None,
        },
        "ai_provider": provider if provider in AI_PROVIDER_VALUES else "unknown",
        "bot": bot,
        "bridge": bridge,
        "persistence": persistence,
        "tasks": tasks,
        "calendar_sync": calendar_sync,
        "reminder_runtime": reminder_runtime,
    }


async def collect_bridge_health(monitor: object | None = None) -> dict[str, Any]:
    host, port = _bridge_endpoint()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=2.5,
        )
        request = b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        writer.write(request)
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=2.5)
        writer.close()
        await writer.wait_closed()

        header_end = response.find(b"\r\n\r\n")
        if header_end > 0:
            body = response[header_end + 4 :]
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                lm_studio = payload.get("lm_studio", "unknown")
                status = payload.get("status", "unknown")
                if lm_studio == "disconnected" and status == "healthy":
                    status = "degraded"
                return {
                    "status": status,
                    "lm_studio": lm_studio,
                    "host": host,
                    "port": port,
                    "requests": payload.get("requests", 0),
                    "errors": payload.get("errors", 0),
                }
    except Exception:
        pass

    return {"status": "unavailable", "host": host, "port": port}


def collect_calendar_data(monitor: object | None = None) -> dict[str, Any]:
    path = hermes_discord_data_path("calendar.json")
    data = _read_json_file(path, {})
    items = _flatten_calendar_items(data)

    now = datetime.now()
    upcoming = []
    event_count = 0
    task_count = 0

    for item in items:
        if item.get("completed") or item.get("delete_pending"):
            continue

        event_count += 1

        title = str(item.get("title", "")).strip()
        item_type = str(item.get("type", "")).strip().lower()
        if item_type == "task" or (
            not item.get("time")
            and not item.get("recurrence")
            and not item.get("gcal_event_id")
            and not item.get("gcal_link")
        ):
            task_count += 1

        item_date = _parse_date(item.get("date"))
        if item_date is None or item_date.date() < now.date():
            continue

        upcoming.append(
            {
                "title": title,
                "date": item.get("date"),
                "time": item.get("time"),
                "recurrence": item.get("recurrence"),
            }
        )

    upcoming.sort(key=lambda value: _parse_date(value.get("date")) or datetime.max)

    return {
        "event_count": event_count,
        "upcoming_events": upcoming[:5],
        "task_count": task_count,
    }


def collect_poll_data(monitor: object | None = None) -> dict[str, Any]:
    path = hermes_discord_data_path("polls.json")
    data = _read_json_file(path, {})

    active_polls: list[dict[str, Any]] = []
    total_active = 0

    if isinstance(data, dict):
        for guild_polls in data.values():
            if not isinstance(guild_polls, dict):
                continue
            for poll in guild_polls.values():
                if not isinstance(poll, dict):
                    continue
                if poll.get("status") != "active":
                    continue

                options = poll.get("options", [])
                vote_count = 0
                if isinstance(options, list):
                    for option in options:
                        if isinstance(option, dict):
                            votes = option.get("votes", [])
                            if isinstance(votes, list):
                                vote_count += len(votes)

                active_polls.append(
                    {
                        "title": poll.get("question", ""),
                        "vote_count": vote_count,
                    }
                )
                total_active += 1

    return {"active_polls": total_active, "polls": active_polls}


def _flat_rate_counts(raw: object) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, int] = {}
    for raw_user, raw_value in raw.items():
        user = str(raw_user)
        if len(user) > 32 or not user.isascii() or not user.isdecimal():
            continue
        value = (
            raw_value.get("requests", 0)
            if isinstance(raw_value, Mapping)
            else raw_value
        )
        count = _nonnegative_int(value)
        if count:
            result[user] = count
    return result


def collect_rate_limits(
    monitor: object | None = None,
    *,
    store: ConsoleStore | None = None,
) -> dict[str, Any]:
    active_store = store if store is not None else get_console_store()
    persisted = _flat_rate_counts(active_store.load_rate_limit_stats())

    def render(counts: Mapping[str, int]) -> dict[str, Any]:
        return {
            "user_stats": _anonymize_user_ids(
                {user: {"requests": count} for user, count in counts.items()}
            ),
            "summary": {"total_requests": sum(counts.values())},
        }

    if monitor is None:
        return render(persisted)

    try:
        get_unsaved = getattr(monitor, "get_unsaved_rate_stats", None)
        if callable(get_unsaved):
            unsaved = _flat_rate_counts(get_unsaved())
            merged = dict(persisted)
            for user, count in unsaved.items():
                merged[user] = merged.get(user, 0) + count
            return render(merged)

        rate_limiter = getattr(monitor, "rate_limiter", None)
        if rate_limiter is None:
            return render(persisted)

        overall_stats = rate_limiter.get_stats() if hasattr(rate_limiter, "get_stats") else {}
        live: dict[str, int] = {}

        for attr in ("user_stats", "per_user_stats", "stats_by_user", "user_counters", "user_limits"):
            candidate = getattr(rate_limiter, attr, None)
            if isinstance(candidate, Mapping):
                live = _flat_rate_counts(candidate)
                break

        if not live and isinstance(overall_stats, Mapping):
            for key in ("user_stats", "per_user", "users"):
                candidate = overall_stats.get(key)
                if isinstance(candidate, Mapping):
                    live = _flat_rate_counts(candidate)
                    break
        # Without an explicit unsaved-delta API, a live snapshot is already a
        # full current-process total. Prefer it over persisted data rather than
        # counting the flushed prefix twice.
        return render(live or persisted)
    except Exception:
        return render(persisted)


def collect_intent_stats(
    monitor: object | None = None,
    *,
    store: ConsoleStore | None = None,
) -> dict[str, Any]:
    active_store = store if store is not None else get_console_store()
    persisted = active_store.load_intent_stats()

    if monitor is None:
        intent_counts = {
            str(name): _nonnegative_int(stats.get("count", 0))
            for name, stats in persisted.items()
            if name in INTENT_STAT_NAMES and isinstance(stats, Mapping)
        }
        fallback_count = sum(
            _nonnegative_int(stats.get("low_confidence", 0))
            for name, stats in persisted.items()
            if name in INTENT_STAT_NAMES and isinstance(stats, Mapping)
        )
        return {"intent_counts": intent_counts, "fallback_count": fallback_count}

    try:
        raw_stats = {}
        is_delta = False
        get_unsaved_intent_stats = getattr(monitor, "get_unsaved_intent_stats", None)
        get_intent_stats = getattr(monitor, "get_intent_stats", None)
        if callable(get_unsaved_intent_stats):
            raw_stats = get_unsaved_intent_stats()
            is_delta = True
        elif callable(get_intent_stats):
            raw_stats = get_intent_stats()
        else:
            raw_stats = getattr(monitor, "intent_stats", {})

        intent_counts: dict[str, int] = (
            {
                str(intent_name): _nonnegative_int(stats.get("count", 0))
                for intent_name, stats in persisted.items()
                if intent_name in INTENT_STAT_NAMES
                and isinstance(stats, Mapping)
            }
            if is_delta or not raw_stats
            else {}
        )
        fallback_count = (
            sum(
                _nonnegative_int(stats.get("low_confidence", 0))
                for name, stats in persisted.items()
                if name in INTENT_STAT_NAMES and isinstance(stats, Mapping)
            )
            if is_delta or not raw_stats
            else 0
        )

        if isinstance(raw_stats, Mapping):
            for intent_name, stats in raw_stats.items():
                if (
                    intent_name not in INTENT_STAT_NAMES
                    or not isinstance(stats, Mapping)
                ):
                    continue
                count = _nonnegative_int(stats.get("count", 0))
                intent_counts[intent_name] = intent_counts.get(intent_name, 0) + count
                fallback_count += _nonnegative_int(stats.get("low_confidence", 0))

        return {"intent_counts": intent_counts, "fallback_count": fallback_count}
    except Exception:
        return {
            "intent_counts": {
                str(name): _nonnegative_int(stats.get("count", 0))
                for name, stats in persisted.items()
                if name in INTENT_STAT_NAMES and isinstance(stats, Mapping)
            },
            "fallback_count": sum(
                _nonnegative_int(stats.get("low_confidence", 0))
                for name, stats in persisted.items()
                if name in INTENT_STAT_NAMES and isinstance(stats, Mapping)
            ),
        }


def collect_memory_stats(monitor: object | None = None) -> dict[str, int]:
    if monitor is None:
        return {"user_count": 0, "conversation_count": 0}

    try:
        user_memory = getattr(monitor, "user_memory", None)
        conversation = getattr(monitor, "conversation", None)

        user_count = 0
        if user_memory is not None:
            memory = getattr(user_memory, "memory", None)
            if isinstance(memory, dict):
                user_count = len(memory)

        conversation_count = 0
        if conversation is not None:
            threads = getattr(conversation, "threads", None)
            if isinstance(threads, dict):
                conversation_count = len(threads)

        return {"user_count": user_count, "conversation_count": conversation_count}
    except Exception:
        return {"user_count": 0, "conversation_count": 0}


def collect_logs(
    count: int = 200,
    *,
    store: ConsoleStore | None = None,
) -> dict[str, Any]:
    if store is not None:
        return {"logs": store.load_logs(count)}
    from utils.logger import get_log_buffer
    return {"logs": get_log_buffer().get_lines(count)}


def generate_mock_data() -> dict[str, Any]:
    """Generate realistic mock data for the demo dashboard."""
    return {
        "status": {
            "status": "online",
            "uptime_seconds": 86400 + 3600 * 4 + 120,
            "guilds": 3,
            "users": 42,
            "discord_connected": True,
            "monitor_ready": True,
        },
        "bridge": {
            "status": "healthy",
            "lm_studio": "connected",
            "requests": 1337,
            "errors": 3,
        },
        "calendar": {
            "event_count": 12,
            "upcoming_events": [
                {"title": "Møte med Ola", "date": "15.05.2025", "time": "14:00", "recurrence": None},
                {"title": "Lunsj med gjengen", "date": "16.05.2025", "time": "12:00", "recurrence": "hver uke"},
                {"title": "Tannlege", "date": "20.05.2025", "time": "09:00", "recurrence": None},
                {"title": "RBK - Bodø/Glimt", "date": "25.05.2025", "time": "18:00", "recurrence": None},
            ],
            "task_count": 2,
        },
        "polls": {
            "active_polls": 2,
            "polls": [
                {
                    "question": "Pizza eller burger?",
                    "votes": {"Pepperoni": 5, "Margherita": 3, "Kebab": 7},
                },
                {
                    "question": "Neste teambuilding?",
                    "votes": {"Bowling": 2, "Escape room": 4, "Grilling": 6},
                },
            ],
        },
        "rate_limits": {
            "summary": {"total_requests": 1337},
            "user_stats": {
                "user_1": 45,
                "user_2": 32,
                "user_3": 18,
                "user_4": 12,
                "user_5": 8,
            },
        },
        "intents": {
            "intent_counts": {
                "CALENDAR_ITEM": 45,
                "AI_CHAT": 120,
                "POLL_CREATE": 8,
                "STATUS": 12,
                "CALENDAR_LIST": 20,
            },
            "fallback_count": 5,
        },
        "memory": {
            "user_count": 15,
            "conversation_count": 32,
        },
        "logs": {
            "logs": [
                "08:00:00 [INFO] Bot started successfully",
                "08:00:01 [INFO] Connected to Discord (3 guilds)",
                "08:00:02 [INFO] Bridge server running on port 3000",
                "08:05:15 [INFO] Calendar sync completed (12 events)",
                "08:10:42 [INFO] AI response generated (120 tokens)",
                "08:15:00 [INFO] Daily digest sent to #general",
                "08:20:33 [WARN] Rate limit approaching for user_123",
                "08:30:00 [INFO] Reminder sent: Møte med Ola",
                "08:45:12 [INFO] Poll created: Pizza eller burger?",
                "09:00:00 [INFO] New quote added by user_456",
            ],
        },
    }


class StateCollector:
    def __init__(
        self,
        monitor: object | None = None,
        *,
        store: ConsoleStore | None = None,
    ):
        self.monitor = monitor
        self.store = store if store is not None else get_console_store()

    async def collect_all(self) -> dict[str, Any]:
        result = {
            "status": collect_bot_status(self.monitor, store=self.store),
            "bridge": await collect_bridge_health(self.monitor),
            "calendar": collect_calendar_data(self.monitor),
            "polls": collect_poll_data(self.monitor),
            "rate_limits": collect_rate_limits(self.monitor, store=self.store),
            "intents": collect_intent_stats(self.monitor, store=self.store),
            "memory": collect_memory_stats(self.monitor),
            "logs": collect_logs(store=self.store),
        }
        reminder_runtime = _collect_public_reminder_runtime(self.monitor)
        if reminder_runtime is not None:
            result["reminder_runtime"] = reminder_runtime
        return result
