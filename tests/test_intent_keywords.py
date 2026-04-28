import unittest
from typing import cast

import core.intent_keywords as intent_keywords
from core.intent_keywords import (
    AURORA_KEYWORDS,
    CALENDAR_KEYWORDS,
    CLEAR_KEYWORDS,
    COMPLETE_KEYWORDS,
    DAILY_DIGEST_KEYWORDS,
    DELETE_KEYWORDS,
    EDIT_KEYWORDS,
    HELP_KEYWORDS,
    LIST_KEYWORDS,
    POLL_CLOSE_KEYWORDS,
    POLL_DELETE_KEYWORDS,
    POLL_EDIT_KEYWORDS,
    PROFILE_KEYWORDS,
    SCHOOL_HOLIDAYS_KEYWORDS,
    STATUS_KEYWORDS,
    SYNC_KEYWORDS,
    WORD_OF_DAY_KEYWORDS,
)


EXPECTED_KEYWORDS = {
    "HELP_KEYWORDS": (
        "hjelp", "help", "kommandoer", "commands",
        "hva kan du gjøre", "hva kan du", "hva gjør du",
        "funksjoner", "features", "capabilities",
        "hva er du", "hvem er du", "what can you do",
    ),
    "STATUS_KEYWORDS": (
        "bot status", "status bot", "inebotten status",
        "health", "helse", "diagnose", "diagnostics",
    ),
    "CALENDAR_KEYWORDS": (
        "kalender", "calendar", "arrangementer", "events",
        "kommende", "planlagt", "påminnelser", "huskeliste",
        "synk", "sync", "synkroniser", "gcal",
    ),
    "SYNC_KEYWORDS": ("synk", "sync", "synkroniser", "hent fra google", "oppdater fra google"),
    "DELETE_KEYWORDS": ("slett", "delete", "fjern"),
    "COMPLETE_KEYWORDS": ("ferdig", "done", "complete", "fullført"),
    "EDIT_KEYWORDS": ("endre", "edit", "oppdater"),
    "LIST_KEYWORDS": ("liste", "vis", "se", "oversikt"),
    "CLEAR_KEYWORDS": ("tøm", "clear", "empty", "slett alt", "fjern alt"),
    "PROFILE_KEYWORDS": (
        "status", "bio", "om meg", "about me", "endre navn", "spiller", "ser på",
        "playing", "watching",
    ),
    "WORD_OF_DAY_KEYWORDS": ("dagens ord", "word of the day", "lære meg et ord"),
    "AURORA_KEYWORDS": ("nordlys", "aurora", "nordly"),
    "SCHOOL_HOLIDAYS_KEYWORDS": ("skoleferie", "skoleferier", "vinterferie", "påskeferie"),
    "DAILY_DIGEST_KEYWORDS": ("daglig oppsummering", "daily digest", "oppsummering", "summary"),
    "POLL_EDIT_KEYWORDS": ("endre poll", "edit poll", "endre avstemning", "rediger poll"),
    "POLL_DELETE_KEYWORDS": ("slett poll", "delete poll", "fjern avstemning", "slett avstemning"),
    "POLL_CLOSE_KEYWORDS": ("lukk poll", "close poll", "avslutt avstemning", "steng poll"),
}

EXPECTED_EXPORTS = tuple(EXPECTED_KEYWORDS.keys())


def _keywords(name: str) -> tuple[str, ...]:
    return cast(tuple[str, ...], getattr(intent_keywords, name))


class IntentKeywordsTests(unittest.TestCase):
    def test_all_exports_are_present(self):
        self.assertEqual(tuple(intent_keywords.__all__), EXPECTED_EXPORTS)

    def test_all_exports_are_importable_and_tuples(self):
        for name in EXPECTED_EXPORTS:
            value = _keywords(name)
            self.assertIsInstance(value, tuple, f"{name} should be a tuple")
            self.assertEqual(value, EXPECTED_KEYWORDS[name], f"{name} changed unexpectedly")

    def test_no_duplicates_within_each_keyword_tuple(self):
        for name in EXPECTED_EXPORTS:
            value = _keywords(name)
            self.assertEqual(len(value), len(set(value)), f"{name} has duplicate keywords")

    def test_keyword_tuples_are_immutable(self):
        for name in EXPECTED_EXPORTS:
            value = _keywords(name)
            with self.assertRaises(TypeError, msg=f"{name} should be immutable"):
                exec("value[0] = value[0]", {}, {"value": value})

    def test_imported_constants_match_module_values(self):
        imported_values = {
            "HELP_KEYWORDS": HELP_KEYWORDS,
            "STATUS_KEYWORDS": STATUS_KEYWORDS,
            "CALENDAR_KEYWORDS": CALENDAR_KEYWORDS,
            "SYNC_KEYWORDS": SYNC_KEYWORDS,
            "DELETE_KEYWORDS": DELETE_KEYWORDS,
            "COMPLETE_KEYWORDS": COMPLETE_KEYWORDS,
            "EDIT_KEYWORDS": EDIT_KEYWORDS,
            "LIST_KEYWORDS": LIST_KEYWORDS,
            "CLEAR_KEYWORDS": CLEAR_KEYWORDS,
            "PROFILE_KEYWORDS": PROFILE_KEYWORDS,
            "WORD_OF_DAY_KEYWORDS": WORD_OF_DAY_KEYWORDS,
            "AURORA_KEYWORDS": AURORA_KEYWORDS,
            "SCHOOL_HOLIDAYS_KEYWORDS": SCHOOL_HOLIDAYS_KEYWORDS,
        "DAILY_DIGEST_KEYWORDS": DAILY_DIGEST_KEYWORDS,
        "POLL_EDIT_KEYWORDS": POLL_EDIT_KEYWORDS,
        "POLL_DELETE_KEYWORDS": POLL_DELETE_KEYWORDS,
        "POLL_CLOSE_KEYWORDS": POLL_CLOSE_KEYWORDS,
    }

        for name, value in imported_values.items():
            self.assertIs(value, _keywords(name), f"{name} should be imported from the module")


if __name__ == "__main__":
    _ = unittest.main()
