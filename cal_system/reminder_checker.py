#!/usr/bin/env python3
"""
Calendar Reminder Checker for Inebotten

Background asyncio task that:
1. Checks every minute for events/reminders coming up in 30 minutes
   and pings the event creator in the original channel
2. Sends a "now" reminder when events are happening
3. Sends a "passed" notification when events just happened
4. Sends a morning digest at 09:00 Europe/Oslo with today's events

Tracks sent reminders in a JSON file to avoid duplicate pings.
"""

import copy
import time
import asyncio
from datetime import datetime, timedelta, timezone
from cal_system.event_schema import EventTime, Clock
from pathlib import Path

from zoneinfo import ZoneInfo
from utils.json_storage import hermes_discord_data_path, write_json_atomic
from utils.storage_contract import DocumentOwner, StorageMutationError, store_worker, writable_store
from core.outbound_sender import OutboundSender, DeliveryResult


class ReminderChecker:
    """
    Proactive calendar reminder checker that pings users in Discord
    when events are approaching, happening, or have just happened.
    Also sends a morning digest.
    """

    def __init__(
        self,
        calendar_manager=None,
        reminder_manager=None,
        event_manager=None,
        get_channel_func=None,
        send_channel_message_func=None,
        send_ping_message_func=None,
        storage_path=None,
        outbound_sender=None,
        clock=None,
        health_callback=None,
        user_memory=None,
        daily_digest=None,
    ):
        self.clock = clock or Clock(wall=lambda: datetime.now(timezone.utc))
        self.calendar = calendar_manager
        self.reminders = reminder_manager
        self.events = event_manager
        self.get_channel = get_channel_func
        self.send_channel_message = send_channel_message_func
        self.send_ping_message = send_ping_message_func
        self.outbound = outbound_sender or OutboundSender(get_channel_func, send_channel_message=send_channel_message_func)
        self.health_callback = health_callback
        self.user_memory = user_memory
        self.daily_digest = daily_digest
        self.running = False
        self._morning_digest_sent = False
        self._last_gcal_sync = None

        self.stats = {
            "30min_sent": 0,
            "now_sent": 0,
            "passed_sent": 0,
            "digest_sent": 0,
            "errors": 0,
        }

        if storage_path is None:
            storage_path = hermes_discord_data_path("reminder_log.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage = DocumentOwner(self.storage_path, lambda d: all(
            isinstance(d.get(key, {}), dict) for key in ('reminders_sent', 'digest_log', 'deliveries')))
        self.sent_log = self._storage.rollback() or {"reminders_sent": {}, "digest_log": {}, "deliveries": {}}

    @property
    def sent_log(self):
        return self._storage.data

    @sent_log.setter
    def sent_log(self, value):
        self._storage.data = value

    def close_storage(self):
        self._storage.close()

    async def setup(self):
        """Async initialization"""
        self.sent_log = await self._load_sent_log()

    async def _load_sent_log(self):
        data = await store_worker(self._storage.load)
        return data or {'reminders_sent': {}, 'digest_log': {}, 'deliveries': {}}

    async def _save_sent_log(self):
        candidate = copy.deepcopy(self.sent_log)
        cutoff = int(time.time()) - 172800
        candidate['reminders_sent'] = {key: value for key, value in candidate.get('reminders_sent', {}).items()
                                      if isinstance(value, (int, float)) and value > cutoff}
        cutoff_date = (self.clock.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        candidate['digest_log'] = {key: value for key, value in candidate.get('digest_log', {}).items()
                                  if isinstance(value, str) and value >= cutoff_date}
        # Unresolved acceptance is never discarded into automatic replay.
        candidate['deliveries'] = {key: value for key, value in candidate.get('deliveries', {}).items()
                                   if value.get('status') in ('pending', 'unknown') or value.get('updated_at', 0) > cutoff}
        result = await store_worker(self._storage.commit, candidate, writer=write_json_atomic)
        if not result.ok:
            raise StorageMutationError(result.error_code)
        self.sent_log = candidate

    @writable_store
    async def _deliver(self, channel_id, message, delivery_key, *, can_dispatch=None, deadline=None):
        if can_dispatch is not None and not can_dispatch():
            return DeliveryResult('dropped', reason_code='authorization_changed')
        receipt = self.sent_log.get('deliveries', {}).get(delivery_key)
        if receipt and receipt.get('status') in ('pending', 'unknown'):
            return DeliveryResult('unknown', reason_code='persisted_unresolved_acceptance')
        if receipt and receipt.get('status') == 'delivered' and (delivery_key.startswith(('profile:', 'snooze:')) or time.time() - receipt.get('updated_at', 0) < 3600):
            return DeliveryResult('delivered', message_id=receipt.get('message_id'), reason_code='persisted_receipt')
        if len(self.sent_log.get('deliveries', {})) >= 4096:
            return DeliveryResult('dropped', reason_code='receipt_capacity')
        self.sent_log.setdefault('deliveries', {})[delivery_key] = {
            'status': 'pending', 'updated_at': int(time.time()), 'message_id': None,
            'reason_code': 'send_not_resolved'}
        await self._save_sent_log()
        result = DeliveryResult('unknown', reason_code='interrupted')
        try:
            result = await self.outbound.send(str(channel_id) if channel_id else '', message,
                                             delivery_key=f"{delivery_key}:{self.sent_log['deliveries'][delivery_key]['updated_at']}", deadline=deadline or time.monotonic()+10,
                                             **({'_can_dispatch': can_dispatch} if can_dispatch is not None else {}))
            return result
        except asyncio.CancelledError as error:
            result = getattr(error, 'delivery_result', result)
            raise
        finally:
            self.sent_log['deliveries'][delivery_key] = {
                'status': result.status, 'updated_at': int(time.time()),
                'message_id': result.message_id, 'reason_code': result.reason_code}
            await self._save_sent_log()

    def _has_been_sent(self, item_id, remind_type):
        """Check if a reminder was already sent for this item+type"""
        key = f"{item_id}:{remind_type}"
        sent_at = self.sent_log.setdefault("reminders_sent", {}).get(key)
        receipt = self.sent_log.get('deliveries', {}).get(key, {})
        if receipt.get('status') in ('pending', 'unknown'):
            return True
        if receipt.get('status') == 'delivered' and time.time() - receipt.get('updated_at', 0) < 3600:
            return True
        if sent_at is None:
            return False
        # Only suppress within a 60-minute window (allow re-alert for next occurrence)
        if time.time() - sent_at < 3600:
            return True
        return False

    @writable_store
    async def _mark_sent(self, item_id, remind_type):
        """Mark a reminder as sent"""
        key = f"{item_id}:{remind_type}"
        self.sent_log.setdefault("reminders_sent", {})[key] = int(time.time())
        await self._save_sent_log()

    def _digest_already_sent_today(self, guild_id, channel_id):
        key = f"{guild_id}:{channel_id}"
        today_key = self.clock.now().strftime("%Y-%m-%d")
        digest_log = self.sent_log.get("digest_log", {})
        return digest_log.get(key) == today_key

    @writable_store
    async def _mark_digest_sent_today(self, guild_id, channel_id):
        key = f"{guild_id}:{channel_id}"
        today_key = self.clock.now().strftime("%Y-%m-%d")
        self.sent_log.setdefault("digest_log", {})[key] = today_key
        await self._save_sent_log()

    # ---- 30-min warning ----

    async def check_upcoming_30min(self):
        """Check calendar items & reminders due within 30 minutes, ping creator in channel"""
        now = self.clock.now()
        thirty_min = now + timedelta(minutes=30)

        # Check calendar items from CalendarManager
        if self.calendar:
            for guild_id, items_list in self._calendar_buckets().items():
                for item in items_list:
                    if item.get("completed"):
                        continue
                    item = self._current_occurrence_item(item)
                    if item is None:
                        continue
                    try:
                        item_date = self._parse_item_datetime(item)
                    except (ValueError, TypeError):
                        continue
                    if item_date is None:
                        continue
                    # Already happened or exactly in the 30-min window
                    if now <= item_date <= thirty_min:
                        if self._has_been_sent(self._delivery_identity(item), "30min"):
                            continue
                        await self._send_item_reminder(item, "30min", "30 minutter")

        # Check reminders from ReminderManager
        if self.reminders:
            for guild_id, reminders_list in self.reminders.reminders.items():
                for reminder in reminders_list:
                    if reminder.get("completed"):
                        continue
                    reminder = self._current_occurrence_item(reminder)
                    if reminder is None:
                        continue
                    due = reminder.get("due_date")
                    if not due:
                        continue
                    try:
                        reminder_dt = self._parse_due_date(due)
                    except Exception:
                        continue
                    if reminder_dt is None:
                        continue
                    if now <= reminder_dt <= thirty_min:
                        if self._has_been_sent(self._delivery_identity(reminder), "30min"):
                            continue
                        await self._send_reminder_remind(reminder, "30min", "30 minutter")

    # ---- Event happening NOW ----

    async def check_event_now(self):
        """Check for events happening NOW and send notifications"""
        now = self.clock.now()
        one_minute_ago = now - timedelta(minutes=1)
        one_minute_ahead = now + timedelta(minutes=1)

        # Check calendar items
        if self.calendar:
            for guild_id, items_list in self._calendar_buckets().items():
                for item in items_list:
                    if item.get("completed"):
                        continue
                    item = self._current_occurrence_item(item)
                    if item is None:
                        continue
                    try:
                        item_date = self._parse_item_datetime(item)
                    except (ValueError, TypeError):
                        continue
                    if item_date is None:
                        continue
                    # Check if event is happening NOW (within 1 minute window)
                    if one_minute_ago <= item_date <= one_minute_ahead:
                        if self._has_been_sent(self._delivery_identity(item), "now"):
                            continue
                        await self._send_item_reminder(item, "now", "nå")

        # Check reminders
        if self.reminders:
            for guild_id, reminders_list in self.reminders.reminders.items():
                for reminder in reminders_list:
                    if reminder.get("completed"):
                        continue
                    reminder = self._current_occurrence_item(reminder)
                    if reminder is None:
                        continue
                    due = reminder.get("due_date")
                    if not due:
                        continue
                    try:
                        reminder_dt = self._parse_due_date(due)
                    except Exception:
                        continue
                    if reminder_dt is None:
                        continue
                    if one_minute_ago <= reminder_dt <= one_minute_ahead:
                        if self._has_been_sent(self._delivery_identity(reminder), "now"):
                            continue
                        await self._send_reminder_remind(reminder, "now", "nå")

    # ---- Event just passed ----

    async def check_event_passed(self):
        """Check for events that just happened (within last 5 minutes)"""
        now = self.clock.now()
        five_minutes_ago = now - timedelta(minutes=5)

        # Check calendar items
        if self.calendar:
            for guild_id, items_list in self._calendar_buckets().items():
                for item in items_list:
                    if item.get("completed"):
                        continue
                    item = self._current_occurrence_item(item)
                    if item is None:
                        continue
                    try:
                        item_date = self._event_end(item) or self._parse_item_datetime(item)
                    except (ValueError, TypeError):
                        continue
                    if item_date is None:
                        continue
                    # Check if event just happened (within last 5 minutes)
                    if five_minutes_ago <= item_date <= now:
                        if self._has_been_sent(self._delivery_identity(item), "passed"):
                            continue
                        await self._send_item_reminder(item, "passed", "akkurat nå")

        # Check reminders
        if self.reminders:
            for guild_id, reminders_list in self.reminders.reminders.items():
                for reminder in reminders_list:
                    if reminder.get("completed"):
                        continue
                    reminder = self._current_occurrence_item(reminder)
                    if reminder is None:
                        continue
                    due = reminder.get("due_date")
                    if not due:
                        continue
                    try:
                        reminder_dt = self._parse_due_date(due)
                    except Exception:
                        continue
                    if reminder_dt is None:
                        continue
                    if five_minutes_ago <= reminder_dt <= now:
                        if self._has_been_sent(self._delivery_identity(reminder), "passed"):
                            continue
                        await self._send_reminder_remind(reminder, "passed", "akkurat nå")

    # ---- Morning digest at 09:00 ----

    async def check_morning_digest(self):
        """If it's past 09:00 and we haven't sent a morning digest yet per guild, send one"""
        oslo_tz = ZoneInfo("Europe/Oslo")
        now = self.clock.now()

        # Trigger between 09:00 and 10:00 (wider window for reliability)
        if not (9 <= now.hour < 10):
            return

        # Check all guilds that have calendar data
        if self.calendar:
            for guild_id in self._calendar_buckets():
                # Try to find a channel to send the digest to:
                # Use the channel from the earliest upcoming item, or guild default
                channel_id = self._find_digest_channel(guild_id)
                if channel_id is None:
                    continue

                if self._digest_already_sent_today(guild_id, channel_id):
                    continue

                items = self.calendar.get_upcoming(guild_id, days=1)
                items = [item for item in items if self._legacy_allowed(item)]
                if not items:
                    continue

                digest = self._format_morning_digest(items, now)
                key = f'digest:{guild_id}:{channel_id}:{now.strftime("%Y-%m-%d")}'
                result = await self._deliver(channel_id, digest, key)
                if result.status == 'delivered':
                    await self._mark_digest_sent_today(guild_id, channel_id)
                    self.stats['digest_sent'] += 1

    # ---- Helpers ----

    def _profile_scope(self, item):
        # Unscoped legacy records stay shared even when the current default is private.
        return item.get('scope_id') or 'shared'

    def _legacy_allowed(self, item):
        return self.user_memory is None or self.user_memory.notification_profile(item.get('user_id', ''), self._profile_scope(item)) is None

    def _event_end(self, item):
        try:
            value = EventTime.from_item(item)
            if value.kind == 'event' and not value.all_day and value.duration_minutes is not None:
                return value.aware_start().astimezone(timezone.utc) + timedelta(minutes=value.duration_minutes)
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _delivery_identity(item):
        from cal_system.notification_preferences import occurrence_identity
        if not item.get('occurrence_id') and not item.get('series') and not item.get('recurrence'):
            return str(item['id'])
        return occurrence_identity(item)

    def _current_occurrence_item(self, item):
        """Project the exact stored next occurrence into existing delivery paths."""
        if item.get('_recurrence_readonly'):
            return None
        if not item.get('series') and not item.get('recurrence'):
            return item
        try:
            from cal_system.recurrence import Occurrence, Series, occurrence_at, series_from_item
            series = Series.from_document(item['series']) if item.get('series') else series_from_item(item)
            occurrence = occurrence_at(series, item.get('series_next_index', 0))
            if occurrence is None:
                return None
            saved = item.get('occurrences', {}).get(occurrence.occurrence_id)
            if saved:
                occurrence = Occurrence.from_document(saved)
            if occurrence.state != 'planned':
                return None
            result = copy.deepcopy(item)
            result['occurrence_id'] = occurrence.occurrence_id
            result['series_id'] = occurrence.series_id
            result['original_start'] = occurrence.original_start.isoformat()
            if occurrence.override:
                for key in ('date', 'time', 'timezone', 'duration_minutes', 'fold', 'all_day', 'kind', 'title', 'description'):
                    if key in occurrence.override:
                        result[key] = occurrence.override[key]
            return result
        except (KeyError, TypeError, ValueError):
            return item

    async def check_notification_profiles(self):
        """Only explicitly configured actors/destinations; no discovery or fan-out."""
        if self.user_memory is None:
            return
        from core.request_context import RequestContext, request_scope
        from cal_system.notification_preferences import after_quiet_hours, local_instant, occurrence_identity
        now = self.clock.now('UTC')
        deadline = time.monotonic() + 10
        for user_id, profile in self.user_memory.notification_profiles():
            if time.monotonic() >= deadline:
                return
            if not profile.enabled or not profile.destination_id:
                continue
            policy = getattr(self.calendar, 'access_policy', None)
            scope = policy.scopes.get(profile.scope_id) if policy else None
            actor = RequestContext('notification', user_id, profile.destination_id, None, 'no',
                'dm' if scope and scope.kind == 'private_user' else 'guild')
            if policy and not policy.authorize(actor, profile.scope_id, 'read').allowed:
                continue
            if policy:
                import discord
                channel = self.get_channel(int(profile.destination_id)) if self.get_channel else None
                if asyncio.iscoroutine(channel):
                    async with asyncio.timeout(2):
                        channel = await channel
                if channel is None:
                    continue
                if scope.kind == 'private_user' and (not isinstance(channel, discord.DMChannel)
                    or str(getattr(getattr(channel, 'recipient', None), 'id', '')) != user_id):
                    continue
                if isinstance(channel, discord.DMChannel):
                    if str(getattr(getattr(channel, 'recipient', None), 'id', '')) != user_id:
                        continue
                    actor = RequestContext('notification', user_id, profile.destination_id, None, 'no', 'dm')
            with request_scope(actor):
                # Revocation/destination changes during provider or quota awaits
                # invalidate this captured profile before the actual transport call.
                can_dispatch = lambda user=user_id, selected=profile, audience=actor: (
                    self.user_memory.notification_profile(user, selected.scope_id) == selected
                    and (not policy or self.calendar.access_policy.authorize(audience, selected.scope_id, 'read').allowed))
                buckets = self._calendar_buckets() if self.calendar else {}
                items = []
                for bucket, values in buckets.items():
                    for item in values:
                        if (self._profile_scope(item) != profile.scope_id or str(item.get('user_id')) != user_id
                            or item.get('completed')):
                            continue
                        current = self._current_occurrence_item(item)
                        if current is not None:
                            items.append(current)
                if self.reminders:
                    for values in self.reminders.reminders.values():
                        for item in values:
                            if (self._profile_scope(item) != profile.scope_id or str(item.get('user_id')) != user_id
                                or item.get('completed') or item.get('_mutation_deleted') or item.get('delete_pending')):
                                continue
                            current = self._current_occurrence_item(item)
                            if current is not None:
                                items.append(dict(current, _reminder=True))
                for item in items:
                    start = self._parse_due_date(item['due_date']) if item.get('_reminder') and item.get('due_date') else self._parse_item_datetime(item)
                    if start is None:
                        continue
                    start = start.astimezone(timezone.utc)
                    occurrence = occurrence_identity(item)
                    for lead in profile.lead_minutes:
                        if time.monotonic() >= deadline:
                            return
                        due = after_quiet_hours(profile, start - timedelta(minutes=lead))
                        if due <= start and timedelta() <= now - due < timedelta(minutes=5):
                            title = item.get('title', item.get('text', 'Påminnelse'))
                            await self._deliver(profile.destination_id, f'🔔 {title} · valgt forvarsel: {lead} minutter.',
                                f'profile:{profile.scope_id}:{user_id}:{occurrence}:lead:{lead}', can_dispatch=can_dispatch, deadline=deadline)
                indexed = {i['id']: i for i in items}
                for snooze in self.user_memory.notification_snoozes(user_id, profile.scope_id):
                    item = indexed.get(snooze['item_id'])
                    if item is None or occurrence_identity(item) != snooze['occurrence_id']:
                        continue
                    due = after_quiet_hours(profile, datetime.fromisoformat(snooze['due_at']))
                    if timedelta() <= now - due < timedelta(minutes=5):
                        result = await self._deliver(profile.destination_id, f"🔔 Slumret: {item.get('title', item.get('text', 'Påminnelse'))}",
                            f"snooze:{user_id}:{snooze['key']}:{snooze['due_at']}", can_dispatch=can_dispatch, deadline=deadline)
                        if result.status == 'delivered':
                            await self.user_memory.acknowledge_notification_snooze(user_id, snooze['key'], snooze['due_at'])
                if profile.morning_time is not None and self.daily_digest and profile.card_ids:
                    local = now.astimezone(ZoneInfo(profile.timezone))
                    due = after_quiet_hours(profile, local_instant(local.date(), profile.morning_time, profile.timezone))
                    if timedelta() <= now - due < timedelta(minutes=5):
                        key = f'profile:{profile.scope_id}:{user_id}:digest:{local.date()}'
                        receipt = self.sent_log.get('deliveries', {}).get(key, {})
                        if receipt.get('status') in ('delivered', 'pending', 'unknown'):
                            continue
                        try:
                            async with asyncio.timeout_at(deadline):
                                text = await self.daily_digest.generate_digest(profile.scope_id, user_id=user_id, card_ids=profile.card_ids)
                        except TimeoutError:
                            return
                        result = await self._deliver(profile.destination_id, text, key, can_dispatch=can_dispatch, deadline=deadline)
                        if result.status == 'delivered':
                            self.stats['digest_sent'] += 1

    def _calendar_buckets(self):
        from core.request_context import current_request
        policy = getattr(self.calendar, 'access_policy', None)
        buckets = self.calendar.items
        buckets = {key: [item for item in values if not item.get('_mutation_deleted')
                        and not item.get('delete_pending')] for key, values in buckets.items()}
        if policy is None:
            return buckets
        return {key: values for key, values in buckets.items()
                if policy.authorize(current_request(), key if key in policy.scopes or key.startswith(('private:', 'group:')) else 'shared', 'read').allowed}

    def _parse_item_datetime(self, item):
        """Parse date+time from a calendar item into a Europe/Oslo datetime"""
        try:
            value = EventTime.from_item(item)
            # Date-only entries belong in the daily agenda, not a guessed timed alert.
            if value.all_day:
                return None
            return value.aware_start()
        except (ValueError, TypeError):
            return None

    def _parse_due_date(self, due_str):
        """Parse DD.MM.YYYY or DD.MM into a datetime"""
        oslo_tz = ZoneInfo("Europe/Oslo")
        try:
            dt = datetime.strptime(due_str, "%d.%m.%Y").replace(
                hour=9, minute=0, tzinfo=oslo_tz
            )
            return dt
        except ValueError:
            pass
        try:
            dt = datetime.strptime(due_str, "%d.%m").replace(
                year=self.clock.now().year, hour=9, minute=0, tzinfo=oslo_tz
            )
            return dt
        except ValueError:
            return None

    def _find_digest_channel(self, guild_id):
        """Find a sensible channel_id for the morning digest."""
        items = self.calendar.get_upcoming(guild_id, days=1)
        for item in items:
            channel_id = item.get("channel_id")
            if channel_id:
                try:
                    return int(channel_id)
                except (TypeError, ValueError):
                    continue
        return None

    def _format_morning_digest(self, items, now):
        """Format morning digest message in Norwegian"""
        day_names = [
            "mandag", "tirsdag", "onsdag", "torsdag",
            "fredag", "lørdag", "søndag",
        ]
        day_name = day_names[now.weekday()]
        date_str = now.strftime("%d.%m.%Y")

        lines = [
            f"☀️ **God morgen!** {day_name} {date_str}",
            "",
        ]
        for item in items[:8]:
            time_str = f" kl. {item['time']}" if item.get("time") else ""
            creator_str = f" ({item.get('username', 'Ukjent')})"
            lines.append(f"  {item['title']}{time_str}{creator_str}")

        if len(items) > 8:
            lines.append(f"  ...og {len(items) - 8} til. Bruk @inebotten kalender for hele listen.")

        lines.append("")
        lines.append("Ha ein fin dag! ✨")
        return "\n".join(lines)

    async def _send_item_reminder(self, item, remind_type, label):
        """Send a reminder for a calendar item in its original channel"""
        channel_id = item.get("channel_id")
        if not self._legacy_allowed(item):
            return
        time_str = f" kl. {item['time']}" if item.get("time") else ""

        # Different messages based on reminder type
        if remind_type == "30min":
            message = (
                f"⏰ **Påminnelse: {item['title']}**\n\n"
                f"Det er {label} til!{time_str}\n\n"
                f"Klar? 😊"
            )
        elif remind_type == "now":
            message = (
                f"🔔 **Starter nå: {item['title']}**\n\n"
                f"Det er på tide!{time_str}\n\n"
                f"Lykke til! 🎉"
            )
        elif remind_type == "passed":
            ended = self._event_end(item)
            wording = 'Akkurat ferdig' if ended is not None and ended <= self.clock.now() else 'Starttidspunktet er passert'
            message = (
                f"📅 **{wording}: {item['title']}**{time_str}"
            )
        else:
            message = f"⏰ **{item['title']}** - {label}{time_str}"

        identity = self._delivery_identity(item)
        if self._has_been_sent(identity, remind_type):
            return
        result = await self._send_mentions_item(channel_id, item, message, delivery_key=f"{identity}:{remind_type}")
        if result.status != 'delivered':
            self.stats['errors'] += 1
            return
        await self._mark_sent(identity, remind_type)
        
        # Update statistics
        if remind_type == "30min":
            self.stats["30min_sent"] += 1
        elif remind_type == "now":
            self.stats["now_sent"] += 1
        elif remind_type == "passed":
            self.stats["passed_sent"] += 1

    async def _send_reminder_remind(self, reminder, remind_type, label):
        """Send a reminder for a reminder item"""
        channel_id = reminder.get("channel_id")
        if not self._legacy_allowed(reminder):
            return
        
        # Different messages based on reminder type
        if remind_type == "30min":
            message = (
                f"⏰ **Påminnelse: {reminder['text']}**\n\n"
                f"Det er {label} til!\n\n"
                f"Klar? 😊"
            )
        elif remind_type == "now":
            message = (
                f"🔔 **Nå: {reminder['text']}**\n\n"
                f"Det er på tide!\n\n"
                f"Lykke til! 🎉"
            )
        elif remind_type == "passed":
            message = (
                f"🔔 **Fristen er passert: {reminder['text']}**"
            )
        else:
            message = f"⏰ **{reminder['text']}** - {label}"

        identity = self._delivery_identity(reminder)
        if self._has_been_sent(identity, remind_type):
            return
        result = await self._deliver(channel_id, message, f"{identity}:{remind_type}")
        if result.status != 'delivered':
            self.stats['errors'] += 1
            return
        await self._mark_sent(identity, remind_type)

        # Update statistics
        if remind_type == "30min":
            self.stats["30min_sent"] += 1
        elif remind_type == "now":
            self.stats["now_sent"] += 1
        elif remind_type == "passed":
            self.stats["passed_sent"] += 1

    async def _send_mentions_item(self, channel_id, item, message, delivery_key=None):
        """Send a message mentioning the item creator"""
        # Try to mention the original creator via Discord user ID
        user_id = item.get("user_id")
        if user_id and user_id != "gcal_sync":
            mention = f"<@{user_id}>"
            message = f"{mention}\n\n{message}"
        elif user_id == "gcal_sync":
            # For GCal items, maybe just add a header
            message = f"📅 **Google Calendar Sync**\n\n{message}"

        return await self._deliver(channel_id, message, delivery_key)

    async def _send_to_channel(self, channel_id, message):
        return await self.outbound.send(str(channel_id) if channel_id else '', message,
                                        delivery_key=None, deadline=time.monotonic()+10)

    # ---- Main loop ----

    async def sync_google(self, *, pull=False):
        """Share one provider slot across the initialized owner stores."""
        if not self.calendar or not self.calendar.gcal_enabled:
            return
        deadline = time.monotonic() + 20
        configure = getattr(self.reminders, 'configure_google', None)
        if callable(configure):
            configure(self.calendar.gcal, slot=self.calendar._outbox.slot,
                access_policy=self.calendar.access_policy)
        await self.calendar.process_due(deadline=deadline)
        process = getattr(self.reminders, 'process_due', None)
        if callable(process):
            await process(deadline=deadline)
        if pull:
            await self.calendar.sync_from_gcal(deadline=deadline)

    async def start(self):
        """Start the reminder checker background task"""
        self.running = True
        print("[REMIND] Reminder checker started")
        while self.running:
            successful = False
            try:
                prune = getattr(self.calendar, 'prune_mutation_history', None)
                if callable(prune):
                    await prune()
                await self.check_upcoming_30min()
                await self.check_event_now()
                await self.check_event_passed()
                await self.check_morning_digest()
                await self.check_notification_profiles()

                # Periodic Google Calendar sync (every 15 minutes)
                if self.calendar and self.calendar.gcal_enabled:
                    now_ts = self.clock.monotonic()
                    if self._last_gcal_sync is None or now_ts - self._last_gcal_sync > 900:  # 900 seconds = 15 min
                        try:
                            await self.sync_google(pull=True)
                            self._last_gcal_sync = now_ts
                        except Exception as e:
                            print("[REMIND] Google-synkronisering utsatt; lokale endringer er bevart.")
                    else:
                        await self.sync_google()
                successful = True
            except Exception as e:
                print(f"[REMIND] Error in checker loop: {e}")
                self.stats["errors"] += 1

            if callable(self.health_callback):
                self.health_callback(successful)

            # Check every 60 seconds
            for _ in range(60):
                if not self.running:
                    break
                import asyncio
                await asyncio.sleep(1)

    def stop(self):
        """Stop the reminder checker"""
        self.running = False
        print("[REMIND] Reminder checker stopped")
        print(f"[REMIND] Statistics: {self.stats}")
