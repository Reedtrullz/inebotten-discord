#!/usr/bin/env python3
"""
Compliments and Roasting Manager for Inebotten
Generates compliments and friendly roasts
"""

import random
import re


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
_TARGET = r"(?:<@!?\d+>|@[\w.-]+|meg|mæ|me)"
_COMPLIMENT_PATTERNS = (
    re.compile(
        rf"^(?:kompliment(?:er)?|compliment|praise|ros|rose)"
        rf"(?:\s+(?:til|to))?\s*(?P<target>{_TARGET})?$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:gi|gje|give)\s+(?:(?P<before>{_TARGET})\s+)?"
        rf"(?:et|eit|en|a)\s+(?:(?:fint|fint lite|nice|vennlig|vennleg|friendly)\s+)?"
        rf"(?:kompliment|compliment)(?:\s+(?:til|to)\s+(?P<after>{_TARGET}))?$",
        re.IGNORECASE,
    ),
)
_ROAST_PATTERNS = (
    re.compile(
        rf"^(?:roast|roaste|diss)\s*(?P<target>{_TARGET})?$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:gi|gje|give)\s+(?P<target>{_TARGET})\s+"
        rf"(?:en|ein|a)\s+(?:(?:vennlig|vennleg|friendly)\s+)?roast$",
        re.IGNORECASE,
    ),
)


def _prepare_compliment_request(message_content):
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
    return content.rstrip("?!.").strip()


class ComplimentsManager:
    """
    Generates compliments and playful roasts
    """
    
    def __init__(self):
        self.compliments_no = [
            "Du lyser opp rommet du er i! ✨",
            "Du er mer unik enn en enhjørning! 🦄",
            "Hvis du var en taco, ville du vært en supreme! 🌮",
            "Du er så kul at isbjørner fryser! 🐻‍❄️",
            "Din intelligens er høyere enn Trondheim! 🏔️",
            "Du er den karamellen i pose med seigmenn! 🍬",
            "Hvis god stemning var penger, ville du vært milliardær! 💰",
            "Du er som wifi - alle vil ha deg rundt! 📶",
            "Din latter er mer smittsom enn forkjølelse! 😄",
            "Du er søtere enn brunost på vaffel! 🧇",
            "Hvis du var en app, ville du hatt 5 stjerner! ⭐",
            "Du gjør hver dag litt bedre! ☀️",
            "Du er viktigere enn du tror! 💎",
            "Din tilstedeværelse er en gave! 🎁",
            "Du er gull verdt! 🏆",
        ]
        
        self.compliments_en = [
            "You light up every room you enter! ✨",
            "You're more unique than a unicorn! 🦄",
            "If you were a taco, you'd be supreme! 🌮",
            "You're so cool that polar bears get chills! 🐻‍❄️",
            "You're the caramel in a bag of gummy bears! 🍬",
            "If good vibes were money, you'd be a billionaire! 💰",
            "You're like wifi - everyone wants you around! 📶",
            "Your laugh is more contagious than a cold! 😄",
            "If you were an app, you'd have 5 stars! ⭐",
            "You make every day a little better! ☀️",
            "You're more important than you know! 💎",
            "Your presence is a gift! 🎁",
            "You're worth your weight in gold! 🏆",
        ]
        
        self.roasts_no = [
            "Du er som en sky - fin å se på, men ikke så nyttig når det regner! ☁️",
            "Hvis du var en spicy måltid, ville du vært mayonnaise! 🌶️❌",
            "Du er så treg at du ville kommet sist i en konkurranse med snegler! 🐌",
            "Din energi er som en telefon på 1% - snart død! 📱",
            "Du er som en gresskar - rund og full av luft! 🎃",
            "Hvis dumhet var strøm, ville du lyst opp hele Norge! 💡",
            "Du er så forsiktig at du sjekker været før du går ut i dusjen! 🚿",
            "Din tankeprosess er tregere enn internett på 56k! 💾",
            "Du er som en banan - gul og bøyer deg lett! 🍌",
            "Hvis late var en sport, ville du tatt gull! 🥇",
        ]
        
        self.roasts_en = [
            "You're like a cloud - nice to look at, but not so useful when it rains! ☁️",
            "If you were a spicy dish, you'd be mayonnaise! 🌶️❌",
            "You're so slow you'd come last in a race with snails! 🐌",
            "Your energy is like a phone at 1% - about to die! 📱",
            "You're like a pumpkin - round and full of hot air! 🎃",
            "If laziness was a sport, you'd take gold! 🥇",
            "You're so careful you check the weather before showering! 🚿",
            "Your thought process is slower than 56k internet! 💾",
            "You're like a banana - yellow and easily bent! 🍌",
        ]
    
    def parse_compliment_command(self, message_content):
        """
        Parse compliment/roast commands
        Examples:
        - "kompliment @username"
        - "compliment @username"
        - "roast @username"
        - "diss @username"
        """
        content = _prepare_compliment_request(message_content)
        if not content:
            return None

        for pattern in _COMPLIMENT_PATTERNS:
            match = pattern.fullmatch(content)
            if match:
                target = next(
                    (value for value in match.groupdict().values() if value),
                    None,
                )
                return {
                    'action': 'compliment',
                    'user': self._target_to_user(target),
                }

        for pattern in _ROAST_PATTERNS:
            match = pattern.fullmatch(content)
            if match:
                return {
                    'action': 'roast',
                    'user': self._target_to_user(match.group("target")),
                }
        
        return None

    def _target_to_user(self, target):
        """Convert a bounded target token while preserving the user's case."""
        if not target or target.casefold() in {"meg", "mæ", "me"}:
            return None
        discord_match = re.fullmatch(r'<@!?(\d+)>', target)
        if discord_match:
            return "<@" + discord_match.group(1) + ">"
        if target.startswith("@"):
            return target[1:]
        return None
    
    def _extract_user(self, message_content):
        """Extract mentioned username"""
        # Look for Discord mention format
        match = re.search(r'<@!?(\d+)>', message_content)
        if match:
            return "<@" + match.group(1) + ">"

        # Look for @username after checking Discord's numeric form.
        match = re.search(r'@([\w.-]+)', message_content)
        if match:
            return match.group(1)
        
        return None
    
    def get_compliment(self, lang='no'):
        """Get a random compliment"""
        compliments = self.compliments_no if lang == 'no' else self.compliments_en
        return random.choice(compliments)
    
    def get_roast(self, lang='no'):
        """Get a random friendly roast"""
        roasts = self.roasts_no if lang == 'no' else self.roasts_en
        return random.choice(roasts)
    
    def format_compliment(self, text, user=None, lang='no'):
        """Format compliment with optional user mention"""
        if user:
            if lang == 'no':
                return f"💫 {user}, {text}"
            else:
                return f"💫 {user}, {text}"
        return f"💫 {text}"
    
    def format_roast(self, text, user=None, lang='no'):
        """Format roast with optional user mention"""
        if user:
            if lang == 'no':
                return f"😏 {user}, {text}\n\n_(bare tuller, du er awesome!)_"
            else:
                return f"😏 {user}, {text}\n\n_(just kidding, you're awesome!)_"
        return f"😏 {text}"


def parse_compliment_command(message_content):
    """Convenience function"""
    manager = ComplimentsManager()
    return manager.parse_compliment_command(message_content)
