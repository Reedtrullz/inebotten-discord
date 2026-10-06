import asyncio
import importlib
import importlib.util
from datetime import datetime, timezone

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.event_schema import Clock
from core.access_policy import AccessPolicy, ScopeRecord
from core.request_context import RequestContext, request_scope


def exchange(calendar):
    assert importlib.util.find_spec('cal_system.calendar_exchange'), 'reviewed ICS exchange is missing'
    return importlib.import_module('cal_system.calendar_exchange').CalendarExchange(calendar)


def actor(user='7'):
    return RequestContext('ics', user, '9', None, 'no', 'dm')


def data(body, kind='VEVENT'):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Fixture//EN\r\nBEGIN:'+kind+
        '\r\n'+body+'\r\nEND:'+kind+'\r\nEND:VCALENDAR\r\n').encode()


@pytest.mark.parametrize('all_day', [False, True])
def test_unicode_timezone_duration_roundtrip_and_duplicate(tmp_path, all_day):
    a=actor(); source=CalendarManager(storage_path=tmp_path/'source.json')
    destination=CalendarManager(storage_path=tmp_path/'destination.json')
    try:
        with request_scope(a):
            item=source.add_item('shared','7','Tester','Møte æøå', '04.01.2027',
                None if all_day else '09:30', duration_minutes=2880 if all_day else 90)
            source.edit_item_by_id(item['id'], description='Linje 1\nLinje 2,;')
        raw=exchange(source).export_ics(a,'shared',[item['id']])
        service=exchange(destination); preview=service.preview_ics(a,'shared',raw)
        assert preview['new']==1 and not preview['unsupported']
        asyncio.run(service.apply(a,preview['token']))
        saved=destination.items['shared'][0]
        assert saved['title']=='Møte æøå' and saved['description']=='Linje 1\nLinje 2,;'
        assert saved['all_day']==all_day and saved['duration_minutes']==item['duration_minutes']
        assert saved['timezone']==item['timezone'] and saved['date']==item['date'] and saved['time']==item['time']
        again=service.preview_ics(a,'shared',raw)
        assert again['duplicate']==1 and again['new']==0 and again['changed']==0
        revision=destination._storage.revision
        asyncio.run(service.apply(a,again['token']))
        assert destination._storage.revision==revision and len(destination.items['shared'])==1
    finally: source._storage.close(); destination._storage.close()


@pytest.mark.parametrize('frequency',['daily','weekly','biweekly','monthly','yearly'])
def test_supported_recurrence_roundtrip(tmp_path,frequency):
    a=actor(); source=CalendarManager(storage_path=tmp_path/'source.json')
    destination=CalendarManager(storage_path=tmp_path/'destination.json')
    try:
        with request_scope(a):
            item=source.add_item('shared','7','Tester','Serie','04.01.2027','09:00',
                recurrence=frequency,duration_minutes=30,end_count=5)
        raw=exchange(source).export_ics(a,'shared',[item['id']])
        service=exchange(destination); preview=service.preview_ics(a,'shared',raw)
        assert preview['new']==1 and not preview['unsupported']
        asyncio.run(service.apply(a,preview['token']))
        saved=destination.items['shared'][0]
        assert saved['series']['rule']==item['series']['rule']
        assert saved['series']['end_count']==5 and saved['series']['anchor_time']==item['series']['anchor_time']
    finally: source._storage.close(); destination._storage.close()


def test_due_date_task_is_not_converted_to_timed_event(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        service=exchange(calendar)
        preview=service.preview_ics(actor(),'shared',data('UID:task\r\nSUMMARY:Handle\r\nDUE;VALUE=DATE:20270104', 'VTODO'))
        asyncio.run(service.apply(actor(),preview['token']))
        item=calendar.items['shared'][0]
        assert item['kind']=='task' and item['all_day'] and item['time'] is None
        exported=service.export_ics(actor(),'shared',[item['id']])
        assert b'BEGIN:VTODO' in exported and b'DUE;VALUE=DATE:20270104' in exported
    finally: calendar._storage.close()


def test_changed_uid_updates_one_local_record_and_replay_is_refused(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        service=exchange(calendar); a=actor()
        raw=data('UID:stable\r\nSUMMARY:A\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105')
        first=service.preview_ics(a,'shared',raw); asyncio.run(service.apply(a,first['token']))
        changed=service.preview_ics(a,'shared',raw.replace(b'SUMMARY:A',b'SUMMARY:B'))
        assert changed['changed']==1
        asyncio.run(service.apply(a,changed['token']))
        assert len(calendar.items['shared'])==1 and calendar.items['shared'][0]['title']=='B'
        with pytest.raises(ValueError,match='preview_missing'):asyncio.run(service.apply(a,changed['token']))
    finally: calendar._storage.close()


def test_expired_stale_wrong_actor_and_revoked_preview(tmp_path):
    now={'mono':1}; clock=Clock(wall=lambda:datetime(2027,1,1,tzinfo=timezone.utc),monotonic=lambda:now['mono'])
    policy=AccessPolicy([ScopeRecord('private:7','private_user',owner_id='7')],default_scope='private:7')
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json',clock=clock,access_policy=policy)
    try:
        service=exchange(calendar); a=actor(); raw=data('UID:x\r\nSUMMARY:A\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105')
        with pytest.raises(PermissionError): service.preview_ics(actor('8'),'private:7',raw)
        preview=service.preview_ics(a,'private:7',raw)
        with pytest.raises(PermissionError): asyncio.run(service.apply(actor('8'),preview['token']))
        now['mono']=301
        with pytest.raises(ValueError,match='preview_expired'):asyncio.run(service.apply(a,preview['token']))
        now['mono']=302; preview=service.preview_ics(a,'private:7',raw)
        with request_scope(a):calendar.add_item('private:7','7','Tester','Concurrent','05.01.2027')
        with pytest.raises(ValueError,match='revision_changed'):asyncio.run(service.apply(a,preview['token']))
        fresh=service.preview_ics(a,'private:7',raw)
        calendar.access_policy=AccessPolicy([ScopeRecord('shared','legacy_shared')])
        with pytest.raises(PermissionError):asyncio.run(service.apply(a,fresh['token']))
        assert len(calendar.items['private:7'])==1
    finally:calendar._storage.close()


@pytest.mark.parametrize('extra', ['RRULE:FREQ=MONTHLY;BYSETPOS=2', 'ATTENDEE:mailto:test@example.invalid',
    'URL:https://example.invalid', 'ATTACH:https://example.invalid/file', 'RECURRENCE-ID;VALUE=DATE:20270104'])
def test_unsupported_records_are_visible_and_not_applied(tmp_path,extra):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        service=exchange(calendar); original=calendar._storage.revision
        preview=service.preview_ics(actor(),'shared',data('UID:x\r\nSUMMARY:A\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105\r\n'+extra))
        assert preview['unsupported'] and preview['new']==0
        asyncio.run(service.apply(actor(),preview['token']))
        assert calendar._storage.revision==original and not calendar.items
    finally:calendar._storage.close()


@pytest.mark.parametrize('raw', [b'x'*(1024*1024+1),b'BEGIN:VCALENDAR\r\n'+b'A'*9000,
    b'BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nEND:VEVENT\r\nEND:VCALENDAR',b'\xff'])
def test_bounded_malformed_input_refuses_before_mutation(tmp_path,raw):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        service=exchange(calendar)
        with pytest.raises(ValueError): service.preview_ics(actor(),'shared',raw)
        assert not calendar.items
    finally:calendar._storage.close()


def test_local_clamping_and_occurrence_history_are_not_lossily_exported(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json'); a=actor()
    try:
        with request_scope(a):
            item=calendar.add_item('shared','7','Tester','Month end','31.01.2027','09:00',
                recurrence='monthly',duration_minutes=30)
        with pytest.raises(ValueError,match='unsupported_exchange_recurrence'):
            exchange(calendar).export_ics(a,'shared',[item['id']])
    finally:calendar._storage.close()


def test_export_reimport_of_same_store_is_not_a_duplicate_record(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json'); a=actor()
    try:
        with request_scope(a):item=calendar.add_item('shared','7','Tester','One','04.01.2027')
        service=exchange(calendar); raw=service.export_ics(a,'shared',[item['id']])
        preview=service.preview_ics(a,'shared',raw)
        assert preview['duplicate']==1 and not preview['effects']
        asyncio.run(service.apply(a,preview['token']))
        assert len(calendar.items['shared'])==1
    finally:calendar._storage.close()


def test_uploaded_iana_definition_cannot_change_the_clock(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    raw=('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTIMEZONE\r\nTZID:Europe/Oslo\r\n'
        'BEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0900\r\nTZOFFSETTO:+0900\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n'
        'BEGIN:VEVENT\r\nUID:clock\r\nSUMMARY:Fixture\r\nDTSTART;TZID=Europe/Oslo:20270104T090000\r\n'
        'DTEND;TZID=Europe/Oslo:20270104T100000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n').encode()
    try:
        service=exchange(calendar); preview=service.preview_ics(actor(),'shared',raw)
        assert not preview['unsupported'] and preview['warnings']
        asyncio.run(service.apply(actor(),preview['token']))
        item=calendar.items['shared'][0]
        from cal_system.event_schema import EventTime
        assert EventTime.from_item(item).aware_start().utcoffset().total_seconds()==3600
    finally:calendar._storage.close()


def test_import_cannot_overwrite_local_occurrence_history(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json'); a=actor()
    try:
        with request_scope(a):item=calendar.add_item('shared','7','Tester','Series','04.01.2027','09:00',
            recurrence='weekly',duration_minutes=30,end_count=5)
        service=exchange(calendar); raw=service.export_ics(a,'shared',[item['id']])
        with request_scope(a):calendar.complete_item('shared',item_id=item['id'])
        original=calendar.storage_path.read_bytes()
        preview=service.preview_ics(a,'shared',raw.replace(b'SUMMARY:Series',b'SUMMARY:Changed'))
        assert preview['changed']==0 and preview['unsupported'][0]['reason']=='local_history_or_remote_review_required'
        asyncio.run(service.apply(a,preview['token']))
        assert calendar.storage_path.read_bytes()==original
        with pytest.raises(ValueError,match='occurrence_history_exchange_unsupported'):
            service.export_ics(a,'shared',[item['id']])
    finally:calendar._storage.close()


def test_duplicate_uids_cannot_select_ambiguous_changes(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    raw=data('UID:same\r\nSUMMARY:One\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105')
    raw=raw.replace(b'END:VCALENDAR',b'BEGIN:VEVENT\r\nUID:same\r\nSUMMARY:Two\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105\r\nEND:VEVENT\r\nEND:VCALENDAR')
    try:
        with pytest.raises(ValueError,match='duplicate_ics_uid'):exchange(calendar).preview_ics(actor(),'shared',raw)
        assert not calendar.items
    finally:calendar._storage.close()


def test_write_only_collaborator_cannot_receive_other_members_before_images(tmp_path):
    policy=AccessPolicy([ScopeRecord('group:fixture','approved_group',owner_id='7',
        collaborator_ids=frozenset({'8'}),channel_ids=frozenset({'9'}),
        read_policy='owner',write_policy='members')],default_scope='group:fixture')
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json',access_policy=policy)
    member=RequestContext('member','8','9',None,'no','group_dm')
    try:
        assert policy.authorize(member,'group:fixture','write').allowed
        raw=data('UID:x\r\nSUMMARY:One\r\nDTSTART;VALUE=DATE:20270104\r\nDTEND;VALUE=DATE:20270105')
        with pytest.raises(PermissionError):exchange(calendar).preview_ics(member,'group:fixture',raw)
        assert not calendar.items
    finally:calendar._storage.close()


def test_elapsed_duration_ending_in_repeated_hour_survives_export(tmp_path):
    source=CalendarManager(storage_path=tmp_path/'source.json'); dest=CalendarManager(storage_path=tmp_path/'dest.json'); a=actor()
    try:
        with request_scope(a):item=source.add_item('shared','7','Tester','DST','31.10.2027','01:30',duration_minutes=120)
        raw=exchange(source).export_ics(a,'shared',[item['id']])
        service=exchange(dest); preview=service.preview_ics(a,'shared',raw)
        asyncio.run(service.apply(a,preview['token']))
        assert dest.items['shared'][0]['duration_minutes']==120
    finally:source._storage.close();dest._storage.close()


def test_ambiguous_start_cannot_be_exported_without_fold_identity(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json'); a=actor()
    try:
        with request_scope(a):item=calendar.add_item('shared','7','Tester','DST','31.10.2027','02:30',fold=1,duration_minutes=30)
        with pytest.raises(ValueError,match='ambiguous_time'):
            exchange(calendar).export_ics(a,'shared',[item['id']])
    finally:calendar._storage.close()
