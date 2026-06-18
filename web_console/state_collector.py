"""State collection helpers for the web console."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportAttributeAccessIssue=false, reportUnannotatedClassAttribute=false, reportUnusedParameter=false

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.json_storage import hermes_discord_data_path

_JSON_READ_ERRORS: dict[str, str] = {}


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
    if monitor is None or not hasattr(monitor, "get_task_health"):
        return {"status": "unknown", "items": {}}
    try:
        items = monitor.get_task_health()
        degraded_states = {"cancelled", "degraded", "failed"}
        status = "degraded" if any(
            str(task.get("state", "")).lower() in degraded_states
            for task in items.values()
            if isinstance(task, dict)
        ) else "ok"
        return {"status": status, "items": items}
    except Exception as exc:
        return {"status": "degraded", "items": {}, "last_error": str(exc)}


def _collect_persistence_health() -> dict[str, Any]:
    read_errors = _probe_json_files()
    try:
        from web_console.console_store import get_console_store

        store = get_console_store()
        if hasattr(store, "health"):
            health = dict(store.health())
            if read_errors:
                health["status"] = "degraded"
                health["read_errors"] = read_errors
            return health
    except Exception as exc:
        return {"status": "degraded", "last_error": str(exc)}
    return {"status": "degraded", "read_errors": read_errors} if read_errors else {"status": "unknown"}


def _collect_calendar_sync_health(monitor: object | None = None) -> dict[str, Any]:
    calendar = getattr(monitor, "calendar", None)
    if calendar is None:
        return {"status": "unknown", "gcal_enabled": False}

    last_error = getattr(calendar, "last_gcal_sync_error", None)
    gcal_enabled = bool(getattr(calendar, "gcal_enabled", False))
    return {
        "status": "degraded" if last_error else ("ok" if gcal_enabled else "disabled"),
        "gcal_enabled": gcal_enabled,
        "last_error": last_error,
    }


def collect_bot_status(monitor: object | None = None) -> dict[str, Any]:
    if monitor is None:
        return {"status": "starting", "monitor_ready": False}

    try:
        client = getattr(monitor, "client", None) or getattr(monitor, "bot", None)
        if client is None:
            return {"status": "degraded", "monitor_ready": False}

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
                session_uptime = max(0, int((datetime.now() - start_time).total_seconds()))
                from web_console.console_store import get_console_store
                store = get_console_store()
                first_start = store.first_start_time()
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
        persistence = _collect_persistence_health()
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

        return {
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
    except Exception:
        return {"status": "degraded", "monitor_ready": False}


async def collect_console_health(monitor: object | None = None, *, port: int | None = None) -> dict[str, Any]:
    bot = collect_bot_status(monitor)
    bridge = await collect_bridge_health(monitor)
    persistence = bot.get("persistence") or _collect_persistence_health()
    tasks = bot.get("tasks") or _collect_task_health(monitor)
    ai_provider = _configured_ai_provider(monitor)
    bridge_required = ai_provider == "lm_studio"
    bridge_degraded = bridge.get("status") in {"error", "unavailable", "unhealthy", "degraded"} or bridge.get("lm_studio") == "disconnected"

    if bot.get("status") == "starting":
        status = "starting"
    elif (
        bot.get("status") == "degraded"
        or persistence.get("status") == "degraded"
        or tasks.get("status") == "degraded"
        or (bridge_required and bridge_degraded)
    ):
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "console": {"status": "running", "port": port},
        "ai_provider": ai_provider,
        "bot": bot,
        "bridge": bridge,
        "persistence": persistence,
        "tasks": tasks,
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


def collect_rate_limits(monitor: object | None = None) -> dict[str, Any]:
    from web_console.console_store import get_console_store

    store = get_console_store()
    persisted = store.load_rate_limit_stats()

    if monitor is None:
        return {
            "user_stats": _anonymize_user_ids({u: {"requests": c} for u, c in persisted.items()}),
            "summary": {"total_requests": sum(persisted.values())},
        }

    try:
        rate_limiter = getattr(monitor, "rate_limiter", None)
        if rate_limiter is None:
            return {
                "user_stats": _anonymize_user_ids({u: {"requests": c} for u, c in persisted.items()}),
                "summary": {"total_requests": sum(persisted.values())},
            }

        overall_stats = rate_limiter.get_stats() if hasattr(rate_limiter, "get_stats") else {}
        user_stats: dict[str, dict[str, int]] = {}

        for attr in ("user_stats", "per_user_stats", "stats_by_user", "user_counters", "user_limits"):
            candidate = getattr(rate_limiter, attr, None)
            if isinstance(candidate, dict):
                user_stats = _sanitize_user_stats(candidate)
                break

        if not user_stats and isinstance(overall_stats, dict):
            for key in ("user_stats", "per_user", "users"):
                candidate = overall_stats.get(key)
                if isinstance(candidate, dict):
                    user_stats = _sanitize_user_stats(candidate)
                    break

        merged: dict[str, int] = {}
        for user, stats in user_stats.items():
            count = stats.get("requests", 0) if isinstance(stats, dict) else int(stats)
            merged[user] = merged.get(user, 0) + count
        for user, count in persisted.items():
            merged[user] = merged.get(user, 0) + count

        return {
            "user_stats": _anonymize_user_ids({u: {"requests": c} for u, c in merged.items()}),
            "summary": overall_stats if isinstance(overall_stats, dict) else {},
        }
    except Exception:
        return {"user_stats": {}}


def collect_intent_stats(monitor: object | None = None) -> dict[str, Any]:
    from web_console.console_store import get_console_store

    store = get_console_store()
    persisted = store.load_intent_stats()

    if monitor is None:
        intent_counts = {k: v.get("count", 0) for k, v in persisted.items()}
        fallback_count = sum(v.get("low_confidence", 0) for v in persisted.values())
        return {"intent_counts": intent_counts, "fallback_count": fallback_count}

    try:
        raw_stats = {}
        get_unsaved_intent_stats = getattr(monitor, "get_unsaved_intent_stats", None)
        get_intent_stats = getattr(monitor, "get_intent_stats", None)
        if callable(get_unsaved_intent_stats):
            raw_stats = get_unsaved_intent_stats()
        elif callable(get_intent_stats):
            raw_stats = get_intent_stats()
        else:
            raw_stats = getattr(monitor, "intent_stats", {})

        intent_counts: dict[str, int] = {}
        fallback_count = 0

        for intent_name, stats in persisted.items():
            intent_counts[str(intent_name)] = int(stats.get("count", 0))
            fallback_count += int(stats.get("low_confidence", 0))

        if isinstance(raw_stats, dict):
            for intent_name, stats in raw_stats.items():
                if not isinstance(stats, dict):
                    continue
                count = int(stats.get("count", 0) or 0)
                intent_counts[str(intent_name)] = intent_counts.get(str(intent_name), 0) + count
                fallback_count += int(stats.get("low_confidence", 0) or 0)

        return {"intent_counts": intent_counts, "fallback_count": fallback_count}
    except Exception:
        return {"intent_counts": {}, "fallback_count": 0}


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


def collect_logs(count: int = 200) -> dict[str, Any]:
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
    def __init__(self, monitor: object | None = None):
        self.monitor = monitor

    async def collect_all(self) -> dict[str, Any]:
        return {
            "status": collect_bot_status(self.monitor),
            "bridge": await collect_bridge_health(self.monitor),
            "calendar": collect_calendar_data(self.monitor),
            "polls": collect_poll_data(self.monitor),
            "rate_limits": collect_rate_limits(self.monitor),
            "intents": collect_intent_stats(self.monitor),
            "memory": collect_memory_stats(self.monitor),
            "logs": collect_logs(),
        }
