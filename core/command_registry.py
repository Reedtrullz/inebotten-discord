"""One typed command catalogue; IntentRouter remains the only text parser."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime
import json
import math
from types import MappingProxyType
from typing import Callable, Literal

from core.intent_router import BotIntent
from core.intent_thresholds import CONFIDENCE_THRESHOLDS
from core.request_context import RequestContext, request_scope


@dataclass(frozen=True)
class CommandSpec:
    intent: BotIntent
    aliases: tuple[str, ...]
    examples: tuple[str, ...]
    mutation_kind: Literal['read', 'write', 'mixed', 'provider']
    scope_rule: str
    handler_name: str
    payload_validator: Callable[[dict], dict]
    description: str
    argument: str = ''  # empty: message only; '*': full payload; otherwise one key


def _bounded_tree(value, depth=0, budget=None):
    budget = budget if budget is not None else [512]
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        raise ValueError('payload_too_complex')
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        if len(value) > 4000:
            raise ValueError('payload_too_large')
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict) and all(isinstance(key, str) and len(key) <= 64 for key in value):
        return {key: _bounded_tree(child, depth + 1, budget) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bounded_tree(child, depth + 1, budget) for child in value]
    raise ValueError('invalid_payload_type')


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _validator(intent, argument):
    # Full-payload adapters consume only these existing router fields.
    full_keys = {
        'calendar_search': {'query'}, 'reminder_search': {'query'},
        'reminder_edit': {'reminder'}, 'reminder_delete': {'reminder'},
        'reminder_create': {'reminder'}, 'reminder_list': {'reminder'},
        'reminder_complete': {'reminder'}, 'quote_edit': set(), 'quote_delete': set(),
        'birthday_edit': set(), 'calendar_auth': {'auth_code'},
    }
    incidental = {'calendar_delete': {'target'}, 'calendar_complete': {'target'},
                  'poll_list': {'history'}, 'dashboard': {'dashboard_reason'},
                  'ai_chat': {'error'}}
    allowed = full_keys.get(intent.value, set()) if argument == '*' else (
        {argument} if argument else incidental.get(intent.value, set()))
    def validate(payload):
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError('unexpected_payload_fields')
        sanitized = _bounded_tree(payload)
        if len(json.dumps(sanitized, ensure_ascii=False).encode()) > 32768:
            raise ValueError('payload_too_large')
        if argument not in ('', '*') and argument not in payload:
            raise ValueError('missing_payload_field')
        if argument not in ('', '*', 'vote', 'city') and not isinstance(payload[argument], dict):
            raise ValueError('invalid_command_fields')
        if argument == 'vote' and (type(payload['vote']) is not int or not 1 <= payload['vote'] <= 10):
            raise ValueError('invalid_vote')
        if argument == 'city' and not _nonblank(payload['city']):
            raise ValueError('invalid_city')
        if argument == 'calendar_item' and not _nonblank(payload[argument].get('title')):
            raise ValueError('invalid_calendar_title')
        if argument == 'search' and not _nonblank(payload[argument].get('query')):
            raise ValueError('invalid_query')
        if intent in (BotIntent.CALENDAR_SEARCH, BotIntent.REMINDER_SEARCH) and not _nonblank(payload.get('query')):
            raise ValueError('invalid_query')
        if intent == BotIntent.CALENDAR_AUTH and payload.get('auth_code') is not None and not _nonblank(payload['auth_code']):
            raise ValueError('invalid_auth_code')
        if 'target' in payload and not (type(payload['target']) is int and payload['target'] > 0 or _nonblank(payload['target'])):
            raise ValueError('invalid_target')
        if 'history' in payload and type(payload['history']) is not bool:
            raise ValueError('invalid_history')
        if argument == 'memory':
            fields = payload['memory']
            if set(fields) - {'action', 'confirmed', 'changes', 'value'}:
                raise ValueError('self_only_memory')
            actions = {'memory_view': {'view', 'policy', 'school_locality'},
                       'memory_export': {'export'}, 'memory_delete': {'delete'}}[intent.value]
            if fields.get('action') not in actions or ('confirmed' in fields and type(fields['confirmed']) is not bool):
                raise ValueError('invalid_memory_action')
            if fields['action'] == 'policy':
                from memory.user_memory import MemoryPolicy
                changes = fields.get('changes')
                if not isinstance(changes, dict) or not changes:
                    raise ValueError('invalid_memory_policy')
                MemoryPolicy(**changes)
            if fields['action'] == 'school_locality' and fields.get('value') not in ('oslo', 'trondheim'):
                raise ValueError('invalid_locality')
        return copy.deepcopy(payload)
    return validate


def _spec(intent, description, example, handler, argument='', mutation='read', scope='invocation', aliases=()):
    intent = BotIntent(intent)
    examples = (example,) if isinstance(example, str) else tuple(example)
    return CommandSpec(intent, tuple(aliases), examples, mutation, scope, handler,
                       _validator(intent, argument), description, argument)


COMMANDS = (
    _spec('help', 'Vis kommandohjelp', 'hjelp', 'help.handle_help', aliases=('help', 'hjelp')),
    _spec('status', 'Vis drift og relevante avvik', 'bot status', '_send_status_response', aliases=('health',)),
    _spec('profile', 'Endre egen Discord-profil', 'status online', '_registry_profile', mutation='write', scope='controller'),
    _spec('calendar_help', 'Vis kalenderhjelp', 'hjelp kalender', '_registry_calendar_help', scope='calendar'),
    _spec('calendar_list', 'Vis kommende kalender med område og ID', 'kalender', 'calendar.handle_list', scope='calendar'),
    _spec('calendar_sync', 'Synkroniser eller gjennomgå konflikt', ('synk', 'synk konflikt <ID> lokal', 'bekreft synk <ID>'), 'calendar.handle_sync', mutation='write', scope='calendar'),
    _spec('calendar_delete', 'Forhåndsvis sletting av valgt ID', 'slett #<ID> i kalender', 'calendar.handle_delete', mutation='write', scope='calendar'),
    _spec('calendar_complete', 'Fullfør valgt kalenderpunkt', 'ferdig #<ID> i kalender', 'calendar.handle_complete', mutation='write', scope='calendar'),
    _spec('calendar_edit', 'Endre valgt kalenderpunkt', 'kalender endre #<ID> tittel: Ny tittel', 'calendar.handle_edit', mutation='write', scope='calendar'),
    _spec('calendar_search', 'Søk i tillatt kalenderområde', 'søk kalender møte', 'calendar.handle_search', '*', scope='calendar'),
    _spec('calendar_clear', 'Forhåndsvis flere slettinger eller lokal angre', ('slett alt i kalender', 'bekreft kalender <token>', 'angre kalender <token>'), 'calendar.handle_clear', mutation='write', scope='calendar'),
    _spec('calendar_item', 'Tolk og opprett kalenderpunkt', 'møte i morgen kl 14', 'calendar.handle_calendar_item', 'calendar_item', 'write', 'calendar'),
    _spec('calendar_auth', 'Start eller fullfør Google-innlogging', 'kalender auth', 'calendar.handle_auth', '*', 'write', 'controller'),
    _spec('reminder_edit', 'Endre påminnelse', 'endre påminnelse 1 tekst: Ny tekst', 'reminders.handle_reminder_edit', '*', 'write', 'calendar'),
    _spec('reminder_delete', 'Slett påminnelse', 'slett påminnelse 1', 'reminders.handle_reminder_delete', '*', 'write', 'calendar'),
    _spec('reminder_search', 'Søk i påminnelser', 'søk påminnelse handle', 'reminders.handle_reminder_search', '*', scope='calendar'),
    _spec('reminder_create', 'Opprett påminnelse', 'påminnelse kjøp melk', 'reminders.handle_reminder_create', '*', 'write', 'calendar'),
    _spec('reminder_list', 'Vis aktive påminnelser', 'vis påminnelser', 'reminders.handle_reminder_list', '*', scope='calendar'),
    _spec('reminder_complete', 'Fullfør påminnelse', 'ferdig påminnelse 1', 'reminders.handle_reminder_complete', '*', 'write', 'calendar'),
    _spec('poll_create', 'Opprett avstemning', 'poll Pizza / Burger', 'polls.handle_poll', 'poll', 'write', 'channel'),
    _spec('poll_vote', 'Stem i aktiv avstemning', '1', 'polls.handle_vote', 'vote', 'write', 'channel'),
    _spec('poll_edit', 'Rediger egen poll; bekreft stemmeresett', 'endre poll 1 spørsmål: Nytt spørsmål', 'polls.handle_poll_edit', 'poll_edit', 'write', 'poll_owner'),
    _spec('poll_delete', 'Slett egen avstemning', 'slett poll 1', 'polls.handle_poll_delete', 'poll_delete', 'write', 'poll_owner'),
    _spec('poll_close', 'Lukk egen avstemning', 'lukk poll 1', 'polls.handle_poll_close', 'poll_close', 'write', 'poll_owner'),
    _spec('poll_list', 'Vis aktive eller avsluttede resultater', ('vis poll', 'poll resultater'), 'polls.handle_poll_list', scope='channel'),
    _spec('countdown', 'Vis nedtelling', 'hvor lenge til jul', 'countdown.handle_countdown', 'countdown'),
    _spec('watchlist', 'Administrer film- og serieliste', 'hva skal vi se', '_registry_watchlist', 'watchlist', 'mixed', 'channel'),
    _spec('word_of_day', 'Vis dagens ord', 'dagens ord', 'fun.handle_word_of_day'),
    _spec('quote', 'Hent eller lagre sitat', 'sitat', 'fun.handle_quote_command', 'quote', 'mixed', 'channel'),
    _spec('quote_list', 'Vis sitater', 'vis sitater', 'quotes.handle_quote_list', scope='channel'),
    _spec('quote_edit', 'Endre eget sitat', 'endre sitat 1 Ny tekst', 'quotes.handle_quote_edit', '*', 'write', 'channel'),
    _spec('quote_delete', 'Slett eget sitat', 'slett sitat 1', 'quotes.handle_quote_delete', '*', 'write', 'channel'),
    _spec('aurora', 'Vis nordlysvarsel med alder og kilde', 'nordlys', 'aurora.handle_aurora', mutation='provider'),
    _spec('school_holidays', 'Vis kildebelagt skolerute og dekning', 'skoleferie Trondheim 2026-2027', 'school_holidays.handle_school_holidays'),
    _spec('price', 'Vis markedsdata med kilde og alder', 'hva koster bitcoin', 'utility.handle_price', 'price', 'provider'),
    _spec('horoscope', 'Vis horoskop', 'horoskop væren', 'fun.handle_horoscope', 'horoscope'),
    _spec('compliment', 'Gi et kompliment', 'kompliment', 'fun.handle_compliment', 'compliment'),
    _spec('calculator', 'Beregn eller konverter med eksplisitt grunnlag', '2+2', 'utility.handle_calculator', 'calculator'),
    _spec('shorten_url', 'Forkort offentlig URL', 'forkort https://example.com/side', 'utility.handle_shorten', 'shorten', 'provider'),
    _spec('daily_digest', 'Vis dagens valgte oversikt', 'daglig oppsummering', 'daily_digest.handle_daily_digest', mutation='provider'),
    _spec('birthday_edit', 'Endre bursdagsoppføring', 'endre bursdag Ola 15.05', 'birthdays.handle_birthday_edit', '*', 'write', 'channel'),
    _spec('set_location', 'Lagre eget stedsvalg', 'jeg bor i Oslo', '_handle_set_location', 'city', 'write', 'self'),
    _spec('memory_view', 'Vis eller styr eget minne', ('vis minnet mitt', 'minne læring på', 'minne del med ingen', 'minne private fakta av', 'minne behold tema 7 dager', 'minne kommune oslo'), 'memory.handle_memory', 'memory', 'mixed', 'self'),
    _spec('memory_export', 'Eksporter eget minne', 'eksporter minnet mitt', 'memory.handle_memory', 'memory', scope='self'),
    _spec('memory_delete', 'Bekreft lokal sletting av eget minne', 'slett minnet mitt bekreft', 'memory.handle_memory', 'memory', 'write', 'self'),
    _spec('search', 'Søk offentlig informasjon', 'søk på nett Oslo', '_registry_search', 'search', 'provider'),
    _spec('dashboard', 'Vis forespurt oversikt', 'vis dashboard', '_send_dashboard_response', mutation='provider'),
    _spec('ai_chat', 'Svar med konfigurert AI', 'hei', '_send_ai_response', mutation='provider'),
)
_BY_INTENT = MappingProxyType({spec.intent: spec for spec in COMMANDS})
if set(_BY_INTENT) != set(BotIntent) or len(_BY_INTENT) != len(COMMANDS):
    raise RuntimeError('incomplete_command_registry')


def command_spec(intent):
    return _BY_INTENT[intent]


class CommandPayloadError(ValueError):
    pass


def validate_payload(intent, payload):
    try:
        return command_spec(intent).payload_validator(payload)
    except (ValueError, TypeError) as error:
        raise CommandPayloadError('invalid_command_payload') from error


def command_metadata():
    return [{'name': s.intent.value, 'aliases': list(s.aliases), 'examples': list(s.examples),
             'mutation_kind': s.mutation_kind, 'scope': s.scope_rule, 'handler': s.handler_name,
             'description': s.description, 'threshold': CONFIDENCE_THRESHOLDS.get(s.intent, 0.0)} for s in COMMANDS]


def command_reference():
    lines = ['# Kommandooversikt', '', 'Tagg Inebotten for å kjøre en kommando. Eksemplene følger den sentrale katalogen.',
             'Område og rettigheter kontrolleres ved faktisk kjøring; forhåndsvisning kjører ingen handler.', '',
             '| Intent | Eksempler | Virkning | Område | Beskrivelse |', '| --- | --- | --- | --- | --- |']
    for s in COMMANDS:
        examples = '<br>'.join('`' + x.replace('|', '\\|') + '`' for x in s.examples)
        lines.append(f'| {s.intent.value} | {examples} | {s.mutation_kind} | {s.scope_rule} | {s.description} |')
    return '\n'.join(lines) + '\n'


def preview_route(router, text, actor):
    """Inspect the existing pure route; never dispatch, invoke AI, or write state."""
    if not isinstance(actor, RequestContext) or not isinstance(text, str) or len(text) > 4000:
        raise ValueError('invalid_preview_input')
    with request_scope(actor):
        result = router.route(text, guild_id=actor.guild_id or actor.channel_id)
    spec = command_spec(result.intent)
    threshold = CONFIDENCE_THRESHOLDS.get(result.intent, 0.0)
    try:
        fields = _bounded_tree(validate_payload(result.intent, result.payload))
        validation = 'valid'
    except (ValueError, TypeError):
        fields, validation = {}, 'invalid_payload'
    if result.intent == BotIntent.CALENDAR_AUTH and 'auth_code' in fields:
        fields['auth_code'] = '[skjult]' if fields['auth_code'] else None
    if result.intent == BotIntent.AI_CHAT:
        fields = {}  # parser diagnostics may contain private raw input/error text
    return {'intent': result.intent.value, 'confidence': result.confidence, 'reason': result.reason,
            'threshold': threshold, 'accepted': validation == 'valid' and result.confidence >= threshold,
            'validation': validation, 'fields': fields, 'dispatched': False,
            'required_policy': {'invocation': True, 'mention_gate_required': True,
                                'scope_rule': spec.scope_rule, 'mutation_kind': spec.mutation_kind,
                                'actor_id': actor.user_id, 'authoritative_permission': False}}


def command_help_pages(max_chars=1700):
    if not 500 <= max_chars <= 1800:
        raise ValueError('invalid_help_page_size')
    header = '📖 **Kommandoer** — tagg Inebotten. Område, rettigheter og eventuelle bekreftelser sjekkes ved kjøring.\n'
    pages, lines = [], header
    for spec in COMMANDS:
        line = '\n• `' + spec.examples[0] + '` — ' + spec.description
        if len(lines + line) > max_chars:
            pages.append(lines)
            lines = header
        lines += line
    if lines != header:
        pages.append(lines)
    return tuple(pages)


async def dispatch_command(monitor, message, route):
    spec = command_spec(route.intent)
    payload = validate_payload(route.intent, route.payload)
    if spec.handler_name.startswith('_'):
        handler = getattr(monitor, spec.handler_name)
    else:
        owner, name = spec.handler_name.split('.', 1)
        handler = getattr(monitor.handlers[owner], name)
    if spec.argument == '*':
        return await handler(message, payload)
    if spec.argument:
        return await handler(message, payload[spec.argument])
    return await handler(message)
