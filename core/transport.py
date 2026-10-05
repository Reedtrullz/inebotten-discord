"""Narrow adapter contract for an optional Discord bot account transport.

This module has no Discord client imports so it can be contract-tested in the
existing selfbot development environment. The two Discord distributions must
never share an environment because both provide the top-level ``discord``
import package.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import time
from typing import Mapping, Protocol

from core.access_policy import invocation_decision
from core.command_registry import command_spec
from core.intent_router import BotIntent
from core.request_context import RequestContext, request_scope


class UnsupportedTransportOperation(RuntimeError):
    """Raised when an operation is outside the deliberately narrow bot API."""


class Transport(Protocol):
    def capabilities(self) -> frozenset[str]: ...

    async def send_message(
        self,
        channel_id: str,
        text: str,
        attachments: tuple,
        deadline: float,
    ) -> dict: ...


@dataclass(frozen=True)
class BotTransportConfig:
    """Bot-only credentials; deliberately does not load dotenv or user config."""

    token: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "BotTransportConfig":
        values = os.environ if environ is None else environ
        if values.get("DISCORD_USER_TOKEN"):
            raise ValueError("user-token mode is forbidden in the bot transport environment")
        token = values.get("BOT_DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("BOT_DISCORD_TOKEN is required")
        if any(char.isspace() for char in token):
            raise ValueError("BOT_DISCORD_TOKEN has invalid whitespace")
        return cls(token=token)


_CAPABILITIES = frozenset({
    "guild_message_mentions",
    "calendar_scoped_commands",
    "reminder_scoped_commands",
    "channel_polls",
    "existing_invocation_authorization",
    "existing_outbound_rate_limit",
    "delivery_receipts",
})

_SUPPORTED_INTENTS = frozenset({
    "help", "status", "calendar_help", "calendar_list", "calendar_sync",
    "calendar_delete", "calendar_complete", "calendar_edit", "calendar_search",
    "calendar_clear", "calendar_item", "calendar_exchange", "reminder_edit",
    "reminder_delete", "reminder_search", "reminder_create", "reminder_list",
    "reminder_complete", "poll_create", "poll_vote", "poll_edit", "poll_delete",
    "poll_close", "poll_list",
})


def validate_bot_application_config(config) -> None:
    """Require an explicit closed invocation policy for bot deployments."""
    def valid_ids(values):
        return (isinstance(values, (list, tuple, set, frozenset)) and bool(values)
                and all(str(value).isdigit() and int(value) > 0 for value in values))

    if (getattr(config, "INVOCATION_MODE", None) != "allowlist"
        or not valid_ids(getattr(config, "ALLOWED_USERS", None))
        or not valid_ids(getattr(config, "ALLOWED_CHANNELS", None))):
        raise ValueError("bot transport requires allowlist mode with explicit users and channels")


class DiscordBotTransport:
    """Pass guild mentions through the existing monitor's security pipeline."""

    def __init__(self, monitor):
        if monitor is None or not callable(getattr(monitor, "handle_message", None)):
            raise TypeError("a configured MessageMonitor is required")
        validate_bot_application_config(getattr(getattr(monitor, "client", None), "config", None))
        self.monitor = monitor

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def require_operation(self, operation: str) -> None:
        """Fail closed for controller, self-only, and unimplemented operations."""
        if not isinstance(operation, str):
            raise UnsupportedTransportOperation("unsupported_bot_operation:invalid")
        if operation in {"interaction", "controller", "account", "profile", "dm", "private_dm"}:
            raise UnsupportedTransportOperation(f"unsupported_bot_operation:{operation}")
        try:
            spec = command_spec(BotIntent(operation))
        except (StopIteration, ValueError, TypeError):
            raise UnsupportedTransportOperation(f"unsupported_bot_operation:{operation}") from None
        if operation not in _SUPPORTED_INTENTS or spec.scope_rule in {"controller", "self"}:
            raise UnsupportedTransportOperation(f"unsupported_bot_operation:{operation}")

    async def handle_message(self, message) -> dict:
        """Normalize and authorize a guild message, then use the real monitor."""
        if getattr(message, "guild", None) is None:
            return {"status": "rejected", "reason_code": "guild_only"}
        message_id = getattr(message, "id", None)
        if message_id is None:
            return {"status": "rejected", "reason_code": "missing_request_id"}

        actor = RequestContext(
            request_id=str(message_id),
            user_id=str(message.author.id),
            channel_id=str(message.channel.id),
            guild_id=str(message.guild.id),
            locale="no",
            channel_kind="guild",
        )
        config = getattr(self.monitor.client, "config", None)
        try:
            validate_bot_application_config(config)
        except ValueError:
            return {"status": "rejected", "reason_code": "bot_authorization_unconfigured"}
        decision = invocation_decision(
            actor,
            mode=config.INVOCATION_MODE,
            allowed_users=config.ALLOWED_USERS,
            allowed_channels=config.ALLOWED_CHANNELS,
        )
        if not decision.allowed:
            return {"status": "rejected", "reason_code": decision.reason_code}

        bot_user = getattr(self.monitor.client, "user", None)
        bot_id = getattr(bot_user, "id", None)
        if bot_id is None:
            return {"status": "rejected", "reason_code": "bot_identity_unavailable"}
        if str(message.author.id) == str(bot_id):
            return {"status": "ignored", "reason_code": "bot_message"}
        if not any(
            str(getattr(mentioned_user, "id", "")) == str(bot_id)
            for mentioned_user in getattr(message, "mentions", ())
        ):
            return {"status": "ignored", "reason_code": "explicit_bot_mention_required"}

        authorized = self.monitor.authorize_message(message)
        if authorized is None:
            return {"status": "ignored", "reason_code": "mention_required"}

        route = self.monitor.intent_router.route(
            authorized.content, guild_id=message.guild.id
        )
        try:
            self.require_operation(route.intent.value)
        except UnsupportedTransportOperation as error:
            refusal = await self.send_message(
                str(message.channel.id),
                "Denne operasjonen er ikke tilgjengelig via bot-transporten.",
                deadline=monotonic_deadline(10),
            )
            return {"status": "rejected", "reason_code": str(error), "receipt": refusal}
        with request_scope(actor):
            await self.monitor.handle_message(message)
        return {"status": "dispatched", "request_id": actor.request_id,
                "operation": route.intent.value}

    async def send_message(
        self,
        channel_id: str,
        text: str,
        attachments: tuple = (),
        deadline: float | None = None,
        *,
        delivery_key: str | None = None,
    ) -> dict:
        """Use the monitor's rate-limited sender and expose its actual receipt."""
        if deadline is None:
            raise ValueError("an explicit monotonic deadline is required")
        if not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        result = await self.monitor.outbound.send(
            str(channel_id), text, delivery_key=delivery_key, deadline=deadline,
            attachments=attachments,
        )
        return {
            "status": result.status,
            "message_id": result.message_id,
            "retry_after_s": result.retry_after_s,
            "reason_code": result.reason_code,
        }


def monotonic_deadline(timeout_s: float) -> float:
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and positive")
    return time.monotonic() + timeout_s
