"""Canonical reminder timing and recurrence contracts.

These tests deliberately exercise the manager without the Discord handler or
checker.  Routing owns natural-language parsing; the manager owns canonical
storage, stable targets, and explicit-completion recurrence advancement.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from cal_system.reminder_clock import MutableReminderClock
from cal_system.reminder_manager import (
    MAX_CALENDAR_STEPS,
    ReminderManager,
    advance_due_at,
    parse_reminder_command,
)
from cal_system.temporal_resolver import TemporalResolver
from core.intent_models import BotIntent
from core.intent_payloads import validate_intent_payload


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)


def row(manager: ReminderManager, guild_id: object = 1) -> dict[str, object]:
    return manager.reminders[str(guild_id)][0]


def assert_unchanged(
    manager: ReminderManager,
    root: object,
    expected: object,
    raw: bytes,
) -> None:
    assert manager.reminders is root
    assert manager.reminders == expected
    assert manager.storage_path.read_bytes() == raw


def test_loading_a_legacy_date_only_record_does_not_rewrite_bytes(tmp_path):
    path = tmp_path / "reminders.json"
    legacy = {
        "1": [
            {
                "id": "rem_1_legacy",
                "text": "Gammel",
                "due_date": "31.01.2026",
                "recurrence": "monthly",
                "completed": False,
            }
        ]
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False, indent=3), encoding="utf-8")
    before = path.read_bytes()

    manager = ReminderManager(path)

    assert manager.reminders == legacy
    assert path.read_bytes() == before
    assert "due_at" not in manager.reminders["1"][0]
    assert "recurrence_anchor_local" not in manager.reminders["1"][0]


def test_mutable_clock_is_aware_and_advances_one_owned_value():
    clock = MutableReminderClock(NOW)
    assert clock.now() is NOW
    assert clock.epoch() == NOW.timestamp()

    clock.advance(timedelta(minutes=45))

    assert clock.now() == datetime(2026, 7, 14, 12, 45, tzinfo=OSLO)
    with pytest.raises(ValueError, match="naive_reminder_clock"):
        MutableReminderClock(datetime(2026, 7, 14, 12, 0))


@pytest.mark.asyncio
async def test_add_canonicalizes_due_at_as_authority_and_stores_oslo_fields(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")

    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Ring legen",
        "01.01.1999",
        due_at="2026-07-14T12:00:00Z",
        time="03:15",
        timezone="Europe/Oslo",
        reference_time=NOW,
    )

    reminder = row(manager)
    assert reminder["id"] == reminder_id
    assert reminder["due_at"] == "2026-07-14T14:00:00+02:00"
    assert reminder["due_date"] == "14.07.2026"
    assert reminder["time"] == "14:00"
    assert reminder["timezone"] == "Europe/Oslo"
    assert reminder["created_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_add_date_only_defaults_to_nine_before_yearless_selection(tmp_path):
    before = datetime(2026, 7, 14, 8, 0, tzinfo=OSLO)
    after = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)
    early = ReminderManager(tmp_path / "early.json")
    late = ReminderManager(tmp_path / "late.json")

    await early.add_reminder_result(
        1, 7, "Ola", "Medisin", "14.07", reference_time=before
    )
    await late.add_reminder_result(
        1, 7, "Ola", "Medisin", "14.07", reference_time=after
    )

    assert row(early)["due_at"] == "2026-07-14T09:00:00+02:00"
    assert row(late)["due_at"] == "2027-07-14T09:00:00+02:00"
    assert row(early)["time"] == row(late)["time"] == "09:00"


@pytest.mark.asyncio
async def test_add_checklist_has_no_temporal_authority_or_recurrence_anchor(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")

    await manager.add_reminder_result(
        1, 7, "Ola", "Kjøp melk", reference_time=NOW
    )

    reminder = row(manager)
    assert reminder["due_at"] is None
    assert reminder["due_date"] is None
    assert reminder["time"] is None
    assert reminder["timezone"] == "Europe/Oslo"
    assert reminder["recurrence_anchor_local"] is None
    assert reminder["recurrence_sequence"] is None


@pytest.mark.asyncio
async def test_time_only_edit_of_checklist_fails_before_write_with_missing_date(
    tmp_path,
):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1, 7, "Ola", "Kjøp melk", reference_time=NOW
    )
    before_root = manager.reminders
    before = copy.deepcopy(before_root)
    before_bytes = manager.storage_path.read_bytes()

    with pytest.raises(ValueError, match="^missing_date$"):
        await manager.edit_reminder_result(
            1,
            reminder_id=reminder_id,
            time="14:00",
            reference_time=NOW,
        )

    assert_unchanged(manager, before_root, before, before_bytes)


@pytest.mark.asyncio
async def test_edit_lookup_miss_is_one_finite_prewrite_not_found(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    await manager.add_reminder_result(
        1, 7, "Ola", "Finnes", reference_time=NOW
    )
    before_root = manager.reminders
    before = copy.deepcopy(before_root)
    before_bytes = manager.storage_path.read_bytes()

    for selector in (
        {"index": 2},
        {"reminder_id": "rem_1_missing"},
    ):
        with pytest.raises(ValueError, match="^not_found$"):
            await manager.edit_reminder_result(
                1,
                reference_time=NOW,
                **selector,
            )

    assert_unchanged(manager, before_root, before, before_bytes)


@pytest.mark.parametrize(
    ("reference_time", "expected_due_at"),
    [
        (
            datetime(2026, 7, 14, 8, 0, tzinfo=OSLO),
            "2026-07-14T09:00:00+02:00",
        ),
        (
            datetime(2026, 7, 14, 12, 0, tzinfo=OSLO),
            "2027-07-14T09:00:00+02:00",
        ),
    ],
)
@pytest.mark.asyncio
async def test_yearless_date_flows_parser_validator_manager_with_one_reference(
    tmp_path,
    reference_time,
    expected_due_at,
):
    parsed = parse_reminder_command(
        "påminn meg om medisinen 14.07",
        now=reference_time,
        temporal_resolver=TemporalResolver(),
    )
    assert parsed is not None
    canonical = validate_intent_payload(BotIntent.REMINDER_CREATE, parsed)
    manager = ReminderManager(tmp_path / f"{reference_time.hour}.json")

    await manager.add_reminder_result(
        1,
        7,
        "Ola",
        canonical["text"],
        canonical.get("due_date"),
        canonical.get("recurrence"),
        due_at=canonical.get("due_at"),
        time=canonical.get("time"),
        timezone=canonical.get("timezone", "Europe/Oslo"),
        reference_time=reference_time,
    )

    reminder = row(manager)
    assert reminder["due_at"] == expected_due_at
    assert reminder["time"] == "09:00"
    assert reminder["created_at"] == reference_time.isoformat()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"due_at": "2026-07-14T14:00:00"}, "invalid_due_at"),
        ({"due_date": "14.07.2026", "timezone": "UTC"}, "invalid_timezone"),
        ({"recurrence": "daily"}, "invalid_recurrence"),
        (
            {"due_at": "2026-07-14T14:00:00+02:00", "recurrence": "hourly"},
            "invalid_recurrence",
        ),
    ],
)
@pytest.mark.asyncio
async def test_add_rejects_invalid_temporal_state_before_write(tmp_path, kwargs, code):
    path = tmp_path / f"{code}.json"
    manager = ReminderManager(path)

    with pytest.raises(ValueError, match=code):
        await manager.add_reminder_result(
            1,
            7,
            "Ola",
            "Ugyldig",
            reference_time=NOW,
            **kwargs,
        )

    assert manager.reminders == {}
    assert not path.exists()


@pytest.mark.asyncio
async def test_recurring_add_stores_nominal_wall_anchor_and_sequence_zero(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")

    await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Daglig",
        recurrence="daily",
        due_at="2026-03-28T02:30:00+01:00",
        reference_time=NOW,
    )

    reminder = row(manager)
    assert reminder["recurrence_anchor_local"] == "2026-03-28T02:30:00"
    assert reminder["recurrence_sequence"] == 0


@pytest.mark.asyncio
async def test_result_apis_use_supplied_reference_without_reading_injected_clock(
    tmp_path,
):
    class ExplodingClock:
        def now(self):
            raise AssertionError("result API recaptured clock")

        def epoch(self):
            raise AssertionError("result API read epoch")

    manager = ReminderManager(
        tmp_path / "reminders.json",
        clock=ExplodingClock(),
    )
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Eksakt",
        due_at="2026-07-15T09:00:00+02:00",
        reference_time=NOW,
    )
    await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        text="Eksakt igjen",
        reference_time=NOW,
    )
    result = await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=NOW,
    )

    assert result == (True, "Eksakt igjen", None)
    assert row(manager)["created_at"] == NOW.isoformat()
    assert row(manager)["completed_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_edit_canonical_aliases_win_and_omissions_preserve_schedule(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Original",
        recurrence="weekly",
        due_at="2026-07-20T10:00:00+02:00",
        reference_time=NOW,
    )
    anchor = row(manager)["recurrence_anchor_local"]

    updated = await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        title="Legacy title",
        text="Canonical title",
        date="21.07.2026",
        due_date="22.07.2026",
        reference_time=NOW,
    )

    assert updated["text"] == "Canonical title"
    assert updated["due_at"] == "2026-07-22T10:00:00+02:00"
    assert updated["due_date"] == "22.07.2026"
    assert updated["time"] == "10:00"
    assert updated["recurrence"] == "weekly"
    assert updated["recurrence_anchor_local"] == "2026-07-22T10:00:00"
    assert updated["recurrence_anchor_local"] != anchor
    assert updated["recurrence_sequence"] == 0
    assert updated["updated_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_explicit_due_at_edit_overrides_disagreeing_display_fields(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1, 7, "Ola", "Original", reference_time=NOW
    )

    updated = await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        due_at="2026-12-24T18:30:00+01:00",
        due_date="01.01.2001",
        time="03:00",
        reference_time=NOW,
    )

    assert updated["due_at"] == "2026-12-24T18:30:00+01:00"
    assert updated["due_date"] == "24.12.2026"
    assert updated["time"] == "18:30"


@pytest.mark.asyncio
async def test_explicit_timing_clear_requires_recurrence_clear_in_same_edit(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Daglig",
        recurrence="daily",
        due_at="2026-07-15T09:00:00+02:00",
        reference_time=NOW,
    )
    before_root = manager.reminders
    before = copy.deepcopy(before_root)
    before_bytes = manager.storage_path.read_bytes()

    with pytest.raises(ValueError, match="invalid_recurrence"):
        await manager.edit_reminder_result(
            1,
            reminder_id=reminder_id,
            due_at=None,
            reference_time=NOW,
        )
    assert_unchanged(manager, before_root, before, before_bytes)

    cleared = await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        due_at=None,
        recurrence=None,
        reference_time=NOW,
    )
    assert cleared["due_at"] is None
    assert cleared["due_date"] is None
    assert cleared["time"] is None
    assert cleared["recurrence"] is None
    assert cleared["recurrence_anchor_local"] is None
    assert cleared["recurrence_sequence"] is None


@pytest.mark.asyncio
async def test_recurrence_only_edit_preserves_scheduled_occurrence_but_rejects_checklist(
    tmp_path,
):
    scheduled = ReminderManager(tmp_path / "scheduled.json")
    checklist = ReminderManager(tmp_path / "checklist.json")
    scheduled_id = await scheduled.add_reminder_result(
        1,
        7,
        "Ola",
        "Planlagt",
        due_at="2026-07-20T09:00:00+02:00",
        reference_time=NOW,
    )
    checklist_id = await checklist.add_reminder_result(
        1, 7, "Ola", "Liste", reference_time=NOW
    )
    before_root = checklist.reminders
    before = copy.deepcopy(before_root)
    before_bytes = checklist.storage_path.read_bytes()

    updated = await scheduled.edit_reminder_result(
        1,
        reminder_id=scheduled_id,
        recurrence="monthly",
        reference_time=NOW,
    )
    assert updated["due_at"] == "2026-07-20T09:00:00+02:00"
    assert updated["recurrence_anchor_local"] == "2026-07-20T09:00:00"
    assert updated["recurrence_sequence"] == 0

    with pytest.raises(ValueError, match="invalid_recurrence"):
        await checklist.edit_reminder_result(
            1,
            reminder_id=checklist_id,
            recurrence="weekly",
            reference_time=NOW,
        )
    assert_unchanged(checklist, before_root, before, before_bytes)


@pytest.mark.asyncio
async def test_stable_id_edit_does_not_follow_changed_display_position(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    first = await manager.add_reminder_result(
        1, 7, "Ola", "Første", reference_time=NOW
    )
    second = await manager.add_reminder_result(
        1, 8, "Kari", "Andre", reference_time=NOW
    )
    manager.reminders["1"][0]["created_at"] = "2026-07-15T10:00:00+02:00"
    manager.reminders["1"][1]["created_at"] = "2026-07-15T09:00:00+02:00"

    updated = await manager.edit_reminder_result(
        1,
        index=1,
        reminder_id=first,
        text="Eksakt",
        reference_time=NOW,
    )

    assert updated["id"] == first
    by_id = {item["id"]: item["text"] for item in manager.reminders["1"]}
    assert by_id == {first: "Eksakt", second: "Andre"}


@pytest.mark.parametrize(
    ("due_at", "recurrence", "reference", "expected", "sequence"),
    [
        (
            "2026-01-31T09:00:00+01:00",
            "monthly",
            "2026-01-31T09:00:00+01:00",
            "2026-02-28T09:00:00+01:00",
            1,
        ),
        (
            "2024-02-29T09:00:00+01:00",
            "yearly",
            "2024-02-29T09:00:00+01:00",
            "2025-02-28T09:00:00+01:00",
            1,
        ),
        (
            "2026-03-28T09:00:00+01:00",
            "daily",
            "2026-03-28T09:00:00+01:00",
            "2026-03-29T09:00:00+02:00",
            1,
        ),
        (
            "2026-10-24T09:00:00+02:00",
            "daily",
            "2026-10-24T09:00:00+02:00",
            "2026-10-25T09:00:00+01:00",
            1,
        ),
        (
            "2026-07-01T09:00:00+02:00",
            "daily",
            "2026-07-03T10:00:00+02:00",
            "2026-07-04T09:00:00+02:00",
            3,
        ),
        (
            "2026-07-01T09:00:00+02:00",
            "biweekly",
            "2026-08-05T10:00:00+02:00",
            "2026-08-12T09:00:00+02:00",
            3,
        ),
    ],
)
def test_advance_due_at_preserves_anchor_phase_and_catches_up(
    due_at, recurrence, reference, expected, sequence
):
    due = datetime.fromisoformat(due_at)
    result = advance_due_at(
        due,
        recurrence,
        reference_time=datetime.fromisoformat(reference),
        anchor_local=due.astimezone(OSLO).replace(tzinfo=None),
    )
    assert result is not None
    advanced, next_sequence = result
    assert advanced.isoformat() == expected
    assert next_sequence == sequence


def test_monthly_recurrence_catchup_is_bounded_to_max_calendar_steps():
    due = datetime(2000, 1, 1, 9, 0, tzinfo=OSLO)
    reference = datetime(2200, 1, 1, 9, 0, tzinfo=OSLO)

    with pytest.raises(ValueError, match="^recurrence_catchup_limit$"):
        advance_due_at(
            due,
            "monthly",
            reference_time=reference,
            anchor_local=due.replace(tzinfo=None),
        )

    assert MAX_CALENDAR_STEPS == 2400


def test_yearly_leap_anchor_returns_to_february_29_after_clamped_years():
    anchor_due = datetime(2024, 2, 29, 9, 0, tzinfo=OSLO)
    anchor = anchor_due.replace(tzinfo=None)
    current = anchor_due
    sequence = 0
    occurrences = []

    for _ in range(4):
        advanced = advance_due_at(
            current,
            "yearly",
            reference_time=current,
            anchor_local=anchor,
            sequence=sequence,
        )
        assert advanced is not None
        current, sequence = advanced
        occurrences.append(current.isoformat())

    assert occurrences == [
        "2025-02-28T09:00:00+01:00",
        "2026-02-28T09:00:00+01:00",
        "2027-02-28T09:00:00+01:00",
        "2028-02-29T09:00:00+01:00",
    ]
    assert sequence == 4


def test_daily_recurrence_shifts_gap_then_returns_to_nominal_wall_time():
    due = datetime.fromisoformat("2026-03-28T02:30:00+01:00")
    anchor = due.astimezone(OSLO).replace(tzinfo=None)

    first = advance_due_at(
        due,
        "daily",
        reference_time=due,
        anchor_local=anchor,
    )
    assert first is not None
    gap, sequence = first
    assert gap.isoformat() == "2026-03-29T03:30:00+02:00"
    assert sequence == 1

    second = advance_due_at(
        gap,
        "daily",
        reference_time=gap,
        anchor_local=anchor,
        sequence=sequence,
    )
    assert second is not None
    restored, sequence = second
    assert restored.isoformat() == "2026-03-30T02:30:00+02:00"
    assert sequence == 2


def test_daily_recurrence_chooses_fold_zero_and_uses_utc_for_catchup():
    due = datetime.fromisoformat("2026-10-24T02:30:00+02:00")
    anchor = due.astimezone(OSLO).replace(tzinfo=None)
    first = advance_due_at(
        due,
        "daily",
        reference_time=due,
        anchor_local=anchor,
    )
    assert first is not None
    folded, sequence = first
    assert folded.isoformat() == "2026-10-25T02:30:00+02:00"
    assert folded.fold == 0

    after_fold_zero = datetime(2026, 10, 25, 2, 15, tzinfo=OSLO, fold=1)
    caught_up = advance_due_at(
        due,
        "daily",
        reference_time=after_fold_zero,
        anchor_local=anchor,
    )
    assert caught_up is not None
    assert caught_up[0].isoformat() == "2026-10-26T02:30:00+01:00"
    assert caught_up[1] == 2


@pytest.mark.asyncio
async def test_completion_updates_all_due_fields_and_monthly_anchor_sequence(tmp_path):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Månedlig",
        recurrence="monthly",
        due_at="2026-01-31T09:00:00+01:00",
        reference_time=datetime(2026, 1, 1, 9, 0, tzinfo=OSLO),
    )

    first = await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=datetime(2026, 1, 31, 9, 0, tzinfo=OSLO),
    )
    assert first == (True, "Månedlig", "28.02.2026")
    reminder = row(manager)
    assert reminder["due_at"] == "2026-02-28T09:00:00+01:00"
    assert reminder["due_date"] == "28.02.2026"
    assert reminder["time"] == "09:00"
    assert reminder["recurrence_sequence"] == 1

    second = await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=datetime(2026, 2, 28, 9, 0, tzinfo=OSLO),
    )
    assert second == (True, "Månedlig", "31.03.2026")
    reminder = row(manager)
    assert reminder["due_at"] == "2026-03-31T09:00:00+02:00"
    assert reminder["recurrence_anchor_local"] == "2026-01-31T09:00:00"
    assert reminder["recurrence_sequence"] == 2


@pytest.mark.asyncio
async def test_text_only_edit_after_clamp_preserves_phase_and_returns_to_31st(
    tmp_path,
):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Månedlig",
        recurrence="monthly",
        due_at="2026-01-31T09:00:00+01:00",
        reference_time=datetime(2026, 1, 1, 9, 0, tzinfo=OSLO),
    )
    await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=datetime(2026, 1, 31, 9, 0, tzinfo=OSLO),
    )
    anchor = row(manager)["recurrence_anchor_local"]
    sequence = row(manager)["recurrence_sequence"]

    edited = await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        text="Ny tekst",
        reference_time=datetime(2026, 2, 10, 9, 0, tzinfo=OSLO),
    )
    assert edited["recurrence_anchor_local"] == anchor
    assert edited["recurrence_sequence"] == sequence

    completed = await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=datetime(2026, 2, 28, 9, 0, tzinfo=OSLO),
    )
    assert completed == (True, "Ny tekst", "31.03.2026")


@pytest.mark.asyncio
async def test_explicit_schedule_edit_resets_sequence_and_removal_clears_anchor(
    tmp_path,
):
    manager = ReminderManager(tmp_path / "reminders.json")
    reminder_id = await manager.add_reminder_result(
        1,
        7,
        "Ola",
        "Månedlig",
        recurrence="monthly",
        due_at="2026-01-31T09:00:00+01:00",
        reference_time=datetime(2026, 1, 1, 9, 0, tzinfo=OSLO),
    )
    await manager.complete_reminder_result(
        1,
        reminder_id=reminder_id,
        reference_time=datetime(2026, 1, 31, 9, 0, tzinfo=OSLO),
    )
    assert row(manager)["recurrence_sequence"] == 1

    reset = await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        due_at="2026-04-15T16:00:00+02:00",
        reference_time=datetime(2026, 3, 1, 9, 0, tzinfo=OSLO),
    )
    assert reset["recurrence_anchor_local"] == "2026-04-15T16:00:00"
    assert reset["recurrence_sequence"] == 0

    removed = await manager.edit_reminder_result(
        1,
        reminder_id=reminder_id,
        recurrence=None,
        reference_time=datetime(2026, 3, 1, 9, 0, tzinfo=OSLO),
    )
    assert removed["due_at"] == "2026-04-15T16:00:00+02:00"
    assert removed["recurrence"] is None
    assert removed["recurrence_anchor_local"] is None
    assert removed["recurrence_sequence"] is None


@pytest.mark.asyncio
async def test_legacy_recurring_completion_bootstraps_anchor_atomically(tmp_path):
    path = tmp_path / "reminders.json"
    path.write_text(
        json.dumps(
            {
                "1": [
                    {
                        "id": "rem_1_legacy",
                        "user_id": "7",
                        "username": "Ola",
                        "text": "Legacy",
                        "due_at": "2026-01-31T09:00:00+01:00",
                        "due_date": "31.01.2026",
                        "time": "09:00",
                        "recurrence": "monthly",
                        "completed": False,
                        "created_at": "2025-01-01T09:00:00+01:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manager = ReminderManager(path)

    result = await manager.complete_reminder_result(
        1,
        reminder_id="rem_1_legacy",
        reference_time=datetime(2026, 1, 31, 9, 0, tzinfo=OSLO),
    )

    assert result == (True, "Legacy", "28.02.2026")
    reminder = row(manager)
    assert reminder["recurrence_anchor_local"] == "2026-01-31T09:00:00"
    assert reminder["recurrence_sequence"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["1"][0] == reminder

    second = await manager.complete_reminder_result(
        1,
        reminder_id="rem_1_legacy",
        reference_time=datetime(2026, 2, 28, 9, 0, tzinfo=OSLO),
    )
    assert second == (True, "Legacy", "31.03.2026")
    reminder = row(manager)
    assert reminder["due_at"] == "2026-03-31T09:00:00+02:00"
    assert reminder["due_date"] == "31.03.2026"
    assert reminder["time"] == "09:00"
    assert reminder["recurrence_anchor_local"] == "2026-01-31T09:00:00"
    assert reminder["recurrence_sequence"] == 2
    assert json.loads(path.read_text(encoding="utf-8"))["1"][0] == reminder


@pytest.mark.asyncio
async def test_legacy_date_only_recurrence_is_enriched_only_on_completion(tmp_path):
    path = tmp_path / "reminders.json"
    legacy = {
        "1": [
            {
                "id": "rem_1_date_only",
                "text": "Legacy dato",
                "due_date": "31.01.2026",
                "recurrence": "monthly",
                "completed": False,
                "created_at": "2025-01-01T09:00:00+01:00",
            }
        ]
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    manager = ReminderManager(path)
    before = path.read_bytes()
    assert row(manager) == legacy["1"][0]
    assert path.read_bytes() == before

    result = await manager.complete_reminder_result(
        1,
        reminder_id="rem_1_date_only",
        reference_time=datetime(2026, 1, 31, 9, 0, tzinfo=OSLO),
    )

    assert result == (True, "Legacy dato", "28.02.2026")
    reminder = row(manager)
    assert reminder["due_at"] == "2026-02-28T09:00:00+01:00"
    assert reminder["time"] == "09:00"
    assert reminder["timezone"] == "Europe/Oslo"
    assert reminder["recurrence_anchor_local"] == "2026-01-31T09:00:00"
    assert reminder["recurrence_sequence"] == 1


def test_advance_due_at_rejects_naive_and_invalid_sequence():
    aware = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)
    with pytest.raises(ValueError, match="naive_recurrence_datetime"):
        advance_due_at(
            datetime(2026, 7, 14, 12, 0),
            "daily",
            reference_time=aware,
        )
    with pytest.raises(ValueError, match="invalid_recurrence_sequence"):
        advance_due_at(
            aware,
            "daily",
            reference_time=aware,
            sequence=True,
        )
    assert (
        advance_due_at(aware, "hourly", reference_time=aware) is None
    )


def test_recurrence_ordering_is_by_utc_instant_across_fold():
    fold_zero = datetime(2026, 10, 25, 2, 30, tzinfo=OSLO, fold=0)
    fold_one_before_wall = datetime(2026, 10, 25, 2, 15, tzinfo=OSLO, fold=1)
    assert fold_zero.astimezone(timezone.utc) < fold_one_before_wall.astimezone(
        timezone.utc
    )
