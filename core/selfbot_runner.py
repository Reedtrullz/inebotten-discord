#!/usr/bin/env python3
"""
Discord Selfbot Runner - Main Entry Point
Runs the selfbot with all components integrated
"""

import os
import sys
import asyncio
import signal
from pathlib import Path
from datetime import datetime

# Add directories to path for imports
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE_DIR))  # Add root for ai/, cal_system/, etc.
sys.path.insert(0, str(SCRIPT_DIR))  # Add core/ for local imports

try:
    import discord
except ImportError:
    print("[SETUP] Installing discord.py...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "-q", "discord.py"])
    import discord

from core.config import get_config
from core.auth_handler import create_auth_handler
from core.rate_limiter import create_rate_limiter
from ai.hermes_connector import create_hermes_connector
from ai.response_generator import create_response_generator
from core.message_monitor import SelfbotClient


class SelfbotRunner:
    """Main runner class that orchestrates the selfbot"""
    
    def __init__(self):
        self.config = None
        self.auth_handler = None
        self.rate_limiter = None
        self.hermes = None
        self.response_gen = None
        self.client = None
        self.running = False
    
    def setup(self):
        """Initialize all components"""
        print("="*60)
        print("  DISCORD SELFBOT - INITIALIZING")
        print("="*60)
        
        # Load configuration
        print("\n[1/5] Loading configuration...")
        self.config = get_config()
        print(f"  Hermes API: {self.config.HERMES_API_URL}")
        print(f"  Rate limit: {self.config.MAX_MSGS_PER_SECOND}/sec")
        
        # Initialize auth handler
        print("\n[2/5] Initializing authentication...")
        try:
            self.auth_handler = create_auth_handler(self.config)
            auth_type = self.auth_handler.get_auth_type()
            print(f"  Auth type: {auth_type}")
            if auth_type == 'token':
                masked = self.auth_handler.get_masked_token()
                print(f"  Token: {masked}")
        except ValueError as e:
            print(f"  ERROR: {e}")
            return False
        
        # Initialize rate limiter
        print("\n[3/5] Initializing rate limiter...")
        self.rate_limiter = create_rate_limiter(self.config)
        print(f"  Max: {self.rate_limiter.max_per_second}/sec, {self.rate_limiter.daily_quota}/day")
        
        # Initialize Hermes connector
        print("\n[4/5] Initializing Hermes connector...")
        self.hermes = create_hermes_connector(self.config)
        print(f"  API URL: {self.hermes.base_url}")
        
        # Initialize response generator
        print("\n[5/5] Initializing response generator...")
        self.response_gen = create_response_generator()
        print("  Local templates loaded")
        
        print("\n" + "="*60)
        print("  INITIALIZATION COMPLETE")
        print("="*60)
        return True
    
    async def health_check(self):
        """Check all components before starting"""
        print("\n[HEALTH CHECK]")
        
        # Check Hermes
        healthy, message = await self.hermes.check_health()
        if healthy:
            print(f"  ✓ Hermes API: {message}")
        else:
            print(f"  ⚠ Hermes API: {message}")
            print("    Will use local response generator as fallback")
        
        print("  ✓ All components ready")
        return True
    
    def create_client(self):
        """Create the Discord client"""
        self.client = SelfbotClient(
            config=self.config,
            auth_handler=self.auth_handler,
            rate_limiter=self.rate_limiter,
            hermes_connector=self.hermes,
            response_generator=self.response_gen
        )
        
        # Set up signal handlers
        def signal_handler(sig, frame):
            print("\n[SIGNAL] Shutdown requested...")
            asyncio.create_task(self.shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def run(self):
        """Main run loop"""
        if not self.setup():
            return 1
        
        if not await self.health_check():
            return 1
        
        self.create_client()
        
        print("\n[STARTING] Connecting to Discord...")
        print("  (Press Ctrl+C to stop)\n")
        
        self.running = True
        
        try:
            if self.auth_handler.is_token_auth():
                token = self.auth_handler.get_token()
                await self.client.start(token)
            else:
                print("\n[ERROR] Email/password login not supported")
                print("  Please use a token. See .env.example for instructions.")
                return 1
        except discord.errors.LoginFailure as e:
            print(f"\n[ERROR] Login failed: {e}")
            print("  Your token may be expired. Get a fresh one from Discord browser.")
            return 1
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            await self.shutdown()
        
        return 0
    
    async def shutdown(self):
        """Graceful shutdown"""
        if not self.running:
            return
        
        self.running = False
        print("\n[SHUTDOWN] Cleaning up...")
        
        if self.client:
            await self.client.close()
        
        if self.hermes:
            await self.hermes.close()
        
        print("\n[FINAL STATS]")
        if self.rate_limiter:
            stats = self.rate_limiter.get_stats()
            print(f"  Messages sent today: {stats['sent_today']}/{stats['daily_quota']}")
            print(f"  Total sent: {stats['total_sent']}")
        
        print("\n[SHUTDOWN] Complete")


def main():
    """Entry point"""
    runner = SelfbotRunner()
    
    try:
        return asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user")
        return 0
    except Exception as e:
        print(f"\n[MAIN] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
