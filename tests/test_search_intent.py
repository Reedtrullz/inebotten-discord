import importlib.util
import sys
import unittest
from typing import Callable, cast

sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('search_manager', 'features/search_manager.py')
assert spec is not None
assert spec.loader is not None
search_manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search_manager)
detect_search_intent = cast(Callable[[str], dict[str, str] | None], search_manager.detect_search_intent)


class SearchIntentTests(unittest.TestCase):
    # Opinion questions - should NOT trigger
    def test_opinion_question_rbk(self):
        self.assertIsNone(detect_search_intent("Hva synes du om RBK?"))

    def test_opinion_question_where_live(self):
        self.assertIsNone(detect_search_intent("Hvor bor du?"))

    def test_opinion_question_what_think(self):
        self.assertIsNone(detect_search_intent("Hva mener du om det?"))

    def test_opinion_question_like(self):
        self.assertIsNone(detect_search_intent("Liker du pizza?"))

    def test_opinion_question_believe(self):
        self.assertIsNone(detect_search_intent("Tror du det?"))

    # Information questions - should trigger
    def test_info_question_trondheim(self):
        result = detect_search_intent("Hva skjer i Trondheim?")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Trondheim", result["query"])

    def test_info_question_cost(self):
        result = detect_search_intent("Hva koster en kaffe?")
        self.assertIsNotNone(result)

    def test_info_question_who(self):
        result = detect_search_intent("Hvem er statsministeren?")
        self.assertIsNotNone(result)

    def test_info_question_how(self):
        result = detect_search_intent("Hvordan fungerer solceller?")
        self.assertIsNotNone(result)

    # Vague questions - should NOT trigger
    def test_vague_hva_skjer(self):
        self.assertIsNone(detect_search_intent("Hva skjer?"))

    def test_vague_hva_er_nytt(self):
        self.assertIsNone(detect_search_intent("Hva er nytt?"))

    # News triggers
    def test_news_trigger(self):
        result = detect_search_intent("Hva er siste nytt?")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["type"], "news")
