"""State collection helpers for the web console."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportAttributeAccessIssue=false, reportUnannotatedClassAttribute=false, reportUnusedParameter=false

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.json_storage import hermes_discord_data_path
from cal_system.event_schema import Clock
from features.poll_manager import PollManager, validate_poll_document
from core.access_policy import AccessPolicy, policy_summary, invocation_description

from utils.storage_contract import load_document, bucket_records, user_records

_JSON_READ_ERRORS: dict[str, str] = {}
_DOCUMENT_VALIDATORS = {
    "polls.json": validate_poll_document,
    "calendar.json": bucket_records("title"),
    "reminders.json": bucket_records("text"),
    "user_memory.json": user_records,
}

READINESS_STATUSES = {"ready", "degraded", "unavailable", "stale", "disabled"}
PROVIDER_EVIDENCE_TTL = timedelta(minutes=15)
SCHEDULER_STALE_AFTER = timedelta(minutes=3)
CALENDAR_SYNC_STALE_AFTER_SECONDS = 30 * 60



def _read_json_file(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            _JSON_READ_ERRORS.pop(str(path), None)
            return default
        if path.name in _DOCUMENT_VALIDATORS:
            outcome = load_document(path, 1)
            if outcome.status not in ("valid", "missing"):
                raise ValueError(outcome.error_code)
            data = outcome.document or default
            if not _DOCUMENT_VALIDATORS[path.name](data):
                raise ValueError("invalid_shape")
        else:
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
            if name in _DOCUMENT_VALIDATORS:
                result = load_document(path, 1)
                if result.status not in ("valid", "missing"):
                    raise ValueError(result.error_code)
                if not _DOCUMENT_VALIDATORS[name](result.document or {}):
                    raise ValueError("invalid_shape")
            else:
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


def _provider_name(value: object) -> str:
    name = str(value or "").strip().lower()
    if name in {"hermes", "local", "lmstudio"}:
        return "lm_studio"
    return name


def _provider_config(monitor: object | None = None) -> object | None:
    return getattr(getattr(monitor, "client", None), "config", None)


def _provider_contracts(monitor: object | None = None) -> tuple[str, str | None]:
    config = _provider_config(monitor)
    configured_provider = (
        getattr(config, "AI_PROVIDER", None)
        if config is not None
        else os.getenv("AI_PROVIDER", "").strip()
    )
    primary = _provider_name(configured_provider or "unknown")
    fallback = _provider_name(getattr(config, "AI_FALLBACK_PROVIDER", None)) or None
    return primary, fallback


def _bridge_contract(monitor: object | None = None) -> tuple[bool, bool]:
    primary, fallback = _provider_contracts(monitor)
    enabled = primary == "lm_studio" or fallback == "lm_studio"
    if primary == "unknown" and any(os.getenv(key) for key in ("HERMES_BRIDGE_HOST", "HERMES_BRIDGE_PORT")):
        enabled = True  # Explicit endpoint diagnostics during partial startup; optional.
    return enabled, primary == "lm_studio"


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _health_component(
    *,
    enabled: bool,
    required: bool,
    status: str,
    checked_at: str,
    reason_code: str,
    recovery_action: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    if status not in READINESS_STATUSES:
        status = "unavailable"
    return {
        "enabled": bool(enabled),
        "required": bool(required),
        "status": status,
        "checked_at": checked_at,
        "reason_code": reason_code,
        "recovery_action": recovery_action if status not in {"ready", "disabled"} else None,
        **details,
    }


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
        raw_items = monitor.get_task_health()
        raw_items = raw_items if isinstance(raw_items, dict) else {}
        degraded_states = {"cancelled", "degraded", "failed"}
        status = "degraded" if any(
            str(task.get("state", "")).lower() in degraded_states
            for task in raw_items.values()
            if isinstance(task, dict)
        ) else "ok"
        items: dict[str, dict[str, Any]] = {}
        for name, task in raw_items.items():
            if not isinstance(task, dict):
                continue
            safe_name = str(name)[:64]
            safe = {
                key: task[key]
                for key in ("state", "started_at", "last_ok", "finished_at", "last_error_at")
                if isinstance(task.get(key), (str, int, float, bool))
            }
            if str(task.get("state", "")).lower() in degraded_states:
                safe["reason_code"] = "background_task_failed"
            items[safe_name] = safe
        return {"status": status, "items": items}
    except Exception:
        return {"status": "degraded", "items": {}, "reason_code": "task_health_unavailable"}


def _collect_persistence_health() -> dict[str, Any]:
    read_errors = _probe_json_files()
    try:
        from web_console.console_store import get_console_store

        store = get_console_store()
        if hasattr(store, "health"):
            health = dict(store.health())
            status = "degraded" if read_errors else str(health.get("status", "unknown"))
            safe = {
                key: health[key]
                for key in (
                    "stats_schema_version", "stats_storage_status", "sessions_storage_status",
                    "last_stats_saved_at", "last_log_write_at", "last_error_at",
                )
                if isinstance(health.get(key), (str, int, float, bool))
            }
            safe["status"] = status
            if status == "degraded":
                safe["reason_code"] = "storage_document_invalid" if read_errors else "store_read_or_write_failed"
            return safe
    except Exception:
        return {
            "status": "degraded",
            "reason_code": "store_health_unavailable",
        }
    return {
        "status": "degraded" if read_errors else "unknown",
        **({"reason_code": "storage_document_invalid"} if read_errors else {}),
    }


def _collect_calendar_sync_health(
    monitor: object | None = None, *, now: datetime | None = None
) -> dict[str, Any]:
    checked_at = _utc_now(now).isoformat()
    calendar = getattr(monitor, "calendar", None)
    config = _provider_config(monitor)
    configured = getattr(calendar, "gcal_enabled", None)
    if configured is None:
        configured = getattr(config, "GCAL_ENABLED", False)
    enabled = bool(configured)
    if not enabled:
        return _health_component(
            enabled=False,
            required=False,
            status="disabled",
            checked_at=checked_at,
            reason_code="google_calendar_disabled",
            gcal_enabled=False,
        )

    if getattr(calendar, "last_gcal_sync_error", None):
        return _health_component(
            enabled=True,
            required=True,
            status="degraded",
            checked_at=checked_at,
            reason_code="calendar_sync_failed",
            recovery_action="Kontroller Google-tilgangen og prøv synkronisering igjen. Lokale hendelser er bevart.",
            gcal_enabled=True,
        )

    client = getattr(monitor, "client", None)
    checker = getattr(client, "reminder_checker", None)
    last_sync_mono = getattr(checker, "_last_gcal_sync", None)
    if isinstance(last_sync_mono, (int, float)):
        age_seconds = time.monotonic() - float(last_sync_mono)
        if 0 <= age_seconds <= CALENDAR_SYNC_STALE_AFTER_SECONDS:
            return _health_component(
                enabled=True,
                required=True,
                status="ready",
                checked_at=checked_at,
                reason_code="calendar_sync_recent",
                gcal_enabled=True,
                age_seconds=int(age_seconds),
            )

    task_items = {}
    task_health = getattr(monitor, "get_task_health", None)
    if callable(task_health):
        try:
            task_items = task_health()
        except Exception:
            task_items = {}
    initial_sync = task_items.get("initial-gcal-sync", {}) if isinstance(task_items, dict) else {}
    last_ok = _parse_timestamp(initial_sync.get("last_ok")) if isinstance(initial_sync, dict) else None
    if last_ok is None and isinstance(initial_sync, dict):
        last_ok = _parse_timestamp(initial_sync.get("finished_at"))
    age = _utc_now(now) - last_ok if last_ok else None
    if age is not None and timedelta(0) <= age <= timedelta(seconds=CALENDAR_SYNC_STALE_AFTER_SECONDS):
        return _health_component(
            enabled=True,
            required=True,
            status="ready",
            checked_at=checked_at,
            reason_code="calendar_sync_recent",
            gcal_enabled=True,
            age_seconds=max(0, int(age.total_seconds())),
        )

    return _health_component(
        enabled=True,
        required=True,
        status="stale",
        checked_at=checked_at,
        reason_code="calendar_sync_stale",
        recovery_action="Kjør Google-synkronisering og kontroller resultatet i den innloggede konsollen.",
        gcal_enabled=True,
        age_seconds=max(0, int(age.total_seconds())) if age is not None else None,
    )


def _collect_scheduler_readiness(
    monitor: object | None, *, now: datetime
) -> dict[str, Any]:
    checked_at = now.isoformat()
    if monitor is None:
        return _health_component(
            enabled=True,
            required=True,
            status="unavailable",
            checked_at=checked_at,
            reason_code="scheduler_not_started",
            recovery_action="Start boten og vent på påminnelsesplanleggeren.",
        )

    tasks = _collect_task_health(monitor)
    items = tasks.get("items", {}) if isinstance(tasks, dict) else {}
    scheduler = items.get("reminder-checker") if isinstance(items, dict) else None
    if not isinstance(scheduler, dict):
        return _health_component(
            enabled=True,
            required=True,
            status="unavailable",
            checked_at=checked_at,
            reason_code="scheduler_not_started",
            recovery_action="Start boten på nytt og kontroller at påminnelsesplanleggeren starter.",
        )

    state = str(scheduler.get("state", "unknown")).lower()
    if state in {"failed", "cancelled", "degraded"}:
        return _health_component(
            enabled=True,
            required=True,
            status="degraded",
            checked_at=checked_at,
            reason_code="scheduler_failed",
            recovery_action="Start boten på nytt og kontroller planleggerdiagnostikken i den innloggede konsollen.",
        )
    if state != "running":
        return _health_component(
            enabled=True,
            required=True,
            status="unavailable",
            checked_at=checked_at,
            reason_code="scheduler_not_running",
            recovery_action="Start boten på nytt og kontroller at påminnelsesplanleggeren starter.",
        )

    heartbeat = _parse_timestamp(scheduler.get("last_ok"))
    if heartbeat is None:
        heartbeat = _parse_timestamp(scheduler.get("started_at"))
    age = now - heartbeat if heartbeat else None
    if age is None or not timedelta(0) <= age <= SCHEDULER_STALE_AFTER:
        return _health_component(
            enabled=True,
            required=True,
            status="stale",
            checked_at=checked_at,
            reason_code="scheduler_heartbeat_stale",
            recovery_action="Start planleggeren på nytt og kontroller at fullførte arbeidsrunder registreres.",
            heartbeat_at=heartbeat.isoformat() if heartbeat else None,
        )
    return _health_component(
        enabled=True,
        required=True,
        status="ready",
        checked_at=checked_at,
        reason_code="scheduler_running",
        heartbeat_at=heartbeat.isoformat(),
    )


def _collect_store_readiness(*, now: datetime) -> dict[str, Any]:
    checked_at = now.isoformat()
    store = _collect_persistence_health()
    status = str(store.get("status", "unavailable")).lower()
    if status in {"ok", "healthy", "ready"}:
        return _health_component(
            enabled=True,
            required=True,
            status="ready",
            checked_at=checked_at,
            reason_code="store_healthy",
        )
    if status == "degraded":
        return _health_component(
            enabled=True,
            required=True,
            status="degraded",
            checked_at=checked_at,
            reason_code="store_write_or_read_failed",
            recovery_action="Kontroller konsolllagerets rettigheter og ledig plass. Bevar eksisterende filer før reparasjon.",
        )
    return _health_component(
        enabled=True,
        required=True,
        status="unavailable",
        checked_at=checked_at,
        reason_code="store_unavailable",
        recovery_action="Gjenopprett tilgang til konsolllageret og start konsollen på nytt.",
    )


def _provider_snapshot(monitor: object | None) -> dict[str, Any]:
    getter = getattr(monitor, "get_provider_readiness", None)
    if callable(getter):
        try:
            snapshot = getter()
        except Exception:
            snapshot = None
    else:
        snapshot = getattr(monitor, "_provider_readiness", None)
    return snapshot if isinstance(snapshot, dict) else {}


def _provider_readiness_component(
    monitor: object | None,
    bridge: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    provider, _fallback = _provider_contracts(monitor)
    config = _provider_config(monitor)
    enabled = provider in {"lm_studio", "openrouter"}
    probe = _provider_snapshot(monitor).get("probe")
    inference = _provider_snapshot(monitor).get("inference")
    probe = probe if isinstance(probe, dict) else {}
    inference = inference if isinstance(inference, dict) else {}
    probe_ok = probe.get("ok") if type(probe.get("ok")) is bool else None
    probe_at = _parse_timestamp(probe.get("checked_at"))
    if probe_at is None or not timedelta(0) <= now - probe_at <= PROVIDER_EVIDENCE_TTL:
        probe_ok = None
    inference_at = _parse_timestamp(inference.get("checked_at"))
    inference_status = str(inference.get("status", "")).lower()
    inference_provider = _provider_name(inference.get("provider"))
    inference_fresh = inference_at is not None and timedelta(0) <= now - inference_at <= PROVIDER_EVIDENCE_TTL
    inference_accepted = (
        inference_status == "success"
        and bool(inference.get("accepted", True))
        and inference_fresh
    )
    primary_accepted = inference_accepted and inference_provider == provider
    bridge_connected = (
        bridge.get("lm_studio") == "connected"
        and bridge.get("status") not in {"unavailable", "error"}
    )
    if provider == "lm_studio":
        transport = "reachable" if bridge_connected or primary_accepted else (
            "unavailable" if bridge.get("status") in {"unavailable", "error"} else "unverified"
        )
        model_discovery = "catalog_reachable" if bridge_connected else (
            "unavailable" if transport == "unavailable" else "unverified"
        )
    else:
        transport = "reachable" if primary_accepted or probe_ok is True else (
            "unavailable" if probe_ok is False else "unverified"
        )
        model_discovery = "catalog_reachable" if probe_ok is True else (
            "unavailable" if probe_ok is False else "unverified"
        )
    inference_label = "accepted" if inference_accepted else (
        "rejected" if inference_status and inference_status != "success" and inference_fresh else "not_observed"
    )

    missing_credentials = provider == "openrouter" and config is not None and not getattr(config, "OPENROUTER_API_KEY", None)
    used_fallback = bool(inference.get("fallback")) or (
        inference_accepted and inference_provider and inference_provider != provider
    )
    if not enabled:
        status, reason, action = "unavailable", "provider_contract_missing", "Velg en støttet AI-provider i privat oppsett og start boten på nytt."
    elif missing_credentials:
        status, reason, action = "unavailable", "provider_credentials_missing", "Legg inn valgt providers legitimasjon i privat oppsett og start boten på nytt."
    elif transport == "unavailable" and not inference_accepted:
        status, reason, action = "unavailable", "provider_unreachable", "Kontroller valgt providers tjeneste og tilkoblingsadresse, og koble til igjen."
    elif inference_status == "auth_error" and inference_fresh:
        status, reason, action = "unavailable", "provider_auth_rejected", "Kontroller providers legitimasjon og modelltilgang i privat oppsett."
    elif inference_status in {"busy", "retryable"} and inference_fresh:
        status, reason, action = "degraded", "provider_request_failed", "Vent på ledig kapasitet hos provider og prøv en vanlig forespørsel igjen."
    elif inference_accepted and inference_provider == provider and not used_fallback:
        status, reason, action = "ready", "provider_inference_accepted", None
    elif used_fallback:
        status, reason, action = "degraded", "fallback_provider_served", "Kontroller hovedprovider. Den konfigurerte reserveprovideren svarte sist."
    else:
        status, reason, action = "stale", "inference_acceptance_unobserved", "Send en vanlig AI-forespørsel til boten for å kontrollere et faktisk modellsvar."

    return _health_component(
        enabled=enabled,
        required=True,
        status=status,
        checked_at=now.isoformat(),
        reason_code=reason,
        recovery_action=action,
        provider=provider,
        transport_status=transport,
        model_discovery_status=model_discovery,
        inference_acceptance_status=inference_label,
        provider_checked_at=probe_at.isoformat() if probe_at else None,
        inference_checked_at=inference_at.isoformat() if inference_at else None,
    )


async def collect_provider_readiness(
    monitor: object | None = None,
    *,
    bridge_health: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build redacted readiness from configuration and observed outcomes only."""
    checked = _utc_now(now)
    bridge_enabled, bridge_required = _bridge_contract(monitor)
    if bridge_health is None:
        bridge_health = await collect_bridge_health(monitor) if bridge_enabled else {"status": "disabled"}
    provider = _provider_readiness_component(monitor, bridge_health, now=checked)
    if not bridge_enabled:
        bridge = _health_component(
            enabled=False,
            required=False,
            status="disabled",
            checked_at=checked.isoformat(),
            reason_code="bridge_not_required",
        )
    elif bridge_health.get("lm_studio") == "connected" and bridge_health.get("status") not in {"unavailable", "error"}:
        bridge = _health_component(
            enabled=True,
            required=bridge_required,
            status="ready",
            checked_at=checked.isoformat(),
            reason_code="bridge_model_catalog_reachable",
        )
    else:
        bridge = _health_component(
            enabled=True,
            required=bridge_required,
            status="unavailable",
            checked_at=checked.isoformat(),
            reason_code="bridge_unreachable",
            recovery_action="Start Hermes-broen og kontroller at LM Studio kjører med valgt modell.",
        )

    calendar_sync = _collect_calendar_sync_health(monitor, now=checked)
    google_calendar = dict(calendar_sync)
    scheduler = _collect_scheduler_readiness(monitor, now=checked)
    store = _collect_store_readiness(now=checked)
    components = {
        "provider": provider,
        "bridge": bridge,
        "google_calendar": google_calendar,
        "scheduler": scheduler,
        "store": store,
        "calendar_sync": calendar_sync,
    }
    required_statuses = [
        component["status"]
        for component in components.values()
        if component["required"]
    ]
    if "unavailable" in required_statuses:
        status = "unavailable"
    elif "degraded" in required_statuses:
        status = "degraded"
    elif "stale" in required_statuses:
        status = "stale"
    else:
        status = "ready"
    return {"status": status, "checked_at": checked.isoformat(), "components": components}


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
            or calendar_sync.get("status") in {"degraded", "stale", "unavailable"}
        ):
            status = "degraded"
            if tasks.get("status") == "degraded":
                degraded_reasons.append("tasks_degraded")
            if persistence.get("status") == "degraded":
                degraded_reasons.append("persistence_degraded")
            if calendar_sync.get("status") in {"degraded", "stale", "unavailable"}:
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
    _bridge_enabled, bridge_required = _bridge_contract(monitor)
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
    enabled, required = _bridge_contract(monitor)
    checked_at = datetime.now(timezone.utc).isoformat()
    if not enabled:
        return {
            "status": "disabled",
            "lm_studio": "disabled",
            "enabled": False,
            "required": False,
            "checked_at": checked_at,
            "requests": 0,
            "errors": 0,
        }
    host, port, writer = "unknown", None, None
    try:
        host, port = _bridge_endpoint()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=2.5,
        )
        request = b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        writer.write(request)
        await asyncio.wait_for(writer.drain(), timeout=2.5)

        response = await asyncio.wait_for(reader.read(4096), timeout=2.5)

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
                    "enabled": True,
                    "required": required,
                    "checked_at": checked_at,
                    "host": host,
                    "port": port,
                    "requests": payload.get("requests", 0),
                    "errors": payload.get("errors", 0),
                }
    except Exception:
        pass
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2.5)
            except Exception:
                pass

    return {
        "status": "unavailable",
        "lm_studio": "unknown",
        "enabled": True,
        "required": required,
        "checked_at": checked_at,
        "host": host,
        "port": port,
    }


def collect_calendar_data(monitor: object | None = None, *, actor=None) -> dict[str, Any]:
    path = hermes_discord_data_path("calendar.json")
    data = _read_json_file(path, {})
    policy = getattr(monitor, 'access_policy', None) or AccessPolicy()
    permitted = {scope_id: values for scope_id, values in data.items()
                 if policy.authorize(actor, scope_id if scope_id in policy.scopes or scope_id.startswith(('private:', 'group:')) else 'shared', 'read').allowed}
    withheld = set(data) - set(permitted)
    items = _flatten_calendar_items(permitted)

    now = (getattr(getattr(monitor, "calendar", None), "clock", None) or Clock()).now()
    sync_states = {state: 0 for state in ('pending', 'synced', 'unknown', 'failed', 'conflict')}
    for item in items:
        for operation in item.get('sync_operations', []):
            state = operation.get('state')
            if state in sync_states:
                sync_states[state] += 1
    upcoming = []
    event_count = 0
    task_count = 0

    for item in items:
        if item.get("completed") or item.get("delete_pending") or item.get('_mutation_deleted'):
            continue

        title = str(item.get('title', '')).strip()
        item_type = item.get('kind', item.get('type', 'event'))
        if item_type == 'task':
            task_count += 1
        else:
            event_count += 1

        item_date = _parse_date(item.get("date"))
        if item_date is None or item_date.date() < now.date():
            continue

        upcoming.append(
            {
                "title": title,
                "kind": item_type,
                "timezone": item.get("timezone", "Europe/Oslo"),
                "all_day": item.get("all_day", not bool(item.get("time"))),
                "duration_minutes": item.get("duration_minutes"),
                "date": item.get("date"),
                "time": item.get("time"),
                "recurrence": item.get("recurrence"),
            }
        )

    upcoming.sort(key=lambda value: _parse_date(value.get("date")) or datetime.max)

    return {
        "storage_status": "degraded" if str(path) in _JSON_READ_ERRORS else "ok",
        "storage_error": _JSON_READ_ERRORS.get(str(path)),
        "event_count": event_count,
        "sync_states": sync_states,
        "scope_policy": policy.describe(),
        "default_scope": policy.default_scope,
        "access_summary": policy_summary(policy) + (' Innhold fra andre områder er skjult; konsollen trenger en verifisert område-identitet.' if withheld else ''),
        "withheld_scope_count": len(withheld),
        "invocation_policy": invocation_description(getattr(getattr(monitor, 'client', None), 'config', None)),
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
                if poll.get("status") != "active" or PollManager._is_expired(poll):
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

    return {"active_polls": total_active, "polls": active_polls,
            "storage_status": "degraded" if str(path) in _JSON_READ_ERRORS else "ok",
            "storage_error": _JSON_READ_ERRORS.get(str(path))}


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
            "status": "unavailable",
            "lm_studio": "unknown",
            "requests": 1337,
            "errors": 3,
        },
        "readiness": {
            "status": "ready",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": {
                "provider": {
                    "enabled": True, "required": True, "status": "ready",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "reason_code": "provider_inference_accepted", "recovery_action": None,
                    "provider": "openrouter", "transport_status": "reachable",
                    "model_discovery_status": "catalog_reachable",
                    "inference_acceptance_status": "accepted",
                },
                "bridge": {
                    "enabled": False, "required": False, "status": "disabled",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "reason_code": "bridge_not_required", "recovery_action": None,
                },
                "google_calendar": {
                    "enabled": False, "required": False, "status": "disabled",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "reason_code": "google_calendar_disabled", "recovery_action": None,
                },
                "scheduler": {
                    "enabled": True, "required": True, "status": "ready",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "reason_code": "scheduler_running", "recovery_action": None,
                },
                "store": {
                    "enabled": True, "required": True, "status": "ready",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "reason_code": "store_healthy", "recovery_action": None,
                },
                "calendar_sync": {
                    "enabled": False, "required": False, "status": "disabled",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "reason_code": "google_calendar_disabled", "recovery_action": None,
                },
            },
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
        bridge = await collect_bridge_health(self.monitor)
        return {
            "status": collect_bot_status(self.monitor),
            "bridge": bridge,
            "readiness": await collect_provider_readiness(self.monitor, bridge_health=bridge),
            "calendar": collect_calendar_data(self.monitor),
            "polls": collect_poll_data(self.monitor),
            "rate_limits": collect_rate_limits(self.monitor),
            "intents": collect_intent_stats(self.monitor),
            "memory": collect_memory_stats(self.monitor),
            "logs": collect_logs(),
        }
