#!/usr/bin/env python3
"""
Unified AI Connector Factory
Creates the appropriate AI connector based on configuration
Supports both LM Studio (local) and OpenRouter (cloud) providers
"""

from typing import Union
from utils.logger import LoggerMixin


class AIConnectorFactory(LoggerMixin):
    """
    Factory for creating AI connectors based on configuration
    """
    
    @staticmethod
    def create_connector(config) -> Union['HermesConnector', 'OpenRouterConnector']:
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


def create_ai_connector(config) -> Union['HermesConnector', 'OpenRouterConnector']:
    """
    Convenience function to create an AI connector
    
    Args:
        config: Configuration object
        
    Returns:
        Appropriate AI connector instance
    """
    return AIConnectorFactory.create_connector(config)
