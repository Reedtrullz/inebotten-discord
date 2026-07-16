#!/usr/bin/env python3
# pyright: reportDeprecated=false, reportExplicitAny=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportAny=false, reportUnusedImport=false
"""Central intent router for Inebotten message handling."""

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import re
from typing import Any, Dict, Optional
from urllib.parse import unquote

from cal_system.natural_language_parser import NaturalParseResult
from cal_system.temporal_resolver import OSLO, TemporalResolver
from core.intent_arbitration import arbitrate_candidates
from core.calendar_fact_check_recognition import (
    parse_fact_check_continuation,
    parse_schedule_concern,
)
from core.calendar_fact_check_store import CalendarFactCheckStore

from core.intent_models import (
    BotIntent,
    CandidateRejection,
    IntentCandidate,
    IntentResult,
    IntentRisk,
    IntentSource,
    RejectionCode,
    RouteDiagnostics,
    RoutedIntent,
)
from core.intent_policy import classify_intent_risk
from core.list_read_filters import (
    filtered_list_read_family,
    is_supported_calendar_read_date,
    unfiltered_list_read_family,
)
from core.intent_payloads import (
    ENVELOPE_KEYS,
    PayloadValidationError,
    validate_intent_payload,
)
from core.message_context import (
    ConversationKey,
    RoutingContext,
    domain_scope_id,
)
from core.nlu_metrics import NLUMetrics
from core.pending_actions import (
    PendingActionStore,
    PendingResolutionKind,
)
from core.pending_targets import PendingTargetError
from core.utterance import NormalizedUtterance, normalize_utterance
from core.utterance_semantics import (
    MAX_SEQUENCE_CLAUSE_PROBES,
    SpeechAct,
    UtteranceSemantics,
    analyze_utterance,
    bounded_english_calendar_create_head,
    bounded_english_reminder_create_head,
    has_bounded_future_weather_request,
    has_sequenced_action_request,
    has_unsupported_poll_mutation_request,
    is_independent_conversational_request,
    is_standalone_action_retraction,
    sequenced_clause_candidates,
    strip_bounded_request_courtesy,
)

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
    QUOTE_DELETE_KEYWORDS,
    QUOTE_EDIT_KEYWORDS,
    QUOTE_LIST_KEYWORDS,
    REMINDER_COMPLETE_KEYWORDS,
    REMINDER_DELETE_KEYWORDS,
    REMINDER_EDIT_KEYWORDS,
    REMINDER_LIST_KEYWORDS,
    SCHOOL_HOLIDAYS_KEYWORDS,
    STATUS_KEYWORDS,
    SYNC_KEYWORDS,
    WORD_OF_DAY_KEYWORDS,
    GCAL_AUTH_KEYWORDS,
)
from core.intent_utils import has_any_keyword


@dataclass(frozen=True, slots=True)
class CollectorContext:
    utterance: NormalizedUtterance
    semantics: UtteranceSemantics
    routing: RoutingContext | None
    guild_id: int | None
    channel_id: int | None
    user_id: int | None
    reference_time: datetime

    @property
    def domain_scope_id(self) -> int | None:
        if self.routing is not None:
            return domain_scope_id(self.routing.key)
        return self.guild_id if self.guild_id is not None else self.channel_id


@dataclass(frozen=True, slots=True)
class CollectorOutput:
    candidates: tuple[IntentCandidate, ...] = ()
    parser_errors: tuple[str, ...] = ()
    rejections: tuple[CandidateRejection, ...] = ()


COLLECTOR_ORDER = (
    "_collect_control_candidates",
    "_collect_calendar_reminder_candidates",
    "_collect_poll_watchlist_quote_candidates",
    "_collect_utility_candidates",
    "_collect_fallback_candidates",
)


def _resolve_single_date_read_filter(
    resolver: TemporalResolver,
    text: str,
    *,
    reference_time: datetime,
) -> str | None:
    """Resolve one bounded date-only read against the turn's frozen clock."""

    try:
        resolved = resolver.resolve(text, reference=reference_time)
    except (TypeError, ValueError):
        return None
    if (
        resolved.errors
        or resolved.date is None
        or resolved.time is not None
        or resolved.due_at is not None
    ):
        return None
    return resolved.date


_SCHOOL_HOLIDAY_POLITE_HEAD = re.compile(
    r"^(?:(?:kan|kunne|vil|can|could|would|will)\s+(?:du|you)|"
    r"vennligst|please)\s+",
    re.IGNORECASE,
)
_SCHOOL_HOLIDAY_SHOW_HEAD = re.compile(
    r"^(?:vis|vise|show|list|liste|fortell|fortelje|tell)"
    r"(?:\s+(?:meg|mæ|me))?\s+",
    re.IGNORECASE,
)
_SCHOOL_HOLIDAY_ARTICLE = re.compile(
    r"^(?:den|det|de|the|a|an)\s+",
    re.IGNORECASE,
)
_SCHOOL_HOLIDAY_DESCRIPTORS = frozenset(
    {
        "dato",
        "datoen",
        "datoer",
        "datoene",
        "oversikt",
        "kalender",
        "date",
        "dates",
        "overview",
        "calendar",
        "schedule",
    }
)

_SCHOOL_HOLIDAY_TERMINAL_DATE_WORDS = frozenset(
    {
        "begin",
        "begins",
        "begynne",
        "begynner",
        "end",
        "ends",
        "slutt",
        "slutter",
        "start",
        "starts",
        "starter",
    }
)


def _school_holiday_topic_suffix(text: str) -> tuple[str, str] | None:
    cleaned = text.strip().rstrip("?!.,")
    for keyword in sorted(
        SCHOOL_HOLIDAYS_KEYWORDS,
        key=len,
        reverse=True,
    ):
        if cleaned == keyword:
            return keyword, ""
        if cleaned.startswith(f"{keyword} "):
            return keyword, cleaned[len(keyword):].strip()
    return None


def _is_compact_school_holiday_request(control: str) -> bool:
    """Accept only a bare holiday topic or topic plus a known location."""

    split = _school_holiday_topic_suffix(control)
    if split is None:
        return False
    _, suffix = split
    if not suffix:
        return True

    from features.school_holidays import get_fylke_from_exact_location

    return get_fylke_from_exact_location(suffix) is not None


def _is_school_holiday_show_request(control: str) -> bool:
    cleaned = control.strip().rstrip("?!.,")
    without_polite = _SCHOOL_HOLIDAY_POLITE_HEAD.sub("", cleaned, count=1)
    without_action = _SCHOOL_HOLIDAY_SHOW_HEAD.sub(
        "",
        without_polite,
        count=1,
    )
    if without_action == without_polite:
        return False
    topic_text = _SCHOOL_HOLIDAY_ARTICLE.sub("", without_action, count=1)
    split = _school_holiday_topic_suffix(topic_text)
    if split is None:
        return False
    _, suffix = split
    if not suffix:
        return True

    from features.school_holidays import get_fylke_from_exact_location

    if get_fylke_from_exact_location(suffix) is not None:
        return True
    descriptor, _, location = suffix.partition(" ")
    return (
        descriptor in _SCHOOL_HOLIDAY_DESCRIPTORS
        and (
            not location
            or get_fylke_from_exact_location(location) is not None
        )
    )


def _is_bounded_school_holiday_suffix(
    suffix: str,
    *,
    allow_empty: bool,
) -> bool:
    """Allow only date words or one exact location after a holiday topic."""

    cleaned = suffix.strip().rstrip("?!.,")
    if not cleaned:
        return allow_empty
    if cleaned in _SCHOOL_HOLIDAY_TERMINAL_DATE_WORDS:
        return True

    from features.school_holidays import get_fylke_from_exact_location

    if get_fylke_from_exact_location(cleaned) is not None:
        return True
    descriptor, _, location = cleaned.partition(" ")
    return (
        descriptor in _SCHOOL_HOLIDAY_DESCRIPTORS
        and (
            not location
            or get_fylke_from_exact_location(location) is not None
        )
    )


def _topic_after_school_question_head(
    text: str,
    pattern: str,
) -> tuple[str, str] | None:
    match = re.match(pattern, text, re.IGNORECASE)
    if match is None:
        return None
    topic_text = _SCHOOL_HOLIDAY_ARTICLE.sub(
        "",
        match.group("topic").strip(),
        count=1,
    )
    return _school_holiday_topic_suffix(topic_text)


def _is_school_holiday_date_question(control: str) -> bool:
    """Recognize bounded date/list questions with the topic in request slot."""

    # The topic must begin immediately after the question shell. This keeps
    # media titles such as "when is Summer Vacation showing?" conversational.
    split = _topic_after_school_question_head(
        control,
        r"^(?:når|when)\s+(?:er|is|are|starter|start|begynner|begins|does)"
        r"\s+(?P<topic>.+)$",
    )
    if split is not None:
        _, suffix = split
        return _is_bounded_school_holiday_suffix(suffix, allow_empty=True)

    duration = re.match(
        r"^(?:(?:hvor|kor)\s+(?:lenge|mange\s+dag(?:er|ar))\b.*?"
        r"\b(?:til|før)\b|how\s+(?:long|many\s+days)\b.*?"
        r"\b(?:to|until|till)\b)\s+(?P<topic>.+)$",
        control,
        re.IGNORECASE,
    )
    if duration is not None:
        split = _school_holiday_topic_suffix(duration.group("topic"))
        return bool(
            split is not None
            and _is_bounded_school_holiday_suffix(
                split[1],
                allow_empty=True,
            )
        )

    # "What are the school holidays in Oslo?" is a location lookup, while
    # the unscoped definitional question "what are school holidays?" belongs
    # in conversation. A date descriptor also makes the request executable.
    split = _topic_after_school_question_head(
        control,
        r"^(?:(?:hva|kva|ka)\s+(?:er|blir)|what\s+(?:is|are))\s+"
        r"(?P<topic>.+)$",
    )
    if split is not None:
        _, suffix = split
        return _is_bounded_school_holiday_suffix(
            suffix,
            allow_empty=False,
        )

    split = _topic_after_school_question_head(
        control,
        r"^(?:hvilke|kva\s+for|which)\s+(?P<topic>.+)$",
    )
    if split is not None:
        _, suffix = split
        owned_location = re.fullmatch(
            r"(?:does\s+(.+?)\s+have|har\s+(.+))",
            suffix,
            re.IGNORECASE,
        )
        if owned_location is not None:
            location = next(
                group for group in owned_location.groups() if group
            )
            return _is_bounded_school_holiday_suffix(
                location,
                allow_empty=False,
            )
        suffix = re.sub(
            r"^(?:er\s+det|finnes\s+det|are(?:\s+there)?)\s+",
            "",
            suffix,
            count=1,
            flags=re.IGNORECASE,
        )
        return _is_bounded_school_holiday_suffix(suffix, allow_empty=True)

    # English/Norwegian topic-first variants: "what school holidays are
    # there in Oslo?". Requiring the exact existential tail avoids treating
    # opinions or planning questions as feature calls.
    existential = re.match(
        r"^(?:what|hva|kva|ka)\s+(?P<topic>.+?)\s+"
        r"(?:are\s+there|er\s+det|finnes\s+det)\s+"
        r"(?P<location>.+)$",
        control,
        re.IGNORECASE,
    )
    if existential is not None:
        split = _school_holiday_topic_suffix(existential.group("topic"))
        return bool(
            split is not None
            and not split[1]
            and _is_bounded_school_holiday_suffix(
                existential.group("location"),
                allow_empty=False,
            )
        )
    return False


def _is_bounded_school_holiday_request(control: str) -> bool:
    control = strip_bounded_request_courtesy(control)
    return (
        _is_compact_school_holiday_request(control)
        or _is_school_holiday_show_request(control)
        or _is_school_holiday_date_question(control)
    )


_READ_TOPIC_POLITE_HEAD = re.compile(
    r"^(?:(?:kan|kunne|vil|can|could|would|will)\s+(?:du|you)|"
    r"vennligst|please)\s+",
    re.IGNORECASE,
)
_READ_TOPIC_ACTION_HEAD = re.compile(
    r"^(?:vis|vise|show|hent|get|gi|gje|give|fortell|fortelje|tell)"
    r"(?:\s+(?:meg|mæ|me))?\s+",
    re.IGNORECASE,
)
_READ_TOPIC_ARTICLE = re.compile(
    r"^(?:den|det|et|eit|en|ei|the|a|an)\s+",
    re.IGNORECASE,
)
_READ_TOPIC_QUESTION_HEAD = re.compile(
    r"^(?:(?:hva|kva|ka)\s+er|what\s+is|what['’]s)\s+",
    re.IGNORECASE,
)
_WORD_OF_DAY_NATURAL_REQUEST = re.compile(
    r"^(?:(?:(?:kan|kunne|vil|can|could|would|will)\s+(?:du|you)\s+)?"
    r"(?:lær|lære|teach)(?:\s+(?:meg|mæ|me))?\s+"
    r"(?:(?:et|eit|a)\s+(?:ord|word)|dagens\s+ord)|"
    r"(?:what\s+is|what['’]s)\s+today['’]s\s+word)\s*[?.!]*$",
    re.IGNORECASE,
)
_AURORA_NATURAL_REQUEST = re.compile(
    r"^(?:(?:kan|vil)\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
    r"(?:nordlys|aurora)(?:\s+i\s+kveld)?|"
    r"(?:blir|er)\s+det\s+(?:nordlys|aurora)(?:\s+i\s+kveld)?|"
    r"(?:will|can|could)\s+i\s+see\s+(?:the\s+)?"
    r"(?:aurora|northern\s+lights)(?:\s+tonight)?|"
    r"(?:is\s+there|will\s+there\s+be)\s+(?:an?\s+|the\s+)?"
    r"(?:aurora|northern\s+lights)(?:\s+tonight)?)\s*[?.!]*$",
    re.IGNORECASE,
)


def _is_bounded_read_topic_request(
    control: str,
    keywords: tuple[str, ...],
    *,
    information_keywords: tuple[str, ...] = (),
) -> bool:
    """Match an exact topic, optionally wrapped in one bounded read request."""

    cleaned = strip_bounded_request_courtesy(control)
    if cleaned in keywords:
        return True
    without_question = _READ_TOPIC_QUESTION_HEAD.sub("", cleaned, count=1)
    if without_question != cleaned:
        topic = _READ_TOPIC_ARTICLE.sub("", without_question, count=1)
        return topic in information_keywords
    without_polite = _READ_TOPIC_POLITE_HEAD.sub("", cleaned, count=1)
    without_action = _READ_TOPIC_ACTION_HEAD.sub(
        "",
        without_polite,
        count=1,
    )
    if without_action == without_polite:
        return False
    topic = _READ_TOPIC_ARTICLE.sub("", without_action, count=1)
    return topic in keywords


_PARSER_NAMES = frozenset(
    {
        "parse_task_with_recurrence",
        "parse_event",
        "parse_countdown_query",
        "parse_poll_command",
        "parse_vote",
        "parse_watchlist_command",
        "parse_quote_command",
        "parse_price_command",
        "parse_horoscope_command",
        "parse_compliment_command",
        "parse_calculator_command",
        "parse_shorten_command",
        "detect_search_intent",
        "parse_reminder_command",
        "parse_birthday_command",
        "parse_profile_command",
    }
)
_PARSER_METRIC_FAMILY = {
    "parse_task_with_recurrence": "calendar",
    "parse_event": "calendar",
    "parse_countdown_query": "countdown",
    "parse_poll_command": "poll",
    "parse_vote": "poll",
    "parse_watchlist_command": "watchlist",
    "parse_quote_command": "quote",
    "parse_price_command": "price",
    "parse_horoscope_command": "horoscope",
    "parse_compliment_command": "compliment",
    "parse_calculator_command": "calculator",
    "parse_shorten_command": "shorten",
    "detect_search_intent": "search",
    "parse_reminder_command": "reminder",
    "parse_birthday_command": "birthday",
    "parse_profile_command": "profile",
}

CAPABILITY_HELP = re.compile(
    r"^(?:(?:hva|kva|ka|what)\s+(?:kan|can)\s+(?:du|you)\s+"
    r"(?:gjøre|gjere|gjør|do)|what\s+can\s+you\s+help\s+me\s+with|"
    r"tell\s+me\s+what\s+you\s+can\s+do|"
    r"show\s+me\s+what\s+you\s+can\s+do|"
    r"how\s+can\s+you\s+help(?:\s+me)?|"
    r"what\s+(?:are\s+you\s+capable\s+of|"
    r"capabilities\s+do\s+you\s+have|features\s+do\s+you\s+have)|"
    r"(?:hva|kva|ka)\s+kan\s+du\s+hjelpe"
    r"(?:\s+(?:meg|mæ))?\s+med|"
    r"(?:hva|kva|ka)\s+kan\s+(?:jeg|eg|æ)\s+bruke\s+"
    r"(?:deg|dæ)\s+til|"
    r"hvilke\s+ting\s+kan\s+du\s+(?:gjøre|gjere))\s*\??$",
    re.IGNORECASE,
)
_COURTESY_CONDITION = (
    r"(?:(?:hvis|om|når)\s+du\s+har\s+tid|hvis\s+det\s+passer|"
    r"(?:hvis|om)\s+du\s+kan|"
    r"(?:if|when)\s+you\s+have\s+time|"
    r"if\s+(?:it(?:'s|\s+is)\s+)?convenient|if\s+you\s+can|"
    r"if\s+possible)"
)
_POLITE_REQUEST_HEAD = (
    r"(?:kan\s+du|kunne\s+du|vil\s+du|can\s+you|could\s+you|"
    r"would\s+you|will\s+you|vennligst|please)"
)
_BOUNDED_SEARCH_REQUEST_SHELL = (
    r"(?:(?:"
    rf"{_POLITE_REQUEST_HEAD}(?:(?:\s*,\s*|\s+)"
    rf"{_COURTESY_CONDITION}\s*,?)?\s+|"
    rf"{_COURTESY_CONDITION}(?:(?:\s*,\s*|\s+)"
    rf"{_POLITE_REQUEST_HEAD}\s+|\s*,\s*)"
    r"))?"
)
_SEARCH_ACTION = r"(?:søk|søke|søkje|search|look\s+up)"
_BOUNDED_BARE_SEARCH_REQUEST = re.compile(
    rf"^{_BOUNDED_SEARCH_REQUEST_SHELL}{_SEARCH_ACTION}\s+"
    r"(?:(?:etter|for)\s+)?(?P<query>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)
_TRAILING_SEARCH_COURTESY = re.compile(
    rf"(?:(?:\s*,\s*|\s+){_COURTESY_CONDITION}|"
    r"(?:\s*,\s*|\s+)(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you))\s*[?.!]*$",
    re.IGNORECASE,
)
_EXACT_SEARCH_COURTESY_QUERIES = frozenset(
    {
        "please",
        "takk",
        "takk skal du ha",
        "thank you",
        "thanks",
        "tusen takk",
    }
)
EXPLICIT_SHORTEN = re.compile(
    rf"^(?:{_COURTESY_CONDITION}(?:\s*,\s*|"
    rf"\s+(?={_POLITE_REQUEST_HEAD}\b)))?"
    rf"(?:{_POLITE_REQUEST_HEAD}"
    rf"(?:(?:\s*,\s*|\s+){_COURTESY_CONDITION}\s*,?)?\s+)?"
    r"(?:(?:forkort|forkorte|kort\s+ned|korte\s+ned|shorten)\s+"
    r"(?:(?:denne|this)\s+(?:url(?:-en)?|lenk(?:e|en)|link)"
    r"(?:\s+for\s+me)?\s*[:?]?\s*)?https?://[^\s]+?|"
    r"make\s+this\s+url\s+shorter\s*:?\s*https?://[^\s]+?|"
    r"(?:lag|lage|make)\s+(?:en|ei|a)\s+"
    r"(?:kort\s+lenke|short\s+link)\s+(?:av|for|from)\s+"
    rf"https?://[^\s]+?)(?:\s*,?\s+{_COURTESY_CONDITION})?"
    r"(?:\s*[,;]?\s+(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you)\s*[.!?]*)?$",
    re.IGNORECASE,
)
INFORMATION_TRANSIT = re.compile(
    r"^(?:når|when|hva tid|kva tid|ka tid)\b.*\b"
    r"(?:tog|toget|buss|bussen|train|bus)\b",
    re.IGNORECASE,
)
VAGUE_WHAT_HAPPENS = re.compile(
    r"^(?:hva|kva|ka)\s+skjer\??$", re.IGNORECASE
)

_POLITE_COMMAND_PREFIX = (
    r"(?:(?:(?:kan|kunne|vil|can|could|would|will)\s+(?:du|you)\s+)|"
    r"(?:(?:vennligst|please)\s+))?"
)
_CALENDAR_EDIT_KEEP_TIME = re.compile(
    r"^(?:(?:men|but|og|and)\s+)?(?:ikke|ikkje|do\s+not|don't|don’t)\s+"
    r"(?:endre|change)\s+(?:tidspunktet|tiden|tida|klokkeslettet|"
    r"the\s+time|time)$",
    re.IGNORECASE,
)
_CALENDAR_EDIT_TEMPORAL_FILLERS = frozenset(
    {"", "på", "on", "den", "takk", "please", "thanks"}
)
_ENGLISH_BARE_CLOCK_TIME = re.compile(
    r"(?<!\w)at\s+(?:[1-9]|1[0-2])"
    r"(?:(?::|\.)(?:[0-5]\d))?(?![\d:])"
    r"(?!\s*(?:am|pm|in\s+the\s+morning|in\s+the\s+afternoon|"
    r"in\s+the\s+evening|at\s+night)\b)",
    re.IGNORECASE,
)
_ENGLISH_CALENDAR_TIME_FRAME = re.compile(
    r"\b(?:meeting|appointment|event|calendar|schedule|book|put|add)\b",
    re.IGNORECASE,
)
_ENGLISH_REMINDER_TIME_FRAME = re.compile(
    r"\b(?:remind\s+me|remember|don['’]?t\s+(?:let\s+me\s+)?forget|"
    r"i\s+need\s+to|reminder)\b",
    re.IGNORECASE,
)
_CALENDAR_FAMILY = r"møte|avtale|kalender|påminnelse|reminder|event"
_CALENDAR_ITEM_FAMILY = (
    r"møte|møtet|avtale|avtalen|arrangement|arrangementet|"
    r"meeting|appointment|event|eventet"
)
_FOREIGN_CALENDAR_CREATE_DOMAIN = re.compile(
    r"\b(?:"
    r"påminnelse(?:n|r|ne)?|påminning(?:a|ar|ane)?|reminders?|"
    r"gjøremål|gjeremål|todos?|"
    r"bursdag(?:en|er|ene|ar|ane)?|"
    r"fødselsdag(?:en|er|ene|ar|ane)?|birthdays?|"
    r"watch\s*list|watchlist(?:a|en)?|filmlist(?:a|e|en)?|"
    r"serielist(?:a|e|en)?|"
    r"se[-\s]?list(?:a|e|en)?|sjå[-\s]?list(?:a|e|en)?|"
    r"avstemning(?:a|en|er|ar|ane)?|avstemming(?:a|en|er|ar|ane)?|"
    r"avstemnning|polls?|stemme|vote|voting|"
    r"sitat(?:et|er|ene|a)?|quotes?|profil(?:en)?|profiles?"
    r")\b",
    re.IGNORECASE,
)
_CALENDAR_MUTATION_FAMILY = (
    rf"{_CALENDAR_FAMILY}|arrangement|meeting|"
    r"kalenderoppføring(?:en|a|er|ene)?|calendar\s+(?:entry|item)"
)
_RESERVED_CALENDAR_AUTH_CODES = frozenset(
    {
        "avbryt",
        "cancel",
        "dropp",
        "nei",
        "no",
        "stopp",
        "stop",
    }
)
_OAUTH_REDIRECT_CODE = re.compile(
    r"(?:[?&]code=)(?P<code>[^&\s]{6,2048})",
    re.IGNORECASE,
)
_BARE_OAUTH_CODE = re.compile(
    r"(?P<code>4(?:/|%2f)"
    r"(?=[A-Za-z0-9._~%+\-/=]{4,2048})"
    r"(?=[A-Za-z0-9._~%+\-/=]*[A-Za-z_\-])"
    r"[A-Za-z0-9._~%+\-/=]{4,2048})",
    re.IGNORECASE,
)
_EXPLICIT_AUTH_FOLLOWUP = re.compile(
    r"(?:\b(?:kalender|gcal)\s+(?:auth|login|kode|code)|"
    r"\bkalenderkode)\s+"
    r"(?P<code>[A-Za-z0-9._~%+\-/=]{6,2048})",
    re.IGNORECASE,
)
_NATURAL_AUTH_FOLLOWUP = re.compile(
    r"(?:"
    r"(?:her|here)\s+(?:er|is)\s+(?:den|koden|kode|the\s+code)|"
    r"(?:den\s+nye\s+|min\s+|my\s+)?"
    r"(?:koden|kode|code|oauth-koden|oauth-code|oauth\s+code)\s+"
    r"(?:er|is)|"
    r"(?:jeg\s+fikk|i\s+got)\s+(?:denne\s+|the\s+)?(?:koden|code)"
    r")\s*[:=\-]?\s*`?"
    r"(?P<code>(?=[A-Za-z0-9._~%+\-/=]{6,2048})"
    r"(?=[A-Za-z0-9._~%+\-/=]*[0-9_%+\-/=])"
    r"[A-Za-z0-9._~%+\-/=]{6,2048})`?",
    re.IGNORECASE,
)
_WATCHLIST_GENRE = (
    r"komedie|comedy|drama|sci-fi|action|thriller|horror"
)
_WATCHLIST_SUGGESTION_FRAME = re.compile(
    rf"(?:hva\s+skal\s+vi\s+se|what\s+should\s+we\s+watch|"
    rf"(?:filmforslag|serieforslag)(?:\s+(?:{_WATCHLIST_GENRE}))?|"
    rf"(?:movie|series)\s+suggestion(?:\s+(?:{_WATCHLIST_GENRE}))?|"
    rf"anbefaling\s+(?:(?:{_WATCHLIST_GENRE})\s+)?"
    rf"(?:film|serie)(?:\s+(?:{_WATCHLIST_GENRE}))?|"
    rf"(?:(?:can|could|would|will)\s+you\s+|please\s+)?"
    rf"recommend(?:\s+me)?\s+(?:(?:a|an|some)\s+)?"
    rf"(?:(?:{_WATCHLIST_GENRE})\s+)?(?:movie|series|show)"
    rf"(?:\s+(?:{_WATCHLIST_GENRE}))?)\s*\??",
    re.IGNORECASE,
)
_SUPPORTED_QUOTE_SPAN = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|«[^»\n]*»|'
    r"(?<!\w)'[^'\n]+'(?!\w)"
)
_LEADING_QUOTE_SAVE_FRAME = re.compile(
    r"^(?P<frame>husk\s+dette|lagre\s+dette|dette\s+må\s+huskes|"
    r"gullkorn|remember\s+this|save\s+this|"
    r"this\s+must\s+be\s+remembered|quote\s+this|"
    r"lagre\s+sitat|save\s+quote)\b"
    r"(?:\s*[:\-–—]\s*|\s+)(?P<payload>.+?)\s*$",
    re.IGNORECASE,
)
_POLL_EDIT_FIELD = re.compile(
    r"(?<!\w)(?P<label>spørsmål|question|alternativer|options)\s*:\s*",
    re.IGNORECASE,
)
_CANONICAL_CALENDAR_CREATE_FIELDS = (
    "title",
    "date",
    "time",
    "type",
    "recurrence",
    "recurrence_day",
    "rrule_day",
    "days_offset",
    "description",
)
_PAYLOAD_METRIC_FAMILY = {
    **{
        intent: "calendar"
        for intent in (
            BotIntent.CALENDAR_ITEM,
            BotIntent.CALENDAR_LIST,
            BotIntent.CALENDAR_EDIT,
            BotIntent.CALENDAR_FACT_CHECK,
            BotIntent.CALENDAR_DELETE,
            BotIntent.CALENDAR_COMPLETE,
            BotIntent.CALENDAR_CLEAR,
        )
    },
    **{
        intent: "reminder"
        for intent in (
            BotIntent.REMINDER_CREATE,
            BotIntent.REMINDER_LIST,
            BotIntent.REMINDER_SEARCH,
            BotIntent.REMINDER_COMPLETE,
            BotIntent.REMINDER_EDIT,
            BotIntent.REMINDER_DELETE,
        )
    },
    **{
        intent: "poll"
        for intent in (
            BotIntent.POLL_CREATE,
            BotIntent.POLL_VOTE,
            BotIntent.POLL_EDIT,
            BotIntent.POLL_DELETE,
            BotIntent.POLL_CLOSE,
        )
    },
    BotIntent.WATCHLIST: "watchlist",
    BotIntent.QUOTE: "quote",
    BotIntent.QUOTE_LIST: "quote",
    BotIntent.QUOTE_EDIT: "quote",
    BotIntent.QUOTE_DELETE: "quote",
    BotIntent.BIRTHDAY_CREATE: "birthday",
    BotIntent.BIRTHDAY_LIST: "birthday",
    BotIntent.BIRTHDAY_EDIT: "birthday",
    BotIntent.MEMORY_VIEW: "other",
    BotIntent.MEMORY_EXPORT: "other",
    BotIntent.MEMORY_DELETE: "other",
}


def _phrase_present(text: str, phrase: str) -> bool:
    return bool(
        re.search(rf"(?<!\w){re.escape(phrase.casefold())}(?!\w)", text.casefold())
    )


def _present_terms(text: str, terms) -> tuple[str, ...]:
    return tuple(term for term in terms if _phrase_present(text, term))


def _clean_bounded_search_query(value: str) -> str:
    """Remove only terminal, bounded courtesy adjuncts from search data."""

    query = value.strip()
    while query:
        if query.casefold().rstrip(" ?.! ") in _EXACT_SEARCH_COURTESY_QUERIES:
            break
        courtesy = _TRAILING_SEARCH_COURTESY.search(query)
        if courtesy is None:
            break
        cleaned = query[: courtesy.start()].strip()
        # A courtesy token can itself be the requested lookup.  Remove it
        # only when substantive query text already precedes the suffix.
        if re.search(r"[^\W_]", cleaned, re.UNICODE) is None:
            break
        query = cleaned
    return query.rstrip(" ?.! ").strip()


def _extract_auth_followup_code(text: str) -> str | None:
    """Extract only tightly framed, credential-shaped OAuth follow-ups."""

    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    match = _OAUTH_REDIRECT_CODE.search(cleaned)
    if match is None:
        match = _BARE_OAUTH_CODE.search(cleaned)
    if match is None:
        match = _EXPLICIT_AUTH_FOLLOWUP.search(cleaned)
    if match is None:
        match = _NATURAL_AUTH_FOLLOWUP.search(cleaned)
    if match is None:
        return None
    code = unquote(
        match.group("code").strip("`<>").rstrip(".,;!?")
    )
    if (
        not 6 <= len(code) <= 2048
        or any(character.isspace() for character in code)
        or code.casefold() in _RESERVED_CALENDAR_AUTH_CODES
    ):
        return None
    return code


def _pending_key(
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int | None,
    routing_context: RoutingContext | None,
) -> ConversationKey | None:
    if routing_context is not None:
        return routing_context.key
    if (
        channel_id is None
        or user_id is None
        or isinstance(channel_id, bool)
        or not isinstance(channel_id, int)
        or isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or (
            guild_id is not None
            and (
                isinstance(guild_id, bool)
                or not isinstance(guild_id, int)
            )
        )
    ):
        return None
    return ConversationKey(guild_id, channel_id, user_id)


class IntentRouter:
    """Routes cleaned, authorized message text to one concrete bot intent."""

    def __init__(
        self,
        monitor,
        metrics: NLUMetrics | None = None,
        pending_actions: PendingActionStore | None = None,
        calendar_fact_checks: CalendarFactCheckStore | None = None,
        *,
        temporal_resolver: TemporalResolver | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.monitor = monitor
        self.metrics = metrics if metrics is not None else NLUMetrics()
        self.pending_actions = pending_actions
        self.calendar_fact_checks = calendar_fact_checks
        inherited_resolver = getattr(
            getattr(monitor, "nlp_parser", None),
            "temporal_resolver",
            None,
        )
        self.temporal_resolver = (
            temporal_resolver or inherited_resolver or TemporalResolver()
        )
        self._now_provider = now_provider or (lambda: datetime.now(OSLO))

    def route(
        self,
        content: str,
        guild_id: Optional[int] = None,
        *,
        channel_id: int | None = None,
        user_id: int | None = None,
        routing_context: RoutingContext | None = None,
        reference_time: datetime | None = None,
    ) -> IntentResult:
        return self.route_utterance(
            normalize_utterance(content),
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            routing_context=routing_context,
            reference_time=reference_time,
        )

    def route_utterance(
        self,
        utterance: NormalizedUtterance,
        guild_id: int | None = None,
        *,
        channel_id: int | None = None,
        user_id: int | None = None,
        routing_context: RoutingContext | None = None,
        reference_time: datetime | None = None,
    ) -> IntentResult:
        return self.evaluate_utterance(
            utterance,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            routing_context=routing_context,
            reference_time=reference_time,
        ).result

    def evaluate_utterance(
        self,
        utterance: NormalizedUtterance,
        guild_id: int | None = None,
        *,
        channel_id: int | None = None,
        user_id: int | None = None,
        routing_context: RoutingContext | None = None,
        reference_time: datetime | None = None,
        _sequence_probe: bool = False,
    ) -> RoutedIntent:
        captured = (
            reference_time
            if reference_time is not None
            else self._now_provider()
        )
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("routing_reference_must_be_aware")
        captured = captured.astimezone(OSLO)

        if routing_context is not None:
            key = routing_context.key
            mismatch = (
                (guild_id is not None and guild_id != key.guild_id)
                or (
                    channel_id is not None
                    and channel_id != key.channel_id
                )
                or (user_id is not None and user_id != key.user_id)
            )
            if mismatch:
                self.metrics.record_rejection(RejectionCode.INVALID_CONTEXT)
                return RoutedIntent(
                    IntentResult(
                        BotIntent.AI_CHAT, 0.2, {}, "invalid_context"
                    ),
                    RouteDiagnostics(
                        rejection_counts={
                            RejectionCode.INVALID_CONTEXT: 1
                        }
                    ),
                )
            guild_id = key.guild_id
            channel_id = key.channel_id
            user_id = key.user_id

        semantics = analyze_utterance(utterance)
        context = CollectorContext(
            utterance=utterance,
            semantics=semantics,
            routing=routing_context,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            reference_time=captured,
        )
        sequence_semantics_allowed = (
            semantics.speech_act not in {SpeechAct.META, SpeechAct.REJECTION}
        )
        if sequence_semantics_allowed and (
            (
                semantics.speech_act is not SpeechAct.HYPOTHETICAL
                and "negated_action" not in semantics.reasons
                and has_sequenced_action_request(utterance)
            )
            or (
                not _sequence_probe
                and self._has_parser_routed_sequence(context)
            )
        ):
            # The dispatch contract cannot atomically execute multiple
            # user-visible actions.  Clarify before credentials or collectors
            # can select or stage only the first clause; the model bridge
            # enforces the same rule without credential-shaped input.
            self.metrics.record_rejection(RejectionCode.CONFLICT)
            return RoutedIntent(
                IntentResult(
                    BotIntent.CLARIFY,
                    1.0,
                    {
                        "clarification": (
                            "Jeg ser flere handlinger i samme melding. "
                            "Send én handling om gangen, så unngår vi at "
                            "bare deler av forespørselen blir utført."
                        )
                    },
                    "multiple_actions_require_split",
                    risk=IntentRisk.READ_ONLY,
                    requires_confirmation=False,
                ),
                RouteDiagnostics(
                    rejection_counts={RejectionCode.CONFLICT: 1}
                ),
            )

        if has_unsupported_poll_mutation_request(utterance):
            self.metrics.record_rejection(RejectionCode.INVALID_CONTEXT)
            return RoutedIntent(
                IntentResult(
                    BotIntent.CLARIFY,
                    1.0,
                    {
                        "clarification": (
                            "Jeg kan bare lukke eller slette én avstemning "
                            "med én gang. Oppgi én avstemning uten "
                            "tidsforsinkelse, vilkår eller ekstra tekst."
                        )
                    },
                    "unsupported_poll_mutation_modifier",
                    risk=IntentRisk.READ_ONLY,
                    requires_confirmation=False,
                ),
                RouteDiagnostics(
                    rejection_counts={RejectionCode.INVALID_CONTEXT: 1}
                ),
            )

        credential_code = _extract_auth_followup_code(utterance.text)
        if credential_code is not None:
            explicit_auth = _EXPLICIT_AUTH_FOLLOWUP.search(
                utterance.text
            ) is not None
            if explicit_auth or self._matches_active_calendar_auth_flow(
                context
            ):
                return RoutedIntent(
                    IntentResult(
                        BotIntent.CALENDAR_AUTH,
                        0.99,
                        {"auth_code": credential_code},
                        (
                            "calendar_auth_keyword"
                            if explicit_auth
                            else "calendar_auth_scoped_followup"
                        ),
                        risk=IntentRisk.MUTATING,
                        requires_confirmation=True,
                    )
                )
            return RoutedIntent(
                IntentResult(
                    BotIntent.CLARIFY,
                    1.0,
                    {
                        "clarification": (
                            "Jeg sender ikke en mulig påloggingskode til "
                            "chatmodellen. Start Google Calendar-pålogging "
                            "i denne kanalen og prøv igjen."
                        )
                    },
                    "credential_shaped_input_blocked",
                    risk=IntentRisk.READ_ONLY,
                )
            )

        pending = self._pending_result(
            utterance,
            _pending_key(
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=user_id,
                routing_context=routing_context,
            ),
        )
        if pending is not None:
            return RoutedIntent(pending)

        fact_check_key = _pending_key(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            routing_context=routing_context,
        )
        if self.calendar_fact_checks is not None and fact_check_key is not None:
            lookup = self.calendar_fact_checks.lookup(fact_check_key)
            continuation = parse_fact_check_continuation(
                utterance.text,
                lookup.inquiry,
                expired=lookup.expired,
                temporal_resolver=self.temporal_resolver,
                reference_time=captured,
            )
            if continuation is not None:
                if continuation.kind == "expired":
                    return RoutedIntent(IntentResult(
                        BotIntent.CLARIFY,
                        1.0,
                        {"clarification": "Faktasjekken er utløpt. Start på nytt."},
                        "calendar_fact_check_expired",
                    ))
                if continuation.clarification is not None:
                    return RoutedIntent(IntentResult(
                        BotIntent.CLARIFY,
                        1.0,
                        {"clarification": continuation.clarification},
                        "calendar_fact_check_clarify",
                    ))
                if continuation.kind == "direct":
                    assert lookup.inquiry is not None
                    target = lookup.inquiry.targets[0]
                    try:
                        self.monitor.pending_targets.revalidate_calendar_fact_check_target(
                            target,
                            reference_time=captured,
                        )
                    except PendingTargetError:
                        self.calendar_fact_checks.cancel(fact_check_key)
                        return RoutedIntent(IntentResult(
                            BotIntent.CLARIFY,
                            1.0,
                            {"clarification": "Kalenderoppføringen har endret seg; start på nytt."},
                            "calendar_fact_check_stale",
                        ))
                    assert continuation.changes is not None
                    return RoutedIntent(IntentResult(
                        BotIntent.CALENDAR_EDIT,
                        1.0,
                        {"calendar_edit": {
                            "target": target.stable_id,
                            "changes": dict(continuation.changes),
                        }},
                        "calendar_fact_check_direct_edit",
                        risk=IntentRisk.MUTATING,
                        requires_confirmation=True,
                    ))
                payload = (
                    {"action": "select", "number": continuation.number}
                    if continuation.kind == "select"
                    else (
                        {"action": "cancel"}
                        if continuation.kind == "cancel"
                        else {
                            "action": "search",
                            "field": "schedule",
                            "target": lookup.inquiry.targets[0].stable_id,
                        }
                    )
                )
                return RoutedIntent(IntentResult(
                    BotIntent.CALENDAR_FACT_CHECK,
                    1.0,
                    {"calendar_fact_check": payload},
                    f"calendar_fact_check_{continuation.kind}",
                    risk=IntentRisk.READ_ONLY,
                ))

        candidates: list[IntentCandidate] = []
        parser_errors: list[str] = []
        collector_rejections: list[CandidateRejection] = []
        for method_name in COLLECTOR_ORDER:
            output = getattr(self, method_name)(context)
            candidates.extend(output.candidates)
            parser_errors.extend(output.parser_errors)
            collector_rejections.extend(output.rejections)

        candidates, payload_rejections = self._validate_action_candidates(
            candidates
        )
        collector_rejections.extend(payload_rejections)

        decision = arbitrate_candidates(
            utterance, semantics, candidates
        )
        all_rejections = (
            tuple(collector_rejections) + decision.rejected
        )
        counts = Counter(
            rejection.code for rejection in all_rejections
        )
        for rejection in all_rejections:
            self.metrics.record_rejection(rejection.code)

        if decision.selected is not None:
            if (
                decision.selected.intent is BotIntent.CLARIFY
                and decision.alternatives
            ):
                result = IntentResult(
                    BotIntent.CLARIFY,
                    decision.selected.confidence,
                    {
                        "clarification": (
                            "Jeg ser to mulige tolkninger. Hvilken mener du?"
                        ),
                        "choices": tuple(
                            candidate.to_result()
                            for candidate in decision.alternatives
                        ),
                    },
                    decision.selected.reason,
                    source=decision.selected.source,
                    risk=IntentRisk.READ_ONLY,
                )
            else:
                result = decision.selected.to_result()
        else:
            result = IntentResult(
                BotIntent.AI_CHAT,
                0.2 if decision.blocked else 0.5,
                {},
                (
                    "unsafe_mutation_blocked"
                    if decision.blocked
                    else "fallback"
                ),
            )
        return RoutedIntent(
            result,
            RouteDiagnostics(
                parser_errors=tuple(parser_errors),
                rejection_counts=dict(
                    sorted(
                        counts.items(),
                        key=lambda item: item[0].value,
                    )
                ),
            ),
        )

    def _has_parser_routed_sequence(
        self,
        context: CollectorContext,
    ) -> bool:
        """Fail closed when a write is followed by another routed request.

        The lexical grammar catches common forms before any parser work.  This
        bounded fallback uses the same production collectors and live routing
        fixture to cover valid natural paraphrases without maintaining a
        second exhaustive verb list.  Probes have isolated metrics, ignore
        pending-action state, and never dispatch or persist anything.
        """

        sequence_surface = strip_bounded_request_courtesy(
            context.utterance.control_text
        )
        pairs = sequenced_clause_candidates(
            normalize_utterance(sequence_surface)
        )
        if not pairs:
            return False
        probe = IntentRouter(
            self.monitor,
            metrics=NLUMetrics(),
            pending_actions=None,
            temporal_resolver=self.temporal_resolver,
            now_provider=lambda: context.reference_time,
        )
        route_kwargs = {
            "guild_id": context.guild_id,
            "channel_id": context.channel_id,
            "user_id": context.user_id,
            "routing_context": context.routing,
            "reference_time": context.reference_time,
            "_sequence_probe": True,
        }
        overflow = len(pairs) > MAX_SEQUENCE_CLAUSE_PROBES
        for index, (left, right) in enumerate(
            pairs[:MAX_SEQUENCE_CLAUSE_PROBES]
        ):
            left_result = probe.evaluate_utterance(
                normalize_utterance(left),
                **route_kwargs,
            ).result
            if left_result.risk is IntentRisk.READ_ONLY:
                continue
            if overflow and index == 0:
                return True
            right_result = probe.evaluate_utterance(
                normalize_utterance(right),
                **route_kwargs,
            ).result
            if right_result.intent is not BotIntent.AI_CHAT:
                return True
            right_utterance = normalize_utterance(right)
            if is_standalone_action_retraction(right_utterance):
                continue
            if is_independent_conversational_request(right_utterance):
                return True
        return False

    @property
    def now_provider(self) -> Callable[[], datetime]:
        return self._now_provider

    def _pending_result(
        self,
        utterance: NormalizedUtterance,
        key: ConversationKey | None,
    ) -> IntentResult | None:
        if self.pending_actions is None or key is None:
            return None
        resolution = self.pending_actions.resolve(key, utterance.text)
        if resolution.kind is PendingResolutionKind.NONE:
            return None
        if resolution.kind is PendingResolutionKind.EXPIRED:
            return IntentResult(
                BotIntent.CLARIFY,
                1.0,
                {
                    "clarification": (
                        "Den forrige bekreftelsen er utløpt. "
                        "Be meg om handlingen på nytt."
                    )
                },
                "pending_expired",
                risk=IntentRisk.READ_ONLY,
            )
        if not isinstance(resolution.action_id, str):
            return None

        pending: dict[str, object] = {
            "action_id": resolution.action_id,
        }
        mapping = {
            PendingResolutionKind.CONFIRM: BotIntent.ACTION_CONFIRM,
            PendingResolutionKind.CANCEL: BotIntent.ACTION_CANCEL,
            PendingResolutionKind.SELECT: BotIntent.ACTION_SELECT,
            PendingResolutionKind.CORRECT: BotIntent.ACTION_CORRECT,
        }
        intent = mapping.get(resolution.kind)
        if intent is None:
            return None
        if resolution.kind is PendingResolutionKind.SELECT:
            if (
                isinstance(resolution.choice_index, bool)
                or not isinstance(resolution.choice_index, int)
            ):
                return None
            pending["choice_index"] = resolution.choice_index
        if resolution.kind is PendingResolutionKind.CORRECT:
            pending["correction_text"] = utterance.text
        return IntentResult(
            intent,
            1.0,
            {"pending": pending},
            f"pending_{resolution.kind.value}",
            risk=IntentRisk.READ_ONLY,
        )

    def _validate_action_candidates(
        self, candidates: list[IntentCandidate]
    ) -> tuple[list[IntentCandidate], list[CandidateRejection]]:
        """Canonicalize every typed action candidate before arbitration."""

        valid: list[IntentCandidate] = []
        rejected: list[CandidateRejection] = []
        invalid_payloads: list[tuple[BotIntent, dict[str, Any]]] = []
        for candidate in candidates:
            envelope = ENVELOPE_KEYS.get(candidate.intent)
            if envelope is None:
                valid.append(candidate)
                continue
            if (
                candidate.intent is BotIntent.CALENDAR_LIST
                and candidate.payload == {}
            ):
                # Preserve the long-standing unfiltered read contract while
                # filtered reads use the new canonical typed envelope.
                valid.append(candidate)
                continue
            try:
                if set(candidate.payload) != {envelope}:
                    raise PayloadValidationError("missing_payload")
                raw = candidate.payload[envelope]
                if not isinstance(raw, Mapping):
                    raise PayloadValidationError("missing_payload")
                normalized = validate_intent_payload(
                    candidate.intent,
                    raw,
                    source=candidate.source,
                )
            except (PayloadValidationError, TypeError, ValueError):
                duplicate = False
                for seen_intent, seen_payload in invalid_payloads:
                    if seen_intent is not candidate.intent:
                        continue
                    try:
                        same_payload = seen_payload == candidate.payload
                        duplicate = (
                            same_payload
                            if type(same_payload) is bool
                            else False
                        )
                    except Exception:
                        duplicate = False
                    if duplicate:
                        break
                if duplicate:
                    continue
                invalid_payloads.append((candidate.intent, candidate.payload))
                rejected.append(
                    CandidateRejection(candidate, RejectionCode.PARSER_ERROR)
                )
                self.metrics.record_parser_error(
                    _PAYLOAD_METRIC_FAMILY[candidate.intent],
                    "invalid_payload",
                )
                continue
            payload = {envelope: normalized}
            valid.append(
                replace(
                    candidate,
                    payload=payload,
                    risk=classify_intent_risk(candidate.intent, payload),
                )
            )
        return valid, rejected

    def _safe_parse(
        self,
        errors,
        rejections,
        parser_name,
        metric_family,
        fn,
        *args,
        **kwargs,
    ):
        if parser_name not in _PARSER_NAMES:
            raise ValueError("unknown_parser_name")
        if _PARSER_METRIC_FAMILY.get(parser_name) != metric_family:
            raise ValueError("invalid_parser_metric_family")
        try:
            return fn(*args, **kwargs)
        except Exception:
            errors.append(parser_name)
            rejections.append(
                CandidateRejection(
                    IntentCandidate(
                        BotIntent.AI_CHAT,
                        0.0,
                        90,
                        order=389,
                        payload={},
                        reason="parser_error_diagnostic",
                        source=IntentSource.DETERMINISTIC,
                        risk=IntentRisk.READ_ONLY,
                        specificity=0,
                    ),
                    RejectionCode.PARSER_ERROR,
                )
            )
            self.metrics.record_parser_error(
                metric_family, "exception"
            )
            return None

    def _candidate_from_result(
        self,
        result,
        *,
        tier,
        order,
        specificity,
        action_terms=(),
        domain_terms=(),
        source=IntentSource.DETERMINISTIC,
    ):
        return IntentCandidate(
            result.intent,
            result.confidence,
            tier,
            order=order,
            payload=dict(result.payload),
            reason=result.reason,
            source=source,
            risk=classify_intent_risk(
                result.intent, result.payload
            ),
            action_terms=tuple(action_terms),
            domain_terms=tuple(domain_terms),
            specificity=specificity,
        )

    def _append_invalid_temporal(
        self,
        rejections: list[CandidateRejection],
        *,
        intent: BotIntent = BotIntent.CALENDAR_ITEM,
        tier: int = 40,
        order: int = 130,
        reason: str = "calendar_temporal_invalid",
    ) -> None:
        rejections.append(
            CandidateRejection(
                IntentCandidate(
                    intent,
                    0.0,
                    tier,
                    order=order,
                    payload={},
                    reason=reason,
                    source=IntentSource.DETERMINISTIC,
                    risk=classify_intent_risk(intent, {}),
                    specificity=0,
                ),
                RejectionCode.INVALID_TEMPORAL,
            )
        )
        self.metrics.record_parser_error(
            "calendar", "invalid_temporal"
        )

    def _append_invalid_payload(
        self,
        rejections: list[CandidateRejection],
        *,
        intent: BotIntent,
        family: str,
        tier: int,
        order: int,
    ) -> None:
        """Record one bounded diagnostic without retaining parser data."""

        rejections.append(
            CandidateRejection(
                IntentCandidate(
                    intent,
                    0.0,
                    tier,
                    order=order,
                    payload={},
                    reason="invalid_payload_diagnostic",
                    source=IntentSource.DETERMINISTIC,
                    risk=classify_intent_risk(intent, {}),
                    specificity=0,
                ),
                RejectionCode.PARSER_ERROR,
            )
        )
        self.metrics.record_parser_error(family, "invalid_payload")

    def _collect_control_candidates(
        self, context: CollectorContext
    ) -> CollectorOutput:
        control = context.utterance.control_text.strip()
        text = context.utterance.text
        candidates: list[IntentCandidate] = []
        errors: list[str] = []
        rejections: list[CandidateRejection] = []

        if re.fullmatch(
            r"(?:(?:kalender|calendar|gcal)\s+(?:hjelp|help|guide)|"
            r"(?:hjelp|help|guide)\s+(?:med|with)\s+"
            r"(?:kalender(?:en)?|calendar|gcal))\s*[?.!]*",
            control,
            re.I,
        ):
            result = IntentResult(
                BotIntent.CALENDAR_HELP,
                0.99,
                reason="calendar_help_keyword",
            )
            candidates.append(
                self._candidate_from_result(
                    result,
                    tier=10,
                    order=10,
                    specificity=4,
                    domain_terms=_present_terms(
                        control, ("kalender", "calendar", "gcal")
                    ),
                )
            )

        if self._is_status_command(control):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.STATUS,
                        0.99,
                        reason="status_keyword",
                    ),
                    tier=10,
                    order=20,
                    specificity=4,
                    domain_terms=_present_terms(
                        control,
                        ("status", "health", "helse", "diagnose"),
                    ),
                )
            )

        simple_help = (
            "hjelp",
            "help",
            "kommandoer",
            "commands",
            "funksjoner",
            "features",
            "capabilities",
            "hva er du",
            "hvem er du",
        )
        simple_help_control = control.strip(" .!?")
        natural_help_request = re.fullmatch(
            r"(?:show|vis|vise)\s+(?:(?:me|meg|mæ)\s+)?"
            r"(?:(?:your|dine)\s+)?(?:commands|kommandoer)",
            simple_help_control,
            re.I,
        )
        if simple_help_control in simple_help or natural_help_request:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.HELP,
                        0.96,
                        reason="help_keyword",
                    ),
                    tier=10,
                    order=30,
                    specificity=4,
                    domain_terms=_present_terms(control, simple_help),
                )
            )

        capability = CAPABILITY_HELP.fullmatch(control)
        if capability:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.HELP,
                        0.96,
                        reason="capability_help_natural",
                    ),
                    tier=10,
                    order=31,
                    specificity=2,
                    action_terms=_present_terms(control, ("kan", "can")),
                    domain_terms=_present_terms(
                        control, ("gjøre", "gjere", "gjør", "do")
                    ),
                )
            )

        if self._is_profile_command(control, text):
            parser = getattr(self.monitor, "parse_profile_command", None)
            if parser is None:
                from features.profile_commands import (
                    parse_profile_command as parser,
                )
            parsed_profile = self._safe_parse(
                errors,
                rejections,
                "parse_profile_command",
                "profile",
                parser,
                text,
            )
            if isinstance(parsed_profile, dict):
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.PROFILE,
                            0.95,
                            {"profile": parsed_profile},
                            "profile_command",
                        ),
                        tier=10,
                        order=40,
                        specificity=3,
                        action_terms=_present_terms(
                            control,
                            (
                                "status",
                                "spiller",
                                "playing",
                                "ser på",
                                "watching",
                                "sett",
                                "sette",
                                "set",
                            ),
                        ),
                        domain_terms=_present_terms(
                            control,
                            (
                                "status",
                                "online",
                                "offline",
                                "idle",
                                "dnd",
                                "invisible",
                                "spiller",
                                "playing",
                                "ser på",
                                "watching",
                                "aktivitet",
                                "aktiviteten",
                                "activity",
                            ),
                        ),
                    )
                )
            elif parsed_profile is not None:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.PROFILE,
                    family="profile",
                    tier=10,
                    order=40,
                )

        memory_result = self._route_memory_command(control)
        if memory_result is not None:
            mapping = {
                BotIntent.MEMORY_DELETE: (50, 4),
                BotIntent.MEMORY_EXPORT: (51, 4),
                BotIntent.MEMORY_VIEW: (52, 4),
            }
            order, specificity = mapping[memory_result.intent]
            candidates.append(
                self._candidate_from_result(
                    memory_result,
                    tier=10,
                    order=order,
                    specificity=specificity,
                    action_terms=_present_terms(
                        control,
                        (
                            "slett",
                            "slette",
                            "delete",
                            "glem",
                            "glemme",
                            "gløym",
                            "gløyme",
                            "forget",
                        ),
                    ),
                    domain_terms=_present_terms(
                        control,
                        (
                            "minne",
                            "minnet",
                            "memory",
                            "brukerminne",
                            "glem meg",
                            "glemme meg",
                            "gløym meg",
                            "gløyme meg",
                            "forget me",
                        ),
                    ),
                )
            )
        return CollectorOutput(
            candidates=tuple(candidates),
            parser_errors=tuple(errors),
            rejections=tuple(rejections),
        )

    def _collect_calendar_reminder_candidates(
        self, context: CollectorContext
    ) -> CollectorOutput:
        control = context.utterance.control_text.strip()
        text = context.utterance.text
        candidates: list[IntentCandidate] = []
        errors: list[str] = []
        rejections: list[CandidateRejection] = []

        fact_check_target = parse_schedule_concern(
            context.utterance,
            context.semantics,
        )
        if fact_check_target is not None:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CALENDAR_FACT_CHECK,
                        0.99,
                        {
                            "calendar_fact_check": {
                                "action": "start",
                                "field": "schedule",
                                "target": fact_check_target,
                            }
                        },
                        "calendar_fact_check_concern",
                    ),
                    tier=30,
                    order=118,
                    specificity=3,
                    action_terms=("schedule_concern",),
                    domain_terms=("calendar",),
                )
            )

        local_search_gate = bool(
            _BOUNDED_BARE_SEARCH_REQUEST.fullmatch(control)
            or re.match(
                r"^(?:søk|search)\s+(?:påminnelse|påminnelser|påminning|"
                r"påminningar|reminder|reminders|kalender|calendar|på nett|"
                r"(?:the )?web)\b",
                control,
                re.I,
            )
            or re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?:søk|søke|search)\s+"
                r"(?:i|in)\s+(?:kalenderen|calendar)\s+"
                r"(?:etter|for)\s+.+?\s*\??|"
                r"(?:finn|find)\s+(?:påminnelsen|påminninga|"
                r"the\s+reminder|reminder)\s+(?:om|about)\s+.+?\s*\??",
                control,
                re.I,
            )
            or re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?:søk|søke|søkje|search|"
                r"look\s+up)\s+(?:på\s+nett(?:et)?|"
                r"(?:the\s+)?web)\s+(?:etter|for)\s+.+?\s*[?.!]*",
                control,
                re.I,
            )
        )
        if local_search_gate:
            local_search = self._route_local_search_command(text)
            if local_search is not None:
                search_order = {
                    BotIntent.REMINDER_SEARCH: 80,
                    BotIntent.CALENDAR_SEARCH: 81,
                    BotIntent.SEARCH: 82,
                }[local_search.intent]
                candidates.append(
                    self._candidate_from_result(
                        local_search,
                        tier=30,
                        order=search_order,
                        specificity=3,
                        action_terms=_present_terms(
                            control,
                            ("søk", "søke", "søkje", "search", "look up"),
                        ),
                        domain_terms=_present_terms(
                            control,
                            (
                                "påminnelse",
                                "påminnelser",
                                "reminder",
                                "reminders",
                                "kalender",
                                "calendar",
                                "nett",
                                "web",
                            ),
                        ),
                    )
                )

        bare_search = re.match(
            r"^(?:søk|search)\s+(?:(?:etter|for)\s+)?(.+)$",
            control,
            re.I,
        )
        if bare_search and not local_search_gate:
            local_search = self._route_local_search_command(text)
            if local_search is not None:
                candidates.append(
                    self._candidate_from_result(
                        local_search,
                        tier=30,
                        order=83,
                        specificity=3,
                        action_terms=_present_terms(
                            control, ("søk", "search")
                        ),
                        domain_terms=(bare_search.group(1),),
                    )
                )

        date_filtered_reminder_read = (
            filtered_list_read_family(control) == "reminder"
        )
        if date_filtered_reminder_read:
            date_filter = _resolve_single_date_read_filter(
                self.temporal_resolver,
                control,
                reference_time=context.reference_time,
            )
            if date_filter is not None:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.REMINDER_LIST,
                            0.98,
                            {
                                "reminder": {
                                    "action": "list",
                                    "due_date": date_filter,
                                }
                            },
                            "reminder_list_date_filtered",
                        ),
                        tier=30,
                        order=92,
                        specificity=3,
                        action_terms=_present_terms(
                            control,
                            ("vis", "vise", "show", "list", "har", "have"),
                        ),
                        domain_terms=_present_terms(
                            control,
                            (
                                "påminnelser",
                                "påminningar",
                                "påminnelsene",
                                "påminningane",
                                "reminders",
                                "huske",
                                "hugse",
                                "remember",
                            ),
                        ),
                    )
                )

        reminder_gate = bool(
            bounded_english_reminder_create_head(context.utterance)
            or re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:"
                r"(?:i['’]d|i\s+would)\s+like\s+(?:a\s+)?reminder"
                r"(?:\s+for\s+me)?\s+to|"
                r"påminn(?:e)?\s+meg|minn(?:e)?\s+(?:meg|mæ)|husk\s+(?:å|at)|"
                r"hugs\s+(?:å|at)|ikke\s+glem\s+(?:å|at)|"
                r"(?:jeg|eg|æ)\s+må\s+(?:huske|hugse)\s+(?:å|at)|"
                r"(?:pass\s+på|syt\s+for)\s+at|"
                r"make\s+sure(?:\s+that)?\s+i(?:\s+remember\s+to)?|"
                r"ikkje\s+gløym\s+(?:å|at)|"
                r"ikkje\s+lat\s+meg\s+gløyme\s+(?:å|at)|"
                r"ikke\s+la\s+meg\s+glemme\s+(?:å|at)|"
                r"(?:don't|don’t)\s+(?:let\s+me\s+)?forget\s+(?:to|that)|"
                r"remind\s+me|(?:i\s+need\s+to\s+)?remember\s+to|"
                r"(?:(?:opprett|opprette|lag|lage|"
                r"(?:legg|legge)\s+(?:inn|til)|(?:sette|setje)\s+opp|"
                r"planlegg|planlegge|planleggje)\s+"
                r"(?:(?:en|ei|et|a)\s+)?(?:påminnelse|påminning|reminder|"
                r"gjøremål|gjeremål|todo)|"
                r"(?:create|add|make|set|put|set\s+up)\s+"
                r"(?:a\s+)?reminder(?:\s+for\s+me)?\s+(?:to|about)|"
                r"(?:endre|rediger|redigere|edit|slett|slette|fjern|fjerne|"
                r"delete|remove|ferdig|fullfør|fullføre|fullført|done|"
                r"complete|gjort|marker|markere|mark)\s+"
                r"(?:the\s+)?(?:påminnelse|påminnelsen|påminning|"
                r"påminninga|reminder))|"
                r"(?:vis|list|show|søk|search)?\s*"
                r"(?:påminnelser|påminningar|reminders|gjøremål|todos|"
                r"huskeliste)|(?:påminnelse|påminning|reminder|gjøremål|todo)\b)",
                control,
                re.I,
            )
            or re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?:vis|vise|list|show)\s+"
                r"(?:(?:meg|mæ|me)\s+)?(?:(?:alle|all)\s+)?(?:påminnelsene\s+mine|"
                r"påminningane\s+mine|my\s+reminders)\s*\??|"
                r"how\s+many\s+reminders\s+do\s+i\s+have\s*\??|"
                r"what\s+reminders\s+do\s+i\s+have\s*\??|"
                r"what\s+do\s+i\s+need\s+to\s+remember\s*\??|"
                r"(?:is\s+there\s+)?anything\s+i\s+need\s+to\s+remember\s*\??|"
                r"do\s+i\s+have\s+any\s+reminders\s*\??|"
                r"any\s+reminders\s+for\s+me\s*\??|"
                r"can\s+i\s+see\s+my\s+reminders\s*\??|"
                r"could\s+i\s+see\s+my\s+reminders\s*\??|"
                r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
                r"(?:påminnelsene|påminningane)\s+mine\s*\??|"
                r"(?:hva|kva|ka)\s+må\s+(?:jeg|eg|æ)\s+"
                r"(?:huske|hugse)\s*\??|"
                r"(?:hva|kva|ka)\s+står\s+på\s+"
                r"(?:huskelista|hugselista)\s*\??|"
                r"har\s+(?:jeg|eg|æ)\s+(?:noen|nokon)\s+"
                r"(?:påminnelser|påminningar)\s*\??|"
                r"(?:finn|find)\s+(?:påminnelsen|påminninga|"
                r"the\s+reminder|reminder)\s+(?:om|about)\s+.+?\s*\??",
                control,
                re.I,
            )
        )
        parsed_reminder = None
        ambiguous_english_reminder_time = bool(
            reminder_gate
            and _ENGLISH_BARE_CLOCK_TIME.search(control)
            and _ENGLISH_REMINDER_TIME_FRAME.search(control)
        )
        if ambiguous_english_reminder_time:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        0.99,
                        {
                            "clarification": (
                                "Mener du om morgenen eller ettermiddagen? "
                                "Oppgi AM eller PM."
                            )
                        },
                        "reminder_english_time_ambiguous",
                    ),
                    tier=30,
                    order=91,
                    specificity=3,
                    domain_terms=("at",),
                )
            )
        elif reminder_gate:
            parser = getattr(
                self.monitor, "parse_reminder_command", None
            )
            if parser is None:
                from cal_system.reminder_manager import (
                    parse_reminder_command as parser,
                )
            parsed_reminder = self._safe_parse(
                errors,
                rejections,
                "parse_reminder_command",
                "reminder",
                parser,
                text,
                now=context.reference_time,
                temporal_resolver=self.temporal_resolver,
            )
        if parsed_reminder is not None and not isinstance(parsed_reminder, dict):
            self._append_invalid_payload(
                rejections,
                intent=BotIntent.REMINDER_CREATE,
                family="reminder",
                tier=30,
                order=94,
            )
            parsed_reminder = None

        half_clock_errors: tuple[str, ...] = ()
        if (
            reminder_gate
            and parsed_reminder is None
            and re.search(
                r"\b(?:(?:kl(?:okka|okken)?\.?)\s+)?halv\b",
                control,
                re.I,
            )
        ):
            half_clock_errors = self.temporal_resolver.resolve(
                control,
                reference=context.reference_time,
            ).errors
        ambiguous_half_clock = half_clock_errors == ("ambiguous_time",)
        if ambiguous_half_clock:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        0.99,
                        {
                            "clarification": (
                                "Mener du halv tre om morgenen eller "
                                "halv tre på ettermiddagen?"
                            )
                        },
                        "reminder_half_clock_ambiguous",
                    ),
                    tier=30,
                    order=92,
                    specificity=3,
                    action_terms=_present_terms(
                        control,
                        ("påminn", "påminne", "minn", "minne", "husk"),
                    ),
                    domain_terms=("halv",),
                )
            )

        explicit_reminder_list = (
            unfiltered_list_read_family(control) == "reminder"
        ) or re.fullmatch(
            r"(?:(?:vis|list|show)\s+)?(?:påminnelser|påminningar|"
            r"reminders|gjøremål|todos|huskeliste)\s*\??|"
            r"(?:show\s+me\s+(?:all\s+)?my\s+reminders|"
            r"how\s+many\s+reminders\s+do\s+i\s+have|"
            r"what\s+do\s+i\s+need\s+to\s+remember|"
            r"(?:is\s+there\s+)?anything\s+i\s+need\s+to\s+remember|"
            r"do\s+i\s+have\s+any\s+reminders|"
            r"any\s+reminders\s+for\s+me|"
            r"can\s+i\s+see\s+my\s+reminders|"
            r"could\s+i\s+see\s+my\s+reminders|"
            r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
            r"(?:påminnelsene|påminningane)\s+mine|"
            r"(?:hva|kva|ka)\s+må\s+(?:jeg|eg|æ)\s+(?:huske|hugse)|"
            r"(?:hva|kva|ka)\s+står\s+på\s+(?:huskelista|hugselista)|"
            r"har\s+(?:jeg|eg|æ)\s+(?:noen|nokon)\s+"
            r"(?:påminnelser|påminningar)|"
            r"vis\s+(?:meg|mæ)\s+(?:påminnelsene|påminningane))\s*\??|"
            r"(?:fortell|fortel)\s+(?:meg|mæ)\s+om\s+"
            r"(?:påminnelsene|påminningane)\s+mine\s*\??|"
            r"tell\s+me\s+about\s+my\s+reminders\s*\??",
            control,
            re.I,
        )
        if explicit_reminder_list:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.REMINDER_LIST,
                        0.97,
                        {"reminder": {"action": "list"}},
                        "reminder_list_keyword",
                    ),
                    tier=30,
                    order=93,
                    specificity=2,
                    action_terms=_present_terms(
                        control,
                        (
                            "vis",
                            "list",
                            "show",
                            "check",
                            "sjekk",
                            "sjekke",
                            "har",
                            "have",
                        ),
                    ),
                    domain_terms=_present_terms(
                        control,
                        (
                            "påminnelser",
                            "påminningar",
                            "reminders",
                            "gjøremål",
                            "todos",
                            "huskeliste",
                        ),
                    ),
                )
            )

        if isinstance(parsed_reminder, dict):
            action = parsed_reminder.get("action")
            payload = {"reminder": dict(parsed_reminder)}
            action_terms = _present_terms(
                control,
                (
                    "påminn",
                    "påminne",
                    "minn",
                    "minne",
                    "husk",
                    "huske",
                    "hugs",
                    "hugse",
                    "glem",
                    "glemme",
                    "gløym",
                    "gløyme",
                    "forget",
                    "remind",
                    "remember",
                    "pass på",
                    "syt for",
                    "make sure",
                    "endre",
                    "rediger",
                    "redigere",
                    "edit",
                    "slett",
                    "slette",
                    "fjern",
                    "fjerne",
                    "delete",
                    "remove",
                    "ferdig",
                    "fullfør",
                    "fullføre",
                    "fullført",
                    "done",
                    "complete",
                    "gjort",
                    "marker",
                    "markere",
                    "mark",
                    "opprett",
                    "opprette",
                    "lag",
                    "lage",
                    "create",
                    "add",
                    "set up",
                    "vis",
                    "list",
                    "show",
                ),
            )
            domain_terms = _present_terms(
                control,
                (
                    "påminn meg",
                    "påminne meg",
                    "minn meg",
                    "minne meg",
                    "minn mæ",
                    "husk å",
                    "hugs å",
                    "ikke glem",
                    "ikkje gløym",
                    "ikkje lat meg gløyme",
                    "don't forget",
                    "don’t forget",
                    "remind me",
                    "remember to",
                    "påminnelse",
                    "påminnelsen",
                    "påminning",
                    "påminninga",
                    "påminnelser",
                    "påminningar",
                    "reminder",
                    "reminders",
                    "gjøremål",
                    "todos",
                    "huskeliste",
                ),
            )
            reminder_result = None
            tier = 30
            order = 94
            specificity = 2
            if (
                action == "add"
                and isinstance(parsed_reminder.get("text"), str)
                and parsed_reminder["text"].strip()
            ):
                reminder_result = IntentResult(
                    BotIntent.REMINDER_CREATE,
                    0.96,
                    payload,
                    "reminder_create_natural",
                )
                tier, order, specificity = 35, 122, 3
            elif (
                action == "edit"
                and bool(parsed_reminder.get("changes"))
                and (
                    (
                        isinstance(parsed_reminder.get("number"), int)
                        and parsed_reminder["number"] > 0
                    )
                    != bool(
                        isinstance(parsed_reminder.get("reminder_id"), str)
                        and parsed_reminder["reminder_id"].strip()
                    )
                )
            ):
                reminder_result = IntentResult(
                    BotIntent.REMINDER_EDIT,
                    0.98,
                    payload,
                    "reminder_edit_keyword",
                )
                tier, order, specificity = 20, 60, 3
            elif isinstance(action, str) and action in {"delete", "complete"}:
                complete_selector = (
                    (
                        isinstance(parsed_reminder.get("number"), int)
                        and parsed_reminder["number"] > 0
                    )
                    != bool(
                        isinstance(parsed_reminder.get("reminder_id"), str)
                        and parsed_reminder["reminder_id"].strip()
                    )
                )
                if complete_selector:
                    intent = (
                        BotIntent.REMINDER_DELETE
                        if action == "delete"
                        else BotIntent.REMINDER_COMPLETE
                    )
                    reason = (
                        "reminder_delete_keyword"
                        if action == "delete"
                        else "reminder_complete_keyword"
                    )
                    reminder_result = IntentResult(
                        intent, 0.98, payload, reason
                    )
                    tier = 20
                    order = 70 if action == "delete" else 90
                    specificity = 3
            elif action == "list":
                reminder_result = IntentResult(
                    BotIntent.REMINDER_LIST,
                    0.95,
                    payload,
                    "reminder_list_parser",
                )
                tier, order, specificity = 30, 94, 2
            elif (
                action == "search"
                and isinstance(parsed_reminder.get("query"), str)
                and parsed_reminder["query"].strip()
            ):
                reminder_result = IntentResult(
                    BotIntent.REMINDER_SEARCH,
                    0.98,
                    payload,
                    "reminder_search_keyword",
                )
                tier, order, specificity = 30, 80, 3
            if reminder_result is None:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.REMINDER_CREATE,
                    family="reminder",
                    tier=30,
                    order=94,
                )
            else:
                candidates.append(
                    self._candidate_from_result(
                        reminder_result,
                        tier=tier,
                        order=order,
                        specificity=specificity,
                        action_terms=action_terms,
                        domain_terms=domain_terms,
                    )
                )

        bare_number_has_reminders = bool(
            control.isdigit()
            and self._has_active_reminders(context.domain_scope_id)
        )
        bare_number_has_poll = bool(
            control.isdigit()
            and self._has_active_poll(
                context.domain_scope_id,
                context.reference_time,
            )
        )
        if bare_number_has_reminders and bare_number_has_poll:
            number = int(control)
            if number > 0:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CLARIFY,
                            1.0,
                            {
                                "clarification": (
                                    f"Mener du å stemme på alternativ {number} "
                                    f"eller fullføre påminnelse {number}? "
                                    "Skriv handlingen og området uttrykkelig."
                                )
                            },
                            "ambiguous_numeric_domain",
                        ),
                        tier=10,
                        order=24,
                        specificity=5,
                        domain_terms=(control,),
                    )
                )
        elif bare_number_has_reminders:
            number = int(control)
            if number > 0:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.REMINDER_COMPLETE,
                            0.94,
                            {
                                "reminder": {
                                    "action": "complete",
                                    "number": number,
                                }
                            },
                            "active_reminder_numeric_complete",
                        ),
                        tier=20,
                        order=91,
                        specificity=4,
                        domain_terms=(control,),
                    )
                )
        active_complete = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:(?:ferdig|fullført|fullfør|done|complete|gjort)\s+"
            r"(?P<prefix_number>\d+)|"
            r"(?:marker|markere|mark)\s+(?P<mark_number>\d+)\s+"
            r"(?:som\s+)?(?:ferdig|fullført|done|complete|completed))"
            r"\s*\??",
            control,
            re.I,
        )
        active_complete_number = (
            int(
                active_complete.group("prefix_number")
                or active_complete.group("mark_number")
            )
            if active_complete is not None
            else None
        )
        active_reminder_target = bool(
            active_complete
            and self._has_active_reminders(context.domain_scope_id)
        )
        active_calendar_target = bool(
            active_complete
            and active_complete_number is not None
            and self._has_calendar_target_number(
                active_complete_number,
                context.domain_scope_id,
                context.reference_time,
            )
        )
        if active_complete and active_reminder_target and active_calendar_target:
            assert active_complete_number is not None
            number = active_complete_number
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        1.0,
                        {
                            "clarification": (
                                f"Mener du kalenderoppføring {number} eller "
                                f"påminnelse {number}? Skriv for eksempel "
                                f"«kalender ferdig {number}» eller "
                                f"«ferdig påminnelse {number}»."
                            )
                        },
                        "ambiguous_completion_domain",
                    ),
                    tier=10,
                    order=25,
                    specificity=5,
                    action_terms=_present_terms(
                        control,
                        (
                            "ferdig",
                            "fullført",
                            "fullfør",
                            "done",
                            "complete",
                            "gjort",
                            "marker",
                            "markere",
                            "mark",
                        ),
                    ),
                    domain_terms=(str(number),),
                )
            )
        elif active_complete and active_reminder_target:
            assert active_complete_number is not None
            number = active_complete_number
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.REMINDER_COMPLETE,
                        0.94,
                        {
                            "reminder": {
                                "action": "complete",
                                "number": number,
                            }
                        },
                        "active_reminder_complete_number",
                    ),
                    tier=20,
                    order=92,
                    specificity=4,
                    action_terms=_present_terms(
                        control,
                        (
                            "ferdig",
                            "fullført",
                            "fullfør",
                            "done",
                            "complete",
                            "gjort",
                            "marker",
                            "markere",
                            "mark",
                        ),
                    ),
                    domain_terms=(str(number),),
                )
            )

        auth_match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:(?:kalender|gcal)\s+"
            r"(?:(?:auth|login)(?:\s+(?P<auth_code>[a-z0-9._~%+/=\-]+))?|"
            r"(?:kode|code)(?:\s+(?P<label_code>[a-z0-9._~%+/=\-]+))?)|"
            r"kalenderkode(?:\s+(?P<compact_code>[a-z0-9._~%+/=\-]+))?)\s*\??",
            text.strip(),
            re.I,
        )
        auth_code: str | None = None
        auth_reason: str | None = None
        if auth_match:
            auth_code = next(
                (
                    auth_match.group(name)
                    for name in ("auth_code", "label_code", "compact_code")
                    if auth_match.group(name)
                ),
                None,
            )
            if isinstance(auth_code, str):
                auth_code = unquote(auth_code)
            if (
                isinstance(auth_code, str)
                and auth_code.casefold() in _RESERVED_CALENDAR_AUTH_CODES
            ):
                auth_match = None
                auth_code = None
        if auth_match is not None:
            auth_reason = "calendar_auth_keyword"
        else:
            followup_code = _extract_auth_followup_code(text)
            if followup_code is not None:
                if self._matches_active_calendar_auth_flow(context):
                    auth_code = followup_code
                    auth_reason = "calendar_auth_scoped_followup"
                else:
                    blocked = IntentResult(
                        BotIntent.CLARIFY,
                        1.0,
                        {
                            "clarification": (
                                "Jeg sender ikke en mulig påloggingskode til "
                                "chatmodellen. Start Google Calendar-pålogging "
                                "i denne kanalen og prøv igjen."
                            )
                        },
                        "credential_shaped_input_blocked",
                    )
                    candidates.append(
                        self._candidate_from_result(
                            blocked,
                            tier=20,
                            order=99,
                            specificity=5,
                        )
                    )
        if auth_reason is not None:
            result = IntentResult(
                BotIntent.CALENDAR_AUTH,
                0.99,
                (
                    {"auth_code": auth_code}
                    if auth_code is not None
                    else {}
                ),
                auth_reason,
            )
            candidates.append(
                self._candidate_from_result(
                    result,
                    tier=20,
                    order=100,
                    specificity=(
                        5
                        if auth_reason == "calendar_auth_scoped_followup"
                        else 4
                    ),
                    action_terms=_present_terms(
                        control,
                        (
                            "auth",
                            "kode",
                            "koden",
                            "code",
                            "login",
                        ),
                    )
                    or (("kalenderkode",) if _phrase_present(
                        control, "kalenderkode"
                    ) else ())
                    or (
                        (auth_code,)
                        if auth_reason == "calendar_auth_scoped_followup"
                        and auth_code is not None
                        else ()
                    ),
                    domain_terms=_present_terms(
                        control, ("kalender", "gcal", "calendar")
                    )
                    or (("kalenderkode",) if _phrase_present(
                        control, "kalenderkode"
                    ) else ()),
                )
            )

        calendar_domain = _present_terms(
            control,
            (
                "kalender",
                "kalenderen",
                "calendar",
                "gcal",
                "møte",
                "møtet",
                "avtale",
                "avtalen",
                "arrangement",
                "arrangementet",
                "meeting",
                "event",
                "eventet",
            ),
        )
        calendar_actions = _present_terms(
            control,
            (
                "synk",
                "sync",
                "synkroniser",
                "tøm",
                "tømme",
                "clear",
                "slett",
                "slette",
                "delete",
                "fjern",
                "fjerne",
                "ferdig",
                "done",
                "complete",
                "fullfør",
                "fullføre",
                "fullført",
                "endre",
                "rediger",
                "edit",
                "change",
                "move",
                "flytt",
                "oppdater",
            ),
        )
        sync_match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:(?:kalender(?:en)?|calendar|gcal)\s+"
            r"(?:synk|sync|synkroniser|hent\s+fra\s+google|"
            r"oppdater\s+fra\s+google)|"
            r"(?:synk|sync|synkroniser)\s+(?:kalender(?:en)?|calendar|gcal)|"
            r"(?:hent|oppdater)\s+(?:kalender(?:en)?\s+)?fra\s+google)\s*\??",
            text.strip(),
            re.I,
        )
        if sync_match:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CALENDAR_SYNC,
                        0.98,
                        {},
                        "calendar_sync_keyword",
                    ),
                    tier=20,
                    order=110,
                    specificity=2,
                    action_terms=calendar_actions,
                    domain_terms=calendar_domain,
                )
            )

        calendar_clear_target = (
            r"(?:(?:hele|heile)\s+)?(?:"
            r"(?:kalenderen|kalender)(?:\s+min)?|"
            r"min\s+(?:kalenderen|kalender)|"
            r"(?:(?:the|my)\s+)?calendar)"
        )
        clear_match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:(?:slett|slette|delete|tøm|tømme|clear)\s+"
            rf"{calendar_clear_target}|"
            r"(?:kalenderen|kalender|calendar)\s+(?:slett|fjern)\s+alt|"
            r"(?:kalenderen|kalender|calendar)\s+(?:tøm|tømme|clear))\s*\??",
            text.strip(),
            re.I,
        )
        if clear_match:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CALENDAR_CLEAR,
                        0.98,
                        {"calendar_target": {"all": True}},
                        "calendar_clear_keyword",
                    ),
                    tier=20,
                    order=111,
                    specificity=3,
                    action_terms=calendar_actions,
                    domain_terms=calendar_domain,
                )
            )

        mutation_verb = (
            r"slett|slette|delete|fjern|fjerne|ferdig|done|complete|"
            r"fullfør|fullføre|fullført"
        )
        mutation_match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:kalender(?:en)?|calendar)\s+"
            rf"(?P<verb>{mutation_verb})\s+(?P<target>.+?)\s*\??",
            text,
            re.I,
        )
        if mutation_match is None:
            mutation_match = re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?P<verb>{mutation_verb})\s+"
                rf"(?P<target>.+?)\s+(?:i|fra|from)\s+"
                rf"(?:kalender(?:en)?|calendar)\s*\??",
                text,
                re.I,
            )
        explicit_domain = mutation_match is not None
        if mutation_match is None:
            direct = re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?P<verb>{mutation_verb})\s+"
                rf"(?P<target>.+?)\s*\??",
                text,
                re.I,
            )
            if direct:
                raw_target = self._normalize_calendar_target(
                    direct.group("target")
                )
                if self._target_looks_like_calendar_item(
                    raw_target,
                    context.domain_scope_id,
                    context.reference_time,
                ):
                    mutation_match = direct

        if mutation_match is None:
            mark_match = re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}"
                r"(?P<verb>marker|markere|mark)\s+"
                r"(?P<target>.+?)\s+(?:som\s+)?"
                r"(?:ferdig|fullført|done|complete|completed)\s*\??",
                text,
                re.I,
            )
            if mark_match and self._target_looks_like_calendar_item(
                mark_match.group("target"),
                context.domain_scope_id,
                context.reference_time,
            ):
                mutation_match = mark_match

        if mutation_match is not None and not clear_match:
            verb = mutation_match.group("verb").casefold()
            raw_target = mutation_match.group("target").strip(" .!?")
            _, target_is_quoted = self._unwrap_supported_quote(raw_target)
            target = self._normalize_calendar_target(
                mutation_match.group("target")
            )
            positive_target = not target.isdigit() or int(target) > 0
            target_is_code = raw_target.startswith("`")
            quoted_target_is_unique = (
                not target_is_quoted
                or self._calendar_unique_title_match(
                    target,
                    context.domain_scope_id,
                    context.reference_time,
                )
            )
            if (
                target
                and positive_target
                and not target_is_code
                and quoted_target_is_unique
                and not self._is_reserved_delete_target(target)
            ):
                target_payload = (
                    {"number": int(target)}
                    if target.isdigit() and int(target) > 0
                    else {"target": target}
                )
                intent = (
                    BotIntent.CALENDAR_DELETE
                    if verb
                    in {"slett", "slette", "delete", "fjern", "fjerne"}
                    else BotIntent.CALENDAR_COMPLETE
                )
                reason = (
                    "calendar_delete_keyword"
                    if intent is BotIntent.CALENDAR_DELETE
                    else "calendar_complete_keyword"
                )
                order = 112 if intent is BotIntent.CALENDAR_DELETE else 114
                if not explicit_domain:
                    reason = (
                        "calendar_delete_title_match"
                        if intent is BotIntent.CALENDAR_DELETE
                        else "calendar_complete_title_match"
                    )
                    order += 1
                # A positive visible display number is bounded target evidence;
                # it is never inferred from an unrelated number elsewhere.
                target_domain = (
                    calendar_domain
                    if explicit_domain
                    else (target if target_is_quoted else raw_target,)
                )
                if target_domain:
                    candidates.append(
                        self._candidate_from_result(
                            IntentResult(
                                intent,
                                0.98 if explicit_domain else 0.94,
                                {"calendar_target": target_payload},
                                reason,
                            ),
                            tier=20,
                            order=order,
                            specificity=3,
                            action_terms=_present_terms(control, (verb,)),
                            domain_terms=target_domain,
                        )
                    )

        family_target = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?P<verb>{mutation_verb})\s+"
            rf"(?P<family>{_CALENDAR_MUTATION_FAMILY})\s+"
            r"(?P<target>.+?)\s*\??",
            text,
            re.I,
        )
        if family_target:
            raw_bound_target = family_target.group("target").strip(" .!?")
            bound_target, target_is_quoted = self._unwrap_supported_quote(
                raw_bound_target
            )
            target_is_code = raw_bound_target.startswith("`")
            family = family_target.group("family").casefold()
            numeric_target = bound_target.isdigit() and int(bound_target) > 0
            numeric_family = family not in {"påminnelse", "reminder"}
            quoted_family = family in _CALENDAR_FAMILY.split("|")
            uniquely_bound = (
                numeric_target and numeric_family
            ) or (
                not numeric_target
                and (not target_is_quoted or quoted_family)
                and self._calendar_unique_title_match(
                    bound_target,
                    context.domain_scope_id,
                    context.reference_time,
                )
            )
            if bound_target and not target_is_code and uniquely_bound:
                verb = family_target.group("verb").casefold()
                intent = (
                    BotIntent.CALENDAR_DELETE
                    if verb
                    in {"slett", "slette", "delete", "fjern", "fjerne"}
                    else BotIntent.CALENDAR_COMPLETE
                )
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            intent,
                            0.94,
                            {
                                "calendar_target": {
                                    **(
                                        {"number": int(bound_target)}
                                        if numeric_target
                                        else {"target": bound_target}
                                    )
                                }
                            },
                            (
                                "calendar_delete_title_match"
                                if intent is BotIntent.CALENDAR_DELETE
                                else "calendar_complete_title_match"
                            ),
                        ),
                        tier=20,
                        order=(113 if intent is BotIntent.CALENDAR_DELETE else 115),
                        specificity=3,
                        action_terms=_present_terms(control, (verb,)),
                        domain_terms=(
                            _present_terms(control, (family,))
                            if target_is_quoted
                            else (bound_target,)
                        ),
                    )
                )
        natural_edit, natural_edit_invalid = self._parse_natural_calendar_edit(
            text,
            reference_time=context.reference_time,
        )
        if natural_edit_invalid and calendar_domain:
            self._append_invalid_temporal(
                rejections,
                intent=BotIntent.CALENDAR_EDIT,
                tier=20,
                order=117,
                reason="calendar_edit_temporal_invalid",
            )
        elif natural_edit and calendar_domain:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CALENDAR_EDIT,
                        0.98,
                        {
                            "calendar_edit": {
                                "target": natural_edit["target"],
                                "changes": natural_edit["changes"],
                            }
                        },
                        "calendar_edit_natural",
                    ),
                    tier=20,
                    order=117,
                    specificity=3,
                    action_terms=_present_terms(
                        control, (natural_edit["verb"],)
                    ),
                    domain_terms=calendar_domain,
                )
            )

        explicit_edit = re.fullmatch(
            r"(?:kalender(?:en)?|calendar)\s+"
            r"(?P<verb>endre|rediger|edit|oppdater|oppdatere)\s+"
            r"(?P<target>.+?)\s+"
            r"(?P<field>tittel|title|beskrivelse|description|type)\s*:\s*"
            r"(?P<value>.+?)\s*\??",
            text,
            re.I,
        )
        if explicit_edit:
            field = {
                "tittel": "title",
                "title": "title",
                "beskrivelse": "description",
                "description": "description",
                "type": "type",
            }[explicit_edit.group("field").casefold()]
            target = explicit_edit.group("target").strip()
            value = explicit_edit.group("value").strip(" .!?")
            if target and value:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CALENDAR_EDIT,
                            0.98,
                            {
                                "calendar_edit": {
                                    "target": target,
                                    "changes": {field: value},
                                }
                            },
                            "calendar_edit_keyword",
                        ),
                        tier=20,
                        order=116,
                        specificity=3,
                        action_terms=_present_terms(
                            control, (explicit_edit.group("verb"),)
                        ),
                        domain_terms=calendar_domain,
                    )
                )

        date_filtered_calendar_read = (
            filtered_list_read_family(control) == "calendar"
        )
        if date_filtered_calendar_read:
            date_filter = _resolve_single_date_read_filter(
                self.temporal_resolver,
                control,
                reference_time=context.reference_time,
            )
            if date_filter is not None:
                supported = is_supported_calendar_read_date(
                    date_filter,
                    reference_time=context.reference_time,
                )
                result = (
                    IntentResult(
                        BotIntent.CALENDAR_LIST,
                        0.98,
                        {"calendar_list": {"date": date_filter}},
                        "calendar_list_date_filtered",
                    )
                    if supported
                    else IntentResult(
                        BotIntent.CLARIFY,
                        1.0,
                        {
                            "clarification": (
                                "Kalenderlisten viser i dag og fremover. "
                                "Be om en dato fra i dag eller senere."
                            )
                        },
                        "calendar_history_not_supported",
                        risk=IntentRisk.READ_ONLY,
                    )
                )
                candidates.append(
                    self._candidate_from_result(
                        result,
                        tier=30,
                        order=117,
                        specificity=3,
                        action_terms=_present_terms(
                            control,
                            ("vis", "show", "list", "har", "have", "skjer"),
                        ),
                        domain_terms=_present_terms(
                            control,
                            (
                                "kalender",
                                "kalenderen",
                                "calendar",
                                "schedule",
                                "planlagt",
                                "planned",
                                "planen",
                            ),
                        ),
                    )
                )

        if self._has_calendar_context(control):

            natural_calendar_read = re.fullmatch(
                r"(?:hva\s+vet|kva\s+veit|ka\s+veit)\s+du\s+om\s+"
                r"kalenderen\s+min\s*\??|"
                r"(?:fortell|fortel)\s+(?:meg|mæ)\s+om\s+"
                r"kalenderen\s+min\s*\??|"
                r"(?:what\s+do\s+you\s+know|tell\s+me)\s+about\s+"
                r"my\s+calendar\s*\??|"
                rf"{_POLITE_COMMAND_PREFIX}(?:vis|vise|show)\s+"
                r"(?:(?:meg|mæ|me)\s+)?(?:kalenderen\s+min|"
                r"my\s+calendar)\s*\??|"
                r"(?:hva|kva|ka)\s+står\s+(?:det\s+)?i\s+"
                r"kalenderen\s+min\s*\??|"
                r"(?:what\s+is|what['’]s)\s+(?:coming\s+up\s+)?on\s+"
                r"my\s+calendar\s*\??|"
                r"(?:show\s+me\s+my\s+schedule|"
                r"what['’]s\s+my\s+schedule)\s*\??|"
                r"kan\s+(?:jeg|eg|æ)\s+(?:se|sjå)\s+"
                r"kalenderen\s+min\s*\??|"
                r"(?:can|could)\s+i\s+see\s+my\s+calendar\s*\??",
                control,
                re.I,
            )
            explicit_calendar_list = re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?:vis|vise|list|show)\s+"
                r"(?:(?:meg|mæ|me)\s+)?(?:kalender(?:en)?|calendar|"
                r"arrangementer|events)\s*[?.!]*",
                control,
                re.I,
            )
            shared_calendar_read = (
                unfiltered_list_read_family(control) == "calendar"
            )
            no_mutation = not calendar_actions and not clear_match
            if (
                explicit_calendar_list
                or natural_calendar_read
                or shared_calendar_read
            ) and no_mutation:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CALENDAR_LIST,
                            0.92,
                            {},
                            (
                                "calendar_list_natural"
                                if natural_calendar_read or shared_calendar_read
                                else "calendar_list_keyword"
                            ),
                        ),
                        tier=30,
                        order=118,
                        specificity=2,
                        action_terms=_present_terms(
                            control,
                            (
                                "vis",
                                "list",
                                "vet",
                                "veit",
                                "fortell",
                                "fortel",
                                "know",
                                "tell",
                                "vise",
                                "show",
                                "check",
                                "sjekk",
                                "sjekke",
                                "har",
                                "have",
                                "står",
                                "what is",
                                "what's",
                            ),
                        ),
                        domain_terms=calendar_domain,
                    )
                )
            elif control in {
                "kalender",
                "kalenderen",
                "calendar",
                "arrangementer",
                "events",
                "kommende",
                "kommende arrangementer",
                "planlagt",
                "planlagte",
            }:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CALENDAR_LIST,
                            0.85,
                            {},
                            "calendar_keyword_default",
                        ),
                        tier=30,
                        order=119,
                        specificity=1,
                        domain_terms=calendar_domain or (control,),
                    )
                )

        birthday_gate = bool(
            re.search(
                r"\b(?:bursdag(?:en|er|ene|ar|ane)?|birthday(?:s)?)\b",
                control,
                re.I,
            )
        )
        if birthday_gate:
            birthday_parser = getattr(
                self.monitor, "parse_birthday_command", None
            )
            if birthday_parser is None:
                from features.birthday_manager import (
                    parse_birthday_command as birthday_parser,
                )
            parsed_birthday = self._safe_parse(
                errors,
                rejections,
                "parse_birthday_command",
                "birthday",
                birthday_parser,
                text,
                routing_context=context.routing,
            )
            if isinstance(parsed_birthday, dict):
                action = parsed_birthday.get("action")
                intent_by_action = {
                    "add": BotIntent.BIRTHDAY_CREATE,
                    "edit": BotIntent.BIRTHDAY_EDIT,
                    "list": BotIntent.BIRTHDAY_LIST,
                }
                birthday_intent = intent_by_action.get(action)
                if action == "clarify":
                    result = IntentResult(
                        BotIntent.CLARIFY,
                        0.95,
                        {},
                        "birthday_identity_required",
                    )
                elif birthday_intent is not None:
                    result = IntentResult(
                        birthday_intent,
                        0.96,
                        {"birthday": dict(parsed_birthday)},
                        f"birthday_{action}_natural",
                    )
                else:
                    result = None
                if result is not None:
                    candidates.append(
                        self._candidate_from_result(
                            result,
                            tier=30,
                            order={
                                "list": 119,
                                "clarify": 120,
                                "add": 121,
                                "edit": 122,
                            }.get(str(action), 122),
                            specificity=(
                                2
                                if action == "list"
                                else (
                                    3
                                    if action != "clarify"
                                    or re.search(
                                        r"\d{1,2}[.]\d{1,2}", control
                                    )
                                    else 2
                                )
                            ),
                            action_terms=_present_terms(
                                control,
                                (
                                    "vis",
                                    "list",
                                    "show",
                                    "endre",
                                    "rediger",
                                    "oppdater",
                                    "edit",
                                    "update",
                                    "bursdagen min",
                                    "min bursdag",
                                    "har bursdag",
                                    "my birthday",
                                ),
                            ),
                            domain_terms=_present_terms(
                                control,
                                (
                                    "bursdag",
                                    "bursdagen",
                                    "bursdager",
                                    "bursdagar",
                                    "birthday",
                                    "birthdays",
                                ),
                            ),
                        )
                    )
                else:
                    self._append_invalid_payload(
                        rejections,
                        intent=BotIntent.BIRTHDAY_CREATE,
                        family="birthday",
                        tier=30,
                        order=121,
                    )
            elif parsed_birthday is not None:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.BIRTHDAY_CREATE,
                    family="birthday",
                    tier=30,
                    order=121,
                )

        bounded_english_calendar_create = (
            bounded_english_calendar_create_head(context.utterance)
        )
        calendar_create_frame = re.match(
            rf"^{_POLITE_COMMAND_PREFIX}(?:(?:(?:legg|legge)\s+"
            r"(?:inn|til)|(?:sette|setje)\s+opp|lag|lage|opprett|opprette|"
            r"booke|planlegg|planlegge|"
            r"planleggje)\s+"
            r"(?:(?:en|ei|et|a|an)\s+)?)?"
            rf"(?:{_CALENDAR_ITEM_FAMILY})\b",
            control,
            re.I,
        ) or re.match(
            rf"^(?:ikke\s+glem|ikkje\s+gløym)\s+"
            rf"(?:{_CALENDAR_ITEM_FAMILY})\b",
            control,
            re.I,
        )
        bounded_generic_calendar_create = (
            bounded_english_calendar_create is not None
            or re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:legg|legge)\s+inn\s+"
                r"(?:(?:en|ei|et)\s+)?\S+",
                control,
                re.I,
            )
            or re.match(
                r"^(?:(?:kan|kunne|vil|can|could|would|will)\s+"
                r"(?:du|you)|vennligst|please)\s+"
                r"(?:(?:sette|setje)\s+opp|booke|"
                r"planlegg|planlegge|planleggje)\s+"
                r"(?:(?:en|ei|et|a|an)\s+)?\S+",
                control,
                re.I,
            )
            or re.match(
                r"^(?:(?:can|could|would|will)\s+you|please)\s+"
                r"add\s+.+?\s+to\s+my\s+calendar\b|"
                r"^(?:i['’]d|i\s+would)\s+like\s+to\s+add\s+.+?\s+"
                r"to\s+my\s+calendar\b|"
                r"^(?:planlegg|planlegge|planleggje)\s+\S+",
                control,
                re.I,
            )
        )
        task_create_frame = re.match(
            r"^(?:jeg\s+må|eg\s+må|i\s+need\s+to)\b",
            control,
            re.I,
        )
        reminder_precedence_frame = re.match(
            r"^(?:(?:jeg|eg|æ)\s+må\s+(?:huske|hugse)\b|"
            r"i\s+need\s+to\s+remember\b)",
            control,
            re.I,
        )
        explicit_reminder_noun_create = re.match(
            rf"^{_POLITE_COMMAND_PREFIX}(?:opprett|opprette|lag|lage|"
            r"(?:legg|legge)\s+(?:inn|til)|(?:sette|setje)\s+opp|"
            r"planlegg|planlegge|planleggje|create|add|set\s+up)\s+"
            r"(?:(?:en|ei|et|a)\s+)?(?:påminnelse|påminning|reminder|"
            r"gjøremål|gjeremål|todo)\b",
            control,
            re.I,
        )
        foreign_calendar_create_domain = _FOREIGN_CALENDAR_CREATE_DOMAIN.search(
            control
        )
        calendar_parse_gate = bool(
            calendar_create_frame
            or bounded_generic_calendar_create
            or (task_create_frame and not reminder_precedence_frame)
        ) and not explicit_reminder_noun_create and not (
            foreign_calendar_create_domain and not calendar_domain
        )
        calendar_item = None
        calendar_temporal_errors: tuple[str, ...] = ()
        if (
            calendar_parse_gate
            and _ENGLISH_BARE_CLOCK_TIME.search(control)
            and _ENGLISH_CALENDAR_TIME_FRAME.search(control)
        ):
            calendar_temporal_errors = ("ambiguous_time",)
        elif calendar_parse_gate:
            parser = getattr(self.monitor, "nlp_parser", None)
            task_parser = getattr(
                parser, "parse_task_with_recurrence_result", None
            ) or getattr(parser, "parse_task_with_recurrence", None)
            task_result = self._safe_parse(
                errors,
                rejections,
                "parse_task_with_recurrence",
                "calendar",
                task_parser,
                text,
                temporal_text=control,
                reference_time=context.reference_time,
            )
            if isinstance(task_result, dict):
                calendar_item = task_result
            elif isinstance(task_result, NaturalParseResult) and task_result.errors:
                calendar_temporal_errors = task_result.errors
                self._append_invalid_temporal(rejections)
            elif isinstance(task_result, NaturalParseResult):
                calendar_item = task_result.item
                if calendar_item is not None and not isinstance(
                    calendar_item, dict
                ):
                    self._append_invalid_payload(
                        rejections,
                        intent=BotIntent.CALENDAR_ITEM,
                        family="calendar",
                        tier=40,
                        order=130,
                    )
                    calendar_item = None
                elif calendar_item is None:
                    event_parser = getattr(
                        parser, "parse_event_result", None
                    ) or getattr(parser, "parse_event", None)
                    event_result = self._safe_parse(
                        errors,
                        rejections,
                        "parse_event",
                        "calendar",
                        event_parser,
                        text,
                        temporal_text=control,
                        reference_time=context.reference_time,
                    )
                    if isinstance(event_result, dict):
                        calendar_item = event_result
                    elif (
                        isinstance(event_result, NaturalParseResult)
                        and event_result.errors
                    ):
                        calendar_temporal_errors = event_result.errors
                        self._append_invalid_temporal(rejections)
                    elif isinstance(event_result, NaturalParseResult):
                        calendar_item = event_result.item
                        if calendar_item is not None and not isinstance(
                            calendar_item, dict
                        ):
                            self._append_invalid_payload(
                                rejections,
                                intent=BotIntent.CALENDAR_ITEM,
                                family="calendar",
                                tier=40,
                                order=130,
                            )
                            calendar_item = None
                    elif event_result is not None:
                        self._append_invalid_payload(
                            rejections,
                            intent=BotIntent.CALENDAR_ITEM,
                            family="calendar",
                            tier=40,
                            order=130,
                        )
            elif task_result is not None:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.CALENDAR_ITEM,
                    family="calendar",
                    tier=40,
                    order=130,
                )

        if isinstance(calendar_item, dict):
            calendar_item = {
                key: calendar_item[key]
                for key in _CANONICAL_CALENDAR_CREATE_FIELDS
                if key in calendar_item
                and not (
                    key != "days_offset"
                    and key != "title"
                    and calendar_item[key] is None
                )
            }
            confidence = 0.86
            if (
                calendar_item.get("date")
                or calendar_item.get("recurrence")
            ) and calendar_item.get("title"):
                confidence = 0.97
            if _present_terms(
                control, ("husk", "remind", "påminn", "minn")
            ):
                confidence = max(confidence, 0.95)
            create_actions = _present_terms(
                control,
                (
                    "husk",
                    "glem",
                    "lag",
                    "lage",
                    "opprett",
                    "opprette",
                    "legg inn",
                    "legge inn",
                    "legg til",
                    "legge til",
                    "sette opp",
                    "setje opp",
                    "set up",
                    "book",
                    "booke",
                    "put",
                    "create",
                    "add",
                    "schedule",
                    "make",
                    "planlegg",
                    "planlegge",
                    "planleggje",
                    "påminn",
                    "minn",
                    "jeg må",
                    "eg må",
                    "i need to",
                ),
            )
            create_domains = _present_terms(
                control,
                (
                    "møte",
                    "møtet",
                    "avtale",
                    "avtalen",
                    "arrangement",
                    "arrangementet",
                    "meeting",
                    "appointment",
                    "event",
                    "eventet",
                ),
            )
            result = IntentResult(
                BotIntent.CALENDAR_ITEM,
                confidence,
                {"calendar_item": calendar_item},
                "calendar_nlp_high" if confidence >= 0.94 else "calendar_nlp",
            )
            has_complete_shape = bool(
                isinstance(calendar_item.get("title"), str)
                and calendar_item["title"].strip()
                and (
                    calendar_item.get("date")
                    or calendar_item.get("recurrence")
                )
            )
            if create_domains and has_complete_shape:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CALENDAR_ITEM,
                            confidence,
                            {"calendar_item": calendar_item},
                            "calendar_create_natural",
                        ),
                        tier=35,
                        order=123,
                        specificity=3,
                        action_terms=create_actions,
                        domain_terms=create_domains,
                    )
                )
            candidates.append(
                self._candidate_from_result(
                    result,
                    tier=40 if confidence >= 0.94 else 70,
                    order=130 if confidence >= 0.94 else 350,
                    specificity=3 if has_complete_shape else 0,
                    action_terms=create_actions,
                    domain_terms=create_domains,
                )
            )

        if calendar_temporal_errors == ("ambiguous_time",):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        0.99,
                        {
                            "clarification": (
                                "Mener du tidspunktet om morgenen eller "
                                "på ettermiddagen?"
                            )
                        },
                        "calendar_time_ambiguous",
                    ),
                    tier=35,
                    order=124,
                    specificity=3,
                    action_terms=_present_terms(
                        control,
                        (
                            "lag",
                            "lage",
                            "opprett",
                            "opprette",
                            "legg inn",
                            "legge inn",
                            "legg til",
                            "legge til",
                            "sette opp",
                            "setje opp",
                            "book",
                            "booke",
                            "create",
                            "add",
                            "schedule",
                        ),
                    ),
                    domain_terms=_present_terms(
                        control,
                        (
                            "møte",
                            "møtet",
                            "avtale",
                            "avtalen",
                            "arrangement",
                            "arrangementet",
                            "meeting",
                            "event",
                            "eventet",
                        ),
                    ),
                )
            )

        if calendar_temporal_errors == ("conflicting_recurrence",):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        0.99,
                        {
                            "clarification": (
                                "Jeg fant flere ulike gjentakelser. "
                                "Hvilken skal jeg bruke?"
                            )
                        },
                        "calendar_recurrence_conflict",
                    ),
                    tier=35,
                    order=125,
                    specificity=3,
                    action_terms=_present_terms(
                        control,
                        (
                            "lag",
                            "lage",
                            "opprett",
                            "opprette",
                            "legg inn",
                            "legge inn",
                            "legg til",
                            "legge til",
                            "sette opp",
                            "setje opp",
                            "book",
                            "booke",
                            "create",
                            "add",
                            "schedule",
                        ),
                    ),
                    domain_terms=_present_terms(
                        control,
                        (
                            "møte",
                            "møtet",
                            "avtale",
                            "avtalen",
                            "arrangement",
                            "arrangementet",
                            "meeting",
                            "event",
                            "eventet",
                        ),
                    ),
                )
            )

        return CollectorOutput(
            candidates=tuple(candidates),
            parser_errors=tuple(errors),
            rejections=tuple(rejections),
        )

    def _collect_poll_watchlist_quote_candidates(
        self, context: CollectorContext
    ) -> CollectorOutput:
        control = context.utterance.control_text.strip()
        text = context.utterance.text
        candidates: list[IntentCandidate] = []
        errors: list[str] = []
        rejections: list[CandidateRejection] = []

        poll_domain = _present_terms(
            control,
            (
                "poll",
                "pollen",
                "avstemning",
                "avstemningen",
                "avstemninga",
                "avstemming",
                "avstemmingen",
                "avstemminga",
            ),
        )
        poll_list_alias = (
            r"(?:polls|avstemninger|active polls|vis polls?|"
            r"vis avstemninger?|list polls?|poll liste|poll list|"
            r"avstemning liste|what\s+polls\s+are\s+active|"
            r"are\s+there\s+any\s+active\s+polls|"
            rf"{_POLITE_COMMAND_PREFIX}(?:vis|vise|show)\s+"
            r"(?:(?:meg|mæ|me)\s+)?(?:aktive|active)\s+"
            r"(?:avstemninger|avstemmingar|polls))"
        )
        poll_list_gate = bool(
            re.fullmatch(poll_list_alias + r"\s*\??", control, re.I)
            or re.fullmatch(
                poll_list_alias
                + r"\s+(?:```.*```|`[^`]*`|\"[^\"]*\"|"
                r"“[^”]*”|‘[^’]*’|«[^»]*»)",
                text,
                re.I | re.S,
            )
        )
        poll_mutation_frame = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:endre|rediger|redigere|edit|"
                r"slett|slette|delete|fjern|fjerne|remove|lukk|lukke|close|"
                r"avslutt|avslutte|steng|stenge)\s+"
                r"(?:poll(?:en)?|avstemning(?:en|a)?|"
                r"avstemming(?:en|a)?)\b",
                control,
                re.I,
            )
        )
        explicit_vote_gate = bool(
            re.fullmatch(
                r"(?:"
                r"(?:stem|vote)(?:\s+(?:på|for))?"
                r"(?:\s+(?:alternativ(?:et)?|valg(?:et)?|option))?\s+|"
                r"(?:jeg|eg|æ)\s+stemmer(?:\s+på)?"
                r"(?:\s+(?:alternativ(?:et)?|valg(?:et)?|option))?\s+|"
                r"i\s+vote(?:\s+for)?(?:\s+option)?\s+"
                r")(?:\d{1,2}|en|én|ein|ett|one|to|two|tre|three|"
                r"fire|four|fem|five|seks|six|sju|syv|seven|åtte|"
                r"eight|ni|nine|ti|ten)\s*[.!?]*",
                control,
                re.I,
            )
        )
        active_polls = (
            self._active_polls(
                context.domain_scope_id,
                context.reference_time,
            )
            if (
                poll_list_gate
                or control.isdigit()
                or explicit_vote_gate
                or poll_domain
            )
            else ()
        )
        single_poll_id = self._single_poll_id(active_polls)
        if poll_list_gate:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.POLL_LIST,
                        0.95,
                        {},
                        "poll_list_keyword",
                    ),
                    tier=50,
                    order=140,
                    specificity=2,
                    domain_terms=poll_domain or _present_terms(
                        control, ("polls", "avstemninger")
                    ),
                )
            )

        slash_shape = control.count("/") >= 2 or " / " in control
        poll_create_gate = bool(
            not poll_list_gate
            and not poll_mutation_frame
            and (
                re.match(
                    rf"^{_POLITE_COMMAND_PREFIX}"
                    r"(?:(?:lag|lage|opprett|opprette|ny|create|make)\s+"
                    r"(?:(?:en|ei|et|a|an)\s+)?)?"
                    r"(?:poll|avstemning)\b",
                    control,
                    re.I,
                )
                or slash_shape
            )
        )
        parsed_poll = None
        if poll_create_gate:
            parsed_poll = self._safe_parse(
                errors,
                rejections,
                "parse_poll_command",
                "poll",
                getattr(self.monitor, "parse_poll_command", None),
                text,
            )
        if parsed_poll is not None and not isinstance(parsed_poll, dict):
            self._append_invalid_payload(
                rejections,
                intent=BotIntent.POLL_CREATE,
                family="poll",
                tier=50,
                order=150,
            )
            parsed_poll = None
        if isinstance(parsed_poll, dict):
            question = parsed_poll.get("question")
            options = parsed_poll.get("options")
            complete_poll = bool(
                isinstance(question, str)
                and question.strip()
                and isinstance(options, list)
                and len(
                    [
                        option
                        for option in options
                        if isinstance(option, str) and option.strip()
                    ]
                )
                >= 2
            )
            result = IntentResult(
                BotIntent.POLL_CREATE,
                0.95,
                {"poll": dict(parsed_poll)},
                "poll_parser",
            )
            if poll_domain and complete_poll and poll_create_gate:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.POLL_CREATE,
                            0.95,
                            {"poll": dict(parsed_poll)},
                            "poll_create_natural",
                        ),
                        tier=35,
                        order=124,
                        specificity=3,
                        action_terms=_present_terms(
                            control,
                            (
                                "lag",
                                "lage",
                                "opprett",
                                "opprette",
                                "create",
                                "make",
                                "ny",
                            ),
                        ),
                        domain_terms=poll_domain,
                    )
                )
            if poll_create_gate:
                candidates.append(
                    self._candidate_from_result(
                        result,
                        tier=50,
                        order=150,
                        specificity=3 if poll_domain and complete_poll else 0,
                        action_terms=_present_terms(
                            control,
                            (
                                "lag",
                                "lage",
                                "opprett",
                                "opprette",
                                "create",
                                "make",
                                "ny",
                            ),
                        ),
                        domain_terms=poll_domain,
                    )
                )

        if (control.isdigit() or explicit_vote_gate) and single_poll_id is not None:
            parsed_vote = self._safe_parse(
                errors,
                rejections,
                "parse_vote",
                "poll",
                getattr(self.monitor, "parse_vote", None),
                text,
            )
            if type(parsed_vote) is int and parsed_vote > 0:
                vote_payload = {
                    "option": parsed_vote,
                    "poll_id": single_poll_id,
                }
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.POLL_VOTE,
                            0.95,
                            {"vote": vote_payload},
                            "active_poll_vote",
                        ),
                        tier=50,
                        order=160,
                        specificity=4,
                        action_terms=_present_terms(
                            control, ("stem", "stemmer", "vote")
                        ),
                        domain_terms=(
                            (control,)
                            if control.isdigit()
                            else _present_terms(
                                control, ("stem", "stemmer", "vote")
                            )
                        ),
                    )
                )
            elif parsed_vote is not None:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.POLL_VOTE,
                    family="poll",
                    tier=50,
                    order=160,
                )

        if poll_domain and active_polls:
            poll_ref = self._parse_poll_reference(control)
            poll_mutations = (
                (
                    ("endre", "rediger", "redigere", "edit"),
                    BotIntent.POLL_EDIT,
                    "poll_edit",
                    "poll_edit_keyword",
                    170,
                ),
                (
                    (
                        "slett",
                        "slette",
                        "delete",
                        "fjern",
                        "fjerne",
                        "remove",
                    ),
                    BotIntent.POLL_DELETE,
                    "poll_delete",
                    "poll_delete_keyword",
                    180,
                ),
                (
                    (
                        "lukk",
                        "lukke",
                        "close",
                        "avslutt",
                        "avslutte",
                        "steng",
                        "stenge",
                    ),
                    BotIntent.POLL_CLOSE,
                    "poll_close",
                    "poll_close_keyword",
                    190,
                ),
            )
            for actions, intent, envelope, reason, order in poll_mutations:
                action_pattern = "|".join(map(re.escape, actions))
                if not re.match(
                    rf"^{_POLITE_COMMAND_PREFIX}(?:{action_pattern})\s+"
                    r"(?:poll(?:en)?|avstemning(?:en|a)?|"
                    r"avstemming(?:en|a)?)\b",
                    control,
                    re.I,
                ):
                    continue
                action_payload = {
                    key: value
                    for key, value in poll_ref.items()
                    if value is not None
                }
                if not action_payload and single_poll_id is not None:
                    action_payload["poll_id"] = single_poll_id
                if not action_payload:
                    continue
                if intent is BotIntent.POLL_EDIT:
                    edit_changes = self._parse_poll_edit_changes(text)
                    if edit_changes is not None:
                        action_payload.update(edit_changes)
                has_target = bool(
                    action_payload.get("target") is not None
                    or action_payload.get("poll_id")
                )
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            intent,
                            0.95,
                            {envelope: action_payload},
                            reason,
                        ),
                        tier=50,
                        order=order,
                        specificity=3 if has_target else 2,
                        action_terms=_present_terms(control, actions),
                        domain_terms=poll_domain,
                    )
                )

        countdown_gate = bool(
            re.search(
                r"\b(?:hvor\s+(?:lenge|mange\s+dager)|"
                r"kor\s+(?:lenge|mange\s+dagar)|når\s+er|"
                r"countdown|count\s+down|nedtelling|nedteljing|dager\s+til|"
                r"dagar\s+til|days\s+(?:to|until)|"
                r"how\s+long(?:\s+is\s+it)?\s+(?:to|until|till)|"
                r"how\s+many\s+days(?:\s+are\s+there)?|"
                r"when(?:\s+is|['’]s))\b",
                control,
                re.I,
            )
        )
        if countdown_gate:
            countdown = getattr(self.monitor, "countdown", None)
            parsed_countdown = self._safe_parse(
                errors,
                rejections,
                "parse_countdown_query",
                "countdown",
                getattr(countdown, "parse_countdown_query", None),
                text,
                reference_time=context.reference_time,
            )
            if parsed_countdown:
                target = (
                    parsed_countdown.get("event")
                    if isinstance(parsed_countdown, dict)
                    else None
                )
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.COUNTDOWN,
                            0.93,
                            {"countdown": parsed_countdown},
                            "countdown_parser",
                        ),
                        tier=50,
                        order=200,
                        specificity=3 if target else 2,
                        action_terms=_present_terms(
                            control,
                            (
                                "hvor lenge",
                                "hvor mange dager",
                                "kor lenge",
                                "kor mange dagar",
                                "når er",
                                "countdown",
                                "nedtelling",
                                "nedteljing",
                                "dager til",
                                "dagar til",
                                "days to",
                                "days until",
                                "how long to",
                                "how long until",
                                "how many days",
                                "when is",
                                "when's",
                                "when’s",
                            ),
                        ),
                        domain_terms=(str(target),) if target else (),
                    )
                )

        watchlist_status_gate = bool(
            re.fullmatch(
                r"(?:(?:(?:vis|list|show)\s+)?(?:(?:min|my|the)\s+)?"
                r"(?:watchlist|watchlista|watch\s+list)|"
                r"hva\s+har\s+vi\s+(?:på|i)\s+watchlist|"
                r"hva\s+har\s+(?:jeg|eg|æ)\s+(?:på|i)\s+"
                r"(?:watchlist|watchlista|watchlisten)(?:\s+min)?|"
                r"show\s+me\s+my\s+(?:watchlist|watch\s+list)|"
                r"(?:what\s+is|what['’]s)\s+on\s+my\s+"
                r"(?:watchlist|watch\s+list)|"
                r"which\s+(?:movies|films|series|shows)\s+are\s+on\s+my\s+"
                r"(?:watchlist|watch\s+list))\s*[?.!]*",
                control,
                re.I,
            )
        )
        watchlist_suggest_gate = bool(
            _WATCHLIST_SUGGESTION_FRAME.fullmatch(control)
        )
        watchlist_add_gate = bool(
            re.fullmatch(
                rf"(?:{_POLITE_COMMAND_PREFIX}(?:legg|legge)(?:\s+til)?\s+"
                r".+?\s+(?:på|i|til)\s+(?:watchlist(?:a|en)?|watch\s+list)"
                r"(?:\s+min)?|"
                rf"{_POLITE_COMMAND_PREFIX}add\s+.+?\s+to\s+"
                r"(?:(?:the|my)\s+)?watchlist|"
                rf"{_POLITE_COMMAND_PREFIX}(?:husk|huske|hugs|hugse)\s+at\s+"
                r"(?:jeg|eg|æ)\s+(?:vil|skal)\s+(?:se|sjå)(?:\s+på)?\s+.+|"
                r"(?:husk\s+å\s+se|hugs\s+å\s+sjå|remember\s+to\s+watch)"
                r"(?:\s+.*)?|"
                r"legg\s+til\s+(?:film|filmen|serie|serien)(?:\s+.*)?)"
                r"\s*\??",
                control,
                re.I,
            )
        )
        watchlist_remove_gate = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:fjern|fjerne|slett|slette|"
                r"remove|delete)\s+(?:film|filmen|serie|serien|movie|show|"
                r"watchlist(?:a)?)\b",
                control,
                re.I,
            )
            or re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:fjern|fjerne|slett|slette|"
                r"remove|delete)\s+(?:nummer|number|nr\.?|no\.?|#)?\s*"
                r"\d+\s+(?:fra|from)\s+watchlist(?:a)?\b",
                control,
                re.I,
            )
        )
        watchlist_edit_gate = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:endre|rediger|edit|change)\s+"
                r"(?:film|filmen|serie|serien|movie|show|watchlist(?:a)?)\b",
                control,
                re.I,
            )
        )
        watchlist_gate = bool(
            watchlist_status_gate
            or watchlist_suggest_gate
            or watchlist_add_gate
            or watchlist_remove_gate
            or watchlist_edit_gate
        )
        parsed_watchlist = None
        if watchlist_gate:
            parsed_watchlist = self._safe_parse(
                errors,
                rejections,
                "parse_watchlist_command",
                "watchlist",
                getattr(self.monitor, "parse_watchlist_command", None),
                text,
                reference_time=context.reference_time,
                temporal_resolver=self.temporal_resolver,
            )
        if parsed_watchlist is not None and not isinstance(parsed_watchlist, dict):
            self._append_invalid_payload(
                rejections,
                intent=BotIntent.WATCHLIST,
                family="watchlist",
                tier=50,
                order=210,
            )
            parsed_watchlist = None
        if isinstance(parsed_watchlist, dict):
            action = parsed_watchlist.get("action")
            action_is_live = isinstance(action, str) and {
                "status": watchlist_status_gate,
                "list": watchlist_status_gate,
                "suggest": watchlist_suggest_gate,
                "add": watchlist_add_gate,
                "remove": watchlist_remove_gate,
                "edit": watchlist_edit_gate,
            }.get(action, False)
            if not action_is_live:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.WATCHLIST,
                    family="watchlist",
                    tier=50,
                    order=210,
                )
                parsed_watchlist = None
        if isinstance(parsed_watchlist, dict):
            action = parsed_watchlist.get("action")
            title = parsed_watchlist.get("title")
            index = parsed_watchlist.get("index")
            complete_mutation = bool(
                (isinstance(title, str) and title.strip())
                or (isinstance(index, int) and index > 0)
            )
            if action in {"add", "edit", "remove"} and not complete_mutation:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.WATCHLIST,
                    family="watchlist",
                    tier=50,
                    order=210,
                )
                parsed_watchlist = None
            else:
                result = IntentResult(
                    BotIntent.WATCHLIST,
                    0.93,
                    {"watchlist": dict(parsed_watchlist)},
                    "watchlist_parser",
                )
                watch_actions = _present_terms(
                    control,
                    (
                        "husk",
                        "huske",
                        "hugs",
                        "hugse",
                        "remember",
                        "legg",
                        "legge",
                        "legg til",
                        "add",
                        "fjern",
                        "fjerne",
                        "slett",
                        "slette",
                        "remove",
                        "delete",
                        "endre",
                        "rediger",
                        "edit",
                        "change",
                    ),
                )
                watch_domains = _present_terms(
                    control,
                    (
                        "watchlist",
                        "watchlista",
                        "watchlisten",
                        "film",
                        "filmen",
                        "serie",
                        "serien",
                        "movie",
                        "show",
                        "husk å se",
                        "husk at",
                        "huske at",
                        "hugs å sjå",
                        "hugs at",
                        "hugse at",
                        "remember to watch",
                    ),
                )
                specificity = (
                    3
                    if action in {"add", "edit", "remove"}
                    else 1
                )
                if action == "add":
                    candidates.append(
                        self._candidate_from_result(
                            IntentResult(
                                BotIntent.WATCHLIST,
                                0.93,
                                {"watchlist": dict(parsed_watchlist)},
                                "watchlist_add_natural",
                            ),
                            tier=35,
                            order=125,
                            specificity=3,
                            action_terms=watch_actions,
                            domain_terms=watch_domains,
                        )
                    )
                candidates.append(
                    self._candidate_from_result(
                        result,
                        tier=50,
                        order=210,
                        specificity=specificity,
                        action_terms=watch_actions,
                        domain_terms=watch_domains,
                    )
                )

        natural_word_request = bool(
            _WORD_OF_DAY_NATURAL_REQUEST.fullmatch(
                strip_bounded_request_courtesy(control)
            )
        )
        if natural_word_request or (
            has_any_keyword(control, WORD_OF_DAY_KEYWORDS)
            and _is_bounded_read_topic_request(
                control,
                WORD_OF_DAY_KEYWORDS,
                information_keywords=WORD_OF_DAY_KEYWORDS,
            )
        ):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.WORD_OF_DAY,
                        0.95,
                        {},
                        "word_of_day_keyword",
                    ),
                    tier=50,
                    order=220,
                    specificity=2,
                    domain_terms=_present_terms(control, WORD_OF_DAY_KEYWORDS),
                )
            )

        quote_list_gate = bool(
            re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?:liste\s+sitater|"
                r"(?:vis|vise)\s+(?:(?:meg|mæ)\s+)?(?:alle\s+)?"
                r"sitat(?:er|ene)|alle\s+sitater|list\s+quotes|"
                r"show\s+(?:me\s+)?(?:all\s+)?quotes|all\s+quotes|"
                r"what\s+quotes\s+have\s+i\s+saved|"
                r"show\s+me\s+my\s+saved\s+quotes)\s*[?.!]*",
                control,
                re.I,
            )
        )
        quote_domain = _present_terms(
            control,
            ("sitat", "sitatet", "sitater", "sitatene", "quote", "quotes"),
        )
        quote_edit_gate = bool(
            re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}(?:endre|rediger|redigere|edit)\s+"
                r"(?:sitat|quote)\s+"
                r"\d+(?:\s+.+)?",
                control,
                re.I,
            )
        )
        quote_delete_gate = bool(re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:slett|slette|fjern|fjerne|"
            r"delete|remove)\s+(?:sitat|quote)\s+(\d+)\s*[?.!]*",
            control,
            re.I,
        ))
        quote_get_gate = bool(
            re.fullmatch(
                rf"(?:{_POLITE_COMMAND_PREFIX}(?:sitat|quote|random\s+quote|"
                r"give\s+me\s+(?:a\s+)?random\s+quote|"
                r"(?:show|vis|vise)\s+(?:(?:meg|me|mæ)\s+)?"
                r"(?:(?:et|eit|a)\s+)?(?:sitat|quote)|"
                r"husk\s+hva(?:\s+.+)?)|hva\s+sa(?:\s+.+)?|"
                r"what\s+did\s+.+?\s+say)\s*\??",
                control,
                re.I,
            )
        )
        quote_save_gate = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:husk\s+dette|"
                r"lagre\s+dette(?:\s+som\s+(?:et\s+)?sitat)?|"
                r"dette\s+må\s+huskes|"
                r"gullkorn|remember\s+this|save\s+this|"
                r"this\s+must\s+be\s+remembered|quote\s+this|"
                r"lagre\s+sitat|save\s+quote)\b",
                control,
                re.I,
            )
        )
        quote_gate = bool(
            quote_list_gate
            or quote_edit_gate
            or quote_delete_gate
            or quote_get_gate
            or quote_save_gate
        )
        parsed_quote = None
        if quote_gate:
            parsed_quote = self._safe_parse(
                errors,
                rejections,
                "parse_quote_command",
                "quote",
                getattr(self.monitor, "parse_quote_command", None),
                text,
            )
        if parsed_quote is not None and not isinstance(parsed_quote, dict):
            self._append_invalid_payload(
                rejections,
                intent=BotIntent.QUOTE,
                family="quote",
                tier=50,
                order=260,
            )
            parsed_quote = None
        leading_save = self._parse_leading_quote_save(text)
        if leading_save is not None:
            parsed_quote = leading_save
        if isinstance(parsed_quote, dict):
            action = parsed_quote.get("action")
            action_is_live = isinstance(action, str) and {
                "list": quote_list_gate,
                "edit": quote_edit_gate,
                "delete": quote_delete_gate,
                "save": quote_save_gate,
                "get": quote_get_gate,
            }.get(action, False)
            if not action_is_live:
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.QUOTE,
                    family="quote",
                    tier=50,
                    order=260,
                )
                parsed_quote = None
        if isinstance(parsed_quote, dict):
            action = parsed_quote.get("action")
            if action == "save" and not (
                isinstance(parsed_quote.get("text"), str)
                and parsed_quote["text"].strip()
            ):
                self._append_invalid_payload(
                    rejections,
                    intent=BotIntent.QUOTE,
                    family="quote",
                    tier=50,
                    order=260,
                )
                parsed_quote = None
            elif action in {"save", "get", "list", "edit", "delete"}:
                intent, reason, order, specificity = {
                    "list": (
                        BotIntent.QUOTE_LIST,
                        "quote_list_keyword",
                        230,
                        2,
                    ),
                    "edit": (
                        BotIntent.QUOTE_EDIT,
                        "quote_edit_keyword",
                        240,
                        3,
                    ),
                    "delete": (
                        BotIntent.QUOTE_DELETE,
                        "quote_delete_keyword",
                        250,
                        3,
                    ),
                    "save": (BotIntent.QUOTE, "quote_parser", 260, 3),
                    "get": (BotIntent.QUOTE, "quote_parser", 260, 1),
                }[action]
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            intent,
                            0.95 if action in {"list", "edit", "delete"} else 0.9,
                            {"quote": dict(parsed_quote)},
                            reason,
                        ),
                        tier=50,
                        order=order,
                        specificity=specificity,
                        action_terms=_present_terms(
                            control,
                            (
                                "husk",
                                "lagre",
                                "remember",
                                "save",
                                "quote this",
                                "endre",
                                "rediger",
                                "redigere",
                                "edit",
                                "slett",
                                "slette",
                                "fjern",
                                "fjerne",
                                "delete",
                                "remove",
                            ),
                        ),
                        domain_terms=quote_domain or _present_terms(
                            control,
                            ("gullkorn", "dette", "hva sa", "what did", "say"),
                        ),
                    )
                )

        natural_aurora_request = bool(
            _AURORA_NATURAL_REQUEST.fullmatch(
                strip_bounded_request_courtesy(control)
            )
        )
        if natural_aurora_request or (
            has_any_keyword(control, AURORA_KEYWORDS)
            and _is_bounded_read_topic_request(
                control,
                AURORA_KEYWORDS,
                information_keywords=(
                    "nordlysvarsel",
                    "nordlysvarselet",
                    "aurora forecast",
                    "northern lights forecast",
                ),
            )
        ):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.AURORA,
                        0.9,
                        {},
                        "aurora_keyword",
                    ),
                    tier=50,
                    order=270,
                    specificity=1,
                    domain_terms=_present_terms(control, AURORA_KEYWORDS),
                )
            )
        if has_any_keyword(
            control,
            SCHOOL_HOLIDAYS_KEYWORDS,
        ) and _is_bounded_school_holiday_request(control):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.SCHOOL_HOLIDAYS,
                        0.9,
                        {},
                        "school_holidays_keyword",
                    ),
                    tier=50,
                    order=280,
                    specificity=1,
                    domain_terms=_present_terms(
                        control, SCHOOL_HOLIDAYS_KEYWORDS
                    ),
                )
            )

        return CollectorOutput(
            candidates=tuple(candidates),
            parser_errors=tuple(errors),
            rejections=tuple(rejections),
        )

    def _collect_utility_candidates(
        self, context: CollectorContext
    ) -> CollectorOutput:
        control = context.utterance.control_text.strip()
        text = context.utterance.text
        candidates: list[IntentCandidate] = []
        errors: list[str] = []
        rejections: list[CandidateRejection] = []

        price_gate = bool(
            re.search(
                r"\b(?:pris(?:en)?|price|verdi(?:en)?|value|kurs(?:en)?|"
                r"koster|kostar|how\s+much\s+(?:is|does)|bitcoin|"
                r"ethereum|btc|eth|krypto|crypto)\b",
                control,
                re.I,
            )
        )
        if price_gate:
            parsed = self._safe_parse(
                errors,
                rejections,
                "parse_price_command",
                "price",
                getattr(self.monitor, "parse_price_command", None),
                text,
            )
            if parsed:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.PRICE,
                            0.88,
                            {"price": parsed},
                            "price_parser",
                        ),
                        tier=60,
                        order=290,
                        specificity=3,
                        domain_terms=_present_terms(
                            control,
                            (
                                "bitcoin",
                                "ethereum",
                                "btc",
                                "eth",
                                "krypto",
                                "crypto",
                                "pris",
                                "prisen",
                                "price",
                                "verdi",
                                "verdien",
                                "value",
                                "kurs",
                                "kursen",
                                "how much",
                            ),
                        ),
                    )
                )

        horoscope_gate = bool(
            re.search(
                r"\b(?:horoskop(?:et)?|horoscope|stjernetegn(?:et)?)\b",
                control,
                re.I,
            )
        )
        if horoscope_gate:
            parsed = self._safe_parse(
                errors,
                rejections,
                "parse_horoscope_command",
                "horoscope",
                getattr(self.monitor, "parse_horoscope_command", None),
                text,
            )
            if parsed:
                target = parsed.get("sign") if isinstance(parsed, dict) else None
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.HOROSCOPE,
                            0.88,
                            {"horoscope": parsed},
                            "horoscope_parser",
                        ),
                        tier=60,
                        order=300,
                        specificity=3 if target else 2,
                        domain_terms=_present_terms(
                            control,
                            (
                                "horoskop",
                                "horoskopet",
                                "horoscope",
                                "stjernetegn",
                                "stjernetegnet",
                            ),
                        ),
                    )
                )

        compliment_gate = bool(
            re.search(
                r"\b(?:kompliment|compliment|skryt|roast)\b", control, re.I
            )
        )
        if compliment_gate:
            parsed = self._safe_parse(
                errors,
                rejections,
                "parse_compliment_command",
                "compliment",
                getattr(self.monitor, "parse_compliment_command", None),
                text,
            )
            if parsed:
                target = None
                if isinstance(parsed, dict):
                    target = parsed.get("user") or parsed.get("person")
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.COMPLIMENT,
                            0.86,
                            {"compliment": parsed},
                            "compliment_parser",
                        ),
                        tier=60,
                        order=310,
                        specificity=3 if target else 2,
                        domain_terms=_present_terms(
                            control, ("kompliment", "compliment", "skryt", "roast")
                        ),
                    )
                )

        calculator_gate = bool(
            re.search(
                r"(?:\b(?:regn(?:e)?\s+ut|rekn(?:e)?\s+ut|calculate|"
                r"calc|compute|work\s+out|kalk(?:uler(?:e)?)?|"
                r"(?:hva|kva|ka)\s+er|what\s+is|konverter(?:e)?|"
                r"convert|omgjør|gjør\s+om|gjer\s+om)\b|"
                r"\d\s*[+x×*/^-]\s*\d)",
                control,
                re.I,
            )
            or re.fullmatch(
                rf"{_POLITE_COMMAND_PREFIX}"
                r"[+-]?\d+(?:[.,]\d+)?\s*"
                r"(?:[A-Za-z]{1,5}|°\s*[CFK])\s+"
                r"(?:til|to|i|in)\s+(?:[A-Za-z]{1,5}|°\s*[CFK])"
                r"\s*[?.!]*",
                control,
                re.I,
            )
        )
        if calculator_gate:
            parsed = self._safe_parse(
                errors,
                rejections,
                "parse_calculator_command",
                "calculator",
                getattr(self.monitor, "parse_calculator_command", None),
                text,
            )
            if parsed:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CALCULATOR,
                            0.9,
                            {"calculator": parsed},
                            "calculator_parser",
                        ),
                        tier=60,
                        order=320,
                        specificity=3,
                        domain_terms=_present_terms(
                            control,
                            (
                                "regn ut",
                                "regne ut",
                                "rekn ut",
                                "rekne ut",
                                "calculate",
                                "calc",
                                "compute",
                                "work out",
                                "kalk",
                                "kalkuler",
                                "kalkulere",
                                "hva er",
                                "kva er",
                                "ka er",
                                "what is",
                                "konverter",
                                "konvertere",
                                "convert",
                                "omgjør",
                                "gjør om",
                                "gjer om",
                            ),
                        ),
                    )
                )

        shorten_gate = EXPLICIT_SHORTEN.search(control)
        if shorten_gate:
            parsed = self._safe_parse(
                errors,
                rejections,
                "parse_shorten_command",
                "shorten",
                getattr(self.monitor, "parse_shorten_command", None),
                text,
            )
            if parsed:
                action = (
                    "forkorte"
                    if _phrase_present(control, "forkorte")
                    else (
                        "forkort"
                        if _phrase_present(control, "forkort")
                        else "shorten"
                    )
                )
                url_match = re.search(r"https?://[^\s]+", control, re.I)
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.SHORTEN_URL,
                            0.9,
                            {"shorten": parsed},
                            "shorten_parser",
                        ),
                        tier=60,
                        order=330,
                        specificity=3,
                        action_terms=(action,),
                        domain_terms=(url_match.group(0),) if url_match else (),
                    )
                )

        if has_any_keyword(
            control,
            DAILY_DIGEST_KEYWORDS,
        ) and _is_bounded_read_topic_request(
            control,
            DAILY_DIGEST_KEYWORDS,
        ):
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.DAILY_DIGEST,
                        0.9,
                        {},
                        "daily_digest_keyword",
                    ),
                    tier=60,
                    order=340,
                    specificity=2,
                    domain_terms=_present_terms(control, DAILY_DIGEST_KEYWORDS),
                )
            )

        vague = bool(VAGUE_WHAT_HAPPENS.fullmatch(control))
        transit = INFORMATION_TRANSIT.match(control)
        if transit:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.SEARCH,
                        0.92,
                        {
                            "search": {
                                "query": text.rstrip("?"),
                                "type": "web",
                            }
                        },
                        "information_search_natural",
                    ),
                    tier=80,
                    order=361,
                    specificity=2,
                    domain_terms=_present_terms(
                        control,
                        ("tog", "toget", "buss", "bussen", "train", "bus"),
                    ),
                )
            )

        date_filtered_calendar_question = bool(
            re.fullmatch(
                r"(?:har\s+(?:jeg|eg|æ)\s+noe\s+i\s+kalenderen|"
                r"(?:hva|kva|ka)\s+skjer\s+i\s+kalenderen(?:\s+min)?)\s+"
                r"(?:i\s+morgen|i\s+morgon)\s*[?.!]*",
                control,
                re.I,
            )
        )
        search_gate = bool(
            not vague
            and not date_filtered_calendar_question
            and re.search(
                r"\b(?:nyheter|news|søk|search|hva skjer i|hvem vant|"
                r"resultatet|hvordan gikk|hva er status|hvor mye koster|"
                r"hva koster|kva kostar|når|hvor|hvordan|hvem|fortell meg om|"
                r"hva vet du om)\b",
                control,
                re.I,
            )
        )
        if search_gate:
            parsed = self._safe_parse(
                errors,
                rejections,
                "detect_search_intent",
                "search",
                getattr(self.monitor, "detect_search_intent", None),
                text,
            )
            if parsed and self._looks_contextual_enough_for_search(
                control, parsed
            ):
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.SEARCH,
                            0.72,
                            {"search": parsed},
                            "search_intent",
                        ),
                        tier=80,
                        order=360,
                        specificity=1,
                        domain_terms=_present_terms(
                            control,
                            ("nyheter", "news", "søk", "search", "når", "hvor", "hvem"),
                        ),
                    )
                )

        direct_weather_location = False
        weather_location_match = re.fullmatch(
            r"(?:vær(?:et)?|vêret|værmelding|weather)\s+"
            r"(?:i|in|for)\s+(?P<location>[^?!.]+?)\s*[?!.]*",
            control,
            re.I,
        )
        if weather_location_match is not None:
            location = weather_location_match.group("location").strip()
            from features.weather_api import extract_city

            city = extract_city(location)
            direct_weather_location = bool(
                city is not None and location.casefold() == city.casefold()
            )

        future_weather_request = bool(
            has_bounded_future_weather_request(context.utterance)
            and context.semantics.speech_act
            in {SpeechAct.DIRECTIVE, SpeechAct.INFORMATION_REQUEST}
        )
        if future_weather_request:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        1.0,
                        {
                            "clarification": (
                                "Jeg kan vise forholdene nå, men denne "
                                "handlingen støtter ikke en datofestet "
                                "værprognose ennå. Spør om været nå, eller "
                                "bruk en egen værtjeneste for fremtidsvarsel."
                            )
                        },
                        "weather_future_date_unsupported",
                    ),
                    tier=10,
                    order=26,
                    specificity=4,
                    domain_terms=_present_terms(
                        control,
                        (
                            "weather",
                            "forecast",
                            "rain",
                            "umbrella",
                            "vær",
                            "været",
                            "vêret",
                            "regn",
                            "paraply",
                        ),
                    ),
                )
            )

        natural_weather_match = re.fullmatch(
            r"what['’]s\s+the\s+weather\s+like\s*[?.!]*|"
            r"(?:will\s+it|is\s+it\s+going\s+to)\s+rain"
            r"(?:\s+today)?\s*[?.!]*|"
            r"do\s+i\s+need\s+(?:an?\s+)?umbrella"
            r"(?:\s+today)?\s*[?.!]*|"
            r"what(?:\s+is|['’]s)\s+(?:the\s+)?forecast"
            r"(?:\s+today)?\s*[?.!]*|"
            r"what\s+is\s+the\s+weather\s+forecast\s*[?.!]*|"
            r"(?:(?:hvordan|korleis)\s+(?:er|blir)\s+(?:været|vêret)|"
            r"how['’]s\s+(?:the\s+)?weather|"
            r"how\s+is\s+(?:the\s+)?weather|"
            r"how\s+will\s+(?:the\s+)?weather\s+be|"
            r"(?:hva|kva|ka)\s+(?:er|blir)\s+(?:været|vêret)|"
            r"what\s+is\s+the\s+weather)"
            r"(?:\s+(?:i|in)\s+(?P<conditions_location>[^?!.]+?))?"
            r"\s*[?.!]*|"
            r"blir\s+det\s+regn(?:\s+i\s+dag)?\s*[?.!]*|"
            r"(?:trenger|treng)\s+(?:jeg|eg|æ)\s+"
            r"(?:(?:en|ei|ein)\s+)?paraply(?:\s+i\s+dag)?\s*[?.!]*|"
            r"(?:how\s+warm\s+is\s+it|(?:hvor|kor)\s+varmt\s+er\s+det)\s+"
            r"(?:in|i)\s+(?P<warm_location>[^?!.]+?)\s*[?.!]*",
            control,
            re.I,
        )
        natural_weather_request = natural_weather_match is not None
        weather_location = None
        if natural_weather_match is not None:
            weather_location = (
                natural_weather_match.groupdict().get("warm_location")
                or natural_weather_match.groupdict().get("conditions_location")
            )
        if weather_location:
            weather_location = weather_location.strip()
            from features.weather_api import extract_city

            warm_city = extract_city(weather_location)
            natural_weather_request = bool(
                warm_city is not None
                and weather_location.casefold() == warm_city.casefold()
            )
        dashboard_gate = bool(
            not vague
            and (
                direct_weather_location
                or natural_weather_request
                or re.fullmatch(
                rf"(?:vær|været|vêret|værmelding|weather|dashboard(?:et)?|"
                r"dashbord(?:et)?|oversikt(?:en)?|overview)|"
                rf"{_POLITE_COMMAND_PREFIX}(?:vis|vise|show|fortell|fortelje|"
                r"tell)\s+(?:(?:meg|mæ|me)\s+)?(?:(?:en|ei|an)\s+)?"
                r"(?:vær(?:et)?|vêret|weather|dashboard(?:et)?|"
                r"dashbord(?:et)?|oversikt(?:en)?|overview)"
                r"(?:\s+(?:i|in|for)\s+.+?)?\s*\??",
                control,
                re.I,
            )
            )
        )
        conversation = getattr(self.monitor, "conversation", None)
        dashboard_parser = getattr(conversation, "should_show_dashboard", None)
        if dashboard_gate and callable(dashboard_parser):
            try:
                if natural_weather_request:
                    wants_dashboard = True
                    dashboard_reason = "natural_weather_request"
                else:
                    wants_dashboard, dashboard_reason = dashboard_parser(
                        text,
                        (
                            context.channel_id
                            if context.channel_id is not None
                            else context.guild_id
                        ),
                    )
            except Exception:
                wants_dashboard, dashboard_reason = False, "default"
            if wants_dashboard:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.DASHBOARD,
                            0.9 if natural_weather_request else 0.7,
                            {"dashboard_reason": dashboard_reason},
                            "dashboard_intent",
                        ),
                        tier=80,
                        order=370,
                        specificity=2 if natural_weather_request else 1,
                        domain_terms=_present_terms(
                            control, ("dashboard", "dashbord", "oversikt", "vær", "weather")
                        ),
                    )
                )

        location_actions = _present_terms(
            control,
            (
                "bor",
                "bur",
                "bosted",
                "sted",
                "lokasjon",
                "location",
                "flytt",
                "sett",
                "sette",
                "set",
                "holder til",
                "held til",
                "live in",
                "from",
                "frå",
            ),
        )
        if location_actions:
            location_result = self._route_location_command(text)
            if location_result is not None:
                candidates.append(
                    self._candidate_from_result(
                        location_result,
                        tier=80,
                        order=380,
                        specificity=3,
                        action_terms=location_actions,
                        domain_terms=_present_terms(
                            control,
                            ("lokasjon", "location", "bor", "holder til", "fra", "from"),
                        )
                        or location_actions,
                    )
                )

        return CollectorOutput(
            candidates=tuple(candidates),
            parser_errors=tuple(errors),
            rejections=tuple(rejections),
        )

    def _collect_fallback_candidates(
        self, context: CollectorContext
    ) -> CollectorOutput:
        return CollectorOutput(
            candidates=(
                IntentCandidate(
                    BotIntent.AI_CHAT,
                    0.5,
                    90,
                    order=390,
                    payload={},
                    reason="fallback",
                    source=IntentSource.DETERMINISTIC,
                    risk=IntentRisk.READ_ONLY,
                    specificity=0,
                ),
            )
        )

    def _has_calendar_context(self, content_lower: str) -> bool:
        stripped = content_lower.strip()
        if re.fullmatch(
            r"(?:arrangementer|events|kommende|kommende arrangementer|"
            r"planlagt|planlagte|schedule)",
            stripped,
            flags=re.IGNORECASE,
        ):
            return True
        if has_any_keyword(
            content_lower,
            [
                "kalender",
                "calendar",
                "gcal",
                "schedule",
                "planned",
                "plans",
                "planlagt",
                "planer",
                "planar",
                "planene",
                "planane",
            ],
        ):
            return True
        return bool(re.search(r"\bkalenderen\b", content_lower, flags=re.IGNORECASE))

    def _extract_calendar_mutation_target(self, content_lower: str, keywords) -> Optional[str]:
        keyword_pattern = "|".join(re.escape(keyword) for keyword in sorted(keywords, key=len, reverse=True))
        match = re.match(
            rf"^(?:(?:kan du|kunne du|vennligst|please)\s+)?(?:{keyword_pattern})\s+(.+)$",
            content_lower,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        target = self._normalize_calendar_target(match.group(1))
        return target if target and len(target) > 0 else None

    def _normalize_calendar_target(self, target: str) -> str:
        target = re.sub(
            r"\s+(?:i|fra)\s+(?:kalender(?:en)?|calendar|gcal)\s*$",
            "",
            target.strip(),
            flags=re.IGNORECASE,
        )
        target = target.strip(" .!?")
        target = re.sub(r"^(?:the)\s+", "", target, flags=re.I)
        target = re.sub(
            r"^(?:møtet|meeting(?:en)?|avtalen|arrangementet|eventet)\b",
            lambda match: {
                "møtet": "møte",
                "meetingen": "meeting",
                "meeting": "meeting",
                "avtalen": "avtale",
                "arrangementet": "arrangement",
                "eventet": "event",
            }[match.group(0).casefold()],
            target,
            count=1,
            flags=re.I,
        )
        target = self._strip_wrapping_quotes(target)

        bulk_match = re.match(r"^(alle?|all|every|both)\s+(.+)$", target, flags=re.IGNORECASE)
        if bulk_match:
            bulk_target = self._strip_wrapping_quotes(bulk_match.group(2).strip())
            return f"{bulk_match.group(1)} {bulk_target}".strip()

        return target

    def _strip_wrapping_quotes(self, value: str) -> str:
        return self._unwrap_supported_quote(value)[0]

    def _unwrap_supported_quote(self, value: str) -> tuple[str, bool]:
        quote_pairs = (
            ('"', '"'),
            ("'", "'"),
            ("“", "”"),
            ("‘", "’"),
            ("«", "»"),
        )
        stripped = value.strip()
        for left, right in quote_pairs:
            if (
                stripped.startswith(left)
                and stripped.endswith(right)
                and len(stripped) >= 2
            ):
                return stripped[1:-1].strip(), True
        return stripped, False

    def _mask_supported_quotes(self, value: str) -> str:
        chars = list(value)
        for quote in _SUPPORTED_QUOTE_SPAN.finditer(value):
            for position in range(quote.start(), quote.end()):
                if not chars[position].isspace():
                    chars[position] = "\ufffc"
        return "".join(chars)

    def _parse_natural_calendar_edit(
        self,
        content: str,
        *,
        reference_time: datetime,
    ) -> tuple[dict[str, Any] | None, bool]:
        frame = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}"
            r"(?P<verb>endre|rediger|flytt|flytte|edit|change|move)\s+"
            r"(?P<body>.+)$",
            content,
            re.I,
        )
        if frame is None:
            return None, False

        body = frame.group("body")
        masked = self._mask_supported_quotes(body)
        connectors = list(re.finditer(r"\s+(?:til|to)\s+", masked, re.I))
        saw_invalid_temporal = False
        for connector in reversed(connectors):
            target = body[: connector.start()].strip(" .!?")
            change_text = body[connector.end() :].strip(" .!?")
            if not target or not change_text:
                continue
            change_control = normalize_utterance(change_text).control_text
            resolved = self.temporal_resolver.resolve(
                change_control,
                reference=reference_time,
            )
            if resolved.errors:
                saw_invalid_temporal = True
                continue
            residual = self.temporal_resolver.strip_temporal_evidence(
                change_control,
                reference=reference_time,
            )
            residual = re.sub(
                r"^[\s,;:–—-]+|[\s,;:–—-]+$",
                "",
                residual,
            ).casefold()
            if (
                residual not in _CALENDAR_EDIT_TEMPORAL_FILLERS
                and _CALENDAR_EDIT_KEEP_TIME.fullmatch(residual) is None
            ):
                saw_invalid_temporal = True
                continue
            changes = {
                key: value
                for key, value in (
                    ("date", resolved.date),
                    ("time", resolved.time),
                )
                if value is not None
            }
            if changes:
                return {
                    "verb": frame.group("verb"),
                    "target": target,
                    "changes": changes,
                }, False
        return None, saw_invalid_temporal

    def _parse_leading_quote_save(
        self, content: str
    ) -> dict[str, str] | None:
        match = _LEADING_QUOTE_SAVE_FRAME.fullmatch(content.strip())
        if match is None:
            return None
        payload, _ = self._unwrap_supported_quote(match.group("payload"))
        if not payload:
            return None
        frame = match.group("frame").casefold()
        return {
            "action": "save",
            "text": payload,
            "lang": (
                "no"
                if any(
                    marker in frame
                    for marker in ("husk", "lagre", "gullkorn")
                )
                else "en"
            ),
        }

    def _target_looks_like_calendar_item(
        self,
        target: str,
        scope_id: int | None,
        reference_time: datetime,
    ) -> bool:
        if self._is_reserved_delete_target(target):
            return False

        title_query = self._calendar_title_query(target)
        if not title_query:
            return False
        if title_query.isdigit():
            return True
        return self._calendar_title_matches(
            title_query, scope_id, reference_time
        )

    def _calendar_title_query(self, target: str) -> str:
        target = self._normalize_calendar_target(target)
        bulk_match = re.match(r"^(alle?|all|every|both)\s+(.+)$", target, flags=re.IGNORECASE)
        if bulk_match:
            return self._strip_wrapping_quotes(bulk_match.group(2).strip())
        return target

    def _is_reserved_delete_target(self, target: str) -> bool:
        return has_any_keyword(
            target,
            (
                "poll",
                "avstemning",
                "påminnelse",
                "påminnelser",
                "reminder",
                "reminders",
                "sitat",
                "quote",
                "quotes",
                "watchlist",
                "minne",
                "memory",
                "brukerminne",
            ),
        )

    def _calendar_title_matches(
        self,
        title_query: str,
        scope_id: int | None,
        reference_time: datetime,
    ) -> bool:
        calendar = getattr(self.monitor, "calendar", None)
        if not calendar:
            return False

        try:
            if hasattr(calendar, "get_upcoming"):
                items = calendar.get_upcoming(
                    scope_id,
                    days=365,
                    reference_time=reference_time,
                )
                return any(title_query.lower() in str(item.get("title", "")).lower() for item in items)
            if hasattr(calendar, "search_items"):
                return bool(calendar.search_items(title_query))
        except Exception:
            return False

        return False

    def _calendar_unique_title_match(
        self,
        title_query: str,
        scope_id: int | None,
        reference_time: datetime,
    ) -> bool:
        calendar = getattr(self.monitor, "calendar", None)
        if not calendar or not hasattr(calendar, "get_upcoming"):
            return False
        try:
            items = calendar.get_upcoming(
                scope_id,
                days=365,
                reference_time=reference_time,
            )
        except Exception:
            return False
        folded = title_query.casefold()
        matches = [
            item
            for item in items
            if folded in str(item.get("title", "")).casefold()
        ]
        return len(matches) == 1

    def _route_memory_command(self, content: str) -> Optional[IntentResult]:
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()
        lower = re.sub(r"\s+", " ", cleaned.lower()).strip(" .!?")

        delete_commands = {"slett minnet mitt", "slett brukerminne", "glem meg"}
        confirmed_delete_commands = {
            "slett minnet mitt bekreft",
            "slett brukerminne bekreft",
            "glem meg bekreft",
            "slett minnet mitt confirm",
            "slett brukerminne confirm",
            "glem meg confirm",
        }
        natural_delete = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:slett|slette|delete)\s+"
            r"(?:minnet\s+mitt|brukerminne|my\s+memory)",
            lower,
            re.I,
        )
        natural_forget = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:glem|glemme|gløym|gløyme|forget)\s+"
            r"(?:meg|mæ|me)",
            lower,
            re.I,
        )
        if (
            lower in delete_commands
            or lower in confirmed_delete_commands
            or natural_delete
            or natural_forget
        ):
            return IntentResult(
                BotIntent.MEMORY_DELETE,
                0.99,
                {"memory": {"action": "delete"}},
                "memory_delete_keyword",
            )
        memory_export = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:eksporter|eksportere|export)\s+"
            r"(?:minnet\s+mitt|brukerminne|my\s+memory)",
            lower,
            re.I,
        )
        if memory_export:
            return IntentResult(
                BotIntent.MEMORY_EXPORT,
                0.99,
                {"memory": {"action": "export"}},
                "memory_export_keyword",
            )
        memory_view = re.fullmatch(
            r"(?:vis\s+minnet\s+mitt|mitt\s+minne|brukerminne|"
            r"hva\s+(?:husker|vet)\s+du\s+om\s+meg|"
            r"kva\s+(?:hugsar|veit)\s+du\s+om\s+meg|"
            r"what\s+do\s+you\s+(?:remember|know)\s+about\s+me|"
            r"(?:(?:kan|kunne|vil)\s+du\s+)?(?:vis|vise)\s+"
            r"(?:(?:meg|mæ)\s+)?(?:hva\s+du\s+husker|"
            r"kva\s+du\s+hugsar)\s+om\s+meg|"
            r"(?:(?:can|could|would|will)\s+you\s+)?show\s+"
            r"(?:me\s+)?what\s+you\s+remember\s+about\s+me)",
            lower,
            re.I,
        )
        if memory_view:
            return IntentResult(
                BotIntent.MEMORY_VIEW,
                0.99,
                {"memory": {"action": "view"}},
                "memory_view_keyword",
            )
        return None

    def _route_local_search_command(self, content: str) -> Optional[IntentResult]:
        cleaned = re.sub(r"<@!?\d+>", "", content)
        cleaned = cleaned.replace("@inebotten", "").strip()

        natural_calendar_match = re.fullmatch(
            rf"{_BOUNDED_SEARCH_REQUEST_SHELL}"
            r"(?:søk|søke|søkje|search)\s+"
            r"(?:i|in)\s+(?:kalenderen|calendar)\s+"
            r"(?:etter|for)\s+(.+?)\s*[?.!]*",
            cleaned,
            flags=re.IGNORECASE,
        )
        if natural_calendar_match:
            query = _clean_bounded_search_query(
                natural_calendar_match.group(1)
            )
            if query:
                return IntentResult(
                    BotIntent.CALENDAR_SEARCH,
                    0.98,
                    {"query": query},
                    "calendar_search_natural",
                )

        natural_reminder_match = re.fullmatch(
            rf"{_BOUNDED_SEARCH_REQUEST_SHELL}"
            r"(?:finn|find)\s+(?:påminnelsen|påminninga|"
            r"the\s+reminder|reminder)\s+(?:om|about)\s+"
            r"(.+?)\s*[?.!]*",
            cleaned,
            flags=re.IGNORECASE,
        )
        if natural_reminder_match:
            query = _clean_bounded_search_query(
                natural_reminder_match.group(1)
            )
            if query:
                return IntentResult(
                    BotIntent.REMINDER_SEARCH,
                    0.98,
                    {"reminder": {"action": "search", "query": query}},
                    "reminder_search_natural",
                )

        natural_web_match = re.fullmatch(
            rf"{_BOUNDED_SEARCH_REQUEST_SHELL}{_SEARCH_ACTION}\s+"
            r"(?:på\s+nett(?:et)?|(?:the\s+)?web)\s+(?:etter|for)\s+"
            r"(.+?)\s*[?.!]*",
            cleaned,
            flags=re.IGNORECASE,
        )
        if natural_web_match:
            query = _clean_bounded_search_query(natural_web_match.group(1))
            if query:
                return IntentResult(
                    BotIntent.SEARCH,
                    0.98,
                    {"search": {"query": query, "type": "web"}},
                    "web_search_natural",
                )

        reminder_match = re.match(
            rf"^{_BOUNDED_SEARCH_REQUEST_SHELL}"
            r"(?:søk|søke|søkje|search)\s+"
            r"(?:påminnelse|påminnelser|reminder|reminders)\s+"
            r"(?:(?:etter|for|om|about)\s+)?(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if reminder_match:
            query = _clean_bounded_search_query(reminder_match.group(1))
            if query:
                return IntentResult(
                    BotIntent.REMINDER_SEARCH,
                    0.98,
                    {
                        "reminder": {
                            "action": "search",
                            "query": query,
                        }
                    },
                    "reminder_search_keyword",
                )

        calendar_match = re.match(
            rf"^{_BOUNDED_SEARCH_REQUEST_SHELL}"
            r"(?:søk|søke|søkje|search)\s+"
            r"(?:kalender|calendar)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if calendar_match:
            query = _clean_bounded_search_query(calendar_match.group(1))
            if query:
                return IntentResult(
                    BotIntent.CALENDAR_SEARCH,
                    0.98,
                    {"query": query},
                    "calendar_search_keyword",
                )

        web_match = re.match(
            rf"^{_BOUNDED_SEARCH_REQUEST_SHELL}"
            r"(?:(?:søk|søke|søkje)\s+på\s+nett(?:et)?|"
            r"search\s+(?:the\s+)?web)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if web_match:
            query = _clean_bounded_search_query(web_match.group(1))
            if query:
                return IntentResult(
                    BotIntent.SEARCH,
                    0.96,
                    {"search": {"query": query, "type": "web"}},
                    "explicit_web_search_keyword",
                )

        bare_match = _BOUNDED_BARE_SEARCH_REQUEST.fullmatch(cleaned)
        if bare_match:
            query = _clean_bounded_search_query(bare_match.group("query"))
            if query:
                return IntentResult(
                    BotIntent.SEARCH,
                    0.95,
                    {"search": {"query": query, "type": "web"}},
                    "bare_web_search_keyword",
                )

        return None

    def _matches_active_calendar_auth_flow(
        self,
        context: CollectorContext,
    ) -> bool:
        if (
            context.channel_id is None
            or context.user_id is None
            or isinstance(context.channel_id, bool)
            or not isinstance(context.channel_id, int)
            or isinstance(context.user_id, bool)
            or not isinstance(context.user_id, int)
        ):
            return False
        calendar = getattr(self.monitor, "calendar", None)
        gcal = getattr(calendar, "gcal", None)
        checker = getattr(gcal, "has_active_auth_flow", None)
        if not callable(checker):
            return False
        try:
            return checker(
                context.user_id,
                context.channel_id,
                reference_time=context.reference_time,
            ) is True
        except Exception:
            return False

    def _has_active_reminders(self, scope_id: int | None) -> bool:
        reminders = getattr(self.monitor, "reminders", None)
        if not reminders or not hasattr(reminders, "get_active_reminders"):
            return False
        try:
            return bool(reminders.get_active_reminders(scope_id))
        except Exception:
            return False

    def _has_calendar_target_number(
        self,
        number: int,
        scope_id: int | None,
        reference_time: datetime,
    ) -> bool:
        """Check the same stable future-item index used by calendar handlers."""

        if isinstance(number, bool) or number <= 0:
            return False
        calendar = getattr(self.monitor, "calendar", None)
        if calendar is None:
            return False
        try:
            snapshot = getattr(calendar, "snapshot_target_items", None)
            if callable(snapshot):
                rows = snapshot(reference_time=reference_time)
            else:
                upcoming = getattr(calendar, "get_upcoming", None)
                if not callable(upcoming):
                    return False
                rows = upcoming(
                    scope_id,
                    days=365,
                    reference_time=reference_time,
                )
            return 1 <= number <= len(rows)
        except Exception:
            return False

    def _route_location_command(self, content: str) -> Optional[IntentResult]:
        """Detect when a user is setting their location."""
        content_lower = content.lower().strip(" .!?")
        
        # Phrases like "Jeg bor i Trondheim", "Min lokasjon er Oslo", "Sett lokasjon til Bergen"
        patterns = [
            r"(?:jeg\s+bor\s+i|eg\s+bur\s+i|min\s+lokasjon\s+er|"
            r"(?:jeg\s+holder|eg\s+held)\s+til\s+i|"
            r"jeg\s+er\s+fra|eg\s+er\s+frå)\s+([a-zæøå\s]+)",
            rf"{_POLITE_COMMAND_PREFIX}(?:sett|sette|set)\s+"
            r"(?:(?:min\s+lokasjon(?:en)?)|"
            r"(?:lokasjon(?:en)?(?:\s+min)?)|"
            r"(?:my\s+location)|location)\s+"
            r"(?:til|to)\s+([a-zæøå\s]+)",
            r"(?:i'm\s+from|i\s+live\s+in|my\s+location\s+is)\s+"
            r"([a-z\s]+)",
        ]
        
        for pattern in patterns:
            match = re.fullmatch(pattern, content_lower)
            if match:
                city = match.group(1).strip()
                # Validate if it's a known city or at least seems like one
                from features.weather_api import extract_city
                found_city = extract_city(city)
                if found_city:
                    return IntentResult(BotIntent.SET_LOCATION, 0.95, {"city": found_city}, "location_pattern")
        
        return None

    def _is_status_command(self, content_lower: str) -> bool:
        return re.fullmatch(
            rf"(?:status|bot\s+status|status\s+bot|inebotten\s+status|"
            r"health(?:\s+check)?|helse(?:sjekk)?|diagnose|diagnostics)|"
            rf"{_POLITE_COMMAND_PREFIX}(?:vis|vise|show|sjekk|check|kjør|run)\s+"
            r"(?:(?:meg|me)\s+)?(?:bot\s*)?(?:status|health(?:\s+check)?|"
            r"helse(?:sjekk)?|diagnostics)\s*[?.!]*",
            content_lower,
            re.I,
        ) is not None

    def _is_profile_command(
        self,
        content_lower: str,
        raw_content: str | None = None,
    ) -> bool:
        if self._is_status_command(content_lower):
            return False
        if re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:sett|sette|set)\s+"
            r"(?:(?:min|my)\s+)?status(?:en)?(?:\s+(?:til|to))?\s+"
            r"(?:online|offline|idle|dnd|invisible)\s*[.!?]*",
            content_lower,
            re.I,
        ):
            return True
        if re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:sett|sette|set)\s+"
            r"(?:aktivitet(?:en)?|activity)\s+(?:til|to)\s+"
            r"(?:å\s+)?(?:spille|spiller|playing|se\s+på|ser\s+på|"
            r"watching)\s+.+?\s*[.!?]*",
            content_lower,
            re.I,
        ):
            return True
        if re.fullmatch(
            r"status\s+(?:online|offline|idle|dnd|invisible)",
            content_lower,
            re.I,
        ):
            return True
        activity = re.fullmatch(
            r"(?:spiller|playing|ser\s+på|watching)\s+(.+?)\s*\??",
            content_lower,
            re.I,
        )
        if activity is None:
            return False
        value = activity.group(1).strip()
        if not value:
            return False
        # A direct activity frame is supported; a copular sentence about the
        # activity is ordinary conversation. Preserve title-like proper-case
        # values such as "Life is Strange" and "This Is Us".
        if re.search(r"\b(?:is|er)\s+\S+", value, re.I) is None:
            return True
        raw_activity = re.fullmatch(
            r"(?:spiller|playing|ser\s+på|watching)\s+(.+?)\s*\??",
            raw_content or "",
            re.I,
        )
        if raw_activity is None:
            return False
        significant_words = [
            word
            for word in re.findall(
                r"[^\W\d_][^\W_'-]*",
                raw_activity.group(1),
                re.UNICODE,
            )
            if word.casefold() not in {"is", "er"}
        ]
        return bool(significant_words) and all(
            word[0].isupper() for word in significant_words
        )

    def _active_polls(
        self,
        scope_id: int | None,
        reference_time: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        if scope_id is None:
            return ()
        try:
            rows = self.monitor.poll.get_active_polls(
                scope_id,
                reference_time=reference_time,
            )
        except Exception:
            return ()
        if not isinstance(rows, (list, tuple)):
            return ()
        return tuple(row for row in rows if isinstance(row, Mapping))

    def _has_active_poll(
        self,
        scope_id: int | None,
        reference_time: datetime,
    ) -> bool:
        return bool(self._active_polls(scope_id, reference_time))

    @staticmethod
    def _single_poll_id(
        active_polls: tuple[Mapping[str, Any], ...],
    ) -> str | None:
        if len(active_polls) != 1:
            return None
        value = active_polls[0].get("id")
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    def _parse_poll_edit_changes(
        self, content: str
    ) -> dict[str, Any] | None:
        match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:endre|rediger|redigere|edit)\s+"
            r"(?:poll(?:en)?|avstemning(?:en|a)?|"
            r"avstemming(?:en|a)?)(?:\s+(?:\d+|siste|last))?\s+"
            r"(?P<body>.+?)\s*",
            content,
            re.I,
        )
        if match is None:
            return None
        body = match.group("body")
        fields = list(_POLL_EDIT_FIELD.finditer(body))
        if not fields or body[: fields[0].start()].strip():
            return None
        aliases = {
            "spørsmål": "question",
            "question": "question",
            "alternativer": "options",
            "options": "options",
        }
        result: dict[str, Any] = {}
        for index, field in enumerate(fields):
            key = aliases[field.group("label").casefold()]
            if key in result:
                return None
            end = (
                fields[index + 1].start()
                if index + 1 < len(fields)
                else len(body)
            )
            value = body[field.end() : end].strip(" \t\r\n,;")
            if not value:
                return None
            if key == "question":
                result[key] = value
            else:
                separator = "/" if "/" in value else ","
                result[key] = [
                    option.strip()
                    for option in value.split(separator)
                    if option.strip()
                ]
        return result or None

    def _parse_poll_reference(self, content_lower: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"target": None}
        # Scoped extraction: number immediately after "poll" or "avstemning"
        number_match = re.search(
            r"(?:poll(?:en)?|avstemning(?:en|a)?|"
            r"avstemming(?:en|a)?)\s+"
            r"(?:(?:nummer|number|nr\.?|no\.?|#)\s*)?(\d+)",
            content_lower,
        )
        if number_match:
            result["target"] = int(number_match.group(1))
            return result
        # If message contains poll keywords but no scoped number, don't fall back
        # to arbitrary numbers (prevents "slett poll etter 15 minutter" → target=15)
        if has_any_keyword(
            content_lower,
            (
                "poll",
                "pollen",
                "avstemning",
                "avstemningen",
                "avstemninga",
                "avstemming",
                "avstemmingen",
                "avstemminga",
            ),
        ):
            if has_any_keyword(content_lower, ("siste", "last")):
                result["target"] = "siste"
                return result
            return result
        # Fallback for messages without poll keywords (backward compat)
        number_match = re.search(r'\b(\d+)\b', content_lower)
        if number_match:
            result["target"] = int(number_match.group(1))
            return result
        if has_any_keyword(content_lower, ("siste", "last")):
            result["target"] = "siste"
            return result
        return result

    def _looks_contextual_enough_for_search(self, content_lower: str, search_info: Dict[str, str]) -> bool:
        if search_info.get("type") == "news":
            return True
        if content_lower.strip() in {"hva skjer", "hva skjer?", "what's up", "what is up"}:
            return False
        context_markers = [
            "i", "på", "om", "for", "hos", "til", "trondheim", "oslo",
            "bergen", "tromsø", "helga", "helgen", "siste", "nå", "today",
            "fra", "fly", "flight", "reise", "travel",
        ]
        return any(re.search(rf"\b{re.escape(marker)}\b", content_lower) for marker in context_markers)
