#!/usr/bin/env python3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from features.poll_manager import PollManager


def _payload(guild_id=123, message_id=999, user_id=555, channel_id=777,
             emoji="1️⃣", event_type="REACTION_ADD"):
    return SimpleNamespace(
        guild_id=guild_id, message_id=message_id, user_id=user_id,
        channel_id=channel_id, emoji=emoji, event_type=event_type,
    )


def _bare_monitor(manager, *, users=("555",), channels=("777",), bot_id=1):
    from core.message_monitor import MessageMonitor
    monitor = MessageMonitor.__new__(MessageMonitor)
    monitor.client = SimpleNamespace(
        config=SimpleNamespace(
            INVOCATION_MODE="allowlist",
            ALLOWED_USERS=list(users),
            ALLOWED_CHANNELS=list(channels),
        ),
        user=SimpleNamespace(id=bot_id),
    )
    monitor.poll = manager
    monitor._closing = False
    return monitor


class PollReactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.manager = PollManager(storage_path=Path(self._tmp.name) / "polls.json")
        self.poll = self.manager.create_poll("123", "Ja eller Nei?", ["Ja", "Nei"], "Tester")

    async def test_message_id_round_trip(self):
        self.assertIsNone(self.manager.find_by_message("123", 999))
        self.assertTrue(self.manager.set_message_id("123", self.poll["id"], 999))
        found = self.manager.find_by_message("123", 999)
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], self.poll["id"])

    async def test_reaction_add_records_vote(self):
        self.manager.set_message_id("123", self.poll["id"], 999)
        monitor = _bare_monitor(self.manager)
        await monitor.handle_reaction_vote(_payload())
        option = self.manager.get_poll("123", self.poll["id"])["options"][0]
        self.assertIn("555", option["votes"])

    async def test_bot_self_reaction_is_ignored(self):
        self.manager.set_message_id("123", self.poll["id"], 999)
        monitor = _bare_monitor(self.manager)
        await monitor.handle_reaction_vote(_payload(user_id=1))
        option = self.manager.get_poll("123", self.poll["id"])["options"][0]
        self.assertNotIn("1", option["votes"])

    async def test_unknown_emoji_is_ignored(self):
        self.manager.set_message_id("123", self.poll["id"], 999)
        monitor = _bare_monitor(self.manager)
        await monitor.handle_reaction_vote(_payload(emoji="U0001f389"))
        option = self.manager.get_poll("123", self.poll["id"])["options"][0]
        self.assertNotIn("555", option["votes"])

    async def test_denied_user_is_rejected(self):
        self.manager.set_message_id("123", self.poll["id"], 999)
        monitor = _bare_monitor(self.manager)
        await monitor.handle_reaction_vote(_payload(user_id=404))
        option = self.manager.get_poll("123", self.poll["id"])["options"][0]
        self.assertNotIn("404", option["votes"])

    async def test_reaction_remove_withdraws_vote(self):
        self.manager.set_message_id("123", self.poll["id"], 999)
        monitor = _bare_monitor(self.manager)
        await monitor.handle_reaction_vote(_payload())
        await monitor.handle_reaction_vote(_payload(event_type="REACTION_REMOVE"))
        option = self.manager.get_poll("123", self.poll["id"])["options"][0]
        self.assertNotIn("555", option["votes"])

    async def test_vote_switch_via_different_reaction(self):
        self.manager.set_message_id("123", self.poll["id"], 999)
        monitor = _bare_monitor(self.manager)
        await monitor.handle_reaction_vote(_payload(emoji="1️⃣"))
        await monitor.handle_reaction_vote(_payload(emoji="2️⃣"))
        poll = self.manager.get_poll("123", self.poll["id"])
        self.assertNotIn("555", poll["options"][0]["votes"])
        self.assertIn("555", poll["options"][1]["votes"])


if __name__ == "__main__":
    unittest.main()
