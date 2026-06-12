#!/usr/bin/env python3
"""Google Calendar sync regression tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from cal_system.calendar_manager import CalendarManager
from cal_system.google_calendar_manager import GoogleCalendarManager
from features.calendar_handler import CalendarHandler


def _gcal_event(event_id, title, when, *, recurring_event_id=None):
    event = {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": when.isoformat()},
        "htmlLink": f"https://calendar.example/{event_id}",
        "creator": {"email": "ola@example.com"},
    }
    if recurring_event_id:
        event["recurringEventId"] = recurring_event_id
    return event


class FakeGCal:
    def __init__(self, events=None, configured=True, fetched_events=None):
        self.events = events or []
        self.configured = configured
        self.fetched_events = fetched_events or {}
        self.list_calls = []
        self.update_calls = []

    def is_configured(self):
        return self.configured

    def list_upcoming_events(self, days=30):
        self.list_calls.append(days)
        return self.events

    def get_event(self, event_id):
        return self.fetched_events.get(event_id)

    def update_event(self, event_id, **kwargs):
        self.update_calls.append((event_id, kwargs))
        return {"id": event_id, "htmlLink": f"https://calendar.example/{event_id}"}


class CalendarSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.storage_path = Path(self.tmp.name) / "calendar.json"

    def tearDown(self):
        self.tmp.cleanup()

    async def test_sync_updates_existing_recurring_series_once(self):
        now = datetime.now(ZoneInfo("Europe/Oslo"))
        first = now + timedelta(days=1)
        second = now + timedelta(days=8)
        gcal = FakeGCal(
            [
                _gcal_event("master_20270601", "Ukentlig møte", first, recurring_event_id="master"),
                _gcal_event("master_20270608", "Ukentlig møte", second, recurring_event_id="master"),
            ]
        )
        manager = CalendarManager(storage_path=self.storage_path, gcal_manager=gcal)
        manager.items = {
            manager.SHARED_KEY: [
                {
                    "id": "local-1",
                    "title": "Gammelt navn",
                    "date": "01.01.2027",
                    "time": "09:00",
                    "gcal_event_id": "master",
                    "username": "Google Calendar",
                    "user_id": "gcal_sync",
                    "completed": False,
                }
            ]
        }

        count = await manager.sync_from_gcal()

        synced = manager.items[manager.SHARED_KEY]
        self.assertEqual(count, 1)
        self.assertEqual(len(synced), 1)
        self.assertEqual(synced[0]["title"], "Ukentlig møte")
        self.assertEqual(synced[0]["date"], first.strftime("%d.%m.%Y"))
        self.assertEqual(synced[0]["gcal_event_id"], "master")
        self.assertEqual(gcal.list_calls, [90])

    async def test_sync_imports_new_recurring_series_once_with_master_id(self):
        now = datetime.now(ZoneInfo("Europe/Oslo"))
        first = now + timedelta(days=1)
        second = now + timedelta(days=8)
        gcal = FakeGCal(
            [
                _gcal_event("series_1", "Yoga", first, recurring_event_id="series-master"),
                _gcal_event("series_2", "Yoga", second, recurring_event_id="series-master"),
            ]
        )
        manager = CalendarManager(storage_path=self.storage_path, gcal_manager=gcal)
        manager.items = {}

        count = await manager.sync_from_gcal()

        synced = manager.items[manager.SHARED_KEY]
        self.assertEqual(count, 1)
        self.assertEqual(len(synced), 1)
        self.assertEqual(synced[0]["title"], "Yoga")
        self.assertEqual(synced[0]["date"], first.strftime("%d.%m.%Y"))
        self.assertEqual(synced[0]["gcal_event_id"], "series-master")

    async def test_manual_sync_rechecks_gcal_configuration(self):
        class ConfiguredGCal(FakeGCal):
            def __init__(self):
                super().__init__(events=[], configured=True)

        manager = CalendarManager(storage_path=self.storage_path, gcal_manager=None)
        manager.items = {}
        monitor = SimpleNamespace(
            calendar=manager,
            nlp_parser=SimpleNamespace(parse_event=lambda content: None),
            rate_limiter=SimpleNamespace(
                record_sent=lambda: None,
                record_failure=lambda **kwargs: None,
                can_send=lambda: (True, None),
                wait_if_needed=AsyncMock(return_value=True),
            ),
            loc=SimpleNamespace(current_lang="no"),
            client=None,
        )
        handler = CalendarHandler(monitor)
        handler.send_response = AsyncMock()
        message = SimpleNamespace(
            content="@inebotten synk",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        with patch("cal_system.google_calendar_manager.GoogleCalendarManager", ConfiguredGCal):
            await handler.handle_sync(message)

        responses = [call.args[1] for call in handler.send_response.await_args_list]
        self.assertTrue(manager.gcal_enabled)
        self.assertIn("🔄 Synkroniserer med Google Calendar...", responses)
        self.assertNotIn("❌ Google Calendar er ikke konfigurert eller koblet til ennå.", responses)

    def test_local_edit_pushes_full_update_to_gcal(self):
        gcal = FakeGCal()
        manager = CalendarManager(storage_path=self.storage_path, gcal_manager=gcal)
        manager.add_item(
            "123",
            "1",
            "Alice",
            "Møte",
            "10.06.2027",
            time_str="09:00",
            gcal_event_id="gcal-1",
        )

        updated = manager.edit_item(1, title="Nytt møte", date="11.06.2027")

        self.assertEqual(updated["gcal_link"], "https://calendar.example/gcal-1")
        self.assertEqual(gcal.update_calls[0][0], "gcal-1")
        self.assertEqual(gcal.update_calls[0][1]["title"], "Nytt møte")
        self.assertEqual(gcal.update_calls[0][1]["date_str"], "11.06.2027")
        self.assertEqual(gcal.update_calls[0][1]["time_str"], "09:00")

    async def test_sync_removes_deleted_gcal_item_inside_sync_window(self):
        tomorrow = datetime.now() + timedelta(days=1)
        gcal = FakeGCal(events=[])
        manager = CalendarManager(storage_path=self.storage_path, gcal_manager=gcal)
        manager.items = {
            manager.SHARED_KEY: [
                {
                    "id": "local-1",
                    "title": "Slettet i Google",
                    "date": tomorrow.strftime("%d.%m.%Y"),
                    "time": "12:00",
                    "gcal_event_id": "missing-gcal",
                    "completed": False,
                }
            ]
        }

        count = await manager.sync_from_gcal()

        self.assertEqual(count, 1)
        self.assertEqual(manager.items[manager.SHARED_KEY], [])

    async def test_sync_sets_error_when_gcal_list_fails(self):
        class FailingGCal(FakeGCal):
            def list_upcoming_events(self, days=30):
                self.list_calls.append(days)
                return None

        manager = CalendarManager(storage_path=self.storage_path, gcal_manager=FailingGCal())
        manager.items = {}

        count = await manager.sync_from_gcal()

        self.assertEqual(count, 0)
        self.assertIn("Kunne ikke hente", manager.last_gcal_sync_error)


class GoogleCalendarPushTests(unittest.TestCase):
    def test_sync_local_event_defaults_missing_time(self):
        manager = GoogleCalendarManager.__new__(GoogleCalendarManager)
        manager.enabled = True
        captured = {}

        def fake_create_event(**kwargs):
            captured.update(kwargs)
            return {"id": "created"}

        manager.create_event = fake_create_event

        result = GoogleCalendarManager.sync_local_event(
            manager,
            {"title": "Uten tid", "date": "10.06.2027", "time": None},
        )

        self.assertEqual(result, {"id": "created"})
        self.assertIn("T12:00:00", captured["start_time"])

    def test_list_upcoming_events_pages_through_all_results(self):
        manager = GoogleCalendarManager.__new__(GoogleCalendarManager)
        manager.enabled = True
        manager.calendar_id = "primary"
        manager._save_credentials = lambda creds: None

        class FakeCreds:
            expired = False
            refresh_token = None

        class FakeRequest:
            def __init__(self, payload):
                self.payload = payload

            def execute(self):
                return self.payload

        class FakeEventsResource:
            def __init__(self):
                self.page_tokens = []

            def list(self, **kwargs):
                token = kwargs.get("pageToken")
                self.page_tokens.append(token)
                if token is None:
                    return FakeRequest({"items": [{"id": "one"}], "nextPageToken": "page-2"})
                return FakeRequest({"items": [{"id": "two"}]})

        events_resource = FakeEventsResource()
        service = SimpleNamespace(events=lambda: events_resource)

        with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=FakeCreds()):
            with patch("googleapiclient.discovery.build", return_value=service):
                events = GoogleCalendarManager.list_upcoming_events(manager, days=30)

        self.assertEqual(events, [{"id": "one"}, {"id": "two"}])
        self.assertEqual(events_resource.page_tokens, [None, "page-2"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
