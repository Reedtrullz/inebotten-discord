#!/usr/bin/env python3
"""
Quick start script - sets up environment with proper session token
"""

import os
import sys
from pathlib import Path

def main():
    # Get Discord token from environment (DO NOT hardcode)
    discord_token = os.environ.get('DISCORD_USER_TOKEN', '')
    
    if not discord_token:
        print("Error: DISCORD_USER_TOKEN not set")
        print("Set it with: export DISCORD_USER_TOKEN='your_token'")
        sys.exit(1)
    
    os.environ['HERMES_API_URL'] = 'http://127.0.0.1:3000/api/chat'
    
    print("="*60)
    print("  DISCORD SELFBOT - Quick Start")
    print("="*60)
    print(f"Hermes API URL: {os.environ['HERMES_API_URL']}")
    print(f"Auth type: Session Token configured\n")
    
    # Add hermes_tools to path
    sys.path.insert(0, str(Path.home()))
    sys.path.insert(0, str(Path.home() / '.hermes'))
    
    # Import and run setup
    print("[1/3] Running setup...")
    try:
        from discord.setup import setup
        setup()
    except Exception as e:
        print(f"Setup warning: {e}")
    
    # Run tests
    print("\n[2/3] Running comprehensive tests...")
    try:
        from discord.test_selfbot import run_tests
        success = run_tests()
        if success:
            print("\n✅ All tests passed! Selfbot is ready.")
        else:
            print("\n⚠️  Some tests failed. Check output above.")
    except Exception as e:
        print(f"Test error: {e}")
    
    # Summary
    print("\n[3/3] SUMMARY")
    print("="*60)
    print("Files created in ~/.hermes/discord/")
    files = ['config.py', 'auth_handler.py', 'rate_limiter.py', 
             'hermes_connector.py', 'message_monitor.py', 
             'response_generator.py', 'selfbot_runner.py']
    for f in files:
        path = Path.home() / '.hermes' / 'discord' / f
        print(f"  {'✓' if path.exists() else '✗'} {f}")
    
    print("\nTo run tests only:")
    print("  python3 ~/.hermes/discord/run_tests.py")
    print("\nTo run the selfbot (after tests pass):")
    print("  python3 ~/.hermes/discord/selfbot_runner.py --test")
    print("\nTo run full mode:")
    print("  python3 ~/.hermes/discord/selfbot_runner.py")

if __name__ == "__main__":
    main()
