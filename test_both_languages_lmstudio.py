#!/usr/bin/env python3
"""
Comprehensive LM Studio test for Bokmål and Nynorsk language support
Tests 100 sentences in each language via the Hermes bridge
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Sample sentences for testing (20 from each category)
BOKMAAL_SENTENCES = [
    # Simple
    "Hunden sover.",
    "Katta sitter på bordet.",
    "Jeg liker kaffe.",
    "Solen skinner i dag.",
    "Barnet leker i hagen.",
    # Medium
    "Da jeg kom hjem, satt katten og ventet på meg.",
    "Hvis det regner i morgen, blir vi hjemme.",
    "Selv om han var trøtt, gikk han på jobb.",
    "Boken som lå på bordet, tilhørte min bestemor.",
    "Vi skulle ha dratt tidligere, men bussen var forsinket.",
    # Complex
    "Hadde det ikke vært for at bussen var forsinket, ville vi aldri møtt hverandre.",
    "Det at han velger å reise nå, betyr ikke at han ikke bryr seg.",
    "Uansett hvor mye du prøver å forklare, vil hun aldri forstå.",
    "Det var først etter at stormen hadde lagt seg at vi forsto.",
    "Siden ingen av oss hadde tenkt på konsekvensene, endte vi opp i en vanskelig situasjon.",
    # Calendar-related
    "Jeg har et møte i morgen klokken 14.",
    "Husk å ringe mamma på søndag.",
    "Vi skal ha julebord 20. desember.",
    "Regningene kommer den 5. hver måned.",
    "Tannlege time neste tirsdag kl 09:00.",
]

NYNORSK_SENTENCES = [
    # Simple
    "Hunden søv.",
    "Katta sit på bordet.",
    "Eg likar kaffi.",
    "Sola skìn i dag.",
    "Barnet leikar i hagen.",
    # Medium
    "Då eg kom heim, sat katta og venta på meg.",
    "Viss det regnar i morgon, blir vi heime.",
    "Sjølv om han var trøtt, gjekk han på jobb.",
    "Boka som låg på bordet, høyrde til mi bestemor.",
    "Vi skulle ha drege tidlegare, men bussen var forseinka.",
    # Complex
    "Hadde det ikkje vore for at bussen var forseinka, ville vi aldri ha møtt kvarandre.",
    "Det at han vel å reise sin veg no, betyr ikkje at han ikkje bryr seg.",
    "Uansett kor mykje du prøver å forklare det, vil ho aldri forstå.",
    "Det var først etter at stormen hadde lagt seg at vi forstod.",
    "Sidan ingen av oss hadde tenkt på konsekvensane, endte vi opp i ein vanskeleg situasjon.",
    # Calendar-related
    "Eg har eit møte i morgon klokken 14.",
    "Hugs å ringe mamma på sundag.",
    "Vi skal ha julebord 20. desember.",
    "Regningane kjem den 5. kvar månad.",
    "Tannlege time neste tirsdag kl 09:00.",
]


class LMStudioTester:
    def __init__(self):
        self.bridge_url = "http://localhost:5001/api/chat"
        self.results = {
            "bokmaal": {"total": 0, "responded": 0, "correct_language": 0, "errors": 0},
            "nynorsk": {"total": 0, "responded": 0, "correct_language": 0, "errors": 0},
        }

    async def test_connection(self):
        """Test if LM Studio bridge is available"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Health endpoint is at root, not /api/chat
                async with session.get("http://localhost:5001/health", timeout=5) as resp:
                    return resp.status == 200
        except Exception as e:
            print(f"❌ Bridge connection failed: {e}")
            return False

    async def send_message(self, message: str) -> dict:
        """Send message to LM Studio via bridge"""
        try:
            import aiohttp
            import json
            from urllib.parse import quote
            
            payload = {
                "message": message,
                "user": "test_user",
                "channel": "test_channel",
                "guild": "test_guild",
                "channel_type": "text",
                "timestamp": datetime.now().isoformat(),
                "is_mention": True,
            }
            
            # Bridge uses GET with data query parameter
            url = f"{self.bridge_url}?data={quote(json.dumps(payload))}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=60
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {"error": f"HTTP {resp.status}: {text[:100]}"}
        except asyncio.TimeoutError:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    def detect_language(self, text: str) -> str:
        """Detect if response is in Bokmål, Nynorsk, or other"""
        text_lower = text.lower()
        
        # Nynorsk indicators
        nynorsk_words = ['eg', 'ikkje', 'det', 'kva', 'kor', 'kven', 'noko', 'nokon', 
                        'ein', 'eit', 'dei', 'dykk', 'verkeleg', 'tydeleg', 'vanskeleg',
                        'morgon', 'månad', 'veke', 'måndag', 'laurdag', 'sundag']
        
        # Bokmål indicators  
        bokmaal_words = ['jeg', 'ikke', 'det', 'hva', 'hvor', 'hvem', 'noe', 'noen',
                        'en', 'et', 'de', 'dere', 'virkelig', 'tydelig', 'vanskelig',
                        'morgen', 'måned', 'uke', 'mandag', 'lørdag', 'søndag']
        
        nynorsk_score = sum(1 for word in nynorsk_words if word in text_lower)
        bokmaal_score = sum(1 for word in bokmaal_words if word in text_lower)
        
        if nynorsk_score > bokmaal_score:
            return "nynorsk"
        elif bokmaal_score > nynorsk_score:
            return "bokmaal"
        else:
            return "ambiguous"

    async def test_language(self, sentences: list, language: str):
        """Test a set of sentences"""
        print(f"\n{'='*70}")
        print(f"Testing {language.upper()} ({len(sentences)} sentences)")
        print("="*70)
        
        self.results[language]["total"] = len(sentences)
        
        for i, sentence in enumerate(sentences, 1):
            print(f"\n{i:2d}. {sentence}")
            
            response = await self.send_message(f"@inebotten {sentence}")
            
            if "error" in response:
                print(f"   ❌ Error: {response['error']}")
                self.results[language]["errors"] += 1
                continue
            
            if "response" not in response:
                print(f"   ❌ No response field")
                self.results[language]["errors"] += 1
                continue
            
            ai_response = response["response"]
            self.results[language]["responded"] += 1
            
            # Truncate response for display
            display_resp = ai_response[:100].replace('\n', ' ')
            print(f"   → {display_resp}...")
            
            # Detect language of response
            detected = self.detect_language(ai_response)
            
            if language == "bokmaal" and detected == "bokmaal":
                print(f"   ✓ Correct language (Bokmål)")
                self.results[language]["correct_language"] += 1
            elif language == "nynorsk" and detected == "nynorsk":
                print(f"   ✓ Correct language (Nynorsk)")
                self.results[language]["correct_language"] += 1
            elif detected == "ambiguous":
                print(f"   ⚠ Ambiguous language")
                # Count as half correct
                self.results[language]["correct_language"] += 0.5
            else:
                print(f"   ✗ Wrong language (detected: {detected})")
            
            # Small delay to avoid overwhelming the model
            await asyncio.sleep(0.5)

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        
        total_correct = 0
        total_tests = 0
        
        for lang in ["bokmaal", "nynorsk"]:
            r = self.results[lang]
            total = r["total"]
            responded = r["responded"]
            correct = r["correct_language"]
            errors = r["errors"]
            
            total_correct += correct
            total_tests += total
            
            print(f"\n{lang.upper()}:")
            print(f"  Total sentences: {total}")
            print(f"  Got response: {responded} ({responded/total*100:.1f}%)")
            print(f"  Correct language: {correct:.1f} ({correct/total*100:.1f}%)")
            print(f"  Errors: {errors}")
        
        overall_score = (total_correct / total_tests) * 100 if total_tests > 0 else 0
        
        print("\n" + "="*70)
        print(f"OVERALL SCORE: {overall_score:.1f}%")
        print("="*70)
        
        if overall_score >= 80:
            print("✅ EXCELLENT - Model handles both languages very well")
        elif overall_score >= 60:
            print("✅ GOOD - Model handles both languages reasonably well")
        elif overall_score >= 40:
            print("⚠️  FAIR - Some issues with language detection/response")
        else:
            print("❌ POOR - Model struggles with Norwegian languages")


async def main():
    print("="*70)
    print("LM STUDIO COMPREHENSIVE LANGUAGE TEST")
    print("Testing Bokmål and Nynorsk via Hermes Bridge")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Bridge URL: http://localhost:5001")
    print(f"Model: Gemma 3 12B (configured)")
    
    tester = LMStudioTester()
    
    # Test connection
    print("\nChecking bridge connection...")
    if not await tester.test_connection():
        print("\n❌ Cannot connect to Hermes bridge at http://localhost:5001")
        print("Please ensure:")
        print("  1. LM Studio is running with Gemma 3 12B loaded")
        print("  2. Hermes bridge server is running (python3 hermes_bridge_server.py)")
        print("  3. Bridge is accessible at localhost:5001")
        return 1
    
    print("✓ Bridge connection successful")
    
    # Run tests
    await tester.test_language(BOKMAAL_SENTENCES, "bokmaal")
    await tester.test_language(NYNORSK_SENTENCES, "nynorsk")
    
    # Print summary
    tester.print_summary()
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
