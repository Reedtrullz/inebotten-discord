#!/usr/bin/env python3
"""
Secure Token Storage Module
Provides secure storage for sensitive tokens using system keychain or encrypted files
"""

import os
import logging
from pathlib import Path
from typing import Optional

# Try to import keyring for system keychain storage
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logging.warning("keyring library not available, falling back to encrypted file storage")

# Try to import cryptography for file encryption
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logging.warning("cryptography library not available, encryption disabled")


logger = logging.getLogger(__name__)


class SecureTokenStorage:
    """Store tokens securely using system keychain or encrypted files"""
    
    SERVICE_NAME = "inebotten-discord"
    TOKEN_KEY = "discord_token"
    
    def __init__(self):
        self.storage_dir = Path.home() / '.hermes' / 'discord'
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def save_token(self, token: str) -> bool:
        """
        Save token to system keychain (preferred) or encrypted file (fallback)
        
        Args:
            token: The token to save
            
        Returns:
            True if successful, False otherwise
        """
        if not token:
            logger.error("Cannot save empty token")
            return False
        
        # Try system keychain first
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(
                    SecureTokenStorage.SERVICE_NAME,
                    SecureTokenStorage.TOKEN_KEY,
                    token
                )
                logger.info("Token saved to system keychain")
                return True
            except Exception as e:
                logger.warning(f"Failed to save token to keychain: {e}, falling back to encrypted file")
        
        # Fallback to encrypted file storage
        if CRYPTO_AVAILABLE:
            return self._save_token_encrypted(token)
        else:
            # Last resort: save with restricted permissions (not ideal but better than nothing)
            return self._save_token_plaintext(token)
    
    def get_token(self) -> Optional[str]:
        """
        Retrieve token from system keychain (preferred) or encrypted file (fallback)
        
        Returns:
            The token if found, None otherwise
        """
        # Try system keychain first
        if KEYRING_AVAILABLE:
            try:
                token = keyring.get_password(
                    SecureTokenStorage.SERVICE_NAME,
                    SecureTokenStorage.TOKEN_KEY
                )
                if token:
                    logger.info("Token retrieved from system keychain")
                    return token
            except Exception as e:
                logger.warning(f"Failed to retrieve token from keychain: {e}, trying encrypted file")
        
        # Fallback to encrypted file storage
        if CRYPTO_AVAILABLE:
            return self._get_token_encrypted()
        else:
            # Last resort: read from plaintext file
            return self._get_token_plaintext()
    
    def delete_token(self) -> bool:
        """
        Delete token from storage
        
        Returns:
            True if successful, False otherwise
        """
        # Try system keychain first
        if KEYRING_AVAILABLE:
            try:
                keyring.delete_password(
                    SecureTokenStorage.SERVICE_NAME,
                    SecureTokenStorage.TOKEN_KEY
                )
                logger.info("Token deleted from system keychain")
                return True
            except Exception as e:
                logger.warning(f"Failed to delete token from keychain: {e}")
        
        # Fallback to encrypted file storage
        if CRYPTO_AVAILABLE:
            return self._delete_token_encrypted()
        else:
            return self._delete_token_plaintext()
    
    def _save_token_encrypted(self, token: str) -> bool:
        """Save token encrypted to file"""
        try:
            # Generate encryption key
            key = Fernet.generate_key()
            fernet = Fernet(key)
            encrypted = fernet.encrypt(token.encode())
            
            # Save encrypted token
            token_path = self.storage_dir / '.token.enc'
            with open(token_path, 'wb') as f:
                f.write(encrypted)
            
            # Save key separately
            key_path = self.storage_dir / '.token.key'
            with open(key_path, 'wb') as f:
                f.write(key)
            
            # Set restrictive permissions
            os.chmod(token_path, 0o600)
            os.chmod(key_path, 0o600)
            
            logger.info(f"Token saved encrypted to {token_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save encrypted token: {e}")
            return False
    
    def _get_token_encrypted(self) -> Optional[str]:
        """Retrieve token from encrypted file"""
        try:
            token_path = self.storage_dir / '.token.enc'
            key_path = self.storage_dir / '.token.key'
            
            if not token_path.exists() or not key_path.exists():
                return None
            
            # Read key
            with open(key_path, 'rb') as f:
                key = f.read()
            
            # Read encrypted token
            with open(token_path, 'rb') as f:
                encrypted = f.read()
            
            # Decrypt
            fernet = Fernet(key)
            token = fernet.decrypt(encrypted).decode()
            
            logger.info("Token retrieved from encrypted file")
            return token
        except Exception as e:
            logger.error(f"Failed to retrieve encrypted token: {e}")
            return None
    
    def _delete_token_encrypted(self) -> bool:
        """Delete encrypted token file"""
        try:
            token_path = self.storage_dir / '.token.enc'
            key_path = self.storage_dir / '.token.key'
            
            if token_path.exists():
                token_path.unlink()
            if key_path.exists():
                key_path.unlink()
            
            logger.info("Encrypted token files deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete encrypted token: {e}")
            return False
    
    def _save_token_plaintext(self, token: str) -> bool:
        """Save token in plaintext with restricted permissions (NOT RECOMMENDED)"""
        try:
            token_path = self.storage_dir / '.token'
            with open(token_path, 'w') as f:
                f.write(token)
            
            # Set restrictive permissions
            os.chmod(token_path, 0o600)
            
            logger.warning(f"Token saved in plaintext to {token_path} (NOT SECURE)")
            return True
        except Exception as e:
            logger.error(f"Failed to save plaintext token: {e}")
            return False
    
    def _get_token_plaintext(self) -> Optional[str]:
        """Retrieve token from plaintext file"""
        try:
            token_path = self.storage_dir / '.token'
            
            if not token_path.exists():
                return None
            
            with open(token_path, 'r') as f:
                token = f.read().strip()
            
            logger.warning("Token retrieved from plaintext file (NOT SECURE)")
            return token
        except Exception as e:
            logger.error(f"Failed to retrieve plaintext token: {e}")
            return None
    
    def _delete_token_plaintext(self) -> bool:
        """Delete plaintext token file"""
        try:
            token_path = self.storage_dir / '.token'
            
            if token_path.exists():
                token_path.unlink()
            
            logger.info("Plaintext token file deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete plaintext token: {e}")
            return False
    
    def has_token(self) -> bool:
        """
        Check if a token is stored
        
        Returns:
            True if token exists, False otherwise
        """
        return self.get_token() is not None


def get_secure_storage() -> SecureTokenStorage:
    """
    Get a SecureTokenStorage instance
    
    Returns:
        SecureTokenStorage instance
    """
    return SecureTokenStorage()
