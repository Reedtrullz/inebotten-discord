#!/usr/bin/env python3
"""
Authentication Handler for Discord Selfbot
Handles token-based and email/password authentication
"""

import os
import sys
from pathlib import Path

class AuthHandler:
    """
    Manages Discord authentication with support for:
    - Token-based auth (preferred, faster)
    - Email/password auth (fallback)
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
                "Set DISCORD_USER_TOKEN or both DISCORD_EMAIL and DISCORD_PASSWORD"
            )
        
        self.auth_method = creds['type']
        self.credentials = creds
        
        if self.auth_method == 'token':
            self._validate_token()
        else:
            self._validate_email_password()
    
    def _validate_token(self):
        """
        Validate Discord token format
        """
        token = self.credentials['token']
        
        # Basic format check - Discord tokens are typically 59+ chars
        # Format: base64(user_id).timestamp.hmac
        if len(token) < 50:
            print(f"[AUTH] WARNING: Token seems short ({len(token)} chars)")
            print("  Discord tokens are typically 59+ characters")
        
        # Check for dots (Discord tokens have 2 dots)
        parts = token.split('.')
        if len(parts) != 3:
            print(f"[AUTH] WARNING: Token format unusual (expected 3 parts, got {len(parts)})")
        
        print(f"[AUTH] Token authentication configured ({len(token)} chars)")
    
    def _validate_email_password(self):
        """
        Validate email/password format
        """
        email = self.credentials['email']
        password = self.credentials['password']
        
        if '@' not in email:
            print(f"[AUTH] WARNING: Email format looks invalid: {email}")
        
        if len(password) < 6:
            print(f"[AUTH] WARNING: Password seems very short")
        
        print(f"[AUTH] Email/password authentication configured ({email})")
    
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
        return self.auth_method == 'token'
    
    def get_token(self):
        """
        Get the token (only valid for token auth)
        """
        if self.auth_method == 'token':
            return self.credentials['token']
        return None
    
    def get_email_password(self):
        """
        Get email and password (only valid for email/password auth)
        """
        if self.auth_method == 'email/password':
            return (self.credentials['email'], self.credentials['password'])
        return None
    
    def get_auth_type(self):
        """
        Return current authentication type
        """
        return self.auth_method
    
    def is_token_auth(self):
        """
        Check if using token authentication
        """
        return self.auth_method == 'token'
    
    def get_masked_token(self):
        """
        Get token with middle characters hidden (for logging)
        """
        if self.auth_method != 'token':
            return None
        
        token = self.credentials['token']
        if len(token) <= 10:
            return "***"
        
        return token[:5] + "..." + token[-5:]
    
    def save_token_to_file(self, filepath=None):
        """
        Save token to a file for persistence
        """
        if self.auth_method != 'token':
            print("[AUTH] Cannot save: not using token auth")
            return False
        
        if filepath is None:
            filepath = Path.home() / '.hermes' / 'discord' / '.token'
        
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(filepath, 'w') as f:
                f.write(self.credentials['token'])
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
