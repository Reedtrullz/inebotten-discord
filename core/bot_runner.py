"""Optional discord.py bot entrypoint kept outside the selfbot runtime."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import metadata

from core.transport import (
    BotTransportConfig,
    DiscordBotTransport,
    validate_bot_application_config,
)


class BotRunner:
    """Construct a bot-only client and inject an existing domain monitor.

    ``monitor_factory`` must build the normal application/MessageMonitor around
    the supplied discord.py client and an explicitly selected application
    configuration. This runner never loads the checkout's .env or creates a
    selfbot AuthHandler.
    """

    def __init__(self, config: BotTransportConfig, client, transport: DiscordBotTransport):
        self.config = config
        self.client = client
        self.transport = transport

    @classmethod
    def create(
        cls,
        monitor_factory: Callable,
        *,
        application_config,
        environ: Mapping[str, str] | None = None,
    ) -> "BotRunner":
        config = BotTransportConfig.from_environment(environ)
        validate_bot_application_config(application_config)
        try:
            installed_version = metadata.version("discord.py")
        except metadata.PackageNotFoundError as error:
            raise RuntimeError(
                "discord.py is missing; use the isolated requirements/bot.lock environment"
            ) from error
        if installed_version != "2.7.1":
            raise RuntimeError("bot transport requires locked discord.py==2.7.1")
        try:
            metadata.version("discord.py-self")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise RuntimeError("discord.py-self is installed; use a separate bot environment")
        try:
            import discord
        except ImportError as error:
            raise RuntimeError(
                "bot transport needs its isolated requirements/bot.lock environment"
            ) from error

        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        # Message content remains disabled; Discord supplies mentioned-message
        # content without this privileged intent.
        client = discord.Client(intents=intents)
        # Application authorization/scope config is supplied explicitly by the
        # caller. The bot runner never loads core.config or a dotenv file.
        client.config = application_config
        monitor = monitor_factory(client)
        if getattr(monitor, "client", client) is not client:
            raise ValueError("monitor_factory must bind the monitor to the bot client")
        transport = DiscordBotTransport(monitor)

        @client.event
        async def on_message(message):
            await transport.handle_message(message)

        return cls(config, client, transport)

    async def run(self) -> None:
        # discord.py 2.x accepts bot credentials through Client.start(token).
        await self.client.start(self.config.token)

    async def close(self) -> None:
        await self.client.close()
