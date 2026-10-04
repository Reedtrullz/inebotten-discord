"""Opt-in scheduling uses synthetic stores and aware fake clocks."""
import asyncio
from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.event_schema import Clock
from memory.user_memory import UserMemory


def clock(instant):
    return Clock(wall=lambda: datetime.fromisoformat(instant))


def test_quiet_hours_cross_midnight_and_dst_gap():
    from cal_system.notification_preferences import NotificationProfile, next_delivery
    p = NotificationProfile(True, 'shared', '70', [30], time(22), time(7))
    due = next_delivery(p, datetime.fromisoformat('2027-03-28T08:00:00+02:00'), clock('2027-03-28T04:00:00+00:00'))
    assert due == datetime.fromisoformat('2027-03-28T07:30:00+02:00')
    p = NotificationProfile(True, 'shared', '70', [60], time(22), time(2, 30))
    due = next_delivery(p, datetime.fromisoformat('2027-03-28T03:00:00+02:00'), clock('2027-03-27T21:00:00+00:00'))
    assert due.astimezone(timezone.utc) == datetime.fromisoformat('2027-03-28T01:00:00+00:00')


def test_optout_and_absent_destination_never_schedule():
    from cal_system.notification_preferences import NotificationProfile, next_delivery
    now = clock('2027-01-01T00:00:00+00:00')
    event = datetime.fromisoformat('2027-01-01T09:00:00+01:00')
    assert next_delivery(NotificationProfile(False, 'shared', '70', [30]), event, now) is None
    assert next_delivery(NotificationProfile(True, 'shared', None, [30]), event, now) is None


@pytest.mark.asyncio
async def test_profiles_and_occurrence_snooze_survive_restart(tmp_path):
    from cal_system.notification_preferences import NotificationProfile
    path = tmp_path / 'memory.json'
    memory = UserMemory(path)
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', [10, 0]))
    due = datetime.fromisoformat('2027-01-01T08:10:00+00:00')
    await memory.set_notification_snooze('7', 'shared', 'item', 'occurrence-1', due)
    memory._storage.close()
    resumed = UserMemory(path)
    assert resumed.notification_profile('7', 'shared').lead_minutes == (10, 0)
    assert resumed.notification_snoozes('7', 'shared')[0]['occurrence_id'] == 'occurrence-1'
    assert resumed.notification_snoozes('7', 'shared')[0]['due_at'] == due.isoformat()
    assert resumed.notification_profile('9', 'shared') is None
    resumed._storage.close()


@pytest.mark.asyncio
async def test_profile_revocation_during_digest_provider_blocks_transport(tmp_path):
    from cal_system.notification_preferences import NotificationProfile
    from cal_system.reminder_checker import ReminderChecker
    memory = UserMemory(tmp_path / 'memory.json')
    enabled = NotificationProfile(True, 'shared', '70', [], morning_time=time(9), card_ids=['weather'])
    await memory.set_notification_profile('7', enabled)
    async def generate(*args, **kwargs):
        await memory.set_notification_profile('7', NotificationProfile.from_document(dict(enabled.document(), enabled=False)))
        return 'Synthetic completed provider card'
    sender = SimpleNamespace(send=AsyncMock())
    checker = ReminderChecker(user_memory=memory, outbound_sender=sender, daily_digest=SimpleNamespace(generate_digest=generate),
        storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T08:00:00+00:00'))
    await checker.setup(); await checker.check_notification_profiles()
    sender.send.assert_not_awaited()
    assert checker.stats['digest_sent'] == 0
    checker.close_storage(); memory._storage.close()


@pytest.mark.asyncio
async def test_authorization_rechecked_after_shared_quota_wait():
    import time as system_time
    from core.outbound_sender import OutboundSender
    from core.rate_limiter import RateLimiter
    limiter = RateLimiter(daily_quota=1, safe_interval=0)
    reserved = await limiter.reserve(system_time.monotonic() + 2)
    send = AsyncMock(return_value=SimpleNamespace(id='receipt'))
    sender = OutboundSender(lambda _: SimpleNamespace(send=send), limiter)
    permitted = [True]
    pending = asyncio.create_task(sender.send('70', 'Synthetic', deadline=system_time.monotonic() + 2, _can_dispatch=lambda: permitted[0]))
    await asyncio.sleep(.01)
    permitted[0] = False
    limiter.release(reserved, attempted=False)
    result = await pending
    assert result.status == 'dropped' and result.reason_code == 'authorization_changed'
    send.assert_not_awaited()
    assert limiter.get_stats()['reserved'] == 0 and limiter.get_stats()['sent_today'] == 0


@pytest.mark.asyncio
async def test_actual_snooze_handler_refuses_other_users_and_persists_own_identity(tmp_path):
    from cal_system.calendar_manager import CalendarManager
    from cal_system.notification_preferences import NotificationProfile, occurrence_identity
    from core.request_context import RequestContext, request_scope
    from features.reminder_handler import ReminderHandler
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', []))
    calendar = CalendarManager(storage_path=tmp_path / 'calendar.json', clock=clock('2027-01-01T08:00:00+00:00'))
    own = calendar.add_item('shared', '7', 'Synthetic', 'Own', '01.01.2027', time_str='09:00')
    other = calendar.add_item('shared', '9', 'Synthetic', 'Other', '01.01.2027', time_str='09:00')
    handler = ReminderHandler(SimpleNamespace(calendar=calendar, user_memory=memory,
        reminders=SimpleNamespace(reminders={}), rate_limiter=None, loc=None, client=None))
    handler.send_response = AsyncMock()
    message = SimpleNamespace(author=SimpleNamespace(id=7))
    with request_scope(RequestContext('snooze', '7', '70', None, 'no', 'dm')):
        with pytest.raises(PermissionError):
            await handler.handle_snooze(message, {'item_id': other['id'], 'minutes': 10})
        await handler.handle_snooze(message, {'item_id': own['id'], 'minutes': 10})
    snooze = memory.notification_snoozes('7', 'shared')[0]
    assert snooze['occurrence_id'] == occurrence_identity(own)
    assert snooze['due_at'] == '2027-01-01T08:10:00+00:00'
    assert len(memory.notification_snoozes('7', 'shared')) == 1
    calendar._storage.close(); memory._storage.close()


@pytest.mark.asyncio
async def test_only_selected_digest_cards_are_called_and_failures_degrade():
    from features.daily_digest_manager import DailyDigestManager
    forecast = SimpleNamespace(get_weather=AsyncMock(side_effect=OSError('synthetic')))
    crypto = SimpleNamespace(get_price=AsyncMock())
    calendar = SimpleNamespace(get_upcoming=lambda *a, **k: [{'title': 'Synthetic', 'date': '01.01.2027'}])
    manager = DailyDigestManager(event_manager=calendar, crypto_manager=crypto, forecast_service=forecast,
                                clock=clock('2027-01-01T07:00:00+00:00'))
    text = await manager.generate_digest('shared', card_ids=['weather', 'calendar'])
    assert 'Synthetic' in text and 'utilgjengelig' in text
    assert 'Lokal kalender' in text
    crypto.get_price.assert_not_awaited()
    forecast.get_weather.assert_awaited_once()


@pytest.mark.asyncio
async def test_market_and_aurora_use_existing_valid_formatters():
    from features.daily_digest_manager import DailyDigestManager
    from features.crypto_manager import CryptoManager
    crypto = CryptoManager()
    crypto.get_price = AsyncMock(return_value={'type': 'crypto', 'name': 'Synthetic', 'symbol': 'SYN',
        'price': 12, 'change_24h': 1, 'high_24h': 13, 'low_24h': 11, 'market_cap': 10})
    aurora = SimpleNamespace(get_forecast=AsyncMock(return_value={'synthetic': True}),
                             format_forecast=lambda data: 'NOAA; 2027-01-01; synthetic forecast')
    manager = DailyDigestManager(crypto_manager=crypto, aurora_manager=aurora)
    text = await manager.generate_digest('shared', card_ids=['market', 'aurora'])
    assert 'CoinGecko' in text and 'NOAA' in text and 'utilgjengelig' not in text
    assert 'ikke dokumentert' in text


@pytest.mark.asyncio
async def test_optout_suppresses_legacy_item_delivery_and_new_profiles_do_not_expand_users(tmp_path):
    from cal_system.notification_preferences import NotificationProfile
    from cal_system.reminder_checker import ReminderChecker
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(False, 'shared', '70', [30, 0]))
    sender = SimpleNamespace(send=AsyncMock())
    checker = ReminderChecker(user_memory=memory, outbound_sender=sender, storage_path=tmp_path / 'sent.json')
    await checker.setup()
    await checker._send_item_reminder({'id': 'item', 'user_id': '7', 'scope_id': 'shared', 'channel_id': '70', 'title': 'Synthetic'}, 'now', 'nå')
    sender.send.assert_not_awaited()
    checker.close_storage(); memory._storage.close()


def test_quiet_end_fold_uses_first_still_eligible_boundary():
    from cal_system.notification_preferences import NotificationProfile, after_quiet_hours
    p = NotificationProfile(True, 'shared', '70', [30], time(22), time(2, 30))
    first = after_quiet_hours(p, datetime.fromisoformat('2027-10-31T02:15:00+02:00'))
    second = after_quiet_hours(p, datetime.fromisoformat('2027-10-31T02:15:00+01:00'))
    assert first == datetime.fromisoformat('2027-10-31T00:30:00+00:00')
    assert second == datetime.fromisoformat('2027-10-31T01:30:00+00:00')


@pytest.mark.asyncio
async def test_enabled_profile_sends_only_actor_items_and_selected_lead(tmp_path):
    from cal_system.notification_preferences import NotificationProfile
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', [10]))
    items = [{'id': str(i), 'user_id': str(i), 'title': f'User {i}', 'date': '01.01.2027', 'time': '09:00', 'scope_id': 'shared', 'channel_id': '80'} for i in (7, 9)]
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered', 'receipt')))
    checker = ReminderChecker(calendar_manager=SimpleNamespace(items={'shared': items}), user_memory=memory,
        outbound_sender=sender, storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T07:50:00+00:00'))
    await checker.setup(); await checker.check_notification_profiles(); await checker.check_notification_profiles()
    assert sender.send.await_count == 1
    assert sender.send.call_args.args[0] == '70'
    assert 'User 7' in sender.send.call_args.args[1] and 'User 9' not in sender.send.call_args.args[1]
    checker.close_storage(); memory._storage.close()


@pytest.mark.asyncio
async def test_missing_destination_does_not_call_digest_provider(tmp_path):
    from cal_system.notification_preferences import NotificationProfile
    from cal_system.reminder_checker import ReminderChecker
    from core.access_policy import AccessPolicy
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', [], morning_time=time(9), card_ids=['weather']))
    digest = SimpleNamespace(generate_digest=AsyncMock())
    sender = SimpleNamespace(send=AsyncMock())
    checker = ReminderChecker(calendar_manager=SimpleNamespace(items={}, access_policy=AccessPolicy()), user_memory=memory,
        outbound_sender=sender, get_channel_func=lambda _: None, daily_digest=digest,
        storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T08:00:00+00:00'))
    await checker.setup(); await checker.check_notification_profiles()
    digest.generate_digest.assert_not_awaited(); sender.send.assert_not_awaited()
    checker.close_storage(); memory._storage.close()


@pytest.mark.asyncio
async def test_private_destination_recipient_and_legacy_scope_are_verified(tmp_path, monkeypatch):
    import discord
    from core.access_policy import AccessPolicy, ScopeRecord
    from cal_system.notification_preferences import NotificationProfile
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    class DM:
        def __init__(self, recipient):
            self.recipient = SimpleNamespace(id=recipient)
    monkeypatch.setattr(discord, 'DMChannel', DM)
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(True, 'private:7', '70', [0]))
    policy = AccessPolicy([ScopeRecord('shared', 'legacy_shared'), ScopeRecord('private:7', 'private_user', '7')], default_scope='private:7')
    item = {'id': 'i', 'user_id': '7', 'title': 'Synthetic', 'date': '01.01.2027', 'time': '09:00'}
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered', 'receipt')))
    checker = ReminderChecker(calendar_manager=SimpleNamespace(items={'shared': [item]}, access_policy=policy), user_memory=memory,
        outbound_sender=sender, get_channel_func=lambda _: DM(9),
        storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T08:00:00+00:00'))
    await checker.setup(); await checker.check_notification_profiles()
    sender.send.assert_not_awaited()
    checker.get_channel = lambda _: DM(7)
    await checker.check_notification_profiles()  # An unscoped shared item never becomes private.
    sender.send.assert_not_awaited()
    checker.close_storage(); memory._storage.close()


@pytest.mark.asyncio
async def test_unknown_snooze_acceptance_is_retained_without_retry(tmp_path):
    from cal_system.notification_preferences import NotificationProfile, occurrence_identity
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', []))
    item = {'id': 'i', 'user_id': '7', 'title': 'Synthetic', 'date': '01.01.2027', 'time': '09:00'}
    await memory.set_notification_snooze('7', 'shared', 'i', occurrence_identity(item), datetime.fromisoformat('2027-01-01T08:00:00+00:00'))
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('unknown', reason_code='send_timeout')))
    checker = ReminderChecker(calendar_manager=SimpleNamespace(items={'shared': [item]}), user_memory=memory,
        outbound_sender=sender, storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T08:00:00+00:00'))
    await checker.setup(); await checker.check_notification_profiles(); await checker.check_notification_profiles()
    assert sender.send.await_count == 1 and len(memory.notification_snoozes('7', 'shared')) == 1
    checker.close_storage(); memory._storage.close()


@pytest.mark.asyncio
async def test_notification_setting_and_snooze_commands_bind_real_actor_scope(tmp_path):
    from core.access_policy import AccessPolicy
    from core.request_context import RequestContext, request_scope
    from core.intent_router import IntentRouter
    from core.command_registry import validate_payload
    from tests.test_intent_router import DummyMonitor
    from features.memory_handler import MemoryHandler
    memory = UserMemory(tmp_path / 'memory.json')
    monitor = SimpleNamespace(user_memory=memory, rate_limiter=None, loc=None, client=None,
        calendar=SimpleNamespace(access_policy=AccessPolicy()))
    handler = MemoryHandler(monitor); handler.send_response = AsyncMock()
    message = SimpleNamespace(author=SimpleNamespace(id=7), channel=SimpleNamespace(id=70))
    actor = RequestContext('set', '7', '70', None, 'no', 'dm')
    router = IntentRouter(DummyMonitor())
    for text in ('varsler på', 'varsler forvarsel 10,0 minutter', 'varsler stille 22:00-07:00', 'varsler morgen 09:00', 'varsler kort kalender,vær'):
        result = router.route(text, guild_id='70')
        payload = validate_payload(result.intent, result.payload)['memory']
        with request_scope(actor):
            await handler.handle_memory(message, payload)
    profile = memory.notification_profile('7', 'shared')
    assert profile.enabled and profile.destination_id == '70' and profile.lead_minutes == (10, 0)
    assert profile.card_ids == ('calendar', 'weather') and profile.quiet_end == time(7)
    assert memory.notification_profile('9', 'shared') is None
    result = router.route('slumre #item 10 minutter', guild_id='70')
    assert validate_payload(result.intent, result.payload)['memory']['action'] == 'snooze'
    memory._storage.close()


@pytest.mark.asyncio
async def test_passed_event_only_says_finished_after_known_end(tmp_path):
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered', 'receipt')))
    item = {'id': 'item', 'title': 'Synthetic', 'date': '01.01.2027', 'time': '09:00', 'duration_minutes': 60, 'channel_id': '70'}
    checker = ReminderChecker(calendar_manager=SimpleNamespace(items={'shared': [item]}), outbound_sender=sender,
        storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T08:02:00+00:00'))
    await checker.setup(); await checker.check_event_passed()
    sender.send.assert_not_awaited()
    checker.clock = clock('2027-01-01T09:02:00+00:00')
    await checker.check_event_passed()
    assert 'ferdig' in sender.send.call_args.args[1].lower()
    checker.close_storage()


@pytest.mark.asyncio
async def test_snooze_delivery_dedup_survives_backward_clock_jump(tmp_path):
    from cal_system.notification_preferences import NotificationProfile
    from cal_system.reminder_checker import ReminderChecker
    from core.outbound_sender import DeliveryResult
    memory = UserMemory(tmp_path / 'memory.json')
    await memory.set_notification_profile('7', NotificationProfile(True, 'shared', '70', []))
    await memory.set_notification_snooze('7', 'shared', 'item', 'item:01.01.2027:09:00', datetime.fromisoformat('2027-01-01T08:10:00+00:00'))
    item = {'id': 'item', 'user_id': '7', 'scope_id': 'shared', 'channel_id': '70', 'title': 'Synthetic', 'date': '01.01.2027', 'time': '09:00'}
    sender = SimpleNamespace(send=AsyncMock(return_value=DeliveryResult('delivered', 'receipt')))
    checker = ReminderChecker(calendar_manager=SimpleNamespace(items={'shared': [item]}), user_memory=memory,
        outbound_sender=sender, storage_path=tmp_path / 'sent.json', clock=clock('2027-01-01T08:10:00+00:00'))
    await checker.setup(); await checker.check_notification_profiles()
    checker.clock = clock('2027-01-01T08:09:00+00:00'); await checker.check_notification_profiles()
    checker.clock = clock('2027-01-01T08:10:00+00:00'); await checker.check_notification_profiles()
    assert sender.send.await_count == 1
    assert memory.notification_snoozes('7', 'shared') == []
    checker.close_storage(); memory._storage.close()
