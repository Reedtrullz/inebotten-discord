#!/usr/bin/env python3
"""Regression tests for the stabilization and hardening pass."""

from __future__ import annotations

import importlib
import asyncio
import http.client
import io
import os
import time
import unittest
import threading
import importlib.util
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cal_system.calendar_manager import CalendarManager
from cal_system.event_manager import EventManager
from cal_system.reminder_checker import ReminderChecker
from cal_system.reminder_manager import ReminderManager
from features.birthday_manager import BirthdayManager
from features.crypto_manager import CryptoManager
from features.poll_manager import PollManager
from features.quote_manager import QuoteManager
from utils.json_storage import hermes_discord_data_path, read_json, write_json_atomic
from utils.sanitizer import sanitize_discord_mention, sanitize_html


class CalendarHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.manager = CalendarManager(storage_path=Path(self.tmp.name) / "calendar.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_normalizes_slash_date(self):
        self.manager.add_item("123", "1", "Alice", "Møte", "05.05.2027")

        updated = self.manager.edit_item(1, date="5/6/2027")

        self.assertEqual(updated["date"], "05.06.2027")

    def test_edit_by_id_can_update_past_search_match(self):
        item = self.manager.add_item("123", "1", "Alice", "Gammelt møte", "01.01.2024")

        updated = self.manager.edit_item_by_id(item["id"], date="6.6.2027")

        self.assertEqual(updated["date"], "06.06.2027")
        self.assertEqual(self.manager.search_items("gammelt")[0]["date"], "06.06.2027")


class BirthdayHardeningTests(unittest.TestCase):
    def test_birthday_sync_passes_yearly_recurrence(self):
        class FakeGCal:
            def __init__(self):
                self.calls = []

            def is_configured(self):
                return True

            def create_event(self, **kwargs):
                self.calls.append(kwargs)
                return {"id": "gcal-1", "htmlLink": "https://calendar.example/event"}

        with TemporaryDirectory() as tmp:
            manager = BirthdayManager(storage_path=Path(tmp) / "birthdays.json")
            fake_gcal = FakeGCal()
            manager.gcal = fake_gcal
            manager.gcal_enabled = True

            self.assertTrue(manager.add_birthday("123", "1", "Ola", 15, 5, 1990))

            self.assertEqual(fake_gcal.calls[0]["recurrence"], "yearly")
            self.assertEqual(manager.birthdays["123"]["1"]["gcal_event_id"], "gcal-1")

    def test_edit_birthday_resyncs_google_calendar_event(self):
        class FakeGCal:
            def __init__(self):
                self.created = []
                self.deleted = []

            def is_configured(self):
                return True

            def create_event(self, **kwargs):
                self.created.append(kwargs)
                return {"id": f"gcal-{len(self.created)}", "htmlLink": "https://calendar.example/event"}

            def delete_event(self, event_id):
                self.deleted.append(event_id)
                return True

        with TemporaryDirectory() as tmp:
            manager = BirthdayManager(storage_path=Path(tmp) / "birthdays.json")
            fake_gcal = FakeGCal()
            manager.gcal = fake_gcal
            manager.gcal_enabled = True

            manager.add_birthday("123", "1", "Ola", 15, 5, 1990)
            updated = manager.edit_birthday("123", "Ola", 16, 6, 1990)

            self.assertEqual(fake_gcal.deleted, ["gcal-1"])
            self.assertEqual(fake_gcal.created[-1]["recurrence"], "yearly")
            self.assertEqual(updated["gcal_event_id"], "gcal-2")
            self.assertEqual(updated["day"], 16)


class ReminderHardeningTests(unittest.TestCase):
    def test_stale_sent_log_allows_realert(self):
        checker = ReminderChecker(storage_path=Path("/tmp/nonexistent-reminder-log.json"))
        checker.sent_log = {
            "reminders_sent": {"item-1:now": int(time.time()) - 3700},
            "digest_log": {},
        }

        self.assertFalse(checker._has_been_sent("item-1", "now"))

    def test_recent_sent_log_still_suppresses(self):
        checker = ReminderChecker(storage_path=Path("/tmp/nonexistent-reminder-log.json"))
        checker.sent_log = {
            "reminders_sent": {"item-1:now": int(time.time())},
            "digest_log": {},
        }

        self.assertTrue(checker._has_been_sent("item-1", "now"))


class IdAndPersistenceHardeningTests(unittest.TestCase):
    def test_reminder_poll_and_event_ids_do_not_collide(self):
        with TemporaryDirectory() as tmp:
            reminder = ReminderManager(storage_path=Path(tmp) / "reminders.json")
            first_reminder = reminder.add_reminder("123", "1", "Alice", "En")
            second_reminder = reminder.add_reminder("123", "1", "Alice", "To")

            poll = PollManager(storage_path=Path(tmp) / "polls.json")
            first_poll = poll.create_poll("123", "En?", ["Ja", "Nei"], "Alice")
            second_poll = poll.create_poll("123", "To?", ["Ja", "Nei"], "Alice")

            event = EventManager(storage_path=Path(tmp) / "events.json")
            first_event = event.create_event("123", "En", "01.01.2027")
            second_event = event.create_event("123", "To", "02.01.2027")

            self.assertNotEqual(first_reminder, second_reminder)
            self.assertNotEqual(first_poll["id"], second_poll["id"])
            self.assertNotEqual(first_event["id"], second_event["id"])

    def test_write_json_atomic_round_trips(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            write_json_atomic(path, {"ok": True})

            self.assertEqual(read_json(path, {}), {"ok": True})
            self.assertFalse((Path(tmp) / ".data.json.tmp").exists())

    def test_default_data_path_migrates_legacy_file(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            legacy_dir = home / ".hermes" / "discord"
            legacy_dir.mkdir(parents=True)
            legacy = legacy_dir / "polls.json"
            legacy.write_text('{"legacy": true}', encoding="utf-8")

            with patch.object(Path, "home", return_value=home):
                path = hermes_discord_data_path("polls.json")

            self.assertEqual(path, home / ".hermes" / "discord" / "data" / "polls.json")
            self.assertTrue(path.exists())
            self.assertFalse(legacy.exists())

    def test_generated_console_api_key_is_persisted_and_reused(self):
        from core.config import Config

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.object(Path, "home", return_value=home):
                with patch.dict(os.environ, {"DISCORD_USER_TOKEN": "token"}, clear=True):
                    first = Config()
                    second = Config()

            key_path = home / ".hermes" / "discord" / "data" / "console" / "api_key.txt"
            self.assertTrue(key_path.exists())
            self.assertEqual(first.CONSOLE_API_KEY, key_path.read_text(encoding="utf-8").strip())
            self.assertEqual(second.CONSOLE_API_KEY, first.CONSOLE_API_KEY)

    def test_generated_console_api_key_is_not_logged(self):
        from core.config import Config

        generated_key = "super-secret-console-key"
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            stdout = io.StringIO()
            with patch.object(Path, "home", return_value=home):
                with patch.object(Config, "load_env", lambda self: setattr(self, "env_file_loaded", None)):
                    with patch.dict(os.environ, {"DISCORD_USER_TOKEN": "token"}, clear=True):
                        with patch("core.config.secrets.token_urlsafe", return_value=generated_key):
                            with redirect_stdout(stdout):
                                config = Config()

        output = stdout.getvalue()
        self.assertEqual(config.CONSOLE_API_KEY, generated_key)
        self.assertNotIn(generated_key, output)
        self.assertIn("Console API key generated and stored", output)
        self.assertIn("Console API key file:", output)


class SanitizerHardeningTests(unittest.TestCase):
    def test_discord_mentions_are_removed(self):
        self.assertEqual(sanitize_discord_mention("hei <@123> og <@!456>"), "hei  og ")

    def test_html_is_escaped(self):
        self.assertEqual(
            sanitize_html('<script>alert("x")</script>'),
            '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;',
        )


class PriceHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_stock_price_returns_unsupported_instead_of_simulated_data(self):
        manager = CryptoManager()
        query = manager.parse_price_query("aapl pris")

        data = await manager.get_price(query)
        response = manager.format_price(data, lang="no")

        self.assertEqual(data["type"], "unsupported_stock")
        self.assertIn("ikke koblet til en live datakilde", response)
        self.assertNotIn("Pris:", response)


class QuoteScopeHardeningTests(unittest.TestCase):
    def test_scoped_random_quote_does_not_fallback_to_other_guild(self):
        with TemporaryDirectory() as tmp:
            manager = QuoteManager(storage_path=Path(tmp) / "quotes.json")
            manager.add_quote("guild-a", "Privat", "Ola")

            self.assertIsNone(manager.get_random_quote("guild-b"))
            self.assertEqual(manager.get_random_quote()["text"], "Privat")

    def test_scoped_author_lookup_does_not_fallback_to_other_guild(self):
        with TemporaryDirectory() as tmp:
            manager = QuoteManager(storage_path=Path(tmp) / "quotes.json")
            manager.add_quote("guild-a", "Privat", "Ola")

            self.assertIsNone(manager.get_quote_by_author("guild-b", "Ola"))
            self.assertEqual(manager.get_quote_by_author(None, "Ola")["text"], "Privat")


class BridgeConfigHardeningTests(unittest.IsolatedAsyncioTestCase):
    def test_lm_studio_env_overrides_are_used(self):
        with patch.dict(
            os.environ,
            {
                "LM_STUDIO_URL": "http://localhost:9999/v1/",
                "LM_STUDIO_MODEL": "qwen-test",
                "OPENROUTER_MODEL": "should-not-be-used",
            },
            clear=False,
        ):
            import ai.hermes_bridge_server as bridge

            bridge = importlib.reload(bridge)
            self.assertEqual(bridge.LM_STUDIO_URL, "http://localhost:9999/v1")
            self.assertEqual(bridge.LM_STUDIO_MODEL, "qwen-test")

    async def test_bridge_rejects_oversized_post_body_before_reading(self):
        import ai.hermes_bridge_server as bridge

        server_obj = bridge.HermesBridgeServer()
        server = await asyncio.start_server(server_obj.handle_request, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            request = (
                "POST /api/chat HTTP/1.1\r\n"
                "Host: localhost\r\n"
                f"Content-Length: {bridge.MAX_BODY_BYTES + 1}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            writer.write(request)
            await writer.drain()
            response = await reader.read(4096)
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

        self.assertIn(b"413", response)


class WebhookHardeningTests(unittest.TestCase):
    def test_webhook_rejects_oversized_body(self):
        module_path = Path(__file__).resolve().parents[1] / "scripts" / "deploy" / "inebotten-webhook.py"
        spec = importlib.util.spec_from_file_location("inebotten_webhook_test", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/github-webhook",
                body=b"",
                headers={"Content-Length": str(module.MAX_WEBHOOK_BODY_BYTES + 1)},
            )
            response = conn.getresponse()
            body = response.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(response.status, 413)
        self.assertIn(b"payload too large", body)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
