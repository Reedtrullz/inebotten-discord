import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from core.intent_router import BotIntent, IntentRouter
from features.quote_handler import QuoteHandler
from features.quote_manager import QuoteManager


class QuoteManagerCrudTests(unittest.TestCase):
    def make_manager(self) -> QuoteManager:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return QuoteManager(storage_path=Path(tmp.name) / "quotes.json")

    def test_list_quotes_returns_all_quotes(self):
        manager = self.make_manager()
        manager.add_quote("123", "Første", "Ola")
        manager.add_quote("123", "Andre", "Kari")

        quotes = manager.list_quotes("123")

        self.assertEqual(len(quotes), 2)
        self.assertEqual([q["text"] for q in quotes], ["Første", "Andre"])

    def test_list_quotes_empty_when_no_quotes(self):
        self.assertEqual(self.make_manager().list_quotes("123"), [])

    def test_update_quote_updates_text(self):
        manager = self.make_manager()
        manager.add_quote("123", "Gamle", "Ola")

        self.assertTrue(manager.update_quote("123", 1, text="Nye"))
        self.assertEqual(manager.list_quotes("123")[0]["text"], "Nye")

    def test_update_quote_updates_author(self):
        manager = self.make_manager()
        manager.add_quote("123", "Tekst", "Ola")

        self.assertTrue(manager.update_quote("123", 1, author="Kari"))
        self.assertEqual(manager.list_quotes("123")[0]["author"], "Kari")

    def test_update_quote_invalid_index_raises_value_error(self):
        manager = self.make_manager()
        manager.add_quote("123", "Tekst", "Ola")

        with self.assertRaises(ValueError):
            manager.update_quote("123", 2, text="Nye")

    def test_delete_quote_removes_quote(self):
        manager = self.make_manager()
        manager.add_quote("123", "Første", "Ola")
        manager.add_quote("123", "Andre", "Kari")

        self.assertTrue(manager.delete_quote("123", 1))
        self.assertEqual([q["text"] for q in manager.list_quotes("123")], ["Andre"])

    def test_delete_quote_invalid_index_raises_value_error(self):
        manager = self.make_manager()
        manager.add_quote("123", "Tekst", "Ola")

        with self.assertRaises(ValueError):
            manager.delete_quote("123", 2)


class DummyQuoteMonitor:
    def __init__(self, quote_manager: QuoteManager):
        self.quote = quote_manager
        self.rate_limiter = SimpleNamespace(
            record_sent=lambda: None,
            record_failure=lambda **kwargs: None,
            can_send=lambda: (True, None),
            wait_if_needed=lambda: True,
        )
        self.loc = SimpleNamespace(
            t=lambda key, **kwargs: key if not kwargs else f"{key}:{kwargs}"
        )
        self.client = None
        self.countdown = SimpleNamespace(parse_countdown_query=lambda content: None)
        self.poll = SimpleNamespace(get_active_polls=lambda guild_id: [])
        self.conversation = SimpleNamespace(
            should_show_dashboard=lambda content, guild_id: (False, "default"),
            threads={},
        )
        self.nlp_parser = SimpleNamespace(
            parse_task_with_recurrence=lambda content: None,
            parse_event=lambda content: None,
        )
        self.parse_poll_command = lambda content: None
        self.parse_vote = lambda content: None
        self.parse_watchlist_command = lambda content: None
        self.parse_quote_command = lambda content: None
        self.parse_price_command = lambda content: None
        self.parse_horoscope_command = lambda content: None
        self.parse_compliment_command = lambda content: None
        self.parse_calculator_command = lambda content: None
        self.parse_shorten_command = lambda content: None
        self.detect_search_intent = lambda content: None


class QuoteRoutingAndHandlerTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self) -> QuoteManager:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return QuoteManager(storage_path=Path(tmp.name) / "quotes.json")

    def _router(self):
        monitor = DummyQuoteMonitor(self.make_manager())
        return IntentRouter(monitor)

    def test_quote_list_routes_to_quote_list(self):
        result = self._router().route("liste sitater", guild_id=123)
        self.assertEqual(result.intent, BotIntent.QUOTE_LIST)

    def test_quote_edit_routes_to_quote_edit(self):
        result = self._router().route("endre sitat", guild_id=123)
        self.assertEqual(result.intent, BotIntent.QUOTE_EDIT)

    async def test_handler_list_quotes_outputs_numbered_quotes(self):
        manager = self.make_manager()
        manager.add_quote("123", "Første", "Ola")
        manager.add_quote("123", "Andre", "Kari")
        handler = QuoteHandler(DummyQuoteMonitor(manager))

        captured = {}

        async def reply(content, mention_author=False):
            captured["content"] = content
            captured["mention_author"] = mention_author

        message = SimpleNamespace(
            content="liste sitater",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            reply=reply,
        )

        await handler.handle_quote_list(message)

        self.assertIn("quote_list_title", captured["content"])
        self.assertIn('1. "Første" — Ola', captured["content"])
        self.assertIn('2. "Andre" — Kari', captured["content"])

    async def test_handler_edit_quotes_parses_text_and_author_from_content(self):
        manager = self.make_manager()
        manager.add_quote("123", "Gammel", "Ola")
        handler = QuoteHandler(DummyQuoteMonitor(manager))

        captured = {}

        async def reply(content, mention_author=False):
            captured["content"] = content
            captured["mention_author"] = mention_author

        message = SimpleNamespace(
            content="@inebotten endre sitat 1 tekst: Ny tekst forfatter: Kari",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            reply=reply,
        )

        await handler.handle_quote_edit(message, {})

        updated = manager.list_quotes("123")[0]
        self.assertEqual(updated["text"], "Ny tekst")
        self.assertEqual(updated["author"], "Kari")
        self.assertEqual(captured["content"], "quote_edit_success")

    async def test_handler_edit_quotes_rejects_missing_fields(self):
        manager = self.make_manager()
        manager.add_quote("123", "Gammel", "Ola")
        handler = QuoteHandler(DummyQuoteMonitor(manager))

        captured = {}

        async def reply(content, mention_author=False):
            captured["content"] = content
            captured["mention_author"] = mention_author

        message = SimpleNamespace(
            content="@inebotten endre sitat 1",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            reply=reply,
        )

        await handler.handle_quote_edit(message, {})

        self.assertEqual(captured["content"], "calendar_edit_invalid")
        self.assertEqual(manager.list_quotes("123")[0]["text"], "Gammel")

    async def test_handler_edit_quotes_parses_author_when_text_is_empty(self):
        manager = self.make_manager()
        manager.add_quote("123", "Gammel", "Ola")
        handler = QuoteHandler(DummyQuoteMonitor(manager))

        captured = {}

        async def reply(content, mention_author=False):
            captured["content"] = content
            captured["mention_author"] = mention_author

        message = SimpleNamespace(
            content="@inebotten endre sitat 1 tekst: forfatter: Kari",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            reply=reply,
        )

        await handler.handle_quote_edit(message, {})

        updated = manager.list_quotes("123")[0]
        self.assertEqual(updated["text"], "Gammel")
        self.assertEqual(updated["author"], "Kari")
        self.assertEqual(captured["content"], "quote_edit_success")

    async def test_handler_edit_quotes_parses_text_when_author_is_empty(self):
        manager = self.make_manager()
        manager.add_quote("123", "Gammel", "Ola")
        handler = QuoteHandler(DummyQuoteMonitor(manager))

        captured = {}

        async def reply(content, mention_author=False):
            captured["content"] = content
            captured["mention_author"] = mention_author

        message = SimpleNamespace(
            content="@inebotten endre sitat 1 forfatter: tekst: Ny tekst",
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=456),
            reply=reply,
        )

        await handler.handle_quote_edit(message, {})

        updated = manager.list_quotes("123")[0]
        self.assertEqual(updated["text"], "Ny tekst")
        self.assertEqual(updated["author"], "Ola")
        self.assertEqual(captured["content"], "quote_edit_success")


if __name__ == "__main__":
    unittest.main()
