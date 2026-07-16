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

    def test_local_memory_question_is_not_forced_onto_the_web(self):
        self.assertIsNone(detect_search_intent("Hva vet du om meg?"))

    def test_owned_calendar_question_is_not_forced_onto_the_web(self):
        self.assertIsNone(
            detect_search_intent("Hva vet du om kalenderen min?")
        )

    def test_owned_reminder_question_is_not_forced_onto_the_web(self):
        self.assertIsNone(
            detect_search_intent("Fortell meg om påminnelsene mine")
        )

    def test_owned_profile_question_is_not_forced_onto_the_web(self):
        self.assertIsNone(
            detect_search_intent("Kva veit du om profilen min?")
        )

    def test_explicit_web_search_still_wins_for_an_owned_noun(self):
        result = detect_search_intent("Søk på nett etter kalenderen min")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["type"], "web")

    def test_explicit_trailing_web_scope_overrides_local_knowledge_guard(self):
        cases = (
            "Søk etter kalenderen min på nettet",
            "What do you know about my calendar? Search the web.",
        )
        for text in cases:
            with self.subTest(text=text):
                result = detect_search_intent(text)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result["type"], "web")

    # Vague questions - should NOT trigger
    def test_vague_hva_skjer(self):
        self.assertIsNone(detect_search_intent("Hva skjer?"))

    def test_vague_hva_er_nytt(self):
        self.assertIsNone(detect_search_intent("Hva er nytt?"))

    def test_bare_temporal_what_happens_never_becomes_web_search(self):
        for head in ("Hva", "Kva", "Ka"):
            for complement in (
                "dag",
                "morgen",
                "morgon",
                "morra",
                "overmorgen",
                "overmorgon",
            ):
                text = f"{head} skjer i {complement}?"
                with self.subTest(text=text):
                    self.assertIsNone(detect_search_intent(text))

    def test_bare_temporal_guard_accepts_bot_mentions(self):
        cases = (
            "@inebotten Hva skjer i morgen?",
            "<@123> Kva skjer i morgon?",
            "<@!123> Ka skjer i morra?",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(detect_search_intent(text))

    def test_temporal_context_with_a_real_location_remains_searchable(self):
        result = detect_search_intent("Hva skjer i Trondheim i morgen?")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Trondheim", result["query"])

    # News triggers
    def test_news_trigger(self):
        result = detect_search_intent("Hva er siste nytt?")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["type"], "news")
