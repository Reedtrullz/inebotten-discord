#!/usr/bin/env python3
"""Comprehensive false-positive regression tests for intent routing."""

import unittest
from datetime import datetime
from types import SimpleNamespace

from core.intent_router import BotIntent, IntentRouter
from cal_system.natural_language_parser import NaturalLanguageParser
from features.search_manager import detect_search_intent
from memory.conversation_context import ConversationContext


class DummyMonitor:
    def __init__(self, active_polls=False):
        self.nlp_parser = NaturalLanguageParser()
        self.countdown = SimpleNamespace(parse_countdown_query=self._parse_countdown)
        self.poll = SimpleNamespace(
            get_active_polls=lambda guild_id: [{"id": "poll1"}] if active_polls else []
        )
        self.conversation = SimpleNamespace(
            should_show_dashboard=ConversationContext().should_show_dashboard,
            threads={},
        )
        self.detect_search_intent = detect_search_intent

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
        return {"action": "suggest"} if "hva skal vi se" in content.lower() else None

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


class FalsePositiveTests(unittest.TestCase):
    def route(self, text, active_polls=False):
        monitor = DummyMonitor(active_polls=active_polls)
        return IntentRouter(monitor).route(text, guild_id=123)

    def test_conversational_rbk_opinion(self):
        result = self.route("Hva synes du om RBK i morgen?")
        self.assertNotEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_conversational_barely_listen(self):
        result = self.route("Jeg skal bare høre hva du synes")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_conversational_rbkjokes(self):
        result = self.route("Hva synes du om RBK på søndag?")
        self.assertNotEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_conversational_future_tense(self):
        result = self.route("Jeg skal reise til Oslo i morgen")
        self.assertNotEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_conversational_just_ask(self):
        result = self.route("Jeg skal bare spørre deg om noe i kveld")
        self.assertNotEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_vague_hva_skjer(self):
        result = self.route("Hva skjer?")
        self.assertNotEqual(result.intent, BotIntent.SEARCH)

    def test_opinion_where_live(self):
        result = self.route("Hvor bor du?")
        self.assertNotEqual(result.intent, BotIntent.SEARCH)

    def test_opinion_who_are_you(self):
        result = self.route("Hvem er du?")
        self.assertNotEqual(result.intent, BotIntent.SEARCH)

    def test_opinion_what_think(self):
        result = self.route("Hva mener du?")
        self.assertNotEqual(result.intent, BotIntent.SEARCH)

    def test_real_calendar_meeting(self):
        result = self.route("møte med Ola i morgen kl 14")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_real_calendar_remember(self):
        result = self.route("husk å kjøpe melk på mandag")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_real_calendar_event(self):
        result = self.route("arrangement 17. mai kl 12:00")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_real_search_trondheim(self):
        result = self.route("Hva skjer i Trondheim i helga?")
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_real_search_cost(self):
        result = self.route("Hva koster det å fly til Paris?")
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_english_conversational(self):
        result = self.route("What do you think about the weather tomorrow?")
        self.assertNotEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_english_calendar(self):
        result = self.route("meeting tomorrow at 3pm")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_status_ambiguous(self):
        result = self.route("Status på prosjektet")
        self.assertNotEqual(result.intent, BotIntent.STATUS)

    def test_help_explicit(self):
        result = self.route("hjelp")
        self.assertEqual(result.intent, BotIntent.HELP)

    def test_dashboard_explicit(self):
        result = self.route("vær i Trondheim")
        self.assertEqual(result.intent, BotIntent.DASHBOARD)

    def test_nynorsk_conversational(self):
        result = self.route("Kva meiner du om RBK?")
        self.assertNotEqual(result.intent, BotIntent.SEARCH)

    def test_nynorsk_calendar_still_works(self):
        result = self.route("Husk å kjøpe melk på måndag")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_english_weather_conversational(self):
        result = self.route("What do you think about the weather tomorrow?")
        self.assertNotEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_calendar_with_recurrence(self):
        result = self.route("møte hver tirsdag kl 10")
        self.assertEqual(result.intent, BotIntent.CALENDAR_ITEM)

    def test_search_with_news_trigger(self):
        result = self.route("nyheter om RBK")
        self.assertEqual(result.intent, BotIntent.SEARCH)

    def test_small_talk_greeting(self):
        result = self.route("Hei, hvordan går det?")
        self.assertEqual(result.intent, BotIntent.AI_CHAT)

    def test_explicit_calendar_list(self):
        result = self.route("kalender")
        self.assertEqual(result.intent, BotIntent.CALENDAR_LIST)


if __name__ == "__main__":
    unittest.main()
