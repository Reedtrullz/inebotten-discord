#!/usr/bin/env python3
"""
Compliments and Roasting Manager for Inebotten
Generates compliments and friendly roasts
"""

import random
import re

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
        content_lower = message_content.lower()
        
        # Check for compliments
        if any(word in content_lower for word in ['kompliment', 'compliment', 'ros', 'praise']):
            # Extract username if mentioned
            user = self._extract_user(message_content)
            return {'action': 'compliment', 'user': user}
        
        # Check for roasts (friendly)
        if any(word in content_lower for word in ['roast', 'diss', 'drit', 'kjøl deg ned']):
            user = self._extract_user(message_content)
            return {'action': 'roast', 'user': user}
        
        return None
    
    def _extract_user(self, message_content):
        """Extract mentioned username"""
        # Look for @username or Discord mentions
        match = re.search(r'@(\w+)', message_content)
        if match:
            return match.group(1)
        
        # Look for Discord mention format
        match = re.search(r'<@!?(\d+)>', message_content)
        if match:
            return "<@" + match.group(1) + ">"
        
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
