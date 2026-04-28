"""State collection helpers for the web console."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportAttributeAccessIssue=false, reportUnannotatedClassAttribute=false, reportUnusedParameter=false

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


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

        uptime_seconds = 0
        if start_time:
            try:
                uptime_seconds = max(0, int((datetime.now() - start_time).total_seconds()))
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

        return {
            "status": "online" if user is not None else "degraded",
            "uptime_seconds": uptime_seconds,
            "guilds": len(guilds),
            "users": users,
            "discord_connected": user is not None,
            "monitor_ready": True,
        }
    except Exception:
        return {"status": "degraded", "monitor_ready": False}


async def collect_bridge_health(monitor: object | None = None) -> dict[str, Any]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 3000),
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
                return {
                    "status": payload.get("status", "unknown"),
                    "lm_studio": payload.get("lm_studio", "unknown"),
                    "requests": payload.get("requests", 0),
                    "errors": payload.get("errors", 0),
                }
    except Exception:
        pass

    return {"status": "unavailable"}


def collect_calendar_data(monitor: object | None = None) -> dict[str, Any]:
    path = Path.home() / ".hermes" / "discord" / "data" / "calendar.json"
    data = _read_json_file(path, {})
    items = _flatten_calendar_items(data)

    now = datetime.now()
    upcoming = []
    event_count = 0
    task_count = 0

    for item in items:
        if item.get("completed"):
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
    path = Path.home() / ".hermes" / "discord" / "polls.json"
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
    if monitor is None:
        return {"user_stats": {}}

    try:
        rate_limiter = getattr(monitor, "rate_limiter", None)
        if rate_limiter is None:
            return {"user_stats": {}}

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

        return {
            "user_stats": _anonymize_user_ids(user_stats),
            "summary": overall_stats if isinstance(overall_stats, dict) else {},
        }
    except Exception:
        return {"user_stats": {}}


def collect_intent_stats(monitor: object | None = None) -> dict[str, Any]:
    if monitor is None:
        return {"intent_counts": {}, "fallback_count": 0}

    try:
        raw_stats = {}
        get_intent_stats = getattr(monitor, "get_intent_stats", None)
        if callable(get_intent_stats):
            raw_stats = get_intent_stats()
        else:
            raw_stats = getattr(monitor, "intent_stats", {})

        intent_counts: dict[str, int] = {}
        fallback_count = 0

        if isinstance(raw_stats, dict):
            for intent_name, stats in raw_stats.items():
                if not isinstance(stats, dict):
                    continue
                count = int(stats.get("count", 0) or 0)
                intent_counts[str(intent_name)] = count
                fallback_count += int(stats.get("low_confidence", 0) or 0)

        fallback_count += intent_counts.get("ai_chat", 0)

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
        }
