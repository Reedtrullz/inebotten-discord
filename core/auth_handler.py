#!/usr/bin/env python3
"""
Authentication Handler for Discord Selfbot
Handles token-based Discord authentication
"""

import os
import sys
from pathlib import Path

from utils.json_storage import hermes_home_path


class AuthHandler:
    """
    Manages the supported Discord user-token authentication method.
    """

    def __init__(self, config):
        self.config = config
        self.auth_method = None
        self.credentials = None
        self._validate_auth()

    def _validate_auth(self):
        """
        Determine and validate authentication method
        """
        creds = self.config.get_auth_creds()

        if not creds:
            raise ValueError(
                "No Discord credentials configured!\n"
                "Set DISCORD_USER_TOKEN"
            )

        self.auth_method = creds["type"]
        if self.auth_method != "token":
            raise ValueError("Unsupported Discord authentication method; configure DISCORD_USER_TOKEN.")
        self.credentials = creds
        self._validate_token()

    def _validate_token(self):
        """
        Validate Discord token format
        """
        token = self.credentials["token"]

        # Basic format check - Discord tokens are typically 59+ chars
        # Format: base64(user_id).timestamp.hmac
        if len(token) < 50:
            print(f"[AUTH] WARNING: Token seems short ({len(token)} chars)")
            print("  Discord tokens are typically 59+ characters")

        # Check for dots (Discord tokens have 2 dots)
        parts = token.split(".")
        if len(parts) != 3:
            print(
                f"[AUTH] WARNING: Token format unusual (expected 3 parts, got {len(parts)})"
            )

        print(f"[AUTH] Token authentication configured ({len(token)} chars)")

    def get_discord_credentials(self):
        """
        Get credentials for discord.py client
        Returns: dict with connection info for the runner to handle
        """
        return self.credentials

    def is_token_auth(self):
        """
        Check if using token authentication
        """
        return self.auth_method == "token"

    def get_token(self):
        """
        Get the token (only valid for token auth)
        """
        if self.auth_method == "token":
            return self.credentials["token"]
        return None

    def get_email_password(self):
        """
        Retained for API compatibility; password authentication is unsupported.
        """
        return None

    def get_auth_type(self):
        """
        Return current authentication type
        """
        return self.auth_method

    def get_masked_token(self):
        """
        Get token with middle characters hidden (for logging)
        """
        if self.auth_method != "token":
            return None

        token = self.credentials["token"]
        if len(token) <= 10:
            return "***"

        return token[:5] + "..." + token[-5:]

    def save_token_to_file(self, filepath=None):
        """
        Save token to secure storage using system keychain or encrypted file
        
        Args:
            filepath: Optional filepath (ignored if keyring is available)
            
        Returns:
            True if successful, False otherwise
        """
        if self.auth_method != "token":
            print("[AUTH] Cannot save: not using token auth")
            return False

        try:
            from utils.secure_storage import get_secure_storage
            
            storage = get_secure_storage()
            success = storage.save_token(self.credentials["token"])
            
            if success:
                print("[AUTH] Token saved to secure storage")
            else:
                print("[AUTH] Failed to save token to secure storage")
            
            return success
        except ImportError:
            print("[AUTH] Secure storage not available, using fallback")
            return self._save_token_fallback(filepath)
        except Exception as e:
            print(f"[AUTH] Error saving token: {e}")
            return False
    
    def _save_token_fallback(self, filepath=None):
        """
        Fallback method to save token to file with restricted permissions
        """
        if filepath is None:
            filepath = hermes_home_path() / "discord" / ".token"

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(filepath, "w") as f:
                f.write(self.credentials["token"])
            # Restrict permissions
            os.chmod(filepath, 0o600)
            print(f"[AUTH] Token saved to {filepath}")
            return True
        except Exception as e:
            print(f"[AUTH] Error saving token: {e}")
            return False


def create_auth_handler(config):
    """
    Factory function to create AuthHandler
    """
    return AuthHandler(config)
