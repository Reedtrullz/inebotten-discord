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
import time

from ai.result_schema import (
    AIResult,
    BoundedAdmission,
    MAX_AI_PROMPT_CHARS,
    MAX_AI_TEXT_CHARS,
    parse_retry_after,
    read_provider_json,
)
from core.request_context import RequestContext


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

    def __init__(self, base_url="http://127.0.0.1:3000/api/chat", temperature=0.7, max_tokens=500, model_size="12b", api_key=None):
        self.base_url = base_url.rstrip("/")
        self.session = None
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
        self.provider = "hermes"
        self.model = model_size
        self._reply_admission = BoundedAdmission()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = (
            api_key.strip()
            if isinstance(api_key, str)
            else os.getenv("HERMES_BRIDGE_API_KEY", "").strip()
        )
        
        # Load system prompt optimized for model size (default to 12b)
        self.default_system_prompt = load_system_prompt(model_size)

    async def _get_session(self):
        if getattr(self, '_closed', False):
            raise RuntimeError('connector_closed')
        """
        Get or create aiohttp session with proper timeout configuration
        """
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(
                total=30,      # Total request timeout
                connect=10,   # Connection timeout
                sock_read=20  # Socket read timeout
            )
            headers = {
                "User-Agent": "DiscordSelfbot/1.0 HermesConnector",
                "Accept": "application/json",
            }
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout
            )
        return self.session

    async def close(self):
        """
        Close the HTTP session
        """
        self._closed = True
        admission = getattr(self, '_reply_admission', None)
        if admission is not None:
            await admission.close()
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def _make_request(self, url: str, method: str = "GET", payload: dict = None) -> AIResult:
        """
        Make API request with comprehensive error handling
        
        Args:
            url: The URL to request
            method: HTTP method (GET or POST)
            payload: Optional payload for POST requests
            
        Returns:
            A validated provider outcome.
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
            return AIResult("retryable", None, self.provider, self.model)
            
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = f"Connection error: {type(e).__name__}"
            print(f"[HERMES] Network error: {type(e).__name__}: {str(e)[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)
            
        except aiohttp.ClientError as e:
            self.error_count += 1
            self.last_error = f"Client error: {type(e).__name__}"
            print(f"[HERMES] HTTP client error: {type(e).__name__}: {str(e)[:100]}")
            return AIResult("retryable", None, self.provider, self.model)
            
        except json.JSONDecodeError as e:
            self.error_count += 1
            self.last_error = f"JSON decode error: {str(e)[:100]}"
            print(f"[HERMES] Invalid JSON response: {str(e)[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)
            
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Unexpected error: {type(e).__name__}"
            print(f"[HERMES] Unexpected error: {type(e).__name__}: {str(e)[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)

    async def _handle_response(self, response: aiohttp.ClientResponse) -> AIResult:
        """
        Handle HTTP response with proper error handling
        
        Args:
            response: The aiohttp response object
            
        Returns:
            A validated provider outcome.
        """
        print(f"[HERMES] Response status: {response.status}")
        
        if response.status == 200:
            try:
                data = await read_provider_json(response)
                print("[HERMES] Response payload received")
                # Handle different response formats
                if isinstance(data, dict):
                    if "response" in data:
                        result = data["response"]
                    elif "message" in data:
                        result = data["message"]
                    elif "content" in data:
                        result = data["content"]
                    else:
                        result = None
                else:
                    result = data
                if isinstance(result, str) and result.strip() and len(result) <= MAX_AI_TEXT_CHARS:
                    print(f"[HERMES] Using provider response ({len(result)} chars)")
                    return AIResult("success", result, self.provider, self.model)
                self.last_error = "Invalid or oversized response text"
                return AIResult("unavailable", None, self.provider, self.model)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self.last_error = "Invalid or oversized provider envelope"
                return AIResult("unavailable", None, self.provider, self.model)

        elif response.status == 429:
            retry_after = parse_retry_after(
                response.headers.get("Retry-After", 5), default=5.0
            )
            self.error_count += 1
            self.last_error = f"Rate limited (retry after {retry_after}s)"
            print(f"[HERMES] Rate limited, retry after {retry_after}s")
            return AIResult("busy", None, self.provider, self.model, retry_after_s=retry_after)
            
        elif response.status >= 500:
            self.error_count += 1
            self.last_error = f"Server error {response.status}"
            error_text = await response.text()
            print(f"[HERMES] Server error {response.status}: {error_text[:100]}")
            return AIResult("retryable", None, self.provider, self.model)

        elif response.status in (401, 403):
            self.error_count += 1
            self.last_error = f"Authentication error {response.status}"
            return AIResult("auth_error", None, self.provider, self.model)
            
        else:
            self.error_count += 1
            self.last_error = f"HTTP {response.status}"
            error_text = await response.text()
            print(f"[HERMES] HTTP error {response.status}: {error_text[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)

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

    async def generate_reply(
        self,
        context: RequestContext,
        prompt: str,
        *,
        deadline: float,
    ) -> AIResult:
        """Generate one response before an absolute monotonic deadline."""
        return await self._generate_reply(
            context,
            prompt,
            deadline=deadline,
            temperature=None,
            max_tokens=None,
            is_mention=True,
        )

    async def _generate_reply(
        self,
        context: RequestContext,
        prompt: str,
        *,
        deadline: float,
        temperature: float | None,
        max_tokens: int | None,
        is_mention: bool,
        system_prompt: str | None = None,
        author_name: str = "bruker",
    ) -> AIResult:
        if not isinstance(prompt, str) or len(prompt) > MAX_AI_PROMPT_CHARS:
            return AIResult("unavailable", None, self.provider, self.model)

        channel_types = {"dm": "DM", "group_dm": "GROUP_DM", "guild": "GUILD_TEXT"}
        payload = {
            "message": prompt,
            "author_name": author_name,
            "channel_type": channel_types.get(context.channel_kind, "UNKNOWN"),
            "timestamp": datetime.now().isoformat(),
            "is_mention": is_mention,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        selected_prompt = system_prompt or self.default_system_prompt
        if selected_prompt:
            payload["system_prompt"] = selected_prompt

        async def request():
            self.request_count += 1
            return await self._make_request(self.base_url, method="POST", payload=payload)

        return await self._reply_admission.run(
            request,
            deadline=deadline,
            provider=self.provider,
            model=self.model,
        )

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
        channel_kinds = {"DM": "dm", "GROUP_DM": "group_dm", "GUILD_TEXT": "guild"}
        context = RequestContext(
            request_id="legacy",
            user_id=str(author_name),
            channel_id="legacy",
            guild_id=None,
            locale="no",
            channel_kind=channel_kinds.get(str(channel_type).upper(), "unknown"),
        )
        prompt = str(message_content)
        result = await self._generate_reply(
            context,
            prompt,
            deadline=time.monotonic() + 30,
            temperature=temperature,
            max_tokens=max_tokens,
            is_mention=is_mention,
            system_prompt=system_prompt,
            author_name=str(author_name),
        )
        return result.legacy_tuple()

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
        max_tokens=max_tokens,
        api_key=getattr(config, "HERMES_BRIDGE_API_KEY", None),
    )
