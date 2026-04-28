import unittest

from core.intent_utils import has_all_keywords, has_any_keyword, has_keyword, extract_keywords


class IntentUtilsTests(unittest.TestCase):
    def test_has_keyword_matches_whole_word(self):
        self.assertTrue(has_keyword("hello world", "hello"))

    def test_has_keyword_rejects_substring(self):
        self.assertFalse(has_keyword("helloworld", "hello"))

    def test_has_keyword_norwegian_chars(self):
        self.assertTrue(has_keyword("møte i morgen", "møte"))

    def test_has_keyword_rejects_substring_norwegian(self):
        self.assertFalse(has_keyword("avtale", "tale"))

    def test_has_keyword_case_insensitive(self):
        self.assertTrue(has_keyword("Hello World", "hello"))

    def test_has_any_keyword_finds_match(self):
        self.assertTrue(has_any_keyword("jeg har møte", ["avtale", "møte"]))

    def test_has_any_keyword_no_match(self):
        self.assertFalse(has_any_keyword("helt vanlig tekst", ["møte", "avtale"]))

    def test_has_all_keywords_all_present(self):
        self.assertTrue(has_all_keywords("møte i morgen", ["møte", "morgen"]))

    def test_has_all_keywords_one_missing(self):
        self.assertFalse(has_all_keywords("møte i dag", ["møte", "morgen"]))

    def test_extract_keywords_returns_matches(self):
        self.assertEqual(
            extract_keywords("møte i morgen", ["møte", "tale", "morgen"]),
            ["møte", "morgen"],
        )

    def test_extract_keywords_empty(self):
        self.assertEqual(extract_keywords("helt vanlig", ["møte", "avtale"]), [])
