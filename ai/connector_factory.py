#!/usr/bin/env python3
"""
Unified AI Connector Factory
Creates the appropriate AI connector based on configuration
Supports both LM Studio (local) and OpenRouter (cloud) providers
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING, Union
from utils.logger import LoggerMixin
from ai.result_schema import AIResult
from core.request_context import RequestContext

if TYPE_CHECKING:
    from ai.hermes_connector import HermesConnector
    from ai.openrouter_connector import OpenRouterConnector


class AIConnectorFactory(LoggerMixin):
    """
    Factory for creating AI connectors based on configuration
    """
    
    @staticmethod
    def create_connector(
        config,
        *,
        fallback_provider=None,
    ) -> Union['HermesConnector', 'OpenRouterConnector', 'AIConnectorRouter']:
        """
        Create an AI connector based on configuration
        
        Args:
            config: Configuration object with AI provider settings
            
        Returns:
            HermesConnector or OpenRouterConnector instance
            
        Raises:
            ValueError: If no valid AI provider is configured
        """
        provider = config.get_ai_provider()
        
        if fallback_provider is None:
            fallback_provider = getattr(config, "AI_FALLBACK_PROVIDER", None)
        if fallback_provider:
            if provider != "openrouter" or fallback_provider != "lm_studio":
                raise ValueError(
                    "Only an explicitly declared OpenRouter-to-local fallback is supported"
                )
            from ai.openrouter_connector import create_openrouter_connector
            from ai.hermes_connector import create_hermes_connector

            logger = LoggerMixin()
            logger.logger.info("Creating OpenRouter connector with declared local fallback")
            primary = create_openrouter_connector(config)
            return AIConnectorRouter(primary, fallback=create_hermes_connector(config))

        if provider == 'openrouter':
            from ai.openrouter_connector import create_openrouter_connector
            logger = LoggerMixin()
            logger.logger.info("Creating OpenRouter connector")
            return create_openrouter_connector(config)
        else:
            # Default to LM Studio
            from ai.hermes_connector import create_hermes_connector
            logger = LoggerMixin()
            logger.logger.info("Creating LM Studio connector")
            return create_hermes_connector(config)


class AIConnectorRouter:
    """Use one configured provider and at most one declared local fallback."""

    def __init__(self, primary, *, fallback=None):
        self.primary = primary
        self.fallback = fallback
        primary_provider = getattr(primary, "provider", None)
        fallback_provider = getattr(fallback, "provider", None) if fallback else None
        if fallback is not None:
            if primary_provider != "openrouter" or fallback_provider != "hermes":
                raise ValueError("Fallback must be explicitly declared OpenRouter to Hermes")

    async def generate_reply(
        self, context: RequestContext, prompt: str, *, deadline: float
    ) -> AIResult:
        result = await self.primary.generate_reply(context, prompt, deadline=deadline)
        if not isinstance(result, AIResult):
            return AIResult(
                "unavailable",
                None,
                getattr(self.primary, "provider", "unknown"),
                getattr(self.primary, "model", None),
            )
        if (
            self.fallback is None
            or result.status not in {"busy", "retryable", "unavailable"}
        ):
            return result
        fallback_result = await self.fallback.generate_reply(
            context, prompt, deadline=deadline
        )
        if not isinstance(fallback_result, AIResult):
            return AIResult(
                "unavailable",
                None,
                getattr(self.fallback, "provider", "unknown"),
                getattr(self.fallback, "model", None),
                fallback=True,
            )
        return replace(fallback_result, fallback=True)

    async def generate_response(self, **kwargs) -> tuple[bool, str]:
        channel_kinds = {
            "DM": "dm",
            "GROUP_DM": "group_dm",
            "GUILD_TEXT": "guild",
        }
        channel_type = str(kwargs.get("channel_type", "unknown")).upper()
        context = RequestContext(
            request_id="legacy",
            user_id=str(kwargs.get("author_name", "unknown")),
            channel_id="legacy",
            guild_id=None,
            locale="no",
            channel_kind=channel_kinds.get(channel_type, "unknown"),
        )
        prompt = str(kwargs.get("message_content", ""))
        system_prompt = kwargs.get("system_prompt")
        if system_prompt:
            prompt = f"{system_prompt}\n\nBrukermelding:\n{prompt}"
        result = await self.generate_reply(
            context, prompt, deadline=time.monotonic() + 60
        )
        return result.legacy_tuple()

    async def check_health(self):
        return await self.primary.check_health()

    async def close(self):
        await self.primary.close()
        if self.fallback is not None:
            await self.fallback.close()

    def get_stats(self):
        stats = self.primary.get_stats()
        if self.fallback is not None:
            stats["fallback_provider"] = self.fallback.provider
        return stats

    def __getattr__(self, name):
        return getattr(self.primary, name)


def create_ai_connector(
    config,
    *,
    fallback_provider=None,
) -> Union['HermesConnector', 'OpenRouterConnector', 'AIConnectorRouter']:
    """
    Convenience function to create an AI connector
    
    Args:
        config: Configuration object
        
    Returns:
        Appropriate AI connector instance
    """
    return AIConnectorFactory.create_connector(
        config, fallback_provider=fallback_provider
    )
