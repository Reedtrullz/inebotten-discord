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
    
    def __init__(self, event_manager=None, weather_manager=None):
        self.event_manager = event_manager
        self.weather_manager = weather_manager
    
    def generate_digest(self, guild_id, lang='no'):
        """
        Generate daily digest for a guild
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
                f"📰 **Dagens Oppsummering**",
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
                f"📰 **Daily Digest**",
                f"_{greeting}_",
                "",
            ])
        
        # Today's date
        today = datetime.now()
        if lang == 'no':
            date_str = today.strftime('%d.%m.%Y')
            lines.append(f"📅 **I dag:** {date_str}")
        else:
            date_str = today.strftime('%B %d, %Y')
            lines.append(f"📅 **Today:** {date_str}")
        lines.append("")
        
        # Weather (placeholder - would integrate with weather manager)
        if lang == 'no':
            lines.extend([
                "🌤️ **Vær:**",
                "Sjekk været med `@inebotten vær [by]`",
                "",
            ])
        else:
            lines.extend([
                "🌤️ **Weather:**",
                "Check weather with `@inebotten weather [city]`",
                "",
            ])
        
        # Events today
        if self.event_manager:
            today_events = self._get_today_events(guild_id)
            if today_events:
                if lang == 'no':
                    lines.append(f"📋 **Arrangementer i dag ({len(today_events)}):**")
                else:
                    lines.append(f"📋 **Events today ({len(today_events)}):**")
                for event in today_events[:3]:
                    lines.append(f"• {event['title']} kl {event.get('time', '??:??')}")
                lines.append("")
            else:
                if lang == 'no':
                    lines.extend([
                        "📋 **Arrangementer:**",
                        "Ingen planlagt i dag",
                        "",
                    ])
                else:
                    lines.extend([
                        "📋 **Events:**",
                        "None scheduled today",
                        "",
                    ])
        
        # Reminders
        if lang == 'no':
            lines.extend([
                "⏰ **Påminnelser:**",
                "Se dine påminnelser med `@inebotten påminnelser`",
                "",
            ])
        else:
            lines.extend([
                "⏰ **Reminders:**",
                "See your reminders with `@inebotten reminders`",
                "",
            ])
        
        # Fun tip
        if lang == 'no':
            lines.extend([
                "💡 **Dagens tips:**",
                "Prøv `@inebotten horoskop [stjernetegn]` for å lese horoskopet ditt!",
            ])
        else:
            lines.extend([
                "💡 **Daily tip:**",
                "Try `@inebotten horoscope [zodiac sign]` to read your horoscope!",
            ])
        
        return "\n".join(lines)
    
    def _get_today_events(self, guild_id):
        """Get events for today"""
        if not self.event_manager:
            return []
        
        today = datetime.now().strftime('%d.%m.%Y')
        events = self.event_manager.get_upcoming_events(guild_id, days=1)
        
        # Filter to today's events
        today_events = [e for e in events if e.get('date') == today]
        return today_events


def generate_daily_digest(guild_id, event_manager=None, birthday_manager=None, lang='no'):
    """Convenience function"""
    manager = DailyDigestManager(event_manager, birthday_manager)
    return manager.generate_digest(guild_id, lang)
