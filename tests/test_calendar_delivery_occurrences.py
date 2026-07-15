"""Read-only calendar occurrence snapshots consumed by ReminderChecker."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cal_system.calendar_manager import CalendarManager
from core.mutation_coordinator import CALENDAR_SHARED_SCOPE, MutationCoordinator


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)


class ExplodingClock:
    def now(self):
        raise AssertionError("delivery snapshots must not read the clock")

    def epoch(self):
        raise AssertionError("delivery snapshots must not read the clock")


def _item(item_id: str, title: str, date: str, time: str | None, **extra):
    return {
        "id": item_id,
        "title": title,
        "date": date,
        "time": time,
        "completed": False,
        "delete_pending": False,
        "user_id": "42",
        "channel_id": "99",
        **extra,
    }


def _fingerprint(row: dict[str, object]):
    return (
        row["id"],
        row["due_at"],
        row["status"],
        row["delete_pending"],
    )


def test_snapshot_is_canonical_deterministic_detached_and_clock_free(tmp_path):
    path = tmp_path / "calendar.json"
    manager = CalendarManager(path, clock=ExplodingClock())
    manager.items = {
        manager.SHARED_KEY: [
            _item("later", "Senere", "16.07.2026", "10:00"),
            _item("same-b", "Lik B", "16.07.2026", "09:00"),
            _item("same-a", "Lik A", "16.07.2026", "09:00"),
            _item(
                "date-only",
                "Dato",
                "15.07.2026",
                None,
                user_id="gcal_sync",
                channel_id=None,
            ),
        ]
    }
    original = deepcopy(manager.items)

    rows = manager.snapshot_delivery_occurrences(reference_time=NOW)

    assert [row["id"] for row in rows] == [
        "date-only",
        "same-a",
        "same-b",
        "later",
    ]
    assert set(rows[0]) == {
        "source_kind",
        "id",
        "due_at",
        "status",
        "delete_pending",
        "user_id",
        "channel_id",
        "title",
        "time",
    }
    assert rows[0] == {
        "source_kind": "calendar",
        "id": "date-only",
        "due_at": datetime(2026, 7, 15, 9, 0, tzinfo=OSLO),
        "status": "active",
        "delete_pending": False,
        "user_id": "gcal_sync",
        "channel_id": None,
        "title": "Dato",
        "time": None,
    }
    assert rows[-1]["due_at"] == datetime(2026, 7, 16, 10, 0, tzinfo=OSLO)
    assert rows[-1]["time"] == "10:00"
    assert rows[-1]["due_at"].tzinfo is OSLO

    rows[0]["title"] = "Mutert kopi"
    assert manager.items == original
    assert not path.exists()


def test_snapshot_skips_ineligible_ambiguous_and_malformed_rows_without_leakage(
    tmp_path,
    capsys,
):
    manager = CalendarManager(tmp_path / "calendar.json", clock=ExplodingClock())
    manager.items = {
        manager.SHARED_KEY: [
            _item("valid", "Gyldig", "16.07.2026", "09:00"),
            _item("completed", "Ferdig", "16.07.2026", "09:00", completed=True),
            _item("pending", "Slettes", "16.07.2026", "09:00", delete_pending=True),
            _item("integer-completed", "Ugyldig", "16.07.2026", "09:00", completed=0),
            _item("null-pending", "Ugyldig", "16.07.2026", "09:00", delete_pending=None),
            _item("dup", "Duplikat A", "16.07.2026", "09:00"),
            _item("dup", "Duplikat B", "17.07.2026", "09:00"),
            _item(" ", "Blank id", "16.07.2026", "09:00"),
            _item("missing-title", " ", "16.07.2026", "09:00"),
            _item("bad-date", "SECRET_TITLE", "SECRET_DATE", "09:00"),
            _item("bad-time", "Dårlig tid", "16.07.2026", "SECRET_TIME"),
            _item("spring-gap", "Gap", "29.03.2026", "02:30"),
            _item("autumn-fold", "Fold", "25.10.2026", "02:30"),
        ]
    }
    original = deepcopy(manager.items)

    rows = manager.snapshot_delivery_occurrences(reference_time=NOW)

    assert [row["id"] for row in rows] == ["valid"]
    assert manager.items == original
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.asyncio
async def test_snapshot_and_revalidation_reject_naive_reference_without_clock_read(
    tmp_path,
):
    manager = CalendarManager(tmp_path / "calendar.json", clock=ExplodingClock())
    manager.items = {
        manager.SHARED_KEY: [_item("one", "Én", "16.07.2026", "09:00")]
    }
    naive = datetime(2026, 7, 15, 12, 0)

    with pytest.raises(ValueError, match="reference_time_must_be_aware"):
        manager.snapshot_delivery_occurrences(reference_time=naive)
    async with manager.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
        with pytest.raises(ValueError, match="reference_time_must_be_aware"):
            manager.matches_delivery_fingerprint(
                (
                    "one",
                    datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
                    "active",
                    False,
                ),
                reference_time=naive,
            )


@pytest.mark.asyncio
async def test_revalidation_uses_exact_four_field_fingerprint_and_current_eligibility(
    tmp_path,
):
    coordinator = MutationCoordinator()
    manager = CalendarManager(
        tmp_path / "calendar.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.items = {
        manager.SHARED_KEY: [_item("one", "Opprinnelig", "16.07.2026", "09:00")]
    }
    row = manager.snapshot_delivery_occurrences(reference_time=NOW)[0]
    fingerprint = _fingerprint(row)

    async with coordinator.hold(CALENDAR_SHARED_SCOPE):
        assert manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        # The frozen contract is exactly the four fields above. Presentation
        # changes are deliberately outside the claim fingerprint.
        manager.items[manager.SHARED_KEY][0]["title"] = "Nytt navn"
        manager.items[manager.SHARED_KEY][0]["channel_id"] = "100"
        assert manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        manager.items[manager.SHARED_KEY][0]["time"] = "09:01"
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        manager.items[manager.SHARED_KEY][0]["time"] = "09:00"
        manager.items[manager.SHARED_KEY][0]["completed"] = True
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        manager.items[manager.SHARED_KEY][0]["completed"] = False
        manager.items[manager.SHARED_KEY][0]["delete_pending"] = True
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.parametrize(
    "fingerprint",
    [
        None,
        [],
        ("one",),
        ("", datetime(2026, 7, 16, 9, 0, tzinfo=OSLO), "active", False),
        ("one", datetime(2026, 7, 16, 9, 0), "active", False),
        ("one", datetime(2026, 7, 16, 9, 0, tzinfo=OSLO), "completed", False),
        ("one", datetime(2026, 7, 16, 9, 0, tzinfo=OSLO), "active", 0),
    ],
)
@pytest.mark.asyncio
async def test_revalidation_rejects_noncanonical_fingerprints(
    tmp_path,
    fingerprint,
):
    manager = CalendarManager(tmp_path / "calendar.json", clock=ExplodingClock())
    manager.items = {
        manager.SHARED_KEY: [_item("one", "Én", "16.07.2026", "09:00")]
    }

    async with manager.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_duplicate_id_is_never_revalidated_as_a_unique_occurrence(tmp_path):
    manager = CalendarManager(tmp_path / "calendar.json", clock=ExplodingClock())
    manager.items = {
        manager.SHARED_KEY: [
            _item("dup", "A", "16.07.2026", "09:00"),
            _item("dup", "B", "17.07.2026", "09:00"),
        ]
    }
    fingerprint = (
        "dup",
        datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
        "active",
        False,
    )

    assert manager.snapshot_delivery_occurrences(reference_time=NOW) == ()
    async with manager.mutation_coordinator.hold(CALENDAR_SHARED_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_colon_id_is_never_snapshotted_or_revalidated(tmp_path):
    coordinator = MutationCoordinator()
    manager = CalendarManager(
        tmp_path / "calendar.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.items = {
        manager.SHARED_KEY: [
            _item("calendar:colon", "Ugyldig", "16.07.2026", "09:00")
        ]
    }
    fingerprint = (
        "calendar:colon",
        datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
        "active",
        False,
    )

    assert manager.snapshot_delivery_occurrences(reference_time=NOW) == ()
    async with coordinator.hold(CALENDAR_SHARED_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_revalidation_requires_current_task_to_hold_calendar_scope(tmp_path):
    manager = CalendarManager(tmp_path / "calendar.json", clock=ExplodingClock())
    manager.items = {
        manager.SHARED_KEY: [_item("one", "Én", "16.07.2026", "09:00")]
    }
    fingerprint = _fingerprint(
        manager.snapshot_delivery_occurrences(reference_time=NOW)[0]
    )

    with pytest.raises(RuntimeError) as error:
        manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

    assert str(error.value) == "mutation_scope_not_owned"
