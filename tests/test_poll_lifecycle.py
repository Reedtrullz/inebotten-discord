"""Poll expiry, option identity, and edit preview regressions."""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.intent_router import BotIntent, IntentRouter
from features.poll_manager import PollManager, PollStorageError
from features.polls_handler import PollsHandler


class PollLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.pm = PollManager(storage_path=Path(self.tmp.name) / "polls.json")
        self.poll = self.pm.create_poll(
            "123", "Dinner?", ["Pizza", "Soup"], "Owner", "1"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_expiry_rejects_direct_vote(self):
        expiry = datetime.fromisoformat(self.poll["expires_at"])
        with patch("features.poll_manager.datetime") as clock:
            clock.now.return_value = expiry
            clock.fromisoformat = datetime.fromisoformat
            result = self.pm.vote("123", self.poll["id"], 1, "2", "Voter")
        self.assertFalse(result[0])
        self.assertIn("expired", result[1].lower())
        self.assertEqual(self.poll["options"][0]["votes"], [])

    def test_label_only_edit_preserves_vote_and_option_identity(self):
        old_ids = [option["id"] for option in self.poll["options"]]
        self.pm.vote("123", self.poll["id"], 1, "2", "Voter")
        preview = self.pm.preview_poll_edit(
            "123", self.poll["id"], {"options": ["Margherita", "Soup"]}, "1"
        )
        self.assertEqual(preview["effect"], "preserve_votes")
        success, result = self.pm.apply_poll_edit(
            "123", self.poll["id"], "1", preview["token"]
        )
        self.assertTrue(success)
        self.assertEqual(
            [option["id"] for option in result["options"]], old_ids
        )
        self.assertEqual(result["options"][0]["votes"], ["2"])

    def test_removed_option_requires_confirmed_reset_preview(self):
        self.pm.vote("123", self.poll["id"], 2, "2", "Voter")
        preview = self.pm.preview_poll_edit(
            "123", self.poll["id"], {"options": ["Pizza"]}, "1"
        )
        self.assertEqual(preview["effect"], "reset_votes")
        self.assertTrue(preview["requires_confirmation"])
        denied = self.pm.apply_poll_edit(
            "123", self.poll["id"], "1", preview["token"]
        )
        self.assertFalse(denied[0])
        success, result = self.pm.apply_poll_edit(
            "123", self.poll["id"], "1", preview["token"], confirm_reset=True
        )
        self.assertTrue(success)
        self.assertEqual(len(result["options"]), 1)

    def test_stale_reset_preview_cannot_apply_after_vote_revision(self):
        preview = self.pm.preview_poll_edit(
            "123", self.poll["id"], {"options": ["Pizza"]}, "1"
        )
        self.pm.vote("123", self.poll["id"], 1, "2", "Voter")
        result = self.pm.apply_poll_edit(
            "123", self.poll["id"], "1", preview["token"], confirm_reset=True
        )
        self.assertFalse(result[0])
        self.assertIn("stale", result[1].lower())
        self.assertEqual(len(self.poll["options"]), 2)

    def test_preview_confirmation_is_bound_to_owner_actor(self):
        preview = self.pm.preview_poll_edit(
            "123", self.poll["id"], {"options": ["Pizza"]}, "1"
        )
        refused = self.pm.apply_poll_edit(
            "123", self.poll["id"], "9", preview["token"], confirm_reset=True
        )
        self.assertFalse(refused[0])
        self.assertIn("actor", refused[1].lower())
        accepted = self.pm.apply_poll_edit(
            "123", self.poll["id"], "1", preview["token"], confirm_reset=True
        )
        self.assertTrue(accepted[0])

    def test_non_owner_cannot_preview_or_apply_poll_edit(self):
        result = self.pm.preview_poll_edit(
            "123", self.poll["id"], {"options": ["Pizza"]}, "9"
        )
        self.assertFalse(result["ok"])
        self.assertIn("owner", result["error"].lower())

    def test_vote_write_failure_reports_failure_and_restores_state(self):
        before_revision = self.poll["revision"]
        with patch.object(
            self.pm, "_save_polls", side_effect=OSError("disk full")
        ):
            success, error = self.pm.vote(
                "123", self.poll["id"], 1, "2", "Voter"
            )
        self.assertFalse(success)
        self.assertIn("could not be saved", error.lower())
        self.assertEqual(self.poll["options"][0]["votes"], [])
        self.assertEqual(self.poll["revision"], before_revision)

    def test_create_write_failure_raises_typed_error(self):
        with patch.object(
            self.pm, "_save_polls", side_effect=OSError("disk full")
        ):
            with self.assertRaisesRegex(
                PollStorageError, "could not be saved"
            ):
                self.pm.create_poll(
                    "456", "Synthetic?", ["A", "B"], "Owner", "1"
                )
        self.assertNotIn("456", self.pm.polls)

    def test_legacy_poll_ids_and_revision_survive_reload(self):
        poll = self.pm.create_poll(
            "123", "Legacy?", ["One", "Two"], "Owner", "1"
        )
        raw = self.pm.polls["123"][poll["id"]]
        raw.pop("revision")
        for option in raw["options"]:
            option.pop("id")
        self.pm._save_polls()
        reloaded = PollManager(storage_path=self.pm.storage_path)
        first = reloaded.get_poll("123", poll["id"])
        ids = [option["id"] for option in first["options"]]
        again = PollManager(
            storage_path=self.pm.storage_path
        ).get_poll("123", poll["id"])
        self.assertEqual(first["revision"], 0)
        self.assertEqual(
            ids, [option["id"] for option in again["options"]]
        )

    def test_closed_results_route_and_history_read(self):
        monitor = SimpleNamespace(poll=self.pm)
        router = IntentRouter(monitor)
        self.assertEqual(
            router.route("poll results").intent, BotIntent.POLL_LIST
        )
        self.assertEqual(
            router.route("poll results").reason, "poll_results_command"
        )
        self.pm.vote("123", self.poll["id"], 1, "2", "Voter")
        self.pm.close_poll("123", self.poll["id"], "1", "Owner")
        result = self.pm.get_closed_poll_results("123", self.poll["id"])
        self.assertEqual(result["options"][0]["votes"], ["2"])


class PollResultsHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_results_command_uses_closed_history(self):
        with TemporaryDirectory() as tmp:
            manager = PollManager(storage_path=Path(tmp) / "polls.json")
            poll = manager.create_poll(
                "123", "Dinner?", ["Pizza", "Soup"], "Owner", "1"
            )
            manager.vote("123", poll["id"], 1, "2", "Voter")
            manager.close_poll("123", poll["id"], "1", "Owner")
            monitor = SimpleNamespace(
                poll=manager,
                loc=SimpleNamespace(
                    t=lambda key, **kwargs: key, current_lang="en"
                ),
                rate_limiter=SimpleNamespace(
                    record_sent=lambda: None,
                    record_failure=lambda **kwargs: None,
                ),
                client=None,
            )
            handler = PollsHandler(monitor)
            handler.send_response = AsyncMock()
            message = SimpleNamespace(
                content="@inebotten poll results",
                guild=SimpleNamespace(id=123),
                channel=SimpleNamespace(id=456),
                author=SimpleNamespace(id=2, name="Reader"),
            )
            await handler.handle_poll_list(message)
            self.assertIn("Dinner?", handler.send_response.await_args.args[1])
            self.assertIn(
                "lukket", handler.send_response.await_args.args[1].lower()
            )

    async def test_structural_edit_handler_requires_token_confirmation(self):
        with TemporaryDirectory() as tmp:
            manager = PollManager(storage_path=Path(tmp) / "polls.json")
            poll = manager.create_poll(
                "123", "Dinner?", ["Pizza", "Soup"], "Owner", "1"
            )
            manager.vote("123", poll["id"], 2, "2", "Voter")
            monitor = SimpleNamespace(
                poll=manager,
                loc=SimpleNamespace(
                    t=lambda key, **kwargs: key, current_lang="en"
                ),
                rate_limiter=SimpleNamespace(
                    record_sent=lambda: None,
                    record_failure=lambda **kwargs: None,
                ),
                client=None,
            )
            handler = PollsHandler(monitor)
            handler.send_response = AsyncMock()
            message = SimpleNamespace(
                guild=SimpleNamespace(id=123),
                channel=SimpleNamespace(id=456),
                author=SimpleNamespace(id=1, name="Owner"),
            )

            await handler.handle_poll_edit(
                message, {"target": 1, "changes": {"options": ["Pizza"]}}
            )
            preview_text = handler.send_response.await_args.args[1]
            self.assertIn("nullstille stemmene", preview_text)
            self.assertEqual(
                manager.get_poll("123", poll["id"])["options"][1]["votes"],
                ["2"],
            )
            token = preview_text.split(
                "bekreft poll endring ", 1
            )[1].split(" ", 1)[0]

            await handler.handle_poll_edit(
                message, {"confirm_token": token, "confirm_reset": True}
            )
            updated = manager.get_poll("123", poll["id"])
            self.assertEqual(len(updated["options"]), 1)
            self.assertEqual(updated["options"][0]["votes"], [])


if __name__ == "__main__":
    unittest.main()
