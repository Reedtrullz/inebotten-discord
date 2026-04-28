#!/usr/bin/env python3
"""Shared intent keyword constants for Inebotten routing."""

HELP_KEYWORDS = (
    "hjelp", "help", "kommandoer", "commands",
    "hva kan du gjøre", "hva kan du", "hva gjør du",
    "funksjoner", "features", "capabilities",
    "hva er du", "hvem er du", "what can you do",
)

STATUS_KEYWORDS = (
    "bot status", "status bot", "inebotten status",
    "health", "helse", "diagnose", "diagnostics",
)

CALENDAR_KEYWORDS = (
    "kalender", "calendar", "arrangementer", "events",
    "kommende", "planlagt", "påminnelser", "huskeliste",
    "synk", "sync", "synkroniser", "gcal",
)

SYNC_KEYWORDS = ("synk", "sync", "synkroniser", "hent fra google", "oppdater fra google")
DELETE_KEYWORDS = ("slett", "delete", "fjern")
COMPLETE_KEYWORDS = ("ferdig", "done", "complete", "fullført")
EDIT_KEYWORDS = ("endre", "edit", "oppdater")
LIST_KEYWORDS = ("liste", "vis", "se", "oversikt")
CLEAR_KEYWORDS = ("tøm", "clear", "empty", "slett alt", "fjern alt")

PROFILE_KEYWORDS = (
    "status", "spiller", "ser på", "playing", "watching",
)

WORD_OF_DAY_KEYWORDS = ("dagens ord", "word of the day", "lære meg et ord")
AURORA_KEYWORDS = ("nordlys", "aurora", "nordly")
SCHOOL_HOLIDAYS_KEYWORDS = ("skoleferie", "skoleferier", "vinterferie", "påskeferie")
DAILY_DIGEST_KEYWORDS = ("daglig oppsummering", "daily digest", "oppsummering", "summary")

POLL_EDIT_KEYWORDS = ("endre poll", "edit poll", "endre avstemning", "rediger poll")
POLL_DELETE_KEYWORDS = ("slett poll", "delete poll", "fjern avstemning", "slett avstemning")
POLL_CLOSE_KEYWORDS = ("lukk poll", "close poll", "avslutt avstemning", "steng poll")

__all__ = [
    "HELP_KEYWORDS",
    "STATUS_KEYWORDS",
    "CALENDAR_KEYWORDS",
    "SYNC_KEYWORDS",
    "DELETE_KEYWORDS",
    "COMPLETE_KEYWORDS",
    "EDIT_KEYWORDS",
    "LIST_KEYWORDS",
    "CLEAR_KEYWORDS",
    "PROFILE_KEYWORDS",
    "WORD_OF_DAY_KEYWORDS",
    "AURORA_KEYWORDS",
    "SCHOOL_HOLIDAYS_KEYWORDS",
    "DAILY_DIGEST_KEYWORDS",
    "POLL_EDIT_KEYWORDS",
    "POLL_DELETE_KEYWORDS",
    "POLL_CLOSE_KEYWORDS",
]
