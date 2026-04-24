#!/usr/bin/env python3
"""
Daily Digest Manager for Inebotten
Generates daily summary of events, weather, etc.
"""

from datetime import datetime, timedelta

class DailyDigestManager:
    """
    Generates daily digest summaries
    """
    
    def __init__(self, event_manager=None, birthday_manager=None, crypto_manager=None, aurora_manager=None, watchlist_manager=None):
        self.event_manager = event_manager
        self.birthday_manager = birthday_manager
        self.crypto_manager = crypto_manager
        self.aurora_manager = aurora_manager
        self.watchlist_manager = watchlist_manager
    
    async def generate_digest(self, guild_id, lang='no'):
        """
        Generate a comprehensive daily briefing for a guild
        """
        lines = []
        
        # Header with greeting
        hour = datetime.now().hour
        if lang == 'no':
            if hour < 12:
                greeting = "God morgen! ☀️"
            elif hour < 18:
                greeting = "God ettermiddag! 🌤️"
            else:
                greeting = "God kveld! 🌙"
            
            lines.extend([
                f"✨ **Dagens Briefing** ✨",
                f"_{greeting}_",
                "",
            ])
        else:
            if hour < 12:
                greeting = "Good morning! ☀️"
            elif hour < 18:
                greeting = "Good afternoon! 🌤️"
            else:
                greeting = "Good evening! 🌙"
            
            lines.extend([
                f"✨ **Daily Briefing** ✨",
                f"_{greeting}_",
                "",
            ])
        
        # Today's date
        today = datetime.now()
        from cal_system.norwegian_calendar import get_todays_info
        norwegian_data = get_todays_info()
        
        if lang == 'no':
            date_str = today.strftime('%d.%m.%Y')
            lines.append(f"📅 **Dato:** {date_str}")
            if norwegian_data.get('navnedag'):
                names = " og ".join(norwegian_data['navnedag'][:2])
                lines.append(f"🎉 **Navnedag:** {names}")
        else:
            date_str = today.strftime('%B %d, %Y')
            lines.append(f"📅 **Date:** {date_str}")
        lines.append("────────────────────")
        
        # 1. Weather Section
        from features.weather_api import get_weather_for_city, METWeatherAPI
        weather = await get_weather_for_city('oslo') # Default to Oslo
        if weather:
            emoji = METWeatherAPI().get_weather_emoji(weather['symbol_code'])
            if lang == 'no':
                lines.append(f"{emoji} **Været i {weather['location']}:** {weather['temp']}°C ({weather['condition']})")
                lines.append(f"   ↓ {weather['temp_low']}°C  ↑ {weather['temp_high']}°C")
            else:
                lines.append(f"{emoji} **Weather in {weather['location']}:** {weather['temp']}°C ({weather['condition']})")
                lines.append(f"   ↓ {weather['temp_low']}°C  ↑ {weather['temp_high']}°C")
            lines.append("")

        # 2. Birthdays Section
        if self.birthday_manager:
            birthdays = self.birthday_manager.get_todays_birthdays(guild_id)
            if birthdays:
                lines.append("🎂 **Bursdager i dag!**")
                for name, age in birthdays:
                    age_str = f" ({age} år)" if age else ""
                    lines.append(f"• **{name}**{age_str} 🎉")
                lines.append("")

        # 3. Events Section
        if self.event_manager:
            today_events = self._get_today_events(guild_id)
            if today_events:
                if lang == 'no':
                    lines.append(f"📋 **Dagens planer ({len(today_events)}):**")
                else:
                    lines.append(f"📋 **Today's events ({len(today_events)}):**")
                for event in today_events[:5]:
                    lines.append(f"• {event['title']} kl {event.get('time', '??:??')}")
                lines.append("")
        
        # 4. Market Update (Crypto)
        if self.crypto_manager:
            lines.append("₿ **Markedet:**")
            top_coins = ['bitcoin', 'ethereum', 'solana']
            for coin in top_coins:
                data = await self.crypto_manager.get_price({'type': 'crypto', 'coin_id': coin, 'asset': coin, 'display_name': coin.upper()})
                if data:
                    change_emoji = '📈' if data['change_24h'] >= 0 else '📉'
                    lines.append(f"• {data['symbol']}: **${data['price']:,.0f}** ({change_emoji} {data['change_24h']:.1f}%)")
            lines.append("")

        # 5. Aurora Forecast
        if self.aurora_manager:
            forecast = await self.aurora_manager.get_forecast()
            if forecast and forecast['kp_index'] >= 3:
                vis = forecast['visibility']
                lines.append(f"🌌 **Nordlysvarsel:** {vis['emoji']} KP {forecast['kp_index']:.1f} - {vis['level']}")
                lines.append(f"   _{vis['areas']}_")
                lines.append("")

        # 6. Watchlist Update
        if self.watchlist_manager:
            items = self.watchlist_manager.get_watchlist(guild_id)
            if items:
                active_items = [i for i in items if not i.get('completed')]
                if active_items:
                    lines.append(f"📦 **Vaktliste:** {len(active_items)} aktive ting")
                    for item in active_items[:2]:
                        lines.append(f"• {item['title']}")
                    lines.append("")

        lines.append("────────────────────")
        # Fun tip / Closing
        if lang == 'no':
            lines.append("💡 *Tips: Bruk `@inebotten hjelp` for å se alle kommandoer.*")
        else:
            lines.append("💡 *Tip: Use `@inebotten help` to see all commands.*")
        
        return "\n".join(lines)
    
    def _get_today_events(self, guild_id):
        """Get events for today"""
        if not self.event_manager:
            return []
        
        today = datetime.now().strftime('%d.%m.%Y')
        # Use get_upcoming which is the correct method in CalendarManager
        events = self.event_manager.get_upcoming(guild_id, days=1)
        
        # Filter to today's events
        today_events = [e for e in events if e.get('date') == today]
        return today_events


async def generate_daily_digest(guild_id, event_manager=None, birthday_manager=None, crypto_manager=None, aurora_manager=None, watchlist_manager=None, lang='no'):
    """Convenience function"""
    manager = DailyDigestManager(event_manager, birthday_manager, crypto_manager, aurora_manager, watchlist_manager)
    return await manager.generate_digest(guild_id, lang)
