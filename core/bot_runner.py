"""Optional discord.py bot entrypoint kept outside the selfbot runtime."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import metadata
import os
from pathlib import Path

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
        self._monitor_ready = False
        self._monitor_started = False
        self._monitor_closed = False
        self._client_closed = False

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
        selected=getattr(application_config,'BOT_DATA_HOME',None)
        if (not isinstance(selected,str) or not Path(selected).is_absolute()
            or os.environ.get('HERMES_HOME')!=selected
            or Path(selected).resolve()==(Path.home()/'.hermes').resolve()):
            raise ValueError('explicit_isolated_data_profile_required')
        directory=Path(selected)
        if any(part.is_symlink() for part in (directory,*directory.parents)):
            raise ValueError('symlink_data_profile_refused')
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if not directory.is_dir() or os.name=='posix' and directory.stat().st_mode&0o077:
            raise ValueError('private_data_profile_required')

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
        if not callable(getattr(monitor, "setup", None)) or not callable(getattr(monitor, "close", None)):
            raise TypeError("monitor_factory must return a monitor with async setup() and close() lifecycle")
        transport = DiscordBotTransport(monitor)

        @client.event
        async def on_message(message):
            await transport.handle_message(message)

        return cls(config, client, transport)

    async def run(self) -> None:
        if self._client_closed or self._monitor_closed:
            raise RuntimeError('bot_runner_closed')
        try:
            await self._setup_monitor()
            # discord.py 2.x accepts bot credentials through Client.start(token).
            await self.client.start(self.config.token)
        except BaseException as error:
            try:
                await self.close()
            except BaseException as cleanup_error:
                error.add_note(f'bot cleanup also failed: {type(cleanup_error).__name__}')
            raise
        else:
            await self.close()

    async def _setup_monitor(self) -> None:
        if self._monitor_started:
            if not self._monitor_ready:raise RuntimeError('bot_monitor_setup_failed')
            return
        self._monitor_started = True
        try:
            await self.transport.monitor.setup()
            self._monitor_ready = True
        except BaseException as setup_error:
            # setup() can fail after it has started monitor-owned workers.
            try:
                await self._close_monitor()
            except BaseException as cleanup_error:
                setup_error.add_note(
                    f"monitor cleanup also failed: {type(cleanup_error).__name__}"
                )
            raise

    async def _close_monitor(self) -> None:
        if self._monitor_closed:
            return
        await self.transport.monitor.close()
        receipt=getattr(self.transport.monitor,'shutdown_receipt',None)
        if receipt is not None and receipt.get('status')!='closed':
            raise RuntimeError('bot_monitor_closure_incomplete')
        self._monitor_closed = True

    async def close(self) -> None:
        try:
            await self._close_monitor()
        finally:
            if not self._client_closed:
                await self.client.close()
                self._client_closed = True
