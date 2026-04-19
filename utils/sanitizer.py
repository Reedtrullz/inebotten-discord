#!/usr/bin/env python3
"""
Input Sanitization Module
Provides utilities to sanitize user input and prevent injection attacks
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def sanitize_text(text: str, max_length: int = 1000) -> str:
    """
    Sanitize user text input to prevent injection attacks
    
    Args:
        text: User input text
        max_length: Maximum allowed length
    
    Returns:
        Sanitized text
    """
    if not text:
        return ""
    
    # Remove null bytes and control characters (except \n, \r, \t)
    sanitized = ''.join(
        char for char in text 
        if ord(char) >= 32 or char in '\n\r\t'
    )
    
    # Remove potential log injection sequences
    sanitized = re.sub(r'[\r\n]+', ' ', sanitized)
    
    # Truncate to max length
    return sanitized[:max_length]


def sanitize_discord_mention(text: str) -> str:
    """
    Remove Discord mentions from text
    
    Args:
        text: Text containing Discord mentions
        
    Returns:
        Text with mentions removed
    """
    return re.sub(r'<@!?\\d+>', '', text)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal
    
    Args:
        filename: The filename to sanitize
        
    Returns:
        Sanitized filename
    """
    # Remove path separators
    sanitized = filename.replace('/', '').replace('\\', '')
    
    # Remove null bytes
    sanitized = ''.join(char for char in sanitized if ord(char) >= 32)
    
    # Remove control characters
    sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '._-')
    
    # Limit length
    return sanitized[:255]


def validate_message_content(content: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Discord message content
    
    Args:
        content: The message content to validate
        
    Returns:
        (is_valid, error_message)
    """
    if not content or not content.strip():
        return False, "Empty message"
    
    if len(content) > 2000:  # Discord limit
        return False, "Message too long"
    
    # Check for suspicious patterns
    suspicious_patterns = [
        r'\x00',  # Null bytes
        r'[\x01-\x08\x0b\x0c\x0e-\x1f]',  # Control chars
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, content):
            return False, "Invalid characters in message"
    
    return True, None


def sanitize_command_input(input_text: str) -> str:
    """
    Sanitize command input (more aggressive than text sanitization)
    
    Args:
        input_text: The command input to sanitize
        
    Returns:
        Sanitized command input
    """
    if not input_text:
        return ""
    
    # Remove all control characters
    sanitized = ''.join(
        char for char in input_text 
        if ord(char) >= 32 or char in ' \t\n\r'
    )
    
    # Remove potential command injection sequences
    sanitized = re.sub(r'[;&|`$()]', '', sanitized)
    
    # Truncate to reasonable length for commands
    return sanitized[:500]


def sanitize_url(url: str) -> str:
    """
    Sanitize URL to prevent SSRF attacks
    
    Args:
        url: The URL to sanitize
        
    Returns:
        Sanitized URL or empty string if invalid
    """
    if not url:
        return ""
    
    # Remove whitespace
    url = url.strip()
    
    # Basic URL validation
    if not re.match(r'^https?://', url):
        return ""
    
    # Remove potential SSRF patterns
    # Block internal/private IPs
    if re.search(r'@(localhost|127\.0\.0\.1|0\.0\.0\.0|::1|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', url):
        return ""
    
    # Block file:// protocol
    if url.startswith('file://'):
        return ""
    
    return url[:2048]  # Reasonable URL length limit


def sanitize_json_input(json_str: str) -> str:
    """
    Sanitize JSON input string
    
    Args:
        json_str: The JSON string to sanitize
        
    Returns:
        Sanitized JSON string
    """
    if not json_str:
        return ""
    
    # Remove control characters except whitespace
    sanitized = ''.join(
        char for char in json_str 
        if ord(char) >= 32 or char in '\t\n\r'
    )
    
    return sanitized[:10000]  # Reasonable JSON length limit


def validate_number_input(input_str: str, min_val: float = None, max_val: float = None) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Validate and parse number input
    
    Args:
        input_str: The input string to validate
        min_val: Minimum allowed value (optional)
        max_val: Maximum allowed value (optional)
        
    Returns:
        (is_valid, parsed_value, error_message)
    """
    if not input_str:
        return False, None, "Empty input"
    
    try:
        value = float(input_str)
        
        if min_val is not None and value < min_val:
            return False, None, f"Value must be at least {min_val}"
        
        if max_val is not None and value > max_val:
            return False, None, f"Value must be at most {max_val}"
        
        return True, value, None
    except ValueError:
        return False, None, "Invalid number format"


def sanitize_html(text: str) -> str:
    """
    Sanitize text to prevent XSS attacks (basic HTML escaping)
    
    Args:
        text: The text to sanitize
        
    Returns:
        Sanitized text with HTML special characters escaped
    """
    if not text:
        return ""
    
    # Escape HTML special characters
    text = text.replace('&', '&')
    text = text.replace('<', '<')
    text = text.replace('>', '>')
    text = text.replace('"', '"')
    text = text.replace("'", '&#x27;')
    
    return text


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Validate email address format
    
    Args:
        email: The email address to validate
        
    Returns:
        (is_valid, error_message)
    """
    if not email:
        return False, "Empty email"
    
    # Basic email validation
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False, "Invalid email format"
    
    if len(email) > 254:  # Maximum email length
        return False, "Email too long"
    
    return True, None


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to max length with suffix
    
    Args:
        text: The text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated string
    """
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix
