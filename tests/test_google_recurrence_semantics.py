from datetime import date,time
import asyncio,copy
import pytest
from cal_system.recurrence import parse_google_recurrence
from cal_system.event_schema import EventTime
from cal_system.calendar_manager import CalendarManager
from core.request_context import RequestContext,request_scope

@pytest.mark.parametrize('day,frequency',[(date(2027,1,31),'MONTHLY'),(date(2028,2,29),'YEARLY')])
def test_rfc_skip_invalid_dates_cannot_be_imported_as_local_clamping(day,frequency):
    anchor=EventTime('event',day,time(9),'UTC',False,30)
    rule='RRULE:FREQ='+frequency+';COUNT=3'
    result=parse_google_recurrence([rule],anchor)
    assert result['supported'] is False
    assert result['raw']==[rule]
    assert result['reason_code']=='google_invalid_date_semantics_unsupported'

@pytest.mark.parametrize('all_day,until',[(False,'20270131'),(True,'20270131T235959Z')])
def test_google_until_value_type_must_match_dtstart(all_day,until):
    anchor=EventTime('event',date(2027,1,4),None if all_day else time(9),'UTC',all_day,None if all_day else 30)
    assert not parse_google_recurrence(['RRULE:FREQ=WEEKLY;UNTIL='+until],anchor)['supported']


def test_google_pull_preserves_unconfirmed_local_occurrence_edit(tmp_path):
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    actor=RequestContext('google-fixture','7','9',None,'no','dm')
    master={'id':'master','summary':'Series','start':{'dateTime':'2027-01-04T09:00:00+01:00','timeZone':'Europe/Oslo'},
            'end':{'dateTime':'2027-01-04T09:30:00+01:00','timeZone':'Europe/Oslo'},'recurrence':['RRULE:FREQ=WEEKLY;COUNT=4']}
    instance={**master,'id':'first','recurringEventId':'master','originalStartTime':master['start']}
    instance.pop('recurrence')
    try:
        with request_scope(actor):
            asyncio.run(calendar._apply_google_pull([master,instance],{},calendar._storage.revision))
            scope=calendar.scope_key(operation='write')
            item=calendar.items[scope][0]
            proposal=calendar.preview_mutation(actor,scope,[item['id']],'edit',calendar._storage.revision,
                changes={'date':'05.01.2027','edit_scope':'this'})
            asyncio.run(calendar.apply_preview(actor,proposal.token))
            before=copy.deepcopy(calendar.items[scope][0])
            assert before['sync_blocked'].startswith('google_')
            asyncio.run(calendar._apply_google_pull([master,instance],{},calendar._storage.revision))
            after=calendar.items[scope][0]
            assert after['occurrences']==before['occurrences']
            assert after['date']==before['date']
            assert after['sync_blocked']==before['sync_blocked']
    finally:calendar._storage.close()


def test_unsupported_google_instance_evidence_is_committed_on_later_pull(tmp_path):
    master={'id':'master','summary':'Series','start':{'dateTime':'2027-01-04T09:00:00+01:00','timeZone':'Europe/Oslo'},
            'end':{'dateTime':'2027-01-04T09:30:00+01:00','timeZone':'Europe/Oslo'},
            'recurrence':['RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1']}
    instance={**master,'id':'first','recurringEventId':'master','originalStartTime':master['start']}
    instance.pop('recurrence')
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        asyncio.run(calendar._apply_google_pull([master],{},calendar._storage.revision))
        asyncio.run(calendar._apply_google_pull([master,instance],{},calendar._storage.revision))
        current=calendar.items['shared'][0]
        assert current['google_instances'][0]['id']=='first'
        assert current['recurrence_diagnostic']=='unsupported_google_recurrence'
    finally:calendar._storage.close()
    reloaded=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:assert reloaded.items['shared'][0]['google_instances'][0]['id']=='first'
    finally:reloaded._storage.close()


def test_remote_supported_schedule_change_does_not_remap_existing_exception(tmp_path):
    from cal_system.recurrence import Series,Occurrence,occurrence_at
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        item=calendar.add_item('shared','u','User','Series','04.01.2027','09:00',recurrence='weekly',duration_minutes=30)
        series=Series.from_document(item['series'])
        original=occurrence_at(series,0)
        item['occurrences']={original.occurrence_id:Occurrence(original.occurrence_id,series.series_id,
            original.original_start,'planned',{'date':'05.01.2027'}).to_document()}
        before=copy.deepcopy(item)
        remote={'id':'master','summary':'Changed remote','start':{'dateTime':'2027-01-11T09:00:00+01:00','timeZone':'Europe/Oslo'},
                'end':{'dateTime':'2027-01-11T09:30:00+01:00','timeZone':'Europe/Oslo'},'recurrence':['RRULE:FREQ=WEEKLY']}
        calendar.apply_remote_sync_fields(item,remote)
        assert item['series']==before['series'] and item['occurrences']==before['occurrences']
        assert item['title']==before['title'] and item['date']==before['date']
        assert item['_recurrence_readonly'] is True
        assert item['sync_blocked']=='google_series_changed_requires_review'
        assert item['_remote_series_change_pending']['recurrence']==remote['recurrence']
    finally:calendar._storage.close()


def test_changed_google_master_preserves_existing_exception_through_actual_pull(tmp_path):
    master={'id':'master','summary':'Series','start':{'dateTime':'2027-01-04T09:00:00+01:00','timeZone':'Europe/Oslo'},
            'end':{'dateTime':'2027-01-04T09:30:00+01:00','timeZone':'Europe/Oslo'},'recurrence':['RRULE:FREQ=WEEKLY;COUNT=4']}
    instance={**master,'id':'first','recurringEventId':'master','originalStartTime':master['start'],
              'start':{'dateTime':'2027-01-05T09:00:00+01:00','timeZone':'Europe/Oslo'},
              'end':{'dateTime':'2027-01-05T09:30:00+01:00','timeZone':'Europe/Oslo'}}
    instance.pop('recurrence')
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json')
    try:
        asyncio.run(calendar._apply_google_pull([master,instance],{},calendar._storage.revision))
        before=calendar.items['shared'][0]
        assert before['occurrences']
        changed={**master,'summary':'Changed','start':{'dateTime':'2027-01-11T09:00:00+01:00','timeZone':'Europe/Oslo'},
                 'end':{'dateTime':'2027-01-11T09:30:00+01:00','timeZone':'Europe/Oslo'}}
        asyncio.run(calendar._apply_google_pull([changed],{},calendar._storage.revision))
        after=calendar.items['shared'][0]
        assert after['series']==before['series'] and after['occurrences']==before['occurrences']
        assert after['date']==before['date'] and after['title']==before['title']
        assert after['sync_blocked']=='google_series_changed_requires_review'
    finally:calendar._storage.close()
