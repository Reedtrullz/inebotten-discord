#!/usr/bin/env python3
"""
Configuration Module for Discord Selfbot
Centralized settings, defaults, and environment variables
"""

import os
from pathlib import Path
from datetime import timedelta


class Config:
    """
    Central configuration management with fallbacks
    Priority: .env file > Environment Variables > Defaults
    """

    def __init__(self):
        # Load .env file first
        self.load_env()

        # Discord Credentials
        self.DISCORD_TOKEN = os.getenv("DISCORD_USER_TOKEN")
        self.DISCORD_EMAIL = os.getenv("DISCORD_EMAIL")
        self.DISCORD_PASSWORD = os.getenv("DISCORD_PASSWORD")

        # Hermes API Configuration
        self.HERMES_API_URL = os.getenv(
            "HERMES_API_URL", "http://127.0.0.1:3000/api/chat"
        )

        # Rate Limiting (conservative to avoid flags)
        self.MAX_MSGS_PER_SECOND = int(os.getenv("MAX_MSGS_PER_SEC", 5))
        self.DAILY_QUOTA = int(os.getenv("DAILY_QUOTA", 10000))
        self.SAFE_INTERVAL = timedelta(seconds=int(os.getenv("SAFE_INTERVAL", 1)))

        # Monitoring
        self.POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 8))  # seconds

        # Hermes Integration
        self.HERMES_MAX_REQ_PER_MIN = int(os.getenv("HERMES_MAX_REQ_PER_MIN", 60))
        self.HERMES_MAX_TOKENS = int(os.getenv("HERMES_MAX_TOKENS", 200))

        # THORNode Monitoring
        self.THORNODE_ADDRESS = os.getenv("THORNODE_ADDRESS", "")
        self.THORNODE_BOND_PROVIDER = os.getenv("THORNODE_BOND_PROVIDER", "")
        self.THORNODE_ALERT_CHANNEL_ID = os.getenv("THORNODE_ALERT_CHANNEL_ID", "")
        self.THORNODE_POLL_INTERVAL = int(os.getenv("THORNODE_POLL_INTERVAL", 300))

        self.validate()

    def load_env(self):
        """
        Load environment variables from .env file if it exists
        """
        env_path = Path.home() / ".hermes" / "discord" / ".env"
        if env_path.exists():
            print(f"[CONFIG] Loading settings from {env_path}")
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            value = value.strip()
                            # Remove quotes if present
                            if (value.startswith('"') and value.endswith('"')) or (
                                value.startswith("'") and value.endswith("'")
                            ):
                                value = value[1:-1]
                            os.environ[key] = value
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

    def get_hermes_url(self):
        """
        Get the Hermes API URL
        Returns: string URL
        """
        return self.HERMES_API_URL

    def get_auth_type(self) -> str:
        """
        Determine which authentication method is configured
        Returns: 'token' or 'email/password'
        """
        if self.DISCORD_TOKEN:
            return "token"
        elif self.DISCORD_EMAIL and self.DISCORD_PASSWORD:
            return "email/password"
        else:
            return "none"

    def get_auth_creds(self):
        """
        Get authentication credentials
        Returns: dict with token or email/password
        """
        if self.DISCORD_TOKEN:
            return {"type": "token", "token": self.DISCORD_TOKEN}
        elif self.DISCORD_EMAIL and self.DISCORD_PASSWORD:
            return {
                "type": "password",
                "email": self.DISCORD_EMAIL,
                "password": self.DISCORD_PASSWORD,
            }
        else:
            return None


def get_config() -> Config:
    """
    Get the global configuration instance (singleton)
    """
    if not hasattr(get_config, "_instance"):
        get_config._instance = Config()
    return get_config._instance
