"""Read-only reminder occurrence snapshots consumed by ReminderChecker."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from cal_system.reminder_manager import ReminderManager
from cal_system.temporal_resolver import TemporalResolver
from core.mutation_coordinator import REMINDER_STORE_SCOPE, MutationCoordinator


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)


class ExplodingClock:
    def now(self):
        raise AssertionError("delivery snapshots must not read the clock")

    def epoch(self):
        raise AssertionError("delivery snapshots must not read the clock")


def _reminder(
    reminder_id: str,
    text: str,
    due_at: str | None,
    **extra,
):
    return {
        "id": reminder_id,
        "text": text,
        "due_at": due_at,
        "due_date": None,
        "time": None,
        "timezone": "Europe/Oslo",
        "recurrence": None,
        "recurrence_anchor_local": None,
        "recurrence_sequence": None,
        "completed": False,
        "user_id": "42",
        "channel_id": "99",
        **extra,
    }


def _fingerprint(row: dict[str, object]):
    return (
        row["id"],
        row["due_at"],
        row["recurrence_anchor_local"],
        row["recurrence_sequence"],
        row["completed"],
    )


def test_snapshot_is_canonical_deterministic_detached_and_clock_free(tmp_path):
    path = tmp_path / "reminders.json"
    manager = ReminderManager(path, clock=ExplodingClock())
    manager.reminders = {
        "2": [
            _reminder(
                "fold-later",
                "Andre fold",
                "2026-10-25T02:15:00+01:00",
            ),
            _reminder(
                "same-b",
                "Lik B",
                "2026-10-25T03:00:00+01:00",
            ),
        ],
        "1": [
            _reminder(
                "same-a",
                "Lik A",
                "2026-10-25T03:00:00+01:00",
            ),
            _reminder(
                "fold-earlier",
                "Første fold",
                "2026-10-25T02:30:00+02:00",
                recurrence="daily",
                recurrence_anchor_local="2026-10-24T02:30:00",
                recurrence_sequence=1,
            ),
        ],
    }
    original = copy.deepcopy(manager.reminders)
    original_root = manager.reminders

    rows = manager.snapshot_delivery_occurrences(reference_time=NOW)

    assert [row["id"] for row in rows] == [
        "fold-earlier",
        "fold-later",
        "same-a",
        "same-b",
    ]
    assert set(rows[0]) == {
        "source_kind",
        "id",
        "due_at",
        "recurrence_anchor_local",
        "recurrence_sequence",
        "completed",
        "user_id",
        "channel_id",
        "text",
    }
    assert rows[0] == {
        "source_kind": "reminder",
        "id": "fold-earlier",
        "due_at": datetime(2026, 10, 25, 2, 30, tzinfo=OSLO, fold=0),
        "recurrence_anchor_local": "2026-10-24T02:30:00",
        "recurrence_sequence": 1,
        "completed": False,
        "user_id": "42",
        "channel_id": "99",
        "text": "Første fold",
    }
    assert rows[1]["due_at"] == datetime(
        2026,
        10,
        25,
        2,
        15,
        tzinfo=OSLO,
        fold=1,
    )
    assert rows[0]["due_at"].astimezone(timezone.utc) < rows[1][
        "due_at"
    ].astimezone(timezone.utc)

    rows[0]["text"] = "Mutert kopi"
    assert manager.reminders is original_root
    assert manager.reminders == original
    assert not path.exists()


def test_legacy_due_fields_are_detached_and_receive_exact_reference_identity(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "reminders.json"
    stored = {
        "1": [
            _reminder(
                "canonical",
                "Canonical",
                "2026-12-08T10:00:00+01:00",
                due_date="SECRET_DISPLAY_DATE",
                time="SECRET_DISPLAY_TIME",
            ),
            {
                "id": "legacy",
                "text": "Legacy",
                "due_date": "08.12",
                "time": "10:00",
                "completed": False,
                "user_id": "43",
                "channel_id": None,
                "recurrence": "weekly",
            },
        ]
    }
    path.write_text(json.dumps(stored), encoding="utf-8")
    manager = ReminderManager(path, clock=ExplodingClock())
    before = path.read_bytes()
    reference = datetime(2026, 12, 8, 8, 0, tzinfo=timezone.utc)
    seen_references: list[datetime] = []
    original_validate = TemporalResolver.validate_fields

    def validate_spy(self, *args, **kwargs):
        seen_references.append(kwargs["reference"])
        return original_validate(self, *args, **kwargs)

    monkeypatch.setattr(TemporalResolver, "validate_fields", validate_spy)

    rows = manager.snapshot_delivery_occurrences(reference_time=reference)

    assert [row["id"] for row in rows] == ["canonical", "legacy"]
    assert all(
        row["due_at"] == datetime(2026, 12, 8, 10, 0, tzinfo=OSLO)
        for row in rows
    )
    assert rows[1]["recurrence_anchor_local"] is None
    assert rows[1]["recurrence_sequence"] is None
    assert seen_references == [reference]
    assert seen_references[0] is reference
    assert manager.reminders == stored
    assert path.read_bytes() == before


def test_legacy_date_only_defaults_to_nine_oslo_without_rewrite(tmp_path):
    path = tmp_path / "reminders.json"
    stored = {
        "1": [
            {
                "id": "date-only",
                "text": "Dato",
                "due_date": "16.07.2026",
                "completed": False,
                "user_id": "42",
                "channel_id": "99",
            }
        ]
    }
    path.write_text(json.dumps(stored), encoding="utf-8")
    manager = ReminderManager(path, clock=ExplodingClock())
    before = path.read_bytes()

    rows = manager.snapshot_delivery_occurrences(reference_time=NOW)

    assert len(rows) == 1
    assert rows[0]["due_at"] == datetime(2026, 7, 16, 9, 0, tzinfo=OSLO)
    assert manager.reminders == stored
    assert path.read_bytes() == before


def test_snapshot_diagnostics_are_bounded_detached_and_due_specific(tmp_path):
    path = tmp_path / "reminders.json"
    manager = ReminderManager(path, clock=ExplodingClock())
    manager.reminders = {
        "1": [
            _reminder(
                "mismatch-both",
                "Mismatch",
                "2026-07-16T09:00:00+02:00",
                due_date="17.07.2026",
                time="10:00",
            ),
            _reminder(
                "mismatch-one",
                "Mismatch én",
                "2026-07-18T11:00:00+02:00",
                due_date="18.07.2026",
                time="10:00",
            ),
            _reminder(
                "mismatch-missing",
                "Manglende visningsfelt",
                "2026-07-18T12:00:00+02:00",
            ),
            {
                "id": "malformed-legacy-date",
                "text": "SECRET_BAD_DATE",
                "due_date": "SECRET_DATE",
                "time": "09:00",
                "completed": False,
            },
            _reminder(
                "malformed-due-at",
                "SECRET_BAD_DUE_AT",
                "SECRET_DUE_AT",
            ),
            _reminder("undated", "Checklist", None),
            _reminder(
                "completed-malformed",
                "Historisk",
                "SECRET_COMPLETED_DUE_AT",
                completed=True,
            ),
            _reminder(
                "matching",
                "Canonical",
                "2026-07-19T12:00:00+02:00",
                due_date="19.07.2026",
                time="12:00",
            ),
        ]
    }
    original = copy.deepcopy(manager.reminders)

    diagnostics = manager.snapshot_delivery_diagnostics(reference_time=NOW)

    assert diagnostics == {
        "malformed_legacy_due_at": 2,
        "legacy_due_mismatch": 3,
    }
    diagnostics["malformed_legacy_due_at"] = 999
    assert manager.reminders == original
    assert not path.exists()


def test_snapshot_skips_ineligible_ambiguous_and_malformed_rows_without_leakage(
    tmp_path,
    capsys,
):
    manager = ReminderManager(tmp_path / "reminders.json", clock=ExplodingClock())
    manager.reminders = {
        "1": [
            _reminder("valid", "Gyldig", "2026-07-16T09:00:00+02:00"),
            _reminder(
                "completed",
                "Ferdig",
                "2026-07-16T09:00:00+02:00",
                completed=True,
            ),
            _reminder(
                "numeric-completed",
                "Ikke bool",
                "2026-07-16T09:00:00+02:00",
                completed=0,
            ),
            _reminder(
                "null-completed",
                "Ikke legacy-manglende",
                "2026-07-16T09:00:00+02:00",
                completed=None,
            ),
            _reminder("undated", "Liste", None),
            _reminder("dup", "Duplikat A", "2026-07-16T09:00:00+02:00"),
            _reminder(" ", "Blank id", "2026-07-16T09:00:00+02:00"),
            _reminder("missing-text", " ", "2026-07-16T09:00:00+02:00"),
            _reminder("bad-due", "SECRET_TEXT", "SECRET_DUE_AT"),
            _reminder("naive-due", "Naiv", "2026-07-16T09:00:00"),
            _reminder(
                "partial-recurrence",
                "Delvis",
                "2026-07-16T09:00:00+02:00",
                recurrence="weekly",
                recurrence_anchor_local="2026-07-16T09:00:00",
                recurrence_sequence=None,
            ),
            _reminder(
                "bool-sequence",
                "Bool",
                "2026-07-16T09:00:00+02:00",
                recurrence="weekly",
                recurrence_anchor_local="2026-07-16T09:00:00",
                recurrence_sequence=True,
            ),
            _reminder(
                "unhashable-recurrence",
                "Listegjentakelse",
                "2026-07-16T09:00:00+02:00",
                recurrence=["weekly"],
            ),
            {
                "id": "bad-date",
                "text": "SECRET_BAD_DATE",
                "due_date": "SECRET_DATE",
                "time": "09:00",
                "completed": False,
            },
            {
                "id": "bad-time",
                "text": "Dårlig tid",
                "due_date": "16.07.2026",
                "time": "SECRET_TIME",
                "completed": False,
            },
            {
                "id": "spring-gap",
                "text": "Gap",
                "due_date": "29.03.2026",
                "time": "02:30",
                "completed": False,
            },
            {
                "id": "autumn-fold",
                "text": "Fold",
                "due_date": "25.10.2026",
                "time": "02:30",
                "completed": False,
            },
            None,
            "not-a-row",
        ],
        "2": [
            _reminder(
                "dup",
                "Duplikat B ferdig",
                "2026-07-17T09:00:00+02:00",
                completed=True,
            ),
        ],
        "broken-bucket": "not-a-list",
    }
    original = copy.deepcopy(manager.reminders)

    rows = manager.snapshot_delivery_occurrences(reference_time=NOW)

    assert [row["id"] for row in rows] == ["valid"]
    assert manager.reminders == original
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_snapshot_and_revalidation_reject_naive_reference_without_clock_read(
    tmp_path,
):
    manager = ReminderManager(tmp_path / "reminders.json", clock=ExplodingClock())
    manager.reminders = {
        "1": [_reminder("one", "Én", "2026-07-16T09:00:00+02:00")]
    }
    naive = datetime(2026, 7, 15, 12, 0)

    with pytest.raises(ValueError, match="^reference_time_must_be_aware$"):
        manager.snapshot_delivery_occurrences(reference_time=naive)
    with pytest.raises(ValueError, match="^reference_time_must_be_aware$"):
        manager.snapshot_delivery_diagnostics(reference_time=naive)
    with pytest.raises(ValueError, match="^reference_time_must_be_aware$"):
        manager.matches_delivery_fingerprint(
            (
                "one",
                datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
                None,
                None,
                False,
            ),
            reference_time=naive,
        )


@pytest.mark.asyncio
async def test_revalidation_requires_scope_and_repeats_exact_current_eligibility(
    tmp_path,
):
    coordinator = MutationCoordinator()
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.reminders = {
        "1": [
            _reminder(
                "one",
                "Opprinnelig",
                "2026-07-16T09:00:00+02:00",
                recurrence="weekly",
                recurrence_anchor_local="2026-07-16T09:00:00",
                recurrence_sequence=0,
            )
        ]
    }
    row = manager.snapshot_delivery_occurrences(reference_time=NOW)[0]
    fingerprint = _fingerprint(row)

    with pytest.raises(RuntimeError, match="^mutation_scope_not_owned$"):
        manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

    async with coordinator.hold(REMINDER_STORE_SCOPE):
        assert manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        manager.reminders["1"][0]["text"] = "Nytt navn"
        manager.reminders["1"][0]["channel_id"] = "100"
        manager.reminders["1"][0]["user_id"] = "43"
        assert manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        manager.reminders["1"][0]["recurrence_sequence"] = 1
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )

        manager.reminders["1"][0]["recurrence_sequence"] = 0
        manager.reminders["1"][0]["completed"] = True
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_revalidation_compares_fold_due_at_by_utc_instant(tmp_path):
    coordinator = MutationCoordinator()
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.reminders = {
        "1": [
            _reminder(
                "fold",
                "Fold",
                "2026-10-25T02:30:00+02:00",
            )
        ]
    }
    row = manager.snapshot_delivery_occurrences(reference_time=NOW)[0]
    fingerprint = _fingerprint(row)
    assert fingerprint[1].fold == 0
    assert fingerprint[1].utcoffset().total_seconds() == 2 * 60 * 60
    assert fingerprint[1].astimezone(timezone.utc) == datetime(
        2026,
        10,
        25,
        0,
        30,
        tzinfo=timezone.utc,
    )
    manager.reminders["1"][0]["due_at"] = "2026-10-25T02:30:00+01:00"
    async with coordinator.hold(REMINDER_STORE_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fingerprint",
    [
        None,
        [],
        ("one",),
        (
            " ",
            datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
            None,
            None,
            False,
        ),
        (
            "one",
            datetime(2026, 7, 16, 9, 0),
            None,
            None,
            False,
        ),
        (
            "one",
            datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
            "not-an-anchor",
            0,
            False,
        ),
        (
            "one",
            datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
            None,
            True,
            False,
        ),
        (
            "one",
            datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
            None,
            None,
            0,
        ),
    ],
)
async def test_revalidation_rejects_noncanonical_fingerprints(
    tmp_path,
    fingerprint,
):
    coordinator = MutationCoordinator()
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.reminders = {
        "1": [_reminder("one", "Én", "2026-07-16T09:00:00+02:00")]
    }

    async with coordinator.hold(REMINDER_STORE_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_duplicate_id_is_never_revalidated_as_a_unique_occurrence(tmp_path):
    coordinator = MutationCoordinator()
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.reminders = {
        "1": [_reminder("dup", "A", "2026-07-16T09:00:00+02:00")],
        "2": [_reminder("dup", "B", "2026-07-17T09:00:00+02:00")],
    }
    fingerprint = (
        "dup",
        datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
        None,
        None,
        False,
    )

    assert manager.snapshot_delivery_occurrences(reference_time=NOW) == ()
    async with coordinator.hold(REMINDER_STORE_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )


@pytest.mark.asyncio
async def test_colon_id_is_never_snapshotted_or_revalidated(tmp_path):
    coordinator = MutationCoordinator()
    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=ExplodingClock(),
        mutation_coordinator=coordinator,
    )
    manager.reminders = {
        "1": [
            _reminder(
                "reminder:colon",
                "Ugyldig",
                "2026-07-16T09:00:00+02:00",
            )
        ]
    }
    fingerprint = (
        "reminder:colon",
        datetime(2026, 7, 16, 9, 0, tzinfo=OSLO),
        None,
        None,
        False,
    )

    assert manager.snapshot_delivery_occurrences(reference_time=NOW) == ()
    async with coordinator.hold(REMINDER_STORE_SCOPE):
        assert not manager.matches_delivery_fingerprint(
            fingerprint,
            reference_time=NOW,
        )
