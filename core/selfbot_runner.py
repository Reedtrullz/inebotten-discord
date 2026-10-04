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

import discord

from core.config import get_config
from core.auth_handler import create_auth_handler
from core.rate_limiter import create_rate_limiter
from ai.connector_factory import create_ai_connector
from ai.response_generator import create_response_generator
from core.message_monitor import SelfbotClient


class SelfbotRunner:
    """Main runner class that orchestrates the selfbot"""
    
    def __init__(self):
        self.config = None
        self.auth_handler = None
        self.rate_limiter = None
        self.ai_connector = None
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
        
        # Show AI provider info
        ai_provider = self.config.get_ai_provider()
        if ai_provider == 'openrouter':
            print(f"  AI Provider: OpenRouter (model: {self.config.OPENROUTER_MODEL})")
        else:
            print(f"  AI Provider: LM Studio (URL: {self.config.HERMES_API_URL})")
        
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
        
        # Initialize AI connector (LM Studio or OpenRouter)
        print("\n[4/5] Initializing AI connector...")
        try:
            self.ai_connector = create_ai_connector(self.config)
            if ai_provider == 'openrouter':
                print(f"  OpenRouter API: {self.config.OPENROUTER_BASE_URL}")
                print(f"  Model: {self.config.OPENROUTER_MODEL}")
            else:
                print(f"  LM Studio API: {self.ai_connector.base_url}")
        except Exception as e:
            print(f"  ERROR: {e}")
            print(f"  Will use local response generator as fallback")
            self.ai_connector = None
        
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
        
        # Check AI connector
        if self.ai_connector:
            healthy, message = await self.ai_connector.check_health()
            if healthy:
                print(f"  ✓ AI Connector: {message}")
            else:
                print(f"  ⚠ AI Connector: {message}")
                print("    Will use local response generator as fallback")
        else:
            print("  ⚠ AI Connector: Not initialized")
            print("    Will use local response generator")
        
        print("  ✓ All components ready")
        return True
    
    def create_client(self):
        """Create the Discord client"""
        self.client = SelfbotClient(
            config=self.config,
            auth_handler=self.auth_handler,
            rate_limiter=self.rate_limiter,
            hermes_connector=self.ai_connector,  # Can be None
            response_generator=self.response_gen
        )
        
        # Set up signal handlers
        def signal_handler(sig, frame):
            print("\n[SIGNAL] Shutdown requested...")
            asyncio.create_task(self.shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def run(self):
        try:
            result = await self._run()
        finally:
            await self.shutdown()
        return result if self.shutdown_receipt['status'] == 'closed' else 2

    async def _run(self):
        """Main run loop"""
        if not self.setup():
            return 1
        
        if not await self.health_check():
            return 1
        
        self.create_client()
        await self.client.start_console()
        
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
    
    async def shutdown(self, deadline=None):
        """Graceful shutdown"""
        import time
        from utils.resource_shutdown import OwnedResources
        self.running = False
        if not hasattr(self, '_owned_resources'):
            self._owned_resources = OwnedResources()
            console = getattr(self.client, 'console_server', None)
            memory = getattr(self.client, '_process_memory_owner', None) or getattr(getattr(self.client, 'monitor', None), 'user_memory', None)
            if console is not None:
                from utils.logger import close_log_capture
                def close_console_capture():
                    close_log_capture()
                    console.store.close()
                self._owned_resources.add('console-capture-store', close_console_capture)
                from features import forecast_service
                if forecast_service._DEFAULT is not None:
                    self._owned_resources.add('console-forecasts', forecast_service._DEFAULT.close)
            if memory is not None:
                self._owned_resources.add('process-memory-store', memory._storage.aclose)
            if self.ai_connector is not None:
                self._owned_resources.add('ai-connector', self.ai_connector.close)
            if self.client is not None:
                self._owned_resources.add('discord-client', self.client.close)
        try:
            await self._owned_resources.close(deadline if deadline is not None else time.monotonic() + 10)
        finally:
            self.shutdown_receipt = self._owned_resources.receipt()

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
