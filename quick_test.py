#!/usr/bin/env python3
"""Quick test of bot response"""
import asyncio
import sys
sys.path.insert(0, '.')
from ai.hermes_connector import HermesConnector

async def test():
    connector = HermesConnector()
    print('Testing 5 messages...\n')
    
    messages = [
        "Hei! Hvem er du?",
        "Hva kan du gjøre?",
        "Hvordan går det?",
        "Fortell en vits!",
        "Takk for hjelpen!"
    ]
    
    for msg in messages:
        print(f"Q: {msg}")
        success, response = await connector.generate_response(
            msg, 'TestUser', 'DM', True
        )
        if success:
            print(f"A: {response}\n")
        else:
            print(f"ERROR: {response}\n")
        await asyncio.sleep(1)

asyncio.run(test())
