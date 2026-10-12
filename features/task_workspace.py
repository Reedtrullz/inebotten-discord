import copy
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from cal_system.notification_preferences import NotificationProfile, delivery_schedule, after_quiet_hours, occurrence_identity
from cal_system.reminder_manager import validate_deadline
from cal_system.event_schema import EventTime
from cal_system.recurrence import project_current_occurrence, SUPPORTED_FREQUENCIES
from cal_system.mutation_preview import actor_key
from core.request_context import request_scope
from utils.local_undo import undo_change, undo_hint


def reminder_plan(item, memory, clock, scope) -> dict[str, Any]:
    value = item.get('due_date')
    profile = memory.notification_profile(str(item['user_id']), scope) if memory else None
    if profile is None:
        destination = str(item.get('channel_id') or '')
        if not destination.isdecimal():
            return {'next_at': None, 'message': 'Ingen godkjent varselkanal.'}
        profile = NotificationProfile(True, scope, destination)
    if not profile.enabled:
        return {'next_at': None, 'message': 'Egne varsler er pauset.'}
    snoozes = memory.notification_snoozes(str(item['user_id']), scope) if memory else []
    snoozed = [after_quiet_hours(profile, datetime.fromisoformat(s['due_at'])) for s in snoozes
        if s['item_id'] == item['id'] and s['occurrence_id'] == occurrence_identity(project_current_occurrence(item) or item)]
    snoozed = [instant for instant in snoozed if instant + timedelta(minutes=5) > clock.now('UTC')]
    if snoozed:
        schedule = [('snooze', instant) for instant in snoozed]
    else:
        value = validate_deadline(value, clock)
        if value is None:
            return {'next_at': None, 'message': 'Ingen frist: ingen automatisk varsling.'}
        date, _, local_time = value.partition(' ')
        due = EventTime.from_item({'kind': 'task', 'date': date, 'time': local_time or '09:00', 'timezone': 'Europe/Oslo'}).aware_start()
        schedule = [(kind, instant) for kind, instant in delivery_schedule(profile, due) if instant >= clock.now('UTC')]
    if not schedule:
        return {'next_at': None, 'message': 'Ingen fremtidige varsler planlagt. Eventuell forsinket levering vises i meldingskanalen.'}
    _, instant = min(schedule, key=lambda row: row[1])
    local = instant.astimezone(ZoneInfo(profile.timezone))
    return {'next_at': instant.isoformat(), 'destination_id': profile.destination_id,
        'message': f'Neste varsel: {local:%d.%m.%Y %H:%M} ({profile.timezone}) i <#{profile.destination_id}>. '
                   'Stille timer er medregnet; levering kan ta opptil ett minutt.'}


def task_workspace(monitor):
    if monitor is None:
        raise PermissionError('calendar_workspace_not_configured')
    owner = getattr(monitor, 'reminders', None) or monitor
    service = getattr(owner, '_task_workspace', None)
    if service is None:
        service = TaskWorkspace(monitor)
        owner._task_workspace = service
    elif hasattr(monitor, 'poll'):
        service.monitor = monitor
    return service


class TaskWorkspace:
    def __init__(self, monitor):
        self.monitor = monitor
        self.previews = {}
        self.actions = {}

    def _scope(self, actor, operation='read'):
        calendar = getattr(self.monitor, 'calendar', None)
        if actor is None or calendar is None:
            raise PermissionError('calendar_workspace_not_configured')
        policy = calendar.access_policy
        scope = policy.default_scope
        if not policy.authorize(actor, scope, operation).allowed:
            raise PermissionError('scope_membership_required')
        return scope

    def _reminders(self, actor):
        manager = getattr(self.monitor, 'reminders', None)
        if manager is None:
            return []
        selected = self._scope(actor)
        memory = getattr(self.monitor, 'user_memory', None)
        profile = memory.notification_profile(actor.user_id, selected) if memory else None
        result = []
        with request_scope(actor), manager._storage.transaction(write=False):
            for bucket, rows in manager.reminders.items():
                try:
                    _, scope = manager._scope_bucket(bucket, 'read')
                except PermissionError:
                    continue
                for item in rows:
                    if (scope != selected or not manager._record_in_scope(item, scope)
                        or str(item.get('user_id')) != actor.user_id or item.get('delete_pending')
                        or item.get('_mutation_deleted') or (actor.channel_id != 'console' and str(item.get('channel_id')) != actor.channel_id
                            and not (profile and profile.enabled and profile.destination_id == actor.channel_id))):
                        continue
                    result.append((bucket, copy.deepcopy(item)))
        return result

    def _polls(self, actor):
        manager = getattr(self.monitor, 'poll', None)
        if manager is None:
            return []
        with request_scope(actor), manager._storage.transaction(write=False):
            return [(bucket, copy.deepcopy(poll)) for bucket, rows in manager.polls.items() for poll in rows.values()
                if str(poll.get('channel_id')) == actor.channel_id and manager._planning_allowed(poll)]

    def _owner(self, domain):
        attribute = {'reminder': 'reminders', 'poll': 'poll', 'notification': 'user_memory'}.get(domain)
        manager = getattr(self.monitor, attribute, None) if attribute else None
        if manager is None:
            raise ValueError('task_domain_unavailable')
        return manager

    def items(self, actor) -> dict[str, Any]:
        scope = self._scope(actor)
        reminders = self._reminders(actor)
        manager = getattr(self.monitor, 'reminders', None)
        memory = getattr(self.monitor, 'user_memory', None)
        rows = []
        if manager is not None:
            for _, item in reminders:
                deadline = validate_deadline(item.get('due_date'), manager.clock)
                date, _, local_time = (deadline or '').partition(' ')
                due = EventTime.from_item({'kind': 'task', 'date': date, 'time': local_time or '09:00', 'timezone': 'Europe/Oslo'}).aware_start() if date else None
                rows.append(dict({key: item.get(key) for key in ('id', 'text', 'due_date', 'completed', 'recurrence')},
                    overdue=bool(due and due < manager.clock.now('UTC')),
                    plan={'next_at': None, 'message': 'Fullført: ingen flere varsler.'} if item.get('completed') else reminder_plan(item, memory, manager.clock, scope)))
        rows.sort(key=lambda r: (r['completed'], r['plan'].get('next_at') or '9999', r['text']))
        polls = [{'id': poll['id'], 'question': poll['question'], 'status': poll['status'],
            'owned': str(poll.get('created_by_id')) == actor.user_id,
            'message_url': f'https://discord.com/channels/{bucket}/{actor.channel_id}/{poll["message_id"]}' if str(poll.get('message_id') or '').isdecimal() and str(bucket).isdecimal() else None,
            'options': [{'text': option['text'], 'votes': len(option['votes'])} for option in poll['options']]}
            for bucket, poll in self._polls(actor) if poll['status'] == 'active']
        profile = memory.notification_profile(actor.user_id, scope) if memory else None
        return {'reminders': rows, 'polls': polls, 'notification': profile.document() if profile else None,
            'notification_available': actor.channel_id.isdecimal() or bool(profile and profile.destination_id),
            'revisions': {domain: self._owner(domain)._storage.revision for domain in ('reminder', 'poll', 'notification')
                          if getattr(self.monitor, {'reminder': 'reminders', 'poll': 'poll', 'notification': 'user_memory'}[domain], None)}}

    def _validate(self, actor, payload):
        domain, operation = payload.get('domain'), payload.get('operation')
        self._scope(actor, 'write')
        manager = self._owner(domain)
        if type(payload.get('revision')) is not int or payload['revision'] != manager._storage.revision:
            raise ValueError('revision_changed')
        if set(payload) - {'domain', 'operation', 'revision', 'item_id', 'changes'}:
            raise ValueError('invalid_payload')
        changes = payload.get('changes', {})
        if not isinstance(changes, dict):
            raise ValueError('invalid_changes')
        if operation in ('complete', 'close', 'delete', 'snooze') and changes or operation == 'edit' and not changes:
            raise ValueError('invalid_changes')
        if domain == 'notification':
            if operation != 'edit' or set(changes) - {'enabled', 'lead_minutes', 'quiet_start', 'quiet_end', 'overdue_minutes', 'timezone'}:
                raise ValueError('invalid_notification_changes')
            prior = manager.notification_profile(actor.user_id, self._scope(actor))
            document = (prior or NotificationProfile(False, self._scope(actor), actor.channel_id if actor.channel_id.isdecimal() else None)).document()
            document.update(changes)
            if changes.get('enabled') is True:
                document['destination_id'] = actor.channel_id if actor.channel_id.isdecimal() else prior.destination_id if prior else None
                if document['destination_id'] is None:
                    raise ValueError('notification_destination_required')
            return None, prior.document() if prior else None, NotificationProfile.from_document(document).document()
        if domain == 'reminder':
            if operation not in ('create', 'edit', 'complete', 'delete', 'snooze') or set(changes) - {'text', 'due_date', 'recurrence'}:
                raise ValueError('invalid_changes')
            if operation == 'create' or 'text' in changes:
                if not isinstance(changes.get('text'), str) or not 1 <= len(changes['text'].strip()) <= 200:
                    raise ValueError('invalid_title')
            if 'due_date' in changes:
                changes = dict(changes, due_date=validate_deadline(changes['due_date'], manager.clock))
            if 'recurrence' in changes and (not isinstance(changes['recurrence'], str) or changes['recurrence'] not in SUPPORTED_FREQUENCIES | {''}):
                raise ValueError('invalid_recurrence_frequency')
            if operation == 'create' and changes.get('recurrence') and not changes.get('due_date'):
                raise ValueError('recurrence_requires_deadline')
        elif domain == 'poll':
            if operation not in ('create', 'edit', 'close', 'delete', 'vote') or set(changes) - ({'option_index'} if operation == 'vote' else {'question', 'options'}):
                raise ValueError('invalid_changes')
            if operation in ('create', 'edit') and (not isinstance(changes.get('question'), str) or not 1 <= len(changes['question'].strip()) <= 200):
                raise ValueError('invalid_title')
            if operation == 'create' and (not isinstance(changes.get('options'), list) or not 2 <= len(changes['options']) <= 10
                or any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 150 for v in changes['options'])):
                raise ValueError('invalid_options')
            if operation == 'edit' and 'options' in changes:
                raise ValueError('structural_edit_requires_discord_preview')
        if operation == 'create':
            record = self.monitor.calendar.access_policy.scopes[self._scope(actor)]
            bucket = actor.guild_id or actor.channel_id if record.kind == 'legacy_shared' else record.scope_id
            return bucket, None, changes
        rows = self._reminders(actor) if domain == 'reminder' else self._polls(actor)
        matches = [(bucket, item) for bucket, item in rows if item['id'] == payload.get('item_id')]
        if len(matches) != 1:
            raise PermissionError('task_not_available')
        bucket, item = matches[0]
        owner = item.get('user_id') if domain == 'reminder' else item.get('created_by_id')
        if (operation != 'vote' and str(owner) != actor.user_id) or item.get('completed') or domain == 'poll' and item['status'] != 'active':
            raise PermissionError('task_owner_required')
        if operation == 'vote':
            option = changes.get('option_index')
            if not isinstance(option, int) or isinstance(option, bool) or not 1 <= option <= len(item['options']):
                raise ValueError('invalid_option')
        if item.get('_planning'):
            raise ValueError('use_planning_workflow')
        if domain == 'reminder' and operation == 'edit' and changes.get('recurrence', item.get('recurrence')) and not changes.get('due_date', item.get('due_date')):
            raise ValueError('recurrence_requires_deadline')
        return bucket, item, changes

    def preview(self, actor, payload) -> dict[str, Any]:
        with request_scope(actor):
            bucket, item, changes = self._validate(actor, payload)
        now = time.monotonic()
        self.previews = {k: v for k, v in self.previews.items() if v['expires'] > now}
        token = secrets.token_urlsafe(18)
        self.previews[token] = {'actor': actor_key(actor), 'payload': copy.deepcopy(payload), 'expires': now + 300}
        while len(self.previews) > 32:
            self.previews.pop(next(iter(self.previews)))
        fields = ('enabled', 'lead_minutes', 'quiet_start', 'quiet_end', 'overdue_minutes', 'timezone') if payload['domain'] == 'notification' else ('text', 'question', 'due_date', 'recurrence', 'completed', 'status')
        public = {k: item.get(k) for k in fields} if item else None
        return {'token': token, 'before': public, 'changes': changes, 'operation': payload['operation'], 'expires_in_seconds': 300}

    async def apply(self, actor, token) -> dict[str, Any]:
        entry = self.previews.get(token)
        if not entry or time.monotonic() >= entry['expires']:
            raise ValueError('preview_expired')
        if actor_key(actor) != entry['actor']:
            raise PermissionError('preview_actor_mismatch')
        payload = entry['payload']
        manager = self._owner(payload['domain'])
        with request_scope(actor):
            if payload['domain'] == 'reminder' and payload['operation'] == 'snooze':
                _, item, _ = self._validate(actor, payload)
                result = await self.reminder_action(actor, self.reminder_action_token(actor, item['id']), 'snooze')
                self.previews.pop(token)
                return result
            if payload['domain'] == 'notification':
                async with manager._storage.async_transaction(write=True):
                    _, _, document = self._validate(actor, payload)
                    await manager.set_notification_profile(actor.user_id, NotificationProfile.from_document(document))
            else:
                with manager._storage.transaction(write=True):
                    bucket, item, changes = self._validate(actor, payload)
                    operation = payload['operation']
                    if payload['domain'] == 'reminder':
                        if operation == 'create':
                            manager.add_reminder(bucket, actor.user_id, 'Console', changes['text'].strip(), changes.get('due_date'), recurrence=changes.get('recurrence') or None, channel_id=actor.channel_id)
                        else:
                            active = manager.get_active_reminders(bucket)
                            index = next(n for n, row in enumerate(active, 1) if row['id'] == item['id'])
                            if operation == 'complete':
                                success, _, _ = manager.complete_reminder(bucket, reminder_id=item['id'])
                                if not success:
                                    raise ValueError('selection_changed')
                            elif operation == 'edit':
                                manager.edit_reminder(bucket, index, title=changes.get('text'), date=(changes['due_date'] or '') if 'due_date' in changes else None, recurrence=changes.get('recurrence'))
                            else:
                                manager.delete_reminder_by_id(bucket, index)
                    else:
                        if operation == 'create':
                            manager.create_poll(bucket, changes['question'], changes['options'], 'Console', actor.user_id)
                            new = next(reversed(manager.polls[bucket].values()))
                            manager.set_message_id(bucket, new['id'], None, actor.channel_id)
                        elif operation == 'vote':
                            ok, result = manager.vote(bucket, item['id'], changes['option_index'], actor.user_id, 'Console')
                            if not ok:
                                raise ValueError(result)
                        else:
                            function = {'edit': manager.edit_poll, 'close': manager.close_poll, 'delete': manager.delete_poll}[operation]
                            ok, result = function(bucket, item['id'], actor.user_id, **({'question': changes['question']} if operation == 'edit' else {}))
                            if not ok:
                                raise ValueError(result)
        self.previews.pop(token)
        return {'ok': True, 'undo': undo_hint(manager, actor), 'message': 'Lagret lokalt. Sendte Discord-meldinger beholdes.'}

    def undo(self, actor, token):
        self._scope(actor, 'write')
        for domain in ('reminder', 'poll'):
            manager = getattr(self.monitor, 'reminders' if domain == 'reminder' else 'poll', None)
            if manager is None:
                continue
            if token in getattr(manager, '_local_undo', {}):
                return undo_change(manager, actor, token)
        raise ValueError('undo_expired')

    def reminder_action_token(self, actor, item_id):
        rows = [item for _, item in self._reminders(actor) if item['id'] == item_id and not item['completed']]
        if len(rows) != 1:
            raise PermissionError('task_not_available')
        now = time.monotonic()
        self.actions = {k: v for k, v in self.actions.items() if v['expires'] > now}
        token = secrets.token_urlsafe(9)
        self.actions[token] = {'actor': actor_key(actor)[:2], 'item': rows[0], 'expires': now + 86400}
        while len(self.actions) > 512:
            self.actions.pop(next(iter(self.actions)))
        return token

    def reminder_actions(self, actor, item_id):
        token = self.reminder_action_token(actor, item_id)
        return (f'Fullfør: `@inebotten ferdig påminnelse valg {token}`\n'
                f'Slumre: `@inebotten slumre valg {token}` (10 minutter)\n'
                f'Rediger: `@inebotten endre påminnelse valg {token} tekst: ny tekst`\n'
                'Valget gjelder denne oppføringen i opptil 24 timer og utløper ved endring eller omstart.')

    async def reminder_action(self, actor, token, operation, changes=None) -> dict[str, Any]:
        entry = self.actions.get(token)
        if not entry or entry['expires'] <= time.monotonic():
            raise ValueError('action_expired')
        if entry['actor'] != actor_key(actor)[:2]:
            raise PermissionError('action_actor_mismatch')
        current = next((item for _, item in self._reminders(actor) if item['id'] == entry['item']['id']), None)
        if current is None or current != entry['item']:
            raise ValueError('selection_changed')
        if operation == 'snooze':
            from cal_system.notification_preferences import occurrence_identity
            self._scope(actor, 'write')
            projected = project_current_occurrence(current)
            if projected is None:
                raise ValueError('selection_changed')
            if self.monitor.user_memory.notification_profile(actor.user_id, self._scope(actor)) is None:
                destination = actor.channel_id if actor.channel_id.isdecimal() else str(current.get('channel_id') or '')
                if not destination.isdecimal():
                    raise ValueError('notification_destination_required')
                await self.monitor.user_memory.set_notification_profile(actor.user_id, NotificationProfile(True, self._scope(actor), destination))
            current = next((item for _, item in self._reminders(actor) if item['id'] == entry['item']['id']), None)
            if current is None or current != entry['item']:
                raise ValueError('selection_changed')
            await self.monitor.user_memory.set_notification_snooze(actor.user_id, self._scope(actor), current['id'],
                occurrence_identity(projected), self.monitor.reminders.clock.now('UTC') + timedelta(minutes=10))
            return {'ok': True, 'message': 'Slumret 10 minutter; stille timer gjelder fortsatt.'}
        preview = self.preview(actor, {'domain': 'reminder', 'operation': operation,
            'item_id': current['id'], 'revision': self.monitor.reminders._storage.revision, 'changes': changes or {}})
        return await self.apply(actor, preview['token'])
