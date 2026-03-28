#!/usr/bin/env python3
"""
Inebotten Personality Module
Makes the bot feel like a friendly chat homie, not a robot
"""

import random
from datetime import datetime


class InebottenPersonality:
    """
    Gives Inebotten a friendly, helpful personality
    """
    
    def __init__(self):
        self.greetings = [
            "Hei! 👋",
            "Halla! 😊",
            "Heisann! ✨",
            "Yo! 🙌",
            "Hei på deg! 🌟",
        ]
        
        self.signoffs = [
            "Ha en fin dag! 🌈",
            "Ta vare! 💫",
            "Kos deg videre! 🎈",
            "Snakkes! 👋",
            "Ha det! ✌️",
        ]
        
        self.enthusiasm = [
            "Gleder meg til å hjelpe deg!",
            "Jeg er på saken!",
            "La oss få dette til å skje!",
            "Dette blir bra!",
        ]
        
        self.acknowledgments = [
            "Skjønner! 👍",
            "Følger med! ✍️",
            "Notert! 📝",
            "Fikk det! ✅",
        ]
        
        self.weather_comments = {
            'sol': ["Nydelig vær ute! ☀️ Perfekt for en tur!", "Endelig sol! 🌞", "Herlig med sol! ☀️"],
            'regn': ["Husk paraply! 🌧️ Eller kanskje en koselig dag inne?", "Typisk norsk vær... 🌧️", "Regn - da er det godt å være inne! ☕"],
            'snø': ["Vinteridyll! ❄️", "Snø ute - ta på varme klær! 🧣", "Perfekt skiføre kanskje? ⛷️"],
            'tåke': ["Tåkete i dag... 🌫️ Mystisk stemning!", "Litt grått ute, men det letter kanskje? 🌫️"],
            'skyet': ["Overskyet, men det kan forandre seg! ⛅", "Litt grått, men fint for innekos! ☁️"],
        }
    
    def get_greeting(self):
        """Get a random friendly greeting"""
        return random.choice(self.greetings)
    
    def get_signoff(self):
        """Get a random friendly signoff"""
        return random.choice(self.signoffs)
    
    def get_enthusiasm(self):
        """Get enthusiastic response"""
        return random.choice(self.enthusiasm)
    
    def get_acknowledgment(self):
        """Get acknowledgment phrase"""
        return random.choice(self.acknowledgments)
    
    def comment_on_weather(self, condition):
        """Make a natural comment about weather"""
        condition_lower = condition.lower()
        
        for key, comments in self.weather_comments.items():
            if key in condition_lower:
                return random.choice(comments)
        
        return "Håper været holder seg! 🌤️"
    
    def format_event_created(self, title, date, time=None):
        """Natural response when event is created"""
        time_str = f" kl {time}" if time else ""
        
        responses = [
            f"Supert! Jeg har lagt til **{title}** den {date}{time_str}! 📅✨",
            f"Notert! **{title}** {date}{time_str} er i kalenderen! 🎯",
            f"Flott! Da er **{title}** booket den {date}{time_str}! 🎉",
        ]
        
        return random.choice(responses)
    
    def format_reminder_created(self, text):
        """Natural response when reminder is added"""
        responses = [
            f"Huskelapp lagt til: *{text}* ⬜",
            f"Notert! Jeg minner deg på: {text} 📝",
            f"Fikk det! **{text}** står på lista! ✅",
        ]
        return random.choice(responses)
    
    def format_dashboard(self, date_info, weather=None, events=None, reminders=None):
        """
        Format dashboard in a conversational, friendly way
        Instead of rigid sections, make it flow like a friend talking
        """
        parts = []
        
        # Friendly opening
        hour = datetime.now().hour
        if hour < 12:
            parts.append("God morgen! ☀️")
        elif hour < 18:
            parts.append("God ettermiddag! 👋")
        else:
            parts.append("God kveld! 🌙")
        
        # Date and name day (conversational)
        parts.append(f"I dag er det {date_info['formatted_date']}")
        
        if date_info.get('navnedag'):
            names = " og ".join(date_info['navnedag'])
            parts.append(f"Gratulerer med dagen til {names}! 🎂")
        
        if date_info.get('flaggdag'):
            parts.append(f"Og ikke glem: {date_info['flaggdag']} 🇳🇴")
        
        # Weather with personality
        if weather:
            parts.append(f"\nVæret i dag? {weather['condition']}, rundt {weather['temp']}°C.")
            parts.append(self.comment_on_weather(weather['condition']))
        
        # Events (conversational)
        if events:
            parts.append(f"\nPå agendaen:")
            for event in events[:3]:
                time_str = f" kl {event['time']}" if event.get('time') else ""
                parts.append(f"• **{event['title']}**{time_str}")
        
        # Reminders (conversational)
        if reminders:
            parts.append(f"\nHusk også:")
            for i, reminder in enumerate(reminders[:3], 1):
                parts.append(f"{i}. {reminder['text']}")
        
        # Signoff with helpful hints
        parts.append(f"\n{self.get_signoff()}")
        
        if not events and not reminders:
            parts.append(f"\n💡 *Tips: Nevn noe som skjer så legger jeg det til! F.eks. \"@inebotten kamp i kveld kl 20\"*")
        else:
            parts.append(f"\n💡 *Vil du legge til noe mer? Bare si ifra!*")
        
        return "\n".join(parts)
    
    def format_helpful_hint(self):
        """Random helpful hint"""
        hints = [
            "Spør meg om været, skoleferier, eller nordlys!",
            "Jeg kan huske bursdager også - bare si \"bursdag 15.05\"!",
            "Skriv \"ferdig 1\" for å fullføre en påminnelse!",
            "Si \"slett arrangement 1\" for å fjerne noe!",
        ]
        return random.choice(hints)


# Singleton instance
_personality = None

def get_personality():
    """Get the personality instance"""
    global _personality
    if _personality is None:
        _personality = InebottenPersonality()
    return _personality
