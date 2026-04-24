#!/usr/bin/env python3
"""
Configuration Module for Discord Selfbot
Centralized settings, defaults, and environment variables
"""

import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

class Config:
    """
    Central configuration management with fallbacks
    Priority: .env file > Environment Variables > Defaults
    """
    
    def __init__(self):
        # Load .env file first
        self.load_env()
        
        # Discord Credentials
        self.DISCORD_TOKEN = os.getenv('DISCORD_USER_TOKEN')
        self.DISCORD_EMAIL = os.getenv('DISCORD_EMAIL')
        self.DISCORD_PASSWORD = os.getenv('DISCORD_PASSWORD')
        
        # AI Provider Selection
        # Options: "lm_studio" (default) or "openrouter"
        self.AI_PROVIDER = os.getenv('AI_PROVIDER', 'lm_studio')
        
        # LM Studio Configuration (default)
        self.HERMES_API_URL = os.getenv('HERMES_API_URL', 'http://127.0.0.1:3000/api/chat')
        self.HERMES_TEMPERATURE = float(os.getenv('HERMES_TEMPERATURE', '0.7'))
        self.HERMES_MAX_TOKENS = int(os.getenv('HERMES_MAX_TOKENS', '200'))
        
        # OpenRouter Configuration
        self.OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
        self.OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'google/gemma-3-4b-it:free')
        self.OPENROUTER_TEMPERATURE = float(os.getenv('OPENROUTER_TEMPERATURE', '0.7'))
        self.OPENROUTER_MAX_TOKENS = int(os.getenv('OPENROUTER_MAX_TOKENS', '200'))
        self.OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
        
        # Google Calendar Configuration
        self.GCAL_ENABLED = os.getenv('GCAL_ENABLED', 'False').lower() == 'true'
        self.GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
        
        # Rate Limiting (conservative to avoid flags)
        self.MAX_MSGS_PER_SECOND = int(os.getenv('MAX_MSGS_PER_SEC', 5))
        self.DAILY_QUOTA = int(os.getenv('DAILY_QUOTA', 10000))
        self.SAFE_INTERVAL = timedelta(seconds=int(os.getenv('SAFE_INTERVAL', 1)))
        
        # Monitoring
        self.POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', 8))  # seconds
        
        # Hermes Integration (legacy, kept for compatibility)
        self.HERMES_MAX_REQ_PER_MIN = int(os.getenv('HERMES_MAX_REQ_PER_MIN', 60))
        
        self.validate()
    
    def load_env(self):
        """
        Load environment variables from .env file if it exists
        Uses python-dotenv for robust parsing
        """
        env_paths = [
            Path('.env'),  # Current directory
            Path.home() / '.hermes' / 'discord' / '.env',  # User home
        ]
        
        for env_path in env_paths:
            if env_path.exists():
                try:
                    load_dotenv(env_path)
                    print(f"[CONFIG] Loaded settings from {env_path}")
                    break
                except Exception as e:
                    print(f"[CONFIG] Warning: Could not load .env file: {e}")
    
    def validate(self):
        """
        Validate configuration - ensure we have at least one auth method
        """
        has_token = bool(self.DISCORD_TOKEN)
        has_email_password = bool(self.DISCORD_EMAIL and self.DISCORD_PASSWORD)
        
        if not has_token and not has_email_password:
            print("[CONFIG] WARNING: No Discord credentials configured!")
            print("  Please set one of the following:")
            print("    - DISCORD_USER_TOKEN (preferred)")
            print("    - OR both DISCORD_EMAIL and DISCORD_PASSWORD")
        
        if not self.DISCORD_TOKEN and has_email_password:
            print("[CONFIG] Using username/password auth (slower than token)")
        
        # Validate AI provider configuration
        if self.AI_PROVIDER == 'openrouter':
            if not self.OPENROUTER_API_KEY:
                print("[CONFIG] WARNING: AI_PROVIDER is 'openrouter' but OPENROUTER_API_KEY is not set!")
                print("  Falling back to LM Studio...")
                self.AI_PROVIDER = 'lm_studio'
            else:
                print(f"[CONFIG] Using OpenRouter API (model: {self.OPENROUTER_MODEL})")
        else:
            print(f"[CONFIG] Using LM Studio (URL: {self.HERMES_API_URL})")
    
    def get_hermes_url(self):
        """
        Get the Hermes API URL (legacy method)
        Returns: string URL
        """
        return self.HERMES_API_URL
    
    def get_auth_type(self) -> str:
        """
        Determine which authentication method is configured
        Returns: 'token' or 'email/password'
        """
        if self.DISCORD_TOKEN:
            return 'token'
        elif self.DISCORD_EMAIL and self.DISCORD_PASSWORD:
            return 'email/password'
        else:
            return 'none'
    
    def get_auth_creds(self):
        """
        Get authentication credentials
        Returns: dict with token or email/password
        """
        if self.DISCORD_TOKEN:
            return {'type': 'token', 'token': self.DISCORD_TOKEN}
        elif self.DISCORD_EMAIL and self.DISCORD_PASSWORD:
            return {
                'type': 'password',
                'email': self.DISCORD_EMAIL,
                'password': self.DISCORD_PASSWORD
            }
        else:
            return None
    
    def get_ai_provider(self) -> str:
        """
        Get the configured AI provider
        Returns: 'lm_studio' or 'openrouter'
        """
        return self.AI_PROVIDER
    
    def is_using_openrouter(self) -> bool:
        """
        Check if using OpenRouter API
        Returns: True if using OpenRouter, False otherwise
        """
        return self.AI_PROVIDER == 'openrouter'

def get_config() -> Config:
    """
    Get the global configuration instance (singleton)
    """
    if not hasattr(get_config, '_instance'):
        get_config._instance = Config()
    return get_config._instance
