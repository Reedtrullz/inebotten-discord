import argparse
import asyncio
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import inebotten_ctl as ctl


def test_bounded_limit_rejects_out_of_range_values():
    assert ctl.bounded_limit("25") == 25
    with pytest.raises(Exception):
        ctl.bounded_limit("0")
    with pytest.raises(Exception):
        ctl.bounded_limit(str(ctl.MAX_LIMIT + 1))


def test_safe_env_file_requires_private_regular_file(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("DISCORD_USER_TOKEN=test\n", encoding="utf-8")
    env_path.chmod(0o600)
    assert ctl._safe_env_file(env_path)

    env_path.chmod(0o644)
    assert not ctl._safe_env_file(env_path)

    fifo_path = tmp_path / "fifo"
    os.mkfifo(fifo_path)
    assert not ctl._safe_env_file(fifo_path)


def test_load_token_prefers_environment(monkeypatch):
    monkeypatch.setenv("DISCORD_USER_TOKEN", "from-env")
    token, source = ctl.load_token_with_source()
    assert token == "from-env"
    assert source == "environment"


def test_load_token_prefers_explicit_hermes_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(ctl, "HERMES_HOME", tmp_path)
    hermes_env = tmp_path / "discord" / ".env"
    hermes_env.parent.mkdir(parents=True)
    hermes_env.write_text("DISCORD_USER_TOKEN=from-hermes\n", encoding="utf-8")
    hermes_env.chmod(0o600)
    token, source = ctl.load_token_with_source()
    assert token == "from-hermes"
    assert source == "hermes_env"


def test_load_token_uses_stable_non_path_source_labels(monkeypatch):
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    project_env = Path(ctl.__file__).resolve().parent.parent / ".env"

    def fake_read_token(path: Path):
        return "from-project" if path == project_env else None

    monkeypatch.setattr(ctl, "_read_token_file", fake_read_token)
    token, source = ctl.load_token_with_source()
    assert token == "from-project"
    assert source == "project_env"


def test_load_token_rejects_unsafe_existing_files(monkeypatch, tmp_path: Path):
    project_env = Path(ctl.__file__).resolve().parent.parent / ".env"
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)
    monkeypatch.setattr(ctl, "HERMES_HOME", tmp_path)
    hermes_env = tmp_path / "discord" / ".env"
    hermes_env.parent.mkdir(parents=True)
    hermes_env.write_text("DISCORD_USER_TOKEN=unsafe\n", encoding="utf-8")
    hermes_env.chmod(0o644)
    if project_env.exists() and ctl._safe_env_file(project_env):
        pytest.skip("project token file is configured; environment-specific unsafe-file assertion is not isolated")
    with pytest.raises(ctl.ControlError, match="unsafe permissions"):
        ctl.load_token_with_source()


def test_resolver_rejects_ambiguous_fragments():
    items = [SimpleNamespace(id=1, name="general"), SimpleNamespace(id=2, name="general-chat")]
    with pytest.raises(ctl.ControlError, match="ambiguous"):
        ctl._resolve_one(items, "gene", "channel", lambda item: item.name)


def test_resolver_requires_exact_target_for_writes():
    items = [SimpleNamespace(id=1, name="general")]
    with pytest.raises(ctl.ControlError, match="exact"):
        ctl._resolve_one(items, "gen", "channel", lambda item: item.name, exact_only=True)


def test_numeric_target_is_id_only():
    items = [SimpleNamespace(id=1, name="12345")]
    with pytest.raises(ctl.ControlError, match="not found"):
        ctl._resolve_one(items, "12345", "guild", lambda item: item.name)


def test_verify_identity_fails_closed():
    ctl.verify_identity(SimpleNamespace(user=SimpleNamespace(id=ctl.EXPECTED_USER_ID)))
    with pytest.raises(ctl.ControlError, match="unexpected"):
        ctl.verify_identity(SimpleNamespace(user=SimpleNamespace(id=123)))


def test_write_allowlist_is_optional_but_exact_when_configured(monkeypatch):
    monkeypatch.delenv("INEBOTTEN_WRITE_ALLOWLIST", raising=False)
    monkeypatch.delenv("INEBOTten_WRITE_ALLOWLIST", raising=False)
    assert ctl.write_is_allowed(1, 2)
    monkeypatch.setenv("INEBOTTEN_WRITE_ALLOWLIST", "1:2,3:4")
    assert ctl.write_is_allowed(1, 2)
    assert not ctl.write_is_allowed(1, 3)


def test_write_allowlist_ignores_legacy_misspelled_environment_key(monkeypatch):
    monkeypatch.delenv("INEBOTTEN_WRITE_ALLOWLIST", raising=False)
    monkeypatch.setenv("INEBOTten_WRITE_ALLOWLIST", "1:2")
    assert ctl.write_is_allowed(1, 3)


def test_output_writer_jsonl_preserves_tabs_and_metadata(capsys):
    writer = ctl.OutputWriter("jsonl", "test")
    writer.set_identity(SimpleNamespace(id=ctl.EXPECTED_USER_ID, __str__=lambda self: "inebotten"))
    writer.line("message\twith-tab", record={"message_id": "42"})
    writer.finish()
    lines = capsys.readouterr().out.splitlines()
    payload = json.loads(lines[0])
    assert payload["fields"] == ["message\twith-tab"]
    assert payload["message_id"] == "42"
    assert payload["source"] == "test"
    assert "ok" not in payload
    assert payload["identity"]["id"] == str(ctl.EXPECTED_USER_ID)
    assert json.loads(lines[-1])["type"] == "complete"


def test_output_writer_failure_is_authoritative_completion(capsys):
    writer = ctl.OutputWriter("jsonl", "test")
    writer.line("partial")
    writer.finish(ok=False, complete=False, error="failed")
    payloads = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert "complete" not in payloads[0]
    assert payloads[-1]["ok"] is False
    assert payloads[-1]["complete"] is False


def test_output_writer_enforces_record_budget(monkeypatch):
    monkeypatch.setattr(ctl, "MAX_OUTPUT_RECORDS", 1)
    writer = ctl.OutputWriter()
    writer.line("first")
    with pytest.raises(ctl.ControlError, match="safety limit"):
        writer.event("second")


def test_append_audit_hashes_content_and_writes_private_file(monkeypatch, tmp_path: Path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(ctl, "AUDIT_PATH", audit_path)
    ctl.append_audit(
        command="send",
        outcome="dry_run",
        guild_id=1,
        channel_id=2,
        content="secret message",
        dry_run=True,
    )
    raw = audit_path.read_text(encoding="utf-8")
    assert "secret message" not in raw
    payload = json.loads(raw)
    assert payload["content_sha256"]
    assert payload["dry_run"] is True
    assert stat.S_IMODE(audit_path.stat().st_mode) == 0o600


def test_append_audit_rejects_symlink(monkeypatch, tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("unchanged", encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    audit_path.symlink_to(target)
    monkeypatch.setattr(ctl, "AUDIT_PATH", audit_path)
    with pytest.raises(ctl.ControlError, match="audit log is unavailable"):
        ctl.append_audit(command="send", outcome="authorized_pending")
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_require_snowflake_rejects_rest_path_injection():
    assert ctl.require_snowflake("123456789", "thread ID") == "123456789"
    with pytest.raises(ctl.ControlError, match="decimal Discord ID"):
        ctl.require_snowflake("123/../../users/@me", "thread ID")


def test_explicit_hermes_home_does_not_fallback_to_project(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DISCORD_USER_TOKEN", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(ctl, "HERMES_HOME", tmp_path)

    def fake_read(path: Path):
        project_env = Path(ctl.__file__).resolve().parent.parent / ".env"
        return "project-secret" if path == project_env else None

    monkeypatch.setattr(ctl, "_read_token_file", fake_read)
    with pytest.raises(ctl.ControlError, match="configured environment"):
        ctl.load_token_with_source()


class _FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, content_type=None):
        return self.payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_rest_get_honors_bounded_retry_after(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(ctl.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(ctl.random, "uniform", lambda *_args: 0.0)
    ctl.REQUEST_TELEMETRY = ctl.RequestTelemetry()
    session = _FakeSession(
        [
            _FakeResponse(429, {"retry_after": 0.1}, {"X-RateLimit-Scope": "user"}),
            _FakeResponse(200, {"ok": True}),
        ]
    )
    status, payload = await ctl.rest_get(session, "https://discord.test", "token")
    assert status == 200
    assert payload == {"ok": True}
    assert sleeps == [0.1]
    assert ctl.REQUEST_TELEMETRY.rate_limited == 1
    assert ctl.REQUEST_TELEMETRY.retries == 1
    assert ctl.REQUEST_TELEMETRY.last_scope == "user"


def test_request_telemetry_captures_discord_rate_headers():
    telemetry = ctl.RequestTelemetry()
    telemetry.record(
        200,
        headers={
            "X-RateLimit-Bucket": "route-bucket",
            "X-RateLimit-Remaining": "4",
            "X-RateLimit-Reset-After": "1.25",
            "X-RateLimit-Scope": "shared",
            "X-RateLimit-Global": "true",
        },
    )
    assert telemetry.as_dict()["last_bucket"] == "route-bucket"
    assert telemetry.as_dict()["last_remaining"] == 4
    assert telemetry.as_dict()["last_reset_after"] == 1.25
    assert telemetry.as_dict()["last_scope"] == "shared"
    assert telemetry.as_dict()["last_global"] is True


@pytest.mark.asyncio
async def test_rest_get_does_not_retry_permission_errors(monkeypatch):
    ctl.REQUEST_TELEMETRY = ctl.RequestTelemetry()
    session = _FakeSession([_FakeResponse(403, {"code": 50013})])
    status, payload = await ctl.rest_get(session, "https://discord.test", "token")
    assert status == 403
    assert payload["code"] == 50013
    assert ctl.REQUEST_TELEMETRY.retries == 0


@pytest.mark.asyncio
async def test_rest_get_preserves_successful_json_arrays():
    ctl.REQUEST_TELEMETRY = ctl.RequestTelemetry()
    session = _FakeSession([_FakeResponse(200, [{"id": "1"}, {"id": "2"}])])
    status, payload = await ctl.rest_get(session, "https://discord.test", "token")
    assert status == 200
    assert payload == [{"id": "1"}, {"id": "2"}]


@pytest.mark.asyncio
async def test_rest_get_clamps_caller_retry_budget(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(ctl.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(ctl.random, "uniform", lambda *_args: 0.0)
    ctl.REQUEST_TELEMETRY = ctl.RequestTelemetry()
    session = _FakeSession(
        [
            _FakeResponse(500, {"error": "one"}),
            _FakeResponse(500, {"error": "two"}),
            _FakeResponse(500, {"error": "three"}),
            _FakeResponse(200, {"ok": True}),
        ]
    )
    status, payload = await ctl.rest_get(
        session,
        "https://discord.test",
        "token",
        max_attempts=99,
    )
    assert status == 500
    assert payload["error"] == "three"
    assert len(session.calls) == ctl.MAX_RETRY_ATTEMPTS
    assert len(sleeps) == ctl.MAX_RETRY_ATTEMPTS - 1


class _FakeClient:
    def __init__(self):
        self.user = SimpleNamespace(id=ctl.EXPECTED_USER_ID)
        self.guilds = []
        self._on_ready = None
        self.close_calls = 0

    def event(self, callback):
        self._on_ready = callback
        return callback

    async def start(self, _token):
        await self._on_ready()

    async def close(self):
        self.close_calls += 1


@pytest.mark.asyncio
async def test_run_propagates_on_ready_control_error(monkeypatch, capsys):
    fake_client = _FakeClient()
    monkeypatch.setattr(ctl.discord, "Client", lambda: fake_client)
    monkeypatch.setattr(ctl, "load_token_with_source", lambda: ("token", "environment"))
    args = argparse.Namespace(
        cmd="send",
        guild="missing",
        channel="general",
        text="hello",
        format="text",
        rate_limit_info=False,
        confirm=True,
        dry_run=False,
    )

    with pytest.raises(ctl.ControlError, match="guild not found"):
        await ctl.run(args)

    assert fake_client.close_calls >= 1
    captured = capsys.readouterr()
    assert "token" not in captured.err
    assert captured.out == ""


@pytest.mark.asyncio
async def test_run_enforces_total_command_budget(monkeypatch):
    class HangingClient(_FakeClient):
        async def start(self, _token):
            await asyncio.sleep(1)

    fake_client = HangingClient()
    monkeypatch.setattr(ctl.discord, "Client", lambda: fake_client)
    monkeypatch.setattr(ctl, "load_token_with_source", lambda: ("token", "environment"))
    monkeypatch.setattr(ctl, "MAX_COMMAND_SECONDS", 0.001)
    args = argparse.Namespace(
        cmd="guilds",
        format="text",
        rate_limit_info=False,
    )

    with pytest.raises(ctl.ControlError, match="safety budget"):
        await ctl.run(args)

    assert fake_client.close_calls >= 1
