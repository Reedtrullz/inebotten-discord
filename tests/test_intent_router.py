#!/usr/bin/env python3
"""Regression tests for central intent routing."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

from cal_system.natural_language_parser import NaturalLanguageParser
from core.intent_router import BotIntent, IntentRouter
from features.crypto_manager import parse_price_command
from features.search_manager import detect_search_intent


class DummyMonitor:
    def __init__(self, active_polls=False):
        self.nlp_parser = NaturalLanguageParser()
        self.countdown = SimpleNamespace(parse_countdown_query=self._parse_countdown)
        self.poll = SimpleNamespace(
            get_active_polls=lambda guild_id: [{"id": "poll1"}] if active_polls else []
        )
        self.conversation = SimpleNamespace(
            should_show_dashboard=self._should_show_dashboard,
            threads={},
        )
        self.detect_search_intent = self._detect_search_intent

        self.parse_poll_command = self._parse_poll
        self.parse_vote = self._parse_vote
        self.parse_watchlist_command = self._parse_watchlist
        self.parse_quote_command = self._parse_quote
        self.parse_price_command = self._parse_price
        self.parse_horoscope_command = self._parse_horoscope
        self.parse_compliment_command = self._parse_compliment
        self.parse_calculator_command = self._parse_calculator
        self.parse_shorten_command = self._parse_shorten

    def _parse_countdown(self, content):
        return {"event": "jul"} if "hvor lenge til jul" in content.lower() else None

    def _parse_poll(self, content):
        return {"question": "pizza?", "options": ["Ja", "Nei"]} if "avstemning" in content.lower() else None

    def _parse_vote(self, content):
        return int(content) if content.strip().isdigit() else None

    def _parse_watchlist(self, content):
        lower = content.lower()
        if "fjern watchlist" in lower or "slett watchlist" in lower or "fjern fra watchlist" in lower:
            return {"action": "remove"}
        if "endre watchlist" in lower or "rediger watchlist" in lower:
            return {"action": "edit"}
        return {"action": "suggest"} if "hva skal vi se" in lower else None

    def _parse_quote(self, content):
        return {"action": "get"} if "sitat" in content.lower() else None

    def _parse_price(self, content):
        return {"type": "crypto", "asset": "bitcoin"} if "bitcoin" in content.lower() and "koster" in content.lower() else None

    def _parse_horoscope(self, content):
        return {"sign": "væren"} if "horoskop" in content.lower() else None

    def _parse_compliment(self, content):
        return {"action": "compliment"} if "kompliment" in content.lower() else None

    def _parse_calculator(self, content):
        return {"type": "math", "expression": "2+2"} if "2+2" in content else None

    def _parse_shorten(self, content):
        return {"url": "https://example.com"} if "forkort" in content.lower() else None

    def _detect_search_intent(self, content):
        lower = content.lower()
        if "hva skjer i trondheim" in lower:
            return {"query": "Trondheim i helga", "type": "web"}
        if lower.strip() in {"hva skjer?", "hva skjer"}:
            return {"query": "hva skjer", "type": "web"}
        return None

    def _should_show_dashboard(self, content, guild_id):
        if "vis dashboard" in content.lower():
            return True, "explicit_request"
        return False, "default"


class IntentRouterTests(unittest.TestCase):
    def route(self, text, active_polls=False, monitor=None):
        monitor = monitor or DummyMonitor(active_polls=active_polls)
        return IntentRouter(monitor).route(text, guild_id=123)

    def test_conversational_future_prompt_stays_ai_chat(self):
        result = self.route("jeg skal bare høre hva du synes om RBK i morgen")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_calendar_task_prompt_routes_to_calendar_item(self):
        result = self.route("husk å kjøpe melk på mandag")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
        self.assertEqual(result.payload["calendar_item"]["type"], "task")

    def test_calendar_event_prompt_routes_with_time(self):
        result = self.route("møte med Ola i morgen kl 14")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
        self.assertEqual(result.payload["calendar_item"]["time"], "14:00")

    def test_english_pm_time_routes_with_time(self):
        result = self.route("meeting tomorrow at 3pm")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
        self.assertEqual(result.payload["calendar_item"]["time"], "15:00")
        self.assertEqual(result.payload["calendar_item"]["title"], "Meeting")

    def test_contextual_reminder_followup_uses_recent_offer(self):
        monitor = DummyMonitor()
        monitor.conversation.threads[123] = [
            {
                "user_id": None,
                "username": "Inebotten",
                "content": "Skal jeg hjelpe deg med å legge inn en påminnelse om å bestille billettene, eller kanskje du vil planlegge turen?",
                "is_bot": True,
                "timestamp": datetime.now(),
            }
        ]

        result = self.route("minn meg på det imorgen kveld :Pog:", monitor=monitor)

        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)
        self.assertEqual(result.payload["calendar_item"]["type"], "task")
        self.assertEqual(result.payload["calendar_item"]["title"], "Bestille billettene")
        self.assertEqual(result.payload["calendar_item"]["time"], "19:00")

    def test_vague_hva_skjer_stays_ai_chat(self):
        result = self.route("hva skjer?")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_contextual_hva_skjer_routes_to_search(self):
        result = self.route("hva skjer i Trondheim i helga?")
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_travel_cost_question_routes_to_search_not_crypto(self):
        monitor = DummyMonitor()
        monitor.parse_price_command = cast(Any, parse_price_command)
        monitor.detect_search_intent = detect_search_intent

        result = self.route(
            "hva koster det å fly fra trondheim til panama?",
            monitor=monitor,
        )

        self.assertIsNone(parse_price_command("hva koster det å fly fra trondheim til panama?"))
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_active_poll_gates_numeric_vote(self):
        self.assertEqual(self.route("1", active_polls=False).intent, BotIntent.AI_CHAT)
        self.assertEqual(self.route("1", active_polls=True).intent, BotIntent.POLL_VOTE)

    def test_poll_list_routes_when_active_polls_exist(self):
        result = self.route("polls", active_polls=True)
        self.assertEqual(result.intent, BotIntent.POLL_LIST)
        self.assertEqual(result.confidence, 0.95)

    def test_poll_list_falls_through_when_no_active_polls(self):
        result = self.route("polls", active_polls=False)
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_prompt_priority_examples(self):
        examples = {
            "status": BotIntent.STATUS,
            "hjelp": BotIntent.HELP,
            "bot status": BotIntent.STATUS,
            "status dnd": BotIntent.PROFILE,
            "status online": BotIntent.PROFILE,
            "kalender": BotIntent.CALENDAR_LIST,
            "hvor lenge til jul": BotIntent.COUNTDOWN,
            "hva skal vi se": BotIntent.WATCHLIST,
            "sitat": BotIntent.QUOTE,
            "hvor mye koster bitcoin": BotIntent.PRICE,
            "hva er 2+2": BotIntent.CALCULATOR,
            "vis dashboard": BotIntent.DASHBOARD,
        }
        for prompt, expected in examples.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(self.route(prompt).intent, expected)

    def test_status_command_priority_keeps_health_over_profile(self):
        self.assertEqual(self.route("status").intent, BotIntent.STATUS)
        self.assertEqual(self.route("bot status").intent, BotIntent.STATUS)

    def test_status_alone_does_not_trigger_profile(self):
        result = self.route("status")
        self.assertEqual(result.intent, BotIntent.STATUS)
        self.assertNotEqual(result.intent, BotIntent.PROFILE)

    def test_presence_status_requires_discord_status_word(self):
        self.assertEqual(self.route("status dnd").intent, BotIntent.PROFILE)
        self.assertEqual(self.route("status invisible").intent, BotIntent.PROFILE)
        self.assertEqual(self.route("status").intent, BotIntent.STATUS)

    def test_calendar_oppdater_routes_to_edit_not_sync(self):
        result = self.route("kalender oppdater")
        self.assertEqual(result.intent, BotIntent.CALENDAR_EDIT)
        self.assertEqual(result.reason, "calendar_edit_keyword")

    def test_calendar_oppdater_fra_google_routes_to_sync(self):
        result = self.route("kalender oppdater fra google")
        self.assertEqual(result.intent, BotIntent.CALENDAR_SYNC)
        self.assertEqual(result.reason, "calendar_sync_keyword")

    def test_calendar_synkroniser_routes_to_sync(self):
        result = self.route("kalender synkroniser")
        self.assertEqual(result.intent, BotIntent.CALENDAR_SYNC)
        self.assertEqual(result.reason, "calendar_sync_keyword")

    def test_calendar_clear_phrases_win_over_delete(self):
        self.assertEqual(self.route("kalender slett alt").intent, BotIntent.CALENDAR_CLEAR)
        self.assertEqual(self.route("kalender fjern alt").intent, BotIntent.CALENDAR_CLEAR)

    def test_calendar_delete_still_handles_item_deletion(self):
        self.assertEqual(self.route("kalender slett 2").intent, BotIntent.CALENDAR_DELETE)

    def test_reminder_edit_routes_to_reminder_edit(self):
        result = self.route("endre påminnelse")
        self.assertEqual(result.intent, BotIntent.REMINDER_EDIT)

    def test_quote_list_routes_to_quote_list(self):
        result = self.route("liste sitater")
        self.assertEqual(result.intent, BotIntent.QUOTE_LIST)

    def test_birthday_edit_routes_to_birthday_edit(self):
        result = self.route("endre bursdag")
        self.assertEqual(result.intent, BotIntent.BIRTHDAY_EDIT)

    def test_watchlist_remove_routes_with_remove_action(self):
        result = self.route("fjern watchlist")
        self.assertEqual(result.intent, BotIntent.WATCHLIST)
        self.assertEqual(result.payload["watchlist"]["action"], "remove")


if __name__ == "__main__":
    unittest.main()
