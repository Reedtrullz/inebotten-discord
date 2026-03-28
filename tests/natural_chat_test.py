#!/usr/bin/env python3
"""
Natural Chat Test Suite for Inebotten
Tests 50 different natural messages and evaluates responses
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.hermes_connector import HermesConnector

# 50 Natural chat messages (Norwegian)
TEST_MESSAGES = [
    # Basic greetings (1-10)
    "Hei!",
    "Hallo!",
    "God morgen!",
    "God kveld!",
    "Heisann!",
    "Hvordan går det?",
    "Hvordan har du det?",
    "Lenge siden sist!",
    "Godt å se deg!",
    "Morn!",
    
    # Personal questions (11-20)
    "Hvem er du?",
    "Hva er du for noe?",
    "Hva kan du gjøre?",
    "Hva er din jobb?",
    "Er du en bot?",
    "Hvor kommer du fra?",
    "Hva liker du å gjøre?",
    "Har du en familie?",
    "Hvor gammel er du?",
    "Hva er navnet ditt?",
    
    # Emotional/philosophical (21-30)
    "Hvordan føler du deg?",
    "Er du glad?",
    "Hva tenker du om livet?",
    "Er du ekte?",
    "Har du følelser?",
    "Hva er meningen med livet?",
    "Er du intelligent?",
    "Kan du bli forelsket?",
    "Drømmer du?",
    "Er du redd for noe?",
    
    # Casual chat (31-40)
    "Det er fint vær i dag!",
    "Jeg er sliten...",
    "Jeg har hatt en hard dag",
    "Skal du gjøre noe spennende i helgen?",
    "Liker du kaffe?",
    "Hva synes du om musikk?",
    "Har du sett en bra film i det siste?",
    "Jeg skal på ferie snart!",
    "Kan du synge?",
    "Fortell meg en vits!",
    
    # Mixed/contextual (41-50)
    "Hjelp meg!",
    "Jeg trenger noen å snakke med",
    "Takk for hjelpen!",
    "Beklager hvis jeg forstyrrer",
    "Kan jeg spørre deg noe?",
    "Jeg har en dårlig dag",
    "Dette er gøy!",
    "Jeg er lei meg",
    "Du er fantastisk!",
    "Ha det bra!",
]

# Expected response categories
NATURAL_RESPONSE_INDICATORS = [
    # Good signs
    "emoji_used",  # Uses emojis naturally
    "asks_followup",  # Asks a follow-up question
    "warm_tone",  # Warm, friendly tone
    "no_commands",  # Doesn't list commands unless asked
    "natural_norwegian",  # Proper Norwegian grammar
    "contextual",  # Response relates to the question
    
    # Bad signs
    "lists_commands",  # Lists technical commands
    "robotic",  # Sounds robotic/formulaic
    "fallback_used",  # "Skjønte ikke helt..."
    "broken_norwegian",  # Grammar errors
    "too_long",  # Response > 200 chars
    "english_words",  # Mixes in English
]


class NaturalChatTest:
    def __init__(self):
        self.connector = HermesConnector()
        self.results = []
        self.scores = {
            "total": 0,
            "natural": 0,
            "robotic": 0,
            "fallback": 0,
            "broken": 0,
        }
    
    async def run_test(self):
        """Run all 50 tests"""
        print("=" * 70)
        print("INEBOTTEN NATURAL CHAT TEST SUITE")
        print("=" * 70)
        print(f"Testing {len(TEST_MESSAGES)} messages...\n")
        
        for i, message in enumerate(TEST_MESSAGES, 1):
            print(f"\n[{i}/50] Testing: \"{message}\"")
            
            try:
                success, response = await self.connector.generate_response(
                    message_content=message,
                    author_name="TestUser",
                    channel_type="DM",
                    is_mention=True
                )
                
                if success:
                    result = self.analyze_response(message, response)
                    self.results.append(result)
                    self.update_scores(result)
                    
                    # Print result
                    status = "✅" if result["is_natural"] else "❌"
                    print(f"  {status} Response: {response[:100]}...")
                    if not result["is_natural"]:
                        print(f"      Issues: {', '.join(result['issues'])}")
                else:
                    print(f"  ❌ FAILED: {response}")
                    self.scores["fallback"] += 1
                    self.results.append({
                        "message": message,
                        "response": response,
                        "success": False,
                        "is_natural": False,
                        "issues": ["api_error"]
                    })
                    
            except Exception as e:
                print(f"  ❌ ERROR: {e}")
                self.scores["fallback"] += 1
            
            # Small delay to not overwhelm
            await asyncio.sleep(0.5)
        
        # Generate report
        await self.generate_report()
    
    def analyze_response(self, message, response):
        """Analyze if response is natural"""
        result = {
            "message": message,
            "response": response,
            "success": True,
            "is_natural": True,
            "indicators": {},
            "issues": [],
        }
        
        # Check length
        result["indicators"]["length"] = len(response)
        if len(response) > 200:
            result["issues"].append("too_long")
            result["is_natural"] = False
        
        # Check for command listing (bad)
        command_words = ["@inebotten", "kommando", "arrangement", "påminnelse", 
                        "avstemning", "horoskop", "sitat", "forkort"]
        if any(word in response.lower() for word in command_words[:3]):
            result["issues"].append("lists_commands")
            result["is_natural"] = False
        
        # Check for fallback phrase (bad)
        fallback_phrases = ["skjønte ikke helt", "prøv å si det", "kan du forklare",
                           "forvirra", "gikk over hodet"]
        if any(phrase in response.lower() for phrase in fallback_phrases):
            result["issues"].append("fallback_used")
            result["is_natural"] = False
            result["is_fallback"] = True
        
        # Check for broken Norwegian
        broken_indicators = ["jeg er godt", "dig", "for spørsmålet", 
                            "discord-landet", "hei again", "godt å se deg igjen"]
        if any(indicator in response.lower() for indicator in broken_indicators):
            result["issues"].append("broken_norwegian")
            result["is_natural"] = False
        
        # Check for English words
        english_words = ["hello", "hi", "how are you", "what can i do", 
                        "i'm", "i am", "thanks for", "again"]
        if any(word in response.lower() for word in english_words):
            result["issues"].append("english_words")
            result["is_natural"] = False
        
        # Check for emojis (good)
        emojis = ["👋", "😊", "🎉", "💪", "🌟", "✨", "🤔", "💡"]
        result["indicators"]["has_emoji"] = any(emoji in response for emoji in emojis)
        
        # Check for follow-up question (good)
        result["indicators"]["asks_followup"] = "?" in response and response.count("?") > message.count("?")
        
        # Check for warm tone
        warm_words = ["hyggelig", "godt", "bra", "fint", "gøy", "koselig", "veldig"]
        result["indicators"]["warm_tone"] = any(word in response.lower() for word in warm_words)
        
        # Check for contextual response
        # Response should relate to the question
        contextual = self.check_contextual(message, response)
        result["indicators"]["contextual"] = contextual
        if not contextual:
            result["issues"].append("not_contextual")
        
        return result
    
    def check_contextual(self, message, response):
        """Check if response is contextual to the message"""
        msg_lower = message.lower()
        resp_lower = response.lower()
        
        # Greeting should get greeting
        if any(word in msg_lower for word in ["hei", "hallo", "morn", "god morgen"]):
            return any(word in resp_lower for word in ["hei", "hallo", "morn", "god", "går"])
        
        # "Hvem er du" should get introduction
        if "hvem er du" in msg_lower:
            return any(word in resp_lower for word in ["jeg er", "ine", "kalender", "hjelp"])
        
        # "Hva kan du gjøre" should describe abilities
        if "hva kan" in msg_lower:
            return any(word in resp_lower for word in ["jeg kan", "hjelpe", "gjøre", "lage"])
        
        # Emotional questions should get empathy
        if any(word in msg_lower for word in ["føler", "trist", "sliten", "glad"]):
            return any(word in resp_lower for word in ["forstår", "bra", "håper", "godt"])
        
        return True  # Default pass
    
    def update_scores(self, result):
        """Update score counters"""
        self.scores["total"] += 1
        
        if result.get("is_fallback"):
            self.scores["fallback"] += 1
        elif result["is_natural"]:
            self.scores["natural"] += 1
        else:
            self.scores["robotic"] += 1
        
        if "broken_norwegian" in result["issues"]:
            self.scores["broken"] += 1
    
    async def generate_report(self):
        """Generate analysis report"""
        print("\n" + "=" * 70)
        print("TEST RESULTS")
        print("=" * 70)
        
        total = self.scores["total"]
        natural_pct = (self.scores["natural"] / total * 100) if total else 0
        
        print(f"\nTotal tests: {total}")
        print(f"Natural responses: {self.scores['natural']} ({natural_pct:.1f}%)")
        print(f"Robotic/Command lists: {self.scores['robotic']}")
        print(f"Fallback errors: {self.scores['fallback']}")
        print(f"Broken Norwegian: {self.scores['broken']}")
        
        # Find worst performing categories
        print("\n" + "=" * 70)
        print("PROBLEM ANALYSIS")
        print("=" * 70)
        
        # Group by message type
        problem_messages = []
        for result in self.results:
            if not result.get("is_natural", False):
                problem_messages.append(result)
        
        print(f"\nProblematic responses: {len(problem_messages)}")
        print("\nWorst offenders:")
        for result in problem_messages[:10]:  # Top 10 worst
            print(f"\n  Message: \"{result['message']}\"")
            print(f"  Response: \"{result['response'][:80]}...\"")
            print(f"  Issues: {', '.join(result['issues'])}")
        
        # Generate recommendations
        print("\n" + "=" * 70)
        print("RECOMMENDATIONS")
        print("=" * 70)
        
        if self.scores["fallback"] > 5:
            print("\n⚠️  Many fallback responses detected!")
            print("   → AI may not understand the prompts")
            print("   → Simplify system prompt further")
            print("   → Add more examples for common questions")
        
        if self.scores["robotic"] > 5:
            print("\n⚠️  Too many command-list responses!")
            print("   → System prompt explicitly says not to list commands")
            print("   → Need stronger instructions or different examples")
        
        if self.scores["broken"] > 3:
            print("\n⚠️  Broken Norwegian detected!")
            print("   → Add grammar rules to prompt")
            print("   → Lower temperature")
            print("   → Check model configuration")
        
        # Save detailed results
        report_file = Path(__file__).parent / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump({
                "scores": self.scores,
                "results": self.results,
                "timestamp": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 Detailed report saved to: {report_file}")
        
        return natural_pct


async def main():
    tester = NaturalChatTest()
    score = await tester.run_test()
    
    print("\n" + "=" * 70)
    if score >= 80:
        print("✅ EXCELLENT! Bot responds naturally most of the time.")
    elif score >= 60:
        print("⚠️  GOOD but needs some improvements.")
    elif score >= 40:
        print("❌ NEEDS WORK. Many unnatural responses.")
    else:
        print("❌ CRITICAL. Bot struggles with natural conversation.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
