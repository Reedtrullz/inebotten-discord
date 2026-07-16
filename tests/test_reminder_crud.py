#!/usr/bin/env python3
"""CRUD and handler regression tests for reminders."""

# pyright: reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUninitializedInstanceVariable=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnusedCallResult=false, reportUnusedVariable=false, reportAttributeAccessIssue=false

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cal_system.reminder_manager import ReminderManager, parse_reminder_command
from cal_system.temporal_resolver import DATE_ALIASES, TemporalResolver
from core.dispatch_result import DeliveryState, MessageSendResult
from core.eval_fixtures import EvalFixture
from core.intent_models import BotIntent
from features.reminder_handler import ReminderHandler
from tests.nlu_harness import build_production_router


@pytest.mark.parametrize(
    "text",
    (
        "how many reminders do I have?",
        "show me all my reminders",
        "do I have any reminders?",
    ),
)
def test_natural_reminder_inventory_questions_parse_as_one_list(text):
    assert parse_reminder_command(text) == {"action": "list"}


def test_reminder_search_connector_is_clean_end_to_end():
    result = build_production_router(
        EvalFixture.MIXED_STATE
    ).route_help_example("search reminders for watchlist")

    assert result.intent is BotIntent.REMINDER_SEARCH
    assert result.payload == {
        "reminder": {"action": "search", "query": "watchlist"}
    }


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

    def test_search_connector_is_not_part_of_the_query(self):
        self.assertEqual(
            self.parse("search reminders for watchlist"),
            {"action": "search", "query": "watchlist"},
        )

    def test_temporal_before_infinitive_does_not_leave_orphaned_to(self):
        cases = (
            (
                "remind me tomorrow to watch Inception",
                "watch Inception",
            ),
            (
                "remind me tomorrow to add Inception to my watchlist",
                "add Inception to my watchlist",
            ),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertEqual(parsed["text"], expected)
                self.assertEqual(parsed["due_date"], "15.07.2026")

        title = self.parse("remind me tomorrow To Kill a Mockingbird")
        self.assertEqual(title["text"], "To Kill a Mockingbird")

    def test_trondelag_relative_create_is_canonical(self):
        parsed = self.parse("minn mæ om å ringe legen om 2 timer")
        self.assertEqual(parsed["text"], "ringe legen")
        self.assertEqual(parsed["due_at"], "2026-07-14T14:00:00+02:00")

    def test_half_hour_and_dotted_time_reminders_are_canonical(self):
        half_hour = self.parse(
            "påminn meg om å ringe legen om en halvtime"
        )
        dotted = self.parse("påminn meg om å ringe legen kl 14.30")

        self.assertEqual(half_hour["text"], "ringe legen")
        self.assertEqual(
            half_hour["due_at"], "2026-07-14T12:30:00+02:00"
        )
        self.assertEqual(dotted["text"], "ringe legen")
        self.assertEqual(dotted["time"], "14:30")

    def test_unresolved_temporal_language_never_becomes_title_text(self):
        cases = (
            "påminn meg om å ringe legen senere i dag",
            "påminn meg om å ringe legen kl 123",
            "påminn meg om å ringe legen neste helg",
            "påminn meg om å ringe legen kvart over to",
            "kan du minne meg på å ringe legen i morgen klokka halv tre?",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_half_clock_with_daypart_is_removed_from_reminder_title(self):
        parsed = self.parse(
            "kan du minne meg på å ringe legen i morgen "
            "klokka halv tre på ettermiddagen"
        )

        self.assertEqual(parsed["text"], "ringe legen")
        self.assertEqual(parsed["time"], "14:30")
        self.assertEqual(
            parsed["due_at"],
            "2026-07-15T14:30:00+02:00",
        )

    def test_explicit_past_same_day_reminder_fails_closed(self):
        self.assertIsNone(
            self.parse("påminn meg om å ringe legen i dag kl 09")
        )

    def test_second_mutation_clause_is_not_folded_into_reminder_text(self):
        self.assertIsNone(
            self.parse(
                "påminn meg om å ringe legen i morgen og slett kalenderen"
            )
        )

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
                if offset == 0:
                    # Date-only reminders default to 09:00.  At the fixed
                    # noon reference, creating that already-missed occurrence
                    # must fail closed rather than claim it is scheduled.
                    self.assertIsNone(parsed)
                    continue
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

    def test_later_action_clause_never_becomes_part_of_a_reminder_write(self):
        cases = (
            "påminn meg om å ringe legen i morgen og slett kalenderen",
            "påminn meg om å ringe legen i morgen, og så slett kalenderen",
            "påminn meg om å ringe legen i morgen, deretter slett kalenderen",
            "påminn meg om å ringe legen i morgen, så slett kalenderen",
            "påminn meg om å ringe legen i morgen, slett kalenderen",
            "påminn meg om å ringe legen i morgen; slett kalenderen",
            "remind me to call the doctor tomorrow, then delete the calendar",
            "remind me to call the doctor tomorrow; after that delete the calendar",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_payload_conjunctions_and_quoted_action_words_remain_title_data(self):
        cases = (
            (
                "husk å kjøpe melk og brød i morgen",
                "kjøpe melk og brød",
            ),
            (
                "husk å ringe legen og bestille time i morgen",
                "ringe legen og bestille time",
            ),
            (
                "husk å kjøpe melk og lage middag i morgen",
                "kjøpe melk og lage middag",
            ),
            (
                'påminn meg om "og så slett kalenderen" i morgen',
                '"og så slett kalenderen"',
            ),
        )
        for text, expected_title in cases:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["text"], expected_title)

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
        self.reference_time = OSLO_NOW
        self.tmp = TemporaryDirectory()
        self.storage_path = Path(self.tmp.name) / "reminders.json"
        self.manager = ReminderManager(storage_path=self.storage_path)
        self.manager.add_reminder("123", "1", "Alice", "Første oppgave", "01.05.2026")

        self.monitor = SimpleNamespace(
            reminders=self.manager,
            rate_limiter=SimpleNamespace(record_sent=lambda: None, record_failure=lambda **kwargs: None),
            loc=SimpleNamespace(
                t=lambda key, **kwargs: f"{key}:{kwargs.get('title', kwargs.get('num', ''))}",
                current_lang="no",
            ),
            client=SimpleNamespace(),
            nlu_metrics=SimpleNamespace(
                record_legacy_payload_fallback=Mock(),
            ),
            nlp_parser=SimpleNamespace(
                temporal_resolver=TemporalResolver(),
            ),
        )
        self.handler = ReminderHandler(self.monitor)
        self.handler.send_response_result = AsyncMock(
            return_value=MessageSendResult(DeliveryState.DELIVERED)
        )

    def tearDown(self):
        self.tmp.cleanup()

    async def test_handle_reminder_edit_updates_title(self):
        message = SimpleNamespace(
            content="@inebotten endre påminnelse 1 tekst: Oppdatert tittel",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_edit(
            message,
            reference_time=self.reference_time,
        )

        self.assertEqual(self.manager.reminders["123"][0]["text"], "Oppdatert tittel")
        self.handler.send_response_result.assert_awaited_once()
        self.assertIn("reminder_edit_success", self.handler.send_response_result.await_args.args[1])
        self.assertIn("Oppdatert tittel", self.handler.send_response_result.await_args.args[1])

    async def test_time_only_edit_of_checklist_is_rejected_without_mutation(self):
        reminder_id = await self.manager.add_reminder_result(
            "123",
            "7",
            "Tester",
            "Udatert oppgave",
            reference_time=self.reference_time,
        )
        before_bytes = self.storage_path.read_bytes()
        before_root = self.manager.reminders

        outcome = await self.handler.handle_reminder_edit(
            SimpleNamespace(
                content="typed path must not parse this",
                guild=SimpleNamespace(id=123),
                channel=SimpleNamespace(id=456),
                author=SimpleNamespace(id=7, name="Tester"),
            ),
            {
                "action": "edit",
                "reminder_id": reminder_id,
                "changes": {"time": "14:00"},
            },
            reference_time=self.reference_time,
        )

        self.assertFalse(outcome.ok)
        self.assertFalse(outcome.mutated)
        self.assertFalse(outcome.retryable)
        self.assertEqual(outcome.error_code, "invalid_payload")
        self.assertIs(self.manager.reminders, before_root)
        self.assertEqual(self.storage_path.read_bytes(), before_bytes)
        checklist = next(
            reminder
            for reminder in self.manager.reminders["123"]
            if reminder["id"] == reminder_id
        )
        self.assertIsNone(checklist["due_at"])
        self.assertIsNone(checklist["due_date"])
        self.assertIsNone(checklist["time"])

    async def test_handle_reminder_delete_removes_reminder(self):
        message = SimpleNamespace(
            content="@inebotten slett påminnelse 1",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_delete(
            message,
            reference_time=self.reference_time,
        )

        self.assertEqual(self.manager.reminders["123"], [])
        self.handler.send_response_result.assert_awaited_once()
        self.assertIn("reminder_delete_success", self.handler.send_response_result.await_args.args[1])

    async def test_handle_reminder_search_outputs_matches(self):
        message = SimpleNamespace(
            content="@inebotten søk påminnelse første",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_search(
            message,
            reference_time=self.reference_time,
        )

        self.handler.send_response_result.assert_awaited_once()
        self.assertIn("Første oppgave", self.handler.send_response_result.await_args.args[1])

    async def test_handle_reminder_create_adds_reminder(self):
        message = SimpleNamespace(
            content="@inebotten påminnelse Ring lege",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_create(
            message,
            reference_time=self.reference_time,
        )

        texts = [reminder["text"] for reminder in self.manager.reminders["123"]]
        self.assertIn("Ring lege", texts)
        self.handler.send_response_result.assert_awaited()

    async def test_relative_fallback_persists_one_canonical_oslo_occurrence(self):
        message = SimpleNamespace(
            content="@inebotten minn mæ om å ringe legen om 2 timer",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        outcome = await self.handler.handle_reminder_create(
            message,
            reference_time=self.reference_time,
        )

        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.mutated)
        created = next(
            reminder
            for reminder in self.manager.reminders["123"]
            if reminder["text"] == "ringe legen"
        )
        self.assertEqual(created["due_at"], "2026-07-14T14:00:00+02:00")
        self.assertEqual(created["due_date"], "14.07.2026")
        self.assertEqual(created["time"], "14:00")
        self.assertEqual(created["timezone"], "Europe/Oslo")
        self.assertEqual(created["created_at"], self.reference_time.isoformat())
        self.monitor.nlu_metrics.record_legacy_payload_fallback.assert_called_once_with(
            "reminder"
        )

    async def test_handle_reminder_list_outputs_active_reminders(self):
        message = SimpleNamespace(
            content="@inebotten påminnelser",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_list(
            message,
            reference_time=self.reference_time,
        )

        self.handler.send_response_result.assert_awaited_once()
        self.assertIn("Første oppgave", self.handler.send_response_result.await_args.args[1])

    async def test_handle_reminder_complete_marks_done(self):
        message = SimpleNamespace(
            content="@inebotten ferdig påminnelse 1",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            author=SimpleNamespace(id=7, name="Tester"),
        )

        await self.handler.handle_reminder_complete(
            message,
            reference_time=self.reference_time,
        )

        self.assertTrue(self.manager.reminders["123"][0]["completed"])
        self.handler.send_response_result.assert_awaited_once()
        self.assertIn("Fullført", self.handler.send_response_result.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
