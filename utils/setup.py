#!/usr/bin/env python3
"""
Setup script for Discord Selfbot
Installs required dependencies
"""

import sys
import subprocess
from pathlib import Path

def install_requirements():
    """
    Install all required packages
    """
    print("="*60)
    print("  DISCORD SELFBOT - SETUP")
    print("="*60)
    
    requirements = [
        "discord.py>=2.0.0",
        "aiohttp>=3.8.0",
        "python-dotenv>=0.19.0",
        "google-api-python-client>=2.100.0",
        "google-auth-httplib2>=0.1.1",
        "google-auth-oauthlib>=1.0.0"
    ]
    
    print("\nInstalling required packages...")
    print(f"  Python: {sys.executable}")
    print()
    
    for package in requirements:
        print(f"  Installing {package}...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"    ✓ {package} installed")
        except subprocess.CalledProcessError as e:
            print(f"    ✗ Failed to install {package}: {e}")
            return False
    
    print("\n" + "="*60)
    print("  SETUP COMPLETE")
    print("="*60)
    print("\nNext steps:")
    print("  1. Configure your credentials in .env file")
    print("  2. Run: python3 test_selfbot.py")
    print("  3. Run: python3 selfbot_runner.py")
    
    return True

def create_env_template():
    """
    Create .env.example template if it doesn't exist
    """
    env_path = Path.home() / '.hermes' / 'discord' / '.env.example'
    
    if env_path.exists():
        return
    
    template = """# Discord Selfbot Configuration
# Copy this file to .env and fill in your credentials

# Method 1: Discord User Token (recommended)
# Get this from Discord Developer Tools > Application > Local Storage
DISCORD_USER_TOKEN=your_token_here

# Method 2: Email/Password (fallback if token doesn't work)
# DISCORD_EMAIL=your_email@example.com
# DISCORD_PASSWORD=your_password

# Hermes API Configuration
HERMES_API_URL=http://127.0.0.1:3000/api/chat

# Rate Limiting (optional - defaults shown)
# MAX_MSGS_PER_SEC=5
# DAILY_QUOTA=10000
# SAFE_INTERVAL=1
# POLL_INTERVAL=8
"""
    
    env_path.write_text(template)
    print(f"\nCreated template: {env_path}")

if __name__ == "__main__":
    success = install_requirements()
    create_env_template()
    sys.exit(0 if success else 1)
