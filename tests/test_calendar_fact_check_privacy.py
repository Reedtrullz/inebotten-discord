from dataclasses import fields
from datetime import datetime, timezone

from core.calendar_fact_check_store import (
    CalendarFactCheckInquiry,
    CalendarFactCheckStore,
    CalendarFactCheckTarget,
)
from core.message_context import ConversationKey
from features.calendar_fact_check_manager import CalendarFactCheckManager


def test_inquiry_snapshot_has_only_approved_target_and_timestamps():
    now = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
    store = CalendarFactCheckStore(now_provider=lambda: now)
    key = ConversationKey(1, 2, 3)
    store.begin(key, (
        CalendarFactCheckTarget(
            "calendar-1",
            "revision-1",
            "Møte med Ola",
            "26.07.2026",
            "09:00",
        ),
    ))
    inquiry = store.lookup(key).inquiry
    assert inquiry is not None
    assert {field.name for field in fields(CalendarFactCheckTarget)} == {
        "stable_id", "revision", "title", "date", "time"
    }
    assert {field.name for field in fields(CalendarFactCheckInquiry)} == {
        "key", "phase", "targets", "created_at", "expires_at"
    }
    serialized = repr(inquiry)
    for canary in (
        "DISCORD_ID_CANARY",
        "UNRELATED_CALENDAR_CANARY",
        "DESCRIPTION_CANARY",
        "MEMORY_CANARY",
        "CREDENTIAL_CANARY",
    ):
        assert canary not in serialized


def test_source_labels_are_approved_domain_or_fixed_hash_only():
    manager = CalendarFactCheckManager.__new__(CalendarFactCheckManager)
    from core.calendar_fact_check_evidence import CalendarSourcePolicy
    manager.source_policy = CalendarSourcePolicy()
    assert manager._safe_site_label("https://www.fotball.no/kamp") == "fotball.no"
    label = manager._safe_site_label(
        "https://private-title-canary.example/path?token=CREDENTIAL_CANARY"
    )
    assert len(label) == 12
    assert label.isalnum()
    assert "canary" not in label
