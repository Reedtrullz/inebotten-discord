#!/usr/bin/env python3
"""Test LM Studio connection directly"""

import requests
import json

LM_STUDIO_URL = "http://192.168.160.1:1234/v1"

def test_connection():
    print("=== Testing LM Studio Connection ===\n")
    
    # Test 1: Check if server is running
    try:
        resp = requests.get(f"{LM_STUDIO_URL}/models", timeout=5)
        print(f"✓ Server reachable (status {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Models: {data}")
    except Exception as e:
        print(f"✗ Cannot connect: {e}")
        return
    
    # Test 2: Simple chat completion
    print("\n=== Testing Chat Completion ===")
    
    payload = {
        "model": "qwen3-4b-thinking",
        "messages": [
            {"role": "system", "content": "Du er Ine. Svar på norsk."},
            {"role": "user", "content": "Hei! Hvem er du?"}
        ],
        "temperature": 0.6,
        "max_tokens": 100,
        "stream": False
    }
    
    try:
        resp = requests.post(
            f"{LM_STUDIO_URL}/chat/completions",
            json=payload,
            timeout=30
        )
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"\nFull response:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            
            if 'choices' in data and len(data['choices']) > 0:
                content = data['choices'][0].get('message', {}).get('content', '')
                print(f"\n>>> AI Response: {content}")
            else:
                print("✗ No choices in response")
        else:
            print(f"✗ Error: {resp.text[:500]}")
            
    except Exception as e:
        print(f"✗ Request failed: {e}")

if __name__ == "__main__":
    test_connection()
