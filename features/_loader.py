#!/usr/bin/env python3
"""
Cog Loader - Dynamic loading of all Cogs at startup.

This module provides setup() functions for each Cog and a centralized
load_all_cogs() function to initialize the entire cog-based architecture.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def load_all_cogs(bot):
    """
    Load all Cogs into the bot instance.

    This replaces the monolithic MessageMonitor with a modular Cog structure.
    Each Cog is loaded in order, and failures are logged but don't stop
    other Cogs from loading.

    Args:
        bot: The Discord bot instance (self_bot mode)
    """
    # Core Cogs load first
    core_loaders = [
        # (loader_function, cog_name)
    ]

    # Feature Cogs
    feature_loaders = [
        # (loader_function, cog_name)
    ]

    # Track success/failure
    loaded = []
    failed = []

    # Load core loaders first
    for loader, name in core_loaders:
        try:
            await loader(bot)
            loaded.append(name)
            logger.info(f"Loaded core cog: {name}")
        except Exception as e:
            failed.append((name, str(e)))
            logger.error(f"Failed to load core cog {name}: {e}")

    # Load feature Cogs
    for loader, name in feature_loaders:
        try:
            await loader(bot)
            loaded.append(name)
            logger.info(f"Loaded feature cog: {name}")
        except Exception as e:
            failed.append((name, str(e)))
            logger.error(f"Failed to load feature cog {name}: {e}")

    # Report results
    if failed:
        logger.warning(
            f"Cog loading complete. {len(loaded)} loaded, {len(failed)} failed: {failed}"
        )
    else:
        logger.info(
            f"Cog loading complete. All {len(loaded)} Cogs loaded successfully."
        )

    return {"loaded": loaded, "failed": failed}


def get_available_cogs():
    """
    Return list of all available Cogs.

    Returns:
        dict: Maps cog names to their loader functions
    """
    return {}
