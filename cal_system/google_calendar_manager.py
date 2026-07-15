#!/usr/bin/env python3
"""
Google Calendar Manager for Inebotten
Integrates with Google Calendar API to sync events
"""

import asyncio
import inspect
import json
import os
import sys
import subprocess
import tempfile
import threading
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.dispatch_result import (
    ExternalCommitState,
    ExternalMutationResult,
)
from core.mutation_coordinator import MutationCoordinator
from utils.json_storage import write_json_atomic

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for Python < 3.9
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        # Last resort: simplified mock or dateutil
        from dateutil.tz import gettz
        class ZoneInfo:
            def __new__(cls, name):
                return gettz(name)

# Suppress requests/urllib3 version warnings
warnings.filterwarnings("ignore", category=UserWarning, module="requests")

# Add the google-workspace skill scripts to path
SKILL_PATH = (
    Path.home() / ".hermes" / "skills" / "productivity" / "google-workspace" / "scripts"
)
if str(SKILL_PATH) not in sys.path:
    sys.path.insert(0, str(SKILL_PATH))

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_MISSING = object()

# OAuth material is shared process state.  Provider event calls deliberately do
# not take this lock once credentials have been materialized.
_CREDENTIAL_LOCK = threading.RLock()
_THREAD_STATE = threading.local()


def _reset_mutation_state() -> None:
    _THREAD_STATE.mutation_state = ExternalCommitState.UNCHANGED
    _THREAD_STATE.mutation_error_code = None


def _exception_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    status = status or getattr(response, "status_code", None)
    response = getattr(exc, "resp", None)
    status = status or getattr(response, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _record_mutation_exception(exc: BaseException) -> None:
    status = _exception_status(exc)
    if status in {400, 401, 403, 404, 409, 410, 422}:
        _THREAD_STATE.mutation_state = ExternalCommitState.UNCHANGED
        _THREAD_STATE.mutation_error_code = (
            "external_not_found" if status in {404, 410} else "external_rejected"
        )
    elif getattr(_THREAD_STATE, "mutation_state", None) is ExternalCommitState.UNKNOWN:
        _THREAD_STATE.mutation_error_code = "external_commit_unknown"
    else:
        _THREAD_STATE.mutation_state = ExternalCommitState.UNCHANGED
        _THREAD_STATE.mutation_error_code = "external_preflight_failed"


class ExternalOperationCancelled(asyncio.CancelledError):
    """Outer cancellation observed after a blocking external call settled."""

    def __init__(self, result: ExternalMutationResult):
        self.result = result
        super().__init__(result.error_code or "external_operation_cancelled")


def get_hermes_home() -> Path:
    """Return the base directory for Inebotten's persistent local state."""
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def _configured_path(env_name: str) -> Path | None:
    raw_path = os.getenv(env_name)
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def get_google_token_path() -> Path:
    """Return the OAuth token path, preserving the historical fallback path."""
    configured = _configured_path("GCAL_TOKEN_PATH")
    if configured:
        return configured

    token_path = get_hermes_home() / "google_token.json"
    if token_path.exists():
        return token_path

    # Backwards compatibility for very old local setups that placed the token
    # next to the project checkout instead of under HERMES_HOME.
    alt_path = Path(__file__).parent.parent.parent.parent / "google_token.json"
    if alt_path.exists():
        return alt_path
    return token_path


def get_google_credentials_path() -> Path:
    """Return the OAuth client secrets path used to start new auth flows."""
    configured = _configured_path("GCAL_CREDENTIALS_PATH")
    if configured:
        return configured
    return get_hermes_home() / "credentials.json"


def get_console_public_url() -> str:
    """Return the externally reachable console URL used in setup guidance."""
    raw_url = (
        os.getenv("CONSOLE_PUBLIC_URL")
        or os.getenv("WEB_CONSOLE_PUBLIC_URL")
        or "https://bot.reidar.tech"
    )
    return raw_url.strip().rstrip("/") or "https://bot.reidar.tech"


def get_gcal_setup_url() -> str:
    """Return the protected web-console page for Google Calendar setup."""
    return f"{get_console_public_url()}/gcal-auth"


def get_google_credentials_status() -> dict[str, Any]:
    """Return non-secret status for the Google OAuth client credentials file."""
    credentials_path = get_google_credentials_path()
    return {
        "configured": credentials_path.exists(),
        "path": str(credentials_path),
        "directory": str(credentials_path.parent),
        "setup_url": get_gcal_setup_url(),
    }


def missing_google_credentials_message(credentials_path: Path | None = None) -> str:
    """Return user-facing setup guidance without requiring direct VPS access."""
    path = credentials_path or get_google_credentials_path()
    return (
        f"Fant ikke `credentials.json` i {path.parent}. "
        f"Åpne {get_gcal_setup_url()} i webkonsollen, lim inn OAuth 2.0 "
        "Client ID JSON for `Desktop app`, og lagre. Kjør deretter "
        "`@inebotten kalender auth` på nytt."
    )


def _normalize_client_credentials(raw_credentials: str | dict[str, Any]) -> tuple[bool, dict[str, Any] | str]:
    if isinstance(raw_credentials, str):
        if not raw_credentials.strip():
            return False, "Lim inn innholdet fra Google OAuth client JSON-filen."
        try:
            credentials = json.loads(raw_credentials)
        except json.JSONDecodeError as exc:
            return False, f"Ugyldig JSON: {exc.msg}"
    elif isinstance(raw_credentials, dict):
        credentials = raw_credentials
    else:
        return False, "Credentials må sendes som JSON eller tekst."

    installed = credentials.get("installed") if isinstance(credentials, dict) else None
    if not isinstance(installed, dict):
        if isinstance(credentials, dict) and isinstance(credentials.get("web"), dict):
            return False, (
                "Dette ser ut som en `Web application`-client. "
                "Opprett en OAuth Client ID av typen `Desktop app` i Google Cloud."
            )
        return False, (
            "JSON-en må være en Google OAuth 2.0 Client ID for `Desktop app` "
            "og inneholde et `installed`-objekt."
        )

    required_fields = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [field for field in required_fields if not installed.get(field)]
    if missing:
        return False, "OAuth JSON mangler påkrevde felt: " + ", ".join(missing)

    return True, credentials


def save_google_client_credentials(raw_credentials: str | dict[str, Any]) -> tuple[bool, str]:
    """Validate and store Google OAuth client credentials with private file mode."""
    ok, normalized_or_error = _normalize_client_credentials(raw_credentials)
    if not ok:
        return False, str(normalized_or_error)

    credentials_path = get_google_credentials_path()
    try:
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.parent.chmod(0o700)
        write_json_atomic(credentials_path, normalized_or_error)
        credentials_path.chmod(0o600)
    except Exception:
        return False, "Klarte ikke lagre OAuth-klienten. Prøv igjen."

    return True, (
        "OAuth-klienten er lagret. Kjør `@inebotten kalender auth` på nytt "
        "for å hente Google-innloggingslenken."
    )


# Kept for compatibility with older imports/tests; manager instances resolve
# these paths dynamically so env changes and Docker mounts are respected.
HERMES_HOME = get_hermes_home()
TOKEN_PATH = get_google_token_path()
CREDENTIALS_PATH = get_google_credentials_path()


class GoogleCalendarManager:
    """
    Manages Google Calendar integration for the Discord bot
    """

    def __init__(
        self,
        *,
        mutation_coordinator: MutationCoordinator | None = None,
        token_path: str | Path | None = None,
        credentials_path: str | Path | None = None,
        calendar_id: str | None = None,
    ):
        """Create an offline manager without touching OAuth or the network.

        ``initialize_result`` is the sole startup boundary that reads,
        refreshes, or persists token material.  Keeping construction inert is
        important because the monitor wires one shared instance into multiple
        domain managers before startup I/O begins.
        """
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        if calendar_id is not None:
            self.calendar_id = calendar_id
        self.hermes_home = get_hermes_home()
        self.token_path = Path(token_path) if token_path is not None else get_google_token_path()
        self.credentials_path = (
            Path(credentials_path)
            if credentials_path is not None
            else get_google_credentials_path()
        )
        self.mutation_coordinator = mutation_coordinator or MutationCoordinator()
        self._enabled = False
        self._initialized = False
        self._auth_flow = None
        self._auth_flow_state = None

    @property
    def enabled(self) -> bool:
        """Current validated configuration state; never cached by consumers."""
        return bool(getattr(self, "_enabled", False))

    @enabled.setter
    def enabled(self, value: bool) -> None:
        # Old tests and third-party callers sometimes create the object via
        # ``__new__`` and seed it manually.  Real constructed instances expose
        # a read-only property so runtime code cannot fabricate auth state.
        if getattr(self, "_initialized", None) is not None:
            raise AttributeError("enabled_is_read_only")
        self._enabled = bool(value)

    def _token_path(self) -> Path:
        if hasattr(self, "token_path"):
            return self.token_path
        return get_google_token_path()

    def _credentials_path(self) -> Path:
        if hasattr(self, "credentials_path"):
            return self.credentials_path
        return get_google_credentials_path()

    def _check_auth(self):
        """Materialize credentials under the process-wide credential lock.

        This synchronous helper is invoked only through an owned worker task.
        It intentionally returns structured truth and never logs credential or
        exception details.
        """
        token_path = self._token_path()
        if not token_path.exists():
            self._enabled = False
            self._initialized = True
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="not_configured",
            )
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            with _CREDENTIAL_LOCK:
                try:
                    creds = Credentials.from_authorized_user_file(
                        str(token_path), SCOPES
                    )
                except Exception:
                    self._enabled = False
                    self._initialized = True
                    return ExternalMutationResult(
                        False,
                        ExternalCommitState.UNCHANGED,
                        error_code="invalid_credentials",
                    )
                if creds.valid:
                    self._enabled = True
                    self._initialized = True
                    return ExternalMutationResult(
                        True,
                        ExternalCommitState.UNCHANGED,
                        value=True,
                    )
                if creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        self._enabled = False
                        self._initialized = True
                        return ExternalMutationResult(
                            False,
                            ExternalCommitState.UNKNOWN,
                            error_code="external_commit_unknown",
                        )
                    try:
                        self._save_credentials(creds)
                    except Exception:
                        self._enabled = False
                        self._initialized = True
                        return ExternalMutationResult(
                            False,
                            ExternalCommitState.CHANGED,
                            error_code="token_storage_failed",
                        )
                    self._enabled = True
                    self._initialized = True
                    return ExternalMutationResult(
                        True,
                        ExternalCommitState.CHANGED,
                        value=True,
                    )
                self._enabled = False
                self._initialized = True
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="invalid_credentials",
                )
        except Exception:
            self._enabled = False
            self._initialized = True
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="credential_dependency_unavailable",
            )

    def _save_credentials(self, creds):
        """Atomically persist a complete, private OAuth token document."""
        with _CREDENTIAL_LOCK:
            token_path = self._token_path()
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.parent.chmod(0o700)
            serialized = creds.to_json()
            # Match the minimum document accepted by
            # ``Credentials.from_authorized_user_info`` before replacing a
            # previously valid token.  Merely parseable JSON (``null``, ``[]``
            # or ``{}``) is not a usable authorized-user document.
            document = json.loads(serialized)
            required = ("refresh_token", "client_id", "client_secret")
            if not isinstance(document, dict) or any(
                not isinstance(document.get(field), str)
                or not document[field].strip()
                for field in required
            ):
                raise ValueError("invalid_authorized_user_document")
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{token_path.name}.",
                suffix=".tmp",
                dir=str(token_path.parent),
                text=True,
            )
            temp_path = Path(temp_name)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as token:
                    token.write(serialized)
                    token.flush()
                    os.fsync(token.fileno())
                os.replace(temp_path, token_path)
                token_path.chmod(0o600)
                directory_fd = os.open(token_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)

    def is_configured(self):
        """Return True if Google Calendar is configured and ready"""
        return self.enabled

    async def initialize_result(self) -> ExternalMutationResult:
        return await self._await_worker(self._check_auth)

    async def refresh_configuration_result(self) -> ExternalMutationResult:
        return await self._await_worker(self._check_auth)

    @staticmethod
    async def _await_worker(callable_, /, *args, **kwargs):
        """Shield one blocking operation and settle it before propagating cancel."""
        worker = asyncio.create_task(asyncio.to_thread(callable_, *args, **kwargs))
        outer_cancelled = False
        while True:
            try:
                result = await asyncio.shield(worker)
                break
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is None or current.cancelling() == 0:
                    # The owned worker cancelled independently.  This is an
                    # UNKNOWN external result, not caller cancellation.
                    result = ExternalMutationResult(
                        False,
                        ExternalCommitState.UNKNOWN,
                        error_code="external_commit_unknown",
                    )
                    break
                outer_cancelled = True
                current.uncancel()
                if worker.done():
                    # Cancellation was observed even if the worker completed in
                    # the same loop turn; settle its exact result below.
                    try:
                        result = worker.result()
                    except asyncio.CancelledError:
                        result = ExternalMutationResult(
                            False,
                            ExternalCommitState.UNKNOWN,
                            error_code="external_commit_unknown",
                        )
                    except Exception:
                        result = ExternalMutationResult(
                            False,
                            ExternalCommitState.UNKNOWN,
                            error_code="external_commit_unknown",
                        )
                    break
                continue
            except Exception:
                if not outer_cancelled:
                    raise
                result = ExternalMutationResult(
                    False,
                    ExternalCommitState.UNKNOWN,
                    error_code="external_commit_unknown",
                )
                break
        if outer_cancelled:
            if not isinstance(result, ExternalMutationResult):
                if (
                    isinstance(result, tuple)
                    and len(result) == 2
                    and isinstance(result[1], ExternalCommitState)
                ):
                    value, state = result
                    result = ExternalMutationResult(
                        value is not None,
                        state,
                        value=value,
                        error_code=(None if value is not None else "external_read_failed"),
                    )
                elif result is True or (
                    isinstance(result, dict) and result.get("id")
                ):
                    result = ExternalMutationResult(
                        True,
                        ExternalCommitState.CHANGED,
                        value=result,
                    )
                else:
                    result = ExternalMutationResult(
                        False,
                        ExternalCommitState.UNKNOWN,
                        error_code="external_commit_unknown",
                    )
            raise ExternalOperationCancelled(result)
        return result

    def _get_auth_url_result_sync(
        self,
        requester_id=None,
        channel_id=None,
        ttl_seconds=900,
    ) -> ExternalMutationResult:
        """Generate one requester/channel-bound OAuth flow."""
        from google_auth_oauthlib.flow import InstalledAppFlow
        client_secrets_file = self._credentials_path()

        if not client_secrets_file.exists():
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                value=missing_google_credentials_message(client_secrets_file),
                error_code="missing_credentials",
            )

        try:
            with _CREDENTIAL_LOCK:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secrets_file),
                    SCOPES,
                )
                flow.redirect_uri = "http://localhost:8080"
                auth_url, _ = flow.authorization_url(
                    prompt="consent", access_type="offline"
                )
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=max(60, ttl_seconds)
                )
                self._auth_flow = flow
                self._auth_flow_state = {
                    "requester_id": (
                        str(requester_id) if requester_id is not None else None
                    ),
                    "channel_id": str(channel_id) if channel_id is not None else None,
                    "expires_at": expires_at.isoformat(),
                }
            return ExternalMutationResult(
                True,
                ExternalCommitState.CHANGED,
                value=auth_url,
            )
        except Exception:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="auth_flow_failed",
            )

    async def get_auth_url_result(
        self,
        requester_id=None,
        channel_id=None,
        ttl_seconds=900,
    ) -> ExternalMutationResult:
        return await self._await_worker(
            self._get_auth_url_result_sync,
            requester_id,
            channel_id,
            ttl_seconds,
        )

    def get_auth_url(self, requester_id=None, channel_id=None, ttl_seconds=900):
        """Legacy ``(ok, message_or_url)`` projection."""
        result = self._get_auth_url_result_sync(
            requester_id,
            channel_id,
            ttl_seconds,
        )
        value = result.value if isinstance(result.value, str) else "Kunne ikke starte pålogging."
        return result.ok, value

    @staticmethod
    def _auth_error_message(error_code: str | None) -> str:
        messages = {
            "missing_auth_flow": "Ingen aktiv påloggingsøkt funnet. Vennligst kjør `@inebotten kalender auth` først for å få en ny lenke, og prøv igjen med den nye koden.",
            "auth_flow_expired": "Påloggingsøkten er utløpt. Kjør `@inebotten kalender auth` på nytt.",
            "invalid_auth_flow": "Påloggingsøkten var ugyldig. Kjør `@inebotten kalender auth` på nytt.",
            "requester_mismatch": "Denne kalenderkoden hører til en annen påloggingsøkt.",
            "channel_mismatch": "Denne kalenderkoden må sendes i samme kanal som startet påloggingen.",
            "token_storage_failed": "Google godkjente koden, men tokenet kunne ikke lagres. Start en ny påloggingsøkt.",
            "external_commit_unknown": "Det er uklart om Google godkjente koden. Start en ny påloggingsøkt før du prøver igjen.",
        }
        return messages.get(error_code, "Autentisering feilet. Start en ny påloggingsøkt.")

    def _exchange_code_result_sync(
        self,
        code,
        requester_id=None,
        channel_id=None,
    ) -> ExternalMutationResult:
        """Exchange one code, clearing the flow after dispatch regardless of truth."""
        prior_enabled = self.enabled
        with _CREDENTIAL_LOCK:
            flow = getattr(self, "_auth_flow", None)
            if flow is None:
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="missing_auth_flow",
                )

            state = getattr(self, "_auth_flow_state", {}) or {}
            expires_at = state.get("expires_at")
            if expires_at:
                try:
                    if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                        self._auth_flow = None
                        self._auth_flow_state = None
                        return ExternalMutationResult(
                            False,
                            ExternalCommitState.UNCHANGED,
                            error_code="auth_flow_expired",
                        )
                except Exception:
                    self._auth_flow = None
                    self._auth_flow_state = None
                    return ExternalMutationResult(
                        False,
                        ExternalCommitState.UNCHANGED,
                        error_code="invalid_auth_flow",
                    )

            expected_requester = state.get("requester_id")
            expected_channel = state.get("channel_id")
            if expected_requester and str(requester_id) != expected_requester:
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="requester_mismatch",
                )
            if expected_channel and str(channel_id) != expected_channel:
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="channel_mismatch",
                )

            # Claim before network I/O. A concurrent exchange can no longer
            # consume the same flow, and a new auth URL installed afterwards
            # cannot be cleared by this exchange's settlement.
            self._auth_flow = None
            self._auth_flow_state = None

        try:
            with _CREDENTIAL_LOCK:
                flow.fetch_token(code=code)
                creds = flow.credentials
                try:
                    self._save_credentials(creds)
                except Exception:
                    # Atomic token persistence leaves any previously validated
                    # token untouched.  A failed re-auth must not disable that
                    # still-working integration.
                    self._enabled = prior_enabled
                    self._initialized = True
                    return ExternalMutationResult(
                        False,
                        ExternalCommitState.CHANGED,
                        error_code="token_storage_failed",
                    )
            self._enabled = True
            self._initialized = True
            return ExternalMutationResult(
                True,
                ExternalCommitState.CHANGED,
                value="Autentisering vellykket! Google Calendar er nå synkronisert og klar til bruk.",
            )
        except Exception as exc:
            # Invalid/failed re-auth consumes this one-time flow, but it does
            # not revoke or overwrite an already validated persisted token.
            self._enabled = prior_enabled
            self._initialized = True
            oauth_error = getattr(exc, "error", None)
            if _exception_status(exc) in {400, 401, 403, 404} or oauth_error == "invalid_grant":
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="invalid_auth_code",
                )
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNKNOWN,
                error_code="external_commit_unknown",
            )

    async def exchange_code_result(
        self,
        code,
        requester_id=None,
        channel_id=None,
    ) -> ExternalMutationResult:
        return await self._await_worker(
            self._exchange_code_result_sync,
            code,
            requester_id,
            channel_id,
        )

    def exchange_code(self, code, requester_id=None, channel_id=None):
        """Legacy ``(ok, message)`` projection."""
        result = self._exchange_code_result_sync(code, requester_id, channel_id)
        if result.ok and isinstance(result.value, str):
            return True, result.value
        return False, self._auth_error_message(result.error_code)

    def _run_calendar_command(self, *args):
        """Run a calendar command via the google_api.py script"""
        script_path = SKILL_PATH / "google_api.py"
        cmd = [sys.executable, str(script_path), "calendar"] + list(args)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print("[GCAL] Calendar command failed")
                return None
            return json.loads(result.stdout) if result.stdout.strip() else None
        except Exception:
            print("[GCAL] Calendar command failed")
            return None

    def list_upcoming_events(self, days=30, *, reference_time=None):
        """
        List upcoming events from Google Calendar using direct API.

        Args:
            days: Number of days to look ahead

        Returns:
            List of event dicts or None if error
        """
        if not self.enabled:
            return None

        _THREAD_STATE.read_credential_state = ExternalCommitState.UNCHANGED
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            with _CREDENTIAL_LOCK:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path()), SCOPES
                )
                if creds.expired and creds.refresh_token:
                    try:
                        _THREAD_STATE.read_credential_state = ExternalCommitState.UNKNOWN
                        creds.refresh(Request())
                        self._save_credentials(creds)
                        _THREAD_STATE.read_credential_state = ExternalCommitState.CHANGED
                    except Exception:
                        _THREAD_STATE.read_credential_state = ExternalCommitState.UNKNOWN
                        raise

            service = build("calendar", "v3", credentials=creds)

            if reference_time is None:
                now = datetime.now(timezone.utc)
            else:
                if (
                    reference_time.tzinfo is None
                    or reference_time.utcoffset() is None
                ):
                    raise ValueError("reference_time_must_be_aware")
                now = reference_time.astimezone(timezone.utc)
            end = now + timedelta(days=days)

            items = []
            page_token = None
            while True:
                events_result = service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    maxResults=2500,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                ).execute()
                items.extend(events_result.get("items", []))
                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break
            return items

        except Exception:
            print("[GCAL] Event listing failed")
            return None

    def get_event(self, event_id):
        """Fetch a single event by ID; returns None if missing or unavailable."""
        if not self.enabled:
            return None

        _THREAD_STATE.read_credential_state = ExternalCommitState.UNCHANGED
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            with _CREDENTIAL_LOCK:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path()), SCOPES
                )
                if creds.expired and creds.refresh_token:
                    try:
                        _THREAD_STATE.read_credential_state = ExternalCommitState.UNKNOWN
                        creds.refresh(Request())
                        self._save_credentials(creds)
                        _THREAD_STATE.read_credential_state = ExternalCommitState.CHANGED
                    except Exception:
                        _THREAD_STATE.read_credential_state = ExternalCommitState.UNKNOWN
                        raise

            service = build("calendar", "v3", credentials=creds)
            return (
                service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )
        except Exception:
            print("[GCAL] Event lookup failed")
            return None

    def create_event(
        self,
        title,
        start_time,
        end_time=None,
        description=None,
        location=None,
        attendees=None,
        recurrence=None,
        rrule_day=None,
        discord_user_id=None,
        discord_username=None,
    ):
        """
        Create a new event in Google Calendar

        Args:
            title: Event title/summary
            start_time: ISO 8601 datetime string (with timezone)
            end_time: ISO 8601 datetime string (optional, defaults to 1 hour after start)
            description: Optional event description
            location: Optional location string
            attendees: Optional comma-separated list of email addresses
            recurrence: Optional recurrence rule ('weekly', 'biweekly', 'monthly', 'yearly')
            rrule_day: Optional specific day for weekly recurrence (e.g., 'MO', 'TU')

        Returns:
            Event dict with id and htmlLink, or None if error
        """
        _reset_mutation_state()
        if not self.enabled:
            _THREAD_STATE.mutation_error_code = "integration_disabled"
            return None

        # Calculate end time if not provided (default 1 hour duration)
        if end_time is None:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = start_dt + timedelta(hours=1)
                end_time = end_dt.isoformat()
            except Exception:
                print("[CALENDAR] GCal datetime parse error")
                return None

        # Build recurrence rule if specified
        rrule = None
        if recurrence:
            rrule = self._build_rrule(recurrence, rrule_day)

        # Use direct API for all events (ensures timezone support)
        return self._create_event_api(
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            rrule=rrule,
            discord_user_id=discord_user_id,
            discord_username=discord_username,
        )

    def _create_event_api(
        self, title, start_time, end_time, description=None, location=None, rrule=None,
        discord_user_id=None, discord_username=None
    ):
        """
        Create an event using direct Google Calendar API (handles both recurring and non-recurring)
        """
        _reset_mutation_state()
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            with _CREDENTIAL_LOCK:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path()), SCOPES
                )
                if creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        print("[GCAL] Token refresh failed during event creation")
                        self._enabled = False
                        return None
                    self._save_credentials(creds)
                elif not creds.valid:
                    print("[GCAL] Credentials invalid (no refresh token)")
                    self._enabled = False
                    _THREAD_STATE.mutation_state = ExternalCommitState.UNCHANGED
                    _THREAD_STATE.mutation_error_code = "invalid_credentials"
                    return None

            service = build("calendar", "v3", credentials=creds)

            # Build event body
            event_body = {
                "summary": title,
                "start": {"dateTime": start_time, "timeZone": "Europe/Oslo"},
                "end": {"dateTime": end_time, "timeZone": "Europe/Oslo"},
            }

            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if rrule:
                event_body["recurrence"] = [rrule]
            
            # Add Discord metadata to extended properties
            if discord_user_id or discord_username:
                event_body["extendedProperties"] = {
                    "private": {
                        "discord_user_id": str(discord_user_id) if discord_user_id else "",
                        "discord_username": discord_username or ""
                    }
                }

            _THREAD_STATE.mutation_state = ExternalCommitState.UNKNOWN
            result = (
                service.events()
                .insert(calendarId=self.calendar_id, body=event_body)
                .execute()
            )
            if not isinstance(result, dict) or not result.get("id"):
                _THREAD_STATE.mutation_state = ExternalCommitState.UNKNOWN
                _THREAD_STATE.mutation_error_code = "external_commit_unknown"
                return None
            normalized = {
                "status": "created",
                "id": result["id"],
                "summary": result.get("summary", ""),
                "htmlLink": result.get("htmlLink", ""),
            }
            _THREAD_STATE.mutation_state = ExternalCommitState.CHANGED
            _THREAD_STATE.mutation_error_code = None
            return normalized

        except Exception as exc:
            _record_mutation_exception(exc)
            print("[GCAL] Event creation failed")
            return None

    def delete_event(self, event_id):
        """
        Delete an event from Google Calendar

        Args:
            event_id: The Google Calendar event ID

        Returns:
            True if successful, False otherwise
        """
        _reset_mutation_state()
        if not self.enabled:
            _THREAD_STATE.mutation_error_code = "integration_disabled"
            return False

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            with _CREDENTIAL_LOCK:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path()), SCOPES
                )
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)
            _THREAD_STATE.mutation_state = ExternalCommitState.UNKNOWN
            service.events().delete(
                calendarId=self.calendar_id, eventId=event_id
            ).execute()
            _THREAD_STATE.mutation_state = ExternalCommitState.CHANGED
            _THREAD_STATE.mutation_error_code = None
            return True
        except Exception as exc:
            _record_mutation_exception(exc)
            print("[GCAL] Event deletion failed")
            return False

    def _build_rrule(self, recurrence, rrule_day=None):
        if not recurrence:
            return None
        recurrence = recurrence.lower()
        if recurrence == "daily":
            return "RRULE:FREQ=DAILY"
        if recurrence == "weekly":
            return f"RRULE:FREQ=WEEKLY;BYDAY={rrule_day}" if rrule_day else "RRULE:FREQ=WEEKLY"
        if recurrence == "biweekly":
            return f"RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY={rrule_day}" if rrule_day else "RRULE:FREQ=WEEKLY;INTERVAL=2"
        if recurrence == "monthly":
            return "RRULE:FREQ=MONTHLY"
        if recurrence == "yearly":
            return "RRULE:FREQ=YEARLY"
        return None

    def _local_event_times(self, date_str, time_str=None):
        day, month, year = date_str.split(".")
        hour, minute = (time_str or "12:00").split(":")
        local_tz = ZoneInfo("Europe/Oslo")
        start_dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), tzinfo=local_tz
        )
        end_dt = start_dt + timedelta(hours=1)
        return start_dt.isoformat(), end_dt.isoformat()

    def update_event(
        self,
        event_id,
        title=None,
        description=None,
        completed=False,
        date_str=None,
        time_str=None,
        recurrence=_MISSING,
        rrule_day=None,
    ):
        """
        Update an event in Google Calendar
        """
        _reset_mutation_state()
        if not self.enabled:
            _THREAD_STATE.mutation_error_code = "integration_disabled"
            return None

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            with _CREDENTIAL_LOCK:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path()), SCOPES
                )
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    self._save_credentials(creds)

            service = build("calendar", "v3", credentials=creds)

            # Get existing event
            event = (
                service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )

            # Update fields
            if title:
                event["summary"] = title
            
            if completed and not event["summary"].endswith(" [FERDIG]"):
                event["summary"] += " [FERDIG]"
            
            if description:
                event["description"] = description

            if date_str:
                start_iso, end_iso = self._local_event_times(date_str, time_str)
                event["start"] = {"dateTime": start_iso, "timeZone": "Europe/Oslo"}
                event["end"] = {"dateTime": end_iso, "timeZone": "Europe/Oslo"}

            if recurrence is not _MISSING:
                rrule = self._build_rrule(recurrence, rrule_day)
                if rrule:
                    event["recurrence"] = [rrule]
                else:
                    event.pop("recurrence", None)

            _THREAD_STATE.mutation_state = ExternalCommitState.UNKNOWN
            result = (
                service.events()
                .update(calendarId=self.calendar_id, eventId=event_id, body=event)
                .execute()
            )
            if not isinstance(result, dict) or not result.get("id"):
                _THREAD_STATE.mutation_state = ExternalCommitState.UNKNOWN
                _THREAD_STATE.mutation_error_code = "external_commit_unknown"
                return None
            _THREAD_STATE.mutation_state = ExternalCommitState.CHANGED
            _THREAD_STATE.mutation_error_code = None

            return result
        except Exception as exc:
            _record_mutation_exception(exc)
            print("[GCAL] Event update failed")
            return None

    async def list_upcoming_events_result(
        self,
        days=30,
        *,
        reference_time=None,
    ) -> ExternalMutationResult:
        if not self.enabled:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="integration_disabled",
            )
        if reference_time is not None and (
            reference_time.tzinfo is None
            or reference_time.utcoffset() is None
        ):
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="invalid_reference_time",
            )
        def _read():
            _THREAD_STATE.read_credential_state = ExternalCommitState.UNCHANGED
            legacy_read = self.list_upcoming_events
            try:
                parameters = inspect.signature(legacy_read).parameters.values()
            except (TypeError, ValueError):
                parameters = ()
            supports_reference = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                or parameter.name == "reference_time"
                for parameter in parameters
            )
            if supports_reference:
                value = legacy_read(
                    days,
                    reference_time=reference_time,
                )
            else:
                value = legacy_read(days)
            return value, getattr(
                _THREAD_STATE,
                "read_credential_state",
                ExternalCommitState.UNCHANGED,
            )

        settled = await self._await_worker(_read)
        if isinstance(settled, ExternalMutationResult):
            return settled
        value, credential_state = settled
        if not isinstance(value, list):
            return ExternalMutationResult(
                False,
                credential_state,
                error_code="external_read_failed",
            )
        return ExternalMutationResult(
            True,
            credential_state,
            value=value,
        )

    async def get_event_result(self, event_id) -> ExternalMutationResult:
        if not self.enabled or not isinstance(event_id, str) or not event_id.strip():
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code=(
                    "integration_disabled" if not self.enabled else "invalid_event_id"
                ),
            )
        def _read():
            _THREAD_STATE.read_credential_state = ExternalCommitState.UNCHANGED
            value = self.get_event(event_id)
            return value, getattr(
                _THREAD_STATE,
                "read_credential_state",
                ExternalCommitState.UNCHANGED,
            )

        settled = await self._await_worker(_read)
        if isinstance(settled, ExternalMutationResult):
            return settled
        value, credential_state = settled
        if not isinstance(value, dict):
            return ExternalMutationResult(
                False,
                credential_state,
                error_code="external_read_failed",
            )
        return ExternalMutationResult(
            True,
            credential_state,
            value=value,
        )

    async def _legacy_mutation_result(
        self,
        method,
        *args,
        expected: str,
    ) -> ExternalMutationResult:
        def _call():
            _reset_mutation_state()
            try:
                value = method(*args)
            except Exception as exc:
                _record_mutation_exception(exc)
                value = None
            state = getattr(
                _THREAD_STATE,
                "mutation_state",
                ExternalCommitState.UNCHANGED,
            )
            error_code = getattr(
                _THREAD_STATE,
                "mutation_error_code",
                None,
            )
            valid = (
                value is True
                if expected == "bool"
                else isinstance(value, dict) and bool(value.get("id"))
            )
            if valid:
                return ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    value=value,
                )
            if error_code is None:
                state = ExternalCommitState.UNKNOWN
                error_code = "external_commit_unknown"
            return ExternalMutationResult(
                False,
                state,
                error_code=error_code,
            )

        return await self._await_worker(_call)

    async def create_event_result(
        self,
        title,
        start_time,
        end_time=None,
        description=None,
        location=None,
        attendees=None,
        recurrence=None,
        rrule_day=None,
        discord_user_id=None,
        discord_username=None,
    ) -> ExternalMutationResult:
        if not self.enabled:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="integration_disabled",
            )
        if not isinstance(title, str) or not title.strip():
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="invalid_event",
            )
        try:
            datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="invalid_event",
            )
        return await self._legacy_mutation_result(
            self.create_event,
            title,
            start_time,
            end_time,
            description,
            location,
            attendees,
            recurrence,
            rrule_day,
            discord_user_id,
            discord_username,
            expected="dict",
        )

    async def update_event_result(
        self,
        event_id,
        title=None,
        description=None,
        completed=False,
        date_str=None,
        time_str=None,
        recurrence=_MISSING,
        rrule_day=None,
    ) -> ExternalMutationResult:
        if not self.enabled:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="integration_disabled",
            )
        if not isinstance(event_id, str) or not event_id.strip():
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="invalid_event_id",
            )
        return await self._legacy_mutation_result(
            self.update_event,
            event_id,
            title,
            description,
            completed,
            date_str,
            time_str,
            recurrence,
            rrule_day,
            expected="dict",
        )

    async def delete_event_result(self, event_id) -> ExternalMutationResult:
        if not self.enabled:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="integration_disabled",
            )
        if not isinstance(event_id, str) or not event_id.strip():
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNCHANGED,
                error_code="invalid_event_id",
            )
        return await self._legacy_mutation_result(
            self.delete_event,
            event_id,
            expected="bool",
        )

    def sync_local_event(self, event_data):
        """
        Sync a local bot event to Google Calendar

        Args:
            event_data: Dict with title, date (DD.MM.YYYY), time (HH:MM), description

        Returns:
            Created event dict or None
        """
        if not self.enabled:
            return None

        try:
            # Parse date and time
            date_str = event_data.get("date", "")  # DD.MM.YYYY
            time_str = event_data.get("time") or "12:00"  # HH:MM

            # Parse date
            day, month, year = date_str.split(".")
            hour, minute = time_str.split(":")

            # Create datetime in local timezone (assume Europe/Oslo for Norway)
            from zoneinfo import ZoneInfo

            local_tz = ZoneInfo("Europe/Oslo")

            start_dt = datetime(
                int(year), int(month), int(day), int(hour), int(minute), tzinfo=local_tz
            )
            end_dt = start_dt + timedelta(hours=1)

            # Convert to ISO format with timezone
            start_iso = start_dt.isoformat()
            end_iso = end_dt.isoformat()

            return self.create_event(
                title=event_data.get("title", "Untitled"),
                start_time=start_iso,
                end_time=end_iso,
                description=event_data.get("description", ""),
                recurrence=event_data.get("recurrence"),
                rrule_day=event_data.get("rrule_day"),
                discord_user_id=event_data.get("user_id"),
                discord_username=event_data.get("username"),
            )

        except Exception:
            print("[GCAL] Event sync failed")
            return None

    def format_event_list(self, events, title="Google Calendar - Kommende"):
        """
        Format a list of Google Calendar events for display
        """
        if not events:
            return f"📅 **{title}**\nIngen arrangementer funnet."

        lines = [f"📅 **{title}**", ""]

        for event in events[:10]:  # Show max 10
            summary = event.get("summary", "(ingen tittel)")
            start = event.get("start", "")
            location = event.get("location", "")
            link = event.get("htmlLink", "")

            # Parse datetime - start can be a dict or string
            try:
                if isinstance(start, dict):
                    if "dateTime" in start:
                        dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
                        from zoneinfo import ZoneInfo
                        local_dt = dt.astimezone(ZoneInfo("Europe/Oslo"))
                        date_str = local_dt.strftime("%d.%m.%Y")
                        time_str = local_dt.strftime("%H:%M")
                        time_display = f" kl. {time_str}"
                    else:
                        date_str = start.get("date", start)
                        time_display = ""
                elif isinstance(start, str) and "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    from zoneinfo import ZoneInfo
                    local_dt = dt.astimezone(ZoneInfo("Europe/Oslo"))
                    date_str = local_dt.strftime("%d.%m.%Y")
                    time_str = local_dt.strftime("%H:%M")
                    time_display = f" kl. {time_str}"
                else:
                    # date-only format
                    date_str = start
                    time_display = ""
            except Exception:
                print("[CALENDAR] GCal parse error")
                date_str = start
                time_display = ""

            lines.append(f"📌 **{summary}** - {date_str}{time_display}")

            if location:
                lines.append(f"   📍 {location}")

            if link:
                lines.append(f"   🔗 {link}")

            lines.append("")

        return "\n".join(lines)

    def get_setup_instructions(self):
        """Get instructions for setting up Google Calendar integration"""
        return """🔧 **Google Calendar-oppsett**

For å koble boten til Google Calendar:

1. Gå til https://console.cloud.google.com/apis/credentials
2. Opprett et prosjekt (eller bruk et eksisterende)
3. Klikk "Enable APIs" og skru på: Google Calendar API
4. Gå til Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: "Desktop app" → Create
6. Last ned JSON-filen og gi meg filbanen

Deretter kjører vi setup-scriptet for å autorisere.
"""


def parse_google_calendar_command(message_content):
    """
    Parse Google Calendar commands from message

    Commands:
    - "google calendar" or "gcal" - list upcoming events
    - "sync til google" - sync local events to Google Calendar

    Returns:
        Command dict or None
    """
    content = message_content.lower()

    # Check for Google Calendar commands
    if any(
        phrase in content for phrase in ["google calendar", "gcal", "google kalender"]
    ):
        if any(word in content for word in ["sync", "synk", "oppdater", "push"]):
            return {"action": "sync"}
        elif any(word in content for word in ["slett", "delete", "fjern"]):
            return {"action": "delete"}
        else:
            return {"action": "list"}

    return None


if __name__ == "__main__":
    # Test the manager
    print("=== Google Calendar Manager Test ===\n")

    manager = GoogleCalendarManager()

    if not manager.is_configured():
        print("Google Calendar er ikke konfigurert ennå.")
        print(manager.get_setup_instructions())
    else:
        print("✅ Google Calendar er konfigurert!")
        print("\nHenter kommende arrangementer...\n")

        events = manager.list_upcoming_events(days=30)
        if events:
            print(manager.format_event_list(events))
        else:
            print("Ingen arrangementer funnet eller feil oppstod.")
