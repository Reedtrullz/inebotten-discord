import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from features.poll_manager import PollManager


class PollManagerEditDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.pm = PollManager(storage_path=Path(self.tmp.name) / "polls.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_poll_stores_created_by_id(self):
        poll = self.pm.create_poll(
            guild_id="123",
            question="Pizza?",
            options=["Ja", "Nei"],
            created_by="Alice",
            created_by_id="111",
        )
        self.assertEqual(poll["created_by"], "Alice")
        self.assertEqual(poll["created_by_id"], "111")

    def test_get_poll_returns_poll_or_none(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        self.assertEqual(self.pm.get_poll("123", poll["id"]), poll)
        self.assertIsNone(self.pm.get_poll("123", "nonexistent"))
        self.assertIsNone(self.pm.get_poll("999", poll["id"]))

    def test_is_poll_owner_with_created_by_id(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        self.assertTrue(self.pm.is_poll_owner(poll, "111", "Alice"))
        self.assertTrue(self.pm.is_poll_owner(poll, "111", "Bob"))
        self.assertFalse(self.pm.is_poll_owner(poll, "222", "Alice"))

    def test_is_poll_owner_fallback_to_username(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice")
        self.assertTrue(self.pm.is_poll_owner(poll, "111", "Alice"))
        self.assertFalse(self.pm.is_poll_owner(poll, "111", "Bob"))
        self.assertFalse(self.pm.is_poll_owner(poll, "111"))

    def test_edit_poll_success(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.edit_poll(
            "123", poll["id"], "111", "Alice", question="New Q?", options=["X", "Y", "Z"]
        )
        self.assertTrue(success)
        self.assertEqual(result["question"], "New Q?")
        self.assertEqual([o["text"] for o in result["options"]], ["X", "Y", "Z"])

    def test_edit_poll_not_found(self):
        success, result = self.pm.edit_poll("123", "nope", "111", "Alice", question="X")
        self.assertFalse(success)
        self.assertEqual(result, "Poll not found")

    def test_edit_poll_not_owner(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.edit_poll("123", poll["id"], "222", "Bob", question="X")
        self.assertFalse(success)
        self.assertIn("owner", result.lower())

    def test_edit_poll_closed(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        self.pm.close_poll("123", poll["id"], "111", "Alice")
        success, result = self.pm.edit_poll("123", poll["id"], "111", "Alice", question="X")
        self.assertFalse(success)
        self.assertEqual(result, "Poll is closed")

    def test_delete_poll_success(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.delete_poll("123", poll["id"], "111", "Alice")
        self.assertTrue(success)
        self.assertEqual(result, "Poll deleted")
        self.assertIsNone(self.pm.get_poll("123", poll["id"]))

    def test_delete_poll_not_owner(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.delete_poll("123", poll["id"], "222", "Bob")
        self.assertFalse(success)
        self.assertIn("owner", result.lower())

    def test_close_poll_with_ownership_check(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.close_poll("123", poll["id"], "111", "Alice")
        self.assertTrue(success)
        self.assertEqual(result["status"], "closed")

    def test_close_poll_not_owner(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.close_poll("123", poll["id"], "222", "Bob")
        self.assertFalse(success)
        self.assertIn("owner", result.lower())

    def test_close_poll_already_closed(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        self.pm.close_poll("123", poll["id"], "111", "Alice")
        success, result = self.pm.close_poll("123", poll["id"], "111", "Alice")
        self.assertFalse(success)
        self.assertEqual(result, "Poll is already closed")

    def test_close_poll_without_user_id_allows_anyone(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice", "111")
        success, result = self.pm.close_poll("123", poll["id"])
        self.assertTrue(success)
        self.assertEqual(result["status"], "closed")

    def test_backward_compat_create_poll_without_created_by_id(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice")
        self.assertIn("created_by_id", poll)
        self.assertIsNone(poll["created_by_id"])

    def test_active_poll_read_handles_all_expiry_time_formats(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice")
        before = datetime(2026, 7, 14, 21, 59, tzinfo=timezone.utc)
        exact = datetime(
            2026,
            7,
            14,
            18,
            0,
            tzinfo=ZoneInfo("America/New_York"),
        )
        after = datetime(2026, 7, 14, 22, 1, tzinfo=timezone.utc)

        for expires_at in (
            "2026-07-15T00:00:00",
            "2026-07-15T00:00:00+02:00",
            "2026-07-14T22:00:00Z",
        ):
            with self.subTest(expires_at=expires_at):
                poll["expires_at"] = expires_at
                self.assertEqual(
                    self.pm.get_active_polls(
                        "123", reference_time=before
                    ),
                    [poll],
                )
                self.assertEqual(
                    self.pm.get_active_polls(
                        "123", reference_time=exact
                    ),
                    [],
                )
                self.assertEqual(
                    self.pm.get_active_polls(
                        "123", reference_time=after
                    ),
                    [],
                )

    def test_active_poll_read_preserves_legacy_no_reference_call(self):
        poll = self.pm.create_poll("123", "Q?", ["A", "B"], "Alice")

        self.assertEqual(self.pm.get_active_polls("123"), [poll])

        poll["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(days=7)
        ).isoformat()
        self.assertEqual(self.pm.get_active_polls("123"), [poll])

    def test_active_poll_read_rejects_naive_reference_time(self):
        with self.assertRaisesRegex(ValueError, "reference_time_must_be_aware"):
            self.pm.get_active_polls(
                "123", reference_time=datetime(2026, 7, 14, 12, 0)
            )


if __name__ == "__main__":
    unittest.main()
