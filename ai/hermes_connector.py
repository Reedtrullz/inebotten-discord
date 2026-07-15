#!/usr/bin/env python3
"""
Hermes API Connector for Discord Selfbot
Handles communication with Hermes AI for intelligent responses
"""

import json
import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from typing import Any


# Load system prompt from file
DEFAULT_SYSTEM_PROMPT = None
MAX_CONTEXT_PROMPT_CHARS = 4_000
_LOGGER = logging.getLogger(__name__)


def build_hermes_payload(
    *,
    message_content: str,
    author_name: str,
    channel_type: str,
    is_mention: bool,
    system_prompt: str | None,
    temperature: float,
    max_tokens: int,
    timestamp: str,
    context_prompt: str = "",
) -> dict[str, object]:
    """Build a bridge payload without mutating or reclassifying provider data."""
    if not isinstance(context_prompt, str) or len(context_prompt) > MAX_CONTEXT_PROMPT_CHARS:
        raise ValueError("invalid_context_prompt")
    try:
        context_prompt.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("invalid_context_prompt") from None

    payload: dict[str, object] = {
        "message": message_content,
        "author_name": author_name,
        "channel_type": channel_type,
        "timestamp": timestamp,
        "is_mention": is_mention,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if context_prompt:
        payload["context_prompt"] = context_prompt
    return payload


def load_system_prompt(model_size="12b"):
    """Load the Norwegian system prompt from file
    
    Args:
        model_size: "4b" or "12b" - determines which prompt to load
    """
    global DEFAULT_SYSTEM_PROMPT
    if DEFAULT_SYSTEM_PROMPT is not None:
        return DEFAULT_SYSTEM_PROMPT
    
    # Choose prompt file based on model size
    if model_size == "12b":
        prompt_filename = 'system_prompt_12b.txt'
    else:
        prompt_filename = 'system_prompt.txt'
    
    # Look for system prompt in same directory as this file
    prompt_path = os.path.join(os.path.dirname(__file__), prompt_filename)
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            DEFAULT_SYSTEM_PROMPT = f.read()
            _LOGGER.info("hermes_system_prompt_loaded")
            return DEFAULT_SYSTEM_PROMPT
    except FileNotFoundError:
        # Fallback to default prompt
        fallback_path = os.path.join(os.path.dirname(__file__), 'system_prompt.txt')
        try:
            with open(fallback_path, 'r', encoding='utf-8') as f:
                DEFAULT_SYSTEM_PROMPT = f.read()
                _LOGGER.info("hermes_fallback_system_prompt_loaded")
                return DEFAULT_SYSTEM_PROMPT
        except Exception:
            _LOGGER.error("hermes_system_prompt_missing")
            DEFAULT_SYSTEM_PROMPT = ""
            return DEFAULT_SYSTEM_PROMPT
    except Exception:
        _LOGGER.error("hermes_system_prompt_load_failed")
        DEFAULT_SYSTEM_PROMPT = ""
        return DEFAULT_SYSTEM_PROMPT


class HermesConnector:
    """
    Connects to Hermes API for AI-powered response generation
    Uses GET /api/chat?data={payload}
    """

    def __init__(self, base_url="http://127.0.0.1:3000/api/chat", temperature=0.7, max_tokens=500, model_size="12b"):
        self.base_url = base_url.rstrip("/")
        self.session = None
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Load system prompt optimized for model size (default to 12b)
        self.default_system_prompt = load_system_prompt(model_size)

    async def _get_session(self):
        """
        Get or create aiohttp session with proper timeout configuration
        """
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(
                total=30,      # Total request timeout
                connect=10,   # Connection timeout
                sock_read=20  # Socket read timeout
            )
            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "DiscordSelfbot/1.0 HermesConnector",
                    "Accept": "application/json",
                },
                timeout=timeout
            )
        return self.session

    async def close(self):
        """
        Close the HTTP session
        """
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def _make_request(self, url: str, method: str = "GET", payload: dict = None) -> tuple[bool, Any]:
        """
        Make API request with comprehensive error handling
        
        Args:
            url: The URL to request
            method: HTTP method (GET or POST)
            payload: Optional payload for POST requests
            
        Returns:
            (success, response_data or error_message)
        """
        try:
            session = await self._get_session()
            
            if method.upper() == "POST":
                async with session.post(url, json=payload) as response:
                    return await self._handle_response(response)
            else:
                async with session.get(url) as response:
                    return await self._handle_response(response)
                    
        except asyncio.TimeoutError:
            self.error_count += 1
            self.last_error = "Request timeout"
            _LOGGER.error("hermes_request_timeout")
            return False, "Request timeout (30s)"
            
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = f"Connection error: {type(e).__name__}"
            _LOGGER.error(f"hermes_connection_error:{type(e).__name__}")
            return False, f"Cannot connect to Hermes: {type(e).__name__}"
            
        except aiohttp.ClientError as e:
            self.error_count += 1
            self.last_error = f"Client error: {type(e).__name__}"
            _LOGGER.error(f"hermes_client_error:{type(e).__name__}")
            return False, f"HTTP error: {type(e).__name__}"
            
        except json.JSONDecodeError:
            self.error_count += 1
            self.last_error = "JSON decode error"
            _LOGGER.error("hermes_invalid_json")
            return False, "Invalid response format"
            
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Unexpected error: {type(e).__name__}"
            _LOGGER.error(f"hermes_unexpected_error:{type(e).__name__}")
            return False, f"Request error: {type(e).__name__}"

    async def _handle_response(self, response: aiohttp.ClientResponse) -> tuple[bool, Any]:
        """
        Handle HTTP response with proper error handling
        
        Args:
            response: The aiohttp response object
            
        Returns:
            (success, response_data or error_message)
        """
        _LOGGER.debug(f"hermes_response_status:{response.status}")
        
        if response.status == 200:
            try:
                data = await response.json()
                # Handle different response formats
                if isinstance(data, dict):
                    for field in ("response", "message", "content"):
                        if field in data and isinstance(data[field], str):
                            return True, data[field]
                elif isinstance(data, str):
                    return True, data

                self.error_count += 1
                self.last_error = "Invalid response shape"
                _LOGGER.error("hermes_invalid_response_shape")
                return False, "Invalid response format"
            except json.JSONDecodeError:
                # Non-JSON response
                _LOGGER.warning("hermes_non_json_response")
                text = await response.text()
                return True, text
                
        elif response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 5))
            self.error_count += 1
            self.last_error = f"Rate limited (retry after {retry_after}s)"
            _LOGGER.warning(f"hermes_rate_limited:{retry_after}")
            return False, f"Rate limited (retry after {retry_after}s)"
            
        elif response.status >= 500:
            self.error_count += 1
            self.last_error = f"Server error {response.status}"
            await response.text()
            _LOGGER.error(f"hermes_server_error:{response.status}")
            return False, f"Server error (status {response.status})"
            
        else:
            self.error_count += 1
            self.last_error = f"HTTP {response.status}"
            await response.text()
            _LOGGER.error(f"hermes_http_error:{response.status}")
            return False, f"API error (status {response.status})"

    async def check_health(self):
        """
        Check if Hermes API is reachable
        Returns: (is_healthy, message)
        """
        try:
            # Try a simple POST request to check connectivity
            test_payload = {
                "message": "health_check",
                "author_name": "selfbot",
                "channel_type": "health_check",
            }

            session = await self._get_session()
            async with session.post(self.base_url, json=test_payload) as response:
                if response.status != 200:
                    return False, f"API error (status {response.status})"
                try:
                    data = await response.json()
                except json.JSONDecodeError:
                    text = await response.text()
                    return True, text or "API reachable"

            status = str(data.get("status", "")).lower() if isinstance(data, dict) else ""
            if status in {"degraded", "unhealthy", "error"}:
                return False, data.get("response", status) if isinstance(data, dict) else status
            return True, data.get("response", "API reachable") if isinstance(data, dict) else "API reachable"

        except Exception as e:
            return False, f"Health check error: {type(e).__name__}"

    async def generate_response(
        self,
        message_content,
        author_name,
        channel_type,
        is_mention=True,
        system_prompt=None,
        temperature=None,
        max_tokens=None,
        context_prompt="",
    ):
        """
        Send message to Hermes API and get AI-generated response

        Args:
            message_content: The message text
            author_name: Name of the message author
            channel_type: 'DM', 'GROUP_DM', or 'GUILD_TEXT'
            is_mention: Whether the bot was mentioned
            system_prompt: Optional custom system prompt for personality
            temperature: Optional temperature (0.0-1.0) for response creativity
            max_tokens: Optional max tokens for response length
            context_prompt: Bounded untrusted context data

        Returns:
            (success, response_text or error_message)
        """
        try:
            selected_system_prompt = system_prompt or self.default_system_prompt
            selected_temperature = (
                temperature if temperature is not None else self.temperature
            )
            selected_max_tokens = (
                max_tokens if max_tokens is not None else self.max_tokens
            )
            timestamp = datetime.now().isoformat()
            payload = build_hermes_payload(
                message_content=message_content,
                author_name=author_name,
                channel_type=channel_type,
                is_mention=is_mention,
                system_prompt=selected_system_prompt,
                temperature=selected_temperature,
                max_tokens=selected_max_tokens,
                timestamp=timestamp,
                context_prompt=context_prompt,
            )

            self.request_count += 1
            success, result = await self._make_request(self.base_url, method="POST", payload=payload)
            return success, result

        except Exception as e:
            self.error_count += 1
            self.last_error = f"Generate error: {type(e).__name__}"
            _LOGGER.error(f"hermes_generate_error:{type(e).__name__}")
            return False, f"Request error: {type(e).__name__}"

    async def generate_calendar_response(self, query, author_name):
        """
        Generate a calendar/almanac response specifically

        This is a convenience method that adds context to help Hermes
        understand this is a calendar/almanac request
        """
        enhanced_message = f"[Calendar/Almanac Query] {query}"
        return await self.generate_response(
            message_content=enhanced_message,
            author_name=author_name,
            channel_type="GROUP_DM",
            is_mention=True,
        )

    def get_stats(self):
        """
        Get connector statistics
        """
        return {
            "requests": self.request_count,
            "errors": self.error_count,
            "success_rate": (
                (self.request_count - self.error_count) / max(1, self.request_count)
            )
            * 100,
            "last_error": self.last_error,
        }


def create_hermes_connector(config):
    """
    Factory function to create HermesConnector from config
    """
    # Get optional parameters from config with defaults
    temperature = getattr(config, 'HERMES_TEMPERATURE', 0.7)
    max_tokens = getattr(config, 'HERMES_MAX_TOKENS', 200)
    
    return HermesConnector(
        base_url=config.get_hermes_url(),
        temperature=temperature,
        max_tokens=max_tokens
    )
