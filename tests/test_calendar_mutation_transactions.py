from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from zoneinfo import ZoneInfo

from cal_system.calendar_manager import CalendarManager
from cal_system.google_calendar_manager import (
    ExternalOperationCancelled,
    GoogleCalendarManager,
)
from core.dispatch_result import (
    ExternalCommitState,
    ExternalMutationResult,
    ManagerMutationError,
    ManagerMutationCancelled,
)
from core.mutation_coordinator import MutationCoordinator
from features.birthday_manager import BirthdayManager, BirthdayWriteResult


OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=OSLO)


class FixedClock:
    def now(self):
        return NOW

    def epoch(self):
        return NOW.timestamp()


class ChangedGCal:
    enabled = True

    def __init__(self):
        self.create_calls = 0

    async def create_event_result(self, *args, **kwargs):
        self.create_calls += 1
        return ExternalMutationResult(
            True,
            ExternalCommitState.CHANGED,
            {"id": "remote-1", "htmlLink": "https://calendar.invalid/remote-1"},
        )

    async def update_event_result(self, event_id, *args, **kwargs):
        return ExternalMutationResult(
            True,
            ExternalCommitState.CHANGED,
            {"id": event_id, "htmlLink": f"https://calendar.invalid/{event_id}"},
        )

    async def delete_event_result(self, event_id):
        return ExternalMutationResult(
            True,
            ExternalCommitState.CHANGED,
            True,
        )


class UnknownGCal(ChangedGCal):
    async def create_event_result(self, *args, **kwargs):
        self.create_calls += 1
        return ExternalMutationResult(
            False,
            ExternalCommitState.UNKNOWN,
            error_code="external_commit_unknown",
        )


class ListedChangedGCal:
    enabled = True

    def __init__(self, events):
        self.events = events

    async def list_upcoming_events_result(self, days):
        return ExternalMutationResult(
            True,
            ExternalCommitState.CHANGED,
            self.events,
        )


class RejectedDeleteGCal(ChangedGCal):
    async def delete_event_result(self, event_id):
        return ExternalMutationResult(
            False,
            ExternalCommitState.UNCHANGED,
            error_code="external_rejected",
        )


class MissingDeleteGCal(ChangedGCal):
    async def delete_event_result(self, event_id):
        return ExternalMutationResult(
            False,
            ExternalCommitState.UNCHANGED,
            error_code="external_not_found",
        )


class UnknownDeleteGCal(ChangedGCal):
    async def delete_event_result(self, event_id):
        return ExternalMutationResult(
            False,
            ExternalCommitState.UNKNOWN,
            error_code="external_commit_unknown",
        )


class UnknownThenCancelledChangedGCal(ChangedGCal):
    def __init__(self):
        super().__init__()
        self.delete_calls = 0

    async def delete_event_result(self, event_id):
        self.delete_calls += 1
        if self.delete_calls == 1:
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNKNOWN,
                error_code="external_commit_unknown",
            )
        raise ExternalOperationCancelled(
            ExternalMutationResult(
                True,
                ExternalCommitState.CHANGED,
                True,
            )
        )


@pytest.mark.asyncio
async def test_calendar_create_save_failure_rolls_back_memory_and_bytes(tmp_path):
    path = tmp_path / "calendar.json"
    manager = CalendarManager(path, clock=FixedClock())
    seed = await manager.add_item_result(
        "g", "u", "User", "Seed", "16.07.2026", reference_time=NOW
    )
    before_root = deepcopy(manager.items)
    before_bytes = path.read_bytes()

    def fail(_candidate=None):
        raise OSError("sentinel")

    manager._save_data_sync = fail
    with pytest.raises(ManagerMutationError) as raised:
        await manager.add_item_result(
            "g",
            "u",
            "User",
            "New",
            "17.07.2026",
            reference_time=NOW,
        )

    assert raised.value.code == "storage_write_failed"
    assert raised.value.mutated is False
    assert manager.items == before_root
    assert path.read_bytes() == before_bytes
    assert seed["title"] == "Seed"


@pytest.mark.asyncio
async def test_calendar_validates_complete_state_before_first_write(tmp_path):
    path = tmp_path / "calendar.json"
    manager = CalendarManager(path, clock=FixedClock())
    with pytest.raises(ValueError, match="invalid_time"):
        await manager.add_item_result(
            "g",
            "u",
            "User",
            "Invalid",
            "16.07.2026",
            time_str="99:99",
            reference_time=NOW,
        )
    assert manager.items == {}
    assert not path.exists()

    created = await manager.add_item_result(
        "g", "u", "User", "Valid", "16.07.2026", reference_time=NOW
    )
    before = deepcopy(manager.items)
    before_bytes = path.read_bytes()
    with pytest.raises(ValueError, match="invalid_recurrence"):
        await manager.edit_item_result(
            item_id=created["id"],
            recurrence="sometimes",
            reference_time=NOW,
        )
    assert manager.items == before
    assert path.read_bytes() == before_bytes


@pytest.mark.asyncio
async def test_calendar_candidate_is_invisible_until_writer_commits(tmp_path):
    manager = CalendarManager(tmp_path / "calendar.json", clock=FixedClock())
    started = threading.Event()
    release = threading.Event()
    original = manager._save_data_sync

    def blocked(candidate=None):
        started.set()
        assert release.wait(2)
        original(candidate)

    manager._save_data_sync = blocked
    task = asyncio.create_task(
        manager.add_item_result(
            "g",
            "u",
            "User",
            "Hidden candidate",
            "16.07.2026",
            reference_time=NOW,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    assert manager.snapshot_pending_items(reference_time=NOW) == ()
    release.set()
    created = await task
    assert created["title"] == "Hidden candidate"
    assert [row["title"] for row in manager.snapshot_pending_items(reference_time=NOW)] == [
        "Hidden candidate"
    ]


@pytest.mark.asyncio
async def test_calendar_external_success_second_save_failure_keeps_pending_marker(tmp_path):
    path = tmp_path / "calendar.json"
    gcal = ChangedGCal()
    manager = CalendarManager(path, gcal, clock=FixedClock())
    original = manager._save_data_sync
    writes = 0

    def fail_second(candidate=None):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("sentinel")
        original(candidate)

    manager._save_data_sync = fail_second
    with pytest.raises(ManagerMutationError) as raised:
        await manager.add_item_result(
            "g",
            "u",
            "User",
            "Remote",
            "16.07.2026",
            reference_time=NOW,
        )

    assert raised.value.code == "external_state_changed_storage_failed"
    assert raised.value.mutated is True
    assert gcal.create_calls == 1
    record = manager.items[manager.SHARED_KEY][0]
    assert record["gcal_sync_pending"] is True
    assert record["gcal_event_id"] is None
    assert json.loads(path.read_text())[manager.SHARED_KEY][0] == record


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["edit", "complete", "delete", "clear"])
async def test_calendar_external_change_then_final_save_failure_is_truthful(
    tmp_path,
    operation,
):
    path = tmp_path / f"{operation}.json"
    manager = CalendarManager(path, ChangedGCal(), clock=FixedClock())
    created = await manager.add_item_result(
        "g",
        "u",
        "User",
        "Remote",
        "16.07.2026",
        gcal_event_id="remote-existing",
        reference_time=NOW,
    )
    original = manager._save_data_sync
    writes = 0

    def fail_second(candidate=None):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("sentinel")
        original(candidate)

    manager._save_data_sync = fail_second
    with pytest.raises(ManagerMutationError) as raised:
        if operation == "edit":
            await manager.edit_item_result(
                item_id=created["id"],
                title="Edited",
                reference_time=NOW,
            )
        elif operation == "complete":
            await manager.complete_item_result(
                "g",
                item_id=created["id"],
                reference_time=NOW,
            )
        elif operation == "delete":
            await manager.delete_item_result(
                "g",
                item_id=created["id"],
                reference_time=NOW,
            )
        else:
            await manager.clear_calendar_result("g", reference_time=NOW)

    assert raised.value.code == "external_state_changed_storage_failed"
    assert raised.value.mutated is True
    record = manager.items[manager.SHARED_KEY][0]
    if operation in {"edit", "complete"}:
        assert record["gcal_sync_pending"] is True
    else:
        assert record["delete_pending"] is True
    assert json.loads(path.read_text())[manager.SHARED_KEY][0] == record


@pytest.mark.asyncio
async def test_calendar_external_unknown_is_terminal_and_marker_is_durable(tmp_path):
    manager = CalendarManager(
        tmp_path / "calendar.json",
        UnknownGCal(),
        clock=FixedClock(),
    )
    with pytest.raises(ManagerMutationError) as raised:
        await manager.add_item_result(
            "g",
            "u",
            "User",
            "Unknown",
            "16.07.2026",
            reference_time=NOW,
        )

    assert raised.value.code == "external_commit_unknown"
    assert raised.value.commit_unknown is True
    assert raised.value.mutated is True
    assert manager.items[manager.SHARED_KEY][0]["gcal_sync_pending"] is True


@pytest.mark.asyncio
async def test_cancelled_provider_is_settled_before_calendar_truth_is_carried(tmp_path):
    started = threading.Event()
    release = threading.Event()
    gcal = GoogleCalendarManager(
        token_path=tmp_path / "token.json",
        credentials_path=tmp_path / "credentials.json",
    )
    gcal._enabled = True
    gcal._initialized = True

    def blocked_create(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return {"id": "remote-after-cancel", "htmlLink": "link"}

    gcal.create_event = blocked_create
    manager = CalendarManager(
        tmp_path / "calendar.json",
        gcal,
        clock=FixedClock(),
    )
    task = asyncio.create_task(
        manager.add_item_result(
            "g",
            "u",
            "User",
            "Cancel race",
            "16.07.2026",
            reference_time=NOW,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(ManagerMutationCancelled) as raised:
        await task
    assert raised.value.mutated is True
    assert raised.value.retryable is False
    record = manager.items[manager.SHARED_KEY][0]
    assert record["gcal_event_id"] == "remote-after-cancel"
    assert record["gcal_sync_pending"] is False
    assert json.loads((tmp_path / "calendar.json").read_text())[manager.SHARED_KEY][0] == record


@pytest.mark.asyncio
async def test_cancel_during_final_save_keeps_external_changed_truth(tmp_path):
    started = threading.Event()
    release = threading.Event()
    manager = CalendarManager(
        tmp_path / "calendar.json",
        ChangedGCal(),
        clock=FixedClock(),
    )
    original = manager._save_data_sync
    writes = 0

    def block_second(candidate=None):
        nonlocal writes
        writes += 1
        if writes == 2:
            started.set()
            assert release.wait(2)
        original(candidate)

    manager._save_data_sync = block_second
    task = asyncio.create_task(
        manager.add_item_result(
            "g",
            "u",
            "User",
            "Final save cancel",
            "16.07.2026",
            reference_time=NOW,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(ManagerMutationCancelled) as raised:
        await task
    assert raised.value.mutated is True
    assert raised.value.retryable is False
    record = manager.items[manager.SHARED_KEY][0]
    assert record["gcal_event_id"] == "remote-1"
    assert record["gcal_sync_pending"] is False


@pytest.mark.asyncio
async def test_cancelled_local_writers_settle_later_failure_without_publish(tmp_path):
    calendar_started = threading.Event()
    calendar_release = threading.Event()
    calendar = CalendarManager(tmp_path / "calendar.json", clock=FixedClock())

    def fail_calendar(candidate=None):
        calendar_started.set()
        assert calendar_release.wait(2)
        raise OSError("sentinel")

    calendar._save_data_sync = fail_calendar
    calendar_task = asyncio.create_task(
        calendar.add_item_result(
            "g", "u", "User", "Cancelled", "16.07.2026", reference_time=NOW
        )
    )
    assert await asyncio.to_thread(calendar_started.wait, 2)
    calendar_task.cancel()
    calendar_release.set()
    with pytest.raises(ManagerMutationCancelled) as calendar_cancel:
        await calendar_task
    assert calendar_cancel.value.code == "storage_write_failed"
    assert calendar_cancel.value.mutated is False
    assert calendar_cancel.value.retryable is True
    assert calendar.items == {}
    assert not (tmp_path / "calendar.json").exists()

    birthday_started = threading.Event()
    birthday_release = threading.Event()
    birthday = BirthdayManager(tmp_path / "birthdays.json")

    def fail_birthday(candidate=None):
        birthday_started.set()
        assert birthday_release.wait(2)
        raise OSError("sentinel")

    birthday._save_birthdays = fail_birthday
    birthday_task = asyncio.create_task(
        birthday.create_birthday_result(
            "g", "u", "User", 1, 2, reference_time=NOW
        )
    )
    assert await asyncio.to_thread(birthday_started.wait, 2)
    birthday_task.cancel()
    birthday_release.set()
    with pytest.raises(ManagerMutationCancelled) as birthday_cancel:
        await birthday_task
    assert birthday_cancel.value.code == "storage_write_failed"
    assert birthday_cancel.value.mutated is False
    assert birthday_cancel.value.retryable is True
    assert birthday.birthdays == {}
    assert not (tmp_path / "birthdays.json").exists()


@pytest.mark.asyncio
async def test_sync_carries_credential_change_on_noop_and_local_failure(tmp_path):
    no_op = CalendarManager(
        tmp_path / "noop.json",
        ListedChangedGCal([]),
        clock=FixedClock(),
    )
    result = await no_op.sync_from_gcal_result(reference_time=NOW)
    assert result.ok is True
    assert result.mutated is True
    assert (result.added, result.updated, result.removed) == (0, 0, 0)

    remote = {
        "id": "remote",
        "summary": "Remote",
        "start": {"dateTime": "2026-07-16T10:00:00+02:00"},
    }
    failing = CalendarManager(
        tmp_path / "failing.json",
        ListedChangedGCal([remote]),
        clock=FixedClock(),
    )
    failing._save_data_sync = lambda candidate=None: (_ for _ in ()).throw(
        OSError("sentinel")
    )
    with pytest.raises(ManagerMutationError) as raised:
        await failing.sync_from_gcal_result(reference_time=NOW)
    assert raised.value.code == "external_state_changed_storage_failed"
    assert raised.value.mutated is True
    assert failing.items == {}


@pytest.mark.asyncio
async def test_sync_forwards_the_identical_reference_when_supported(tmp_path):
    class CapturingGCal:
        enabled = True

        def __init__(self):
            self.reference_time = None

        async def list_upcoming_events_result(
            self,
            days,
            *,
            reference_time=None,
        ):
            self.reference_time = reference_time
            return ExternalMutationResult(
                True,
                ExternalCommitState.UNCHANGED,
                [],
            )

    gcal = CapturingGCal()
    manager = CalendarManager(
        tmp_path / "calendar.json",
        gcal,
        clock=FixedClock(),
    )
    result = await manager.sync_from_gcal_result(reference_time=NOW)
    assert result.ok is True
    assert gcal.reference_time is NOW


@pytest.mark.asyncio
async def test_clear_mixed_failure_retains_marker_and_unknown_dominates(tmp_path):
    for name, gcal, expected, commit_unknown in (
        ("rejected", RejectedDeleteGCal(), "storage_write_failed", False),
        ("unknown", UnknownDeleteGCal(), "external_commit_unknown", True),
    ):
        path = tmp_path / f"{name}.json"
        manager = CalendarManager(path, gcal, clock=FixedClock())
        manager.gcal = None
        await manager.add_item_result(
            "g", "u", "User", "Local", "16.07.2026", reference_time=NOW
        )
        manager.gcal = gcal
        await manager.add_item_result(
            "g",
            "u",
            "User",
            "Remote",
            "17.07.2026",
            gcal_event_id="remote",
            reference_time=NOW,
        )
        original = manager._save_data_sync
        writes = 0

        def fail_final(candidate=None):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("sentinel")
            original(candidate)

        manager._save_data_sync = fail_final
        with pytest.raises(ManagerMutationError) as raised:
            await manager.clear_calendar_result("g", reference_time=NOW)
        assert raised.value.code == expected
        assert raised.value.mutated is True
        assert raised.value.commit_unknown is commit_unknown
        rows = manager.items[manager.SHARED_KEY]
        assert len(rows) == 2
        assert next(row for row in rows if row["title"] == "Remote")[
            "delete_pending"
        ] is True
        assert json.loads(path.read_text()) == manager.items


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_final_save", [False, True])
async def test_clear_prior_unknown_dominates_later_cancelled_changed_delete(
    tmp_path,
    fail_final_save,
):
    path = tmp_path / f"dominance-{fail_final_save}.json"
    gcal = UnknownThenCancelledChangedGCal()
    manager = CalendarManager(path, gcal, clock=FixedClock())
    for index in (1, 2):
        await manager.add_item_result(
            "g",
            "u",
            "User",
            f"Remote {index}",
            f"{15 + index}.07.2026",
            gcal_event_id=f"remote-{index}",
            reference_time=NOW,
        )

    if fail_final_save:
        original = manager._save_data_sync
        writes = 0

        def fail_second(candidate=None):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("sentinel")
            original(candidate)

        manager._save_data_sync = fail_second

    with pytest.raises(ManagerMutationCancelled) as raised:
        await manager.clear_calendar_result("g", reference_time=NOW)
    assert raised.value.code == "external_commit_unknown"
    assert raised.value.mutated is True
    assert raised.value.retryable is False
    assert raised.value.commit_unknown is True
    assert json.loads(path.read_text()) == manager.items


@pytest.mark.asyncio
@pytest.mark.parametrize("writer_fails", [False, True])
async def test_clear_prior_unknown_dominates_outer_cancel_during_final_save(
    tmp_path,
    writer_fails,
):
    path = tmp_path / f"outer-cancel-{writer_fails}.json"
    gcal = UnknownDeleteGCal()
    manager = CalendarManager(path, clock=FixedClock())
    await manager.add_item_result(
        "g", "u", "User", "Local", "16.07.2026", reference_time=NOW
    )
    manager.gcal = gcal
    await manager.add_item_result(
        "g",
        "u",
        "User",
        "Remote",
        "17.07.2026",
        gcal_event_id="remote",
        reference_time=NOW,
    )
    started = threading.Event()
    release = threading.Event()
    original = manager._save_data_sync
    writes = 0

    def block_final(candidate=None):
        nonlocal writes
        writes += 1
        if writes == 2:
            started.set()
            assert release.wait(2)
            if writer_fails:
                raise OSError("sentinel")
        original(candidate)

    manager._save_data_sync = block_final
    task = asyncio.create_task(
        manager.clear_calendar_result("g", reference_time=NOW)
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(ManagerMutationCancelled) as raised:
        await task
    assert raised.value.code == "external_commit_unknown"
    assert raised.value.mutated is True
    assert raised.value.retryable is False
    assert raised.value.commit_unknown is True
    assert json.loads(path.read_text()) == manager.items


@pytest.mark.asyncio
async def test_delete_authoritative_absence_removes_local_record(tmp_path):
    manager = CalendarManager(
        tmp_path / "calendar.json",
        MissingDeleteGCal(),
        clock=FixedClock(),
    )
    created = await manager.add_item_result(
        "g",
        "u",
        "User",
        "Missing remotely",
        "16.07.2026",
        gcal_event_id="missing",
        reference_time=NOW,
    )
    deleted = await manager.delete_item_result(
        "g", item_id=created["id"], reference_time=NOW
    )
    assert deleted["deleted_count"] == 1
    assert manager.items[manager.SHARED_KEY] == []


@pytest.mark.asyncio
async def test_missing_or_malformed_provider_adapter_stays_pending_unknown(tmp_path):
    class MissingAdapter:
        enabled = True

    calendar = CalendarManager(
        tmp_path / "calendar.json",
        MissingAdapter(),
        clock=FixedClock(),
    )
    with pytest.raises(ManagerMutationError) as raised:
        await calendar.add_item_result(
            "g", "u", "User", "Pending", "16.07.2026", reference_time=NOW
        )
    assert raised.value.code == "external_commit_unknown"
    assert raised.value.commit_unknown is True
    assert calendar.items[calendar.SHARED_KEY][0]["gcal_sync_pending"] is True

    class MalformedBirthdayGCal:
        enabled = True

        async def create_event_result(self, **kwargs):
            return ExternalMutationResult(
                True,
                ExternalCommitState.CHANGED,
                {},
            )

    birthday = BirthdayManager(
        tmp_path / "birthdays.json",
        gcal_manager=MalformedBirthdayGCal(),
    )
    result = await birthday.create_birthday_result(
        "g", "u", "User", 1, 2, reference_time=NOW
    )
    assert result == BirthdayWriteResult(
        False,
        True,
        True,
        "external_commit_unknown",
        True,
    )
    assert birthday.snapshot_pending_user("g", "u")["gcal_event_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_calendar_malformed_cancel_carrier_never_finalizes_local_state(
    tmp_path,
    operation,
):
    class MalformedCarrierGCal:
        enabled = True

        async def create_event_result(self, *args, **kwargs):
            raise ExternalOperationCancelled(
                ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    {},
                )
            )

        async def update_event_result(self, *args, **kwargs):
            raise ExternalOperationCancelled(
                ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    {},
                )
            )

        async def delete_event_result(self, *args, **kwargs):
            raise ExternalOperationCancelled(
                ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    False,
                )
            )

    manager = CalendarManager(
        tmp_path / f"calendar-{operation}.json",
        MalformedCarrierGCal(),
        clock=FixedClock(),
    )
    if operation == "create":
        invoke = manager.add_item_result(
            "g", "u", "User", "Create", "16.07.2026", reference_time=NOW
        )
    else:
        created = await manager.add_item_result(
            "g",
            "u",
            "User",
            operation.title(),
            "16.07.2026",
            gcal_event_id="remote",
            reference_time=NOW,
        )
        if operation == "update":
            invoke = manager.edit_item_result(
                item_id=created["id"],
                title="Edited",
                reference_time=NOW,
            )
        else:
            invoke = manager.delete_item_result(
                "g",
                item_id=created["id"],
                reference_time=NOW,
            )

    with pytest.raises(ManagerMutationCancelled) as raised:
        await invoke
    assert raised.value.code == "external_commit_unknown"
    assert raised.value.commit_unknown is True
    assert raised.value.retryable is False
    record = manager.items[manager.SHARED_KEY][0]
    if operation == "delete":
        assert record["delete_pending"] is True
    else:
        assert record["gcal_sync_pending"] is True
    assert record.get("gcal_event_id") != ""


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "delete"])
async def test_birthday_malformed_cancel_carrier_never_finalizes_local_state(
    tmp_path,
    operation,
):
    class MalformedCarrierGCal:
        enabled = True

        async def create_event_result(self, **kwargs):
            raise ExternalOperationCancelled(
                ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    {},
                )
            )

        async def delete_event_result(self, event_id):
            raise ExternalOperationCancelled(
                ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    False,
                )
            )

    path = tmp_path / f"birthday-{operation}.json"
    if operation == "create":
        manager = BirthdayManager(path, gcal_manager=MalformedCarrierGCal())
        invoke = manager.create_birthday_result(
            "g", "u", "User", 1, 2, reference_time=NOW
        )
    else:
        manager = BirthdayManager(path)
        await manager.create_birthday_result(
            "g", "u", "User", 1, 2, reference_time=NOW
        )
        manager.birthdays["g"]["u"]["gcal_event_id"] = "remote"
        manager._save_birthdays(manager.birthdays)
        manager.gcal = MalformedCarrierGCal()
        invoke = manager.remove_birthday_result("g", "u")

    with pytest.raises(ManagerMutationCancelled) as raised:
        await invoke
    assert raised.value.code == "external_commit_unknown"
    assert raised.value.commit_unknown is True
    record = manager.snapshot_pending_user("g", "u")
    assert record is not None
    assert record["gcal_sync_pending"] is True


def test_calendar_snapshots_separate_visible_targets_from_clear_ids(tmp_path):
    manager = CalendarManager(tmp_path / "calendar.json", clock=FixedClock())
    manager.items = {
        manager.SHARED_KEY: [
            {"id": "active", "title": "Active", "date": "16.07.2026", "completed": False},
            {"id": "done", "title": "Done", "date": "16.07.2026", "completed": True},
            {"id": "past", "title": "Past", "date": "14.07.2026", "completed": False},
            {"id": "far", "title": "Far", "date": "16.08.2027", "completed": False},
            {"id": "pending", "title": "Pending", "date": "17.07.2026", "delete_pending": True},
        ]
    }

    visible = manager.snapshot_pending_items(reference_time=NOW)
    assert [row["id"] for row in visible] == ["active"]
    assert manager.snapshot_all_item_ids() == (
        "active",
        "done",
        "far",
        "past",
        "pending",
    )
    visible[0]["title"] = "tampered"
    assert manager.items[manager.SHARED_KEY][0]["title"] == "Active"


@pytest.mark.asyncio
async def test_concurrent_calendar_writers_keep_both_updates(tmp_path):
    coordinator = MutationCoordinator()
    manager = CalendarManager(
        tmp_path / "calendar.json",
        clock=FixedClock(),
        mutation_coordinator=coordinator,
    )
    await asyncio.gather(
        manager.add_item_result("g1", "u1", "One", "One", "16.07.2026", reference_time=NOW),
        manager.add_item_result("g2", "u2", "Two", "Two", "17.07.2026", reference_time=NOW),
    )
    assert {row["title"] for row in manager.items[manager.SHARED_KEY]} == {"One", "Two"}
    assert {row["title"] for row in json.loads((tmp_path / "calendar.json").read_text())[manager.SHARED_KEY]} == {"One", "Two"}


@pytest.mark.asyncio
async def test_typed_edit_distinguishes_omitted_recurrence_from_explicit_clear(tmp_path):
    manager = CalendarManager(tmp_path / "calendar.json", clock=FixedClock())
    created = await manager.add_item_result(
        "g",
        "u",
        "User",
        "Recurring",
        "16.07.2026",
        recurrence="weekly",
        reference_time=NOW,
    )
    renamed = await manager.edit_item_result(
        item_id=created["id"],
        title="Still recurring",
        reference_time=NOW,
    )
    assert renamed["recurrence"] == "weekly"

    cleared = await manager.edit_item_result(
        item_id=created["id"],
        recurrence=None,
        reference_time=NOW,
    )
    assert cleared["recurrence"] is None
    assert json.loads((tmp_path / "calendar.json").read_text())[manager.SHARED_KEY][0]["recurrence"] is None

    restored = await manager.edit_item_result(
        item_id=created["id"],
        recurrence="weekly",
        reference_time=NOW,
    )
    assert restored["recurrence"] == "weekly"
    with pytest.raises(RuntimeError, match="use_async_result_api"):
        manager.edit_item(1, title="Legacy edit", recurrence=None)


def test_calendar_legacy_projection_is_offline_and_preserves_shape(tmp_path):
    manager = CalendarManager(tmp_path / "calendar.json", clock=FixedClock())
    created = manager.add_item(
        "g",
        "u",
        "User",
        "Recurring",
        "16.07.2026",
        recurrence="weekly",
    )
    assert isinstance(created, dict)
    edited = manager.edit_item(1, title="Legacy edit", recurrence=None)
    assert edited["title"] == "Legacy edit"
    assert edited["recurrence"] == "weekly"


@pytest.mark.asyncio
async def test_birthday_create_only_and_first_save_rollback(tmp_path):
    path = tmp_path / "birthdays.json"
    manager = BirthdayManager(path)
    first = await manager.create_birthday_result(
        "g", "u", "User", 1, 2, 1990, reference_time=NOW
    )
    duplicate = await manager.create_birthday_result(
        "g", "u", "Other", 2, 3, 1991, reference_time=NOW
    )
    assert first == BirthdayWriteResult(True, True, False)
    assert duplicate.error_code == "already_exists"
    before = deepcopy(manager.birthdays)
    before_bytes = path.read_bytes()
    manager._save_birthdays = lambda candidate=None: (_ for _ in ()).throw(OSError("sentinel"))
    failed = await manager.create_birthday_result(
        "g", "v", "Other", 2, 3, 1991, reference_time=NOW
    )
    assert failed == BirthdayWriteResult(False, False, False, "storage_write_failed")
    assert manager.birthdays == before
    assert path.read_bytes() == before_bytes


@pytest.mark.asyncio
async def test_birthday_provider_success_second_save_failure_retains_pending(tmp_path):
    path = tmp_path / "birthdays.json"
    gcal = ChangedGCal()
    manager = BirthdayManager(path, gcal_manager=gcal)
    original = manager._save_birthdays
    writes = 0

    def fail_second(candidate=None):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("sentinel")
        original(candidate)

    manager._save_birthdays = fail_second
    result = await manager.create_birthday_result(
        "g", "u", "User", 1, 2, 1990, reference_time=NOW
    )
    assert result == BirthdayWriteResult(
        False,
        True,
        True,
        "external_state_changed_storage_failed",
    )
    record = manager.snapshot_pending_user("g", "u")
    assert record["gcal_sync_pending"] is True
    assert record["gcal_event_id"] is None


@pytest.mark.asyncio
async def test_cancelled_birthday_provider_settles_and_publishes_remote_id(tmp_path):
    started = threading.Event()
    release = threading.Event()
    gcal = GoogleCalendarManager(
        token_path=tmp_path / "token.json",
        credentials_path=tmp_path / "credentials.json",
    )
    gcal._enabled = True
    gcal._initialized = True

    def blocked_create(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return {"id": "birthday-remote"}

    gcal.create_event = blocked_create
    manager = BirthdayManager(tmp_path / "birthdays.json", gcal_manager=gcal)
    task = asyncio.create_task(
        manager.create_birthday_result(
            "g",
            "u",
            "User",
            1,
            2,
            1990,
            reference_time=NOW,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(ManagerMutationCancelled) as raised:
        await task
    assert raised.value.mutated is True
    assert raised.value.retryable is False
    record = manager.snapshot_pending_user("g", "u")
    assert record["gcal_event_id"] == "birthday-remote"
    assert record["gcal_sync_pending"] is False


@pytest.mark.asyncio
async def test_concurrent_birthday_create_has_one_winner(tmp_path):
    manager = BirthdayManager(tmp_path / "birthdays.json")
    one, two = await asyncio.gather(
        manager.create_birthday_result("g", "u", "One", 1, 2, reference_time=NOW),
        manager.create_birthday_result("g", "u", "Two", 2, 3, reference_time=NOW),
    )
    assert sorted(result.success for result in (one, two)) == [False, True]
    assert sorted(result.error_code or "" for result in (one, two)) == ["", "already_exists"]


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_missing", [False, True])
async def test_birthday_edit_clears_old_remote_id_before_replacement(
    tmp_path,
    delete_missing,
):
    class ReplacementGCal:
        enabled = True

        async def delete_event_result(self, event_id):
            if delete_missing:
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="external_not_found",
                )
            return ExternalMutationResult(
                True,
                ExternalCommitState.CHANGED,
                True,
            )

        async def create_event_result(self, **kwargs):
            if delete_missing:
                return ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    {"id": "replacement"},
                )
            return ExternalMutationResult(
                False,
                ExternalCommitState.UNKNOWN,
                error_code="external_commit_unknown",
            )

    path = tmp_path / "birthdays.json"
    manager = BirthdayManager(path)
    await manager.create_birthday_result(
        "g", "u", "User", 1, 2, 1990, reference_time=NOW
    )
    manager.birthdays["g"]["u"]["gcal_event_id"] = "old"
    manager._save_birthdays(manager.birthdays)
    manager.gcal = ReplacementGCal()

    result = await manager.edit_birthday_by_user_id_result(
        "g", "u", 2, 3, 1990, reference_time=NOW
    )
    record = manager.snapshot_pending_user("g", "u")
    if delete_missing:
        assert result == BirthdayWriteResult(True, True, False)
        assert record["gcal_event_id"] == "replacement"
        assert record["gcal_sync_pending"] is False
    else:
        assert result == BirthdayWriteResult(
            False,
            True,
            True,
            "external_commit_unknown",
            True,
        )
        assert record["gcal_event_id"] is None
        assert record["gcal_sync_pending"] is True
    assert json.loads(path.read_text())["g"]["u"] == record
