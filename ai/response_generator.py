#!/usr/bin/env python3
"""
Response Generator for Discord Selfbot - Norwegian Version
Formatterer kalender- og almanakk-informasjon for Discord-meldinger
"""

import datetime
import random
from cal_system.norwegian_calendar import (
    get_todays_info, get_moon_phase, get_sunrise_sunset,
    format_date_norwegian
)


class ResponseGenerator:
    """
    Generates formatted calendar and almanac responses in Norwegian
    """
    
    def __init__(self):
        self.templates = self._load_templates()
    
    def _load_templates(self):
        """
        Load Norwegian response templates
        """
        return {
            'weather': [
                "Vær: {conditions}, {temp}°C. H: {high}°, L: {low}°",
                "Nå: {conditions} ved {temp}°C (H:{high}° L:{low}°)",
                "{conditions} - {temp}°C i dag, opptil {high}°"
            ],
            'holiday': [
                "I dag: {holiday}",
                "Markerer: {holiday}",
                "Det er {holiday}!"
            ],
            'moon': [
                "{phase} ({emoji})",
                "Måne: {phase} {emoji}",
                "Månefase: {phase} {emoji}"
            ],
            'almanac': [
                "Soloppgang: {sunrise} | Solnedgang: {sunset}",
                "Dagslys: {sunrise} - {sunset}",
                "{sunrise} 🌅 → {sunset} 🌇"
            ]
        }
    
    def generate_full_response(self, weather_data=None, holiday_data=None, 
                               almanac_data=None, reminders=None, 
                               norwegian_data=None):
        """
        Generate a complete calendar/almanac response in Norwegian (Dashboard)
        Trimmed version - Aurora and School Holidays available via commands
        
        Args:
            weather_data: Optional weather dict
            holiday_data: Optional holidays dict
            almanac_data: Optional almanac dict
            reminders: Optional reminders list
            norwegian_data: Dict with navnedag, flaggdag, week_number (auto-generated if None)
        
        Returns formatted markdown string
        """
        now = datetime.datetime.now()
        lines = []
        
        # Get Norwegian calendar info
        if norwegian_data is None:
            norwegian_data = get_todays_info()
        
        # Header with full Norwegian date format
        header_date = format_date_norwegian(now, include_week=True)
        lines.append(f"📅 **Kalender & Almanakk**")
        lines.append(f"*{header_date}*")
        lines.append("")
        
        # Norwegian Name Day (Navnedag)
        if norwegian_data.get('navnedag'):
            names = ", ".join(norwegian_data['navnedag'])
            lines.append(f"🎂 **Navnedag:** {names}")
            lines.append("")
        
        # Norwegian Flag Day (Flaggdag)
        if norwegian_data.get('flaggdag'):
            flaggday = norwegian_data['flaggdag']
            lines.append(f"🇳🇴 **Flaggdag:** {flaggday}")
            lines.append("")
        
        # Weather section
        if weather_data:
            lines.append(self._format_weather(weather_data))
            lines.append("")
        
        # Holidays section
        if holiday_data:
            lines.append(self._format_holidays(holiday_data))
            lines.append("")
        
        # Reminders section (events + reminders) - compact display
        if reminders:
            lines.append(self._format_reminders_compact(reminders))
            lines.append("")
        
        # Almanac section (moon + sun)
        if almanac_data:
            lines.append(self._format_almanac_compact(almanac_data))
            lines.append("")
        
        # Footer with hint about commands
        lines.append("— *🌌 Nordlys: `@inebotten nordlys` | 🎓 Skoleferie: `@inebotten skoleferie`*")
        
        return "\n".join(lines)
    
    def _format_weather(self, data):
        """
        Format weather section in Norwegian
        """
        template = random.choice(self.templates['weather'])
        
        # Translate conditions to Norwegian
        conditions_en = data.get('conditions', 'Unknown')
        conditions_no = self._translate_weather(conditions_en)
        
        temp = data.get('temp', '--')
        high = data.get('high', '--')
        low = data.get('low', '--')
        
        weather_line = template.format(
            conditions=conditions_no,
            temp=temp,
            high=high,
            low=low
        )
        
        emoji = self._weather_emoji(conditions_en)
        
        return f"{emoji} **Vær:**\n   {weather_line}"
    
    def _translate_weather(self, conditions):
        """
        Translate weather conditions to Norwegian
        """
        translations = {
            'sunny': 'Sol',
            'clear': 'Klart',
            'partly cloudy': 'Delvis skyet',
            'cloudy': 'Skyet',
            'overcast': 'Overskyet',
            'rain': 'Regn',
            'rainy': 'Regnfullt',
            'showers': 'Byger',
            'snow': 'Snø',
            'snowy': 'Snøfullt',
            'storm': 'Storm',
            'thunderstorm': 'Torden',
            'fog': 'Tåke',
            'mist': 'Dis',
            'windy': 'Vindfullt',
            'unknown': 'Ukjent'
        }
        
        conditions_lower = conditions.lower()
        for en, no in translations.items():
            if en in conditions_lower:
                return no
        return conditions  # Return original if no translation
    
    def _weather_emoji(self, conditions):
        """
        Get weather emoji based on conditions
        """
        conditions = conditions.lower()
        if 'sun' in conditions or 'clear' in conditions:
            return '☀️'
        elif 'cloud' in conditions:
            return '☁️'
        elif 'rain' in conditions or 'shower' in conditions:
            return '🌧️'
        elif 'snow' in conditions:
            return '❄️'
        elif 'storm' in conditions or 'thunder' in conditions:
            return '⛈️'
        elif 'fog' in conditions or 'mist' in conditions:
            return '🌫️'
        else:
            return '🌤️'
    
    def _format_holidays(self, data):
        """
        Format holidays section in Norwegian
        """
        lines = ["🎉 **Høytider:**"]
        
        today = data.get('today', [])
        upcoming = data.get('upcoming', [])
        
        if today:
            for holiday in today:
                template = random.choice(self.templates['holiday'])
                lines.append(f"   {template.format(holiday=holiday)}")
        
        if upcoming:
            lines.append("   Kommende:")
            for holiday in upcoming[:3]:  # Show max 3 upcoming
                lines.append(f"   • {holiday}")
        
        if not today and not upcoming:
            lines.append("   Ingen store høytider i dag")
        
        return "\n".join(lines)
    
    def _format_reminders(self, reminders):
        """
        Format reminders section in Norwegian (full version)
        """
        lines = ["📝 **Påminnelser:**"]
        
        for reminder in reminders[:5]:  # Show max 5
            time_str = reminder.get('time', '')
            text = reminder.get('text', '')
            if time_str:
                lines.append(f"   • {time_str} - {text}")
            else:
                lines.append(f"   • {text}")
        
        return "\n".join(lines)
    
    def _format_reminders_compact(self, reminders):
        """
        Format reminders section in compact form
        """
        if not reminders:
            return None
        
        items = []
        for reminder in reminders[:6]:  # Show max 6
            time_str = reminder.get('time', '')
            text = reminder.get('text', '')
            if time_str:
                items.append(f"{time_str}: {text}")
            else:
                items.append(text)
        
        return "📝 " + " | ".join(items)
    
    def _format_almanac(self, data):
        """
        Format almanac section (moon, sunrise, etc.) in Norwegian
        """
        lines = ["🌙 **Almanakk**"]
        
        # Moon phase
        if 'moon_phase' in data:
            phase = data['moon_phase']
            phase_no = self._translate_moon_phase(phase)
            emoji = self._moon_emoji(phase)
            template = random.choice(self.templates['moon'])
            lines.append(f"   {template.format(phase=phase_no, emoji=emoji)}")
        
        # Sunrise/sunset
        if 'sunrise' in data and 'sunset' in data:
            template = random.choice(self.templates['almanac'])
            lines.append(f"   {template.format(sunrise=data['sunrise'], sunset=data['sunset'])}")
        
        # Daylight duration
        if 'daylight_hours' in data:
            lines.append(f"   Dagslys: ~{data['daylight_hours']}")
        
        return "\n".join(lines)
    
    def _format_almanac_compact(self, data):
        """
        Format almanac in compact single-line form
        """
        parts = []
        
        # Moon phase
        if 'moon_phase' in data:
            phase_no = self._translate_moon_phase(data['moon_phase'])
            emoji = self._moon_emoji(data['moon_phase'])
            parts.append(f"🌙 {phase_no} {emoji}")
        
        # Sunrise/sunset
        if 'sunrise' in data and 'sunset' in data:
            parts.append(f"☀️ {data['sunrise']}-{data['sunset']}")
        
        # Daylight
        if 'daylight_hours' in data:
            parts.append(f"⏱️ {data['daylight_hours']}")
        
        return " | ".join(parts) if parts else None
    
    def _translate_moon_phase(self, phase):
        """
        Translate moon phase to Norwegian
        """
        translations = {
            'new moon': 'Nymåne',
            'waxing crescent': 'Voksende månesigd',
            'first quarter': 'Første kvarter',
            'waxing gibbous': 'Voksende måne',
            'full moon': 'Fullmåne',
            'waning gibbous': 'Minkende måne',
            'last quarter': 'Siste kvarter',
            'waning crescent': 'Minkende månesigd'
        }
        
        phase_lower = phase.lower()
        return translations.get(phase_lower, phase)
    
    def _format_aurora(self, forecast):
        """
        Format aurora forecast section
        """
        vis = forecast['visibility']
        
        lines = [
            f"🌌 **Nordlysvarsel**",
            f"",
            f"{vis['emoji']} **Aktivitet:** {vis['level']}",
            f"📊 **KP-indeks:** {forecast['kp_index']:.1f}",
            f"🎯 **Sjanse:** {forecast['probability']}%",
            f"📍 **Synlig:** {vis['areas']}",
        ]
        
        return "\n".join(lines)
    
    def _moon_emoji(self, phase):
        """
        Get moon emoji based on phase
        """
        phase = phase.lower()
        if 'new' in phase:
            return '🌑'
        elif 'waxing crescent' in phase:
            return '🌒'
        elif 'first quarter' in phase:
            return '🌓'
        elif 'waxing gibbous' in phase:
            return '🌔'
        elif 'full' in phase:
            return '🌕'
        elif 'waning gibbous' in phase:
            return '🌖'
        elif 'last quarter' in phase:
            return '🌗'
        elif 'waning crescent' in phase:
            return '🌘'
        else:
            return '🌙'
    
    def generate_demo_response(self):
        """
        Generate a demo response with sample data in Norwegian
        Using real Norwegian calendar data
        """
        # Get real Norwegian calendar data
        norwegian_data = get_todays_info()
        
        # Get real moon phase
        moon_phase, moon_emoji, _ = get_moon_phase()
        
        # Get real sunrise/sunset for Oslo
        sunrise, sunset, daylight = get_sunrise_sunset()
        
        demo_weather = {
            'conditions': 'Delvis skyet',
            'temp': 8,
            'high': 12,
            'low': 3
        }
        
        demo_holidays = {
            'today': [],
            'upcoming': ['Vårdagjevning (20. mars)', 'Langfredag (28. mars)']
        }
        
        demo_almanac = {
            'moon_phase': moon_phase,
            'sunrise': sunrise,
            'sunset': sunset,
            'daylight_hours': daylight
        }
        
        demo_reminders = [
            {'time': 'I dag', 'text': 'Sjekk Discord-meldinger'}
        ]
        
        return self.generate_full_response(
            weather_data=demo_weather,
            holiday_data=demo_holidays,
            almanac_data=demo_almanac,
            reminders=demo_reminders,
            norwegian_data=norwegian_data
        )

def create_response_generator():
    """
    Factory function to create ResponseGenerator
    """
    return ResponseGenerator()
