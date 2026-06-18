# pyright: reportImplicitOverride=false, reportUnannotatedClassAttribute=false, reportUninitializedInstanceVariable=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownLambdaType=false, reportUnusedCallResult=false, reportAttributeAccessIssue=false

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cal_system.calendar_manager import CalendarManager
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
            nlp_parser=SimpleNamespace(parse_event=AsyncMock(return_value=None)),
            rate_limiter=SimpleNamespace(
                record_sent=lambda: None,
                record_failure=lambda **kwargs: None,
                can_send=lambda: (True, None),
                wait_if_needed=AsyncMock(return_value=True),
            ),
            loc=self.loc,
            client=None,
        )
        self.handler = CalendarHandler(self.monitor)
        self.handler.send_response = AsyncMock()

        self.message = SimpleNamespace(
            content="",
            guild=SimpleNamespace(id="123"),
            channel=SimpleNamespace(id="999"),
            author=SimpleNamespace(id="111", name="Alice"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _add_item(self, title: str, date: str, time: str = "09:00"):
        return self.manager.add_item(
            guild_id="123",
            user_id="111",
            username="Alice",
            title=title,
            date_str=date,
            time_str=time,
        )

    async def test_handle_clear_requires_explicit_confirmation(self):
        self._add_item("Møte", _date(1))
        self.message.content = "@inebotten tøm kalender"

        await self.handler.handle_clear(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("bekreft 1", response)
        self.assertEqual(len(self.manager.items[self.manager.SHARED_KEY]), 1)

    async def test_handle_clear_confirmed_deletes_calendar(self):
        self._add_item("Møte", _date(1))
        self.message.content = "@inebotten tøm kalender bekreft 1"

        await self.handler.handle_clear(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Slettet 1", response)
        self.assertEqual(self.manager.items[self.manager.SHARED_KEY], [])

    async def test_handle_clear_rejects_stale_confirmation_count(self):
        self._add_item("Møte", _date(1))
        self._add_item("Trening", _date(2))
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

            def delete_event(self, event_id):
                self.delete_calls.append(event_id)
                return False

        gcal = FailingDeleteGCal()
        manager = CalendarManager(storage_path=Path(self.tmp.name) / "gcal-calendar.json", gcal_manager=gcal)
        manager.add_item(
            guild_id="123",
            user_id="111",
            username="Alice",
            title="GCal møte",
            date_str=_date(1),
            time_str="09:00",
            gcal_event_id="gcal-1",
        )

        result = await manager.clear_calendar("123")

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

            def delete_event(self, event_id):
                self.delete_calls.append(event_id)
                return True

        gcal = SuccessfulDeleteGCal()
        manager = CalendarManager(storage_path=Path(self.tmp.name) / "gcal-calendar.json", gcal_manager=gcal)
        manager.add_item(
            guild_id="123",
            user_id="111",
            username="Alice",
            title="GCal møte",
            date_str=_date(1),
            time_str="09:00",
            gcal_event_id="gcal-1",
        )

        result = await manager.clear_calendar("123")

        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(gcal.delete_calls, ["gcal-1"])
        self.assertEqual(manager.items[manager.SHARED_KEY], [])

    async def test_handle_edit_integration_parse_and_execute_edit(self):
        self._add_item("Møte", _date(1), time="09:00")
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
        self._add_item("Møte med Ola", _date(1), time="09:00")
        target_date = _date(7)
        self.message.content = f"@inebotten rediger møte med ola dato: {target_date}"

        await self.handler.handle_edit(self.message)

        self.handler.send_response.assert_awaited_once_with(
            self.message, "Oppdatert: Møte med Ola"
        )
        self.assertEqual(self.manager.get_upcoming("123")[0]["date"], target_date)

    async def test_handle_search_returns_calendar_matches(self):
        self._add_item("Møte med Ola", _date(1), time="09:00")
        self.message.content = "@inebotten søk møte"

        await self.handler.handle_search(self.message)

        self.handler.send_response.assert_awaited_once()
        self.assertIn("Møte med Ola", self.handler.send_response.await_args.args[1])

    async def test_handle_delete_extracts_title_after_calendar_context(self):
        self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        self.message.content = "@inebotten kalender fjern meldekort"

        await self.handler.handle_delete(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Slettet", response)
        self.assertIn("Send inn meldekort", response)
        self.assertEqual(self.manager.get_upcoming("123"), [])

    async def test_handle_delete_bulk_title_with_calendar_suffix(self):
        self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        self._add_item("Rosenborg - Kristiansund", _date(2), time="09:00")
        self._add_item("Send inn meldekort (Uke 27 - 28)", _date(3), time="12:00")
        self.message.content = '@inebotten Slett alle "Send inn meldekort" i kalenderen'

        await self.handler.handle_delete(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn("Slettet 2", response)
        remaining = self.manager.get_upcoming("123")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["title"], "Rosenborg - Kristiansund")

    async def test_handle_delete_ambiguous_title_shows_only_matching_choices(self):
        self._add_item("Send inn meldekort (Uke 25 - 26)", _date(1), time="12:00")
        self._add_item("Rosenborg - Kristiansund", _date(2), time="09:00")
        self._add_item("Send inn meldekort (Uke 27 - 28)", _date(3), time="12:00")
        self.message.content = "@inebotten slett meldekort"

        await self.handler.handle_delete(self.message)

        self.handler.send_response.assert_awaited_once()
        response = self.handler.send_response.await_args.args[1]
        self.assertIn('Fant 2 treff for "meldekort"', response)
        self.assertIn("Send inn meldekort (Uke 25 - 26)", response)
        self.assertIn("Send inn meldekort (Uke 27 - 28)", response)
        self.assertIn("slett alle meldekort", response)
        self.assertNotIn("Rosenborg - Kristiansund", response)
        self.assertEqual(len(self.manager.get_upcoming("123")), 3)


if __name__ == "__main__":
    unittest.main()
