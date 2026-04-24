#!/usr/bin/env python3
"""
Response Cleaner for Thinking Models
Extracts actual answers from model's thinking output
"""

import re

def clean_thinking_response(text):
    """
    Clean up thinking model responses to extract just the answer
    """
    if not text:
        return ""
    
    # List of patterns that indicate thinking, not answering
    thinking_indicators = [
        r"^Looking at",
        r"^In the examples?",
        r"^According to",
        r"^Based on",
        r"^The rules say",
        r"^I should",
        r"^I need to",
        r"^So I should",
        r"^Wait",
        r"^How about",
        r"^Hmm",
        r"^Let me",
        r"^I think",
        r"^Alternatively",
        r"^This means",
        r"^The assistant",
        r"^First,",
        r"^Then",
        r"^A:\s*",  # "A: " at start
        r"^Q:\s*",  # "Q: " at start
        r"^So the",
        r"^In the",
        r"^But",
        r"^Actually",
        r"^Maybe",
        r"^Perhaps",
    ]
    
    lines = text.split('\n')
    candidates = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip if it's a thinking line
        is_thinking = any(re.search(pattern, line, re.IGNORECASE) for pattern in thinking_indicators)
        if is_thinking:
            continue
        
        # Skip very short lines (less than 3 words) unless it contains a link
        if len(line.split()) < 3 and "[" not in line:
            continue
        
        # Skip lines that are just punctuation or emojis
        if re.match(r'^[\s👋😊🎉💪🌟✨🤔💡🦴🌧️☕📅]+$', line):
            continue
        
        # This looks like an actual response
        candidates.append(line)
    
    # If we found candidates, return the last one (usually the answer)
    if candidates:
        return candidates[-1]
    
    # Fallback: try to extract from quotes
    quotes = re.findall(r'"([^"]{10,})"', text)
    if quotes:
        return quotes[-1]
    
    # Last resort: return text after last period
    sentences = [s.strip() for s in text.split('.') if len(s.strip()) > 10]
    if sentences:
        return sentences[-1] + '.'
    
    return text[:500]  # Return first 500 chars as fallback


if __name__ == "__main__":
    # Test cases
    test_cases = [
        'In the examples, when someone asks "Hvem er du?", the response is: "Jeg er Ine! Jeg hjelper deg med kalender, påminnelser og prat." So I should follow that structure.',
        'So I should follow that exact response. Wait, but the user is the one asking, so I need to make sure the answer is in Norwegian.',
        'A: Jeg er Ine! Jeg hjelper deg med kalender,',
        'How about: "Hvor går en hund når hun blir for gammel? Til høst! 🦴" Hmm,',
        'Wait',
        'Looking at the previous examples, I should respond with "Hei!" and ask how they are doing.',
        'Jeg er Ine! Jeg hjelper deg med kalender, påminnelser og prat. 📅',
    ]
    
    print("Testing response cleaner:\n")
    for test in test_cases:
        cleaned = clean_thinking_response(test)
        print(f"IN:  {test[:60]}...")
        print(f"OUT: {cleaned}")
        print()
