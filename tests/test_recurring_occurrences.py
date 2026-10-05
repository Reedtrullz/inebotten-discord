"""Recurring series must keep their original schedule across completions."""
from datetime import date, datetime, time, timedelta, timezone
import importlib
import importlib.util
import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.event_schema import Clock
from cal_system.reminder_manager import ReminderManager
from core.request_context import RequestContext, request_scope
from features.calendar_handler import CalendarHandler


def fixed_clock(year=2027):
    return Clock(wall=lambda: datetime(year, 1, 1, tzinfo=timezone.utc), monotonic=lambda: 1)


def recurrence_module():
    spec = importlib.util.find_spec("cal_system.recurrence")
    assert spec is not None, "the recurring-series model has not been added"
    return importlib.import_module("cal_system.recurrence")


def recurrence_actor():
    return RequestContext('recurrence-test', '7', '9', None, 'no', 'dm')


def recurrence_message(content):
    return SimpleNamespace(content=content, author=SimpleNamespace(id=7, name='Tester'),
        channel=SimpleNamespace(id=9), guild=None)


def recurrence_handler(calendar):
    monitor = SimpleNamespace(calendar=calendar, nlp_parser=None,
        loc=SimpleNamespace(current_lang='no'), client=None, rate_limiter=None)
    handler = CalendarHandler(monitor)
    handler.send_response = AsyncMock()
    return handler


def test_calendar_monthly_completion_returns_to_the_anchor_day(tmp_path):
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json", clock=fixed_clock())
    item = calendar.add_item(
        "guild", "user", "User", "Månedsmøte", "31.01.2027",
        time_str="09:00", recurrence="monthly", duration_minutes=60,
    )

    assert calendar.complete_item("guild", item_id=item["id"])[2] == "28.02.2027"
    assert calendar.complete_item("guild", item_id=item["id"])[2] == "31.03.2027"


def test_reminder_monthly_completion_returns_to_the_anchor_day(tmp_path):
    reminders = ReminderManager(storage_path=tmp_path / "reminders.json", clock=fixed_clock())
    reminder_id = reminders.add_reminder(
        "guild", "user", "User", "Betal regning", "31.01.2027", recurrence="monthly",
    )

    assert reminders.complete_reminder("guild", reminder_id=reminder_id)[2] == "28.02.2027"
    assert reminders.complete_reminder("guild", reminder_id=reminder_id)[2] == "31.03.2027"


def test_monthly_expansion_reuses_the_anchor_after_a_short_month():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    series = recurrence.Series(
        "series-month-end", EventTime("event", date(2027, 1, 31), time(9), "Europe/Oslo", False, 60),
        {"frequency": "monthly"},
    )

    result = recurrence.expand_series(series, date(2027, 1, 1), date(2027, 3, 31))

    assert [item.original_start.date().isoformat() for item in result] == [
        "2027-01-31", "2027-02-28", "2027-03-31",
    ]
    assert all(item.original_start.tzinfo is not None for item in result)


def test_weekday_rule_after_anchor_does_not_create_an_occurrence_before_anchor():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    anchor = EventTime('event', date(2027, 1, 4), time(9), 'Europe/Oslo', False, 30)
    series = recurrence.Series('weekday-series', anchor,
        {'frequency': 'weekly', 'weekday': 'WE'}, end_count=3)

    assert [recurrence.occurrence_at(series, index).original_start.date() for index in range(3)] == [
        date(2027, 1, 4), date(2027, 1, 6), date(2027, 1, 13),
    ]


def test_yearly_leap_day_returns_to_february_29():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    series = recurrence.Series(
        "series-leap", EventTime("event", date(2028, 2, 29), time(9), "Europe/Oslo", False, 30),
        {"frequency": "yearly"},
    )

    result = recurrence.expand_series(series, date(2028, 1, 1), date(2032, 12, 31))

    assert [item.original_start.date().isoformat() for item in result] == [
        "2028-02-29", "2029-02-28", "2030-02-28", "2031-02-28", "2032-02-29",
    ]


def test_occurrence_identity_and_original_start_survive_move_and_restart():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    series = recurrence.Series(
        "series-move", EventTime("event", date(2027, 1, 4), time(9), "Europe/Oslo", False, 30),
        {"frequency": "weekly"},
    )
    first = recurrence.expand_series(series, date(2027, 1, 1), date(2027, 1, 5))[0]
    moved = recurrence.Occurrence(
        first.occurrence_id, first.series_id, first.original_start, "planned",
        {"date": "05.01.2027", "time": "11:30"},
    )
    restored = recurrence.Occurrence.from_document(moved.to_document())
    expanded = recurrence.expand_series(
        series, date(2027, 1, 1), date(2027, 1, 5), exceptions={restored.occurrence_id: restored},
    )

    assert expanded[0].occurrence_id == first.occurrence_id
    assert expanded[0].original_start == first.original_start
    assert expanded[0].override == {"date": "05.01.2027", "time": "11:30"}


def test_end_count_and_end_date_boundaries_are_inclusive():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    anchor = EventTime("task", date(2027, 1, 1), None, "Europe/Oslo", True)
    counted = recurrence.Series("series-count", anchor, {"frequency": "weekly"}, end_count=3)
    dated = recurrence.Series("series-date", anchor, {"frequency": "weekly"}, end_date=date(2027, 1, 15))

    assert [value.original_start.date().isoformat() for value in recurrence.expand_series(
        counted, date(2027, 1, 1), date(2027, 2, 1),
    )] == ["2027-01-01", "2027-01-08", "2027-01-15"]
    assert [value.original_start.date().isoformat() for value in recurrence.expand_series(
        dated, date(2027, 1, 1), date(2027, 2, 1),
    )] == ["2027-01-01", "2027-01-08", "2027-01-15"]


def test_skipped_completed_and_moved_occurrences_remain_distinct_exceptions():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    series = recurrence.Series(
        "series-exceptions", EventTime("event", date(2027, 1, 4), time(9), "Europe/Oslo", False, 30),
        {"frequency": "weekly"},
    )
    originals = recurrence.expand_series(series, date(2027, 1, 1), date(2027, 1, 20))
    exceptions = {
        originals[0].occurrence_id: recurrence.Occurrence(
            originals[0].occurrence_id, series.series_id, originals[0].original_start, "skipped",
        ),
        originals[1].occurrence_id: recurrence.Occurrence(
            originals[1].occurrence_id, series.series_id, originals[1].original_start, "completed",
        ),
        originals[2].occurrence_id: recurrence.Occurrence(
            originals[2].occurrence_id, series.series_id, originals[2].original_start, "planned",
            {"date": "20.01.2027", "time": "11:00"},
        ),
    }

    restored = recurrence.expand_series(
        series, date(2027, 1, 1), date(2027, 1, 20), exceptions=exceptions,
    )

    assert [item.state for item in restored] == ["skipped", "completed", "planned"]
    assert restored[2].original_start.date().isoformat() == "2027-01-18"
    assert restored[2].override["date"] == "20.01.2027"


def test_google_rule_subset_parses_end_count_and_keeps_unsupported_rule_readable():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    recurrence = recurrence_module()
    parser = getattr(recurrence, "parse_google_recurrence", None)
    assert callable(parser), "Google recurrence imports need an explicit supported-subset parser"
    # A day <=28 shares the local and RFC monthly date semantics. Month-end
    # anchors are covered separately as opaque imports, never as clamped RRULEs.
    anchor = EventTime("event", date(2027, 1, 28), time(9), "Europe/Oslo", False, 60)

    supported = parser(["RRULE:FREQ=MONTHLY;COUNT=5"], anchor)
    unsupported = parser(["RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1"], anchor)

    assert supported["supported"] is True
    assert supported["rule"] == {"frequency": "monthly", "interval": 1}
    assert supported["end_count"] == 5
    assert unsupported["supported"] is False
    assert unsupported["raw"] == ["RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1"]
    assert "BYSETPOS" in unsupported["readable"]


def test_google_utc_until_maps_to_the_last_local_occurrence_date():
    EventTime = __import__("cal_system.event_schema", fromlist=["EventTime"]).EventTime
    parser = recurrence_module().parse_google_recurrence
    anchor = EventTime('event', date(2027, 1, 4), time(9), 'Europe/Oslo', False, 30)

    includes_monday = parser(['RRULE:FREQ=WEEKLY;UNTIL=20270118T080000Z'], anchor)
    ends_before_monday = parser(['RRULE:FREQ=WEEKLY;UNTIL=20270118T070000Z'], anchor)

    assert includes_monday['supported'] is True
    assert includes_monday['end_date'] == date(2027, 1, 18)
    assert ends_before_monday['end_date'] == date(2027, 1, 17)


def test_calendar_completion_keeps_the_series_anchor_and_occurrence_history(tmp_path):
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json", clock=fixed_clock())
    item = calendar.add_item(
        "guild", "user", "User", "Månedsmøte", "31.01.2027",
        time_str="09:00", recurrence="monthly", duration_minutes=60,
    )

    calendar.complete_item("guild", item_id=item["id"])
    calendar.complete_item("guild", item_id=item["id"])
    restored = CalendarManager(storage_path=tmp_path / "calendar.json", clock=fixed_clock())
    stored = restored.items["shared"][0]

    assert stored["series"]["series_id"] == item["id"]
    assert stored["series"]["anchor_time"]["date"] == "31.01.2027"
    assert stored["date"] == "31.03.2027"
    assert [entry["state"] for entry in stored["occurrences"].values()] == ["completed", "completed"]
    assert len({entry["occurrence_id"] for entry in stored["occurrences"].values()}) == 2


def test_end_count_completes_only_the_declared_number_of_occurrences(tmp_path):
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json", clock=fixed_clock())
    item = calendar.add_item(
        "guild", "user", "User", "Ukentlig", "04.01.2027",
        recurrence="weekly", end_count=2,
    )

    first = calendar.complete_item("guild", item_id=item["id"])
    second = tuple(calendar.complete_item("guild", item_id=item["id"]))
    third = tuple(calendar.complete_item("guild", item_id=item["id"]))

    assert first[2] == "11.01.2027"
    assert second == (True, "Ukentlig", None)
    assert third == (False, None, None)


def test_reminder_end_count_keeps_history_then_finishes_series(tmp_path):
    reminders = ReminderManager(storage_path=tmp_path / "reminders.json", clock=fixed_clock())
    reminder_id = reminders.add_reminder(
        "guild", "user", "User", "Ukentlig", "04.01.2027", recurrence="weekly", end_count=2,
    )

    first = reminders.complete_reminder("guild", reminder_id=reminder_id)
    second = reminders.complete_reminder("guild", reminder_id=reminder_id)
    third = reminders.complete_reminder("guild", reminder_id=reminder_id)
    saved = reminders.reminders["guild"][0]

    assert first[2] == "11.01.2027"
    assert second == (True, "Ukentlig", None)
    assert third == (False, None, None)
    assert saved["series"]["anchor_time"]["date"] == "04.01.2027"
    assert [entry["state"] for entry in saved["occurrences"].values()] == ["completed", "completed"]


def test_legacy_advanced_series_migration_keeps_backup_without_inventing_past(tmp_path):
    import asyncio
    import json

    path = tmp_path / "calendar.json"
    original = json.dumps({"shared": [{
        "id": "old-series", "scope_id": "shared", "user_id": "user", "username": "User",
        "title": "Gammelt månedsmøte", "date": "28.02.2027", "time": "09:00",
        "recurrence": "monthly", "completed_count": 1, "completed": False,
    }]}, ensure_ascii=False).encode()
    path.write_bytes(original)
    calendar = CalendarManager(storage_path=path, clock=fixed_clock())

    asyncio.run(calendar.setup())
    migrated = calendar.items["shared"][0]
    anchor = date.fromisoformat(migrated["series"]["anchor_time"]["date"][6:10] + "-"
                                + migrated["series"]["anchor_time"]["date"][3:5] + "-"
                                + migrated["series"]["anchor_time"]["date"][0:2])
    following = recurrence_module().expand_series(
        recurrence_module().Series.from_document(migrated["series"]), anchor, date(2027, 4, 30),
    )

    assert (tmp_path / "calendar.json.legacy-v0.bak").read_bytes() == original
    assert migrated["series"]["series_id"] == "old-series"
    assert migrated["recurrence_migration"]["recovered_before_anchor"] is False
    assert [item.original_start.date().isoformat() for item in following] == [
        "2027-02-28", "2027-03-28", "2027-04-28",
    ]


def test_legacy_advanced_reminder_migration_keeps_backup_and_diagnostic(tmp_path):
    import json

    path = tmp_path / "reminders.json"
    original = json.dumps({"guild": [{
        "id": "old-reminder", "user_id": "user", "username": "User", "text": "Månedsmedisin",
        "due_date": "28.02.2027", "recurrence": "monthly", "completed_count": 2,
        "created_at": "2026-01-01T00:00:00", "completed": False,
    }]}, ensure_ascii=False).encode()
    path.write_bytes(original)
    reminders = ReminderManager(storage_path=path, clock=fixed_clock())

    assert reminders.complete_reminder("guild", reminder_id="old-reminder")[2] == "28.03.2027"
    migrated = reminders.reminders["guild"][0]
    series = recurrence_module().Series.from_document(migrated["series"])

    assert (tmp_path / "reminders.json.legacy-v0.bak").read_bytes() == original
    assert migrated["recurrence_migration"] == {
        "status": "legacy_collapsed", "anchor_source": "stored_current_date",
        "recovered_before_anchor": False, "legacy_advanced_count": 2,
    }
    assert series.anchor_time.local_date == date(2027, 2, 28)
    assert migrated["series_next_index"] == 1
    assert len(migrated["occurrences"]) == 1


def test_recurring_delivery_key_is_occurrence_and_stage_across_restart(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult

    calendar = CalendarManager(storage_path=tmp_path / "calendar.json", clock=fixed_clock())
    item = calendar.add_item(
        "guild", "user", "User", "Møte", "04.01.2027", time_str="09:00",
        recurrence="weekly", duration_minutes=30,
    )
    first = recurrence_module().expand_series(
        recurrence_module().Series.from_document(item["series"]), date(2027, 1, 1), date(2027, 1, 5),
    )[0]
    send = AsyncMock(return_value=DeliveryResult("delivered", message_id="receipt"))
    outbound = SimpleNamespace(send=send)
    log_path = tmp_path / "delivery.json"
    projected = {**item, "occurrence_id": first.occurrence_id}
    checker = ReminderChecker(calendar_manager=calendar, storage_path=log_path, outbound_sender=outbound)

    asyncio.run(checker._send_item_reminder(projected, "now", "nå"))
    restarted = ReminderChecker(calendar_manager=calendar, storage_path=log_path, outbound_sender=outbound)
    asyncio.run(restarted.setup())
    asyncio.run(restarted._send_item_reminder(projected, "now", "nå"))

    assert send.await_count == 1
    assert restarted.sent_log["deliveries"][f"{first.occurrence_id}:now"]["message_id"] == "receipt"


def test_scheduler_uses_the_next_series_occurrence_identity(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult

    now = {"value": datetime(2027, 1, 4, 8, tzinfo=timezone.utc)}
    clock = Clock(wall=lambda: now["value"], monotonic=lambda: 1)
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json", clock=clock)
    item = calendar.add_item(
        "guild", "user", "User", "Møte", "04.01.2027", time_str="09:00",
        recurrence="weekly", duration_minutes=30,
    )
    calendar.complete_item("guild", item_id=item["id"])
    series = recurrence_module().Series.from_document(calendar.items["shared"][0]["series"])
    next_instance = recurrence_module().occurrence_at(series, 1)
    now["value"] = datetime(2027, 1, 11, 8, tzinfo=timezone.utc)
    send = AsyncMock(return_value=DeliveryResult("delivered", message_id="next-receipt"))
    checker = ReminderChecker(
        calendar_manager=calendar, clock=clock, storage_path=tmp_path / "delivery.json",
        outbound_sender=SimpleNamespace(send=send),
    )

    asyncio.run(checker.check_event_now())

    assert checker.sent_log["deliveries"][f"{next_instance.occurrence_id}:now"]["message_id"] == "next-receipt"


def test_google_import_keeps_moved_and_cancelled_occurrence_exceptions(tmp_path):
    import asyncio

    master_start = {"dateTime": "2027-01-04T09:00:00+01:00", "timeZone": "Europe/Oslo"}
    master_end = {"dateTime": "2027-01-04T10:00:00+01:00", "timeZone": "Europe/Oslo"}
    events = [
        {"id": "g-master", "summary": "Ukentlig møte", "start": master_start, "end": master_end,
         "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=4"]},
        {"id": "g-moved", "recurringEventId": "g-master", "summary": "Ukentlig møte flyttet",
         "originalStartTime": {"dateTime": "2027-01-11T09:00:00+01:00", "timeZone": "Europe/Oslo"},
         "start": {"dateTime": "2027-01-12T11:30:00+01:00", "timeZone": "Europe/Oslo"},
         "end": {"dateTime": "2027-01-12T12:30:00+01:00", "timeZone": "Europe/Oslo"}},
        {"id": "g-cancelled", "recurringEventId": "g-master", "status": "cancelled",
         "originalStartTime": {"dateTime": "2027-01-18T09:00:00+01:00", "timeZone": "Europe/Oslo"}},
    ]
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json")

    asyncio.run(calendar._apply_google_pull(events, {}, calendar._storage.revision))
    item = calendar.items["shared"][0]
    series = recurrence_module().Series.from_document(item["series"])
    expected = recurrence_module().expand_series(series, date(2027, 1, 1), date(2027, 1, 20))
    moved = item["occurrences"][expected[1].occurrence_id]
    cancelled = item["occurrences"][expected[2].occurrence_id]

    assert len(calendar.items["shared"]) == 1
    assert series.end_count == 4
    assert moved["state"] == "planned"
    assert moved["original_start"] == expected[1].original_start.isoformat()
    assert moved["override"]["date"] == "12.01.2027"
    assert moved["override"]["time"] == "11:30"
    assert moved["override"]["gcal_instance_id"] == "g-moved"
    assert cancelled["state"] == "skipped"
    assert cancelled["override"]["gcal_instance_id"] == "g-cancelled"
    storage_path = calendar.storage_path
    calendar._storage.close()
    restored = CalendarManager(storage_path=storage_path)
    assert restored.items['shared'][0]['occurrences'] == item['occurrences']
    restored._storage.close()


def test_google_import_projects_moved_current_occurrence_immediately(tmp_path):
    import asyncio

    events = [
        {"id": "g-master", "summary": "Ukentlig møte",
         "start": {"dateTime": "2027-01-04T09:00:00+01:00", "timeZone": "Europe/Oslo"},
         "end": {"dateTime": "2027-01-04T10:00:00+01:00", "timeZone": "Europe/Oslo"},
         "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"]},
        {"id": "g-moved-first", "recurringEventId": "g-master", "summary": "Ukentlig møte",
         "originalStartTime": {"dateTime": "2027-01-04T09:00:00+01:00", "timeZone": "Europe/Oslo"},
         "start": {"dateTime": "2027-01-05T11:30:00+01:00", "timeZone": "Europe/Oslo"},
         "end": {"dateTime": "2027-01-05T12:30:00+01:00", "timeZone": "Europe/Oslo"}},
    ]
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json")

    asyncio.run(calendar._apply_google_pull(events, {}, calendar._storage.revision))
    item = calendar.items["shared"][0]

    assert item["series_next_index"] == 0
    assert item["date"] == "05.01.2027"
    assert item["time"] == "11:30"


def test_google_import_advances_past_cancelled_current_occurrence(tmp_path):
    import asyncio

    events = [
        {"id": "g-master", "summary": "Ukentlig møte",
         "start": {"dateTime": "2027-01-04T09:00:00+01:00", "timeZone": "Europe/Oslo"},
         "end": {"dateTime": "2027-01-04T10:00:00+01:00", "timeZone": "Europe/Oslo"},
         "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"]},
        {"id": "g-cancelled-first", "recurringEventId": "g-master", "status": "cancelled",
         "originalStartTime": {"dateTime": "2027-01-04T09:00:00+01:00", "timeZone": "Europe/Oslo"}},
    ]
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json")

    asyncio.run(calendar._apply_google_pull(events, {}, calendar._storage.revision))
    item = calendar.items["shared"][0]

    assert item["series_next_index"] == 1
    assert item["date"] == "11.01.2027"


def test_unsupported_google_rule_stays_raw_and_readable(tmp_path):
    import asyncio

    unsupported = "RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1"
    event = {"id": "g-master", "summary": "Første mandag", "start": {"dateTime": "2027-01-04T09:00:00+01:00",
             "timeZone": "Europe/Oslo"}, "end": {"dateTime": "2027-01-04T10:00:00+01:00",
             "timeZone": "Europe/Oslo"}, "recurrence": [unsupported]}
    calendar = CalendarManager(storage_path=tmp_path / "calendar.json")

    asyncio.run(calendar._apply_google_pull([event], {}, calendar._storage.revision))
    item = calendar.items["shared"][0]

    assert item["recurrence"] is None
    assert item["_remote_recurrence_raw"] == [unsupported]
    assert item["_recurrence_readonly"] is True
    assert unsupported in item["recurrence_readable"]
    assert unsupported in calendar.format_single_item(item)


def test_unsupported_google_update_keeps_preexisting_local_exceptions(tmp_path):
    from cal_system.recurrence import occurrence_at, Series

    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json')
    item = calendar.add_item('shared', 'u', 'User', 'Series', '04.01.2027', '09:00',
        recurrence='weekly', duration_minutes=30, end_count=4)
    snapshot = calendar.items
    stored = snapshot['shared'][0]
    series = Series.from_document(stored['series'])
    occurrence = occurrence_at(series, 1)
    stored['occurrences'] = {occurrence.occurrence_id: recurrence_module().Occurrence(
        occurrence.occurrence_id, series.series_id, occurrence.original_start, 'skipped').to_document()}
    calendar.items = snapshot
    before = calendar.items['shared'][0]['occurrences'].copy()

    snapshot = calendar.items
    target = snapshot['shared'][0]
    calendar.apply_remote_sync_fields(target, {
        'summary': 'Series', 'start': {'dateTime': '2027-01-04T09:00:00+01:00', 'timeZone': 'Europe/Oslo'},
        'end': {'dateTime': '2027-01-04T09:30:00+01:00', 'timeZone': 'Europe/Oslo'},
        'recurrence': ['RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1']})
    calendar.items = snapshot
    updated = calendar.items['shared'][0]

    assert updated['_recurrence_readonly']
    assert updated['series'] == stored['series']
    assert updated['occurrences'] == before


def test_calendar_nlp_route_extracts_inclusive_recurrence_bounds():
    from core.intent_router import IntentRouter
    from types import SimpleNamespace

    router = object.__new__(IntentRouter)
    router.monitor = SimpleNamespace(nlp_parser=SimpleNamespace(
        parse_task_with_recurrence=lambda _content: {'title': 'Trening', 'date': '04.01.2027',
            'time': '09:00', 'recurrence': 'weekly'},
        parse_event=lambda _content: None))

    count_result = router._route_calendar_item('Trening hver uke for 6 forekomster', 'shared')
    date_result = router._route_calendar_item('Trening hver uke til 08.02.2027', 'shared')

    assert count_result.payload['calendar_item']['end_count'] == 6
    assert date_result.payload['calendar_item']['end_date'] == '08.02.2027'


def test_calendar_command_router_recognizes_occurrence_skip():
    from core.intent_router import BotIntent, IntentRouter

    router = object.__new__(IntentRouter)
    result = router._route_calendar_command('kalender hopp over trening', 'shared')

    assert result.intent == BotIntent.CALENDAR_COMPLETE
    assert result.reason == 'calendar_occurrence_skip'


def test_calendar_command_router_recognizes_occurrence_skip():
    from core.intent_router import BotIntent, IntentRouter

    router = object.__new__(IntentRouter)
    result = router._route_calendar_command('kalender hopp over trening', 'shared')

    assert result.intent == BotIntent.CALENDAR_COMPLETE
    assert result.reason == 'calendar_occurrence_skip'


def test_failed_occurrence_completion_commit_restores_series_state(tmp_path, monkeypatch):
    from cal_system.calendar_manager import CalendarManager
    from utils.storage_contract import StorageCommit, StorageMutationError
    import pytest

    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json')
    item = calendar.add_item('shared', 'u', 'User', 'Ukentlig', '04.01.2027', '09:00',
        recurrence='weekly', duration_minutes=30, end_count=4)
    monkeypatch.setattr(calendar._storage, 'commit', lambda *_args, **_kwargs: StorageCommit(False, 'write_failed'))

    with pytest.raises(StorageMutationError):
        calendar.complete_item('shared', item_id=item['id'])

    restored = calendar.items['shared'][0]
    assert restored['series_next_index'] == 0
    assert restored['occurrences'] == {}
    calendar._storage.close()


def test_failed_reminder_completion_commit_restores_series_state(tmp_path, monkeypatch):
    from utils.storage_contract import StorageCommit, StorageMutationError
    import pytest

    reminders = ReminderManager(storage_path=tmp_path / 'reminders.json', clock=fixed_clock())
    reminder_id = reminders.add_reminder('guild', 'u', 'User', 'Ukentlig', '04.01.2027',
        recurrence='weekly', end_count=3)
    monkeypatch.setattr(reminders._storage, 'commit', lambda *_args, **_kwargs: StorageCommit(False, 'write_failed'))

    with pytest.raises(StorageMutationError):
        reminders.complete_reminder('guild', reminder_id=reminder_id)

    restored = reminders.reminders['guild'][0]
    assert restored['series_next_index'] == 0
    assert restored['occurrences'] == {}
    assert restored['due_date'] == '04.01.2027'
    reminders._storage.close()


def test_recurring_preview_requires_scope_and_this_edit_preserves_anchor(tmp_path):
    from cal_system.recurrence import Series

    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json')
    actor = recurrence_actor()
    with request_scope(actor):
        item = calendar.add_item('shared', '7', 'Tester', 'Månedlig', '31.01.2027', '09:00',
            recurrence='monthly', duration_minutes=30, end_count=4)
        with pytest.raises(ValueError, match='recurrence_edit_scope_required'):
            calendar.edit_item_by_id(item['id'], title='Uten scope')
        with pytest.raises(ValueError, match='recurrence_edit_scope_required'):
            calendar.preview_mutation(actor, 'shared', [item['id']], 'edit',
                calendar._storage.revision, changes={'title': 'Ny tittel'})
        proposal = calendar.preview_mutation(actor, 'shared', [item['id']], 'edit',
            calendar._storage.revision, changes={'title': 'Bare denne', 'edit_scope': 'this', 'time': '11:00'})
    occurrence_id = proposal.effects[0]['occurrence_id']
    applied = asyncio.run(calendar.apply_preview(actor, proposal.token))
    saved = calendar.items['shared'][0]
    series = Series.from_document(saved['series'])
    assert series.anchor_time.local_date == date(2027, 1, 31)
    assert saved['occurrences'][occurrence_id]['override']['time'] == '11:00'
    assert saved['date'] == '31.01.2027'
    asyncio.run(calendar.undo_mutation(actor, applied['undo_token']))
    calendar._storage.close()


def test_future_scope_keeps_occurrence_identity_and_skip_advances(tmp_path):
    from cal_system.recurrence import Series, occurrence_at, expand_series

    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json')
    actor = recurrence_actor()
    with request_scope(actor):
        item = calendar.add_item('shared', '7', 'Tester', 'Ukentlig', '04.01.2027', '09:00',
            recurrence='weekly', duration_minutes=30, end_count=5)
        calendar.complete_item('shared', item_id=item['id'])
        initial_series = Series.from_document(calendar.items['shared'][0]['series'])
        before_id = occurrence_at(initial_series, 1).occurrence_id
        proposal = calendar.preview_mutation(actor, 'shared', [item['id']], 'edit',
            calendar._storage.revision, changes={'title': 'Fra nå av', 'edit_scope': 'future'})
    asyncio.run(calendar.apply_preview(actor, proposal.token))
    saved = calendar.items['shared'][0]
    current = Series.from_document(saved['series'])
    assert occurrence_at(current, 1).occurrence_id == before_id
    assert [entry.original_start.strftime('%d.%m.%Y') for entry in expand_series(
        current, date(2027, 1, 11), date(2027, 1, 31))] == ['11.01.2027', '18.01.2027', '25.01.2027']
    assert current.anchor_time.local_date.strftime('%d.%m.%Y') == '11.01.2027'
    assert current.end_count == 5
    assert saved['title'] == 'Fra nå av'
    assert saved['series_history'][0]['series']['anchor_time']['date'] == '04.01.2027'

    with request_scope(actor):
        skipped = calendar.preview_mutation(actor, 'shared', [item['id']], 'skip', calendar._storage.revision)
    asyncio.run(calendar.apply_preview(actor, skipped.token))
    final = calendar.items['shared'][0]
    assert final['date'] == '18.01.2027'
    assert 'skipped' in [x['state'] for x in final['occurrences'].values()]
    calendar._storage.close()


def test_calendar_handler_wires_occurrence_scopes_and_skip_confirmation(tmp_path):
    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json')
    actor = recurrence_actor()
    handler = recurrence_handler(calendar)
    assert handler._parse_edit_scope('@inebotten kalender endre Møte tid: 10:30 bare denne') == 'this'
    assert handler._parse_edit_scope('@inebotten kalender endre Møte tid: 10:30 denne og fremtidige') == 'future'
    assert handler._parse_edit_scope('@inebotten kalender endre Møte tid: 10:30 hele serien') == 'series'
    day = (datetime.now() + timedelta(days=10)).strftime('%d.%m.%Y')
    item = calendar.add_item('shared', '7', 'Tester', 'Månedlig', day, '09:00',
        recurrence='monthly', duration_minutes=30, end_count=3)

    with request_scope(actor):
        asyncio.run(handler.handle_list(recurrence_message('@inebotten kalender')))
        asyncio.run(handler.handle_edit(recurrence_message('@inebotten kalender endre 1 tid: 10:30 bare denne')))
    proposal = next(reversed(calendar._previews.entries.values()))
    assert proposal['after'][0]['occurrences']
    assert 'forekomst `' in handler.send_response.await_args.args[1]
    assert calendar.items['shared'][0]['id'] == item['id']

    day = (datetime.now() + timedelta(days=12)).strftime('%d.%m.%Y')
    skipped_item = calendar.add_item('shared', '7', 'Tester', 'Ukentlig', day, '09:00',
        recurrence='weekly', duration_minutes=30, end_count=3)
    with request_scope(actor):
        asyncio.run(handler.handle_list(recurrence_message('@inebotten kalender')))
        asyncio.run(handler.handle_complete(recurrence_message('@inebotten kalender hopp over 2')))
        preview_text = handler.send_response.await_args.args[1]
        token = re.search(r'bekreft kalender ([A-Za-z0-9_-]+)', preview_text).group(1)
        asyncio.run(handler.handle_clear(recurrence_message(f'@inebotten bekreft kalender {token}')))
    skipped = next(row for row in calendar.items['shared'] if row['id'] == skipped_item['id'])
    assert 'skipped' in [entry['state'] for entry in skipped['occurrences'].values()]
    assert 'Hoppet over' in handler.send_response.await_args.args[1]
    calendar._storage.close()


def test_readonly_google_series_rejects_flattening_edit(tmp_path):
    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json')
    actor = recurrence_actor()
    item = calendar.add_item('shared', '7', 'Tester', 'Google', '11.01.2027', '09:00', duration_minutes=30)
    snapshot = calendar.items
    snapshot['shared'][0].update(gcal_event_id='master', _recurrence_readonly=True,
        _remote_recurrence_raw=['RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1'],
        recurrence_readable='RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1')
    calendar.items = snapshot
    with pytest.raises(ValueError, match='unsupported_google_recurrence_readonly'):
        calendar.preview_mutation(actor, 'shared', [item['id']], 'edit', calendar._storage.revision,
            changes={'title': 'Flattened'})
    calendar._storage.close()
