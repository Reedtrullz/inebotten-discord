#!/usr/bin/env python3
"""
Auto-tune Prompts based on test results
Analyzes test data and suggests prompt improvements
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def load_test_report(report_file):
    """Load test report JSON"""
    with open(report_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_failures(data):
    """Analyze what went wrong"""
    results = data.get('results', [])
    
    # Categorize failures
    failure_patterns = {
        "fallback_questions": [],  # Questions that got "Skjønte ikke helt"
        "command_lists": [],       # Questions that got command lists
        "broken_norwegian": [],    # Questions with bad grammar
        "not_contextual": [],      # Responses not matching the question
        "too_long": [],            # Too verbose
        "english_mix": [],         # Mixed English
    }
    
    for result in results:
        if not result.get('is_natural', False):
            msg = result['message']
            issues = result.get('issues', [])
            
            if 'fallback_used' in issues:
                failure_patterns["fallback_questions"].append(msg)
            if 'lists_commands' in issues:
                failure_patterns["command_lists"].append(msg)
            if 'broken_norwegian' in issues:
                failure_patterns["broken_norwegian"].append(msg)
            if 'not_contextual' in issues:
                failure_patterns["not_contextual"].append(msg)
            if 'too_long' in issues:
                failure_patterns["too_long"].append(msg)
            if 'english_words' in issues:
                failure_patterns["english_mix"].append(msg)
    
    return failure_patterns


def generate_improved_prompt(failure_patterns):
    """Generate improved prompt based on failures"""
    
    # Base prompt structure
    improved_prompt = """Du er Ine, en vennlig norsk Discord-assistent.

VIKTIGE REGLER:
1. ALLTID svar på NORSK (bokmål)
2. ALDRI bland inn engelske ord
3. ALDRI list opp kommandoer med mindre spesifikt spurt
4. Hold svarene korte (maks 2-3 setninger)
5. Vær varm og personlig

EKSEMPLER PÅ GODE SVAR:
"""
    
    # Add examples for problematic question types
    examples = []
    
    if failure_patterns["fallback_questions"]:
        # Add examples for questions that confused the bot
        examples.append("""
Spørsmål: Hvem er du?
Svar: Jeg er Ine, din kalender-venn! Jeg hjelper deg å huske ting og prate. 📅

Spørsmål: Hva kan du gjøre?
Svar: Jeg kan lagre arrangementer, minne deg på ting, sjekke været, eller bare prate! 😊

Spørsmål: Hvordan føler du deg?
Svar: Jeg har det bra! Klar for å hjelpe deg! 💪
""")
    
    if failure_patterns["command_lists"]:
        # Emphasize NOT listing commands
        examples.append("""
VIKTIG: Når noen spør "Hva kan du gjøre?" skal du BESKRIVE det, ikke liste kommandoer!

FEIL: "Jeg kan: @inebotten arrangementer, @inebotten påminnelser..."
RIKTIG: "Jeg kan hjelpe deg med kalenderen, minne deg på ting, eller bare prate!"
""")
    
    if failure_patterns["broken_norwegian"]:
        # Add grammar rules
        examples.append("""
GRAMMATIKK:
- Si "Det går bra" ikke "Jeg er godt"
- Si "deg" ikke "dig" 
- Si "forstår" ikke "skjønner" (for uformelt)
- Si "hilsen" ikke "hei again"
""")
    
    if failure_patterns["english_mix"]:
        # Emphasize Norwegian only
        examples.append("""
ALDRI bruk:
- "Hi", "Hello", "Hey"
- "Thanks for..."
- "Nice to meet you"
- "Good to see you again"

ALLTID bruk norsk:
- "Hei", "Hallo"
- "Takk for..."
- "Hyggelig å møte deg"
- "Godt å se deg"
""")
    
    # Add general good examples
    examples.append("""
GENERELLE EKSEMPLER:

Spørsmål: Hei!
Svar: Hei! 👋 Hvordan går det?

Spørsmål: Det er fint vær
Svar: Ja, herlig! ☀️ Perfekt dag for en tur!

Spørsmål: Jeg er sliten
Svar: Skjønner det 💙 Ta deg en god pause!

Spørsmål: Fortell en vits
Svar: Hvorfor gikk kyllingen over veien? For å komme til den andre siden! 😄
""")
    
    # Combine all examples
    improved_prompt += "\n".join(examples)
    
    # Add closing instruction
    improved_prompt += """
HUSK:
- Snakk som en venn, ikke en manual
- Bruk emojis naturlig
- Still oppfølgingsspørsmål når det passer
- Vær varm og ekte!"""
    
    return improved_prompt


def generate_model_config_suggestions(failure_patterns):
    """Suggest model configuration changes"""
    suggestions = []
    
    if failure_patterns["broken_norwegian"] or failure_patterns["english_mix"]:
        suggestions.append({
            "setting": "temperature",
            "current": "0.6",
            "suggested": "0.4",
            "reason": "Lower temperature for more consistent language"
        })
        suggestions.append({
            "setting": "frequency_penalty",
            "current": "0.15",
            "suggested": "0.25", 
            "reason": "Higher penalty to prevent English words"
        })
    
    if failure_patterns["too_long"]:
        suggestions.append({
            "setting": "max_tokens",
            "current": "150",
            "suggested": "100",
            "reason": "Shorter responses are more natural"
        })
    
    return suggestions


def main():
    """Main analysis function"""
    import glob
    
    # Find latest test report
    report_files = list(Path(__file__).parent.glob("test_report_*.json"))
    if not report_files:
        print("❌ No test reports found! Run natural_chat_test.py first.")
        return
    
    # Get most recent
    latest_report = max(report_files, key=lambda p: p.stat().st_mtime)
    print(f"📊 Analyzing: {latest_report}")
    
    # Load data
    data = load_test_report(latest_report)
    scores = data.get('scores', {})
    
    print("\n" + "=" * 70)
    print("AUTO-TUNE ANALYSIS")
    print("=" * 70)
    
    print(f"\nCurrent Performance:")
    total = scores.get('total', 0)
    natural = scores.get('natural', 0)
    if total > 0:
        print(f"  Natural responses: {natural}/{total} ({natural/total*100:.1f}%)")
    
    # Analyze failures
    failure_patterns = analyze_failures(data)
    
    print("\n" + "=" * 70)
    print("FAILURE BREAKDOWN")
    print("=" * 70)
    
    for pattern, messages in failure_patterns.items():
        if messages:
            print(f"\n{pattern.replace('_', ' ').title()}: {len(messages)} cases")
            for msg in messages[:3]:  # Show first 3
                print(f"  - \"{msg}\"")
    
    # Generate improved prompt
    print("\n" + "=" * 70)
    print("SUGGESTED IMPROVED PROMPT")
    print("=" * 70)
    
    improved_prompt = generate_improved_prompt(failure_patterns)
    print("\n" + improved_prompt)
    
    # Generate config suggestions
    config_suggestions = generate_model_config_suggestions(failure_patterns)
    
    if config_suggestions:
        print("\n" + "=" * 70)
        print("SUGGESTED CONFIGURATION CHANGES")
        print("=" * 70)
        
        for suggestion in config_suggestions:
            print(f"\n{suggestion['setting']}:")
            print(f"  Current: {suggestion['current']}")
            print(f"  Suggested: {suggestion['suggested']}")
            print(f"  Reason: {suggestion['reason']}")
    
    # Save improved prompt
    output_file = Path(__file__).parent / f"improved_prompt_{latest_report.stem.replace('test_report_', '')}.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(improved_prompt)
    
    print(f"\n📄 Improved prompt saved to: {output_file}")
    
    # Apply suggestion
    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print("\n1. Review the improved prompt above")
    print("2. Copy it to ai/personality_config.py")
    print("3. Update model settings in ai/hermes_bridge_server.py")
    print("4. Re-run the test to verify improvements")
    print("\nApply changes automatically? (y/n)")
    
    # Note: In real usage, this would ask for confirmation
    print("\n💡 Tip: Edit the files manually for full control!")


if __name__ == "__main__":
    main()
