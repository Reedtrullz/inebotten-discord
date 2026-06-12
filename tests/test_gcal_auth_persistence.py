"""Google Calendar auth path and persistence regression tests."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from cal_system.google_calendar_manager import GoogleCalendarManager
from scripts import auth_gcal


class RefreshableCreds:
    valid = False
    expired = True
    refresh_token = "refresh-token"

    def __init__(self):
        self.refreshed = False

    def refresh(self, request):
        self.refreshed = True
        self.valid = True
        self.expired = False

    def to_json(self):
        return json.dumps({"refreshed": self.refreshed, "valid": self.valid})


class ValidCreds:
    valid = True
    expired = False
    refresh_token = "refresh-token"

    def to_json(self):
        return json.dumps({"valid": True, "refresh_token": self.refresh_token})


class GoogleCalendarAuthPersistenceTests(unittest.TestCase):
    def test_startup_auth_refresh_persists_updated_token(self):
        with TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "google_token.json"
            token_path.write_text("{}", encoding="utf-8")
            creds = RefreshableCreds()

            with patch.dict(os.environ, {"GCAL_TOKEN_PATH": str(token_path)}):
                with patch(
                    "google.oauth2.credentials.Credentials.from_authorized_user_file",
                    return_value=creds,
                ):
                    manager = GoogleCalendarManager()

            self.assertTrue(manager.enabled)
            self.assertTrue(creds.refreshed)
            self.assertEqual(json.loads(token_path.read_text())["refreshed"], True)
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_auth_url_uses_explicit_credentials_path(self):
        with TemporaryDirectory() as tmp:
            credentials_path = Path(tmp) / "credentials.json"
            credentials_path.write_text("{}", encoding="utf-8")
            flow = SimpleNamespace(
                redirect_uri=None,
                authorization_url=lambda **kwargs: ("https://auth.example", "state"),
            )

            with patch.dict(os.environ, {"GCAL_CREDENTIALS_PATH": str(credentials_path)}):
                with patch(
                    "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                    return_value=flow,
                ) as factory:
                    manager = GoogleCalendarManager.__new__(GoogleCalendarManager)
                    ok, auth_url = GoogleCalendarManager.get_auth_url(manager)

            self.assertTrue(ok)
            self.assertEqual(auth_url, "https://auth.example")
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args[0], str(credentials_path))
            self.assertEqual(flow.redirect_uri, "http://localhost:8080")

    def test_auth_script_resolves_vps_hermes_home(self):
        home, token_path, credentials_path = auth_gcal.resolve_auth_paths(
            "/opt/apps/inebotten-discord/data"
        )

        self.assertEqual(home, Path("/opt/apps/inebotten-discord/data"))
        self.assertEqual(
            token_path,
            Path("/opt/apps/inebotten-discord/data/google_token.json"),
        )
        self.assertEqual(
            credentials_path,
            Path("/opt/apps/inebotten-discord/data/credentials.json"),
        )

    def test_manual_auth_flow_requests_offline_access_and_saves_token(self):
        with TemporaryDirectory() as tmp:
            credentials_path = Path(tmp) / "credentials.json"
            credentials_path.write_text("{}", encoding="utf-8")
            seen_auth_kwargs = {}

            class FakeFlow:
                credentials = ValidCreds()

                def authorization_url(self, **kwargs):
                    seen_auth_kwargs.update(kwargs)
                    return "https://auth.example", "state"

                def fetch_token(self, code):
                    self.code = code

            with patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                return_value=FakeFlow(),
            ):
                with patch("builtins.input", return_value="oauth-code"):
                    auth_gcal.main(["--no-browser", "--hermes-home", tmp])

            token_path = Path(tmp) / "google_token.json"
            self.assertEqual(seen_auth_kwargs["prompt"], "consent")
            self.assertEqual(seen_auth_kwargs["access_type"], "offline")
            self.assertTrue(token_path.exists())
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
