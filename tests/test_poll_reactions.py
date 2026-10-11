#!/usr/bin/env python3
import unittest
import asyncio
import gc
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

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


def _blocked_refresh(manager):
    first_fetch = asyncio.Event()
    release = asyncio.Event()
    edits = []

    class Message:
        async def edit(self, content):
            edits.append(content)

    class Channel:
        calls = 0

        async def fetch_message(self, message_id):
            self.calls += 1
            if self.calls == 1:
                first_fetch.set()
                await release.wait()
            return Message()

    channel = Channel()
    monitor = _bare_monitor(manager)
    monitor.client.get_channel = lambda _: channel
    return monitor, first_fetch, release, edits


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

    async def test_reaction_vote_edits_poll_post(self):
        self.manager.set_message_id("123", self.poll["id"], 999, 777)
        edits = []

        class FakeMessage:
            async def edit(self, content):
                edits.append(content)

        class FakeChannel:
            async def fetch_message(self, message_id):
                return FakeMessage()

        monitor = _bare_monitor(self.manager)
        monitor.client.get_channel = lambda channel_id: FakeChannel()
        await monitor.handle_reaction_vote(_payload())
        self.assertIn("Totalt: 1", edits[0])

    async def test_reaction_and_text_refresh_finish_with_latest_committed_votes(self):
        self.manager.set_message_id('123', self.poll['id'], 999, 777)
        monitor, fetched, release, edits = _blocked_refresh(self.manager)
        first = asyncio.create_task(monitor.handle_reaction_vote(_payload()))
        await asyncio.wait_for(fetched.wait(), 1)
        self.assertTrue(self.manager.vote('123', self.poll['id'], 2, '556', 'Text voter')[0])
        latest = self.manager.get_poll('123', self.poll['id'])
        second = asyncio.create_task(monitor.refresh_poll_post(latest))
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        self.assertEqual(edits[-1], self.manager.format_poll(latest))
        self.assertIn('Totalt: 2', edits[-1])

    async def test_closure_during_refresh_cannot_restore_an_active_post(self):
        self.manager.set_message_id('123', self.poll['id'], 999, 777)
        monitor, fetched, release, edits = _blocked_refresh(self.manager)
        first = asyncio.create_task(monitor.refresh_poll_post(self.manager.get_poll('123', self.poll['id'])))
        await asyncio.wait_for(fetched.wait(), 1)
        success, closed = self.manager.close_poll('123', self.poll['id'])
        self.assertTrue(success)
        second = asyncio.create_task(monitor.refresh_poll_post(closed))
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        self.assertEqual(edits[-1], self.manager.format_poll(closed))
        self.assertNotIn('Stem med tall', edits[-1])

    async def test_deletion_during_fetch_does_not_publish_a_removed_poll(self):
        self.manager.set_message_id('123', self.poll['id'], 999, 777)
        monitor, fetched, release, edits = _blocked_refresh(self.manager)
        task = asyncio.create_task(monitor.refresh_poll_post(self.manager.get_poll('123', self.poll['id'])))
        await asyncio.wait_for(fetched.wait(), 1)
        self.assertTrue(self.manager.delete_poll('123', self.poll['id'], '7', 'Tester')[0])
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual(edits, [])

    async def test_failed_edit_does_not_block_next_refresh_or_lose_votes(self):
        self.manager.set_message_id('123', self.poll['id'], 999, 777)
        edits = []

        class Message:
            calls = 0

            async def edit(self, content):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError('synthetic edit failure')
                edits.append(content)

        message = Message()

        class Channel:
            async def fetch_message(self, message_id):
                return message

        monitor = _bare_monitor(self.manager)
        monitor.client.get_channel = lambda _: Channel()
        self.manager.vote('123', self.poll['id'], 1, '555', 'Voter')
        latest = self.manager.get_poll('123', self.poll['id'])
        await monitor.refresh_poll_post(latest)
        await monitor.refresh_poll_post(latest)
        self.assertEqual(edits, [self.manager.format_poll(latest)])
        saved = self.manager.get_poll('123', self.poll['id'])
        assert saved is not None
        self.assertIn('555', saved['options'][0]['votes'])

    async def test_stalled_fetch_times_out_and_releases_refresh_state(self):
        self.manager.set_message_id('123', self.poll['id'], 999, 777)
        monitor, fetched, release, edits = _blocked_refresh(self.manager)
        latest = self.manager.get_poll('123', self.poll['id'])
        real_timeout = asyncio.timeout
        with patch('core.message_monitor.asyncio.timeout', side_effect=lambda seconds: real_timeout(0.01)) as timeout:
            await asyncio.wait_for(monitor.refresh_poll_post(latest), 1)
        timeout.assert_called_once_with(10)
        self.assertTrue(fetched.is_set())
        self.assertEqual(edits, [])
        release.set()
        await monitor.refresh_poll_post(latest)
        self.assertEqual(edits, [self.manager.format_poll(latest)])
        gc.collect()
        self.assertEqual(len(monitor._poll_refresh_locks), 0)


if __name__ == "__main__":
    unittest.main()
