#!/usr/bin/env python3
"""
Conversational Response Generator
Makes Inebotten feel like a chat homie, not a bot
"""

import random
from datetime import datetime
from cal_system.norwegian_calendar import get_todays_info, get_moon_phase, get_sunrise_sunset
from ai.personality import get_personality, get_greeting, get_signoff


class ConversationalResponseGenerator:
    """
    Generates friendly, conversational responses
    """
    
    def __init__(self):
        self.personality = get_personality()
    
    def generate_dashboard(self, weather_data=None, events=None, reminders=None, norwegian_data=None):
        """
        Generate a conversational dashboard response
        """
        if norwegian_data is None:
            norwegian_data = get_todays_info()
        
        # Get sunrise/sunset for a natural mention
        lat = weather_data.get('lat', 59.9) if weather_data else 59.9
        lon = weather_data.get('lon', 10.7) if weather_data else 10.7
        sunrise, sunset, daylight = get_sunrise_sunset(latitude=lat, longitude=lon)
        
        lines = []
        
        # Time-appropriate greeting
        hour = datetime.now().hour
        if hour < 12:
            lines.append("God morgen! ☀️")
        elif hour < 18:
            lines.append("Hei der! 👋")
        else:
            lines.append("God kveld! 🌙")
        
        # Date with personality
        lines.append(f"I dag er det {norwegian_data['formatted_date']}")
        
        # Name day (if exists)
        if norwegian_data.get('navnedag'):
            names = " og ".join(norwegian_data['navnedag'][:2])  # Max 2 names
            lines.append(f"Vi feirer {names} i dag! 🎉")
        
        # Flag day (if exists and important)
        if norwegian_data.get('flaggdag'):
            lines.append(f"🇳🇴 {norwegian_data['flaggdag']}")
        
        # Weather - conversational
        if weather_data:
            location_str = f" i {weather_data['location']}" if weather_data.get('location') else ""
            lines.append(f"\n🌤️ **Været{location_str}:** {weather_data['conditions']}, {weather_data['temp']}°C")
            if weather_data['conditions'].lower() in ['sol', 'klarvær']:
                lines.append("Nydelig dag for å være ute! ☀️")
            elif weather_data['conditions'].lower() in ['regn', 'regnfullt']:
                lines.append("Perfekt dag for en kopp kaffe inne ☕")
            elif 'tåke' in weather_data['conditions'].lower():
                lines.append("Litt mystisk vær i dag 🌫️")
        
        # Sunrise/sunset - quick mention
        location_suffix = f" i {weather_data['location']}" if weather_data and weather_data.get('location') else " i dag"
        lines.append(f"\n☀️ Solen går ned {sunset}{location_suffix}")
        
        # Moon
        moon_phase, moon_emoji, _ = get_moon_phase()
        lines.append(f"🌙 Månen er {moon_phase.lower()} {moon_emoji}")
        
        # Events - conversational
        if events:
            lines.append(f"\n📅 **Kommer opp:**")
            for event in events[:3]:
                time_str = f" kl {event['time']}" if event.get('time') else ""
                # Calculate days until
                today = datetime.now().date()
                event_date = datetime.strptime(event['date'], '%d.%m.%Y').date()
                days_until = (event_date - today).days
                
                if days_until == 0:
                    when = "i dag"
                elif days_until == 1:
                    when = "i morgen"
                else:
                    when = f"om {days_until} dager"
                
                lines.append(f"• **{event['title']}** {when}{time_str}")
        
        # Reminders - conversational
        if reminders:
            lines.append(f"\n📝 **Huskeliste:**")
            for i, reminder in enumerate(reminders[:3], 1):
                lines.append(f"{i}. {reminder['text']}")
            if len(reminders) > 3:
                lines.append(f"...og {len(reminders) - 3} til")
        
        # Natural signoff with personality
        lines.append(f"\n{self.personality.get_signoff()}")
        
        # Subtle hint about capabilities
        if not events and not reminders:
            lines.append(f"\n💡 Vil du legge til noe? Prøv: \"@inebotten møte i morgen kl 10\"")
        
        return "\n".join(lines)
    
    def format_event_created(self, title, date, time=None):
        """Friendly confirmation when event is created"""
        time_str = f" kl {time}" if time else ""
        
        responses = [
            f"Supert! 📅 Jeg har notert **{title}** den {date}{time_str}!",
            f"Fikk det! ✅ **{title}** er lagt til {date}{time_str}.",
            f"Perfekt! 🎯 **{title}** står i kalenderen {date}{time_str}.",
        ]
        
        return random.choice(responses) + f"\n\n{self.personality.get_signoff()}"
    
    def format_event_list(self, events):
        """Friendly event list"""
        if not events:
            return "Ingen arrangementer på kalenderen akkurat nå. 📭\n\nVil du legge til noe? Bare si \"@inebotten [hva som skjer] [når]\"!"
        
        lines = ["Her er hva som kommer opp: 📅", ""]
        
        for i, event in enumerate(events, 1):
            time_str = f" kl {event['time']}" if event.get('time') else ""
            lines.append(f"{i}. **{event['title']}** - {event['date']}{time_str}")
        
        lines.append(f"\n💡 Vil du slette noe? Si \"slett arrangement [nummer]\"")
        
        return "\n".join(lines)
    
    def format_reminder_list(self, reminders):
        """Friendly reminder list"""
        if not reminders:
            return "Ingen huskelapper! 🎉\n\nAlt er i orden, eller vil du legge til noe?"
        
        lines = ["Din huskeliste: 📝", ""]
        
        for i, reminder in enumerate(reminders, 1):
            status = "✅" if reminder.get('completed') else "⬜"
            lines.append(f"{status} {i}. {reminder['text']}")
        
        lines.append(f"\n💡 Si \"ferdig [nummer]\" for å kryssse av!")
        
        return "\n".join(lines)
    
    def format_reminder_completed(self, text):
        """Celebrate completing a task"""
        celebrations = [
            f"Bra jobba! ✅ **{text}** er fullført!",
            f"Ferdig! 🎉 **{text}** - check!",
            f"Supert! ✅ **{text}** er gjort!",
        ]
        
        return random.choice(celebrations)
    
    def format_birthday_added(self, username, date, year=None):
        """Friendly birthday confirmation"""
        year_str = f" ({year})" if year else ""
        
        responses = [
            f"Notert! 🎂 {username} har bursdag {date}{year_str}!",
            f"Fikk det! 🎉 {date}{year_str} feirer vi {username}!",
        ]
        
        return random.choice(responses)
    
    def format_birthday_list(self, birthdays):
        """Friendly birthday list"""
        if not birthdays:
            return "Ingen bursdager registrert ennå. 🎂\n\nLegg til din med: \"@inebotten bursdag DD.MM\""
        
        lines = ["Bursdager å feire: 🎉", ""]
        
        months = ['', 'jan', 'feb', 'mar', 'apr', 'mai', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'des']
        
        for b in birthdays:
            date_str = f"{b['day']}. {months[b['month']]}"
            age_str = f" (blir {b['turning']})" if b.get('turning') else ""
            days_str = ""
            if b['days_until'] == 0:
                days_str = " - **I DAG!** 🎂"
            elif b['days_until'] == 1:
                days_str = " - i morgen!"
            elif b['days_until'] <= 7:
                days_str = f" - om {b['days_until']} dager"
            
            lines.append(f"• **{b['username']}**{age_str} - {date_str}{days_str}")
        
        return "\n".join(lines)
    
    def format_aurora_forecast(self, forecast):
        """Friendly aurora forecast"""
        if not forecast:
            return "Kunne ikke hente nordlysvarsel akkurat nå. Prøv igjen senere! 🌌"
        
        vis = forecast['visibility']
        
        lines = [
            f"🌌 **Nordlysvarsel**",
            f"",
            f"{vis['emoji']} **{vis['level']} aktivitet** (KP {forecast['kp_index']:.1f})",
            f"🎯 Sjanse: {forecast['probability']}%",
            f"📍 Kan sees: {vis['areas']}",
        ]
        
        # Add enthusiasm based on activity
        if forecast['kp_index'] >= 5:
            lines.append(f"\n🔥 **Dette er kvelden!** Gå ut og se om du kan få øye på nordlyset!")
        elif forecast['kp_index'] >= 3:
            lines.append(f"\n✨ Verdt å sjekke himmelen i kveld!")
        else:
            lines.append(f"\n💤 Kanskje ikke i kveld, men man vet aldri!")
        
        return "\n".join(lines)
    
    def format_school_holidays(self, holidays_text):
        """Just pass through, already formatted nicely"""
        return holidays_text
    
    def format_delete_confirmation(self, title):
        """Friendly delete confirmation"""
        responses = [
            f"Fjernet! 🗑️ **{title}** er slettet fra kalenderen.",
            f"Borte! ✅ **{title}** er ikke lenger i planene.",
        ]
        return random.choice(responses)
    
    def format_error(self, message="Jeg skjønte ikke helt..."):
        """Friendly error message"""
        responses = [
            f"{message} 🤔\n\nPrøv noe som:\n• \"@inebotten kamp i kveld kl 20\"\n• \"@inebotten påminnelse ringe mamma\"",
            f"{message} 😅\n\nDu kan si for eksempel:\n• \"@inebotten møte i morgen kl 10\"\n• \"@inebotten bursdag 15.05\"",
        ]
        return random.choice(responses)


# Singleton
_generator = None

def get_conversational_generator():
    """Get the conversational generator instance"""
    global _generator
    if _generator is None:
        _generator = ConversationalResponseGenerator()
    return _generator
