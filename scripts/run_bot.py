#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_runner import BotRunner


def _require_production_environment() -> None:
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    bot_data_home = os.environ.get("BOT_DATA_HOME", "").strip()
    if not hermes_home or not Path(hermes_home).is_absolute():
        raise RuntimeError("HERMES_HOME must be an absolute private data root for the bot transport")
    if not bot_data_home or Path(bot_data_home) != Path(hermes_home):
        raise RuntimeError("BOT_DATA_HOME must equal the absolute HERMES_HOME data root")
    if Path(hermes_home).resolve() == (Path.home() / ".hermes").resolve():
        raise RuntimeError("the default Hermes home is reserved for the selfbot runtime")


def _production_application_config():
    _require_production_environment()
    from core.config import get_config
    from core.transport import validate_bot_application_config

    config = get_config()
    validate_bot_application_config(config)
    return config


def _production_monitor_factory(client):
    from ai.connector_factory import create_ai_connector
    from ai.response_generator import create_response_generator
    from core.message_monitor import MessageMonitor
    from core.rate_limiter import create_rate_limiter

    config = client.config
    return MessageMonitor(
        client,
        hermes_connector=create_ai_connector(config),
        rate_limiter=create_rate_limiter(config),
        response_generator=create_response_generator(),
    )


async def main() -> int:
    application_config = _production_application_config()
    runner = BotRunner.create(
        _production_monitor_factory,
        application_config=application_config,
        environ=os.environ,
    )
    await runner.run()
    return 0


def run() -> int:
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(run())
