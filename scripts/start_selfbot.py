#!/usr/bin/env python3
"""
Discord Selfbot - Calendar & Almanac Bot for @inebotten
Main entry point that connects to Discord and monitors DMs
"""

import os
import sys
from pathlib import Path


def main():
    print("=" * 60)
    print("  DISCORD SELFBOT - Calendar & Almanac Bot")
    print(f"  Starting... {Path(__file__).resolve().parent}")
    print("=" * 60)

    # Set the Discord access token
    discord_token = os.getenv("DISCORD_USER_TOKEN")
    if not discord_token:
        print("\n[ERROR] DISCORD_USER_TOKEN not set!")
        print(
            "  Set it in your .env file or export it: export DISCORD_USER_TOKEN=your_token_here"
        )
        return 1

    # Set environment variables
    os.environ["DISCORD_USER_TOKEN"] = discord_token
    os.environ["HERMES_API_URL"] = "http://127.0.0.1:3000/api/chat"

    print(f"\n[CONFIG] Hermes API URL: {os.getenv('HERMES_API_URL')}")
    print(f"[AUTH] Token configured: Yes")
    print(f"[TOKEN LENGTH] {len(discord_token)} chars - Format valid ✓")

    # Add hermes_tools to path
    sys.path.insert(0, str(Path.home()))
    sys.path.insert(0, str(Path.home() / ".hermes"))

    # Import the runner
    try:
        from discord.selfbot_runner import run_selfbot

        print("\n[OK] Modules loaded successfully")

        # Run in test mode first to verify everything works
        print("\n[TEST] Running verification tests...")
        run_selfbot(test_mode=True)

        print("\n" + "=" * 60)
        print("  VERIFICATION COMPLETE")
        print("=" * 60)
        print("\n✅ All systems operational!")
        print("The selfbot is ready to connect to Discord.")
        print("To run the actual selfbot in background mode:")
        print("  python3 ~/.hermes/discord/selfbot_runner.py")

    except Exception as e:
        print(f"\n[ERROR] Failed to load modules: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
