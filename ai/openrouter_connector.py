#!/usr/bin/env python3
"""
OpenRouter API Connector for Discord Selfbot
Handles communication with OpenRouter API for AI-powered responses
"""

import json
import asyncio
import aiohttp
import os
from datetime import datetime
from typing import Optional, Dict, Any
from utils.logger import LoggerMixin


class OpenRouterConnector(LoggerMixin):
    """
    Connects to OpenRouter API for AI-powered response generation
    Uses OpenAI-compatible API format
    """

    def __init__(
        self,
        api_key: str,
        model: str = "google/gemma-3-4b-it:free",
        temperature: float = 0.7,
        max_tokens: int = 500,
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
                    self.logger.info(f"Loaded system prompt from {prompt_path}")
                    return prompt
            else:
                self.logger.warning("System prompt file not found, using default")
                return "Du er en hjelpsom norsk assistent som svarer på norsk."
        except Exception as e:
            self.logger.error(f"Error loading system prompt: {e}")
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
            self.logger.error(f"Request timed out after 60s")
            return False, "Request timeout (60s)"
            
        except aiohttp.ClientConnectorError as e:
            self.error_count += 1
            self.last_error = f"Connection error: {type(e).__name__}"
            self.logger.error(f"Network error: {type(e).__name__}: {str(e)[:100]}")
            return False, f"Cannot connect to OpenRouter: {type(e).__name__}"
            
        except aiohttp.ClientError as e:
            self.error_count += 1
            self.last_error = f"Client error: {type(e).__name__}"
            self.logger.error(f"HTTP client error: {type(e).__name__}: {str(e)[:100]}")
            return False, f"HTTP error: {type(e).__name__}"
            
        except json.JSONDecodeError as e:
            self.error_count += 1
            self.last_error = f"JSON decode error: {str(e)[:100]}"
            self.logger.error(f"Invalid JSON response: {str(e)[:100]}")
            return False, "Invalid response format"
            
        except Exception as e:
            self.error_count += 1
            self.last_error = f"Unexpected error: {type(e).__name__}"
            self.logger.error(f"Unexpected error: {type(e).__name__}: {str(e)[:100]}")
            return False, f"Request error: {type(e).__name__}"

    async def _handle_response(self, response: aiohttp.ClientResponse) -> tuple[bool, Any]:
        """
        Handle HTTP response with proper error handling
        
        Args:
            response: The aiohttp response object
            
        Returns:
            (success, response_data or error_message)
        """
        self.logger.debug(f"Response status: {response.status}")
        
        if response.status == 200:
            try:
                data = await response.json()
                self.logger.debug(f"Response data: {str(data)[:150]}...")
                return True, data
            except json.JSONDecodeError as e:
                text = await response.text()
                self.logger.error(f"Response parse error: {e}")
                return True, text
                
        elif response.status == 401:
            self.error_count += 1
            self.last_error = "Unauthorized - Invalid API key"
            self.logger.error("Unauthorized: Invalid API key")
            return False, "Invalid API key"
            
        elif response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            self.error_count += 1
            self.last_error = f"Rate limited (retry after {retry_after}s)"
            self.logger.warning(f"Rate limited, retry after {retry_after}s")
            return False, f"Rate limited (retry after {retry_after}s)"
            
        elif response.status >= 500:
            self.error_count += 1
            self.last_error = f"Server error {response.status}"
            error_text = await response.text()
            self.logger.error(f"Server error {response.status}: {error_text[:100]}")
            return False, f"Server error (status {response.status})"
            
        else:
            self.error_count += 1
            self.last_error = f"HTTP {response.status}"
            error_text = await response.text()
            self.logger.error(f"HTTP error {response.status}: {error_text[:100]}")
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
        # Add context about the conversation
        context = f"User {author_name} in {channel_type} channel"
        if is_mention:
            context += " (mentioned you)"

        prompt = system_prompt or self.default_system_prompt
        context_prompt = f"Context: {context}. Respond in Norwegian."

        # Google Gemma models on OpenRouter reject system/developer instructions.
        if self.model.startswith("google/gemma"):
            messages = [{
                "role": "user",
                "content": (
                    f"{prompt}\n\n{context_prompt}\n\n"
                    f"User message:\n{message_content}"
                )
            }]
        else:
            messages = []
            if prompt:
                messages.append({"role": "system", "content": prompt})
            messages.append({"role": "system", "content": context_prompt})
            messages.append({"role": "user", "content": message_content})

        # Build request payload
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }

        try:
            self.request_count += 1
            self.logger.info(f"Sending request to OpenRouter (model: {self.model})")

            success, result = await self._make_request("chat/completions", method="POST", payload=payload)
            
            if success and isinstance(result, dict):
                # Extract response from OpenAI-compatible format
                if "choices" in result and len(result["choices"]) > 0:
                    response_text = result["choices"][0]["message"]["content"]
                    self.logger.info(f"Received response: {response_text[:80]}...")
                    return True, response_text
                else:
                    self.logger.error("No choices in response")
                    return False, "No response generated"
            else:
                return success, result

        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            self.logger.error(f"Unexpected error in generate_response: {type(e).__name__}: {str(e)[:100]}")
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
    model = getattr(config, 'OPENROUTER_MODEL', 'google/gemma-3-4b-it:free')
    temperature = getattr(config, 'OPENROUTER_TEMPERATURE', 0.7)
    max_tokens = getattr(config, 'OPENROUTER_MAX_TOKENS', 200)
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
