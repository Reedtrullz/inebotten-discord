#!/usr/bin/env python3
"""
Horoscope Manager for Inebotten
Daily horoscope for zodiac signs
"""

import random
import re
from datetime import datetime

class HoroscopeManager:
    """
    Generates daily horoscopes
    """
    
    def __init__(self):
        self.zodiac_signs = {
            'væren': 'Aries', 'aries': 'Aries', '♈': 'Aries',
            'tyren': 'Taurus', 'taurus': 'Taurus', '♉': 'Taurus',
            'tvillingene': 'Gemini', 'gemini': 'Gemini', '♊': 'Gemini',
            'krepsen': 'Cancer', 'cancer': 'Cancer', '♋': 'Cancer',
            'løven': 'Leo', 'leo': 'Leo', '♌': 'Leo',
            'jomfruen': 'Virgo', 'virgo': 'Virgo', '♍': 'Virgo',
            'vekten': 'Libra', 'libra': 'Libra', '♎': 'Libra',
            'skorpionen': 'Scorpio', 'scorpio': 'Scorpio', '♏': 'Scorpio',
            'skytten': 'Sagittarius', 'sagittarius': 'Sagittarius', '♐': 'Sagittarius',
            'steinbukken': 'Capricorn', 'capricorn': 'Capricorn', '♑': 'Capricorn',
            'vannmannen': 'Aquarius', 'aquarius': 'Aquarius', '♒': 'Aquarius',
            'fiskene': 'Pisces', 'pisces': 'Pisces', '♓': 'Pisces',
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
        content_lower = message_content.lower()
        
        # Remove @inebotten
        content_lower = content_lower.replace('@inebotten', '').strip()
        
        # Check for horoscope keywords
        if not any(word in content_lower for word in ['horoskop', 'horoscope']):
            return None
        
        # Look for zodiac sign
        for sign_key, sign_name in self.zodiac_signs.items():
            if sign_key in content_lower:
                return {'sign': sign_name, 'sign_key': sign_key}
        
        # If no sign found, return None (we need a sign)
        return None
    
    def get_horoscope(self, sign, lang='no'):
        """Generate horoscope for sign"""
        # Use date as seed for consistent daily horoscope
        today = datetime.now().strftime('%Y%m%d')
        random.seed(f"{today}_{sign}")
        
        horoscopes = self.horoscopes_no if lang == 'no' else self.horoscopes_en
        text = random.choice(horoscopes)
        
        # Generate ratings
        love = random.randint(3, 10)
        career = random.randint(3, 10)
        health = random.randint(3, 10)
        luck = random.randint(3, 10)
        
        random.seed()  # Reset seed
        
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
