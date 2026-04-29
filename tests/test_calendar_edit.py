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
        self.message.content = "@inebotten rediger møte med ola dato: 05.05.2026"

        await self.handler.handle_edit(self.message)

        self.handler.send_response.assert_awaited_once_with(
            self.message, "Oppdatert: Møte med Ola"
        )
        self.assertEqual(self.manager.get_upcoming("123")[0]["date"], "05.05.2026")


if __name__ == "__main__":
    unittest.main()
