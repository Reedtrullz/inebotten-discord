#!/usr/bin/env python3
"""
Inebotten Intent Stress-Tester
Simulates the MessageMonitor matching logic to identify false positives.
"""

import sys
import os
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(BASE_DIR))

class MockMonitor:
    """Mock version of MessageMonitor for testing logic only"""
    def __init__(self):
        # Keyword sets (copied from message_monitor.py for simulation)
        self.CALENDAR_KEYWORDS = ["kalender", "calendar", "events", "synk", "sync"]
        self.AURORA_KEYWORDS = ["nordlys", "aurora"]
        self.SCHOOL_KEYWORDS = ["skoleferie", "vinterferie", "påskeferie"]
        self.HELP_KEYWORDS = ["hjelp", "help", "kommandoer", "hva kan du"]
        
        # Managers (simplified)
        from features.crypto_manager import CryptoManager
        from features.horoscope_manager import HoroscopeManager
        from features.calculator_manager import CalculatorManager
        from features.poll_manager import parse_poll_command, parse_vote
        from features.countdown_manager import CountdownManager
        
        self.crypto = CryptoManager()
        self.horoscope = HoroscopeManager()
        self.calculator = CalculatorManager()
        self.countdown = CountdownManager()
        self.parse_poll = parse_poll_command
        self.parse_vote = parse_vote

    def test_intent(self, text):
        content_lower = text.lower()
        
        # 1. Calendar
        if any(w in content_lower for w in self.CALENDAR_KEYWORDS):
            return "CALENDAR"
            
        # 2. Countdown
        if self.countdown.parse_countdown_query(text):
            return "COUNTDOWN"
            
        # 3. Polls
        if self.parse_poll(text):
            return "POLL_CREATE"
        if self.parse_vote(text):
            return "POLL_VOTE"
            
        # 4. Aurora
        if any(w in content_lower for w in self.AURORA_KEYWORDS):
            return "AURORA"
            
        # 5. School
        if any(w in content_lower for w in self.SCHOOL_KEYWORDS):
            return "SCHOOL_HOLIDAYS"
            
        # 6. Price (The problematic one)
        if self.crypto.parse_price_query(text):
            return "PRICE"
            
        # 7. Horoscope
        if self.horoscope.parse_horoscope_command(text):
            return "HOROSCOPE"
            
        # 8. Calculator
        if self.calculator.parse_calculator_command(text):
            return "CALCULATOR"
            
        # 9. Help
        if any(w in content_lower for w in self.HELP_KEYWORDS):
            return "HELP"
            
        return "AI_FALLBACK (Correct)"

def run_suite():
    tester = MockMonitor()
    
    # Format: (Prompt, Expected Intent)
    test_suite = [
        # Small Talk / AI (Should all be AI_FALLBACK)
        ("Hva er egentlig greia med bålforbudet?", "AI_FALLBACK (Correct)"),
        ("Hvordan har du det i dag?", "AI_FALLBACK (Correct)"),
        ("Hva skjer?", "AI_FALLBACK (Correct)"),
        ("Hva er meningen med livet?", "AI_FALLBACK (Correct)"),
        ("Du er flink!", "AI_FALLBACK (Correct)"),
        ("Hva tenker du om saken?", "AI_FALLBACK (Correct)"),
        
        # Valid Commands (Should match their respective handlers)
        ("Hva koster Bitcoin?", "PRICE"),
        ("Bitcoin pris", "PRICE"),
        ("Hva er 2+2?", "CALCULATOR"),
        ("Når er det vinterferie?", "SCHOOL_HOLIDAYS"),
        ("Hjelp", "HELP"),
        ("Horoskop for væren", "HOROSCOPE"),
        ("Når går solen ned?", "AI_FALLBACK (Correct)"), # This is handled by AI/Dashboard logic
        
        # Potential False Positives
        ("Hva er egentlig planen?", "AI_FALLBACK (Correct)"),
        ("Når er du ferdig?", "AI_FALLBACK (Correct)"),
        ("Hvor mye er klokka?", "AI_FALLBACK (Correct)"),
        ("Er det noe kurs i kveld?", "AI_FALLBACK (Correct)"), # Testing 'kurs' which is a price keyword
    ]
    
    print(f"\n{'SENTENCE':<45} | {'MATCHED HANDLER':<20} | {'STATUS'}")
    print("-" * 80)
    
    passes = 0
    for prompt, expected in test_suite:
        actual = tester.test_intent(prompt)
        status = "✅ PASS" if actual == expected else f"❌ FAIL (Expected {expected})"
        if actual == expected: passes += 1
        
        print(f"{prompt[:44]:<45} | {actual[:20]:<20} | {status}")
        
    print("-" * 80)
    print(f"RESULTS: {passes}/{len(test_suite)} passed")

if __name__ == "__main__":
    run_suite()
