"""Shared user-facing value rendering for action confirmation cards."""

from __future__ import annotations

import unicodedata

from core.intent_payloads import canonical_recurrence_day_code


_VALUE_ALIASES = {
    ("gjentakelse", "daily"): "Hver dag",
    ("gjentakelse", "weekly"): "Hver uke",
    ("gjentakelse", "biweekly"): "Annenhver uke",
    ("gjentakelse", "monthly"): "Hver måned",
    ("gjentakelse", "yearly"): "Hvert år",
    ("type", "movie"): "Film",
    ("type", "series"): "Serie",
    ("type", "event"): "Avtale",
    ("type", "task"): "Oppgave",
    ("status", "active"): "Aktiv",
    ("status", "closed"): "Lukket",
    ("status", "online"): "Pålogget",
    ("status", "offline"): "Frakoblet",
    ("status", "idle"): "Borte",
    ("status", "dnd"): "Ikke forstyrr",
    ("status", "invisible"): "Usynlig",
    ("tidssone", "europe/oslo"): "Oslo",
    ("verdi", "online"): "Pålogget",
    ("verdi", "offline"): "Frakoblet",
    ("verdi", "idle"): "Borte",
    ("verdi", "dnd"): "Ikke forstyrr",
    ("verdi", "invisible"): "Usynlig",
}
_RRULE_DAY_DISPLAY = {
    "MO": "Mandag",
    "TU": "Tirsdag",
    "WE": "Onsdag",
    "TH": "Torsdag",
    "FR": "Fredag",
    "SA": "Lørdag",
    "SU": "Søndag",
}
_NORWEGIAN_FULL_DAY_NAMES = frozenset(
    {
        "mandag",
        "måndag",
        "tirsdag",
        "tysdag",
        "onsdag",
        "torsdag",
        "fredag",
        "lørdag",
        "laurdag",
        "søndag",
        "sundag",
    }
)


def display_confirmation_value(label: str, value: str) -> str:
    """Return one friendly Norwegian value without losing material content."""

    folded = value.casefold()
    if folded == "fjern":
        return "Fjern"
    if label == "gjentakelsesdag":
        if folded in _NORWEGIAN_FULL_DAY_NAMES:
            return value[:1].upper() + value[1:]
        day_code = canonical_recurrence_day_code(value)
        if day_code is not None:
            return _RRULE_DAY_DISPLAY[day_code]
        return value[:1].upper() + value[1:]
    alias = _VALUE_ALIASES.get((label, folded))
    if alias is not None:
        return alias
    if label == "status":
        return value[:1].upper() + value[1:]
    return value


def confirmation_display_identity(label: str, value: str) -> str:
    """Return the semantic identity of the value the confirmation will show."""

    if label == "gjentakelsesdag":
        day_code = canonical_recurrence_day_code(value)
        if day_code is not None:
            return f"weekday:{day_code.casefold()}"
    return unicodedata.normalize(
        "NFC",
        display_confirmation_value(label, value),
    ).casefold()


__all__ = [
    "confirmation_display_identity",
    "display_confirmation_value",
]
