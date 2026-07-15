import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType

import discord
import pytest

from ai.action_schema import ActionName
from core.message_context import ResolvedMention, RoutingContext
from tests.nlu_test_support import (
    FIXED_NOW,
    OfflineMessageFactory,
    bridge_context,
    proposal_for,
    routing_context as make_routing_context,
)


def test_fixed_now_and_routing_helpers_are_deterministic():
    mention = ResolvedMention(30, "Ola")
    context = make_routing_context(mentions=[mention])

    assert FIXED_NOW.isoformat() == "2026-07-14T12:00:00+02:00"
    assert isinstance(context, RoutingContext)
    assert context.mentions == (mention,)


def test_proposal_helper_freezes_slots_and_forwards_clarification():
    slots = {"query": "kalender"}
    proposal = proposal_for(
        ActionName.CLARIFY,
        slots,
        reply="Svar",
        clarification="Hvilken kalender?",
    )
    slots["query"] = "endret"

    assert isinstance(proposal.slots, MappingProxyType)
    assert proposal.slots == {"query": "kalender"}
    assert proposal.reply == "Svar"
    assert proposal.clarification == "Hvilken kalender?"


def test_bridge_context_uses_one_reference_and_fresh_resolver():
    first = bridge_context()
    second = bridge_context()

    assert first.reference_time is FIXED_NOW
    assert first.utterance.raw == "utfør handlingen"
    assert first.routing == make_routing_context()
    assert first.temporal_resolver is not second.temporal_resolver


@pytest.mark.asyncio
async def test_offline_factory_preserves_guild_and_dm_raw_content_and_kwargs():
    factory = OfflineMessageFactory()
    guild_raw = "første linje\nandre linje"
    dm_raw = "dm første\ndm andre"
    guild_message = factory.mentioned_message(guild_raw)
    dm_message = factory.untagged_message(dm_raw, guild=False)

    assert guild_message.id != dm_message.id
    assert guild_message.guild.id == factory.GUILD_ID
    assert guild_message.content == f"<@999> {guild_raw}"
    assert guild_message.raw_content == guild_message.content
    assert isinstance(guild_message.mentions[0], discord.Object)
    assert guild_message.mentions[0].id == factory.BOT_USER_ID
    assert dm_message.guild is None
    assert dm_message.content == dm_raw
    assert dm_message.raw_content == dm_raw
    assert dm_message.mentions == []

    allowed_mentions = discord.AllowedMentions.none()
    await guild_message.channel.send(
        "kanal",
        allowed_mentions=allowed_mentions,
        suppress_embeds=True,
    )
    await dm_message.reply(
        "svar",
        allowed_mentions=allowed_mentions,
        suppress_embeds=False,
    )

    guild_message.channel.send.assert_awaited_once_with(
        "kanal",
        allowed_mentions=allowed_mentions,
        suppress_embeds=True,
    )
    dm_message.reply.assert_awaited_once_with(
        "svar",
        allowed_mentions=allowed_mentions,
        suppress_embeds=False,
    )
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles is False
    assert allowed_mentions.users is False


def test_conftest_message_fixtures_share_one_factory(
    mentioned_message,
    untagged_message,
    message,
):
    mentioned = mentioned_message("hei")
    untagged = untagged_message("hei")

    assert len({message.id, mentioned.id, untagged.id}) == 3
    assert message.content == "<@999> test"
    assert mentioned.content == "<@999> hei"
    assert untagged.content == "hei"


def test_conftest_value_fixtures_delegate_to_support(fixed_now, routing_context):
    assert fixed_now is FIXED_NOW
    assert routing_context == make_routing_context()


def test_conftest_optional_discord_fallback_collects_in_clean_process(tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "discord.py").write_text(
        'raise ModuleNotFoundError("discord intentionally unavailable")\n',
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(repo_root), env.get("PYTHONPATH", ""))
    ).rstrip(os.pathsep)
    script = """
import tests.conftest as conftest
import discord

value = discord.AllowedMentions.none()
assert isinstance(discord.Object(id=999), discord.Object)
assert value.users is False
assert value.roles is False
assert value.everyone is False
assert value.replied_user is False
conftest.pytest_sessionfinish(None, 0)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=shadow,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
