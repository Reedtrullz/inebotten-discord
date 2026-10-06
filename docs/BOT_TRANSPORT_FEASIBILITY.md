# Discord bot transport feasibility

Status: **bounded adapter, real shared-domain handlers, and the actual monitor lifecycle are feasible in an isolated bot profile; a production application factory remains deferred**. `MessageMonitor` was imported, constructed with a disconnected client and synthetic home, set up, and closed with `DISCORD_TOKEN=None`. Its broader selfbot service graph and default Hermes-home stores still require an explicit caller-supplied factory/configuration. No bot token, guild, Discord login, application command registration, or live test was used.

## Release disposition — 6 October 2026

I37 is deferred from the current selfbot rollout. The human approved finishing
the existing selfbot work and deferring the optional bot transport. Its isolated
prototype and tests remain preserved in draft #63; they do not constitute a
production factory, proactive scheduler, or actual bot-account acceptance.
Do not install the bot profile into the selfbot environment, activate the adapter,
request a bot application ID for the existing selfbot, or remove the existing
mode. Deferral is a scope disposition, not a completed live bot implementation.

Draft #63 is an ancestor of later corrections. The current stack retains its
inert source; deferring activation does not remove that ancestry. If a later
review requires excluding its source entirely, restack and revalidate downstream
PRs before merging, rather than silently skipping a middle draft.

## Policy and API findings

Discord provides bot accounts and says automating a normal user account outside the OAuth2/bot API is forbidden. The new runtime therefore accepts only `BOT_DISCORD_TOKEN`; `DISCORD_USER_TOKEN` and ambiguous `DISCORD_TOKEN` are rejected, and this code never reads either `.env` file. The current selfbot remains a separate product/runtime and is not migrated by this change. [Discord: Automated User Accounts](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)

Discord's Gateway supports guild message events with declared intents. Message content is privileged in general, with an exception for content in messages that mention the app. This makes an explicit-mention assistant possible without enabling the privileged Message Content intent. It does not authorize reading arbitrary guild history or turning this adapter into a passive listener. [Discord Gateway intents](https://github.com/discord/discord-api-docs/blob/main/developers/events/gateway.mdx) [discord.py intents guide](https://discordpy.readthedocs.io/en/stable/intents.html)

Application commands, buttons, selects, and modals arrive as interaction payloads through the Gateway or a signed HTTP endpoint. This adapter implements neither interaction acknowledgement nor command registration, so it advertises no interaction capability and refuses interaction operations. [Discord interactions](https://github.com/discord/discord-api-docs/blob/main/developers/platform/interactions.mdx)

The bot runtime is pinned to `discord.py==2.7.1` (PyPI release 2026-03-03). `discord.py` and `discord.py-self` both install the top-level `discord` package. The separate bot lock contains the core imports needed by the real monitor and shared handlers (`aiohttp`, `cryptography`, `icalendar`, `requests`, and `simpleeval`) plus pytest for the bot-profile fixtures. It excludes `discord.py-self`, dotenv loading, and Google client credentials. Install the hash-locked bot requirements into a dedicated Python 3.12 environment; never install them into the existing selfbot/development environment. [discord.py on PyPI](https://pypi.org/project/discord.py/2.7.1/) [discord.py 2.x migration notes](https://discordpy.readthedocs.io/en/latest/migrating.html)

## Capability matrix

| Area | Bot transport disposition | Preconditions / boundary |
| --- | --- | --- |
| Explicit guild mentions | Supported by the adapter contract | `GUILDS` and `GUILD_MESSAGES` intents; app mention required by the existing `MessageMonitor` gate; channel visibility and send permission; no privileged Message Content intent is requested. Startup also requires the existing invocation policy in explicit allowlist mode with at least one configured user and channel. |
| Other guild messages / prefix commands | Unavailable | No ambient message processing; no non-mention content capability is claimed. |
| Slash commands, message/user commands, buttons, modals | Unavailable in this implementation | Discord supports these through interactions, but registration, interaction acknowledgement, and conversion to the app's request context are not implemented. |
| Calendar read/write commands | Shared handler import/execution covered by synthetic bot-profile fixtures | Fixtures import the real `CalendarHandler` and `CalendarManager` with temporary JSON storage. Production wiring through the full `MessageMonitor` remains deferred; Google OAuth and private calendar authorization are not tested. Account/controller commands such as calendar authentication are rejected. |
| Reminders | Shared handler import/execution covered by synthetic bot-profile fixtures | Fixtures import the real `ReminderHandler` and `ReminderManager` with temporary JSON storage. The adapter does not compose a proactive ReminderChecker; a production factory must own and test that scheduler explicitly. No private DM delivery is exposed by this adapter. |
| Polls | Shared handler import/execution covered by synthetic bot-profile fixtures | Fixtures import the real `PollsHandler` and `PollManager` with temporary JSON storage. This does not claim support for Discord's native Poll objects or interaction-based voting. |
| Controller endpoints and account-only actions | Unsupported and rejected | Profile/account changes, controller operations, user-only endpoints, self-only memory/location actions, and private/group DMs stay in the existing user-account product where applicable. They are not forwarded to Discord REST endpoints by the bot adapter. |
| Outbound messages | Supported through existing `OutboundSender` | Uses its rate limiter, idempotency/receipt cache, attachment bounds, and result status/message ID. A missing remote acknowledgement remains unknown, never success. |
| Calendar scope and invocation authorization | Reused, not replaced | `RequestContext` is normalized from the guild event; the existing invocation gate and handler scope policies still run. Test-guild acceptance must verify actual configured allowlists, calendar ownership, and poll ownership. |

The adapter deliberately accepts only the existing command-registry operations for help/status, calendar, reminders, and polls. Every other routed operation is refused with an explicit bounded response. User-facing controller endpoints are not represented as bot capabilities.

## Runtime and configuration contract

`BotTransportConfig.from_environment()` reads only the supplied process environment (or `os.environ`); it does not invoke `python-dotenv`, `core.config`, or a selfbot auth handler. Configure `BOT_DISCORD_TOKEN` in the bot process's secret manager. Do not place it in the selfbot `.env`. If `DISCORD_USER_TOKEN` or `DISCORD_TOKEN` is present, startup fails closed. Token strings cannot be reliably distinguished by shape, so isolation and the explicit variable name are part of the identity boundary.

`BotRunner.create(monitor_factory=..., application_config=..., environ=...)` imports `discord` only in the bot environment, requests only guild and guild-message intents, creates the client, and binds the supplied monitor. The monitor must expose async `setup()` and `close()` methods and be bound to that client. `run()` initializes it once before `client.start()` can receive messages; shutdown closes monitor-owned work before closing the Discord client, including cleanup after setup failure. The runner never constructs `core.config` or loads the selfbot dotenv. `DiscordBotTransport.handle_message()` keeps `RequestContext` active across invocation authorization, mention authorization, pre-routing, refusal delivery, and full monitor dispatch. Its message and send results do not establish test-bot acceptance.

The bot-profile lifecycle fixture imports and constructs the actual `MessageMonitor`, runs its async setup, then closes it using an isolated synthetic home and no user token. Separate fixtures invoke the actual calendar, reminder, and poll handlers against real managers and temporary stores. These tests do not route a synthetic Discord message through the actual monitor's full dispatch path, prove provider integrations, or supply a production application factory. A runtime owner must still provide the monitor's surrounding dependencies/configuration explicitly; the transport does not infer them from the selfbot environment or import the checkout's `.env`.

Startup additionally requires `application_config.BOT_DATA_HOME` to be an absolute, explicitly selected data directory matching the actual process `HERMES_HOME`. The default personal `~/.hermes` path, symlink paths, and nonprivate POSIX directories are refused before constructing the monitor. Keep this profile separate from the selfbot stores. Monitor closure is successful only after its owned-resource receipt is closed; incomplete or failed closure can be retried, and a closed/failed runner cannot silently restart.

Create a clean Python 3.12 environment and install `requirements/bot.lock` with hash checking. The runner checks for exactly `discord.py==2.7.1` and refuses to start if the `discord.py-self` distribution is also installed. The lock is separate from every current application/dev lock. The bot adapter is opt-in and has no default entry in the selfbot runner.

## Acceptance status and remaining gates

Offline acceptance covers environment separation (including ambiguous `DISCORD_TOKEN`), operation refusals, guild/mention/invocation checks, actor context during authorization/pre-route/refusal/dispatch, monitor lifecycle ordering/failure cleanup, and receipt propagation. A clean hash-installed bot profile imports, constructs, sets up, and closes the actual `MessageMonitor` under a synthetic home, and imports/executes the actual calendar, reminder, and poll handlers with real managers, synthetic messages, and temporary storage. This does not prove a live bot login, role/permission behavior, mention payloads for the selected application, provider integrations, or full-message dispatch through the production monitor factory.

Before calling this a supported deployment, an owner must provide an explicitly approved test bot and test guild. Then verify the bot's application identity and configured role permissions, mentioned-message content without Message Content intent, allowlisted invocation, calendar scope owner/collaborator decisions, reminder due delivery and restart ownership, poll ownership/votes, and remote-send receipt/error behavior. No private data or existing account migration is part of that gate.

Parent integration verification: 17 contract tests and 108 shared calendar/access/time/mutation/reminder/poll/sender tests passed in a fresh hash-installed bot environment; `pip check` passed and the current PyPI advisory query reported zero findings. The ordinary selfbot profile runs the common contracts and visibly skips the two tests that require the competing bot distribution. The bot CI job installs its own lock in a separate job; that remote job has not run on this candidate.
