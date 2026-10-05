"""One group activity, explicit organizer approval and recoverable identity."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import uuid

from cal_system.event_schema import EventTime
from cal_system.mutation_preview import PreviewCache, actor_key
from core.request_context import request_scope
from utils.json_storage import write_json_atomic
from utils.storage_contract import StorageMutationError, store_worker, writable_store

STATES = frozenset({'draft','voting','review','finalized','cancelled'})
RSVP_RESPONSES = frozenset({'yes','no','maybe'})
VISIBILITIES = frozenset({'self','organizer','group'})


@dataclass(frozen=True)
class PlanningSession:
    session_id: str
    scope_id: str
    organizer_id: str
    poll_id: str
    state: str
    event_id: str | None
    revision: int


def validate_planning_session(value, poll):
    try:
        if (not isinstance(value,dict) or value.get('state') not in STATES
            or not isinstance(value.get('session_id'),str) or len(value['session_id'])!=32
            or not isinstance(value.get('title'),str) or not 1<=len(value['title'])<=200
            or value.get('poll_id')!=poll['id'] or value.get('organizer_id')!=str(poll.get('created_by_id'))
            or type(value.get('revision')) is not int or value['revision']<0
            or any(not isinstance(value.get(key),str) or not value[key] for key in ('scope_id','organizer_id','channel_id','bucket'))
            or value.get('event_id') is not None and not isinstance(value['event_id'],str)
            or not isinstance(value.get('candidates'),list) or not 1<=len(value['candidates'])<=10
            or not isinstance(value.get('rsvps'),dict) or len(value['rsvps'])>256):
            return False
        for candidate in value['candidates']:
            if not isinstance(candidate.get('option_id'),str): return False
            time=EventTime.from_item(candidate['time']).validate_local()
            if time.kind!='event' or time.all_day or not time.duration_minutes: return False
        for user, response in value['rsvps'].items():
            if (not isinstance(user,str) or not user or len(user)>128 or not isinstance(response,dict)
                or response.get('response') not in RSVP_RESPONSES or response.get('visibility') not in VISIBILITIES): return False
        intent=value.get('finalize_intent')
        if intent is not None:
            if (not isinstance(intent,dict) or set(intent)!={'event_id','source','notify'}
                or intent.get('event_id')!=uuid.uuid5(uuid.NAMESPACE_URL,'inebotten:planning:'+value['session_id']).hex
                or type(intent.get('notify')) is not bool or poll.get('status')!='closed'
                or value['state'] not in ('review','finalized')): return False
            source=intent.get('source')
            if (not isinstance(source,dict) or set(source)!={'session_id','poll_id','option_id','time','organizer_id'}
                or any(source[key]!=value[key] for key in ('session_id','poll_id','organizer_id'))
                or not any(candidate['option_id']==source['option_id'] and candidate['time']==source['time']
                    for candidate in value['candidates'])): return False
        if value['state']=='finalized' and (intent is None or value['event_id']!=intent['event_id']): return False
        return True
    except (KeyError,TypeError,ValueError,AttributeError):
        return False


def _poll_fingerprint(poll):
    # The selected option's identity and all votes/status affect approval.
    raw={key:poll.get(key) for key in ('id','revision','question','options','status','expires_at')}
    return hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()


class PlanningManager:
    def __init__(self, calendar, polls, *, watchlist=None):
        self.calendar,self.polls,self.watchlist=calendar,polls,watchlist
        self._storage=polls._storage
        self.previews=PreviewCache(calendar.clock,max_items=1,max_bytes=256*1024)
        polls.planning_authorizer=lambda actor,scope:self._allowed(actor,scope,'read')

    def _allowed(self, actor, scope, operation):
        record=self.calendar.access_policy.scopes.get(scope)
        return bool(record and record.kind!='private_user'
            and self.calendar.access_policy.authorize(actor,scope,'read').allowed
            and self.calendar.access_policy.authorize(actor,scope,operation).allowed)

    def _authorize(self, actor, scope, operation):
        actor_key(actor)
        if not self._allowed(actor,scope,operation): raise PermissionError('planning_scope_required')

    def _record(self, actor, session_id, *, organizer=False, operation='read'):
        records=self.polls.polls
        for bucket in records.values():
            for poll in bucket.values():
                value=poll.get('_planning')
                if value and value['session_id']==session_id:
                    self._authorize(actor,value['scope_id'],operation)
                    if actor.channel_id!=value['channel_id']: raise PermissionError('planning_audience_required')
                    if organizer and actor.user_id!=value['organizer_id']: raise PermissionError('organizer_required')
                    return poll,value
        raise ValueError('planning_session_missing')

    @writable_store
    def create(self, actor, scope, title, times, *, _activity_source=None):
        self._authorize(actor,scope,'write')
        if not isinstance(title,str) or not title.strip() or len(title)>200:
            raise ValueError('invalid_planning_title')
        if not isinstance(times,list) or not 1<=len(times)<=10:
            raise ValueError('invalid_planning_candidates')
        if sum('_planning' in poll for bucket in self.polls.polls.values() for poll in bucket.values())>=256:
            raise ValueError('planning_capacity')
        normalized=[]; keys=set()
        for time in times:
            if not isinstance(time,EventTime) or time.kind!='event' or time.all_day or not time.duration_minutes or time.duration_minutes>1440:
                raise ValueError('explicit_event_time_required')
            time.validate_local()
            if time.local_date<self.calendar.clock.now(time.timezone).date(): raise ValueError('planning_time_in_past')
            key=json.dumps(time.fields(),sort_keys=True)
            if key in keys: raise ValueError('duplicate_planning_candidate')
            keys.add(key);normalized.append(time)
        bucket=actor.guild_id or actor.channel_id
        labels=[f"{time.local_date:%d.%m.%Y} kl. {time.local_time:%H:%M} ({time.timezone}), {time.duration_minutes} min" for time in normalized]
        poll=self.polls._new_poll_record(bucket,title.strip(),labels,'Arrangør',actor.user_id)
        session={'session_id':uuid.uuid4().hex,'scope_id':scope,'organizer_id':actor.user_id,
            'poll_id':poll['id'],'title':title.strip(),'channel_id':actor.channel_id,'bucket':bucket,
            'state':'voting','event_id':None,'revision':0,'rsvps':{},'candidates':[
                {'option_id':option['id'],'time':time.fields()} for option,time in zip(poll['options'],normalized)]}
        if _activity_source is not None:
            session['activity_source']=copy.deepcopy(_activity_source)
        poll['_planning']=session
        self.polls.polls.setdefault(bucket,{})[poll['id']]=poll
        self.polls._save_polls()
        return copy.deepcopy(session)

    def create_from_watchlist(self, actor, scope, index, times):
        self._authorize(actor,scope,'write')
        if self.watchlist is None or type(index) is not int: raise ValueError('watchlist_selection_required')
        entries=self.watchlist.get_watchlist(guild_id=actor.guild_id or actor.channel_id)
        if not 1<=index<=len(entries): raise ValueError('watchlist_selection_changed')
        entry=entries[index-1]
        source={'kind':'watchlist','bucket':actor.guild_id or actor.channel_id,'index':index,
            'title':entry['title'],'added_at':entry.get('added_at')}
        return self.create(actor,scope,entry['title'],times,_activity_source=source)

    @writable_store
    def get_session(self, actor, session_id):
        poll,value=self._record(actor,session_id)
        visible=copy.deepcopy(value)
        visible.pop('finalize_intent',None)
        found=[item for item in self.calendar.items.get(value['scope_id'],[])
            if item.get('_planning_source',{}).get('session_id')==session_id]
        if len(found)==1 and not found[0].get('_mutation_deleted') and not found[0].get('delete_pending'):
            visible.update(state='finalized',event_id=found[0]['id'],
                reconciliation_pending=value['state']!='finalized')
        visible['rsvps']=[{'user_id':user,**copy.deepcopy(response)} for user,response in value['rsvps'].items()
            if user==actor.user_id or response['visibility']=='group'
            or response['visibility']=='organizer' and actor.user_id==value['organizer_id']]
        visible['votes']=[{'option_id':option['id'],'text':option['text'],'count':len(option['votes'])} for option in poll['options']]
        visible['expired']=self.polls._is_expired(poll)
        return visible

    @writable_store
    def vote(self, actor, session_id, selection):
        poll,value=self._record(actor,session_id)
        if type(selection) is not int or not 1<=selection<=len(value['candidates']):
            raise ValueError('invalid_planning_selection')
        if value['state'] not in ('voting','review') or value.get('finalize_intent'):
            raise ValueError('planning_voting_closed')
        with request_scope(actor):
            success,reason=self.polls.vote(value['bucket'],poll['id'],selection,actor.user_id,'Deltaker')
        if not success: raise ValueError('planning_vote_refused')
        return True

    @writable_store
    def rsvp(self, actor, session_id, response, *, visibility='organizer'):
        poll,value=self._record(actor,session_id)
        if value['state']=='cancelled': raise ValueError('planning_cancelled')
        if response not in RSVP_RESPONSES or visibility not in VISIBILITIES: raise ValueError('invalid_rsvp')
        if actor.user_id not in value['rsvps'] and len(value['rsvps'])>=256: raise ValueError('rsvp_capacity')
        value['rsvps'][actor.user_id]={'response':response,'visibility':visibility}
        value['revision']+=1
        self.polls._save_polls()
        return {'response':response,'visibility':visibility}

    @writable_store
    def cancel(self, actor, session_id):
        poll,value=self._record(actor,session_id,organizer=True,operation='write')
        if value['state']=='finalized' or value.get('finalize_intent'): raise ValueError('finalization_already_started')
        value['state']='cancelled';value['revision']+=1;poll['status']='closed';poll['revision']+=1
        self.polls._save_polls()

    def preview_finalize(self, actor, session_id, *, selection=None, notify=False):
        if type(notify) is not bool: raise ValueError('invalid_notification_approval')
        # Calendar -> polls matches backup freeze ordering. No awaiting while
        # holding synchronous read transactions.
        with self.calendar._storage.transaction(write=False),self._storage.transaction(write=False):
            if self.calendar._storage._async_active or self._storage._async_active: raise StorageMutationError('store_busy')
            poll,value=self._record(actor,session_id,organizer=True,operation='write')
            if value['state'] not in ('voting','review'): raise ValueError('planning_not_reviewable')
            intent=value.get('finalize_intent')
            if self.polls._is_expired(poll) and intent is None: raise ValueError('poll_expired')
            if [option['id'] for option in poll['options']]!=[candidate['option_id'] for candidate in value['candidates']]:
                raise ValueError('planning_options_changed')
            if intent:
                frozen=next((index+1 for index,candidate in enumerate(value['candidates'])
                    if candidate['option_id']==intent['source']['option_id']),None)
                if frozen is None or selection is not None and selection!=frozen:
                    raise ValueError('planning_intent_mismatch')
                selection=frozen;notify=intent['notify']
            elif selection is None:
                counts=[len(option['votes']) for option in poll['options']]
                best=max(counts)
                if not best or counts.count(best)!=1: raise ValueError('explicit_selection_required')
                selection=counts.index(best)+1
            if type(selection) is not int or not 1<=selection<=len(value['candidates']): raise ValueError('invalid_planning_selection')
            picked=value['candidates'][selection-1]
            EventTime.from_item(picked['time']).validate_local()
            before={'id':session_id,'title':value['title'],'session_revision':value['revision'],
                'poll_fingerprint':_poll_fingerprint(poll),'calendar_revision':self.calendar._storage.revision}
            after={**before,'selection':selection,'time':copy.deepcopy(picked['time']),
                'option_id':picked['option_id'],'notify':notify,'channel_id':value['channel_id']}
            return self.previews.create(actor,value['scope_id'],self._storage.revision,'finalize',[before],[after])

    async def _commit_polls(self):
        result=await store_worker(self._storage.commit,copy.deepcopy(self.polls.polls),writer=write_json_atomic)
        if not result.ok: raise StorageMutationError(result.error_code)

    async def finalize(self, actor, session_id, preview_token):
        async with self.calendar._storage.async_transaction(), self._storage.async_transaction():
            poll,value=self._record(actor,session_id,organizer=True,operation='write')
            events=self.calendar.items.get(value['scope_id'],[])
            intent=value.get('finalize_intent')
            found=[item for item in events if item.get('_planning_source',{}).get('session_id')==session_id]
            if len(found)>1: raise ValueError('planning_identity_conflict')
            if found:
                event=found[0]
                if event.get('_mutation_deleted') or event.get('delete_pending'): raise ValueError('planning_event_removed')
                if value.get('event_id') and value['event_id']!=event['id']: raise ValueError('planning_identity_conflict')
                if intent and intent['source']!=event['_planning_source']: raise ValueError('planning_identity_conflict')
                if value['state']!='finalized':
                    value.update(state='finalized',event_id=event['id'],revision=value['revision']+1)
                    poll.update(status='closed',revision=poll['revision']+1)
                    try:
                        await self._commit_polls()
                    except StorageMutationError:
                        self.polls.polls=self._storage.rollback()
                        return {'event_id':event['id'],'status':'finalized_reconciliation_pending'}
                return {'event_id':event['id'],'status':'already_finalized'}
            if value['state']=='finalized': raise ValueError('planning_event_missing')
            if value['state']=='cancelled': raise ValueError('planning_cancelled')
            entry=self.previews.get(actor,preview_token)
            if entry['scope']!=value['scope_id'] or entry['before'][0]['id']!=session_id: raise ValueError('planning_preview_mismatch')
            before,after=entry['before'][0],entry['after'][0]
            if before['calendar_revision']!=self.calendar._storage.revision: raise ValueError('calendar_changed')
            if intent is None:
                if before['poll_fingerprint']!=_poll_fingerprint(poll): raise ValueError('poll_changed')
                if entry['revision']!=self._storage.revision or before['session_revision']!=value['revision']: raise ValueError('revision_changed')
                if self.polls._is_expired(poll): raise ValueError('poll_expired')
                source={'session_id':session_id,'poll_id':poll['id'],'option_id':after['option_id'],
                    'time':copy.deepcopy(after['time']),'organizer_id':actor.user_id}
                intent={'event_id':uuid.uuid5(uuid.NAMESPACE_URL,'inebotten:planning:'+session_id).hex,
                    'source':source,'notify':after['notify']}
                value['finalize_intent']=intent;value['state']='review';value['revision']+=1
                # Freeze voting with the durable intent before the calendar write.
                poll['status']='closed';poll['revision']+=1
                await self._commit_polls()
            elif intent['source']['time']!=after['time'] or intent['notify']!=after['notify']:
                raise ValueError('planning_intent_mismatch')
            self._authorize(actor,value['scope_id'],'write')
            time=EventTime.from_item(intent['source']['time']).validate_local()
            if time.local_date<self.calendar.clock.now(time.timezone).date(): raise ValueError('planning_time_in_past')
            event={'id':intent['event_id'],'scope_id':value['scope_id'],'title':value['title'],
                'description':'Aktivitet bekreftet av arrangøren. RSVP er ikke kalenderinvitasjoner.',
                **time.fields(),'user_id':actor.user_id,'username':'Arrangør','completed':False,
                'created_at':self.calendar.clock.now().isoformat(),'recurrence':None,'recurrence_day':None,
                'gcal_event_id':None,'gcal_link':None,'channel_id':value['channel_id'] if intent['notify'] else None,
                '_planning_source':copy.deepcopy(intent['source']),'planning_notifications_approved':intent['notify']}
            if any(item['id']==event['id'] for bucket in self.calendar.items.values() for item in bucket):
                raise ValueError('planning_identity_conflict')
            self.calendar.items.setdefault(value['scope_id'],[]).append(event)
            await self.calendar._save_data()
            value.update(state='finalized',event_id=event['id'],revision=value['revision']+1)
            try:
                await self._commit_polls()
            except StorageMutationError:
                # The source identity committed with the event is authoritative.
                # Retry reconciles its existing receipt; it never recreates it.
                self.polls.polls=self._storage.rollback()
                return {'event_id':event['id'],'status':'finalized_reconciliation_pending'}
            self.previews.entries.pop(preview_token,None)
            return {'event_id':event['id'],'status':'finalized'}
