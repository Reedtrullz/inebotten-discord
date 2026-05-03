#!/usr/bin/env python3
"""
Inebotten Personality Module
Den velinformerte vennen - en digital følgesvenn for nordmenn
"""

import random
from datetime import datetime


class InebottenPersonality:
    """
    Inebotten's personality: "Den velinformerte vennen"
    
    En hjelpsom, varm og kunnskapsrik følgesvenn som:
    - Vet mye, men skryter ikke
    - Alltid er behjelpelig, aldri påtrengende
    - Har meninger, men respekterer dine
    - Bruker humor naturlig, ikke påtvunget
    """
    
    def __init__(self):
        # Core identity
        self.name = "Inebotten"
        self.nickname = "Ine"
        
        # Greetings - varierer basert på kontekst
        self.greetings = {
            "morning": [
                "God morgen! ☀️",
                "Morn! Håper du får en fin start på dagen!",
                "God morgen! Klar for en ny dag?",
                "Hei! Godt å se deg igjen! 👋",
            ],
            "day": [
                "Hei! 👋",
                "Heisann!",
                "Halla! Hva skjer?",
                "Hei på deg!",
            ],
            "evening": [
                "God kveld! 🌙",
                "Kvelden! Håper dagen har vært bra!",
                "God kveld! Klar for å slappe av?",
            ],
            "returning": [
                "Velkommen tilbake! 🎉",
                "Hei igjen! Godt å se deg!",
                "Morn! Lenge siden sist!",
            ]
        }
        
        # Signoffs - varm og personlig
        self.signoffs = [
            "Ha en fin dag! 🌈",
            "Ta vare! 💫",
            "Kos deg videre! 🎈",
            "Snakkes! 👋",
            "Ha det! Si fra hvis du trenger noe! ✌️",
            "Lykke til videre! 🍀",
        ]
        
        # Acknowledgments
        self.acknowledgments = [
            "Skjønner! 👍",
            "Følger med! ✍️",
            "Notert! 📝",
            "Fikk det! ✅",
            "Supert! 🎯",
        ]
        
        # Weather comments - personlige og kontekst-aware
        self.weather_comments = {
            'sol': [
                "Nydelig vær ute! ☀️ Perfekt for en tur!",
                "Endelig sol! 🌞 Få med deg litt D-vitamin!",
                "Herlig med sol! ☀️ En god dag for utendørs!",
                "Sol! Kanskje en kaffepause ute? ☀️☕",
            ],
            'regn': [
                "Husk paraply! 🌧️ Eller kanskje en koselig dag inne?",
                "Typisk norsk vær... 🌧️ Perfekt unnskyldning for å slappe av!",
                "Regn - da er det godt å være inne! ☕ Kanskje med en god bok?",
                "Grått ute, men det kan være ganske koselig det også! 🌧️",
            ],
            'snø': [
                "Vinteridyll! ❄️",
                "Snø ute - ta på varme klær! 🧣",
                "Perfekt skiføre kanskje? ⛷️ Eller bare koselig inne!",
                "Snø! Norge på sitt vakreste! ❄️",
            ],
            'tåke': [
                "Tåkete i dag... 🌫️ Mystisk stemning!",
                "Litt grått ute, men det letter kanskje? 🌫️",
                "Tåke gir en egen ro, på en måte! 🌫️",
            ],
            'skyet': [
                "Overskyet, men det kan forandre seg! ⛅",
                "Litt grått, men fint for innekos! ☁️",
                "Ingen sol i dag, men det er helt greit! ⛅",
            ],
            'vind': [
                "Blåser godt i dag! 💨 Hold på hatten!",
                "Vindfullt - kanskje ikke paraply-vær! 💨",
            ]
        }
        
        # Celebration messages
        self.celebrations = [
            "Woohoo! 🎉",
            "Yay! 🎊",
            "Kjempebra! 🌟",
            "Perfekt! ✨",
        ]
        
        # Empathy for when user seems stressed/down
        self.empathy = [
            "Høres ut som en tøff dag. Vil du snakke om det?",
            "Skjønner at det er mye nå. Ta en ting av gangen!",
            "Det høres hektisk ut. Husk å puste! 💙",
        ]
    
    def get_greeting(self, time_of_day=None, returning_user=False):
        """Get context-appropriate greeting"""
        if returning_user:
            return random.choice(self.greetings["returning"])
        
        if time_of_day is None:
            hour = datetime.now().hour
            if 5 <= hour < 12:
                time_of_day = "morning"
            elif 12 <= hour < 17:
                time_of_day = "day"
            else:
                time_of_day = "evening"
        
        return random.choice(self.greetings.get(time_of_day, self.greetings["day"]))
    
    def get_signoff(self):
        """Get random friendly signoff"""
        return random.choice(self.signoffs)
    
    def get_acknowledgment(self):
        """Get acknowledgment phrase"""
        return random.choice(self.acknowledgments)
    
    def get_celebration(self):
        """Get celebration phrase"""
        return random.choice(self.celebrations)
    
    def comment_on_weather(self, condition):
        """Make a natural comment about weather"""
        condition_lower = condition.lower()
        
        for key, comments in self.weather_comments.items():
            # Use word boundaries to avoid matching substrings in condition names
            if re.search(rf"\b{re.escape(key)}\b", condition_lower):
                return random.choice(comments)
        
        return "Håper været holder seg! 🌤️"
    
    def format_event_created(self, title, date, time=None):
        """Natural response when event is created"""
        time_str = f" kl {time}" if time else ""
        
        responses = [
            f"Supert! Jeg har lagt til **{title}** den {date}{time_str}! 📅✨",
            f"Notert! **{title}** {date}{time_str} er i kalenderen! 🎯",
            f"Flott! Da er **{title}** booket den {date}{time_str}! 🎉",
            f"Fikk det! **{title}** står på agendaen {date}{time_str}! ✅",
        ]
        
        return random.choice(responses)
    
    def format_reminder_created(self, text):
        """Natural response when reminder is added"""
        responses = [
            f"Huskelapp lagt til: *{text}* 📝",
            f"Notert! Jeg minner deg på: {text} ⬜",
            f"Fikk det! **{text}** står på lista! ✅",
            f"Lagt til! Jeg sier ifra om {text}! 🔔",
        ]
        return random.choice(responses)
    
    def format_task_completed(self, text):
        """Celebrate completing a task"""
        responses = [
            f"Bra jobba! ✅ **{text}** er fullført! {self.get_celebration()}",
            f"Ferdig! 🎉 **{text}** - check! {self.get_celebration()}",
            f"Supert! ✅ **{text}** er gjort! En ting mindre å tenke på!",
            f"Woohoo! **{text}** er i boks! 🌟",
        ]
        return random.choice(responses)
    
    def format_dashboard(self, date_info, weather=None, events=None, reminders=None):
        """
        Format dashboard in a conversational, friendly way
        """
        parts = []
        
        # Time-appropriate greeting
        hour = datetime.now().hour
        if 5 <= hour < 12:
            parts.append("God morgen! ☀️")
        elif 12 <= hour < 17:
            parts.append("God ettermiddag! 👋")
        else:
            parts.append("God kveld! 🌙")
        
        # Date and name day (conversational)
        parts.append(f"I dag er det {date_info['formatted_date']}")
        
        if date_info.get('navnedag'):
            names = " og ".join(date_info['navnedag'][:2])
            parts.append(f"Vi feirer {names} i dag! 🎂")
        
        if date_info.get('flaggdag'):
            parts.append(f"{date_info['flaggdag']} 🇳🇴")
        
        # Weather with personality
        if weather:
            parts.append(f"\nVæret? {weather['condition']}, rundt {weather['temp']}°C.")
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
                status = "✅" if reminder.get('completed') else "⬜"
                parts.append(f"{status} {reminder['text']}")
        
        # Signoff with helpful hints
        parts.append(f"\n{self.get_signoff()}")
        
        if not events and not reminders:
            parts.append(f"\n💡 *Nevn noe som skjer så legger jeg det til! F.eks. \"@inebotten kamp i kveld kl 20\"*")
        
        return "\n".join(parts)
    
    def format_helpful_hint(self):
        """Random helpful hint"""
        hints = [
            "Spør meg om været, skoleferier, eller nordlys!",
            "Jeg kan huske bursdager også - bare si \"bursdag 15.05\"!",
            "Skriv \"ferdig 1\" for å fullføre en påminnelse!",
            "Si \"slett arrangement 1\" for å fjerne noe!",
            "Jeg skjønner naturlig språk - prøv \"møte i morgen kl 14\"!",
        ]
        return random.choice(hints)
    
    def format_error(self, context="general"):
        """Friendly error message"""
        errors = {
            "general": [
                "Hmm, skjønte ikke helt det der. Kan du forklare på en annen måte? 🤔",
                "Oi, ble litt forvirra. Hva var det du lurte på?",
                "Beklager, den gikk over hodet på meg. Si det en gang til?",
            ],
            "calendar": [
                "Skjønte ikke helt når det skal skje. Prøv \"i morgen kl 14\" eller \"15.05\"!",
                "Usikker på datoen der. Kan du si det med dag eller dato?",
            ],
            "weather": [
                "Fikk ikke tak i været akkurat nå. Prøv igjen om litt!",
                "Værmeldingen streiker! Prøv å spør om en større by!",
            ],
        }
        return random.choice(errors.get(context, errors["general"]))
    
    def respond_to_dialect(self, content):
        """
        Check if content contains Norwegian dialect expressions and return
        an appropriate response. Returns None if no dialect words found.
        """
        content_lower = content.lower()
        import re
        
        # Check for dialect expressions (use word boundaries)
        if re.search(r"\bkjekt\b", content_lower):
            return random.choice([
                "Det var kjekt å høre! 😊",
                "Kjekt at du sier det!",
                "Det høres kjekt ut!",
            ])
        
        if re.search(r"\btøft\b", content_lower):
            return random.choice([
                "Skikkelig tøft! 👍",
                "Det var tøft!",
                "Tøft å høre!",
            ])
        
        if re.search(r"\brått\b", content_lower):
            return random.choice([
                "Helt rått! 🎉",
                "Det var rått!",
                "Rått! Kjempebra!",
            ])
        
        if re.search(r"\bskikkelig\b", content_lower):
            return random.choice([
                "Skikkelig bra! 👍",
                "Det var skikkelig fint!",
                "Skikkelig!",
            ])
        
        return None


# Singleton instance
_personality = None


def get_personality():
    """Get the personality instance"""
    global _personality
    if _personality is None:
        _personality = InebottenPersonality()
    return _personality


def get_greeting(time_of_day=None, returning_user=False):
    """Convenience function to get greeting"""
    return get_personality().get_greeting(time_of_day, returning_user)


def get_signoff():
    """Convenience function to get signoff"""
    return get_personality().get_signoff()


def get_acknowledgment():
    """Convenience function to get acknowledgment"""
    return get_personality().get_acknowledgment()


# Legacy compatibility
def get_fallback_response(intent="general"):
    """Legacy fallback response function"""
    fallbacks = {
        "general": [
            "Hehe, skjønte ikke helt hva du mente der. Kan du forklare på en annen måte? 🤔",
            "Hmm, ble litt forvirra. Hva var det du lurte på?",
            "Oi, den gikk over hodet på meg. Si det en gang til?",
        ],
        "weather": [
            "Skal sjekke været for deg!",
            "La meg se hva værmeldingen sier...",
        ],
        "calendar": [
            "Sjekker hva som står i kalenderen...",
            "La meg se på planene dine...",
        ],
    }
    return random.choice(fallbacks.get(intent, fallbacks["general"]))


if __name__ == "__main__":
    # Test
    print("=== Testing Inebotten Personality ===\n")
    
    p = get_personality()
    
    print("Greetings:")
    print(f"  Morning: {p.get_greeting('morning')}")
    print(f"  Day: {p.get_greeting('day')}")
    print(f"  Evening: {p.get_greeting('evening')}")
    print(f"  Returning: {p.get_greeting(returning_user=True)}")
    
    print(f"\nSignoff: {p.get_signoff()}")
    print(f"Acknowledgment: {p.get_acknowledgment()}")
    
    print(f"\nWeather comments:")
    for condition in ['sol', 'regn', 'snø']:
        print(f"  {condition}: {p.comment_on_weather(condition)}")
    
    print(f"\nEvent created: {p.format_event_created('Møte', '25.03.2026', '14:00')}")
