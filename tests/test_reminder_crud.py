#!/usr/bin/env python3
"""CRUD and handler regression tests for reminders."""

# pyright: reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUninitializedInstanceVariable=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnusedCallResult=false, reportUnusedVariable=false, reportAttributeAccessIssue=false

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cal_system.reminder_manager import ReminderManager
from features.reminder_handler import ReminderHandler


class ReminderManagerCRUDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.storage_path = Path(self.tmp.name) / "reminders.json"
        self.manager = ReminderManager(storage_path=self.storage_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_reminder_happy_path_updates_title(self):
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave")

        updated = self.manager.edit_reminder("123", 1, title="Ny oppgave")

        self.assertEqual(updated["text"], "Ny oppgave")
        self.assertEqual(self.manager.reminders["123"][0]["text"], "Ny oppgave")

    def test_edit_reminder_updates_date(self):
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave", "01.05.2026")

        updated = self.manager.edit_reminder("123", 1, date="15.05.2026")

        self.assertEqual(updated["due_date"], "15.05.2026")
        self.assertEqual(self.manager.reminders["123"][0]["due_date"], "15.05.2026")

    def test_edit_reminder_invalid_index_raises_value_error(self):
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave")

        with self.assertRaises(ValueError):
            self.manager.edit_reminder("123", 2, title="Ugyldig")

    def test_delete_reminder_by_id_removes_reminder(self):
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave")

        deleted = self.manager.delete_reminder_by_id("123", 1)

        self.assertEqual(deleted["text"], "Første oppgave")
        self.assertEqual(self.manager.reminders["123"], [])

    def test_delete_reminder_by_id_invalid_index_raises_value_error(self):
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave")

        with self.assertRaises(ValueError):
            self.manager.delete_reminder_by_id("123", 2)

    def test_search_reminders_finds_by_title(self):
        self.manager.add_reminder("123", "1", "Alice", "Kjøpe melk")
        self.manager.add_reminder("123", "1", "Alice", "Ringe bestemor")

        matches = self.manager.search_reminders("123", "melk")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["text"], "Kjøpe melk")

    def test_search_reminders_includes_completed_reminders(self):
        _ = self.manager.add_reminder("123", "1", "Alice", "Kjøpe melk")
        completed = self.manager.add_reminder("123", "1", "Alice", "Ringe bestemor")
        for reminder in self.manager.reminders["123"]:
            if reminder["id"] == completed:
                reminder["completed"] = True

        matches = self.manager.search_reminders("123", "bestemor")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], completed)
        self.assertTrue(matches[0]["completed"])

    def test_search_reminders_is_case_insensitive(self):
        self.manager.add_reminder("123", "1", "Alice", "Ta Medisin")

        matches = self.manager.search_reminders("123", "medISin")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["text"], "Ta Medisin")


class ReminderHandlerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.storage_path = Path(self.tmp.name) / "reminders.json"
        self.manager = ReminderManager(storage_path=self.storage_path)
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave", "01.05.2026")

        self.monitor = SimpleNamespace(
            reminders=self.manager,
            rate_limiter=SimpleNamespace(record_sent=lambda: None, record_failure=lambda **kwargs: None),
            loc=SimpleNamespace(
                t=lambda key, **kwargs: f"{key}:{kwargs.get('title', kwargs.get('num', ''))}"
            ),
            client=SimpleNamespace(),
        )
        self.handler = ReminderHandler(self.monitor)
        self.handler.send_response = AsyncMock(return_value=None)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_handle_reminder_edit_updates_title(self):
        message = SimpleNamespace(
            content="@inebotten endre påminnelse 1 tittel: Oppdatert tittel",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_edit(message)

        self.assertEqual(self.manager.reminders["123"][0]["text"], "Oppdatert tittel")
        self.handler.send_response.assert_awaited_once()
        self.assertIn("reminder_edit_success", self.handler.send_response.await_args.args[1])
        self.assertIn("Oppdatert tittel", self.handler.send_response.await_args.args[1])

    async def test_handle_reminder_delete_removes_reminder(self):
        message = SimpleNamespace(
            content="@inebotten slett påminnelse 1",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_delete(message)

        self.assertEqual(self.manager.reminders["123"], [])
        self.handler.send_response.assert_awaited_once()
        self.assertIn("reminder_delete_success", self.handler.send_response.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
