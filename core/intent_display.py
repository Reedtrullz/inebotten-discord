"""Exhaustive localized display labels for typed bot intents."""

from types import MappingProxyType

from core.intent_models import BotIntent


INTENT_DISPLAY_LABELS = MappingProxyType(
    {
        BotIntent.HELP: "vise hjelp",
        BotIntent.STATUS: "vise status",
        BotIntent.PROFILE: "endre profilstatus",
        BotIntent.CALENDAR_HELP: "vise kalenderhjelp",
        BotIntent.CALENDAR_LIST: "vise kalenderen",
        BotIntent.CALENDAR_SYNC: "synkronisere kalenderen",
        BotIntent.CALENDAR_DELETE: "slette kalenderoppføringen",
        BotIntent.CALENDAR_COMPLETE: "fullføre kalenderoppføringen",
        BotIntent.CALENDAR_EDIT: "endre kalenderoppføringen",
        BotIntent.CALENDAR_SEARCH: "søke i kalenderen",
        BotIntent.CALENDAR_CLEAR: "tømme hele kalenderen",
        BotIntent.CALENDAR_ITEM: "opprette kalenderoppføring",
        BotIntent.POLL_CREATE: "opprette avstemning",
        BotIntent.POLL_VOTE: "stemme i avstemning",
        BotIntent.POLL_EDIT: "endre avstemning",
        BotIntent.POLL_DELETE: "slette avstemning",
        BotIntent.POLL_CLOSE: "lukke avstemning",
        BotIntent.POLL_LIST: "vise avstemninger",
        BotIntent.COUNTDOWN: "vise nedtelling",
        BotIntent.WATCHLIST: "bruke se-listen",
        BotIntent.WORD_OF_DAY: "vise dagens ord",
        BotIntent.QUOTE: "bruke sitater",
        BotIntent.QUOTE_LIST: "vise sitater",
        BotIntent.QUOTE_EDIT: "endre sitat",
        BotIntent.QUOTE_DELETE: "slette sitat",
        BotIntent.AURORA: "vise nordlysvarsel",
        BotIntent.SCHOOL_HOLIDAYS: "vise skoleferier",
        BotIntent.PRICE: "vise pris",
        BotIntent.HOROSCOPE: "vise horoskop",
        BotIntent.COMPLIMENT: "gi et kompliment",
        BotIntent.CALCULATOR: "regne ut uttrykket",
        BotIntent.SHORTEN_URL: "forkorte lenken",
        BotIntent.DAILY_DIGEST: "vise dagsoversikt",
        BotIntent.SEARCH: "søke etter informasjon",
        BotIntent.DASHBOARD: "vise oversikten",
        BotIntent.SET_LOCATION: "lagre bostedet",
        BotIntent.MEMORY_VIEW: "vise lagret brukerminne",
        BotIntent.MEMORY_EXPORT: "eksportere lagret brukerminne",
        BotIntent.MEMORY_DELETE: "slette lagret brukerminne",
        BotIntent.BIRTHDAY_EDIT: "endre bursdag",
        BotIntent.REMINDER_EDIT: "endre påminnelse",
        BotIntent.REMINDER_DELETE: "slette påminnelse",
        BotIntent.REMINDER_SEARCH: "søke i påminnelser",
        BotIntent.REMINDER_CREATE: "opprette påminnelse",
        BotIntent.REMINDER_LIST: "vise påminnelser",
        BotIntent.REMINDER_COMPLETE: "fullføre påminnelse",
        BotIntent.CALENDAR_AUTH: "starte kalenderautorisering",
        BotIntent.AI_CHAT: "svare på spørsmålet",
        BotIntent.CLARIFY: "be om avklaring",
        BotIntent.BIRTHDAY_CREATE: "lagre bursdag",
        BotIntent.BIRTHDAY_LIST: "vise bursdager",
        BotIntent.ACTION_CONFIRM: "bekrefte handling",
        BotIntent.ACTION_CANCEL: "avbryte handling",
        BotIntent.ACTION_SELECT: "velge tolkning",
        BotIntent.ACTION_CORRECT: "rette handling",
    }
)


if set(INTENT_DISPLAY_LABELS) != set(BotIntent):
    raise RuntimeError("intent_display_labels_not_exhaustive")


__all__ = ["INTENT_DISPLAY_LABELS"]
