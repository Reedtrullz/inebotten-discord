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


# SIMPLIFIED personality for small models
def get_system_prompt(
    user_name: str = "",
    user_context: Dict = None,
    conversation_history: List = None,
    conversation_context: List = None,
    time_of_day: str = "day",
    style: ResponseStyle = ResponseStyle.CASUAL
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
- Snakk som en venn, ikke en manual
- Bruk Discord Markdown:
  * **fet skrift** for viktige ting
  * Bruk formatet [Tekst](URL) for lenker, men **kun hvis du er 100% sikker på at URL-en er ekte**.
  * Hvis du er usikker på en URL, skriv bare navnet på tjenesten uten lenke.
- VERIFISERTE LENKER (bruk disse):
  * Pollen: [Pollenvarsel](https://www.naaf.no)
  * Vær: [Yr](https://www.yr.no)
  * Bålforbud: [Miljødirektoratet](https://www.miljodirektoratet.no/balforbud)
  * Navnedager: [Navnedag.no](https://www.navnedag.no)
  * Skred/Naturfare: [Varsom](https://www.varsom.no)
- Bruk emojis naturlig for å skape stemning ✨
- Ikke list opp kommandoer med mindre noen spør spesifikt"""

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
