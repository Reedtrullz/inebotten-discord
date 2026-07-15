#!/usr/bin/env python3
"""CRUD and handler regression tests for reminders."""

# pyright: reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUninitializedInstanceVariable=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnusedCallResult=false, reportUnusedVariable=false, reportAttributeAccessIssue=false

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cal_system.reminder_manager import ReminderManager, parse_reminder_command
from cal_system.temporal_resolver import DATE_ALIASES, TemporalResolver
from features.reminder_handler import ReminderHandler


OSLO_NOW = datetime.fromisoformat("2026-07-14T12:00:00+02:00")


class ReminderParserContractTests(unittest.TestCase):
    def parse(self, text):
        return parse_reminder_command(
            text,
            now=OSLO_NOW,
            temporal_resolver=TemporalResolver(),
        )

    def test_natural_create_is_canonical_and_fixed_clock(self):
        self.assertEqual(
            self.parse("Påminn meg om å ringe legen i morgen"),
            {
                "action": "add",
                "text": "ringe legen",
                "due_date": "15.07.2026",
                "time": "09:00",
                "due_at": "2026-07-15T09:00:00+02:00",
                "timezone": "Europe/Oslo",
            },
        )

    def test_trondelag_relative_create_is_canonical(self):
        parsed = self.parse("minn mæ om å ringe legen om 2 timer")
        self.assertEqual(parsed["text"], "ringe legen")
        self.assertEqual(parsed["due_at"], "2026-07-14T14:00:00+02:00")

    def test_all_bounded_reminder_frames_support_checklist_items(self):
        cases = (
            ("påminn meg om å kjøpe melk", "kjøpe melk"),
            ("minn meg om å kjøpe melk", "kjøpe melk"),
            ("minn mæ om å kjøpe melk", "kjøpe melk"),
            ("påminnelse kjøpe melk", "kjøpe melk"),
            ("påminning kjøpe mjølk", "kjøpe mjølk"),
            ("husk å kjøpe melk", "kjøpe melk"),
            ("hugs å kjøpe mjølk", "kjøpe mjølk"),
            ("reminder buy milk", "buy milk"),
        )
        for text, title in cases:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), {"action": "add", "text": title})

    def test_positive_forget_frames_are_canonical_in_nb_nn_and_en(self):
        cases = (
            ("ikke glem å kjøpe melk i morgen", "kjøpe melk"),
            ("ikkje gløym å kjøpe mjølk i morgon", "kjøpe mjølk"),
            ("don't forget to buy milk tomorrow", "buy milk"),
        )
        for text, expected_title in cases:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertEqual(parsed["action"], "add")
                self.assertEqual(parsed["text"], expected_title)
                self.assertEqual(parsed["due_date"], "15.07.2026")
                self.assertEqual(parsed["time"], "09:00")

    def test_polite_inflected_reminder_frames_are_canonical(self):
        cases = (
            "Kan du påminne meg om å ringe legen i morgen?",
            "Kunne du minne meg om å ringe legen i morgen?",
            "Vil du minne meg om å ringe legen i morgen?",
            "Please remind me to call the doctor tomorrow",
            "Could you remind me to call the doctor tomorrow?",
            "Would you remind me to call the doctor tomorrow?",
            "Kan du påminn meg om å ringe legen i morgen?",
        )
        for text in cases:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertEqual(parsed["action"], "add")
                self.assertEqual(parsed["due_date"], "15.07.2026")
                self.assertEqual(parsed["time"], "09:00")

    def test_all_task4_date_aliases_resolve_from_the_fixed_clock(self):
        for alias, offset in DATE_ALIASES.items():
            with self.subTest(alias=alias):
                parsed = self.parse(f"påminn meg om å ringe legen {alias}")
                expected = (OSLO_NOW.date() + timedelta(days=offset)).strftime(
                    "%d.%m.%Y"
                )
                self.assertEqual(parsed["text"], "ringe legen")
                self.assertEqual(parsed["due_date"], expected)
                self.assertEqual(parsed["time"], "09:00")

    def test_all_task4_weekday_aliases_are_recognized_and_cleaned(self):
        weekdays = (
            "mandag",
            "måndag",
            "monday",
            "tirsdag",
            "tuesday",
            "onsdag",
            "wednesday",
            "torsdag",
            "thursday",
            "fredag",
            "friday",
            "lørdag",
            "laurdag",
            "saturday",
            "søndag",
            "sundag",
            "sunday",
        )
        for weekday in weekdays:
            with self.subTest(weekday=weekday):
                parsed = self.parse(
                    f"påminn meg om å ringe legen på {weekday}"
                )
                self.assertEqual(parsed["text"], "ringe legen")
                self.assertEqual(parsed["time"], "09:00")
                self.assertIn("due_at", parsed)

    def test_title_cleanup_covers_every_task4_temporal_family(self):
        cases = (
            ("date_alias", "i morgen"),
            ("numeric_date", "20.07.2026"),
            ("month_date", "20. juli 2026"),
            ("weekday", "fredag"),
            ("relative", "om to timer"),
            ("natural_time", "20.07.2026 kl 14"),
            ("raw_time", "20.07.2026 14:00"),
            ("special_hour", "20.07.2026 noon"),
            ("daypart", "i kveld"),
        )
        for family, temporal in cases:
            with self.subTest(family=family):
                parsed = self.parse(
                    f"påminn meg om å ringe legen {temporal}"
                )
                self.assertEqual(parsed["text"], "ringe legen")
                self.assertIn("due_at", parsed)

    def test_date_only_default_is_applied_before_yearless_selection(self):
        before = parse_reminder_command(
            "påminn meg om medisinen 14.07",
            now=datetime.fromisoformat("2026-07-14T08:00:00+02:00"),
            temporal_resolver=TemporalResolver(),
        )
        after = parse_reminder_command(
            "påminn meg om medisinen 14.07",
            now=datetime.fromisoformat("2026-07-14T12:00:00+02:00"),
            temporal_resolver=TemporalResolver(),
        )
        self.assertEqual(before["due_at"], "2026-07-14T09:00:00+02:00")
        self.assertEqual(after["due_at"], "2027-07-14T09:00:00+02:00")

    def test_quoted_temporal_and_recurrence_words_remain_title_only(self):
        parsed = self.parse(
            'påminn meg om å lese "hver   dag i morgen"'
        )
        self.assertEqual(
            parsed,
            {"action": "add", "text": 'lese "hver   dag i morgen"'},
        )

    def test_quoted_title_keeps_spacing_and_outside_temporal_evidence(self):
        parsed = self.parse("påminn meg om «møte i morgen» på fredag")
        self.assertEqual(parsed["text"], "«møte i morgen»")
        self.assertEqual(parsed["due_at"], "2026-07-17T09:00:00+02:00")

    def test_temporal_cleanup_removes_only_stranded_connectors(self):
        parsed = self.parse("husk å ringe legen fredag og kl 14")
        self.assertEqual(parsed["text"], "ringe legen")
        self.assertEqual(self.parse("husk å stole på")["text"], "stole på")
        self.assertEqual(self.parse("husk å gå til")["text"], "gå til")

    def test_edit_uses_one_complete_canonical_object(self):
        self.assertEqual(
            self.parse("endre påminnelse 1 tekst: Ring tannlegen"),
            {
                "action": "edit",
                "number": 1,
                "changes": {"text": "Ring tannlegen"},
            },
        )

    def test_edit_masks_labels_inside_a_quoted_title(self):
        self.assertEqual(
            self.parse(
                'endre påminnelse 1 tekst: "Ring date: tomorrow" dato: fredag'
            ),
            {
                "action": "edit",
                "number": 1,
                "changes": {
                    "text": '"Ring date: tomorrow"',
                    "due_date": "17.07.2026",
                },
            },
        )

    def test_edit_rejects_unknown_duplicate_and_empty_labels(self):
        cases = (
            "endre påminnelse 1 tekst: Ring prioritet: høy",
            "endre påminnelse 1 tekst: Ring text: igjen",
            "endre påminnelse 1 tekst: dato: fredag",
            'endre påminnelse 1 tekst: ""',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_edit_rejects_contradictory_temporal_clauses(self):
        cases = (
            "endre påminnelse 1 dato: i morgen 20.07.2026",
            "endre påminnelse 1 dato: fredag tid: kl 14 kl 15",
            'endre påminnelse 1 dato: "i morgen"',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_target_actions_require_a_selector(self):
        self.assertEqual(
            self.parse("slett påminnelse 2"),
            {"action": "delete", "number": 2},
        )
        self.assertEqual(
            self.parse("fullfør påminnelse 2"),
            {"action": "complete", "number": 2},
        )
        self.assertIsNone(self.parse("slett påminnelse"))
        self.assertIsNone(self.parse("endre påminnelse"))

    def test_inflected_and_labeled_target_selectors_are_bounded(self):
        cases = {
            "slett påminnelsen 1": {"action": "delete", "number": 1},
            "delete the reminder 1": {"action": "delete", "number": 1},
            "complete reminder number 1": {
                "action": "complete",
                "number": 1,
            },
            "delete reminder #1": {"action": "delete", "number": 1},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_reminder_ids_require_manager_shape_or_explicit_id_prefix(self):
        cases = {
            "slett påminnelse rem_123_abcdef": {
                "action": "delete",
                "reminder_id": "rem_123_abcdef",
            },
            "slett påminnelse id custom_1": {
                "action": "delete",
                "reminder_id": "custom_1",
            },
            "endre påminnelse rem_123_abcdef tekst: Ring": {
                "action": "edit",
                "reminder_id": "rem_123_abcdef",
                "changes": {"text": "Ring"},
            },
            "endre påminnelse id custom_1 tekst: Ring": {
                "action": "edit",
                "reminder_id": "custom_1",
                "changes": {"text": "Ring"},
            },
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_unlabeled_words_are_not_reminder_ids(self):
        for selector in ("tomorrow", "fredag", "tuesday", "mandag"):
            with self.subTest(selector=selector, action="delete"):
                self.assertIsNone(
                    self.parse(f"slett påminnelse {selector}")
                )
            with self.subTest(selector=selector, action="edit"):
                self.assertIsNone(
                    self.parse(
                        f"endre påminnelse {selector} tekst: Ring"
                    )
                )

    def test_watchlist_media_frames_are_excluded(self):
        for text in (
            "husk å se Arrival",
            "hugs å sjå Arrival",
            "remember to watch Arrival",
            'husk å se "Arrival"',
            "hugs å sjå «Arrival»",
            'remember to watch "Arrival"',
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_non_media_watch_frames_remain_reminders(self):
        cases = {
            "husk å se på saken i morgen": "se på saken",
            "husk å se om døra er låst": "se om døra er låst",
            "husk å se til barna": "se til barna",
            "remember to watch the kids tomorrow": "watch the kids",
            "husk å se Arrival i morgen": "se Arrival",
        }
        for text, expected_title in cases.items():
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertEqual(parsed["action"], "add")
                self.assertEqual(parsed["text"], expected_title)


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

    def test_complete_reminder_uses_display_sorted_order(self):
        later_id = self.manager.add_reminder("123", "1", "Alice", "Lagt til først")
        earlier_id = self.manager.add_reminder("123", "1", "Alice", "Vises først")
        for reminder in self.manager.reminders["123"]:
            if reminder["id"] == later_id:
                reminder["created_at"] = "2026-06-18T12:00:00"
            if reminder["id"] == earlier_id:
                reminder["created_at"] = "2026-06-18T08:00:00"

        success, text, _ = self.manager.complete_reminder("123", reminder_num=1)

        self.assertTrue(success)
        self.assertEqual(text, "Vises først")
        completed = {reminder["text"]: reminder["completed"] for reminder in self.manager.reminders["123"]}
        self.assertFalse(completed["Lagt til først"])
        self.assertTrue(completed["Vises først"])


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

    async def test_handle_reminder_search_outputs_matches(self):
        message = SimpleNamespace(
            content="@inebotten søk påminnelse første",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_search(message)

        self.handler.send_response.assert_awaited_once()
        self.assertIn("Første oppgave", self.handler.send_response.await_args.args[1])

    async def test_handle_reminder_create_adds_reminder(self):
        message = SimpleNamespace(
            content="@inebotten påminnelse Ring lege 20.06",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_create(message)

        texts = [reminder["text"] for reminder in self.manager.reminders["123"]]
        self.assertIn("Ring lege", texts)
        self.handler.send_response.assert_awaited()

    async def test_handle_reminder_list_outputs_active_reminders(self):
        message = SimpleNamespace(
            content="@inebotten påminnelser",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_list(message)

        self.handler.send_response.assert_awaited_once()
        self.assertIn("Første oppgave", self.handler.send_response.await_args.args[1])

    async def test_handle_reminder_complete_marks_done(self):
        message = SimpleNamespace(
            content="@inebotten ferdig påminnelse 1",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_complete(message)

        self.assertTrue(self.manager.reminders["123"][0]["completed"])
        self.handler.send_response.assert_awaited_once()
        self.assertIn("Fullført", self.handler.send_response.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
