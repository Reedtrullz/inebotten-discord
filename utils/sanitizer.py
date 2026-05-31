#!/usr/bin/env python3
"""
Input Sanitization Module
Provides utilities to sanitize user input and prevent injection attacks
"""

import html
import ipaddress
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


_LEGACY_IPV4_PART_RE = re.compile(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)\Z")


def _parse_legacy_ipv4_part(part: str) -> int:
    if part.lower().startswith("0x"):
        return int(part, 16)
    if len(part) > 1 and part.startswith("0"):
        return int(part, 8)
    return int(part, 10)


def _parse_legacy_ipv4_host(host: str) -> ipaddress.IPv4Address | None:
    """Parse IPv4 forms accepted by some resolvers but rejected by ipaddress."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    if not all(part and _LEGACY_IPV4_PART_RE.fullmatch(part) for part in parts):
        return None

    try:
        numbers = [_parse_legacy_ipv4_part(part) for part in parts]
    except ValueError:
        return None

    try:
        if len(numbers) == 1:
            return ipaddress.IPv4Address(numbers[0])
        if len(numbers) == 2 and numbers[0] <= 0xFF and numbers[1] <= 0xFFFFFF:
            return ipaddress.IPv4Address((numbers[0] << 24) | numbers[1])
        if len(numbers) == 3 and numbers[0] <= 0xFF and numbers[1] <= 0xFF and numbers[2] <= 0xFFFF:
            return ipaddress.IPv4Address((numbers[0] << 24) | (numbers[1] << 16) | numbers[2])
        if len(numbers) == 4 and all(number <= 0xFF for number in numbers):
            return ipaddress.IPv4Address(
                (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
            )
    except ipaddress.AddressValueError:
        return None

    return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


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
    return re.sub(r'<@!?\d+>|<@&\d+>|@(?:everyone|here)\b', '', text)


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
    """Sanitize URL to prevent SSRF attacks."""
    if not url:
        return ""

    url = url.strip()[:2048]
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        return ""

    if parsed.scheme not in {"http", "https"}:
        return ""
    if not hostname:
        return ""

    host = hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        return ""

    legacy_ipv4 = _parse_legacy_ipv4_host(host)
    if legacy_ipv4 is not None:
        return "" if _is_blocked_ip(legacy_ipv4) else url

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url

    if _is_blocked_ip(ip):
        return ""

    return url


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
    return html.escape(text, quote=True)


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
