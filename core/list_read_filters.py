"""Shared bounded grammars for unfiltered and single-date list reads."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from cal_system.reminder_clock import OSLO


ListReadFamily = Literal["calendar", "reminder"]

_WEEKDAY = (
    r"(?:mandag|måndag|tirsdag|onsdag|torsdag|fredag|lørdag|laurdag|"
    r"søndag|sundag|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)"
)
SINGLE_DATE_READ_FILTER = (
    r"(?:(?:for|on|på)\s+)?(?:"
    r"i\s+dag|idag|today|i\s+morgen|imorgen|i\s+morgon|imorgon|"
    r"i\s+morra|tomorrow|i\s+overmorgen|overmorgen|i\s+overmorgon|"
    r"overmorgon|day\s+after\s+tomorrow|"
    rf"(?:(?:neste|komande|kommande|kommende|førstkommende|next)\s+)?"
    rf"{_WEEKDAY}|"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)"
)

_POLITE_SHOW = (
    r"(?:(?:(?:can|could|would|will)\s+you|"
    r"(?:kan|kunne|vil)\s+du|please|vennligst)\s+)?"
)

_CALENDAR_CHECK_READ = (
    rf"(?:{_POLITE_SHOW}(?:check|sjekk|sjekke)\s+"
    r"(?:(?:my|min)\s+)?(?:calendar|schedule|kalender(?:en)?)"
    r"(?:\s+min)?)"
)
_CALENDAR_EXISTENTIAL_READ = (
    r"(?:(?:what\s+(?:do\s+i\s+have|have\s+i\s+got)|"
    r"(?:(?:do\s+i\s+have|is\s+there)\s+)?anything)\s+"
    r"(?:on|in)\s+my\s+(?:calendar|schedule)|"
    r"(?:har\s+(?:jeg|eg|æ)\s+(?:noe|noko|något)|"
    r"er\s+det\s+(?:noe|noko|något))\s+i\s+"
    r"kalenderen(?:\s+min)?)"
)
_CALENDAR_PLANS_READ = (
    r"(?:what\s+are\s+my\s+plans|"
    r"what\s+plans\s+do\s+i\s+have|"
    r"what\s+have\s+i\s+got\s+planned|"
    r"what\s+have\s+i\s+planned|"
    r"what\s+do\s+i\s+have\s+planned|"
    r"do\s+i\s+have(?:\s+anything)?\s+planned|"
    r"do\s+i\s+have\s+plans|"
    r"har\s+(?:jeg|eg|æ)\s+plan(?:er|ar)|"
    r"(?:hvilke|kva|ka)\s+plan(?:er|ar)\s+har\s+(?:jeg|eg|æ)|"
    r"(?:hva|kva|ka)\s+er\s+plan(?:ene|ane)\s+mine|"
    r"(?:hva|kva|ka)\s+har\s+(?:jeg|eg|æ)\s+planlag[td]|"
    r"what['’]s\s+going\s+on\s+in\s+my\s+(?:calendar|schedule))"
)
_REMINDER_CHECK_READ = (
    rf"(?:{_POLITE_SHOW}(?:check|sjekk|sjekke)\s+"
    r"(?:(?:my|mine)\s+)?(?:reminders?|påminnelsene|påminningane)"
    r"(?:\s+mine)?)"
)
_REMINDER_EXISTENTIAL_READ = (
    r"(?:(?:(?:do\s+i\s+have|are\s+there)\s+)?"
    r"any\s+reminders?(?:\s+for\s+me)?|"
    r"har\s+(?:jeg|eg|æ)\s+(?:(?:noen|nokon)\s+)?"
    r"(?:påminnelser|påminningar)|"
    r"er\s+det\s+(?:noen|nokon)\s+"
    r"(?:påminnelser|påminningar))"
)
_REMINDER_NEED_READ = (
    r"(?:do\s+i\s+need\s+to\s+remember\s+anything|"
    r"do\s+i\s+need\s+to\s+remember\s+something|"
    r"what\s+should\s+i\s+remember|"
    r"(?:is\s+there\s+)?anything\s+i\s+(?:should|have\s+to)\s+remember|"
    r"er\s+det\s+(?:noe|noko)\s+(?:jeg|eg|æ)\s+må\s+"
    r"(?:huske|hugse)|"
    r"er\s+det\s+(?:noe|noko)\s+(?:jeg|eg|æ)\s+bør\s+"
    r"(?:huske|hugse)|"
    r"(?:hva|kva|ka)\s+bør\s+(?:jeg|eg|æ)\s+(?:huske|hugse)|"
    r"må\s+(?:jeg|eg|æ)\s+(?:huske|hugse)\s+(?:noe|noko))"
)

_FILTERED_CALENDAR = re.compile(
    rf"(?:"
    rf"{_CALENDAR_CHECK_READ}|"
    rf"{_CALENDAR_EXISTENTIAL_READ}|"
    rf"{_CALENDAR_PLANS_READ}|"
    r"what(?:\s+is|['’]s)\s+(?:coming\s+up\s+)?on\s+my\s+calendar|"
    r"what['’]s\s+my\s+schedule|"
    r"what\s+do\s+i\s+have(?:\s+(?:on|in)\s+my\s+calendar)?|"
    r"(?:can|could)\s+i\s+see\s+my\s+calendar|"
    r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+kalenderen\s+min|"
    rf"{_POLITE_SHOW}(?:show|list|vis|vise)\s+"
    r"(?:(?:me|meg|mæ)\s+)?(?:my\s+)?(?:calendar|schedule|"
    r"kalenderen(?:\s+min)?)|"
    r"har\s+(?:jeg|eg|æ)\s+(?:noe|noko|något)\s+"
    r"(?:planlagt|i\s+kalenderen(?:\s+min)?)|"
    r"(?:hva|kva|ka)\s+skjer\s+i\s+kalenderen(?:\s+min)?|"
    r"(?:hva|kva|ka)\s+står\s+på\s+planen|"
    r"(?:hva|kva|ka)\s+har\s+(?:jeg|eg|æ)\s+i\s+"
    r"kalenderen(?:\s+min)?"
    rf")\s+{SINGLE_DATE_READ_FILTER}\s*[?.!]*",
    re.IGNORECASE,
)

_FILTERED_REMINDER = re.compile(
    rf"(?:"
    rf"{_REMINDER_CHECK_READ}|"
    rf"{_REMINDER_EXISTENTIAL_READ}|"
    rf"{_REMINDER_NEED_READ}|"
    r"what\s+reminders\s+do\s+i\s+have|"
    r"what\s+do\s+i\s+need\s+to\s+remember|"
    r"(?:is\s+there\s+)?anything\s+i\s+need\s+to\s+remember|"
    r"any\s+reminders|"
    r"do\s+i\s+have\s+any\s+reminders|"
    r"(?:can|could)\s+i\s+see\s+my\s+reminders|"
    r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
    r"(?:påminnelsene|påminningane)\s+mine|"
    rf"{_POLITE_SHOW}(?:show|list|vis|vise|sjå)\s+"
    r"(?:(?:me|meg|mæ)\s+)?(?:my\s+reminders|reminders|"
    r"(?:påminnelsene|påminningane)\s+mine)|"
    r"har\s+(?:jeg|eg|æ)\s+(?:(?:noen|nokon)\s+)?"
    r"(?:påminnelser|påminningar)|"
    r"(?:hva|kva|ka)\s+må\s+(?:jeg|eg|æ)\s+(?:huske|hugse)"
    rf")\s+{SINGLE_DATE_READ_FILTER}\s*[?.!]*",
    re.IGNORECASE,
)

_UNFILTERED_CALENDAR = re.compile(
    rf"(?:"
    r"(?:kalender|kalenderen|calendar|schedule)|"
    rf"{_POLITE_SHOW}(?:show|list|vis|vise)\s+"
    r"(?:(?:me|meg|mæ)\s+)?(?:my\s+)?(?:calendar|schedule|"
    r"kalenderen(?:\s+min)?)|"
    rf"{_CALENDAR_CHECK_READ}|"
    rf"{_CALENDAR_EXISTENTIAL_READ}|"
    rf"{_CALENDAR_PLANS_READ}|"
    r"(?:what(?:\s+is|['’]s)\s+(?:coming\s+up\s+)?on\s+"
    r"my\s+calendar|what['’]s\s+my\s+schedule)|"
    r"(?:can|could)\s+i\s+see\s+my\s+calendar|"
    r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+kalenderen\s+min|"
    r"(?:hva|kva|ka)\s+står(?:\s+det)?\s+i\s+kalenderen\s+min|"
    r"(?:what\s+do\s+you\s+know|tell\s+me)\s+about\s+my\s+calendar|"
    r"(?:hva\s+vet|kva\s+veit|ka\s+veit)\s+du\s+om\s+"
    r"kalenderen\s+min"
    r")\s*[?.!]*",
    re.IGNORECASE,
)

_UNFILTERED_REMINDER = re.compile(
    rf"(?:"
    r"(?:påminnelser|påminningar|reminders|gjøremål|todos|huskeliste)|"
    rf"{_POLITE_SHOW}(?:show|list|vis|vise|sjå)\s+"
    r"(?:(?:me|meg|mæ)\s+)?(?:(?:all|alle)\s+)?"
    r"(?:my\s+reminders|reminders|påminnelser|påminningar|"
    r"(?:påminnelsene|påminningane)"
    r"(?:\s+mine)?)|"
    rf"{_REMINDER_CHECK_READ}|"
    rf"{_REMINDER_EXISTENTIAL_READ}|"
    rf"{_REMINDER_NEED_READ}|"
    r"how\s+many\s+reminders\s+do\s+i\s+have|"
    r"what\s+reminders\s+do\s+i\s+have|"
    r"what\s+do\s+i\s+need\s+to\s+remember|"
    r"(?:is\s+there\s+)?anything\s+i\s+need\s+to\s+remember|"
    r"(?:can|could)\s+i\s+see\s+my\s+reminders|"
    r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
    r"(?:påminnelsene|påminningane)\s+mine|"
    r"(?:hva|kva|ka)\s+må\s+(?:jeg|eg|æ)\s+(?:huske|hugse)|"
    r"(?:hva|kva|ka)\s+står\s+på\s+(?:huskelista|hugselista)"
    r")\s*[?.!]*",
    re.IGNORECASE,
)

_LIST_READ_REQUEST_SHELL = re.compile(
    rf"(?:"
    rf"{_CALENDAR_PLANS_READ}\b|"
    rf"{_REMINDER_NEED_READ}\b|"
    rf"what\s+do\s+i\s+have\s+{SINGLE_DATE_READ_FILTER}\b|"
    rf"{_POLITE_SHOW}(?:check|sjekk|sjekke)\s+"
    r"(?!(?:whether|if|om)\b)[^\r\n]{0,160}\b(?:calendar|schedule|"
    r"kalender(?:en|oppgaver|oppgåver)?|reminders?|"
    r"påminnels(?:er|ene)|påminningar|"
    r"påminningane|events?|tasks?|arrangement(?:er|ene)?|hendelser|"
    r"oppgaver|oppgåver)\b|"
    r"(?:(?:do\s+i\s+have|is\s+there)\s+)?anything\b"
    r"[^\r\n]{0,160}\b(?:calendar|schedule)\b|"
    r"(?:har\s+(?:jeg|eg|æ)\s+(?:noe|noko|något)|"
    r"er\s+det\s+(?:noe|noko|något))\b[^\r\n]{0,160}\b"
    r"(?:kalender(?:en)?|planlagt)\b|"
    r"(?:(?:do\s+i\s+have|are\s+there)\s+)?any\b"
    r"[^\r\n]{0,80}\breminders?\b|"
    r"er\s+det\s+(?:noen|nokon)\b[^\r\n]{0,80}\b"
    r"(?:påminnelser|påminningar)\b|"
    r"(?:what\s+do\s+i\s+have|do\s+i\s+have\s+anything)\s+"
    r"planned\b|"
    r"(?:hva|kva|ka)\s+har\s+(?:jeg|eg|æ)\s+planlag[td]\b|"
    r"(?:show|list|vis|vise|sjå)\b.*\b(?:calendar|schedule|kalender|"
    r"reminders?|påminnelser|påminningar|events?|tasks?)\b|"
    r"(?:what|which)\b.*\b(?:calendar|schedule|reminders?|events?|tasks?)\b|"
    r"(?:any|do\s+i\s+have\s+any)\s+reminders?\b|"
    r"har\s+(?:jeg|eg|æ)\s+.*(?:planlagt|påminnelser|påminningar)\b|"
    r"(?:hva|kva|ka)\s+(?:står\s+på\s+planen|skjer\s+i\s+kalenderen|"
    r"må\s+(?:jeg|eg|æ)\s+(?:huske|hugse))\b"
    r")",
    re.IGNORECASE,
)


def filtered_list_read_family(text: str) -> ListReadFamily | None:
    """Return the one supported date-filtered list family, if any."""

    if _FILTERED_CALENDAR.fullmatch(text):
        return "calendar"
    if _FILTERED_REMINDER.fullmatch(text):
        return "reminder"
    return None


def unfiltered_list_read_family(text: str) -> ListReadFamily | None:
    """Return the one supported unfiltered list family, if any."""

    if _UNFILTERED_CALENDAR.fullmatch(text):
        return "calendar"
    if _UNFILTERED_REMINDER.fullmatch(text):
        return "reminder"
    return None


def looks_like_list_read_request(text: str) -> bool:
    """Recognize a list-read clause even when its filter is unsupported."""

    return bool(
        filtered_list_read_family(text)
        or unfiltered_list_read_family(text)
        or _LIST_READ_REQUEST_SHELL.match(text.strip())
    )


def is_supported_calendar_read_date(
    date_value: str,
    *,
    reference_time: datetime,
) -> bool:
    """Keep calendar reads aligned with its upcoming-only target contract."""

    if (
        not isinstance(reference_time, datetime)
        or reference_time.tzinfo is None
        or reference_time.utcoffset() is None
    ):
        return False
    try:
        requested = datetime.strptime(date_value, "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return False
    return requested >= reference_time.astimezone(OSLO).date()
