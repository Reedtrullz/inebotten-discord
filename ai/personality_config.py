#!/usr/bin/env python3
"""
Personality Configuration for Inebotten
Optimized for small models like Llama 3.2 3B
"""

from enum import Enum
from typing import Dict, List, Optional
import random


class ResponseStyle(Enum):
    """Response style variations"""
    CASUAL = "casual"
    WARM = "warm"
    WITTY = "witty"


INTENT_DESCRIPTIONS = {
    "help": "brukeren ber om hjelp/kommandoer",
    "status": "brukeren ber om bot-status",
    "profile": "brukeren vil endre profil/status",
    "calendar_item": "brukeren vil legge til noe i kalenderen",
    "search": "brukeren vil søke på nettet",
    "ai_chat": "brukeren vil bare chatte",
    "calendar_help": "brukeren ber om kalenderhjelp",
    "calendar_list": "brukeren vil se kalenderlisten",
    "calendar_sync": "brukeren vil synkronisere kalenderen",
    "calendar_delete": "brukeren vil slette en kalenderhendelse",
    "calendar_complete": "brukeren vil markere noe som fullført",
    "calendar_edit": "brukeren vil redigere en kalenderhendelse",
    "calendar_clear": "brukeren vil tømme kalenderen",
    "poll_create": "brukeren vil lage en avstemning",
    "poll_vote": "brukeren vil stemme på en avstemning",
    "countdown": "brukeren vil ha en nedtelling",
    "watchlist": "brukeren vil håndtere en watchlist",
    "word_of_day": "brukeren vil ha dagens ord",
    "quote": "brukeren vil ha et sitat",
    "aurora": "brukeren vil ha nordlysvarsel",
    "school_holidays": "brukeren vil ha informasjon om skoleferie",
    "price": "brukeren vil ha prisinformasjon",
    "horoscope": "brukeren vil ha horoskop",
    "compliment": "brukeren vil ha et kompliment",
    "calculator": "brukeren vil ha en utregning",
    "shorten_url": "brukeren vil forkorte en URL",
    "daily_digest": "brukeren vil ha daglig oppsummering",
    "dashboard": "brukeren vil ha en oversikt",
    "set_location": "brukeren vil sette sin lokasjon",
}


# SIMPLIFIED personality for small models
def get_system_prompt(
    user_name: str = "",
    user_context: Dict = None,
    conversation_history: List = None,
    conversation_context: List = None,
    time_of_day: str = "day",
    style: ResponseStyle = ResponseStyle.CASUAL,
    routed_intent: str = None,
) -> str:
    """
    Generate a SIMPLE system prompt optimized for Llama 3.2 3B
    Small models need clear, direct instructions - not complex structures
    """
    
    # Handle both parameter names
    if conversation_context is not None and conversation_history is None:
        conversation_history = conversation_context
    
    # Base prompt - SIMPLE and NATURAL
    prompt = """Du er Ine. Snakk norsk. Vær vennlig.

EKSEMPLER:
Q: Hei!
A: Hei! 👋 Hvordan går det?

Q: Hvem er du?
A: Jeg er **Ine**, din personlige assistent! 📅 Jeg hjelper deg med å holde styr på alt fra møter til bursdager.

Q: Hvor finner jeg info om bålforbud?
A: Du kan sjekke de nyeste reglene hos [Miljødirektoratet](https://www.miljodirektoratet.no/balforbud). Husk at det er **strengt forbudt** i tørre perioder! 🔥

Q: Hvordan har du det?
A: Jeg har det helt strålende! 😊 Alt i orden med deg?

REGLER:
- Svar alltid på norsk
- Vær vennlig og naturlig
- DIN VIKTIGSTE OPPGAVE ER Å OPPFATE HVA BRUKEREN VIL GJØRE OG UTFØRE HANDLINGER.
- Hvis brukeren vil planlegge noe, lagre en avtale, eller minne seg selv på noe, SKAL du inkludere:
  `[SAVE_EVENT: Tittel | Dato | Tid]`
  *VIKTIG: Tittelen skal kun inneholde HVA som skjer. Ikke inkluder ord som "lørdag", "på kveld", "kl 12" eller andre tidspunkter i selve tittelen.*
- Hvis brukeren vil ha en oversikt over dagen, været, eller planen sin, inkluder:
  `[SHOW_DASHBOARD]`
- Du kan også bruke JSON-format:
  {"action": "SAVE_EVENT", "title": "Møte med Ola", "date": "01.05.2025", "time": "14:00"}
  {"action": "SHOW_DASHBOARD"}
- Handlingstags må stå på en egen linje eller på slutten av meldingen. De blir fjernet før brukeren ser dem.
- Bruk Discord Markdown:
  * **fet skrift** for viktige ting
  * Bruk formatet [Tekst](URL) for lenker, men **kun hvis du er 100% sikker på at URL-en er ekte**.
- Bruk emojis naturlig for å skape stemning ✨
- Ikke list opp kommandoer med mindre noen spør spesifikt"""

    # Add intent routing information if available
    if routed_intent:
        intent_value = routed_intent.value if hasattr(routed_intent, "value") else str(routed_intent)
        description = INTENT_DESCRIPTIONS.get(intent_value, f"utføre handling: {intent_value}")
        prompt += f"""
SYSTEMINTENT: {intent_value}

Systemet har analysert meldingen og bestemt at brukeren vil: {description}
Hvis dette stemmer, fortsett med handlingen. Hvis ikke, svar naturlig.
"""

    # Add user name if available (simple format)
    if user_name:
        prompt += f"\nDu snakker med: {user_name}\n"
    
    # Add minimal user context (handle both dict and string formats)
    if user_context:
        if isinstance(user_context, dict):
            # Dict format
            context_parts = []
            if user_context.get("location"):
                context_parts.append(f"Bor i {user_context['location']}")
            if user_context.get("interests"):
                interests = ", ".join(user_context["interests"][:2])
                context_parts.append(f"Liker {interests}")
            
            if context_parts:
                prompt += f"Du vet: {' | '.join(context_parts)}\n"
        elif isinstance(user_context, str) and user_context.strip():
            # String format (from format_context_for_prompt)
            prompt += f"Du vet: {user_context}\n"
    
    # Add conversation history
    if conversation_history:
        if isinstance(conversation_history, list) and len(conversation_history) > 0:
            prompt += "\nNylig samtale:\n"
            for msg in conversation_history[-3:]:  # Only last 3 for small model
                if isinstance(msg, dict):
                    role = "Bruker" if msg.get('role') == 'user' else "Deg"
                    content = msg.get('content', '')[:100]  # Truncate long messages
                    prompt += f"{role}: {content}\n"
        elif isinstance(conversation_history, str) and conversation_history.strip():
            prompt += f"\nNylig samtale:\n{conversation_history}\n"
    
    # Simple time-based greeting suggestion
    if time_of_day == "morning":
        prompt += "\nDet er morgen - vær fresh og positiv! ☀️\n"
    elif time_of_day == "evening":
        prompt += "\nDet er kveld - vær avslappet og rolig 🌙\n"
    
    return prompt


def get_greeting(user_name: str = "", time_since_last: str = "", last_topic: str = "") -> str:
    """Get a simple, natural greeting"""
    greetings = [
        "Hei! 👋",
        "Heisann!",
        "Halla!",
        "Hei på deg!",
        "God dag!",
    ]
    
    if user_name and time_since_last:
        return f"Hei {user_name}! Godt å se deg igjen! 👋"
    
    return random.choice(greetings)


def get_time_based_greeting() -> str:
    """Get greeting based on time of day"""
    from datetime import datetime
    hour = datetime.now().hour
    
    if 5 <= hour < 12:
        return random.choice(["God morgen! ☀️", "Morn!", "God formiddag!"])
    elif 12 <= hour < 17:
        return random.choice(["God dag! 👋", "Hei!", "God ettermiddag!"])
    elif 17 <= hour < 22:
        return random.choice(["God kveld! 🌙", "Kvelden!", "God kveld!"])
    else:
        return random.choice(["God natt! 🌙", "Hei! Sent ute?"])


def get_farewell() -> str:
    """Get simple farewell"""
    return random.choice([
        "Ha det! 👋",
        "Snakkes!",
        "Ha en fin dag!",
        "Ta vare!",
    ])


def get_confused_response() -> str:
    """Simple confusion response"""
    return random.choice([
        "Skjønte ikke helt. Kan du si det på en annen måte? 🤔",
        "Hmm, ble litt forvirra. Hva mener du?",
        "Oi, den skjønte jeg ikke. Si det igjen?",
    ])


def get_gratitude_response() -> str:
    """Simple gratitude response"""
    return random.choice([
        "Bare hyggelig! 😊",
        "Ingen årsak!",
        "Så lite!",
    ])


def get_fallback_response(intent: str = "general") -> str:
    """Fallback when AI fails"""
    fallbacks = {
        "general": [
            "Skjønte ikke helt. Kan du forklare? 🤔",
            "Hmm, prøv å si det på en annen måte?",
        ],
        "weather": [
            "Skal sjekke været!",
            "La meg se...",
        ],
        "calendar": [
            "Sjekker kalenderen...",
            "Ser på planene dine...",
        ],
    }
    return random.choice(fallbacks.get(intent, fallbacks["general"]))


# For backward compatibility - simplified personality class
class InebottenPersonality:
    """Simplified personality class"""
    NAME = "Inebotten"
    NICKNAME = "Ine"


# Legacy compatibility
ResponseStyle = ResponseStyle


if __name__ == "__main__":
    # Test
    print("=== Simplified System Prompt ===\n")
    prompt = get_system_prompt(
        user_name="Kari",
        user_context={"location": "Bergen", "interests": ["fotball"]},
        time_of_day="morning"
    )
    print(prompt)
    print("\n" + "="*50)
    print(f"\nGreeting: {get_greeting()}")
    print(f"Time-based: {get_time_based_greeting()}")
