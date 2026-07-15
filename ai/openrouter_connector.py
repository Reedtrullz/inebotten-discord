#!/usr/bin/env python3
"""
OpenRouter API Connector for Discord Selfbot
Handles communication with OpenRouter API for AI-powered responses
"""

import json
import asyncio
import aiohttp
import os
from typing import Optional, Dict, Any
from utils.logger import LoggerMixin


MAX_CONTEXT_PROMPT_CHARS = 4_000
MAX_AUTHOR_NAME_CHARS = 100
MAX_CHANNEL_TYPE_CHARS = 50


def _require_utf8(value: str, *, code: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(code) from None


def _serialize_untrusted_context(
    *,
    author_name: str,
    channel_type: str,
    context_prompt: str,
    is_mention: bool,
) -> str:
    def serialize(context_value: str) -> str:
        return json.dumps(
            {
                "author_name": author_name,
                "channel_type": channel_type,
                "context": context_value,
                "is_mention": is_mention,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    serialized = serialize(context_prompt)
    if len(serialized) <= MAX_CONTEXT_PROMPT_CHARS:
        return serialized

    low = 0
    high = len(context_prompt)
    while low < high:
        middle = (low + high + 1) // 2
        if len(serialize(context_prompt[:middle])) <= MAX_CONTEXT_PROMPT_CHARS:
            low = middle
        else:
            high = middle - 1
    return serialize(context_prompt[:low])


def _extract_openrouter_content(response_json: object) -> str:
    if not isinstance(response_json, dict):
        raise ValueError("invalid_response_shape")
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("invalid_response_shape")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("invalid_response_shape")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("invalid_response_shape")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("invalid_response_shape")
    return content


def build_openrouter_messages(
    *,
    message_content: str,
    system_prompt: str,
    context_prompt: str,
    model: str,
    author_name: str | None = None,
    channel_type: str | None = None,
    is_mention: bool | None = None,
) -> list[dict[str, str]]:
    """Build a provider request without crossing trusted-data boundaries."""
    if not isinstance(context_prompt, str) or len(context_prompt) > MAX_CONTEXT_PROMPT_CHARS:
        raise ValueError("invalid_context_prompt")
    _require_utf8(context_prompt, code="invalid_context_prompt")

    untrusted_context = context_prompt
    if any(value is not None for value in (author_name, channel_type, is_mention)):
        if not isinstance(author_name, str) or len(author_name) > MAX_AUTHOR_NAME_CHARS:
            raise ValueError("invalid_author_name")
        if not isinstance(channel_type, str) or len(channel_type) > MAX_CHANNEL_TYPE_CHARS:
            raise ValueError("invalid_channel_type")
        if not isinstance(is_mention, bool):
            raise ValueError("invalid_is_mention")
        _require_utf8(author_name, code="invalid_author_name")
        _require_utf8(channel_type, code="invalid_channel_type")
        untrusted_context = _serialize_untrusted_context(
            author_name=author_name,
            channel_type=channel_type,
            context_prompt=context_prompt,
            is_mention=is_mention,
        )

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({
            "role": "user" if model.startswith("google/gemma") else "system",
            "content": system_prompt,
        })
    if untrusted_context:
        messages.append({
            "role": "user",
            "content": f"UNTRUSTED_CONTEXT_DATA\n{untrusted_context}",
        })
    messages.append({"role": "user", "content": message_content})
    return messages


class OpenRouterConnector(LoggerMixin):
    """
    Connects to OpenRouter API for AI-powered response generation
    Uses OpenAI-compatible API format
    """

    def __init__(
        self,
        api_key: str,
        model: str = "google/gemma-4-31b-it:free",
        temperature: float = 0.7,
        max_tokens: int = 600,
        base_url: str = "https://openrouter.ai/api/v1"
    ):
        """
        Initialize OpenRouter connector
        
        Args:
            api_key: OpenRouter API key
            model: Model identifier (e.g., "google/gemma-3-4b-it:free")
            temperature: Temperature for response creativity (0.0-1.0)
            max_tokens: Maximum tokens for response length
            base_url: OpenRouter API base URL
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")
        self.session = None
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
        
        # Load system prompt
        self.default_system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        """Load the Norwegian system prompt from file"""
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), 'system_prompt_12b.txt')
            if os.path.exists(prompt_path):
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    prompt = f.read()
                    self.logger.info("openrouter_system_prompt_loaded")
                    return prompt
            else:
                self.logger.warning("openrouter_system_prompt_missing")
                return "Du er en hjelpsom norsk assistent som svarer på norsk."
        except Exception:
            self.logger.error("openrouter_system_prompt_load_failed")
            return "Du er en hjelpsom norsk assistent som svarer på norsk."

    async def _get_session(self):
        """
        Get or create aiohttp session with proper timeout configuration
        """
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(
                total=60,      # Total request timeout (longer for LLM)
                connect=10,   # Connection timeout
                sock_read=50  # Socket read timeout
            )
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Reedtrullz/inebotten-discord",
                "X-Title": "Inebotten Discord Bot",
            }
            self.session = aiohttp.ClientSession(
                headers=headers,
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

    async def _make_request(
        self,
        endpoint: str,
        method: str = "POST",
        payload: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, Any]:
        """
        Make API request with comprehensive error handling
        
        Args:
            endpoint: API endpoint
            method: HTTP method
            payload: Request payload
            
        Returns:
            (success, response_data or error_message)
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/{endpoint}"
            
            if method.upper() == "POST":
                async with session.post(url, json=payload) as response:
                    return await self._handle_response(response)
            else:
                async with session.get(url) as response:
                    return await self._handle_response(response)
                    
        except asyncio.TimeoutError:
            self.error_count += 1
            self.last_error = "Request timeout"
            self.logger.error("openrouter_request_timeout")
            return False, "Request timeout (60s)"
            
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = f"Connection error: {type(e).__name__}"
            self.logger.error(f"openrouter_connection_error:{type(e).__name__}")
            return False, f"Cannot connect to OpenRouter: {type(e).__name__}"
            
        except aiohttp.ClientError as e:
            self.error_count += 1
            self.last_error = f"Client error: {type(e).__name__}"
            self.logger.error(f"openrouter_client_error:{type(e).__name__}")
            return False, f"HTTP error: {type(e).__name__}"
            
        except json.JSONDecodeError:
            self.error_count += 1
            self.last_error = "JSON decode error"
            self.logger.error("openrouter_invalid_json")
            return False, "Invalid response format"
            
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Unexpected error: {type(e).__name__}"
            self.logger.error(f"openrouter_unexpected_error:{type(e).__name__}")
            return False, f"Request error: {type(e).__name__}"

    async def _handle_response(self, response: aiohttp.ClientResponse) -> tuple[bool, Any]:
        """
        Handle HTTP response with proper error handling
        
        Args:
            response: The aiohttp response object
            
        Returns:
            (success, response_data or error_message)
        """
        self.logger.debug(f"openrouter_response_status:{response.status}")
        
        if response.status == 200:
            try:
                data = await response.json()
                return True, data
            except json.JSONDecodeError:
                text = await response.text()
                self.logger.warning("openrouter_non_json_response")
                return True, text
                
        elif response.status == 401:
            self.error_count += 1
            self.last_error = "Unauthorized - Invalid API key"
            self.logger.error("openrouter_unauthorized")
            return False, "Invalid API key"
            
        elif response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            self.error_count += 1
            self.last_error = f"Rate limited (retry after {retry_after}s)"
            self.logger.warning(f"openrouter_rate_limited:{retry_after}")
            return False, f"Rate limited (retry after {retry_after}s)"
            
        elif response.status >= 500:
            self.error_count += 1
            self.last_error = f"Server error {response.status}"
            await response.text()
            self.logger.error(f"openrouter_server_error:{response.status}")
            return False, f"Server error (status {response.status})"
            
        else:
            self.error_count += 1
            self.last_error = f"HTTP {response.status}"
            await response.text()
            self.logger.error(f"openrouter_http_error:{response.status}")
            return False, f"API error (status {response.status})"

    async def check_health(self):
        """
        Check if OpenRouter API is reachable
        Returns: (is_healthy, message)
        """
        try:
            # Try to get available models as a health check
            success, result = await self._make_request("models", method="GET")
            if success:
                return True, f"API reachable (using model: {self.model})"
            else:
                return False, result
        except Exception as e:
            return False, f"Health check error: {type(e).__name__}"

    async def generate_response(
        self,
        message_content: str,
        author_name: str,
        channel_type: str,
        is_mention: bool = True,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        context_prompt: str = "",
    ) -> tuple[bool, str]:
        """
        Send message to OpenRouter API and get AI-generated response

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
            prompt = system_prompt or self.default_system_prompt
            messages = build_openrouter_messages(
                message_content=message_content,
                system_prompt=prompt,
                context_prompt=context_prompt,
                model=self.model,
                author_name=author_name,
                channel_type=channel_type,
                is_mention=is_mention,
            )
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature if temperature is not None else self.temperature,
                "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            }

            self.request_count += 1
            self.logger.info("openrouter_request_started")

            success, result = await self._make_request("chat/completions", method="POST", payload=payload)
            
            if success and isinstance(result, dict):
                try:
                    response_text = _extract_openrouter_content(result)
                except ValueError:
                    self.error_count += 1
                    self.last_error = "Invalid response shape"
                    self.logger.error("openrouter_invalid_response_shape")
                    return False, "Invalid response format"
                else:
                    self.logger.info("openrouter_response_received")
                    return True, response_text
            else:
                return success, result

        except Exception as e:
            self.error_count += 1
            self.last_error = f"Generate error: {type(e).__name__}"
            self.logger.error(f"openrouter_generate_error:{type(e).__name__}")
            return False, f"Request error: {type(e).__name__}"

    async def generate_calendar_response(self, query: str, author_name: str) -> tuple[bool, str]:
        """
        Generate a calendar/almanac response specifically

        This is a convenience method that adds context to help the AI
        understand this is a calendar/almanac request
        """
        enhanced_message = f"[Calendar/Almanac Query] {query}"
        return await self.generate_response(
            message_content=enhanced_message,
            author_name=author_name,
            channel_type="GROUP_DM",
            is_mention=True,
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get connector statistics
        """
        return {
            "provider": "openrouter",
            "model": self.model,
            "requests": self.request_count,
            "errors": self.error_count,
            "success_rate": (
                (self.request_count - self.error_count) / max(1, self.request_count)
            ) * 100,
            "last_error": self.last_error,
        }


def create_openrouter_connector(config) -> OpenRouterConnector:
    """
    Factory function to create OpenRouterConnector from config
    
    Args:
        config: Configuration object with OpenRouter settings
        
    Returns:
        OpenRouterConnector instance
    """
    api_key = getattr(config, 'OPENROUTER_API_KEY', None)
    model = getattr(config, 'OPENROUTER_MODEL', 'google/gemma-4-31b-it:free')
    temperature = getattr(config, 'OPENROUTER_TEMPERATURE', 0.7)
    max_tokens = getattr(config, 'OPENROUTER_MAX_TOKENS', 600)
    base_url = getattr(config, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not configured")
    
    return OpenRouterConnector(
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url
    )
