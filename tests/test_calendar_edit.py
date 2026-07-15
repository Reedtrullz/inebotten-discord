# pyright: reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUninitializedInstanceVariable=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownLambdaType=false, reportUnusedCallResult=false, reportAttributeAccessIssue=false

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from cal_system.calendar_manager import CalendarManager
from cal_system.temporal_resolver import TemporalResolver
from core.dispatch_result import (
    DeliveryState,
    ExternalCommitState,
    ExternalMutationResult,
    MessageSendResult,
)
from features.calendar_handler import CalendarHandler


def _date(days_ahead: int) -> str:
    return (datetime.now() + timedelta(days=days_ahead)).strftime("%d.%m.%Y")


class CalendarManagerEditSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.manager = CalendarManager(storage_path=Path(self.tmp.name) / "calendar.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _add_item(self, title: str, date: str, time: str = "09:00", **kwargs):
        return self.manager.add_item(
            guild_id="123",
            user_id="111",
            username="Alice",
            title=title,
            date_str=date,
            time_str=time,
            **kwargs,
        )

    def test_edit_item_happy_path_edit_title_by_index(self):
        self._add_item("Møte", _date(1))

        updated = self.manager.edit_item(1, title="Nytt møte")

        self.assertEqual(updated["title"], "Nytt møte")
        self.assertEqual(self.manager.get_upcoming("123")[0]["title"], "Nytt møte")

    def test_edit_item_edit_date_by_index(self):
        self._add_item("Møte", _date(1))

        updated = self.manager.edit_item(1, date=_date(5))

        self.assertEqual(updated["date"], _date(5))
        self.assertEqual(self.manager.get_upcoming("123")[0]["date"], _date(5))

    def test_edit_item_edit_multiple_fields(self):
        self._add_item("Møte", _date(1), time="09:00")

        updated = self.manager.edit_item(
            1,
            title="Planleggingsmøte",
            date=_date(3),
            time="14:30",
            recurrence="weekly",
            description="Ukentlig status",
        )

        self.assertEqual(updated["title"], "Planleggingsmøte")
        self.assertEqual(updated["date"], _date(3))
        self.assertEqual(updated["time"], "14:30")
        self.assertEqual(updated["recurrence"], "weekly")
        self.assertEqual(updated["description"], "Ukentlig status")

    def test_edit_item_invalid_index_raises_value_error(self):
        self._add_item("Møte", _date(1))

        with self.assertRaises(ValueError):
            self.manager.edit_item(2, title="X")

    def test_search_items_finds_by_title_substring(self):
        self._add_item("Møte med Ola", _date(1))
        self._add_item("Trening", _date(2))

        matches = self.manager.search_items("møte")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["title"], "Møte med Ola")

    def test_search_items_is_case_insensitive(self):
        self._add_item("Kaffemøte", _date(1))

        matches = self.manager.search_items("KAFFE")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["title"], "Kaffemøte")

    def test_search_items_no_results_returns_empty_list(self):
        self._add_item("Kaffemøte", _date(1))

        self.assertEqual(self.manager.search_items("middag"), [])

    def test_upcoming_read_uses_explicit_oslo_reference_date(self):
        self._add_item("Midnight boundary", "15.07.2026")
        oslo = ZoneInfo("Europe/Oslo")

        before = self.manager.get_upcoming(
            "123",
            days=0,
            reference_time=datetime(2026, 7, 14, 23, 59, tzinfo=oslo),
        )
        after = self.manager.get_upcoming(
            "123",
            days=0,
            reference_time=datetime(2026, 7, 15, 0, 1, tzinfo=oslo),
        )

        self.assertEqual(before, [])
        self.assertEqual([item["title"] for item in after], ["Midnight boundary"])

    def test_upcoming_read_converts_utc_across_oslo_midnight(self):
        self._add_item("UTC boundary", "15.07.2026")

        before = self.manager.get_upcoming(
            "123",
            days=0,
            reference_time=datetime(
                2026, 7, 14, 21, 59, tzinfo=timezone.utc
            ),
        )
        after = self.manager.get_upcoming(
            "123",
            days=0,
            reference_time=datetime(
                2026, 7, 14, 22, 1, tzinfo=timezone.utc
            ),
        )

        self.assertEqual(before, [])
        self.assertEqual([item["title"] for item in after], ["UTC boundary"])

    def test_upcoming_read_rejects_naive_reference_time(self):
        with self.assertRaisesRegex(ValueError, "reference_time_must_be_aware"):
            self.manager.get_upcoming(
                "123",
                reference_time=datetime(2026, 7, 14, 12, 0),
            )

    def test_calendar_save_uses_unique_atomic_temp_file(self):
        self._add_item("Møte", _date(1))

        leftover_temp_files = list(Path(self.tmp.name).glob("calendar.tmp"))

        self.assertEqual(leftover_temp_files, [])


class CalendarHandlerEditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.manager = CalendarManager(storage_path=Path(self.tmp.name) / "calendar.json")

        self.loc = SimpleNamespace(
            t=lambda key, **kwargs: {
                "calendar_edit_invalid": "Ugyldig redigeringsformat",
                "calendar_edit_not_found": f"Fant ikke {kwargs.get('num')}",
                "calendar_edit_success": f"Oppdatert: {kwargs.get('title')}",
            }[key]
        )

        self.monitor = SimpleNamespace(
            calendar=self.manager,
            nlp_parser=SimpleNamespace(parse_event=MagicMock(return_value=None)),
            rate_limiter=SimpleNamespace(
                record_sent=lambda: None,
                record_failure=lambda **kwargs: None,
                can_send=lambda: (True, None),
                wait_if_needed=AsyncMock(return_value=True),
            ),
            loc=self.loc,
            client=None,
            nlu_metrics=SimpleNamespace(
                record_legacy_payload_fallback=MagicMock()
            ),
        )
        self.handler = CalendarHandler(self.monitor)
        self.handler.send_response = AsyncMock()

        async def capture_send(message, text):
            await self.handler.send_response(message, text)
            return MessageSendResult(DeliveryState.DELIVERED)

        self.handler.send_response_result = AsyncMock(side_effect=capture_send)

        self.message = SimpleNamespace(
            content="",
            guild=SimpleNamespace(id="123"),
            channel=SimpleNamespace(id="999"),
            author=SimpleNamespace(id="111", name="Alice"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    async def _add_item(self, title: str, date: str, time: str = "09:00"):
        return await self.manager.add_item_result(
            guild_id="123",
            user_id="111",
            username="Alice",
            title=title,
            date_str=date,
            time_str=time,
            reference_time=self.manager.clock.now(),
        )

    def _add_item_sync(self, title: str, date: str, time: str = "09:00"):
        return self.manager.add_item(
            guild_id="123",
            user_id="111",
            username="Alice",
            title=title,
            date_str=date,
            time_str=time,
        )

    async def test_handle_clear_requires_explicit_confirmation(self):
        await self._add_item("Møte", _date(1))
        self.message.content = "@inebotten tøm kalender"

        await self.handler.handle_clear(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("bekreft 1", response)
        self.assertEqual(len(self.manager.items[self.manager.SHARED_KEY]), 1)

    async def test_handle_clear_confirmed_deletes_calendar(self):
        await self._add_item("Møte", _date(1))
        self.message.content = "@inebotten tøm kalender bekreft 1"

        await self.handler.handle_clear(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Slettet 1", response)
        self.assertEqual(self.manager.items[self.manager.SHARED_KEY], [])

    async def test_handle_clear_rejects_stale_confirmation_count(self):
        await self._add_item("Møte", _date(1))
        await self._add_item("Trening", _date(2))
        self.message.content = "@inebotten tøm kalender bekreft 1"

        await self.handler.handle_clear(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("bekreft 2", response)
        self.assertEqual(len(self.manager.items[self.manager.SHARED_KEY]), 2)

    async def test_clear_calendar_keeps_failed_gcal_deletes_pending(self):
        class FailingDeleteGCal:
            def __init__(self):
                self.delete_calls = []

            async def delete_event_result(self, event_id):
                self.delete_calls.append(event_id)
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="external_delete_failed",
                )

        gcal = FailingDeleteGCal()
        manager = CalendarManager(storage_path=Path(self.tmp.name) / "gcal-calendar.json", gcal_manager=gcal)
        await manager.add_item_result(
            guild_id="123",
            user_id="111",
            username="Alice",
            title="GCal møte",
            date_str=_date(1),
            time_str="09:00",
            gcal_event_id="gcal-1",
            reference_time=manager.clock.now(),
        )

        result = await manager.clear_calendar_result(
            "123",
            reference_time=manager.clock.now(),
        )

        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(gcal.delete_calls, ["gcal-1"])
        pending = manager.items[manager.SHARED_KEY][0]
        self.assertTrue(pending["delete_pending"])
        self.assertIn("delete_error", pending)
        self.assertEqual(manager.get_upcoming("123"), [])

    async def test_clear_calendar_removes_local_after_gcal_success(self):
        class SuccessfulDeleteGCal:
            def __init__(self):
                self.delete_calls = []

            async def delete_event_result(self, event_id):
                self.delete_calls.append(event_id)
                return ExternalMutationResult(
                    True,
                    ExternalCommitState.CHANGED,
                    value=True,
                )

        gcal = SuccessfulDeleteGCal()
        manager = CalendarManager(storage_path=Path(self.tmp.name) / "gcal-calendar.json", gcal_manager=gcal)
        await manager.add_item_result(
            guild_id="123",
            user_id="111",
            username="Alice",
            title="GCal møte",
            date_str=_date(1),
            time_str="09:00",
            gcal_event_id="gcal-1",
            reference_time=manager.clock.now(),
        )

        result = await manager.clear_calendar_result(
            "123",
            reference_time=manager.clock.now(),
        )

        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(gcal.delete_calls, ["gcal-1"])
        self.assertEqual(manager.items[manager.SHARED_KEY], [])

    async def test_single_gcal_delete_failure_marks_pending_not_removed(self):
        class FailingDeleteGCal:
            def __init__(self):
                self.delete_calls = []

            async def delete_event_result(self, event_id):
                self.delete_calls.append(event_id)
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="external_delete_failed",
                )

        gcal = FailingDeleteGCal()
        manager = CalendarManager(storage_path=Path(self.tmp.name) / "single-gcal-calendar.json", gcal_manager=gcal)
        item = await manager.add_item_result(
            guild_id="123",
            user_id="111",
            username="Alice",
            title="GCal møte",
            date_str=_date(1),
            time_str="09:00",
            gcal_event_id="gcal-1",
            reference_time=manager.clock.now(),
        )

        result = await manager.delete_item_result(
            "123",
            item_id=item["id"],
            reference_time=manager.clock.now(),
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(gcal.delete_calls, ["gcal-1"])
        pending = manager.items[manager.SHARED_KEY][0]
        self.assertTrue(pending["delete_pending"])
        self.assertEqual(manager.get_upcoming("123"), [])

    async def test_bulk_gcal_delete_failure_marks_pending_not_removed(self):
        class FailingDeleteGCal:
            async def delete_event_result(self, event_id):
                return ExternalMutationResult(
                    False,
                    ExternalCommitState.UNCHANGED,
                    error_code="external_delete_failed",
                )

        manager = CalendarManager(
            storage_path=Path(self.tmp.name) / "bulk-gcal-calendar.json",
            gcal_manager=FailingDeleteGCal(),
        )
        item = await manager.add_item_result(
            guild_id="123",
            user_id="111",
            username="Alice",
            title="Standup",
            date_str=_date(1),
            time_str="09:00",
            gcal_event_id="gcal-1",
            reference_time=manager.clock.now(),
        )

        result = await manager.delete_item_result(
            "123",
            item_id=item["id"],
            reference_time=manager.clock.now(),
        )

        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["pending_count"], 1)
        self.assertTrue(manager.items[manager.SHARED_KEY][0]["delete_pending"])
        self.assertEqual(manager.get_upcoming("123"), [])

    def test_search_results_use_global_calendar_index(self):
        self._add_item_sync("Alpha", _date(1), time="09:00")
        self._add_item_sync("Send inn meldekort", _date(2), time="12:00")

        rendered = self.manager.format_search_results("meldekort")

        self.assertIn("**2.** Send inn meldekort", rendered)
        self.assertIn("Numrene matcher", rendered)

    async def test_handle_edit_integration_parse_and_execute_edit(self):
        await self._add_item("Møte", _date(1), time="09:00")
        self.message.content = "@inebotten endre 1 tittel: Ny tittel"

        await self.handler.handle_edit(self.message)

        self.handler.send_response.assert_awaited_once_with(
            self.message, "Oppdatert: Ny tittel"
        )
        self.assertEqual(self.manager.get_upcoming("123")[0]["title"], "Ny tittel")

    async def test_handle_edit_invalid_format_returns_error_message(self):
        self.message.content = "@inebotten endre 1 tittel Ny tittel"

        await self.handler.handle_edit(self.message)

        self.handler.send_response.assert_awaited_once_with(
            self.message, "Ugyldig redigeringsformat"
        )

    async def test_handle_edit_search_by_title_then_edit(self):
        await self._add_item("Møte med Ola", _date(1), time="09:00")
        target_date = _date(7)
        self.message.content = f"@inebotten rediger møte med ola dato: {target_date}"

        await self.handler.handle_edit(self.message)

        self.handler.send_response.assert_awaited_once_with(
            self.message, "Oppdatert: Møte med Ola"
        )
        self.assertEqual(self.manager.get_upcoming("123")[0]["date"], target_date)

    async def test_handle_search_returns_calendar_matches(self):
        await self._add_item("Møte med Ola", _date(1), time="09:00")
        self.message.content = "@inebotten søk kalender møte"

        await self.handler.handle_search(self.message)

        self.handler.send_response.assert_awaited_once()
        self.assertIn("Møte med Ola", self.handler.send_response.await_args.args[1])

    async def test_handle_delete_extracts_title_after_calendar_context(self):
        await self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        self.message.content = "@inebotten kalender fjern meldekort"

        await self.handler.handle_delete(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Slettet", response)
        self.assertIn("Send inn meldekort", response)
        self.assertEqual(self.manager.get_upcoming("123"), [])

    async def test_handle_delete_bulk_title_with_calendar_suffix(self):
        await self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        await self._add_item("Rosenborg - Kristiansund", _date(2), time="09:00")
        await self._add_item("Send inn meldekort (Uke 27 - 28)", _date(3), time="12:00")
        self.message.content = '@inebotten Slett alle "Send inn meldekort" i kalenderen'

        await self.handler.handle_delete(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Slettet 2", response)
        remaining = self.manager.get_upcoming("123")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["title"], "Rosenborg - Kristiansund")

    async def test_handle_delete_ambiguous_title_shows_only_matching_choices(self):
        await self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        await self._add_item("Rosenborg - Kristiansund", _date(2), time="09:00")
        await self._add_item("Send inn meldekort (Uke 27 - 28)", _date(3), time="12:00")
        self.message.content = "@inebotten slett meldekort"

        await self.handler.handle_delete(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn('Fant 2 treff for "meldekort"', response)
        self.assertIn("Send inn meldekort (Uke 25 - 26)", response)
        self.assertIn("Send inn meldekort (Uke 27 - 28)", response)
        self.assertNotIn("Rosenborg - Kristiansund", response)
        self.assertEqual(len(self.manager.get_upcoming("123")), 3)

    async def test_handle_complete_ambiguous_title_prompts_without_mutating(self):
        await self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        await self._add_item("Send inn meldekort (Uke 27 - 28)", _date(3), time="12:00")
        self.message.content = "@inebotten ferdig meldekort"

        await self.handler.handle_complete(self.message)

        response = self.handler.send_response.await_args.args[1]
        self.assertIn('Fant 2 treff for "meldekort"', response)
        self.assertFalse(any(item.get("completed") for item in self.manager.get_upcoming("123")))

    async def test_handle_complete_title_with_number_does_not_use_number_as_index(self):
        await self._add_item("Send inn meldekort uke 25", _date(1), time="12:00")
        self.message.content = "@inebotten ferdig meldekort uke 25"

        await self.handler.handle_complete(self.message)

        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Fullført", response)
        self.assertEqual(self.manager.get_upcoming("123"), [])

    async def test_handle_complete_accepts_scoped_number_phrase(self):
        await self._add_item("Første", _date(1), time="12:00")
        await self._add_item("Andre", _date(2), time="12:00")
        self.message.content = "@inebotten ferdig nummer 2"

        await self.handler.handle_complete(self.message)

        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Andre", response)
        self.assertEqual([item["title"] for item in self.manager.get_upcoming("123")], ["Første"])

    async def test_handle_edit_ambiguous_title_prompts_without_mutating(self):
        await self._add_item("Møte med Ola", _date(1), time="09:00")
        await self._add_item("Møte med Kari", _date(2), time="09:00")
        self.message.content = f"@inebotten rediger møte dato: {_date(7)}"

        await self.handler.handle_edit(self.message)

        response = self.handler.send_response.await_args.args[1]
        self.assertIn('Fant 2 treff for "møte"', response)
        self.assertNotEqual(self.manager.get_upcoming("123")[0]["date"], _date(7))

    async def test_handle_edit_does_not_mutate_past_title_match(self):
        await self._add_item("Gammelt møte", _date(-3), time="09:00")
        self.message.content = f"@inebotten rediger møte dato: {_date(7)}"

        await self.handler.handle_edit(self.message)

        response = self.handler.send_response.await_args.args[1]
        self.assertIn("synlige kalenderlisten", response)
        self.assertEqual(self.manager.search_items("møte")[0]["date"], _date(-3))


class CalendarHandlerTemporalDefenseTests(unittest.IsolatedAsyncioTestCase):
    OSLO = ZoneInfo("Europe/Oslo")
    NOW = datetime(2026, 7, 14, 12, 0, tzinfo=OSLO)

    def setUp(self):
        self.gcal = SimpleNamespace(create_event=MagicMock(return_value={"id": "g-1"}))
        self.manager = SimpleNamespace(
            gcal_enabled=True,
            gcal=self.gcal,
            add_item_result=AsyncMock(
                return_value={
                    "id": "item-1",
                    "title": "Møte",
                    "date": "15.07.2026",
                    "time": "14:00",
                }
            ),
            format_single_item=MagicMock(return_value="Lagt til"),
            snapshot_pending_items=MagicMock(return_value=()),
            search_items=MagicMock(return_value=[]),
            edit_item_result=AsyncMock(
                return_value={"id": "item-1", "title": "Møte"}
            ),
        )
        self.loc = SimpleNamespace(
            t=lambda key, **kwargs: {
                "calendar_edit_invalid": "Ugyldig redigeringsformat",
                "calendar_edit_not_found": f"Fant ikke {kwargs.get('num')}",
                "calendar_edit_success": f"Oppdatert: {kwargs.get('title')}",
            }[key]
        )
        self.monitor = SimpleNamespace(
            calendar=self.manager,
            nlp_parser=SimpleNamespace(temporal_resolver=TemporalResolver()),
            rate_limiter=SimpleNamespace(),
            loc=self.loc,
            client=None,
            nlu_metrics=SimpleNamespace(
                record_legacy_payload_fallback=MagicMock()
            ),
        )
        self.message = SimpleNamespace(
            content="",
            guild=SimpleNamespace(id="123"),
            channel=SimpleNamespace(id="999"),
            author=SimpleNamespace(id="111", name="Alice"),
        )

    def _handler(self, **kwargs):
        handler = CalendarHandler(self.monitor, **kwargs)
        handler.send_response = AsyncMock()

        async def capture_send(message, text):
            await handler.send_response(message, text)
            return MessageSendResult(DeliveryState.DELIVERED)

        handler.send_response_result = AsyncMock(side_effect=capture_send)
        return handler

    def test_handler_reuses_parser_resolver_when_not_overridden(self):
        handler = self._handler(now_provider=lambda: self.NOW)
        self.assertIs(
            handler.temporal_resolver,
            self.monitor.nlp_parser.temporal_resolver,
        )

    async def test_invalid_create_makes_zero_manager_and_gcal_calls(self):
        handler = self._handler(now_provider=lambda: self.NOW)
        result = await handler.handle_calendar_item(
            self.message,
            {"title": "Møte", "date": "32.13.2026", "time": "14:00"},
        )
        self.assertFalse(result.ok)
        self.manager.add_item_result.assert_not_awaited()
        self.gcal.create_event.assert_not_called()

    async def test_valid_create_calls_manager_once_and_gcal_at_most_once(self):
        handler = self._handler(now_provider=lambda: self.NOW)
        result = await handler.handle_calendar_item(
            self.message,
            {"title": "Møte", "date": "15.7.2026", "time": "14"},
        )
        self.assertTrue(result.ok)
        self.manager.add_item_result.assert_awaited_once()
        self.assertEqual(self.gcal.create_event.call_count, 0)
        args = self.manager.add_item_result.await_args.args
        kwargs = self.manager.add_item_result.await_args.kwargs
        self.assertEqual((args[4], args[5]), ("15.07.2026", "14:00"))
        self.assertIs(kwargs["reference_time"], self.NOW)

    async def test_save_request_preserves_positional_api_and_returns_bool(self):
        handler = self._handler(now_provider=lambda: self.NOW)
        result = await handler.handle_save_request(
            self.message,
            " ring legen ",
            "15.07.2026",
            "14:00",
        )
        self.assertTrue(result.ok)

    async def test_omitted_handler_reference_reads_advancing_provider_once(self):
        calls = []

        def provider():
            calls.append(self.NOW + timedelta(days=len(calls)))
            return calls[-1]

        handler = self._handler(now_provider=provider)
        self.manager.gcal_enabled = False
        result = await handler.handle_calendar_item(
            self.message,
            {"title": "Møte", "date": "15.07.2026", "time": "14:00"},
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(calls), 1)

    async def test_explicit_reference_reads_provider_zero_times(self):
        calls = []
        handler = self._handler(now_provider=lambda: calls.append(True) or self.NOW)
        self.manager.gcal_enabled = False
        result = await handler.handle_calendar_item(
            self.message,
            {"title": "Møte", "date": "15.07.2026", "time": "14:00"},
            reference_time=self.NOW,
        )
        self.assertTrue(result.ok)
        self.assertEqual(calls, [])

    async def test_naive_reference_raises_before_reads_or_writes(self):
        calls = []
        handler = self._handler(now_provider=lambda: calls.append(True) or self.NOW)
        with self.assertRaisesRegex(ValueError, "calendar_reference_must_be_aware"):
            await handler.handle_calendar_item(
                self.message,
                {"title": "Møte", "date": "15.07.2026", "time": "14:00"},
                reference_time=datetime(2026, 7, 14, 12),
            )
        self.assertEqual(calls, [])
        self.manager.add_item_result.assert_not_awaited()
        self.gcal.create_event.assert_not_called()

    async def test_edit_invalid_date_scalar_stops_before_target_lookup(self):
        handler = self._handler(now_provider=lambda: self.NOW)
        self.message.content = "@inebotten endre 1 dato: 32.13.2026"
        result = await handler.handle_edit(self.message)
        self.assertFalse(result.ok)
        self.manager.snapshot_pending_items.assert_not_called()
        self.manager.edit_item_result.assert_not_awaited()

    async def test_time_edit_uses_validate_time_without_resolve_or_date_invention(self):
        resolver = TemporalResolver()
        resolver.validate_time = MagicMock(wraps=resolver.validate_time)
        resolver.resolve = MagicMock(side_effect=AssertionError("resolve must not run"))
        handler = self._handler(
            temporal_resolver=resolver,
            now_provider=lambda: self.NOW,
        )
        self.message.content = "@inebotten endre 1 tid: 25:61"
        result = await handler.handle_edit(self.message)
        self.assertFalse(result.ok)
        resolver.validate_time.assert_called_once_with("25:61")
        resolver.resolve.assert_not_called()
        self.manager.snapshot_pending_items.assert_not_called()

    async def test_index_edit_reads_bounded_target_then_performs_one_edit(self):
        self.manager.snapshot_pending_items.return_value = (
            {"id": "item-1", "title": "Møte", "date": "15.07.2026", "time": "09:00"}
        ,)
        handler = self._handler(now_provider=lambda: self.NOW)
        self.message.content = "@inebotten endre 1 tid: 14"
        result = await handler.handle_edit(self.message)
        self.assertTrue(result.ok)
        self.manager.snapshot_pending_items.assert_called_once_with(reference_time=self.NOW)
        self.manager.edit_item_result.assert_awaited_once_with(
            item_id="item-1", reference_time=self.NOW, time="14:00"
        )

    async def test_title_edit_reads_only_visible_target_then_performs_one_edit(self):
        self.manager.snapshot_pending_items.return_value = (
            {"id": "item-1", "title": "Møte med Ola", "date": "15.07.2026", "time": "09:00"}
        ,)
        handler = self._handler(now_provider=lambda: self.NOW)
        self.message.content = "@inebotten rediger møte med ola tid: 14"
        result = await handler.handle_edit(self.message)
        self.assertTrue(result.ok)
        self.manager.snapshot_pending_items.assert_called_once_with(reference_time=self.NOW)
        self.manager.edit_item_result.assert_awaited_once_with(
            item_id="item-1", reference_time=self.NOW, time="14:00"
        )

    async def test_date_edit_rejects_gap_or_fold_from_unchanged_time(self):
        for date_value in ("29.03.2026", "25.10.2026"):
            with self.subTest(date_value=date_value):
                self.manager.snapshot_pending_items.reset_mock()
                self.manager.edit_item_result.reset_mock()
                self.manager.snapshot_pending_items.return_value = (
                    {"id": "item-1", "title": "Møte", "date": "28.03.2026", "time": "02:30"}
                ,)
                handler = self._handler(now_provider=lambda: self.NOW)
                self.message.content = f"@inebotten endre 1 dato: {date_value}"
                result = await handler.handle_edit(self.message)
                self.assertFalse(result.ok)
                self.manager.edit_item_result.assert_not_awaited()

    async def test_time_edit_rejects_gap_or_fold_from_unchanged_date(self):
        for date_value in ("29.03.2026", "25.10.2026"):
            with self.subTest(date_value=date_value):
                self.manager.snapshot_pending_items.reset_mock()
                self.manager.edit_item_result.reset_mock()
                self.manager.snapshot_pending_items.return_value = (
                    {"id": "item-1", "title": "Møte", "date": date_value, "time": "01:30"}
                ,)
                handler = self._handler(now_provider=lambda: self.NOW)
                self.message.content = "@inebotten endre 1 tid: 02:30"
                result = await handler.handle_edit(self.message)
                self.assertFalse(result.ok)
                self.manager.edit_item_result.assert_not_awaited()

    async def test_missing_effective_date_makes_zero_edit_calls(self):
        self.manager.snapshot_pending_items.return_value = (
            {"id": "item-1", "title": "Møte", "date": None, "time": "09:00"}
        ,)
        handler = self._handler(now_provider=lambda: self.NOW)
        self.message.content = "@inebotten endre 1 tid: 14"
        result = await handler.handle_edit(self.message)
        self.assertFalse(result.ok)
        self.manager.edit_item_result.assert_not_awaited()

    def test_handler_has_no_direct_gcal_mutation_adapter(self):
        handler = self._handler(now_provider=lambda: self.NOW)
        self.assertFalse(hasattr(handler, "_sync_to_gcal"))


if __name__ == "__main__":
    unittest.main()
