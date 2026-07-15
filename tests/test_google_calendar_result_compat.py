from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cal_system.google_calendar_manager import (
    ExternalOperationCancelled,
    GoogleCalendarManager,
)
from core.dispatch_result import ExternalCommitState, ExternalMutationResult


class ValidCreds:
    valid = True
    expired = False
    refresh_token = "refresh"

    def to_json(self):
        return json.dumps(
            {
                "token": "access",
                "refresh_token": "refresh",
                "client_id": "client",
                "client_secret": "secret",
            }
        )


class RefreshCreds:
    valid = False
    expired = True
    refresh_token = "refresh"

    def refresh(self, request):
        self.valid = True
        self.expired = False

    def to_json(self):
        return ValidCreds().to_json()


def _manager(tmp_path: Path) -> GoogleCalendarManager:
    manager = GoogleCalendarManager(
        token_path=tmp_path / "token.json",
        credentials_path=tmp_path / "credentials.json",
    )
    manager._enabled = True
    manager._initialized = True
    return manager


def test_constructor_is_network_and_credential_io_free(tmp_path):
    with patch.object(GoogleCalendarManager, "_check_auth", side_effect=AssertionError):
        manager = GoogleCalendarManager(
            token_path=tmp_path / "token.json",
            credentials_path=tmp_path / "credentials.json",
        )
    assert manager.enabled is False
    assert not (tmp_path / "token.json").exists()


@pytest.mark.asyncio
async def test_initialize_refreshes_in_place_and_revocation_is_dynamic(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")
    manager = GoogleCalendarManager(token_path=token_path)
    creds = RefreshCreds()
    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=creds,
    ):
        initialized = await manager.initialize_result()
    assert initialized.ok is True
    assert initialized.state is ExternalCommitState.CHANGED
    assert manager.enabled is True
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(token_path.read_text())["token"] == "access"

    token_path.unlink()
    revoked = await manager.refresh_configuration_result()
    assert revoked.ok is False
    assert revoked.state is ExternalCommitState.UNCHANGED
    assert manager.enabled is False


@pytest.mark.asyncio
async def test_structured_create_update_delete_and_read_classification(tmp_path):
    manager = _manager(tmp_path)
    manager.create_event = lambda *args, **kwargs: {"id": "new", "htmlLink": "link"}
    manager.update_event = lambda *args, **kwargs: {"id": "old", "htmlLink": "link"}
    manager.delete_event = lambda *args, **kwargs: True
    manager.list_upcoming_events = lambda *args, **kwargs: [{"id": "one"}]

    created = await manager.create_event_result("Title", "2026-07-16T10:00:00+02:00")
    updated = await manager.update_event_result("old", title="Title")
    deleted = await manager.delete_event_result("old")
    listed = await manager.list_upcoming_events_result(30)

    assert created.ok and created.state is ExternalCommitState.CHANGED
    assert created.value == {"id": "new", "htmlLink": "link"}
    assert updated.ok and updated.state is ExternalCommitState.CHANGED
    assert deleted.ok and deleted.value is True
    assert listed.ok and listed.state is ExternalCommitState.UNCHANGED
    assert listed.value == [{"id": "one"}]


@pytest.mark.asyncio
async def test_get_event_result_and_refresh_truth_are_structured(tmp_path, capsys):
    manager = _manager(tmp_path)
    manager.get_event = lambda event_id: {"id": event_id}
    direct = await manager.get_event_result("event-1")
    assert direct == ExternalMutationResult(
        True,
        ExternalCommitState.UNCHANGED,
        {"id": "event-1"},
    )
    manager.get_event = GoogleCalendarManager.get_event.__get__(manager)

    class Execute:
        def execute(self):
            return {"id": "event-2"}

    service = SimpleNamespace(
        events=lambda: SimpleNamespace(get=lambda **kwargs: Execute())
    )
    creds = RefreshCreds()
    with (
        patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=creds,
        ),
        patch("googleapiclient.discovery.build", return_value=service),
    ):
        refreshed = await manager.get_event_result("event-2")
    assert refreshed.ok is True
    assert refreshed.state is ExternalCommitState.CHANGED
    assert refreshed.value == {"id": "event-2"}

    class FailingRefresh(RefreshCreds):
        def refresh(self, request):
            raise RuntimeError("INJECTED_EXCEPTION_TEXT")

    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=FailingRefresh(),
    ):
        failed = await manager.get_event_result("event-3")
    assert failed.ok is False
    assert failed.state is ExternalCommitState.UNKNOWN
    assert failed.error_code == "external_read_failed"
    assert "INJECTED_EXCEPTION_TEXT" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_list_uses_exact_captured_reference_interval(tmp_path):
    manager = _manager(tmp_path)
    captured = {}

    class Execute:
        def execute(self):
            return {"items": []}

    class Events:
        def list(self, **kwargs):
            captured.update(kwargs)
            return Execute()

    reference = datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)
    with (
        patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=ValidCreds(),
        ),
        patch(
            "googleapiclient.discovery.build",
            return_value=SimpleNamespace(events=lambda: Events()),
        ),
    ):
        result = await manager.list_upcoming_events_result(
            90,
            reference_time=reference,
        )
    assert result.ok is True
    assert captured["timeMin"] == "2026-07-15T10:30:00+00:00"
    assert captured["timeMax"] == "2026-10-13T10:30:00+00:00"

    manager.list_upcoming_events = lambda days=30: []
    legacy_override = await manager.list_upcoming_events_result(
        90,
        reference_time=reference,
    )
    assert legacy_override.ok is True
    assert legacy_override.value == []


@pytest.mark.asyncio
async def test_update_result_explicitly_clears_remote_recurrence(tmp_path):
    manager = _manager(tmp_path)
    captured = {}

    class Execute:
        def __init__(self, value):
            self.value = value

        def execute(self):
            return self.value

    class Events:
        def get(self, **kwargs):
            return Execute(
                {
                    "id": "event",
                    "summary": "Recurring",
                    "recurrence": ["RRULE:FREQ=WEEKLY"],
                }
            )

        def update(self, *, body, **kwargs):
            captured.update(body)
            return Execute({**body, "id": "event"})

    with (
        patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=ValidCreds(),
        ),
        patch(
            "googleapiclient.discovery.build",
            return_value=SimpleNamespace(events=lambda: Events()),
        ),
    ):
        result = await manager.update_event_result("event", recurrence=None)
    assert result.ok is True
    assert result.state is ExternalCommitState.CHANGED
    assert "recurrence" not in captured


@pytest.mark.asyncio
async def test_daily_recurrence_is_preserved_by_direct_create_and_update(tmp_path):
    manager = _manager(tmp_path)
    inserted = {}
    updated = {}

    class Execute:
        def __init__(self, value):
            self.value = value

        def execute(self):
            return self.value

    class Events:
        def insert(self, *, body, **kwargs):
            inserted.update(body)
            return Execute({**body, "id": "created"})

        def get(self, **kwargs):
            return Execute({"id": "existing", "summary": "Daily"})

        def update(self, *, body, **kwargs):
            updated.update(body)
            return Execute({**body, "id": "existing"})

    with (
        patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=ValidCreds(),
        ),
        patch(
            "googleapiclient.discovery.build",
            return_value=SimpleNamespace(events=lambda: Events()),
        ),
    ):
        created = await manager.create_event_result(
            "Daily",
            "2026-07-16T10:00:00+02:00",
            recurrence="daily",
        )
        changed = await manager.update_event_result(
            "existing",
            recurrence="daily",
        )
    assert created.ok is True
    assert changed.ok is True
    assert inserted["recurrence"] == ["RRULE:FREQ=DAILY"]
    assert updated["recurrence"] == ["RRULE:FREQ=DAILY"]


@pytest.mark.asyncio
async def test_google_style_not_found_and_malformed_success_are_bounded(tmp_path):
    manager = _manager(tmp_path)

    class NotFound(Exception):
        resp = SimpleNamespace(status=404)

    def missing(*args, **kwargs):
        raise NotFound("INJECTED_EXCEPTION_TEXT")

    manager.delete_event = missing
    absent = await manager.delete_event_result("missing")
    assert absent.ok is False
    assert absent.state is ExternalCommitState.UNCHANGED
    assert absent.error_code == "external_not_found"

    manager.create_event = lambda *args, **kwargs: {}
    malformed = await manager.create_event_result(
        "Title",
        "2026-07-16T10:00:00+02:00",
    )
    assert malformed.ok is False
    assert malformed.state is ExternalCommitState.UNKNOWN
    assert malformed.error_code == "external_commit_unknown"


@pytest.mark.asyncio
async def test_invalid_credentials_before_create_dispatch_are_unchanged(tmp_path):
    manager = _manager(tmp_path)
    invalid = SimpleNamespace(
        valid=False,
        expired=False,
        refresh_token=None,
    )
    with (
        patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=invalid,
        ),
        patch(
            "googleapiclient.discovery.build",
            side_effect=AssertionError("provider_must_not_be_built"),
        ),
    ):
        result = await manager.create_event_result(
            "Title",
            "2026-07-16T10:00:00+02:00",
        )
    assert result.ok is False
    assert result.state is ExternalCommitState.UNCHANGED
    assert result.error_code == "invalid_credentials"


@pytest.mark.asyncio
async def test_outer_cancel_waits_for_worker_exception_and_carries_unknown():
    started = threading.Event()
    release = threading.Event()

    def worker():
        started.set()
        assert release.wait(2)
        raise RuntimeError("INJECTED_EXCEPTION_TEXT")

    task = asyncio.create_task(GoogleCalendarManager._await_worker(worker))
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(ExternalOperationCancelled) as raised:
        await task
    assert raised.value.result.ok is False
    assert raised.value.result.state is ExternalCommitState.UNKNOWN
    assert raised.value.result.error_code == "external_commit_unknown"
    assert task.cancelled()


@pytest.mark.asyncio
async def test_legacy_false_after_mutating_dispatch_never_leaks_false_truth(tmp_path):
    manager = _manager(tmp_path)
    manager.create_event = lambda *args, **kwargs: None
    manager.update_event = lambda *args, **kwargs: None
    manager.delete_event = lambda *args, **kwargs: False

    created = await manager.create_event_result("Title", "2026-07-16T10:00:00+02:00")
    updated = await manager.update_event_result("event", title="Title")
    deleted = await manager.delete_event_result("event")

    for result in (created, updated, deleted):
        assert result.ok is False
        assert result.state is ExternalCommitState.UNKNOWN
        assert result.error_code == "external_commit_unknown"
    # The actual legacy projection remains a bool, not a truthy dataclass.
    assert manager.delete_event("event") is False
    assert bool(manager.delete_event("event")) is False


@pytest.mark.asyncio
async def test_read_failure_is_authoritatively_unchanged(tmp_path):
    manager = _manager(tmp_path)
    manager.list_upcoming_events = lambda *args, **kwargs: None
    result = await manager.list_upcoming_events_result()
    assert result.ok is False
    assert result.state is ExternalCommitState.UNCHANGED
    assert result.error_code == "external_read_failed"


def test_create_update_delete_legacy_shapes(tmp_path):
    manager = _manager(tmp_path)
    manager._create_event_api = lambda **kwargs: {
        "status": "created",
        "id": "new",
        "htmlLink": "link",
    }
    assert manager.create_event("Title", "2026-07-16T10:00:00+02:00") == {
        "status": "created",
        "id": "new",
        "htmlLink": "link",
    }

    # Existing public methods preserve their historical scalar/container
    # projections.  Provider internals are replaced because this is offline.
    with patch.object(GoogleCalendarManager, "update_event", return_value={"id": "old"}):
        assert manager.update_event("old", title="Title") == {"id": "old"}
    with patch.object(GoogleCalendarManager, "delete_event", return_value=True):
        assert manager.delete_event("old") is True
    with patch.object(GoogleCalendarManager, "list_upcoming_events", return_value=[]):
        assert manager.list_upcoming_events() == []


def test_auth_legacy_tuple_and_structured_token_storage_failure(tmp_path):
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}")
    manager = _manager(tmp_path)
    manager.credentials_path = credentials
    flow = SimpleNamespace(
        redirect_uri=None,
        authorization_url=lambda **kwargs: ("https://auth.invalid", "state"),
    )
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
        return_value=flow,
    ):
        ok, value = manager.get_auth_url(1, 2)
    assert (ok, value) == (True, "https://auth.invalid")

    class ExchangingFlow:
        credentials = ValidCreds()

        def fetch_token(self, code):
            return None

    manager._auth_flow = ExchangingFlow()
    manager._auth_flow_state = {
        "requester_id": "1",
        "channel_id": "2",
    }
    manager.token_path.write_text(ValidCreds().to_json())
    old_token = manager.token_path.read_bytes()
    manager._save_credentials = lambda creds: (_ for _ in ()).throw(OSError("sentinel"))
    result = manager._exchange_code_result_sync("code", 1, 2)
    assert result.ok is False
    assert result.state is ExternalCommitState.CHANGED
    assert result.error_code == "token_storage_failed"
    assert manager.enabled is True
    assert manager.token_path.read_bytes() == old_token
    assert manager._auth_flow is None
    assert manager._auth_flow_state is None


@pytest.mark.parametrize("failure", ["invalid_grant", "http_400"])
def test_auth_rejection_is_authoritative_and_redacted(tmp_path, capsys, failure):
    manager = _manager(tmp_path)
    manager.token_path.write_text(ValidCreds().to_json())
    old_token = manager.token_path.read_bytes()

    class OAuthFailure(Exception):
        error = "invalid_grant" if failure == "invalid_grant" else None
        resp = SimpleNamespace(status=400 if failure == "http_400" else None)

    class RejectingFlow:
        credentials = ValidCreds()

        def fetch_token(self, code):
            raise OAuthFailure(
                "SECRET_CODE SECRET_TOKEN https://secret.invalid/auth"
            )

    manager._auth_flow = RejectingFlow()
    manager._auth_flow_state = {}
    result = manager._exchange_code_result_sync("SECRET_CODE")
    assert result.ok is False
    assert result.state is ExternalCommitState.UNCHANGED
    assert result.error_code == "invalid_auth_code"
    assert manager.enabled is True
    assert manager.token_path.read_bytes() == old_token
    output = capsys.readouterr().out
    for secret in (
        "SECRET_CODE",
        "SECRET_TOKEN",
        "https://secret.invalid/auth",
    ):
        assert secret not in output


@pytest.mark.asyncio
async def test_oauth_flow_is_single_use_and_new_flow_survives_old_exchange(
    tmp_path,
):
    manager = _manager(tmp_path)
    manager.credentials_path.write_text("{}")
    started = threading.Event()
    release = threading.Event()
    fetches = 0

    class BlockingFlow:
        credentials = ValidCreds()

        def fetch_token(self, code):
            nonlocal fetches
            fetches += 1
            started.set()
            assert release.wait(2)

    old_flow = BlockingFlow()
    manager._auth_flow = old_flow
    manager._auth_flow_state = {}
    first = asyncio.create_task(
        asyncio.to_thread(manager._exchange_code_result_sync, "first")
    )
    assert await asyncio.to_thread(started.wait, 2)
    duplicate = asyncio.create_task(
        asyncio.to_thread(manager._exchange_code_result_sync, "second")
    )

    new_flow = SimpleNamespace(
        redirect_uri=None,
        authorization_url=lambda **kwargs: ("https://new.invalid", "state"),
    )
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
        return_value=new_flow,
    ):
        replacement = asyncio.create_task(
            asyncio.to_thread(manager._get_auth_url_result_sync, 1, 2, 900)
        )
        await asyncio.sleep(0)
        release.set()
        first_result, duplicate_result, replacement_result = await asyncio.gather(
            first,
            duplicate,
            replacement,
        )

    assert first_result.ok is True
    assert duplicate_result.error_code == "missing_auth_flow"
    assert replacement_result.ok is True
    assert fetches == 1
    assert manager._auth_flow is new_flow


@pytest.mark.asyncio
async def test_credential_lock_is_process_wide_across_exchange_and_refresh(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(ValidCreds().to_json())
    exchanging = _manager(tmp_path)
    refreshing = GoogleCalendarManager(token_path=token_path)
    started = threading.Event()
    release = threading.Event()
    refresh_entered = threading.Event()

    class BlockingFlow:
        credentials = ValidCreds()

        def fetch_token(self, code):
            started.set()
            assert release.wait(2)

    class ObservedRefresh(RefreshCreds):
        def refresh(self, request):
            refresh_entered.set()
            super().refresh(request)

    exchanging._auth_flow = BlockingFlow()
    exchanging._auth_flow_state = {}
    exchange = asyncio.create_task(
        asyncio.to_thread(exchanging._exchange_code_result_sync, "code")
    )
    assert await asyncio.to_thread(started.wait, 2)
    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=ObservedRefresh(),
    ):
        refresh = asyncio.create_task(refreshing.initialize_result())
        await asyncio.sleep(0.02)
        assert not refresh_entered.is_set()
        release.set()
        exchange_result, refresh_result = await asyncio.gather(exchange, refresh)

    assert exchange_result.ok is True
    assert refresh_result.ok is True
    assert refresh_entered.is_set()
    persisted = json.loads(token_path.read_text())
    assert persisted["refresh_token"] == "refresh"
    assert persisted["client_id"] == "client"


def test_atomic_token_writer_never_leaves_a_partial_document(tmp_path):
    manager = _manager(tmp_path)
    token_path = tmp_path / "token.json"
    manager.token_path = token_path
    manager._save_credentials(ValidCreds())
    assert json.loads(token_path.read_text()) == {
        "token": "access",
        "refresh_token": "refresh",
        "client_id": "client",
        "client_secret": "secret",
    }
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(".token.json.*.tmp")) == []

    before = token_path.read_bytes()

    class MalformedCreds:
        def to_json(self):
            return "{}"

    with pytest.raises(ValueError, match="invalid_authorized_user_document"):
        manager._save_credentials(MalformedCreds())
    assert token_path.read_bytes() == before
