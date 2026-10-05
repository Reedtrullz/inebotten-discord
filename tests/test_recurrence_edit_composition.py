import asyncio
import copy
import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.recurrence import Series, expand_series
from core.request_context import RequestContext, request_scope
from datetime import date


def edit(calendar, actor, item_id, **changes):
    with request_scope(actor):
        preview = calendar.preview_mutation(actor, 'shared', [item_id], 'edit',
            calendar._storage.revision, changes=changes)
    asyncio.run(calendar.apply_preview(actor, preview.token))


def fixture(tmp_path):
    calendar = CalendarManager(storage_path=tmp_path/'calendar.json')
    actor = RequestContext('composition', '7', '9', None, 'no', 'dm')
    with request_scope(actor):
        item = calendar.add_item('shared', '7', 'Tester', 'Møte', '04.01.2027', '09:00',
            recurrence='weekly', duration_minutes=30, end_count=4)
    return calendar, actor, item['id']


def test_two_this_edits_keep_previous_move_and_original_identity(tmp_path):
    calendar, actor, item_id = fixture(tmp_path)
    try:
        edit(calendar, actor, item_id, edit_scope='this', date='05.01.2027', time='11:00')
        edit(calendar, actor, item_id, edit_scope='this', title='Ny tittel')
        item = calendar.items['shared'][0]
        exception = next(iter(item['occurrences'].values()))
        assert exception['override'] == {'date':'05.01.2027','time':'11:00','title':'Ny tittel'}
        assert exception['original_start'].startswith('2027-01-04T09:00')
        assert item['date'] == '05.01.2027' and item['time'] == '11:00'
        with request_scope(actor):
            calendar.complete_item('shared', item_id=item_id)
        completed = next(iter(calendar.items['shared'][0]['occurrences'].values()))
        assert completed['state'] == 'completed'
        assert completed['override'] == exception['override']
    finally: calendar._storage.close()


@pytest.mark.parametrize('scope', ['future', 'series'])
def test_schedule_change_with_pending_exception_refuses_without_mutation(tmp_path, scope):
    calendar, actor, item_id = fixture(tmp_path)
    try:
        edit(calendar, actor, item_id, edit_scope='this', date='05.01.2027')
        original = calendar.storage_path.read_bytes()
        document = copy.deepcopy(calendar.items)
        with request_scope(actor), pytest.raises(ValueError, match='pending_occurrence_exceptions_require_review'):
            calendar.preview_mutation(actor, 'shared', [item_id], 'edit',
                calendar._storage.revision, changes={'edit_scope':scope,'time':'10:00'})
        assert calendar.items == document and calendar.storage_path.read_bytes() == original
    finally: calendar._storage.close()


def test_future_title_edit_preserves_current_move_without_reanchoring_to_it(tmp_path):
    calendar, actor, item_id = fixture(tmp_path)
    try:
        edit(calendar, actor, item_id, edit_scope='this', date='05.01.2027')
        edit(calendar, actor, item_id, edit_scope='future', title='Fremtidig tittel')
        item = calendar.items['shared'][0]
        series = Series.from_document(item['series'])
        values = expand_series(series, date(2027,1,1),date(2027,1,31), exceptions=item['occurrences'])
        assert values[0].original_start.date() == date(2027,1,4)
        assert values[0].override['date'] == '05.01.2027'
        assert item['date'] == '05.01.2027'
        assert values[1].original_start.date() == date(2027,1,11)
    finally: calendar._storage.close()
