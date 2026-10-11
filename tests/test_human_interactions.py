from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cal_system.reminder_manager import ReminderManager, parse_reminder_command
from core.intent_router import IntentRouter
from features.poll_manager import PollManager, parse_poll_command, parse_vote
from features.polls_handler import PollsHandler
from features.quote_manager import parse_quote_command
from features.reminder_handler import ReminderHandler
from tests.test_poll_reactions import _bare_monitor, _payload
from tests.test_intent_router import DummyMonitor


def monitor(**fields):
    return SimpleNamespace(rate_limiter=SimpleNamespace(), client=SimpleNamespace(),
        loc=SimpleNamespace(current_lang='no', t=lambda key, **kw: f'{key}: {kw}'), **fields)


def message(content):
    return SimpleNamespace(content=content, guild=SimpleNamespace(id=123),
        channel=SimpleNamespace(id=777), author=SimpleNamespace(id=555, name='Synthetic'))


@pytest.mark.parametrize('text', [
    'Hvorfor bruker mennesker en calendar?', 'Hvordan fungerer en poll?',
    'Forklar hvordan man kan slette en kalender',
    'Hvordan kan man endre påminnelse 1?',
    'Forklar hvordan slette sitat fungerer',
    'Vis meg hvordan en kalender fungerer',
    'Fortell om poll Pizza eller Burger?',
    'Forklar https://example.com/a/b',
    'Forklar en/annen/ting',
])
def test_prose_stays_conversational(text):
    m = SimpleNamespace(**vars(DummyMonitor()))
    m.parse_poll_command, m.parse_vote = parse_poll_command, parse_vote
    m.parse_quote_command = parse_quote_command
    assert IntentRouter(m).route(text, 123).intent.value == 'ai_chat'


def test_named_poll_options():
    parsed = parse_poll_command('avstemning Pizza eller burgere i kveld?')
    assert parsed is not None
    assert parsed['options'] == ['Pizza', 'burgere i kveld']


@pytest.mark.parametrize('text,intent', [('polls', 'poll_list'), ('endre poll 1 spørsmål: Nytt?', 'poll_edit'), ('slett poll 1', 'poll_delete'), ('stem 1', 'poll_vote')])
def test_empty_state_commands_reach_recoverable_handler(text, intent):
    m = SimpleNamespace(**vars(DummyMonitor()))
    m.parse_poll_command, m.parse_vote = parse_poll_command, parse_vote
    assert IntentRouter(m).route(text, 123).intent.value == intent


@pytest.mark.asyncio
async def test_invalid_explicit_poll_does_not_vote(tmp_path):
    polls = PollManager(tmp_path / 'polls.json')
    try:
        poll = polls.create_poll(123, 'Question?', ['A', 'B'], 'Synthetic', 555)
        handler = PollsHandler(monitor(poll=polls))
        handler.send_response = AsyncMock()
        await handler.handle_vote(message('stem 9 2'), {'poll_ref': 9, 'option_index': 2})
        saved = polls.get_poll(123, poll['id'])
        assert saved is not None
        assert all(not o['votes'] for o in saved['options'])
    finally:
        polls.close_storage()


def test_reminder_list_is_bounded_and_keeps_hidden_records_findable(tmp_path):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        for i in range(10):
            reminders.add_reminder(123, 555, 'Synthetic', f'Task {i + 1} ' + 'x' * 3000)
        first = reminders.format_reminders_list(123)
        second = reminders.format_reminders_list(123, page=2)
        assert first is not None and second is not None
        assert len(first) <= 2000 and '10 aktive' in first and 'side 2' in first
        assert '**9.** Task 9' in second
        assert len(reminders.get_active_reminders(123)[0]['text']) > 3000
        assert len(reminders.format_search_results(123, 'x')) <= 2000
    finally:
        reminders._storage.close()


def test_absolute_reminder_time_is_deadline():
    parsed = parse_reminder_command('påminnelse ring legen 12.10.2026 kl 14:00')
    assert parsed is not None
    assert parsed['due_date'] == '12.10.2026 14:00'
    assert parsed['text'] == 'ring legen'


def test_series_content_rejects_non_content_fields():
    from cal_system.mutation_preview import validate_calendar_document
    assert not validate_calendar_document({'123': [{'id': 'synthetic', 'title': 'Weekly',
        'series_content': {'id': 'changed', 'title': 'Injected'}}]})


@pytest.mark.asyncio
async def test_poll_pages_and_results_are_bounded(tmp_path):
    polls = PollManager(tmp_path / 'polls.json')
    try:
        for i in range(10):
            polls.create_poll(123, f'Question {i + 1} ' + 'x' * 180,
                [str(n) + 'x' * 149 for n in range(10)], 'Synthetic', 555)
        handler = PollsHandler(monitor(poll=polls))
        handler.send_response = AsyncMock(return_value=object())
        await handler.handle_vote(message('stem 1'), 1)
        assert len(handler.send_response.call_args.args[1]) <= 2000
        assert len(handler._poll_target_response(123, None, 'endre')) <= 2000
        await handler.handle_poll_list(message('polls side 2'))
        content = handler.send_response.call_args.args[1]
        assert '9. Question 9' in content and '10 aktive' in content and len(content) <= 2000
        for p in polls.get_active_polls(123):
            polls.close_poll(123, p['id'], 555)
        await handler.handle_poll_list(message('poll resultater side 2'))
        content = handler.send_response.call_args.args[1]
        assert 'side 2/10' in content and len(content) <= 2000
    finally:
        polls.close_storage()


def test_invalid_deadline_is_rejected_atomically(tmp_path):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        with pytest.raises(ValueError):
            reminders.add_reminder(123, 555, 'Synthetic', 'Task', '31.02.2027')
        assert reminders.get_active_reminders(123) == []
    finally:
        reminders._storage.close()


def test_time_edit_preserves_title_and_date(tmp_path):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        reminders.add_reminder(123, 555, 'Synthetic', 'Task', '12.10.2026 09:30')
        result = reminders.edit_reminder(123, 1, time='14:00')
        assert result['due_date'] == '12.10.2026 14:00'
        assert result['text'] == 'Task'
    finally:
        reminders._storage.close()


def test_console_withholds_scoped_poll_without_actor(tmp_path, monkeypatch):
    from tests.test_group_planning import fixture, context, candidates
    from web_console import state_collector
    planning, calendar, polls = fixture(tmp_path)
    try:
        planning.create(context(), 'group:approved', 'Restricted synthetic plan', candidates())
        monkeypatch.setattr(state_collector, 'hermes_discord_data_path', lambda _: polls.storage_path)
        assert state_collector.collect_poll_data()['polls'] == []
    finally:
        calendar._storage.close()
        polls.close_storage()


@pytest.mark.asyncio
async def test_reaction_removal_restores_remaining_choice_and_survives_restart(tmp_path):
    polls = PollManager(tmp_path / 'polls.json')
    poll = polls.create_poll(123, 'Question?', ['A', 'B'], 'Synthetic', 555)
    polls.set_message_id(123, poll['id'], 999, 777)
    m = _bare_monitor(polls)
    await m.handle_reaction_vote(_payload(emoji='1️⃣'))
    await m.handle_reaction_vote(_payload(emoji='2️⃣'))
    polls.close_storage()
    polls = PollManager(tmp_path / 'polls.json')
    try:
        m = _bare_monitor(polls)
        await m.handle_reaction_vote(_payload(emoji='2️⃣', event_type='REACTION_REMOVE'))
        saved = polls.get_poll(123, poll['id'])
        assert saved is not None
        assert saved['options'][0]['votes'] == ['555']
        assert saved['options'][1]['votes'] == []
    finally:
        polls.close_storage()


@pytest.mark.asyncio
async def test_stale_display_cannot_complete_another_reminder(tmp_path):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        a = reminders.add_reminder(123, 555, 'Synthetic', 'Alpha')
        reminders.add_reminder(123, 555, 'Synthetic', 'Beta')
        handler = ReminderHandler(monitor(reminders=reminders))
        handler.send_response = AsyncMock(return_value=SimpleNamespace(id=1))
        await handler.handle_reminder_list(message('påminnelser'))
        reminders.complete_reminder(123, reminder_id=a)
        await handler.handle_reminder_complete(message('ferdig påminnelse 1'), {'reminder': {'number': 1}})
        assert [r['text'] for r in reminders.get_active_reminders(123)] == ['Beta']
        call = handler.send_response.await_args
        assert call is not None
        assert 'listen' in call.args[1].lower()
    finally:
        reminders._storage.close()


@pytest.mark.asyncio
async def test_deletion_requires_actor_bound_preview(tmp_path):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        reminders.add_reminder(123, 555, 'Synthetic', 'Alpha')
        handler = ReminderHandler(monitor(reminders=reminders))
        handler.send_response = AsyncMock(return_value=SimpleNamespace(id=1))
        await handler.handle_reminder_list(message('påminnelser'))
        await handler.handle_reminder_delete(message('slett påminnelse 1'))
        assert len(reminders.get_active_reminders(123)) == 1
        call = handler.send_response.await_args
        assert call is not None
        response = call.args[1]
        import re
        confirmation = re.search(r'`@inebotten (bekreft sletting påminnelse [A-Za-z0-9_-]+)`', response)
        assert confirmation is not None
        stranger = message(confirmation.group(1))
        stranger.author.id = 999
        await handler.handle_reminder_delete(stranger)
        assert len(reminders.get_active_reminders(123)) == 1
        await handler.handle_reminder_delete(message(confirmation.group(1)))
        assert reminders.get_active_reminders(123) == []
        await handler.handle_reminder_delete(message(confirmation.group(1)))
        assert reminders.get_active_reminders(123) == []
    finally:
        reminders._storage.close()


@pytest.mark.parametrize('domain', ['quote', 'watchlist'])
@pytest.mark.asyncio
async def test_edits_require_fresh_delivered_list(tmp_path, domain):
    from features.quote_handler import QuoteHandler
    from features.quote_manager import QuoteManager
    from features.watchlist_handler import WatchlistHandler
    from features.watchlist_manager import WatchlistManager
    if domain == 'quote':
        manager = QuoteManager(tmp_path / 'quotes.json')
        manager.add_quote(123, 'Alpha', 'Synthetic')
        manager.add_quote(123, 'Beta', 'Synthetic')
        handler = QuoteHandler(monitor(quote=manager))
        records = lambda: manager.list_quotes(123)
        listing = lambda: handler.handle_quote_list(message('liste sitater'))
        editing = lambda: handler.handle_quote_edit(message('endre sitat 1 tekst: Changed'), {})
        remove = lambda: manager.delete_quote(123, 1)
        field = 'text'
    else:
        manager = WatchlistManager(tmp_path / 'watchlist.json')
        manager.add_from_discord_message('Alpha', 'movie', guild_id=123)
        manager.add_from_discord_message('Beta', 'movie', guild_id=123)
        handler = WatchlistHandler(monitor(watchlist=manager))
        records = lambda: manager.get_watchlist(123)
        listing = lambda: handler.handle_watchlist(message('watchlist'), {'action': 'status'})
        editing = lambda: handler.handle_watchlist(message('endre watchlist 1 Changed'), {'action': 'edit', 'index': 1})
        remove = lambda: manager.remove_from_watchlist(1, guild_id=123)
        field = 'title'
    handler.send_response = AsyncMock(return_value=SimpleNamespace(id=1))
    await editing()
    assert records()[0][field] == 'Alpha'
    await listing()
    remove()
    await editing()
    assert records()[0][field] == 'Beta'
    await listing()
    await editing()
    assert records()[0][field] == 'Changed'


def test_birthday_duplicate_names_need_explicit_identity(tmp_path):
    from features.birthday_manager import BirthdayManager
    birthdays = BirthdayManager(tmp_path / 'birthdays.json')
    birthdays.add_birthday(123, 1, 'Synthetic', 1, 1)
    birthdays.add_birthday(123, 2, 'Synthetic', 2, 2)
    before = birthdays.storage_path.read_bytes()
    with pytest.raises(ValueError, match='tvetydig'):
        birthdays.edit_birthday(123, 'Synthetic', 3, 3)
    assert birthdays.storage_path.read_bytes() == before
    assert birthdays.edit_birthday(123, '#2', 3, 3)['day'] == 3


def test_text_vote_survives_removal_of_old_reaction(tmp_path):
    polls = PollManager(tmp_path / 'polls.json')
    try:
        poll = polls.create_poll(123, 'Question?', ['A', 'B'], 'Synthetic', 555)
        assert polls.vote(123, poll['id'], 1, 555, 'Synthetic', reaction=True)[0]
        assert polls.vote(123, poll['id'], 1, 555, 'Synthetic')[0]
        assert not polls.withdraw_vote(123, poll['id'], 1, 555)
        saved = polls.get_poll(123, poll['id'])
        assert saved is not None and saved['options'][0]['votes'] == ['555']
    finally:
        polls.close_storage()


@pytest.mark.parametrize('deadline', ['31.02.2027', '28.03.2027 02:30', '25.10.2026 02:30', '12.10.2026 25:00'])
def test_invalid_or_unresolved_deadline_edits_do_not_write(tmp_path, deadline):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        reminders.add_reminder(123, 555, 'Synthetic', 'Task', '12.10.2026 09:30')
        before = reminders.storage_path.read_bytes()
        with pytest.raises(ValueError):
            reminders.edit_reminder(123, 1, date=deadline)
        assert reminders.storage_path.read_bytes() == before
    finally:
        reminders._storage.close()


@pytest.mark.asyncio
async def test_reminder_second_page_binds_visible_global_numbers(tmp_path):
    reminders = ReminderManager(tmp_path / 'reminders.json')
    try:
        for i in range(10):
            reminders.add_reminder(123, 555, 'Synthetic', f'Task {i + 1}')
        handler = ReminderHandler(monitor(reminders=reminders))
        handler.send_response = AsyncMock(return_value=SimpleNamespace(id=1))
        await handler.handle_reminder_list(message('påminnelser side 2'))
        call = handler.send_response.await_args
        assert call is not None and '**9.** Task 9' in call.args[1]
        await handler.handle_reminder_complete(message('ferdig påminnelse 1'), {'reminder': {'number': 1}})
        assert len(reminders.get_active_reminders(123)) == 10
        await handler.handle_reminder_complete(message('ferdig påminnelse 9'), {'reminder': {'number': 9}})
        assert len(reminders.get_active_reminders(123)) == 9
    finally:
        reminders._storage.close()


@pytest.mark.asyncio
async def test_poll_numbers_refuse_changed_list_but_stable_id_still_votes(tmp_path):
    polls = PollManager(tmp_path / 'polls.json')
    try:
        first = polls.create_poll(123, 'First?', ['A', 'B'], 'Synthetic', 555)
        second = polls.create_poll(123, 'Second?', ['A', 'B'], 'Synthetic', 555)
        handler = PollsHandler(monitor(poll=polls))
        handler.send_response = AsyncMock(return_value=SimpleNamespace(id=1))
        await handler.handle_poll_list(message('polls'))
        polls.close_poll(123, first['id'], 555, 'Synthetic')
        await handler.handle_vote(message('stem 1 2'), {'poll_ref': 1, 'option_index': 2})
        saved = polls.get_poll(123, second['id'])
        assert saved is not None and all(not option['votes'] for option in saved['options'])
        parsed = parse_vote(f'stem #{second["id"]} 2')
        assert parsed is not None
        await handler.handle_vote(message(f'stem #{second["id"]} 2'), parsed)
        saved = polls.get_poll(123, second['id'])
        assert saved is not None and saved['options'][1]['votes'] == ['555']
    finally:
        polls.close_storage()
