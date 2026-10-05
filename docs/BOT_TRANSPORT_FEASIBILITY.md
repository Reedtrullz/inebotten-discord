# Discord bot transport feasibility

Status: **feasible as an optional, bounded guild assistant adapter; not a drop-in replacement**. This checkout contains an offline adapter contract only. No bot token, guild, Discord login, application command registration, or live test was used.

## Policy and API findings

Discord provides bot accounts and says automating a normal user account outside the OAuth2/bot API is forbidden. The new runtime therefore accepts only `BOT_DISCORD_TOKEN`; `DISCORD_USER_TOKEN` is rejected, and this code never reads either `.env` file. The current selfbot remains a separate product/runtime and is not migrated by this change. [Discord: Automated User Accounts](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)

Discord's Gateway supports guild message events with declared intents. Message content is privileged in general, with an exception for content in messages that mention the app. This makes an explicit-mention assistant possible without enabling the privileged Message Content intent. It does not authorize reading arbitrary guild history or turning this adapter into a passive listener. [Discord Gateway intents](https://github.com/discord/discord-api-docs/blob/main/developers/events/gateway.mdx) [discord.py intents guide](https://discordpy.readthedocs.io/en/stable/intents.html)

Application commands, buttons, selects, and modals arrive as interaction payloads through the Gateway or a signed HTTP endpoint. This adapter implements neither interaction acknowledgement nor command registration, so it advertises no interaction capability and refuses interaction operations. [Discord interactions](https://github.com/discord/discord-api-docs/blob/main/developers/platform/interactions.mdx)

The bot runtime is pinned to `discord.py==2.7.1` (PyPI release 2026-03-03). `discord.py` and `discord.py-self` both install the top-level `discord` package. Install the hash-locked bot requirements into a dedicated Python 3.12 environment; never install them into the existing selfbot/development environment. [discord.py on PyPI](https://pypi.org/project/discord.py/2.7.1/) [discord.py 2.x migration notes](https://discordpy.readthedocs.io/en/latest/migrating.html)

## Capability matrix

| Area | Bot transport disposition | Preconditions / boundary |
| --- | --- | --- |
| Explicit guild mentions | Supported by the adapter contract | `GUILDS` and `GUILD_MESSAGES` intents; app mention required by the existing `MessageMonitor` gate; channel visibility and send permission; no privileged Message Content intent is requested. Startup also requires the existing invocation policy in explicit allowlist mode with at least one configured user and channel. |
| Other guild messages / prefix commands | Unavailable | No ambient message processing; no non-mention content capability is claimed. |
| Slash commands, message/user commands, buttons, modals | Unavailable in this implementation | Discord supports these through interactions, but registration, interaction acknowledgement, and conversion to the app's request context are not implemented. |
| Calendar read/write commands | Adapter-supported command subset, acceptance pending | Existing calendar handlers and scope policy remain authoritative. The `monitor_factory` must provide the normal configured application and bot client. Real Google OAuth and private calendar authorization are not tested here; account/controller commands such as calendar authentication are rejected. |
| Reminders | Adapter-supported command subset, acceptance pending | Existing reminder handlers, scope checks, scheduler, sender, and delivery receipts are reused. No private DM delivery is exposed by this adapter. Scheduler ownership and restart behavior remain subject to the existing runtime. |
| Polls | Adapter-supported command subset, acceptance pending | Existing app-managed poll commands and poll-owner checks are reused. This does not claim support for Discord's native Poll objects or interaction-based voting. |
| Controller endpoints and account-only actions | Unsupported and rejected | Profile/account changes, controller operations, user-only endpoints, self-only memory/location actions, and private/group DMs stay in the existing user-account product where applicable. They are not forwarded to Discord REST endpoints by the bot adapter. |
| Outbound messages | Supported through existing `OutboundSender` | Uses its rate limiter, idempotency/receipt cache, attachment bounds, and result status/message ID. A missing remote acknowledgement remains unknown, never success. |
| Calendar scope and invocation authorization | Reused, not replaced | `RequestContext` is normalized from the guild event; the existing invocation gate and handler scope policies still run. Test-guild acceptance must verify actual configured allowlists, calendar ownership, and poll ownership. |

The adapter deliberately accepts only the existing command-registry operations for help/status, calendar, reminders, and polls. Every other routed operation is refused with an explicit bounded response. User-facing controller endpoints are not represented as bot capabilities.

## Runtime and configuration contract

`BotTransportConfig.from_environment()` reads only the supplied process environment (or `os.environ`); it does not invoke `python-dotenv`, `core.config`, or a selfbot auth handler. Configure `BOT_DISCORD_TOKEN` in the bot process's secret manager. Do not place it in the selfbot `.env`. If `DISCORD_USER_TOKEN` is also present, startup fails closed. Token strings cannot be reliably distinguished by shape, so isolation and the explicit variable name are part of the identity boundary.

`BotRunner.create(monitor_factory=..., application_config=..., environ=...)` imports `discord` only in the bot environment, requests only guild and guild-message intents, creates the client, and connects the existing `MessageMonitor` pipeline. The caller must provide the application's explicit authorization/scope configuration with `INVOCATION_MODE=allowlist`, non-empty `ALLOWED_USERS`, and non-empty `ALLOWED_CHANNELS`, plus a monitor bound to this bot client. The runner never constructs `core.config` or loads the selfbot dotenv. `DiscordBotTransport.handle_message()` checks guild-only context, the same invocation policy, and a resolved mention of the bot's actual user ID before routing; accepted input then goes through `monitor.handle_message()`. Its message and send results are deliberately not equivalent to test-bot acceptance.

Create a clean Python 3.12 environment and install `requirements/bot.lock` with hash checking. The runner checks for exactly `discord.py==2.7.1` and refuses to start if the `discord.py-self` distribution is also installed. The lock is separate from every current application/dev lock. The bot adapter is opt-in and has no default entry in the selfbot runner.

## Acceptance status and remaining gates

Offline acceptance covers environment separation, token-mode confusion, operation refusals, guild/mention/invocation checks, context lifetime, and receipt propagation with synthetic objects. It does not prove a live bot login, role/permission behavior, mention payloads for the selected application, calendar/reminder/poll end-to-end behavior, interaction UX, or cross-adapter domain fixtures.

Before calling this a supported deployment, an owner must provide an explicitly approved test bot and test guild. Then verify the bot's application identity and configured role permissions, mentioned-message content without Message Content intent, allowlisted invocation, calendar scope owner/collaborator decisions, reminder due delivery and restart ownership, poll ownership/votes, and remote-send receipt/error behavior. No private data or existing account migration is part of that gate.
