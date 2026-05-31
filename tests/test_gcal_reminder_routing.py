from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.reminder_checker import ReminderChecker


class FakeGCal:
    def is_configured(self):
        return True

    def list_upcoming_events(self, days=30):
        start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            {
                "id": "gcal-1",
                "summary": "GCal møte",
                "start": {"date": start},
                "creator": {"email": "reed@example.com"},
                "organizer": {"email": "reed@example.com"},
                "htmlLink": "https://calendar.google.com/event?eid=gcal-1",
            }
        ]


@pytest.mark.asyncio
async def test_sync_from_gcal_stores_default_channel_id_for_new_items():
    with TemporaryDirectory() as tmpdir:
        manager = CalendarManager(storage_path=Path(tmpdir) / "calendar.json", gcal_manager=FakeGCal())
        await manager.setup()

        count = await manager.sync_from_gcal(default_guild_id="123", default_channel_id="999")

        assert count == 1
        item = manager.items[manager.SHARED_KEY][0]
        assert item["gcal_event_id"] == "gcal-1"
        assert item["channel_id"] == "999"


@pytest.mark.asyncio
async def test_sync_from_gcal_backfills_channel_id_for_existing_items():
    with TemporaryDirectory() as tmpdir:
        manager = CalendarManager(storage_path=Path(tmpdir) / "calendar.json", gcal_manager=FakeGCal())
        await manager.setup()
        manager.add_item(
            guild_id="123",
            user_id="gcal_sync",
            username="Google Calendar",
            title="Old title",
            date_str=(datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y"),
            gcal_event_id="gcal-1",
            channel_id=None,
        )

        count = await manager.sync_from_gcal(default_guild_id="123", default_channel_id="999")

        assert count == 1
        item = manager.items[manager.SHARED_KEY][0]
        assert item["title"] == "GCal møte"
        assert item["channel_id"] == "999"


def test_find_digest_channel_returns_none_for_shared_without_channel_id():
    class CalendarStub:
        def get_upcoming(self, guild_id, days=1):
            return [{"title": "GCal møte", "channel_id": None}]

    checker = ReminderChecker(calendar_manager=CalendarStub())

    assert checker._find_digest_channel("shared") is None
