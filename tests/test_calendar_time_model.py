"""Lossless calendar time semantics; no live Google account required."""
from datetime import date, datetime, time, timezone
from unittest.mock import Mock
import pytest


def model():
    from cal_system.event_schema import EventTime, Clock, TimeResolutionError
    return EventTime, Clock, TimeResolutionError


def test_date_only_google_roundtrip_is_all_day_not_noon():
    EventTime, _, _ = model()
    value = EventTime('event', date(2027, 1, 1), None, 'Europe/Oslo', True, None)
    start, end = value.google_times()
    assert start == {'date': '2027-01-01'} and end == {'date': '2027-01-02'}
    assert EventTime.from_google({'start': start, 'end': end}) == value


def test_remote_duration_and_timezone_are_preserved():
    EventTime, _, _ = model()
    value = EventTime.from_google({'start': {'dateTime': '2027-01-01T23:30:00+01:00', 'timeZone': 'Europe/Oslo'},
                                  'end': {'dateTime': '2027-01-02T02:00:00+01:00'}})
    assert value.local_date == date(2027, 1, 1) and value.local_time == time(23, 30)
    assert value.duration_minutes == 150
    assert value.google_times()[1]['dateTime'] == '2027-01-02T02:00:00+01:00'


@pytest.mark.parametrize('day,reason', [(date(2027,3,28), 'nonexistent_time'), (date(2027,10,31), 'ambiguous_time')])
def test_dst_gap_or_fold_requires_explicit_resolution(day, reason):
    EventTime, _, Error = model()
    value = EventTime('event', day, time(2,30), 'Europe/Oslo', False, 90)
    with pytest.raises(Error) as caught:
        value.google_times()
    assert caught.value.reason_code == reason
    assert value.preview()['requires_resolution'] is True


def test_dst_fold_resolution_and_elapsed_duration():
    EventTime, _, _ = model()
    value = EventTime('event', date(2027,10,31), time(2,30), 'Europe/Oslo', False, 90, fold=0)
    start, end = value.google_times()
    elapsed = datetime.fromisoformat(end['dateTime']).astimezone(timezone.utc) - datetime.fromisoformat(start['dateTime']).astimezone(timezone.utc)
    assert elapsed.total_seconds() == 5400
    assert start['dateTime'].endswith('+02:00') and end['dateTime'].endswith('+01:00')


@pytest.mark.parametrize('raw', [ {'date':'31.02.2027'}, {'date':'01.01.2027', 'time':'25:00'},
                                  {'date':'01.01.2027', 'time':'12:99'}, {'date':'01.01.2027','timezone':'Unknown/Zone'}])
def test_invalid_legacy_values_do_not_get_normalized(raw):
    EventTime, _, _ = model()
    with pytest.raises(ValueError):
        EventTime.from_item(raw)


def test_legacy_interpretation_is_previewed_without_mutating_source():
    EventTime, _, Error = model()
    raw={'date':'01.01.2027','time':'09:00','extra':'preserve'}
    value=EventTime.from_item(raw)
    assert value.preview()['inferred_fields'] == ['kind', 'timezone', 'all_day']
    assert value.preview()['duration_minutes'] is None
    with pytest.raises(Error, match='duration_required'):
        value.google_times()
    assert raw == {'date':'01.01.2027','time':'09:00','extra':'preserve'}


def test_task_cannot_be_silently_exported_as_event():
    EventTime, _, Error = model()
    value=EventTime.from_item({'date':'01.01.2027','kind':'task'})
    with pytest.raises(Error, match='task_not_event'):
        value.google_times()


def test_wall_clock_jump_does_not_change_elapsed_deadline():
    _, Clock, _ = model()
    tick=Mock(side_effect=[10,11]); wall=Mock(side_effect=[datetime(2027,1,1,tzinfo=timezone.utc), datetime(2026,1,1,tzinfo=timezone.utc)])
    clock=Clock(wall=wall, monotonic=tick)
    deadline=clock.monotonic()+30
    assert clock.now('Europe/Oslo').utcoffset().total_seconds()==3600
    clock.now('UTC')
    assert deadline-clock.monotonic()==29


def test_manager_validates_and_persists_explicit_kind_duration(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    manager=CalendarManager(storage_path=tmp_path/'calendar.json')
    with pytest.raises(ValueError):
        manager.add_item('guild','user','User','Invalid','31.02.2027')
    item=manager.add_item('guild','user','User','Task','01.01.2027', kind='task')
    assert item['kind']=='task' and item['all_day'] is True
    event=manager.add_item('guild','user','User','Event','01.01.2027',time_str='10:00',duration_minutes=75)
    assert event['duration_minutes']==75
    edited=manager.edit_item_by_id(event['id'], date='02.01.2027')
    assert edited['duration_minutes']==75


def test_local_google_adapter_never_invents_time_or_duration():
    from cal_system.google_calendar_manager import GoogleCalendarManager
    manager=object.__new__(GoogleCalendarManager);manager.enabled=True
    manager.create_event=Mock(return_value={'id':'synthetic'})
    manager.sync_local_event({'title':'All day','date':'01.01.2027'})
    assert manager.create_event.call_args.kwargs['all_day'] is True
    assert manager.create_event.call_args.kwargs['start_time']=='2027-01-01'
    manager.create_event.reset_mock()
    assert manager.sync_local_event({'title':'Unknown duration','date':'01.01.2027','time':'09:00'}) is None
    assert manager.sync_local_event({'title':'Task','date':'01.01.2027','kind':'task'}) is None
    manager.create_event.assert_not_called()


def test_aware_calendar_clock_keeps_oslo_midnight_independent_of_host(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    EventTime, Clock, _ = model()
    clock=Clock(wall=lambda: datetime(2027,1,1,23,30,tzinfo=timezone.utc))
    manager=CalendarManager(storage_path=tmp_path/'calendar.json',clock=clock)
    manager.add_item('g','u','User','Yesterday in Oslo','01.01.2027')
    manager.add_item('g','u','User','Today in Oslo','02.01.2027')
    assert [item['title'] for item in manager.get_upcoming('g')] == ['Today in Oslo']


def test_date_only_does_not_receive_guessed_timed_reminder_and_private_data_is_filtered(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    from cal_system.reminder_checker import ReminderChecker
    from core.access_policy import AccessPolicy, ScopeRecord
    policy=AccessPolicy([ScopeRecord('shared','legacy_shared'),ScopeRecord('private:u','private_user',owner_id='u')])
    manager=CalendarManager(storage_path=tmp_path/'calendar.json',access_policy=policy)
    manager.items={'shared':[{'id':'one','title':'Shared','date':'01.01.2027'}],
                   'private:u':[{'id':'two','title':'Private','date':'01.01.2027','time':'09:00'}]}
    checker=ReminderChecker(calendar_manager=manager,storage_path=tmp_path/'sent.json')
    assert checker._parse_item_datetime(manager.items['shared'][0]) is None
    assert list(checker._calendar_buckets())==['shared']


def test_remote_seconds_survive_local_roundtrip():
    EventTime,_,_=model()
    remote={'start':{'dateTime':'2027-01-01T10:00:30+01:00'},'end':{'dateTime':'2027-01-01T11:15:30+01:00'}}
    value=EventTime.from_google(remote)
    assert EventTime.from_item(value.fields()).google_times()[0]['dateTime'] == '2027-01-01T10:00:30+01:00'


@pytest.mark.asyncio
async def test_imported_custom_duration_survives_date_edit_and_remote_update(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    from types import SimpleNamespace
    EventTime,_,_=model()
    update=Mock(return_value={'id':'remote'})
    raw={'id':'remote','summary':'Long meeting','start':{'dateTime':'2027-01-01T10:00:30+01:00'},
         'end':{'dateTime':'2027-01-01T12:15:30+01:00'}}
    remote=SimpleNamespace(is_configured=lambda:True,list_upcoming_events=lambda **_: [raw],update_event=update)
    manager=CalendarManager(storage_path=tmp_path/'calendar.json',gcal_manager=remote)
    await manager.sync_from_gcal()
    item=manager.items['shared'][0]
    edited=manager.edit_item_by_id(item['id'],date='02.01.2027')
    assert edited['duration_minutes']==135 and edited['time']=='10:00:30'
    assert EventTime.from_item(update.call_args.kwargs['event_time']).google_times()[1]['dateTime']=='2027-01-02T12:15:30+01:00'


def test_date_only_can_be_deliberately_edited_to_timed_with_duration(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    manager=CalendarManager(storage_path=tmp_path/'calendar.json')
    item=manager.add_item('g','u','User','All day','01.01.2027')
    changed=manager.edit_item_by_id(item['id'],time='14:30',duration_minutes=45)
    assert changed['all_day'] is False and changed['duration_minutes']==45
    before=manager.storage_path.read_bytes()
    with pytest.raises(ValueError):
        manager.edit_item_by_id(item['id'],date='28.03.2027',time='02:30')
    assert manager.storage_path.read_bytes()==before


@pytest.mark.asyncio
async def test_handler_previews_inferred_meaning_before_store_commit(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    from features.calendar_handler import CalendarHandler
    from memory.localization import Localization
    from types import SimpleNamespace
    manager=CalendarManager(storage_path=tmp_path/'calendar.json')
    handler=CalendarHandler(SimpleNamespace(calendar=manager,nlp_parser=None,rate_limiter=None,loc=Localization(),client=None))
    snapshots=[]
    async def send(_,text):
        snapshots.append((text, manager.storage_path.exists()))
    handler.send_response=send
    message=SimpleNamespace(guild=SimpleNamespace(id='g'),channel=SimpleNamespace(id='c'),author=SimpleNamespace(id='u',name='User'))
    await handler.handle_calendar_item(message,{'title':'Task','date':'01.01.2027','type':'task'})
    assert 'Tolkning før lagring' in snapshots[0][0] and snapshots[0][1] is False
    assert snapshots[1][1] is True
    assert manager.items['shared'][0]['kind']=='task'


def test_parser_keeps_explicit_fold_and_duration():
    from cal_system.natural_language_parser import NaturalLanguageParser
    parsed=NaturalLanguageParser().parse_event('arrangement "DST møte" 31.10.2027 kl 02:30 fold 1 varighet 90 minutter')
    assert parsed['fold']==1 and parsed['duration_minutes']==90
    assert parsed['time_preview']['requires_resolution'] is False


@pytest.mark.asyncio
async def test_handler_date_edit_accepts_explicit_fold_in_one_change(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    from features.calendar_handler import CalendarHandler
    from memory.localization import Localization
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    manager=CalendarManager(storage_path=tmp_path/'calendar.json')
    item=manager.add_item('g','u','User','DST meeting','01.01.2027',time_str='02:30',duration_minutes=90)
    handler=CalendarHandler(SimpleNamespace(calendar=manager,nlp_parser=None,rate_limiter=None,loc=Localization(),client=None))
    handler.send_response=AsyncMock()
    message=SimpleNamespace(content='@inebotten endre 1 dato: 31.10.2027 fold 1',guild=SimpleNamespace(id='g'),channel=SimpleNamespace(id='c'),author=SimpleNamespace(id='u',name='User'))
    await handler.handle_edit(message)
    updated=manager.items['shared'][0]
    assert updated['id']==item['id'] and updated['date']=='31.10.2027' and updated['fold']==1
