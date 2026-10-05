from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.request_context import current_request
from core.transport import (
    BotTransportConfig,
    DiscordBotTransport,
    UnsupportedTransportOperation,
    validate_bot_application_config,
)


class FakeMonitor:
    def __init__(self, operation="calendar_list", *, invocation_mode="allowlist"):
        self.client = SimpleNamespace(config=SimpleNamespace(
            INVOCATION_MODE=invocation_mode,
            ALLOWED_USERS=["42", "99"],
            ALLOWED_CHANNELS=["70"],
        ), user=SimpleNamespace(id="99"))
        self.intent_router = SimpleNamespace(route=lambda _text, guild_id: SimpleNamespace(
            intent=SimpleNamespace(value=operation)
        ))
        self.outbound = FakeSender()
        self.calls = []

    def authorize_message(self, message):
        if not self.is_mention(message):
            return None
        return SimpleNamespace(content="kalender")

    @staticmethod
    def is_mention(message):
        return message.mentioned

    async def handle_message(self, message):
        self.calls.append((message.id, current_request()))


class FakeSender:
    def __init__(self):
        self.calls = []

    async def send(self, channel_id, text, *, delivery_key, deadline, attachments):
        self.calls.append((channel_id, text, delivery_key, deadline, attachments))
        return SimpleNamespace(status="delivered", message_id="9001", retry_after_s=None,
                               reason_code="remote_message")


def synthetic_message(*, guild=True, mentioned=True, user_id="42", channel_id="70"):
    return SimpleNamespace(
        id="8001",
        author=SimpleNamespace(id=user_id),
        channel=SimpleNamespace(id=channel_id),
        guild=SimpleNamespace(id="60") if guild else None,
        mentioned=mentioned,
        mentions=[SimpleNamespace(id="99")] if mentioned else [],
    )


def test_bot_environment_is_separate_and_refuses_user_token_mode():
    assert BotTransportConfig.from_environment({"BOT_DISCORD_TOKEN": "synthetic.bot.token"}).token == "synthetic.bot.token"
    with pytest.raises(ValueError, match="user-token mode"):
        BotTransportConfig.from_environment({
            "BOT_DISCORD_TOKEN": "synthetic.bot.token",
            "DISCORD_USER_TOKEN": "synthetic.user.token",
        })
    with pytest.raises(ValueError, match="BOT_DISCORD_TOKEN"):
        BotTransportConfig.from_environment({"DISCORD_TOKEN": "ambiguous.token"})


def test_bot_application_requires_closed_user_and_channel_allowlists():
    validate_bot_application_config(SimpleNamespace(
        INVOCATION_MODE="allowlist", ALLOWED_USERS=["42"], ALLOWED_CHANNELS=["70"],
    ))
    with pytest.raises(ValueError, match="allowlist mode"):
        validate_bot_application_config(SimpleNamespace(
            INVOCATION_MODE="legacy", ALLOWED_USERS=[], ALLOWED_CHANNELS=[],
        ))


def test_capabilities_are_narrow_and_exclude_interactions_and_controller():
    transport = DiscordBotTransport(FakeMonitor())
    assert transport.capabilities() == frozenset({
        "guild_message_mentions", "calendar_scoped_commands",
        "reminder_scoped_commands", "channel_polls",
        "existing_invocation_authorization", "existing_outbound_rate_limit",
        "delivery_receipts",
    })
    for operation in ("interaction", "profile", "calendar_auth", "memory_view", "ai_chat"):
        with pytest.raises(UnsupportedTransportOperation):
            transport.require_operation(operation)
    transport.require_operation("calendar_list")
    transport.require_operation("poll_vote")


@pytest.mark.asyncio
async def test_guild_mention_uses_existing_invocation_and_request_context():
    monitor = FakeMonitor()
    transport = DiscordBotTransport(monitor)
    result = await transport.handle_message(synthetic_message())
    assert result == {"status": "dispatched", "request_id": "8001", "operation": "calendar_list"}
    assert monitor.calls[0][0] == "8001"
    assert monitor.calls[0][1].user_id == "42"
    assert monitor.calls[0][1].channel_id == "70"
    assert current_request() is None


@pytest.mark.asyncio
async def test_untagged_disallowed_and_dm_messages_never_reach_monitor():
    monitor = FakeMonitor()
    transport = DiscordBotTransport(monitor)
    assert (await transport.handle_message(synthetic_message(mentioned=False)))["reason_code"] == "explicit_bot_mention_required"
    assert (await transport.handle_message(synthetic_message(user_id="43")))["reason_code"] == "invocation_user_denied"
    assert (await transport.handle_message(synthetic_message(guild=False)))["reason_code"] == "guild_only"
    assert monitor.calls == []


@pytest.mark.asyncio
async def test_bot_does_not_process_its_own_message():
    monitor = FakeMonitor()
    transport = DiscordBotTransport(monitor)
    result = await transport.handle_message(synthetic_message(user_id="99"))
    assert result == {"status": "ignored", "reason_code": "bot_message"}
    assert monitor.calls == []


@pytest.mark.asyncio
async def test_unsupported_operation_is_refused_through_the_receipt_sender():
    monitor = FakeMonitor(operation="profile")
    transport = DiscordBotTransport(monitor)
    result = await transport.handle_message(synthetic_message())
    assert result["status"] == "rejected"
    assert result["reason_code"] == "unsupported_bot_operation:profile"
    assert result["receipt"]["status"] == "delivered"
    assert result["receipt"]["message_id"] == "9001"
    assert monitor.calls == []


@pytest.mark.asyncio
async def test_send_message_forwards_deadline_and_returns_delivery_evidence():
    monitor = FakeMonitor()
    transport = DiscordBotTransport(monitor)
    receipt = await transport.send_message("70", "ok", (), 123.0, delivery_key="req-1")
    assert receipt == {"status": "delivered", "message_id": "9001",
                       "retry_after_s": None, "reason_code": "remote_message"}
    assert monitor.outbound.calls == [("70", "ok", "req-1", 123.0, ())]


def test_deadline_helper_rejects_nonpositive_or_nonfinite_values():
    from core.transport import monotonic_deadline

    with pytest.raises(ValueError):
        monotonic_deadline(0)
    assert monotonic_deadline(1) > 0
