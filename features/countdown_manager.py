#!/usr/bin/env python3
"""
Countdown Manager for Inebotten
Handles "how long until..." queries and countdowns to events
Supports both Norwegian and English
"""

import re
from datetime import date, datetime, time
from dateutil.easter import easter


_LEADING_INVOCATION = re.compile(
    r"^\s*(?:@inebotten\b|<@!?\d+>)\s*[:,;-]?\s*",
    re.IGNORECASE,
)
_POLITE_PREFIX = re.compile(
    r"^(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s+",
    re.IGNORECASE,
)
_NON_REQUEST_PATTERNS = (
    re.compile(r"\b(?:ikke|ikkje|not|never|don['’]t|do\s+not)\b", re.IGNORECASE),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:sa|skrev|skreiv|leste|las)\b|"
        r"^i\s+(?:said|wrote|read)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:hva\s+skjer\s+hvis|kva\s+skjer\s+om|ka\s+skjer\s+hvis|"
        r"what\s+happens\s+if|hvis|om|if)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:eksempel|example|hva\s+betyr|kva\s+tyder|hvordan\s+skriver|"
        r"korleis\s+skriv|how\s+do\s+i\s+(?:say|write)|"
        r"what\s+does\b.*\bmean)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:vurderer|tenker\s+på)\b|"
        r"^i(?:'m|\s+am)\s+(?:considering|thinking\s+about)\b",
        re.IGNORECASE,
    ),
)
_TRAILING_POLITENESS = re.compile(
    r"\s*,?\s*(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you)\s*[?!.]*$",
    re.IGNORECASE,
)
_LEADING_COURTESY_REQUEST = re.compile(
    r"^(?:(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s*"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))|"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*,?\s*"
    r"(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please))\s*,?\s*",
    re.IGNORECASE,
)
_TRAILING_COURTESY = re.compile(
    r"(?:\s*,\s*|\s+)(?:(?:om|hvis|viss)\s+du\s+kan|"
    r"(?:om|hvis|viss)\s+du\s+har\s+tid|når\s+du\s+har\s+tid|"
    r"if\s+you\s+can|if\s+you\s+have\s+(?:time|a\s+moment)|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*[?!.]*$",
    re.IGNORECASE,
)
_COUNTDOWN_PATTERNS = (
    re.compile(
        r"^(?:(?:fortell(?:e)?|fortel|si)(?:\s+(?:meg|mæ))?\s+)?"
        r"(?:hvor|kor)\s+lenge(?:\s+(?:er\s+det|det\s+er))?"
        r"(?:\s+igjen)?\s+"
        r"(?:til|før)\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:(?:fortell(?:e)?|fortel|si)(?:\s+(?:meg|mæ))?\s+)?"
        r"(?:hvor\s+mange\s+dager|kor\s+mange\s+dagar)"
        r"(?:\s+(?:er\s+det|det\s+er))?(?:\s+igjen)?\s+"
        r"(?:til|før)\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:nedtelling|nedteljing)(?:en|a)?\s+(?:til|før)\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:når|nar)\s+er(?:\s+det)?\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:dager|dagar)\s+til\s+(?P<event>.+)$", re.IGNORECASE),
    re.compile(
        r"^(?:tell\s+me\s+)?how\s+long(?:\s+is\s+it)?\s+"
        r"(?:to|until|till)\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:tell\s+me\s+)?how\s+many\s+days"
        r"(?:\s+(?:are\s+there|there\s+are|are\s+left|left))?\s+"
        r"(?:to|until|till)\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"^countdown\s+(?:to|until|till)\s+(?P<event>.+)$", re.IGNORECASE),
    re.compile(
        r"^count\s+down\s+(?:to|until|till)\s+(?P<event>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"^when\s+is\s+(?:the\s+)?(?P<event>.+)$", re.IGNORECASE),
    re.compile(r"^days\s+(?:to|until)\s+(?P<event>.+)$", re.IGNORECASE),
    re.compile(
        r"^(?:tell\s+me\s+)?the\s+days\s+(?:to|until|till)\s+"
        r"(?P<event>.+)$",
        re.IGNORECASE,
    ),
)


def _prepare_countdown_request(message_content):
    if not isinstance(message_content, str):
        return None
    content = _LEADING_INVOCATION.sub("", message_content, count=1).strip()
    content = _LEADING_COURTESY_REQUEST.sub("", content, count=1).strip()
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = _TRAILING_COURTESY.sub("", content).strip()
    if not content or any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _POLITE_PREFIX.sub("", content, count=1).strip()
    if any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = re.sub(r"\bwhen['’]s\b", "when is", content, flags=re.IGNORECASE)
    return content.rstrip("?!").strip()


def _clean_event(raw_event):
    event = raw_event.strip().rstrip("?!.;,: ")
    if len(event) >= 2 and (event[0], event[-1]) in {
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
    }:
        event = event[1:-1].strip()
    return re.sub(r"\s+", " ", event)


class CountdownManager:
    """
    Manages countdowns to holidays, events, and custom dates
    """

    def __init__(self, now_provider=None):
        self._now_provider = now_provider or datetime.now

        # Important dates with both Norwegian and English names
        self.important_dates = {
            # Norwegian names
            "17. mai": (5, 17),
            "grunnlovsdagen": (5, 17),
            "jul": (12, 25),
            "julaften": (12, 24),
            "nyttår": (1, 1),
            "nyttårsaften": (12, 31),
            "påske": None,
            "halloween": (10, 31),
            "allehelgensdag": ("nth_weekday", 11, 6, 1),
            "valentines": (2, 14),
            "valentinsdagen": (2, 14),
            "morsdag": ("nth_weekday", 2, 6, 2),
            "farsdag": ("nth_weekday", 11, 6, 2),
            "sankthans": (6, 23),
            # English names
            "17 may": (5, 17),
            "constitution day": (5, 17),
            "christmas": (12, 25),
            "xmas": (12, 25),
            "christmas eve": (12, 24),
            "new year": (1, 1),
            "new years": (1, 1),
            "new years eve": (12, 31),
            "easter": None,
            "all saints day": ("nth_weekday", 11, 6, 1),
            "valentines day": (2, 14),
            "mothers day": ("nth_weekday", 2, 6, 2),
            "fathers day": ("nth_weekday", 11, 6, 2),
            "midsummer": (6, 23),
            "st hans": (6, 23),
        }

        # Emojis for events
        self.event_emojis = {
            "17. mai": "🇳🇴",
            "grunnlovsdagen": "🇳🇴",
            "17 may": "🇳🇴",
            "constitution day": "🇳🇴",
            "jul": "🎄",
            "julaften": "🎁",
            "christmas": "🎄",
            "christmas eve": "🎁",
            "xmas": "🎄",
            "nyttår": "🎆",
            "nyttårsaften": "🎇",
            "new year": "🎆",
            "new years eve": "🎇",
            "påske": "🐰",
            "easter": "🐰",
            "sommerferie": "🏖️",
            "summer holiday": "🏖️",
            "summer vacation": "🏖️",
            "vinterferie": "⛷️",
            "winter holiday": "⛷️",
            "høstferie": "🍂",
            "halloween": "🎃",
            "autumn holiday": "🍂",
            "fall break": "🍂",
            "valentines": "❤️",
            "valentinsdagen": "❤️",
            "valentines day": "❤️",
            "morsdag": "💐",
            "farsdag": "👔",
            "mothers day": "💐",
            "fathers day": "👔",
            "sankthans": "🔥",
            "midsummer": "🔥",
            "st hans": "🔥",
        }

    def parse_countdown_query(self, message_content, *, reference_time=None):
        """
        Parse countdown queries in Norwegian or English

        ``reference_time`` binds parsing and date arithmetic to the caller's
        captured turn clock.  Legacy callers can omit it; the injected provider
        is then read exactly once for a successfully parsed query.
        """
        content = _prepare_countdown_request(message_content)
        if not content:
            return None

        for pattern in _COUNTDOWN_PATTERNS:
            match = pattern.fullmatch(content)
            if match:
                event = _clean_event(match.group("event"))
                if event:
                    captured_reference = self._capture_reference(reference_time)
                    return self._find_date(
                        event,
                        reference_time=captured_reference,
                    )

        return None

    def _capture_reference(self, reference_time=None):
        captured = self._now_provider() if reference_time is None else reference_time
        if isinstance(captured, datetime):
            return captured
        if isinstance(captured, date):
            return datetime.combine(captured, time.min)
        raise TypeError("reference time must be a date or datetime")

    def _next_recurring_date(self, month_day, reference_day):
        year = reference_day.year
        if month_day is None:
            target_day = easter(year)
            if target_day < reference_day:
                target_day = easter(year + 1)
            return target_day

        if month_day[0] == "nth_weekday":
            _, month, weekday, occurrence = month_day
            for candidate_year in (year, year + 1):
                first_day = date(candidate_year, month, 1)
                offset = (weekday - first_day.weekday()) % 7
                target_day = first_day.replace(
                    day=1 + offset + (occurrence - 1) * 7
                )
                if target_day >= reference_day:
                    return target_day
            raise ValueError("no movable occurrence in bounded search window")

        month, day = month_day
        # Eight years covers a leap-day cycle with margin while keeping invalid
        # dates such as 31 February bounded and inert.
        for _ in range(8):
            try:
                target_day = date(year, month, day)
            except ValueError:
                year += 1
                continue
            if target_day >= reference_day:
                return target_day
            year += 1
        raise ValueError("no valid recurring date in bounded search window")

    def _find_date(self, query, *, reference_time=None):
        """Find date for a query and return structured data"""
        captured_reference = self._capture_reference(reference_time)
        reference_day = captured_reference.date()
        query_lower = re.sub(r"['’]", "", query.casefold()).strip()

        # A named event must be the complete target.  This prevents media titles
        # such as "the song Countdown to Christmas" from becoming commands.
        for holiday_name, month_day in self.important_dates.items():
            if query_lower in {holiday_name, f"the {holiday_name}"}:
                target_day = self._next_recurring_date(
                    month_day,
                    reference_day,
                )
                return self._calculate_countdown(
                    target_day,
                    query,
                    reference_time=captured_reference,
                )

        # Try the unambiguous ISO form first.
        date_match = re.fullmatch(
            r"(\d{4})-(\d{2})-(\d{2})",
            query_lower,
        )
        if date_match:
            raw_year, month, day = map(int, date_match.groups())
            try:
                return self._calculate_countdown(
                    date(raw_year, month, day),
                    query,
                    reference_time=captured_reference,
                )
            except ValueError:
                return None

        # Try to parse DD.MM.YYYY or DD.MM (Norwegian)
        date_match = re.fullmatch(
            r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?",
            query_lower,
        )
        if date_match:
            day, month, raw_year = date_match.groups()
            day, month = int(day), int(month)
            try:
                target_day = (
                    date(int(raw_year), month, day)
                    if raw_year
                    else self._next_recurring_date((month, day), reference_day)
                )
                return self._calculate_countdown(
                    target_day,
                    query,
                    reference_time=captured_reference,
                )
            except ValueError:
                return None

        # Try to parse MM/DD/YYYY or MM/DD (US format)
        date_match = re.fullmatch(
            r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?",
            query_lower,
        )
        if date_match:
            month, day, raw_year = date_match.groups()
            month, day = int(month), int(day)
            try:
                target_day = (
                    date(int(raw_year), month, day)
                    if raw_year
                    else self._next_recurring_date((month, day), reference_day)
                )
                return self._calculate_countdown(
                    target_day,
                    query,
                    reference_time=captured_reference,
                )
            except ValueError:
                return None

        return None

    def _calculate_countdown(self, target_date, event_name, *, reference_time=None):
        """Calculate a date-only countdown from one captured reference."""
        captured_reference = self._capture_reference(reference_time)
        reference_day = captured_reference.date()
        target_day = (
            target_date.date() if isinstance(target_date, datetime) else target_date
        )
        if not isinstance(target_day, date):
            raise TypeError("target date must be a date or datetime")

        days = (target_day - reference_day).days
        target_datetime = datetime.combine(
            target_day,
            time.min,
            tzinfo=captured_reference.tzinfo,
        )

        # Find emoji (use word boundaries)
        emoji = "📅"
        normalized_event_name = re.sub(r"['’]", "", event_name.casefold())
        for key, em in self.event_emojis.items():
            if re.search(rf"\b{re.escape(key)}\b", normalized_event_name):
                emoji = em
                break

        return {
            "event": event_name,
            "days": days,
            "hours": 0,
            "minutes": 0,
            "target_date": target_datetime,
            "emoji": emoji,
            "is_today": days == 0,
            "is_tomorrow": days == 1,
            "is_past": days < 0,
        }

    def format_response(self, countdown_data, lang="no"):
        """Format countdown response in specified language"""
        if not countdown_data:
            return None

        event = countdown_data["event"]
        days = countdown_data["days"]
        hours = countdown_data["hours"]
        emoji = countdown_data["emoji"]

        if countdown_data["is_past"]:
            if lang == "no":
                return f"📅 **{event}** var for {abs(days)} dager siden {emoji}"
            else:
                return f"📅 **{event}** was {abs(days)} days ago {emoji}"

        if countdown_data["is_today"]:
            if lang == "no":
                return f"🎉 **{event}** er i dag! {emoji}"
            else:
                return f"🎉 **{event}** is today! {emoji}"

        if countdown_data["is_tomorrow"]:
            if lang == "no":
                return f"📅 **{event}** er i morgen! {emoji}"
            else:
                return f"📅 **{event}** is tomorrow! {emoji}"

        # Format based on how close
        if days < 7:
            if lang == "no":
                return f"⏰ **{event}** om **{days}** dager! {emoji}"
            else:
                return f"⏰ **{event}** in **{days}** days! {emoji}"
        elif days < 30:
            weeks = days // 7
            remaining_days = days % 7
            if lang == "no":
                if remaining_days > 0:
                    return f"📅 **{event}** om {weeks} uker og {remaining_days} dager! {emoji}"
                else:
                    return f"📅 **{event}** om {weeks} uker! {emoji}"
            else:
                if remaining_days > 0:
                    return f"📅 **{event}** in {weeks} weeks and {remaining_days} days! {emoji}"
                else:
                    return f"📅 **{event}** in {weeks} weeks! {emoji}"
        elif days < 365:
            months = days // 30
            if lang == "no":
                return f"📅 **{event}** om ~{months} måneder ({days} dager) {emoji}"
            else:
                return f"📅 **{event}** in ~{months} months ({days} days) {emoji}"
        else:
            years = days // 365
            remaining_days = days % 365
            if lang == "no":
                return f"📅 **{event}** om {years} år og {remaining_days} dager {emoji}"
            else:
                return (
                    f"📅 **{event}** in {years} years and {remaining_days} days {emoji}"
                )


# Quick test
if __name__ == "__main__":
    manager = CountdownManager()

    test_queries = [
        ("@inebotten hvor lenge til 17. mai", "no"),
        ("@inebotten countdown to christmas", "en"),
        ("@inebotten nedtelling til jul", "no"),
        ("@inebotten how many days to easter", "en"),
    ]

    for query, lang in test_queries:
        result = manager.parse_countdown_query(query)
        if result:
            formatted = manager.format_response(result, lang)
            print(f"'{query}' → {formatted}")
        else:
            print(f"'{query}' → No match")
