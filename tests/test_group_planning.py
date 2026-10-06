import asyncio
import importlib
import importlib.util
from datetime import date, time

import pytest

from cal_system.calendar_manager import CalendarManager
from cal_system.event_schema import EventTime
from core.access_policy import AccessPolicy, ScopeRecord
from core.request_context import RequestContext, request_scope
from features.poll_manager import PollManager


def context(user='7',channel='9'):
    return RequestContext('planning',user,channel,'100','no','guild')


def fixture(tmp_path):
    policy=AccessPolicy([ScopeRecord('group:approved','approved_group',owner_id='7',
        collaborator_ids=frozenset({'8'}),channel_ids=frozenset({'9'}),write_policy='owner')],
        default_scope='group:approved')
    calendar=CalendarManager(storage_path=tmp_path/'calendar.json',access_policy=policy)
    polls=PollManager(storage_path=tmp_path/'polls.json')
    assert importlib.util.find_spec('features.planning_manager'), 'group planning is missing'
    manager=importlib.import_module('features.planning_manager').PlanningManager(calendar,polls)
    return manager,calendar,polls


def candidates():
    return [EventTime('event',date(2027,1,4),time(18),'Europe/Oslo',False,120),
        EventTime('event',date(2027,1,5),time(18),'Europe/Oslo',False,120)]


def test_zero_votes_and_tie_need_explicit_organizer_choice(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        with pytest.raises(ValueError,match='explicit_selection_required'):
            manager.preview_finalize(context(),session['session_id'])
        manager.vote(context('7'),session['session_id'],1)
        manager.vote(context('8'),session['session_id'],2)
        with pytest.raises(ValueError,match='explicit_selection_required'):
            manager.preview_finalize(context(),session['session_id'])
        proposal=manager.preview_finalize(context(),session['session_id'],selection=1)
        assert not calendar.items
        result=asyncio.run(manager.finalize(context(),session['session_id'],proposal.token))
        assert result['event_id']==calendar.items['group:approved'][0]['id']
        assert calendar.items['group:approved'][0]['date']=='04.01.2027'
        assert not calendar.items['group:approved'][0]['planning_notifications_approved']
    finally:calendar._storage.close();polls._storage.close()


def test_finalize_is_organizer_only_and_stale_vote_refuses(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        manager.vote(context('8'),session['session_id'],1)
        with pytest.raises(PermissionError):manager.preview_finalize(context('8'),session['session_id'])
        preview=manager.preview_finalize(context(),session['session_id'])
        manager.vote(context('7'),session['session_id'],2)
        with pytest.raises(ValueError,match='poll_changed'):
            asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
        assert not calendar.items
    finally:calendar._storage.close();polls._storage.close()


def test_duplicate_finalize_and_restart_never_create_another_event(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    session=manager.create(context(),'group:approved','Film',candidates())
    preview=manager.preview_finalize(context(),session['session_id'],selection=2,notify=True)
    first=asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
    again=asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
    assert first['event_id']==again['event_id'] and len(calendar.items['group:approved'])==1
    calendar._storage.close();polls._storage.close()
    manager,calendar,polls=fixture(tmp_path)
    try:
        restored=manager.get_session(context(),session['session_id'])
        assert restored['state']=='finalized' and restored['event_id']==first['event_id']
        assert calendar.items['group:approved'][0]['channel_id']=='9'
    finally:calendar._storage.close();polls._storage.close()


def test_cross_channel_and_private_rsvp_visibility_are_enforced(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        manager.rsvp(context('8'),session['session_id'],'yes',visibility='self')
        assert manager.get_session(context(),session['session_id'])['rsvps']==[]
        assert manager.get_session(context('8'),session['session_id'])['rsvps'][0]['response']=='yes'
        with pytest.raises(PermissionError):manager.get_session(context('8','10'),session['session_id'])
        with request_scope(context('8','10')):
            assert polls.get_poll('100',session['poll_id']) is None
            assert not polls.vote('100',session['poll_id'],1,'8','Member')[0]
        manager.rsvp(context('8'),session['session_id'],'maybe',visibility='organizer')
        assert manager.get_session(context(),session['session_id'])['rsvps'][0]['response']=='maybe'
    finally:calendar._storage.close();polls._storage.close()


def test_expired_poll_and_revoked_permission_never_finalize(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        original=polls.polls
        original['100'][session['poll_id']]['expires_at']='2020-01-01T00:00:00+00:00'
        polls.polls=original;polls._save_polls()
        with pytest.raises(ValueError,match='poll_expired'):
            manager.preview_finalize(context(),session['session_id'],selection=1)
        original=polls.polls;original['100'][session['poll_id']]['expires_at']='2030-01-01T00:00:00+00:00';polls.polls=original;polls._save_polls()
        preview=manager.preview_finalize(context(),session['session_id'],selection=1)
        calendar.access_policy=AccessPolicy([ScopeRecord('shared','legacy_shared')])
        with pytest.raises(PermissionError):asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
        assert not calendar.items
    finally:calendar._storage.close();polls._storage.close()


def test_old_poll_reader_refuses_planning_generation(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        manager.create(context(),'group:approved','Film',candidates())
        from utils.storage_contract import load_document
        assert load_document(polls.storage_path,1).status=='unsupported'
        assert load_document(polls.storage_path,2).status=='unsupported'
    finally:calendar._storage.close();polls._storage.close()


def test_failed_calendar_commit_can_be_reviewed_again_after_restart(tmp_path,monkeypatch):
    from utils.storage_contract import StorageCommit,StorageMutationError
    manager,calendar,polls=fixture(tmp_path)
    session=manager.create(context(),'group:approved','Film',candidates())
    preview=manager.preview_finalize(context(),session['session_id'],selection=1)
    with monkeypatch.context() as patch:
        patch.setattr(calendar._storage,'commit',lambda *_args,**_kwargs:StorageCommit(False,'write_failed'))
        with pytest.raises(StorageMutationError):asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
    assert not calendar.items
    calendar._storage.close();polls._storage.close()
    manager,calendar,polls=fixture(tmp_path)
    try:
        retry=manager.preview_finalize(context(),session['session_id'])
        result=asyncio.run(manager.finalize(context(),session['session_id'],retry.token))
        assert result['status']=='finalized' and len(calendar.items['group:approved'])==1
    finally:calendar._storage.close();polls._storage.close()


def test_failed_final_receipt_reconciles_existing_event_without_duplicate(tmp_path,monkeypatch):
    from utils.storage_contract import StorageCommit
    manager,calendar,polls=fixture(tmp_path)
    session=manager.create(context(),'group:approved','Film',candidates())
    preview=manager.preview_finalize(context(),session['session_id'],selection=1)
    original=polls._storage.commit; calls=[]
    def fail_second(*args,**kwargs):
        calls.append(True)
        return StorageCommit(False,'write_failed') if len(calls)==2 else original(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(polls._storage,'commit',fail_second)
        result=asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
    assert result['status']=='finalized_reconciliation_pending'
    assert manager.get_session(context(),session['session_id'])['state']=='finalized'
    calendar._storage.close();polls._storage.close()
    manager,calendar,polls=fixture(tmp_path)
    try:
        again=asyncio.run(manager.finalize(context(),session['session_id'],'restart-reconcile'))
        assert again['event_id']==result['event_id'] and len(calendar.items['group:approved'])==1
    finally:calendar._storage.close();polls._storage.close()


@pytest.mark.parametrize('selection',[True,1.5,'1',0,11])
def test_invalid_selection_never_changes_votes(tmp_path,selection):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        revision=polls._storage.revision
        with pytest.raises(ValueError):manager.vote(context(),session['session_id'],selection)
        assert polls._storage.revision==revision
    finally:calendar._storage.close();polls._storage.close()


def test_poll_api_cannot_forge_organizer_or_voter(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        with request_scope(context('8')):
            assert not polls.vote('100',session['poll_id'],1,'7','Forged')[0]
            assert not polls.edit_poll('100',session['poll_id'],'7',question='Forged')[0]
            assert not polls.close_poll('100',session['poll_id'])[0]
        assert not calendar.items
    finally:calendar._storage.close();polls._storage.close()


def test_post_finalize_poll_change_does_not_reschedule(tmp_path):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        preview=manager.preview_finalize(context(),session['session_id'],selection=1)
        result=asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
        revision=calendar._storage.revision
        with request_scope(context()):
            assert not polls.edit_poll('100',session['poll_id'],'7',question='Another date')[0]
            assert not polls.delete_poll('100',session['poll_id'],'7')[0]
        assert asyncio.run(manager.finalize(context(),session['session_id'],preview.token))['event_id']==result['event_id']
        assert calendar._storage.revision==revision
    finally:calendar._storage.close();polls._storage.close()


def test_watchlist_is_an_explicit_snapshot_and_private_scope_is_refused(tmp_path):
    from types import SimpleNamespace
    manager,calendar,polls=fixture(tmp_path)
    entries=[{'title':'Fixture movie','added_at':'2026-10-01'}]
    manager.watchlist=SimpleNamespace(get_watchlist=lambda **kwargs: entries if kwargs['guild_id']=='100' else [])
    try:
        session=manager.create_from_watchlist(context(),'group:approved',1,candidates())
        entries[0]['title']='Edited later'
        assert manager.get_session(context(),session['session_id'])['activity_source']['title']=='Fixture movie'
        calendar.access_policy=AccessPolicy([ScopeRecord('private:7','private_user',owner_id='7')],default_scope='private:7')
        with pytest.raises(PermissionError):manager.create(context(),'private:7','Private',candidates())
    finally:calendar._storage.close();polls._storage.close()


async def test_scripted_command_flow_routes_then_confirms_one_event(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from features.planning_handler import PlanningHandler
    from core.intent_router import IntentRouter,BotIntent
    from core.command_registry import validate_payload
    manager,calendar,polls=fixture(tmp_path)
    handler=PlanningHandler(SimpleNamespace(planning=manager,rate_limiter=None,loc=None,client=None))
    handler.send_response=AsyncMock()
    from tests.test_intent_router import DummyMonitor
    router=IntentRouter(DummyMonitor())
    message=SimpleNamespace(id=42,author=SimpleNamespace(id=7),guild=SimpleNamespace(id=100),channel=SimpleNamespace(id=9))
    async def command(text):
        result=router.route(text)
        assert result.intent==BotIntent.PLANNING
        payload=validate_payload(result.intent,result.payload)['planning']
        with request_scope(context()):await handler.handle_planning(message,payload)
    try:
        await command('planlegg Film | 04.01.2027 18:00 / 05.01.2027 18:00 | 120')
        session=next(iter(polls.polls['100'].values()))['_planning']
        await command('plan stem '+session['session_id']+' 2')
        await command('plan vurder '+session['session_id'])
        assert not calendar.items and 'Varsler er av' in handler.send_response.await_args.args[1]
        token=next(iter(manager.previews.entries))
        await command('plan bekreft '+session['session_id']+' '+token)
        assert len(calendar.items['group:approved'])==1 and calendar.items['group:approved'][0]['date']=='05.01.2027'
        assert router.route('Jeg vil gjerne planlegge film i morgen').intent!=BotIntent.PLANNING
        with pytest.raises(ValueError):validate_payload(BotIntent.PLANNING,{'planning':{'action':'view','session_id':session['session_id'],'user_id':'8'}})
    finally:calendar._storage.close();polls._storage.close()


def test_unapproved_planning_event_is_absent_from_proactive_paths(tmp_path):
    from types import SimpleNamespace
    from features.daily_digest_manager import DailyDigestManager
    from cal_system.reminder_checker import ReminderChecker
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        preview=manager.preview_finalize(context(),session['session_id'],selection=1)
        asyncio.run(manager.finalize(context(),session['session_id'],preview.token))
        event=calendar.items['group:approved'][0]
        checker=ReminderChecker(calendar_manager=calendar,storage_path=tmp_path/'sent.json')
        assert not checker._legacy_allowed(event)
        with request_scope(context()):assert checker._calendar_buckets()['group:approved']==[]
        digest=DailyDigestManager(event_manager=SimpleNamespace(get_upcoming=lambda *args,**kwargs:[event]),clock=SimpleNamespace(now=lambda: __import__('datetime').datetime(2027,1,4)))
        assert digest._get_today_events('group:approved',proactive=True)==[]
        assert digest._get_today_events('group:approved')==[event]
        checker.close_storage()
    finally:calendar._storage.close();polls._storage.close()


async def test_revocation_during_intent_commit_holds_calendar_write(tmp_path,monkeypatch):
    manager,calendar,polls=fixture(tmp_path)
    try:
        session=manager.create(context(),'group:approved','Film',candidates())
        preview=manager.preview_finalize(context(),session['session_id'],selection=1)
        commit=manager._commit_polls
        async def revoked():
            await commit()
            calendar.access_policy=AccessPolicy([ScopeRecord('shared','legacy_shared')])
        monkeypatch.setattr(manager,'_commit_polls',revoked)
        with pytest.raises(PermissionError):await manager.finalize(context(),session['session_id'],preview.token)
        assert not calendar.items
    finally:calendar._storage.close();polls._storage.close()
