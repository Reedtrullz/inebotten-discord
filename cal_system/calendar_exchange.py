"""Bounded local ICS files, explicit scopes and inert import previews."""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Todo

from cal_system.event_schema import EventTime
from cal_system.mutation_preview import PreviewCache, actor_key, before_image
from cal_system.recurrence import Series, parse_google_recurrence
from utils.storage_contract import StorageMutationError, writable_store

MAX_BYTES = 1024 * 1024
MAX_ITEMS = 256
PROPERTIES = {'UID','SUMMARY','DESCRIPTION','DTSTART','DTEND','DUE','DURATION','RRULE',
    'DTSTAMP','CREATED','LAST-MODIFIED','SEQUENCE','STATUS','COMPLETED','PERCENT-COMPLETE',
    'TRANSP','CLASS','X-INEBOTTEN-TIMEZONE','X-INEBOTTEN-COMPLETED'}
FIELDS = ('title','description','date','time','kind','all_day','timezone','duration_minutes',
    'fold','completed','recurrence','recurrence_day','series')


def _bounded_file(data):
    if type(data) is not bytes or not data or len(data) > MAX_BYTES:
        raise ValueError('invalid_ics_size')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        raise ValueError('invalid_ics_encoding') from None
    if any(ord(char) < 32 and char not in '\r\n\t' for char in text):
        raise ValueError('invalid_ics_control')
    lines = []
    for line in text.splitlines():
        if line.startswith((' ','\t')):
            if not lines:
                raise ValueError('invalid_ics_fold')
            lines[-1] += line[1:]
        else:
            lines.append(line)
        if len(lines[-1].encode()) > 8192 or len(lines) > 8192:
            raise ValueError('ics_line_limit')
    stack, clean, timezone_names = [], [], []
    component_count = 0
    for line in lines:
        upper = line.upper()
        if upper.startswith('BEGIN:'):
            name = upper[6:]
            if not stack and (name != 'VCALENDAR' or clean):
                raise ValueError('invalid_ics_root')
            stack.append(name); component_count += 1
            if len(stack) > 4 or component_count > 1024:
                raise ValueError('ics_component_limit')
        inside_timezone = 'VTIMEZONE' in stack
        if inside_timezone and upper.startswith('TZID:'):
            zone = line[5:]
            try: ZoneInfo(zone)
            except (ValueError, KeyError): raise ValueError('custom_timezone_unsupported') from None
            timezone_names.append(zone)
        # Never let an uploaded VTIMEZONE override the process-wide trusted
        # IANA timezone cache. Components are bounded before library parsing.
        if not inside_timezone and line:
            clean.append(line)
        if upper.startswith('END:'):
            if not stack or stack.pop() != upper[4:]:
                raise ValueError('invalid_ics_nesting')
    if stack or not clean or clean[-1].upper() != 'END:VCALENDAR':
        raise ValueError('invalid_ics_nesting')
    return '\r\n'.join(clean).encode()+b'\r\n', timezone_names


def _uid(item):
    return item.get('_ics_source', {}).get('uid') or item['id']+'@inebotten.invalid'


def _semantic(item):
    value = {key: copy.deepcopy(item.get(key)) for key in FIELDS}
    value['description'] = value['description'] or ''
    if value['kind']=='event' and value['all_day'] and value['duration_minutes'] is None:
        value['duration_minutes']=1440
    if value['series']:
        anchor=value['series']['anchor_time']
        if anchor.get('kind')=='event' and anchor.get('all_day') and anchor.get('duration_minutes') is None:
            anchor['duration_minutes']=1440
    return value


def _history_or_remote(item):
    return bool(item.get('occurrences') or item.get('series_history') or item.get('series_next_index',0)
        or item.get('gcal_event_id') or item.get('sync_operations') or item.get('_local_sync_pending')
        or item.get('_recurrence_readonly') or item.get('_mutation_deleted') or item.get('delete_pending'))


def _rrule(series):
    rule = {'FREQ': {'daily':'DAILY','weekly':'WEEKLY','biweekly':'WEEKLY',
        'monthly':'MONTHLY','yearly':'YEARLY'}[series.rule['frequency']]}
    if series.rule['interval'] != 1: rule['INTERVAL'] = series.rule['interval']
    if series.rule.get('weekdays'): rule['BYDAY'] = series.rule['weekdays']
    if series.end_count is not None: rule['COUNT'] = series.end_count
    if series.end_date is not None:
        rule['UNTIL'] = (series.end_date if series.anchor_time.all_day else
            EventTime(series.anchor_time.kind,series.end_date,series.anchor_time.local_time,
                series.anchor_time.timezone,False,series.anchor_time.duration_minutes,
                series.anchor_time.fold).aware_start().astimezone(timezone.utc))
    return rule


def _export_component(item, clock):
    if item.get('_recurrence_readonly'):
        raise ValueError('unsupported_exchange_recurrence')
    value = EventTime.from_item(item).validate_local()
    if value.local_time is not None:
        # RFC local date-times cannot carry Python's fold discriminator.
        replace(value,fold=None).validate_local()
    if value.kind == 'task' and (not value.all_day or value.local_time):
        raise ValueError('timed_task_exchange_unsupported')
    component = Todo() if value.kind == 'task' else Event()
    component.add('uid', _uid(item)); component.add('summary', item['title'])
    component.add('description',item.get('description') or '')
    component.add('dtstamp',clock.now().astimezone(timezone.utc))
    component.add('x-inebotten-timezone',value.timezone)
    component.add('x-inebotten-completed','TRUE' if item.get('completed') else 'FALSE')
    if value.kind == 'task':
        component.add('due',value.local_date)
        if item.get('completed'): component.add('status','COMPLETED')
    elif value.all_day:
        component.add('dtstart',value.local_date)
        component.add('dtend',value.local_date+timedelta(minutes=value.duration_minutes or 1440))
    else:
        if value.duration_minutes is None: raise ValueError('event_duration_required')
        start = value.aware_start()
        component.add('dtstart',start)
        # Duration represents actual elapsed minutes, including a DST boundary.
        component.add('dtend',start.astimezone(timezone.utc)+timedelta(minutes=value.duration_minutes))
    if item.get('series'):
        if _history_or_remote(item): raise ValueError('occurrence_history_exchange_unsupported')
        series = Series.from_document(item['series'])
        raw_rule = _rrule(series); component.add('rrule',raw_rule)
        if not parse_google_recurrence(['RRULE:'+component['rrule'].to_ical().decode()], series.anchor_time)['supported']:
            raise ValueError('unsupported_exchange_recurrence')
        if value.kind == 'task': component.add('dtstart',value.local_date)
    return component


def _single(component, name, *, required=False):
    value = component.get(name)
    if isinstance(value,list) or required and value is None:
        raise ValueError('invalid_ics_'+name.lower())
    return value


def _time(component, name, *, required=True):
    prop = _single(component,name,required=required)
    if prop is None: return None
    zone = prop.params.get('TZID')
    if zone:
        try: ZoneInfo(str(zone))
        except (ValueError,KeyError): raise ValueError('custom_timezone_unsupported') from None
    value = prop.dt
    if not isinstance(value,(date,datetime)) or isinstance(value,datetime) and value.tzinfo is None:
        raise ValueError('floating_time_unsupported')
    return value


def _import_component(component, scope, clock):
    if component.name not in ('VEVENT','VTODO') or component.subcomponents or component.errors:
        raise ValueError('unsupported_ics_component')
    if set(component) - PROPERTIES:
        raise ValueError('unsupported_ics_property')
    uid = str(_single(component,'UID',required=True))
    title = str(_single(component,'SUMMARY',required=True)).strip()
    description = str(_single(component,'DESCRIPTION') or '')
    if not uid or len(uid.encode()) > 512 or not title or len(title) > 1000 or len(description)>10000:
        raise ValueError('ics_text_limit')
    if any(ord(c)<32 for c in uid): raise ValueError('invalid_ics_uid')
    kind = 'task' if component.name == 'VTODO' else 'event'
    start = _time(component,'DUE' if kind == 'task' else 'DTSTART')
    all_day = type(start) is date
    tz = str(_single(component,'X-INEBOTTEN-TIMEZONE') or
        (getattr(start.tzinfo,'key',None) if not all_day else None) or 'UTC')
    ZoneInfo(tz)
    duration = None
    if kind == 'task':
        if not all_day or _single(component,'DTEND') is not None or _single(component,'DURATION') is not None:
            raise ValueError('timed_task_exchange_unsupported')
        task_start = _time(component,'DTSTART',required=False)
        if task_start is not None and task_start != start: raise ValueError('task_start_exchange_unsupported')
    else:
        end = _time(component,'DTEND',required=False)
        duration_prop = _single(component,'DURATION')
        if end is not None and duration_prop is not None: raise ValueError('ambiguous_ics_duration')
        if end is None and duration_prop is not None:
            delta = duration_prop.dt
            if not isinstance(delta,timedelta): raise ValueError('invalid_ics_duration')
        elif end is not None:
            if type(end) is not type(start): raise ValueError('mixed_ics_time_types')
            delta = end-start if all_day else end.astimezone(timezone.utc)-start.astimezone(timezone.utc)
        elif all_day: delta = timedelta(days=1)
        else: raise ValueError('event_duration_required')
        seconds = delta.total_seconds()
        if seconds <= 0 or seconds%60 or seconds > 366*86400: raise ValueError('invalid_ics_duration')
        duration = int(seconds//60)
    local = start if all_day else start.astimezone(ZoneInfo(tz))
    if not all_day and (local.second or local.microsecond): raise ValueError('subminute_time_unsupported')
    value = EventTime(kind,local if all_day else local.date(),None if all_day else local.time().replace(tzinfo=None),
        tz,all_day,duration).validate_local()
    item_id = uuid.uuid5(uuid.NAMESPACE_URL,'inebotten:ics:'+scope+':'+uid).hex
    completed = str(_single(component,'X-INEBOTTEN-COMPLETED') or '').upper()=='TRUE'
    status = str(_single(component,'STATUS') or '').upper()
    if status not in ('','CONFIRMED','TENTATIVE','NEEDS-ACTION','COMPLETED'):
        raise ValueError('unsupported_ics_status')
    item = {'id':item_id,'title':title,'description':description,**value.fields(),
        'completed':completed or kind=='task' and status=='COMPLETED', 'recurrence':None,'recurrence_day':None,
        'gcal_event_id':None,'gcal_link':None,'created_at':clock.now().isoformat(),'_ics_source':{'uid':uid}}
    rule = _single(component,'RRULE')
    if rule is not None:
        parsed = parse_google_recurrence(['RRULE:'+rule.to_ical().decode()],value)
        if not parsed['supported']: raise ValueError('unsupported_exchange_recurrence')
        series = Series(item_id,value,parsed['rule'],parsed['end_count'],parsed['end_date'])
        item.update(series=series.to_document(),series_next_index=0,occurrences={},
            recurrence=series.rule['frequency'],recurrence_day=series.rule.get('weekdays',[None])[0])
    return item


class CalendarExchange:
    def __init__(self, calendar):
        self.calendar=calendar; self._storage=calendar._storage
        self.previews=PreviewCache(calendar.clock,max_items=MAX_ITEMS)

    def _authorize(self, actor, scope, operation):
        actor_key(actor)
        if (not self.calendar.access_policy.authorize(actor,scope,operation).allowed
            or operation=='write' and not self.calendar.access_policy.authorize(actor,scope,'read').allowed):
            raise PermissionError('scope_membership_required')

    @writable_store
    def export_ics(self, actor, scope, item_ids):
        self._authorize(actor,scope,'read')
        if not isinstance(item_ids,list) or not item_ids or len(item_ids)>MAX_ITEMS or len(set(item_ids))!=len(item_ids):
            raise ValueError('invalid_selection_size')
        records={item['id']:item for item in self.calendar.items.get(scope,[])
            if not item.get('_mutation_deleted') and not item.get('delete_pending')}
        if any(key not in records for key in item_ids): raise ValueError('selection_changed')
        result=Calendar(); result.add('prodid','-//Inebotten//Reviewed local exchange//NO'); result.add('version','2.0')
        for key in item_ids: result.add_component(_export_component(records[key],self.calendar.clock))
        # This operates only on trusted source records / installed timezone data.
        result.add_missing_timezones()
        data=result.to_ical()
        if len(data)>MAX_BYTES: raise ValueError('invalid_ics_size')
        return data

    def preview_ics(self, actor, scope, data):
        self._authorize(actor,scope,'write')
        raw, zones = _bounded_file(data)
        try: parsed=Calendar.from_ical(raw)
        except Exception: raise ValueError('invalid_ics_file') from None
        if str(parsed.get('VERSION'))!='2.0' or str(parsed.get('METHOD','')).upper() not in ('','PUBLISH'):
            raise ValueError('unsupported_ics_calendar')
        if len(parsed.subcomponents)>MAX_ITEMS: raise ValueError('ics_item_limit')
        candidates=[]; unsupported=[]; seen=set()
        for component in parsed.subcomponents:
            try:
                item=_import_component(component,scope,self.calendar.clock)
                uid=item['_ics_source']['uid']
                if uid in seen: raise ValueError('duplicate_ics_uid')
                seen.add(uid); candidates.append(item)
            except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as error:
                if str(error)=='duplicate_ics_uid': raise
                unsupported.append({'index':len(candidates)+len(unsupported),'reason':str(error)[:100]})
        with self._storage.transaction(write=False):
            if self._storage._async_active: raise StorageMutationError('store_busy')
            existing={_uid(item):item for item in self.calendar.items.get(scope,[])}
            if len(existing)!=len(self.calendar.items.get(scope,[])): raise ValueError('ambiguous_source_uid')
            before=[]; after=[]; counts={'new':0,'changed':0,'duplicate':0}
            ids={item['id'] for item in self.calendar.items.get(scope,[])}
            for item in candidates:
                prior=existing.get(item['_ics_source']['uid'])
                if prior:
                    item['id']=prior['id']
                    if item.get('series'): item['series']['series_id']=prior['id']
                    if _semantic(item)==_semantic(prior): counts['duplicate']+=1; continue
                    if _history_or_remote(prior):
                        unsupported.append({'uid':item['_ics_source']['uid'],'reason':'local_history_or_remote_review_required'}); continue
                    replacement=copy.deepcopy(prior); replacement.update(_semantic(item)); replacement['_ics_source']=item['_ics_source']
                    if not item.get('series'):
                        for field in ('series','series_next_index','occurrences','series_history'):
                            replacement.pop(field,None)
                    else:
                        replacement.update(series_next_index=0,occurrences={})
                    before.append(before_image(prior)); after.append(replacement); counts['changed']+=1
                else:
                    if item['id'] in ids: raise ValueError('source_identity_collision')
                    item.update(user_id=actor.user_id,username='ICS-import')
                    before.append({'id':item['id'],'title':item['title'],'_exchange_missing':True}); after.append(item); counts['new']+=1
            # Empty/duplicate-only files are also actor-bound, inert confirmations.
            sentinel={'id':'__exchange_empty__','title':'Ingen endringer','_exchange_missing':True}
            preview=self.previews.create(actor,scope,self._storage.revision,'import',before or [sentinel],after or [sentinel])
            return {'token':preview.token,'revision':preview.revision,'expires_at':preview.expires_at.isoformat(),
                **counts,'unsupported':unsupported,'warnings':['iana_timezone_definitions_ignored'] if zones else [],
                'effects':preview.effects if after else []}

    @writable_store
    async def apply(self, actor, token):
        entry=self.previews.get(actor,token); scope=entry['scope']
        self._authorize(actor,scope,'write')
        if entry['revision']!=self._storage.revision: raise ValueError('revision_changed')
        before,after=entry['before'],entry['after']
        if before[0]['id']=='__exchange_empty__':
            self.previews.entries.pop(token,None); return {'applied_count':0}
        records={item['id']:item for item in self.calendar.items.get(scope,[])}
        for item in before:
            prior=records.get(item['id'])
            if item.get('_exchange_missing'):
                if prior is not None: raise ValueError('selection_changed')
            elif prior is None or before_image(prior)!=item: raise ValueError('selection_changed')
        replacements={item['id']:item for item in after}
        self.calendar.items[scope]=[replacements.pop(item['id'],item) for item in self.calendar.items.get(scope,[])]+list(replacements.values())
        await self.calendar._save_data()
        self.previews.entries.pop(token,None)
        return {'applied_count':len(after),'remote_pending':False}
