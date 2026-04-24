#!/usr/bin/env python3
"""
Hermes API Connector for Discord Selfbot
Handles communication with Hermes AI for intelligent responses
"""

import json
import asyncio
import aiohttp
import os
from datetime import datetime
from urllib.parse import quote


# Load system prompt from file
DEFAULT_SYSTEM_PROMPT = None

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
            print(f"[HERMES] Loaded system prompt from {prompt_path}")
            return DEFAULT_SYSTEM_PROMPT
    except FileNotFoundError:
        # Fallback to default prompt
        fallback_path = os.path.join(os.path.dirname(__file__), 'system_prompt.txt')
        try:
            with open(fallback_path, 'r', encoding='utf-8') as f:
                DEFAULT_SYSTEM_PROMPT = f.read()
                print(f"[HERMES] Loaded fallback system prompt from {fallback_path}")
                return DEFAULT_SYSTEM_PROMPT
        except:
            print(f"[HERMES] System prompt file not found")
            DEFAULT_SYSTEM_PROMPT = ""
            return DEFAULT_SYSTEM_PROMPT
    except Exception as e:
        print(f"[HERMES] Error loading system prompt: {e}")
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

    async def _make_request(self, url: str, method: str = "GET", payload: dict = None) -> tuple[bool, any]:
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
            print(f"[HERMES] Request timed out after 30s")
            return False, "Request timeout (30s)"
            
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = f"Connection error: {type(e).__name__}"
            print(f"[HERMES] Network error: {type(e).__name__}: {str(e)[:100]}")
            return False, f"Cannot connect to Hermes: {type(e).__name__}"
            
        except aiohttp.ClientError as e:
            self.error_count += 1
            self.last_error = f"Client error: {type(e).__name__}"
            print(f"[HERMES] HTTP client error: {type(e).__name__}: {str(e)[:100]}")
            return False, f"HTTP error: {type(e).__name__}"
            
        except json.JSONDecodeError as e:
            self.error_count += 1
            self.last_error = f"JSON decode error: {str(e)[:100]}"
            print(f"[HERMES] Invalid JSON response: {str(e)[:100]}")
            return False, "Invalid response format"
            
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Unexpected error: {type(e).__name__}"
            print(f"[HERMES] Unexpected error: {type(e).__name__}: {str(e)[:100]}")
            return False, f"Request error: {type(e).__name__}"

    async def _handle_response(self, response: aiohttp.ClientResponse) -> tuple[bool, any]:
        """
        Handle HTTP response with proper error handling
        
        Args:
            response: The aiohttp response object
            
        Returns:
            (success, response_data or error_message)
        """
        print(f"[HERMES] Response status: {response.status}")
        
        if response.status == 200:
            try:
                data = await response.json()
                print(f"[HERMES] Response data: {str(data)[:150]}...")
                # Handle different response formats
                if isinstance(data, dict):
                    if "response" in data:
                        print(f"[HERMES] Using 'response' field: {data['response'][:80]}...")
                        return True, data["response"]
                    elif "message" in data:
                        return True, data["message"]
                    elif "content" in data:
                        return True, data["content"]
                    else:
                        return True, str(data)
                else:
                    return True, str(data)
            except json.JSONDecodeError as e:
                # Non-JSON response
                print(f"[HERMES] Response parse error: {e}")
                text = await response.text()
                return True, text
                
        elif response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 5))
            self.error_count += 1
            self.last_error = f"Rate limited (retry after {retry_after}s)"
            print(f"[HERMES] Rate limited, retry after {retry_after}s")
            return False, f"Rate limited (retry after {retry_after}s)"
            
        elif response.status >= 500:
            self.error_count += 1
            self.last_error = f"Server error {response.status}"
            error_text = await response.text()
            print(f"[HERMES] Server error {response.status}: {error_text[:100]}")
            return False, f"Server error (status {response.status})"
            
        else:
            self.error_count += 1
            self.last_error = f"HTTP {response.status}"
            error_text = await response.text()
            print(f"[HERMES] HTTP error {response.status}: {error_text[:100]}")
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

            success, result = await self._make_request(self.base_url, method="POST", payload=test_payload)
            if success:
                return True, f"API reachable"
            else:
                return False, result

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

        Returns:
            (success, response_text or error_message)
        """
        # Build payload
        payload = {
            "message": message_content,
            "author_name": author_name,
            "channel_type": channel_type,
            "timestamp": datetime.now().isoformat(),
            "is_mention": is_mention,
        }

        # Add system prompt (use provided, or default, or none)
        if system_prompt:
            payload["system_prompt"] = system_prompt
        elif self.default_system_prompt:
            payload["system_prompt"] = self.default_system_prompt
            
        # Add temperature and max_tokens if specified
        if temperature is not None:
            payload["temperature"] = temperature
        else:
            payload["temperature"] = self.temperature
            
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        else:
            payload["max_tokens"] = self.max_tokens

        try:
            self.request_count += 1
            success, result = await self._make_request(self.base_url, method="POST", payload=payload)
            return success, result

        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            print(f"[HERMES] Unexpected error in generate_response: {type(e).__name__}: {str(e)[:100]}")
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
