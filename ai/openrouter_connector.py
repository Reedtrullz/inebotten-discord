#!/usr/bin/env python3
"""
OpenRouter API Connector for Discord Selfbot
Handles communication with OpenRouter API for AI-powered responses
"""

import json
import asyncio
import aiohttp
import os
import time
import ssl
import certifi
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import quote
from utils.logger import LoggerMixin
from ai.result_schema import (
    AIResult,
    BoundedAdmission,
    MAX_AI_PROMPT_CHARS,
    MAX_AI_TEXT_CHARS,
    parse_retry_after,
    read_provider_json,
)
from core.request_context import RequestContext


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
        base_url: str = "https://openrouter.ai/api/v1",
        reasoning_enabled: bool | None = None,
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
        if reasoning_enabled is not None and not isinstance(reasoning_enabled, bool):
            raise ValueError('reasoning_enabled must be a boolean or None')
        self.reasoning_enabled = reasoning_enabled
        self.session = None
        self.request_count = 0
        self.error_count = 0
        self.last_error = None
        self.provider = "openrouter"
        self._reply_admission = BoundedAdmission()
        
        # Load system prompt
        self.default_system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        """Load the Norwegian system prompt from file"""
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), 'system_prompt_12b.txt')
            if os.path.exists(prompt_path):
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    prompt = f.read()
                    self.logger.info(f"Loaded system prompt from {prompt_path}")
                    return prompt
            else:
                self.logger.warning("System prompt file not found, using default")
                return "Du er en hjelpsom norsk assistent som svarer på norsk."
        except Exception as e:
            self.logger.error(f"Error loading system prompt: {e}")
            return "Du er en hjelpsom norsk assistent som svarer på norsk."

    async def _get_session(self):
        if getattr(self, '_closed', False):
            raise RuntimeError('connector_closed')
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
                timeout=timeout,
                # Frozen Python cannot rely on the build host's external CA
                # path. Add the pinned bundle while retaining system roots.
                connector=aiohttp.TCPConnector(ssl=self._tls_context()),
            )
        return self.session

    @staticmethod
    def _tls_context():
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        return context

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

    async def _make_request(
        self,
        endpoint: str,
        method: str = "POST",
        payload: Optional[Dict[str, Any]] = None
    ) -> AIResult:
        """
        Make API request with comprehensive error handling
        
        Args:
            endpoint: API endpoint
            method: HTTP method
            payload: Request payload
            
        Returns:
            A validated provider outcome.
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/{endpoint}"
            
            if method.upper() == "POST":
                async with session.post(url, json=payload) as response:
                    return await self._handle_response(response, expect_text=method.upper() == "POST")
            else:
                async with session.get(url) as response:
                    return await self._handle_response(response, expect_text=False)
                    
        except asyncio.TimeoutError:
            self.error_count += 1
            self.last_error = "Request timeout"
            self.logger.error(f"Request timed out after 60s")
            return AIResult("retryable", None, self.provider, self.model)
            
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = f"Connection error: {type(e).__name__}"
            self.logger.error(f"Network error: {type(e).__name__}: {str(e)[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)
            
        except aiohttp.ClientError as e:
            self.error_count += 1
            self.last_error = f"Client error: {type(e).__name__}"
            self.logger.error(f"HTTP client error: {type(e).__name__}: {str(e)[:100]}")
            return AIResult("retryable", None, self.provider, self.model)
            
        except json.JSONDecodeError as e:
            self.error_count += 1
            self.last_error = f"JSON decode error: {str(e)[:100]}"
            self.logger.error(f"Invalid JSON response: {str(e)[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)
            
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Unexpected error: {type(e).__name__}"
            self.logger.error(f"Unexpected error: {type(e).__name__}: {str(e)[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)

    async def _handle_response(
        self, response: aiohttp.ClientResponse, *, expect_text: bool = True
    ) -> AIResult:
        """
        Handle HTTP response with proper error handling
        
        Args:
            response: The aiohttp response object
            
        Returns:
            A validated provider outcome.
        """
        self.logger.debug(f"Response status: {response.status}")
        
        if response.status == 200:
            try:
                data = await read_provider_json(response)
                if not expect_text:
                    return AIResult("success", "API reachable", self.provider, self.model)
                content = None
                if isinstance(data, dict):
                    choices = data.get("choices")
                    if isinstance(choices, list) and choices:
                        choice = choices[0]
                        if isinstance(choice, dict):
                            message = choice.get("message")
                            if isinstance(message, dict):
                                content = message.get("content")
                if isinstance(content, str) and content.strip() and len(content) <= MAX_AI_TEXT_CHARS:
                    return AIResult("success", content, self.provider, self.model)
                self.last_error = "Invalid or oversized response text"
                return AIResult("unavailable", None, self.provider, self.model)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self.last_error = "Invalid or oversized provider envelope"
                return AIResult("unavailable", None, self.provider, self.model)

        elif response.status == 401:
            self.error_count += 1
            self.last_error = "Unauthorized - Invalid API key"
            self.logger.error("Unauthorized: Invalid API key")
            return AIResult("auth_error", None, self.provider, self.model)

        elif response.status == 403:
            self.error_count += 1
            self.last_error = "Provider authorization denied"
            return AIResult("auth_error", None, self.provider, self.model)
            
        elif response.status == 429:
            retry_after = parse_retry_after(
                response.headers.get("Retry-After", 60), default=60.0
            )
            self.error_count += 1
            self.last_error = f"Rate limited (retry after {retry_after}s)"
            self.logger.warning(f"Rate limited, retry after {retry_after}s")
            return AIResult("busy", None, self.provider, self.model, retry_after_s=retry_after)
            
        elif response.status >= 500:
            self.error_count += 1
            self.last_error = f"Server error {response.status}"
            error_text = await response.text()
            self.logger.error(f"Server error {response.status}: {error_text[:100]}")
            return AIResult("retryable", None, self.provider, self.model)
            
        else:
            self.error_count += 1
            self.last_error = f"HTTP {response.status}"
            error_text = await response.text()
            self.logger.error(f"HTTP error {response.status}: {error_text[:100]}")
            return AIResult("unavailable", None, self.provider, self.model)

    async def check_health(self):
        """
        Check if OpenRouter API is reachable
        Returns: (is_healthy, message)
        """
        try:
            # The global catalog can exceed the bounded provider envelope.
            # Query only the configured model while keeping the same limit.
            endpoint = f"models/{quote(self.model, safe='/')}/endpoints"
            result = await self._make_request(endpoint, method="GET")
            if result.status == "success":
                return True, f"API reachable (using model: {self.model})"
            else:
                return False, result.legacy_tuple()[1]
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
            context, prompt, deadline=deadline, temperature=None, max_tokens=None
        )

    async def _generate_reply(
        self,
        context: RequestContext,
        prompt: str,
        *,
        deadline: float,
        temperature: float | None,
        max_tokens: int | None,
        system_prompt: str | None = None,
        is_mention: bool = True,
        author_name: str | None = None,
    ) -> AIResult:
        if not isinstance(prompt, str) or len(prompt) > MAX_AI_PROMPT_CHARS:
            return AIResult("unavailable", None, self.provider, self.model)

        speaker = f" with {author_name}" if author_name else ""
        locale = "Norwegian" if context.locale in {"no", "nb", "nn"} else context.locale
        context_prompt = (
            f"Respond in {locale} in {context.channel_kind} channel{speaker}"
            f"{' (mentioned you)' if is_mention else ''}."
        )
        selected_prompt = system_prompt or self.default_system_prompt
        if self.model.startswith("google/gemma"):
            messages = [{
                "role": "user",
                "content": (
                    f"{selected_prompt}\n\n{context_prompt}\n\nUser message:\n{prompt}"
                ),
            }]
        else:
            messages = []
            if selected_prompt:
                messages.append({"role": "system", "content": selected_prompt})
            messages.append({"role": "system", "content": context_prompt})
            messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if self.reasoning_enabled is not None:
            payload["reasoning"] = {"enabled": self.reasoning_enabled}

        async def request():
            self.request_count += 1
            return await self._make_request(
                "chat/completions", method="POST", payload=payload
            )

        return await self._reply_admission.run(
            request,
            deadline=deadline,
            provider=self.provider,
            model=self.model,
        )

    async def generate_response(
        self,
        message_content: str,
        author_name: str,
        channel_type: str,
        is_mention: bool = True,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
            deadline=time.monotonic() + 60,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            is_mention=is_mention,
            author_name=str(author_name),
        )
        return result.legacy_tuple()

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
        base_url=base_url,
        reasoning_enabled=getattr(config, 'OPENROUTER_REASONING_ENABLED', None),
    )
