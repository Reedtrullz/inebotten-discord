import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import pathlib
import re
import secrets
import time
from datetime import date
from typing import cast
from urllib.parse import parse_qs, urlparse

from web_console.dashboard import render_commands_page, render_dashboard, render_gcal_auth_page, render_login_page  # pyright: ignore[reportUnknownVariableType]
from web_console.cloudflare_access import CloudflareAccessVerifier
from web_console.console_store import get_console_store
from web_console.state_collector import (
    StateCollector,
    collect_bot_status,
    collect_bridge_health,
    collect_calendar_data,
    collect_console_health,
    collect_provider_readiness,
    collect_intent_stats,
    collect_logs,
    collect_memory_stats,
    collect_poll_data,
    collect_rate_limits,
    generate_mock_data,
)
from core.request_context import RequestContext, request_scope
from cal_system.event_schema import EventTime

from utils.deployment_contract import built_revision

logger = logging.getLogger(__name__)

MAX_HEADER_BYTES = 32 * 1024
MAX_BODY_BYTES = 16 * 1024
DEFAULT_REQUEST_READ_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_ACTIVE_CONNECTIONS = 64
DEFAULT_SECURITY_HEADERS = [
    "Cache-Control: no-store",
    "Pragma: no-cache",
    "X-Content-Type-Options: nosniff",
    "X-Frame-Options: DENY",
    "Referrer-Policy: no-referrer",
]
HTML_SECURITY_HEADERS = [
    "Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
]


class ConsoleServer:
    host: str
    port: int
    api_key: str | None
    cookie_secure: bool
    monitor: object | None
    _server: asyncio.AbstractServer | None
    _active_connections: int

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        api_key: str | None = None,
        monitor: object | None = None,
        secure_cookies: bool | None = None,
        session_ttl_days: int | None = None,
        login_max_attempts: int | None = None,
        login_window_seconds: int | None = None,
        cookie_secure: bool | None = None,
        auth_mode: str | None = None,
        cloudflare_access_team_domain: str | None = None,
        cloudflare_access_audiences: list[str] | None = None,
        cloudflare_access_allowed_emails: list[str] | None = None,
        cloudflare_access_verifier: object | None = None,
        request_read_timeout: float | None = None,
        max_active_connections: int | None = None,
        console_actor_user_id: str | None = None,
        console_actor_channel_id: str | None = None,
        trusted_origin: str | None = None,
    ):
        self.host = host
        self.port = port
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.console_actor_user_id = (console_actor_user_id if console_actor_user_id is not None else os.getenv("CONSOLE_ACTOR_USER_ID", "")).strip()
        self.console_actor_channel_id = (console_actor_channel_id if console_actor_channel_id is not None else os.getenv("CONSOLE_ACTOR_CHANNEL_ID", "console")).strip()
        self.trusted_origin = (trusted_origin if trusted_origin is not None else os.getenv("CONSOLE_TRUSTED_ORIGIN", "")).strip().rstrip("/")
        self._calendar_create_previews: dict[str, dict] = {}
        self.monitor = monitor
        self.built_revision = built_revision()
        instance = os.getenv('INEBOTTEN_LAUNCHER_INSTANCE','')
        self.launcher_instance = instance if re.fullmatch(r'[A-Za-z0-9_-]{32}',instance) else None
        self._server = None
        self.request_read_timeout = self._positive_float(
            request_read_timeout if request_read_timeout is not None else os.getenv(
                "CONSOLE_REQUEST_READ_TIMEOUT", str(DEFAULT_REQUEST_READ_TIMEOUT_SECONDS)
            ),
            DEFAULT_REQUEST_READ_TIMEOUT_SECONDS,
        )
        self.max_active_connections = self._positive_int(
            max_active_connections if max_active_connections is not None else os.getenv(
                "CONSOLE_MAX_ACTIVE_CONNECTIONS", str(DEFAULT_MAX_ACTIVE_CONNECTIONS)
            ),
            DEFAULT_MAX_ACTIVE_CONNECTIONS,
        )
        self._active_connections = 0
        self._connection_tasks = set()
        self._connection_writers = set()
        self._stopping = False
        self.store = get_console_store()
        self.session_ttl_seconds = max(
            1,
            int(session_ttl_days if session_ttl_days is not None else os.getenv("CONSOLE_SESSION_TTL_DAYS", "30")) * 86400,
        )
        self.login_max_attempts = max(
            1,
            int(login_max_attempts if login_max_attempts is not None else os.getenv("CONSOLE_LOGIN_MAX_ATTEMPTS", "5")),
        )
        self.login_window_seconds = max(
            1,
            int(login_window_seconds if login_window_seconds is not None else os.getenv("CONSOLE_LOGIN_WINDOW_SECONDS", "300")),
        )
        if cookie_secure is None:
            cookie_secure = secure_cookies
        if cookie_secure is None:
            cookie_secure = os.getenv("CONSOLE_COOKIE_SECURE", "False").lower() == "true"
        self.cookie_secure = bool(cookie_secure)
        if not self._is_loopback_host(self.host):
            # A console bound beyond loopback must never issue a session cookie
            # that can be sent over cleartext HTTP.  This remains fail-closed
            # even when an old deployment explicitly configured False.
            if not self.cookie_secure:
                logger.warning("Forcing Secure console cookies for non-local bind host %s", self.host)
            self.cookie_secure = True
        self.auth_mode = (auth_mode or os.getenv("CONSOLE_AUTH_MODE", "api_key")).strip().lower()
        if self.auth_mode not in {"api_key", "cloudflare_access"}:
            raise ValueError("CONSOLE_AUTH_MODE must be 'api_key' or 'cloudflare_access'")
        self.cloudflare_access_verifier = cloudflare_access_verifier
        if self.auth_mode == "cloudflare_access" and self.cloudflare_access_verifier is None:
            team_domain = (
                cloudflare_access_team_domain
                if cloudflare_access_team_domain is not None
                else os.getenv("CONSOLE_CF_ACCESS_TEAM_DOMAIN", "")
            )
            audiences = (
                cloudflare_access_audiences
                if cloudflare_access_audiences is not None
                else self._split_env_list(os.getenv("CONSOLE_CF_ACCESS_AUD", ""))
            )
            allowed_emails = (
                cloudflare_access_allowed_emails
                if cloudflare_access_allowed_emails is not None
                else self._split_env_list(os.getenv("CONSOLE_CF_ACCESS_ALLOWED_EMAILS", ""))
            )
            self.cloudflare_access_verifier = CloudflareAccessVerifier(
                team_domain=team_domain,
                audiences=audiences,
                allowed_emails=allowed_emails,
            )
        self._login_failures: dict[str, list[float]] = {}

    @staticmethod
    def _positive_float(value: object, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed) or parsed <= 0:
            return default
        return parsed

    @staticmethod
    def _positive_int(value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        normalized = (host or "").strip().lower().strip("[]")
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    @property
    def active_connections(self) -> int:
        return self._active_connections

    @property
    def actual_port(self) -> int:
        if self._server is None:
            return self.port
        for sock in (self._server.sockets or []):
            return sock.getsockname()[1]
        return self.port

    async def start(self) -> None:
        if self._server is not None:
            return

        if self.api_key is None:
            raise RuntimeError("ConsoleServer requires a non-empty api_key")
        if self.auth_mode == "cloudflare_access":
            configured = bool(getattr(self.cloudflare_access_verifier, "configured", False))
            if not configured:
                raise RuntimeError("Cloudflare Access console auth requires team domain, AUD, and allowed email config")

        # Keep the StreamReader's internal line buffer bounded as well as the
        # explicit MAX_HEADER_BYTES check in handle_request().
        self._stopping = False
        self._server = await asyncio.start_server(
            self.handle_request,
            self.host,
            self.port,
            limit=MAX_HEADER_BYTES,
        )
        sockets = self._server.sockets or []
        bound = ", ".join(f"{sock.getsockname()!r}" for sock in sockets) if sockets else f"{self.host}:{self.port}"
        logger.info("Console server started on %s", bound)

    async def stop(self) -> None:
        self._stopping = True
        server = self._server
        if server is not None:
            server.close()
        tasks = self._connection_tasks - {asyncio.current_task()}
        for writer in list(self._connection_writers):
            writer.close()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if server is not None:
            await server.wait_closed()
            self._server = None
        logger.info("Console server stopped")

    def _parse_headers(self, lines: list[str]) -> dict[str, str]:
        headers: dict[str, str] = {}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return headers

    def _split_env_list(self, value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _content_length(self, headers: dict[str, str]) -> int | None:
        raw_length = headers.get("content-length", "0") or "0"
        try:
            content_length = int(raw_length)
        except ValueError:
            return None
        if content_length < 0:
            return None
        return content_length

    def _parse_form_body(self, body_bytes: bytes) -> dict[str, str]:
        body_text = body_bytes.decode("utf-8", errors="replace")
        parsed = parse_qs(body_text, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def _wants_json(self, headers: dict[str, str]) -> bool:
        return (
            "application/json" in headers.get("accept", "").lower()
            or "application/json" in headers.get("content-type", "").lower()
        )

    def _extract_gcal_credentials_payload(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
    ) -> tuple[bool, object | str]:
        if not body_bytes:
            return False, "Mangler OAuth Client ID JSON."

        body_text = body_bytes.decode("utf-8", errors="replace").strip()
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()

        if content_type == "application/json" or body_text.startswith("{"):
            try:
                payload = json.loads(body_text)
            except json.JSONDecodeError as exc:
                return False, f"Ugyldig JSON: {exc.msg}"
            if isinstance(payload, dict) and "credentials_json" in payload:
                return True, payload.get("credentials_json", "")
            if isinstance(payload, dict) and "credentials" in payload:
                return True, payload.get("credentials", "")
            return True, payload

        form_data = self._parse_form_body(body_bytes)
        return True, form_data.get("credentials_json", "")

    def _parse_cookies(self, cookie_header: str | None) -> dict[str, str]:
        cookies: dict[str, str] = {}
        if not cookie_header:
            return cookies
        for part in cookie_header.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            cookies[key.strip()] = value.strip()
        return cookies

    def _candidate_matches_api_key(self, candidate: str | None) -> bool:
        if self.api_key is None or candidate is None:
            return False
        return hmac.compare_digest(candidate, self.api_key)

    def _is_authenticated(self, headers: dict[str, str]) -> bool:
        api_key = headers.get("x-api-key")
        if self._valid_api_key(api_key):
            return True
        cookies = self._parse_cookies(headers.get("cookie"))
        if self.store.validate_session(cookies.get("console_session"), self._session_binding_hash()):
            return True
        if self.auth_mode == "cloudflare_access":
            verifier = self.cloudflare_access_verifier
            if verifier is not None and hasattr(verifier, "verify_headers"):
                return bool(verifier.verify_headers(headers))
        return False

    async def _is_authenticated_async(self, headers: dict[str, str]) -> bool:
        api_key = headers.get("x-api-key")
        if self._valid_api_key(api_key):
            return True
        cookies = self._parse_cookies(headers.get("cookie"))
        if self.store.validate_session(cookies.get("console_session"), self._session_binding_hash()):
            return True
        if self.auth_mode == "cloudflare_access":
            verifier = self.cloudflare_access_verifier
            if verifier is not None and hasattr(verifier, "verify_headers"):
                return bool(await asyncio.to_thread(verifier.verify_headers, headers))
        return False

    def _valid_api_key(self, submitted: str | None) -> bool:
        expected = "" if self.api_key is None else str(self.api_key)
        if not submitted or not expected:
            return False
        return hmac.compare_digest(submitted, expected)

    def _session_binding_hash(self) -> str | None:
        if not self.api_key:
            return None
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()

    def _console_actor(self) -> RequestContext | None:
        if not self.console_actor_user_id or not self.console_actor_channel_id:
            return None
        return RequestContext("console", self.console_actor_user_id, self.console_actor_channel_id,
                              None, "no", channel_kind="console")

    def _csrf_token(self, session_token: str) -> str:
        key = hashlib.sha256((self.api_key or "").encode("utf-8")).digest()
        return hmac.new(key, ("calendar-write:" + session_token).encode("utf-8"), hashlib.sha256).hexdigest()

    def _calendar_credential(self, headers: dict[str, str]) -> str | None:
        if self._valid_api_key(headers.get("x-api-key")):
            return "api_key"
        cookies = self._parse_cookies(headers.get("cookie"))
        if self.store.validate_session(cookies.get("console_session"), self._session_binding_hash()):
            return "session"
        if self.auth_mode == "cloudflare_access":
            return "cloudflare"
        return None

    def _calendar_write_allowed(self, headers: dict[str, str]) -> tuple[bool, str | None]:
        credential = self._calendar_credential(headers)
        if credential is None:
            return False, "unauthorized"
        if credential != "session":
            return True, None
        if not self.trusted_origin or headers.get("origin", "") != self.trusted_origin:
            return False, "trusted_origin_required"
        session = self._parse_cookies(headers.get("cookie")).get("console_session", "")
        supplied = headers.get("x-csrf-token", "")
        if not session or not hmac.compare_digest(supplied, self._csrf_token(session)):
            return False, "csrf_failed"
        return True, None

    def _browser_write_allowed(self, headers: dict[str, str], body_bytes: bytes = b"") -> tuple[bool, str | None]:
        credential = self._calendar_credential(headers)
        if credential is None:
            return False, "unauthorized"
        if credential == "api_key":
            return True, None
        if credential != "session":
            return False, "browser_writes_require_console_session"
        if not self.trusted_origin or headers.get("origin", "") != self.trusted_origin:
            return False, "trusted_origin_required"
        session = self._parse_cookies(headers.get("cookie")).get("console_session", "")
        supplied = headers.get("x-csrf-token", "") or self._parse_form_body(body_bytes).get("csrf_token", "")
        if not session or not hmac.compare_digest(supplied, self._csrf_token(session)):
            return False, "csrf_failed"
        return True, None

    @staticmethod
    def _strict_json_object(body: bytes) -> dict:
        def reject_constant(_value):
            raise ValueError("invalid_json_constant")
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_json_key")
                result[key] = value
            return result
        value = json.loads(body.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_pairs)
        if not isinstance(value, dict):
            raise ValueError("json_object_required")
        return value

    def _calendar_context(self):
        actor = self._console_actor()
        manager = getattr(self.monitor, "calendar", None)
        policy = getattr(manager, "access_policy", None)
        scope = getattr(policy, "default_scope", None)
        if actor is None or manager is None or policy is None or not scope:
            return None, None, None, "calendar_workspace_not_configured"
        return manager, policy, scope, None

    def _calendar_items_response(self, credential: str | None = None, headers: dict[str, str] | None = None) -> dict:
        actor = self._console_actor()
        manager, policy, scope, reason = self._calendar_context()
        enabled = not reason and policy.authorize(actor, scope, "read").allowed
        if not enabled:
            return {"enabled": False, "reason_code": reason or "calendar_scope_forbidden",
                    "message": "Arbeidsområdet er deaktivert. Konfigurer CONSOLE_ACTOR_USER_ID og gi den identiteten tilgang til kalenderområdet.",
                    "items": [], "revision": None}
        items = []
        with manager._storage.transaction(write=False):
            revision = manager._storage.revision
            for item in manager.items.get(scope, []):
                if item.get("_mutation_deleted") or item.get("delete_pending"):
                    continue
                sync = item.get("sync_operations", [])
                items.append({key: item.get(key) for key in (
                    "id", "title", "description", "date", "time", "kind", "all_day", "timezone",
                    "duration_minutes", "completed", "recurrence", "sync_blocked")}
                    | {"pending_sync": bool(item.get("_local_sync_pending")),
                       "sync_state": next((op.get("state") for op in reversed(sync) if op.get("state") != "synced"), "synced"),
                       "conflicts": [{"operation_id": op.get("operation_id"), "reason_code": op.get("reason_code")}
                                     for op in sync if op.get("state") == "conflict"]})
        def agenda_key(item):
            try:
                day=EventTime.from_item(item).local_date
            except (ValueError,TypeError):
                day=date.max
            return day,str(item.get("time") or ""),str(item.get("title") or "").casefold()
        items.sort(key=agenda_key)
        write_authorized = policy.authorize(actor, scope, "write").allowed
        write_available = write_authorized and (credential == "api_key" or credential == "session" and bool(self.trusted_origin))
        result = {"enabled": True, "scope_id": scope, "revision": revision,
                  "items": items, "read_only": not write_available, "write_available": write_available,
                  "trusted_origin_configured": bool(self.trusted_origin)}
        if credential == "session" and headers:
            session = self._parse_cookies(headers.get("cookie" )).get("console_session", "")
            result["csrf_token"] = self._csrf_token(session)
        return result

    def _calendar_preview(self, actor: RequestContext, payload: dict) -> dict:
        allowed = {"operation", "item_id", "revision", "changes", "choice", "operation_id"}
        if set(payload) - allowed or type(payload.get("revision")) is not int:
            raise ValueError("invalid_payload")
        manager, policy, scope, reason = self._calendar_context()
        if reason:
            raise PermissionError(reason)
        if not policy.authorize(actor, scope, "write").allowed:
            raise PermissionError("scope_membership_required")
        operation = payload.get("operation")
        if operation == "create":
            if set(payload) != {"operation", "revision", "changes"}:
                raise ValueError("invalid_payload")
            changes = payload.get("changes")
            fields = {"title", "description", "date", "time", "kind", "timezone", "all_day", "duration_minutes"}
            if not isinstance(changes, dict) or set(changes) - fields or not {"title", "date"} <= set(changes):
                raise ValueError("invalid_create")
            if not isinstance(changes["title"], str) or not changes["title"].strip() or len(changes["title"]) > 200:
                raise ValueError("invalid_title")
            if "all_day" in changes and type(changes["all_day"]) is not bool:
                raise ValueError("invalid_all_day")
            if "duration_minutes" in changes and (type(changes["duration_minutes"]) is not int or not 1 <= changes["duration_minutes"] <= 10080):
                raise ValueError("invalid_duration")
            if "time" in changes and changes["time"] is not None and not isinstance(changes["time"], str):
                raise ValueError("invalid_time")
            if "timezone" in changes and (not isinstance(changes["timezone"], str) or len(changes["timezone"]) > 80):
                raise ValueError("invalid_timezone")
            if "description" in changes and (not isinstance(changes["description"], str) or len(changes["description"]) > 4000):
                raise ValueError("invalid_description")
            time_input = {"date": changes["date"], "time": changes.get("time"),
                "kind": changes.get("kind", "event"), "timezone": changes.get("timezone", "Europe/Oslo")}
            for key in ("all_day", "duration_minutes"):
                if key in changes:
                    time_input[key] = changes[key]
            value = EventTime.from_item(time_input).validate_local()
            now = time.monotonic()
            self._calendar_create_previews = {key: entry for key, entry in self._calendar_create_previews.items()
                                              if entry["expires"] > now}
            token = secrets.token_urlsafe(24)
            self._calendar_create_previews[token] = {"actor": [actor.user_id, actor.channel_id, actor.guild_id, actor.channel_kind],
                "scope": scope, "revision": payload["revision"], "changes": dict(changes), "expires": time.monotonic() + 300}
            while len(self._calendar_create_previews) > 32:
                self._calendar_create_previews.pop(next(iter(self._calendar_create_previews)))
            return {"token": token, "revision": payload["revision"], "operation": "create",
                    "effects": [{"after": {**dict(changes), **value.fields()}}]}
        if operation == "conflict":
            if set(payload) != {"operation", "revision", "operation_id", "choice"}:
                raise ValueError("invalid_payload")
            if payload["revision"] != manager._storage.revision:
                raise ValueError("revision_changed")
            preview = manager.preview_sync_conflict(actor, payload["operation_id"], payload["choice"])
        else:
            if set(payload) != {"operation", "revision", "item_id"} | ({"changes"} if operation == "edit" else set()):
                raise ValueError("invalid_payload")
            item_id = payload["item_id"]
            if not isinstance(item_id, str) or len(item_id) > 64:
                raise ValueError("invalid_item_id")
            if operation == "edit":
                changes = payload["changes"]
                allowed_changes = {"title", "description", "date", "time", "kind", "timezone", "all_day", "duration_minutes"}
                if not isinstance(changes, dict) or not changes or set(changes) - allowed_changes:
                    raise ValueError("invalid_changes")
            if payload["revision"] != manager._storage.revision:
                raise ValueError("revision_changed")
            preview = manager.preview_mutation(actor, scope, [item_id], operation, payload["revision"], changes=payload.get("changes"))
        return {"token": preview.token, "revision": preview.revision, "expires_at": preview.expires_at.isoformat(),
                "operation": operation, "effects": preview.effects}

    async def _calendar_apply(self, actor: RequestContext, payload: dict) -> dict:
        if set(payload) != {"token"} or not isinstance(payload.get("token"), str) or len(payload["token"]) > 128:
            raise ValueError("invalid_payload")
        manager, policy, scope, reason = self._calendar_context()
        if reason:
            raise PermissionError(reason)
        if not policy.authorize(actor, scope, "write").allowed:
            raise PermissionError("scope_membership_required")
        token = payload["token"]
        create = self._calendar_create_previews.get(token)
        if create is not None:
            identity = [actor.user_id, actor.channel_id, actor.guild_id, actor.channel_kind]
            if create["actor"] != identity or create["scope"] != scope:
                raise PermissionError("preview_actor_mismatch")
            if time.monotonic() >= create["expires"]:
                self._calendar_create_previews.pop(token, None)
                raise ValueError("preview_expired")
            self._calendar_create_previews.pop(token, None)
            values = create["changes"]
            with manager._storage.transaction(write=True):
                if manager._storage.revision != create["revision"]:
                    raise ValueError("revision_changed")
                with request_scope(actor):
                    item = manager.add_item(None, actor.user_id, "Console", values["title"].strip(), values["date"],
                        values.get("time"), kind=values.get("kind", "event"), timezone=values.get("timezone", "Europe/Oslo"),
                        all_day=values.get("all_day"), duration_minutes=values.get("duration_minutes"), channel_id=actor.channel_id,
                        description=values.get("description", ""))
            return {"ok": True, "operation": "create", "revision": manager._storage.revision, "item": dict(item)}
        if token in manager._sync_conflicts:
            result = await manager.apply_sync_conflict(actor, token, deadline=time.monotonic() + 10)
            return {"ok": True, "operation": "conflict", "revision": manager._storage.revision,
                    "sync_state": result.state, "reason_code": result.reason_code}
        result = await manager.apply_preview(actor, token)
        return {"ok": True, "operation": result["operation"], "revision": manager._storage.revision,
                "applied_count": result["applied_count"], "remote_pending": result["remote_pending"],
                "remote_blocked": result["remote_blocked"]}

    def _peer_key(self, writer: asyncio.StreamWriter) -> str:
        peername = writer.get_extra_info("peername")
        if isinstance(peername, tuple) and peername:
            return str(peername[0])
        return "unknown"

    def _login_limited(self, peer_key: str) -> bool:
        now = time.time()
        failures = [
            ts for ts in self._login_failures.get(peer_key, [])
            if now - ts < self.login_window_seconds
        ]
        self._login_failures[peer_key] = failures
        return len(failures) >= self.login_max_attempts

    def _record_login_failure(self, peer_key: str) -> None:
        failures = self._login_failures.setdefault(peer_key, [])
        failures.append(time.time())
        self._login_failures[peer_key] = [
            ts for ts in failures if time.time() - ts < self.login_window_seconds
        ]

    def _clear_login_failures(self, peer_key: str) -> None:
        self._login_failures.pop(peer_key, None)

    def _secure_cookie_enabled(self, headers: dict[str, str]) -> bool:
        forwarded_proto = headers.get("x-forwarded-proto", "").lower()
        return self.cookie_secure or forwarded_proto == "https"

    def _session_cookie_header(self, token: str, headers: dict[str, str], max_age: int | None = None) -> str:
        max_age = self.session_ttl_seconds if max_age is None else max_age
        parts = [
            f"console_session={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={max_age}",
        ]
        if self._secure_cookie_enabled(headers):
            parts.append("Secure")
        return "Set-Cookie: " + "; ".join(parts)

    async def _serve_static_file(self, writer: asyncio.StreamWriter, path: str) -> None:
        static_dir = pathlib.Path(__file__).parent / "static"
        if not path.startswith("/static/"):
            await self._send_response(writer, 404, {"error": "Not found"})
            return

        relative = path[len("/static/"):]
        requested = static_dir / relative

        try:
            resolved = requested.resolve()
            static_resolved = static_dir.resolve()
            if not str(resolved).startswith(str(static_resolved) + os.sep) and str(resolved) != str(static_resolved):
                await self._send_response(writer, 403, {"error": "Forbidden"})
                return
        except (OSError, ValueError):
            await self._send_response(writer, 403, {"error": "Forbidden"})
            return

        if not resolved.is_file():
            await self._send_response(writer, 404, {"error": "Not found"})
            return

        for part in [requested] + list(requested.parents):
            if part == static_dir:
                break
            if part.is_symlink():
                await self._send_response(writer, 403, {"error": "Forbidden"})
                return

        ext = resolved.suffix.lower()
        mime_types = {
            ".css": "text/css",
            ".js": "application/javascript",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".woff2": "font/woff2",
            ".ico": "image/x-icon",
            ".json": "application/json",
        }

        if ext not in mime_types:
            await self._send_response(writer, 403, {"error": "Forbidden"})
            return

        try:
            content = resolved.read_bytes()
            await self._send_response(writer, 200, content, content_type=mime_types[ext])
        except OSError:
            await self._send_response(writer, 404, {"error": "Not found"})

    async def _send_response(self, writer: asyncio.StreamWriter, status: int, body: object, content_type: str = "application/json; charset=utf-8", extra_headers: list[str] | None = None) -> None:
        status_text = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            302: "Found",
            408: "Request Timeout",
            413: "Payload Too Large",
            429: "Too Many Requests",
            503: "Service Unavailable",
            500: "Internal Server Error",
        }.get(status, "OK")

        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = str(body).encode("utf-8")

        header_lines = [
            f"HTTP/1.1 {status} {status_text}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body_bytes)}",
            "Connection: close",
        ]
        if extra_headers:
            header_lines.extend(extra_headers)
        header_lines.extend(DEFAULT_SECURITY_HEADERS)
        if content_type.startswith("text/html"):
            header_lines.extend(HTML_SECURITY_HEADERS)
        header_lines.extend(["", ""])

        writer.write("\r\n".join(header_lines).encode("utf-8") + body_bytes)
        await writer.drain()

    async def handle_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._connection_tasks.add(task)
        self._connection_writers.add(writer)
        try:
            if self._stopping:
                writer.close()
                await writer.wait_closed()
                return
            await self._handle_request(reader, writer)
        finally:
            self._connection_tasks.discard(task)
            self._connection_writers.discard(writer)

    async def _handle_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._active_connections >= self.max_active_connections:
            try:
                await self._send_response(writer, 503, {"error": "Console busy; try again later"})
            except Exception:
                logger.debug("Could not reject excess console connection", exc_info=True)
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            return

        self._active_connections += 1
        try:
            try:
                header_data = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"),
                    timeout=self.request_read_timeout,
                )
            except asyncio.TimeoutError:
                await self._send_response(writer, 408, {"error": "Request timed out"})
                return
            except asyncio.IncompleteReadError:
                return
            except asyncio.LimitOverrunError:
                await self._send_response(writer, 400, {"error": "Request headers too large"})
                return
            if len(header_data) > MAX_HEADER_BYTES:
                await self._send_response(writer, 400, {"error": "Request headers too large"})
                return

            header_text = header_data.decode("utf-8", errors="ignore")
            lines = header_text.split("\r\n")
            if not lines or not lines[0]:
                await self._send_response(writer, 400, {"error": "Empty request"})
                return

            request_line = lines[0].split()
            if len(request_line) < 2:
                await self._send_response(writer, 400, {"error": "Invalid request"})
                return

            method, target = request_line[0].upper(), request_line[1]
            parsed = urlparse(target)
            path = parsed.path or "/"
            headers = self._parse_headers(lines[1:])

            content_length = self._content_length(headers)
            if content_length is None:
                await self._send_response(writer, 400, {"error": "Invalid Content-Length"})
                return
            if content_length > MAX_BODY_BYTES:
                await self._send_response(writer, 413, {"error": "Request body too large"})
                return
            body_bytes = b""
            if content_length > 0:
                try:
                    body_bytes = await asyncio.wait_for(
                        reader.readexactly(content_length),
                        timeout=self.request_read_timeout,
                    )
                except asyncio.TimeoutError:
                    await self._send_response(writer, 408, {"error": "Request body timed out"})
                    return
                except asyncio.IncompleteReadError:
                    await self._send_response(writer, 400, {"error": "Incomplete request body"})
                    return

            if method == "GET" and path.startswith("/static/"):
                await self._serve_static_file(writer, path)
                return

            auth_exempt = path in ("/health", "/demo", "/commands")
            if self.auth_mode == "api_key" and path == "/api/login":
                auth_exempt = True
            authenticated = auth_exempt or await self._is_authenticated_async(headers)

            if not authenticated and path in ("/", "/login"):
                if self.auth_mode == "cloudflare_access":
                    await self._send_response(writer, 401, {"error": "Cloudflare Access authentication required"})
                    return
                html = render_login_page()
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
                return

            if not authenticated:
                peername = cast(object | None, writer.get_extra_info("peername"))
                peername_text = "None" if peername is None else repr(peername)
                logger.warning("Unauthorized request to %s from %s", path, peername_text)
                await self._send_response(writer, 401, {"error": "Unauthorized"})
                return

            if path in ("/api/calendar/items", "/api/calendar/preview", "/api/calendar/apply"):
                credential = self._calendar_credential(headers)
                if path == "/api/calendar/items" and method == "GET":
                    await self._send_response(writer, 200, self._calendar_items_response(credential, headers))
                    return
                if method != "POST":
                    await self._send_response(writer, 405, {"error": "Method not allowed"})
                    return
                allowed, denial = self._calendar_write_allowed(headers)
                if not allowed:
                    await self._send_response(writer, 401 if denial == "unauthorized" else 403, {"error": denial})
                    return
                if "application/json" not in headers.get("content-type", "").lower():
                    await self._send_response(writer, 415, {"error": "application_json_required"})
                    return
                try:
                    payload = self._strict_json_object(body_bytes)
                    actor = self._console_actor()
                    if actor is None:
                        raise PermissionError("calendar_workspace_not_configured")
                    if path.endswith("/preview"):
                        result = self._calendar_preview(actor, payload)
                    else:
                        result = await self._calendar_apply(actor, payload)
                    await self._send_response(writer, 200, result)
                except PermissionError as error:
                    await self._send_response(writer, 403, {"error": str(error)})
                except (ValueError, TypeError, KeyError) as error:
                    code = str(error) or "invalid_calendar_request"
                    conflicts = {"revision_changed", "selection_changed", "conflict_changed", "remote_revision_changed"}
                    status = 409 if code in conflicts else 400
                    await self._send_response(writer, status, {"error": code})
                except Exception as error:
                    logger.info("Calendar workspace action failed: %s", type(error).__name__)
                    await self._send_response(writer, 409, {"error": "calendar_action_rejected"})
                return

            if method == "POST" and path == "/api/login":
                if self.auth_mode == "cloudflare_access":
                    await self._send_response(writer, 403, {"error": "API-key browser login is disabled in Cloudflare Access mode"})
                    return
                peer_key = self._peer_key(writer)
                if self._login_limited(peer_key):
                    html = render_login_page(error="Innlogging midlertidig blokkert. Prøv igjen senere.")
                    await self._send_response(writer, 429, html, content_type="text/html; charset=utf-8")
                    return

                body_text = body_bytes.decode("utf-8", errors="replace")
                form_data: dict[str, str] = {}
                for pair in body_text.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        from urllib.parse import unquote_plus
                        form_data[unquote_plus(k)] = unquote_plus(v)
                submitted_key = form_data.get("api_key", "")
                if self._valid_api_key(submitted_key):
                    self._clear_login_failures(peer_key)
                    try:
                        token = self.store.create_session(self.session_ttl_seconds, self._session_binding_hash())
                    except (OSError, RuntimeError):
                        await self._send_response(writer, 503, {"error": "Session storage unavailable"})
                        return
                    await self._send_response(
                        writer,
                        302,
                        "",
                        content_type="text/plain",
                        extra_headers=[
                            "Location: /",
                            self._session_cookie_header(token, headers),
                        ],
                    )
                else:
                    self._record_login_failure(peer_key)
                    html = render_login_page(error="Innlogging feilet")
                    await self._send_response(writer, 401, html, content_type="text/html; charset=utf-8")
                return

            if method == "POST" and path == "/api/setup/settings":
                allowed, denial = self._browser_write_allowed(headers)
                if not allowed:
                    await self._send_response(writer, 401 if denial == "unauthorized" else 403, {"error": denial})
                    return
                from core.config_schema import settings_path, update_settings, validate_settings

                if "application/json" not in headers.get("content-type", "").lower():
                    await self._send_response(writer, 400, {"error": "JSON settings are required"})
                    return
                try:
                    payload = json.loads(body_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._send_response(writer, 400, {"error": "Invalid settings payload"})
                    return
                changes = payload.get("settings") if isinstance(payload, dict) else None
                if not isinstance(changes, dict) or any(
                    not isinstance(key, str) or not isinstance(value, str)
                    for key, value in changes.items()
                ):
                    await self._send_response(writer, 400, {"error": "Settings must be text fields"})
                    return
                errors = validate_settings(changes)
                if errors:
                    await self._send_response(writer, 400, {"errors": errors})
                    return
                try:
                    target = settings_path()
                    update_settings(target, changes)
                except (OSError, ValueError):
                    await self._send_response(writer, 500, {"error": "Settings could not be saved"})
                    return
                await self._send_response(writer, 200, {"ok": True, "path": str(target)})
                return

            if method == "POST" and path == "/api/gcal/credentials":
                allowed, denial = self._browser_write_allowed(headers, body_bytes)
                if not allowed:
                    await self._send_response(writer, 401 if denial == "unauthorized" else 403, {"error": denial})
                    return
                from cal_system.google_calendar_manager import (
                    get_google_credentials_status,
                    save_google_client_credentials,
                )

                ok, payload_or_error = self._extract_gcal_credentials_payload(headers, body_bytes)
                if ok:
                    saved, message = save_google_client_credentials(payload_or_error)
                else:
                    saved, message = False, str(payload_or_error)

                status = get_google_credentials_status()
                if self._wants_json(headers):
                    await self._send_response(
                        writer,
                        200 if saved else 400,
                        {"ok": saved, "message": message, "status": status},
                    )
                else:
                    html = render_gcal_auth_page(
                        status,
                        message=message if saved else None,
                        error=None if saved else message,
                    )
                    await self._send_response(
                        writer,
                        200 if saved else 400,
                        html,
                        content_type="text/html; charset=utf-8",
                    )
                return

            if method == "POST" and path == "/api/logout":
                allowed, denial = self._browser_write_allowed(headers)
                if not allowed:
                    await self._send_response(writer, 401 if denial == "unauthorized" else 403, {"error": denial})
                    return
                cookies = self._parse_cookies(headers.get("cookie"))
                self.store.delete_session(cookies.get("console_session"))
                await self._send_response(
                    writer,
                    302,
                    "",
                    content_type="text/plain",
                    extra_headers=[
                        "Location: /login",
                        self._session_cookie_header("", headers, max_age=0),
                    ],
                )
                return

            if method != "GET":
                await self._send_response(writer, 405, {"error": "Method not allowed"})
                return

            if path == "/login":
                if self.auth_mode == "cloudflare_access":
                    await self._send_response(writer, 404, {"error": "Not found"})
                    return
                html = render_login_page()
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/health":
                health = await collect_console_health(self.monitor, port=self.port)
                readiness = await collect_provider_readiness(
                    self.monitor,
                    bridge_health=health.get("bridge") if isinstance(health.get("bridge"), dict) else None,
                )
                health_status = health.get("status", "starting")
                if health_status == "starting":
                    public_status = "starting"
                elif health_status == "degraded" or readiness.get("status") != "ready":
                    public_status = "degraded"
                else:
                    public_status = "healthy"
                public_health = {
                    "status": public_status,
                    "revision": self.built_revision,
                    "readiness": readiness.get("status", "starting"),
                    "console": {"status": "running"},
                }
                probe = headers.get('x-launcher-probe','')
                if self.launcher_instance and re.fullmatch(r'[A-Za-z0-9_-]{32}',probe) and hmac.compare_digest(probe,self.launcher_instance):
                    public_health['launcher_instance'] = self.launcher_instance
                await self._send_response(
                    writer,
                    200,
                    public_health,
                )
            elif path == "/":
                data = await StateCollector(self.monitor).collect_all()
                html = render_dashboard(data)
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/gcal-auth":
                from cal_system.google_calendar_manager import get_google_credentials_status

                html = render_gcal_auth_page(get_google_credentials_status())
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/commands":
                html = render_commands_page()
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/demo":
                html = render_dashboard(generate_mock_data(), is_demo=True)
                await self._send_response(writer, 200, html, content_type="text/html; charset=utf-8")
            elif path == "/api/status":
                await self._send_response(writer, 200, collect_bot_status(self.monitor))
            elif path == "/api/bridge":
                bridge = await collect_bridge_health(self.monitor)
                bridge.setdefault("lm_studio", "unknown")
                bridge.setdefault("requests", 0)
                bridge.setdefault("errors", 0)
                bridge["readiness"] = await collect_provider_readiness(
                    self.monitor, bridge_health=bridge
                )
                await self._send_response(writer, 200, bridge)
            elif path == "/api/calendar":
                await self._send_response(writer, 200, collect_calendar_data(self.monitor))
            elif path == "/api/calendar/items":
                await self._send_response(writer, 200, self._calendar_items_response(self._calendar_credential(headers), headers))
            elif path == "/api/polls":
                await self._send_response(writer, 200, collect_poll_data(self.monitor))
            elif path == "/api/rate-limits":
                await self._send_response(writer, 200, collect_rate_limits(self.monitor))
            elif path == "/api/intents":
                await self._send_response(writer, 200, collect_intent_stats(self.monitor))
            elif path == "/api/memory":
                await self._send_response(writer, 200, collect_memory_stats(self.monitor))
            elif path == "/api/gcal/credentials":
                from cal_system.google_calendar_manager import get_google_credentials_status

                await self._send_response(writer, 200, get_google_credentials_status())
            elif path == "/api/logs":
                from utils.storage_contract import store_worker
                try:
                    query = parse_qs(urlparse(target).query, keep_blank_values=True, max_num_fields=8)
                    if any(len(values) != 1 for values in query.values()):
                        raise ValueError('invalid_query')
                    query_lines = max(1, min(int(query.get('lines', ['200'])[0]), 2000))
                    budget = int(query['max_bytes'][0]) if 'max_bytes' in query else None
                    filters = {key: query[key][0] for key in ('level', 'component', 'outcome', 'request_id') if key in query}
                    page = await store_worker(collect_logs, query_lines, cursor=query.get('cursor', [None])[0], max_bytes=budget, filters=filters)
                except ValueError as error:
                    code = 'stale_cursor' if str(error) == 'stale_cursor' else 'invalid_log_query'
                    await self._send_response(writer, 409 if code == 'stale_cursor' else 400, {'error': code})
                    return
                await self._send_response(writer, 200, page)
            else:
                await self._send_response(writer, 404, {"error": "Not found"})
        except Exception:
            logger.exception("Unhandled error while processing request")
            try:
                await self._send_response(writer, 500, {"error": "Internal server error"})
            except Exception:
                pass
        finally:
            self._active_connections = max(0, self._active_connections - 1)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
