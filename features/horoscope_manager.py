#!/usr/bin/env python3
"""
Horoscope Manager for Inebotten
Daily horoscope for zodiac signs
"""

import random
import re
from datetime import datetime


_LEADING_INVOCATION = re.compile(
    r"^\s*(?:@inebotten\b|<@!?\d+>)\s*[:,;-]?\s*",
    re.IGNORECASE,
)
_POLITE_PREFIX = re.compile(
    r"^(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s+",
    re.IGNORECASE,
)
_NON_REQUEST_PATTERNS = (
    re.compile(r"\b(?:ikke|ikkje|not|never|don['’]t|do\s+not)\b", re.IGNORECASE),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:sa|skrev|skreiv|leste|las)\b|"
        r"^i\s+(?:said|wrote|read)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:hva\s+skjer\s+hvis|kva\s+skjer\s+om|ka\s+skjer\s+hvis|"
        r"what\s+happens\s+if|hvis|om|if)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:eksempel|example|hva\s+betyr|kva\s+tyder|hvordan\s+skriver|"
        r"korleis\s+skriv|how\s+do\s+i\s+(?:say|write)|"
        r"what\s+does\b.*\bmean)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:vurderer|tenker\s+på)\b|"
        r"^i(?:'m|\s+am)\s+(?:considering|thinking\s+about)\b",
        re.IGNORECASE,
    ),
)
_TRAILING_POLITENESS = re.compile(
    r"\s*,?\s*(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you)\s*[?!.]*$",
    re.IGNORECASE,
)
_LEADING_COURTESY_REQUEST = re.compile(
    r"^(?:(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s*"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))|"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*,?\s*"
    r"(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please))\s*,?\s*",
    re.IGNORECASE,
)
_TRAILING_COURTESY = re.compile(
    r"(?:\s*,\s*|\s+)(?:(?:om|hvis|viss)\s+du\s+kan|"
    r"(?:om|hvis|viss)\s+du\s+har\s+tid|når\s+du\s+har\s+tid|"
    r"if\s+you\s+can|if\s+you\s+have\s+(?:time|a\s+moment)|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*[?!.]*$",
    re.IGNORECASE,
)
_HOROSCOPE_PATTERNS = (
    re.compile(
        r"^(?:(?:dagens|mitt|min|today['’]s|my)\s+)?"
        r"(?:horoskop(?:et)?|horoscope)"
        r"(?:\s+(?:mitt|min|my))?(?:\s+(?:for|til))?\s+(?P<sign>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:vis(?:e)?|syn(?:e)?|fortell(?:e)?|fortel|gi|gje|sjekk(?:e)?|"
        r"show|tell|give|check)(?:\s+(?:meg|mæ|me))?\s+"
        r"(?:(?:det|the)\s+)?(?:(?:dagens|mitt|min|today['’]s|my)\s+)?"
        r"(?:horoskop(?:et)?|horoscope)(?:\s+(?:mitt|min|my))?"
        r"(?:\s+(?:for|til))?\s+(?P<sign>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:hva|kva|ka)\s+er\s+(?:(?:dagens|mitt|min)\s+)?"
        r"horoskop(?:et)?(?:\s+(?:mitt|min))?(?:\s+(?:for|til))?\s+"
        r"(?P<sign>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^what\s+is\s+(?:(?:today['’]s|my)\s+)?horoscope"
        r"(?:\s+my)?(?:\s+for)?\s+(?P<sign>.+)$",
        re.IGNORECASE,
    ),
)


def _prepare_horoscope_request(message_content):
    if not isinstance(message_content, str):
        return None
    content = _LEADING_INVOCATION.sub("", message_content, count=1).strip()
    content = _LEADING_COURTESY_REQUEST.sub("", content, count=1).strip()
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = _TRAILING_COURTESY.sub("", content).strip()
    if not content or any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _POLITE_PREFIX.sub("", content, count=1).strip()
    if any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = re.sub(r"\bwhat['’]s\b", "what is", content, flags=re.IGNORECASE)
    return content.rstrip("?!.").strip()


class HoroscopeManager:
    """
    Generates daily horoscopes
    """
    
    def __init__(self):
        self.zodiac_signs = {
            'væren': 'Aries', 'vêren': 'Aries', 'aries': 'Aries', '♈': 'Aries',
            'tyren': 'Taurus', 'taurus': 'Taurus', '♉': 'Taurus',
            'tvillingene': 'Gemini', 'tvillingane': 'Gemini', 'gemini': 'Gemini', '♊': 'Gemini',
            'krepsen': 'Cancer', 'kreften': 'Cancer', 'cancer': 'Cancer', '♋': 'Cancer',
            'løven': 'Leo', 'løva': 'Leo', 'leo': 'Leo', '♌': 'Leo',
            'jomfruen': 'Virgo', 'jomfrua': 'Virgo', 'virgo': 'Virgo', '♍': 'Virgo',
            'vekten': 'Libra', 'vekta': 'Libra', 'libra': 'Libra', '♎': 'Libra',
            'skorpionen': 'Scorpio', 'scorpio': 'Scorpio', '♏': 'Scorpio',
            'skytten': 'Sagittarius', 'sagittarius': 'Sagittarius', '♐': 'Sagittarius',
            'steinbukken': 'Capricorn', 'capricorn': 'Capricorn', '♑': 'Capricorn',
            'vannmannen': 'Aquarius', 'vassmannen': 'Aquarius', 'aquarius': 'Aquarius', '♒': 'Aquarius',
            'fiskene': 'Pisces', 'fiskane': 'Pisces', 'pisces': 'Pisces', '♓': 'Pisces',
        }
        
        self.horoscopes_no = [
            "I dag er perfekt for å ta de grepene du har utsatt!",
            "En uventet mulighet vil vise seg - grip den!",
            "Din kreativitet er på topp - bruk den!",
            "Et vennskap blir sterkere i dag.",
            "Ta deg tid til å lytte til kroppen din.",
            "En overraskelse venter rundt hjørnet!",
            "Din intuisjon er sterk - stol på den.",
            "Et gammelt problem finner sin løsning i dag.",
            "En samtale vil gi deg ny innsikt.",
            "Dag energi er perfekt for nye begynnelser.",
            "Kjærlighet er i luften - vær åpen for det!",
            "En liten gest vil gjøre stor forskjell.",
            "Din tålmodighet lønner seg i dag.",
            "En gammel venn vil ta kontakt.",
            "Ditt hardt arbeid blir lagt merke til.",
        ]
        
        self.horoscopes_en = [
            "Today is perfect for taking those steps you've been postponing!",
            "An unexpected opportunity will appear - seize it!",
            "Your creativity is at its peak - use it!",
            "A friendship grows stronger today.",
            "Take time to listen to your body.",
            "A surprise waits around the corner!",
            "Your intuition is strong - trust it.",
            "An old problem finds its solution today.",
            "A conversation will give you new insight.",
            "Today's energy is perfect for new beginnings.",
            "Love is in the air - be open to it!",
            "A small gesture will make a big difference.",
            "Your patience pays off today.",
            "An old friend will reach out.",
            "Your hard work is being noticed.",
        ]
    
    def parse_horoscope_command(self, message_content):
        """
        Parse horoscope commands
        Examples:
        - "horoskop vannmannen"
        - "horoscope aquarius"
        """
        content = _prepare_horoscope_request(message_content)
        if not content:
            return None

        for pattern in _HOROSCOPE_PATTERNS:
            match = pattern.fullmatch(content)
            if not match:
                continue
            raw_sign = match.group("sign").strip().rstrip("?!.;,: ")
            if len(raw_sign) >= 2 and (raw_sign[0], raw_sign[-1]) in {
                ('"', '"'),
                ("'", "'"),
                ("“", "”"),
                ("‘", "’"),
            }:
                raw_sign = raw_sign[1:-1].strip()
            sign_name = self.zodiac_signs.get(raw_sign.casefold())
            if sign_name:
                return {'sign': sign_name, 'sign_key': raw_sign}
        
        # If no sign found, return None (we need a sign)
        return None
    
    def get_horoscope(self, sign, lang='no'):
        """Generate horoscope for sign"""
        # Use a local generator for consistent daily output without mutating
        # process-global randomness used by other features.
        today = datetime.now().strftime('%Y%m%d')
        rng = random.Random(f"{today}_{sign}")
        
        horoscopes = self.horoscopes_no if lang == 'no' else self.horoscopes_en
        text = rng.choice(horoscopes)
        
        # Generate ratings
        love = rng.randint(3, 10)
        career = rng.randint(3, 10)
        health = rng.randint(3, 10)
        luck = rng.randint(3, 10)
        
        return {
            'sign': sign,
            'text': text,
            'love': love,
            'career': career,
            'health': health,
            'luck': luck,
        }
    
    def format_horoscope(self, data, lang='no'):
        """Format horoscope for display"""
        if not data:
            return None
        
        sign = data['sign']
        sign_emojis = {
            'Aries': '♈', 'Taurus': '♉', 'Gemini': '♊', 'Cancer': '♋',
            'Leo': '♌', 'Virgo': '♍', 'Libra': '♎', 'Scorpio': '♏',
            'Sagittarius': '♐', 'Capricorn': '♑', 'Aquarius': '♒', 'Pisces': '♓',
        }
        emoji = sign_emojis.get(sign, '⭐')
        
        if lang == 'no':
            lines = [
                f"{emoji} **Horoskop: {sign}**",
                "",
                f"🔮 {data['text']}",
                "",
                f"💕 Kjærlighet: {data['love']}/10",
                f"💼 Karriere: {data['career']}/10",
                f"🏥 Helse: {data['health']}/10",
                f"🍀 Lykke: {data['luck']}/10",
            ]
        else:
            lines = [
                f"{emoji} **Horoscope: {sign}**",
                "",
                f"🔮 {data['text']}",
                "",
                f"💕 Love: {data['love']}/10",
                f"💼 Career: {data['career']}/10",
                f"🏥 Health: {data['health']}/10",
                f"🍀 Luck: {data['luck']}/10",
            ]
        
        return "\n".join(lines)
    
    def get_available_signs(self, lang='no'):
        """Get list of available signs"""
        if lang == 'no':
            return "♈ Væren, ♉ Tyren, ♊ Tvillingene, ♋ Krepsen, ♌ Løven, ♍ Jomfruen, ♎ Vekten, ♏ Skorpionen, ♐ Skytten, ♑ Steinbukken, ♒ Vannmannen, ♓ Fiskene"
        else:
            return "♈ Aries, ♉ Taurus, ♊ Gemini, ♋ Cancer, ♌ Leo, ♍ Virgo, ♎ Libra, ♏ Scorpio, ♐ Sagittarius, ♑ Capricorn, ♒ Aquarius, ♓ Pisces"


def parse_horoscope_command(message_content):
    """Convenience function"""
    manager = HoroscopeManager()
    return manager.parse_horoscope_command(message_content)
