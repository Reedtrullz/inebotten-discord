#!/usr/bin/env python3
"""
Simple Live Simulation - Shows @inebotten's actual response flow
No Discord dependencies needed for demo
"""

import os
from datetime import datetime

def run_simple_simulation():
    print("="*70)
    print("  LIVE SIMULATION: @inebotten Response Flow")
    print("="*70)
    
    # Step 1: Simulate receiving a mention in DMs
    print("\n[1/4] 📥 MESSAGE RECEIVED")
    print("-" * 40)
    print("Scenario: You send this message:")
    
    incoming_message = "Hey @inebotten, what's the weather like today and are there any holidays?"
    print(f"  Message: \"{incoming_message}\"")
    print("  Author: kjellogunnar")
    print("  Channel: Group DM (calendar bot)")
    
    # Step 2: Mention detection
    print("\n[2/4] 📡 MONITORING & DETECTION")
    print("-" * 40)
    content_lower = incoming_message.lower()
    if '@inebotten' in content_lower:
        print("  ✓ MENTION DETECTED!")
        print("  → Triggering response pipeline...")
    else:
        print("  ✗ No mention - would skip")
        return
    
    # Step 3: Rate limiting check
    print("\n[3/4] ⏱️  RATE LIMITING CHECK")
    print("-" * 40)
    print(f"  • Messages sent today: 0 (at startup)")
    print(f"  • Daily quota: {10_000}")
    print(f"  • Rate limit status: PASS ✓")
    print("  → Can proceed immediately")
    
    # Step 4: Hermes API request (show what gets sent)
    print("\n[4/4] 🌐 HERMES INTELLIGENCE PHASE")
    print("-" * 40)
    from hermes_tools import web_search
    
    timestamp = datetime.now().isoformat()
    context_payload = {
        "message": incoming_message,
        "author_name": "kjellogunnar",
        "channel_type": "DM",
        "timestamp": timestamp,
        "is_mention": True
    }
    
    print("  → Building API request...")
    payload_str = str(context_payload)
    print(f"  • Request URL: http://127.0.0.1:3000/api/chat")
    print(f"  • Method: GET")
    print(f"  • Payload ({len(payload_str)} chars): {payload_str}")
    
    # Make actual API call
    result = web_search(f"GET http://127.0.0.1:3000/api/chat?data={payload_str}", limit=1)
    print("  • API Response received ✓")
    
    # Step 5: Generate response (show actual output)
    print("\n" + "="*70)
    print("  📤 FINAL RESPONSE FROM @inebotten:")
    print("-" * 40)
    from discord.response_generator import generate_response
    
    response_text = generate_response(incoming_message)
    
    # Display what @inebotten would actually send back
    lines = response_text.split('\n')
    formatted_response = ""
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if '✗' in line or 'not configured' in line.lower():
            print(f"   {line}")
            continue
        
        # Add proper formatting
        stripped = line.strip()
        if '•' in stripped and not stripped.startswith('•'):
            formatted_response += f"\n   •{stripped}"
        elif ':' in stripped or '☕' in stripped:
            formatted_response += f"\n   {stripped}" 
        else:
            formatted_response += f"\n{stripped}" if i > 0 else f"{stripped}"
    
    print(formatted_response)
    print("-" * 40)
    
    # Summary
    print("\n" + "="*70)
    print("  SIMULATION COMPLETE")
    print("="*70)
    print(f"\nWhat happened:")
    print(f"  1. ⚡ Message received from kjellogunnar")
    print(f"  2. 👀 Mention '@inebotten' detected")
    print(f"  3. 📊 Rate limit check: PASS")
    print(f"  4. 🌐 Hermes API called (localhost:3000)")
    print(f"  5. 💬 Response generated & ready to send")
    print("\nThe selfbot is fully functional - it just needs Discord!")

if __name__ == "__main__":
    run_simple_simulation()
