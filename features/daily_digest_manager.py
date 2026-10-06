"""Shared requested/proactive cards with independently degraded providers."""
import asyncio

from cal_system.event_schema import Clock
from cal_system.notification_preferences import CARD_IDS
from core.request_context import current_request


class DailyDigestManager:
    def __init__(self, event_manager=None, birthday_manager=None, crypto_manager=None,
                 aurora_manager=None, watchlist_manager=None, forecast_service=None,
                 user_memory=None, clock=None, workflows=None):
        self.workflows = workflows
        self.event_manager = event_manager
        self.birthday_manager = birthday_manager
        self.crypto_manager = crypto_manager
        self.aurora_manager = aurora_manager
        self.watchlist_manager = watchlist_manager
        self.user_memory = user_memory
        self.clock = clock or Clock()
        from features.forecast_service import ForecastService
        self.forecasts = forecast_service or ForecastService()

    async def generate_digest(self, guild_id, lang='no', user_id=None, *, card_ids=None, proactive=False):
        selected = tuple((card for card in CARD_IDS if card!='workflow') if card_ids is None else card_ids)
        if any(card not in CARD_IDS for card in selected):
            raise ValueError('invalid_digest_cards')
        lines = ['✨ **Dagens oversikt**' if lang == 'no' else '✨ **Daily briefing**']
        deadline = asyncio.get_running_loop().time() + 8
        for card in dict.fromkeys(selected):
            try:
                async with asyncio.timeout_at(deadline):
                    text = await self._card(card, guild_id, lang, user_id, proactive=proactive)
            except Exception:
                text = f'{card}: utilgjengelig; øvrige kort er bevart.' if lang == 'no' else f'{card}: unavailable; other cards retained.'
            if text:
                lines.append(text[:1200])
        return '\n\n'.join(lines)[:1800]

    async def _card(self, card, scope, lang, user_id, *, proactive=False):
        now = self.clock.now()
        if card == 'workflow' and self.workflows:
            return self.workflows.digest_card(current_request(),scope)
        if card == 'date':
            return f'📅 {now:%d.%m.%Y} ({now.tzinfo})'
        if card == 'calendar':
            items = self._get_today_events(scope,proactive=proactive)
            body = '\n'.join(f"• {i['title']}" + (f" kl. {i['time']}" if i.get('time') else ' (heldag/dato)') for i in items[:8])
            return f'📋 Lokal kalender · {now:%d.%m.%Y}\n' + (body or 'Ingen planer i dag.')
        if card == 'weather':
            from features.forecast_service import resolve_location, format_weather
            city = 'oslo'
            actor = current_request()
            if user_id and self.user_memory and actor and actor.channel_kind == 'dm' and actor.user_id == str(user_id):
                city = self.user_memory.memory.get(str(user_id), {}).get('location') or city
            return format_weather(await self.forecasts.get_weather(resolve_location(city)), lang)
        if card == 'birthdays' and self.birthday_manager:
            entries = self.birthday_manager.get_todays_birthdays(scope)
            return '🎂 Lokal bursdagsliste\n' + '\n'.join(f'• {name}' for name, _age in entries[:8]) if entries else ''
        if card == 'market' and self.crypto_manager:
            data = await self.crypto_manager.get_price({'type': 'crypto', 'coin_id': 'bitcoin', 'asset': 'bitcoin', 'display_name': 'Bitcoin'})
            return self.crypto_manager.format_price(data, lang) + '\nKilde: CoinGecko; hentet/gyldig tidspunkt ikke dokumentert.' if data else 'Marked: utilgjengelig.'
        if card == 'aurora' and self.aurora_manager:
            data = await self.aurora_manager.get_forecast()
            return self.aurora_manager.format_forecast(data) if data else 'Nordlys: utilgjengelig.'
        if card == 'watchlist' and self.watchlist_manager:
            items = [i for i in self.watchlist_manager.get_watchlist(scope) if not i.get('completed')]
            return '📦 Lokal vaktliste\n' + '\n'.join(f"• {i['title']}" for i in items[:4]) if items else ''
        return ''

    def _get_today_events(self, scope, *, proactive=False):
        if not self.event_manager:
            return []
        today = self.clock.now().strftime('%d.%m.%Y')
        return [i for i in self.event_manager.get_upcoming(scope, days=1) if i.get('date') == today
            and (not proactive or not i.get('_planning_source') or i.get('planning_notifications_approved'))]


async def generate_daily_digest(guild_id, event_manager=None, birthday_manager=None,
        crypto_manager=None, aurora_manager=None, watchlist_manager=None, lang='no'):
    manager = DailyDigestManager(event_manager, birthday_manager, crypto_manager, aurora_manager, watchlist_manager)
    return await manager.generate_digest(guild_id, lang)
