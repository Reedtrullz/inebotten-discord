#!/usr/bin/env python3
# pyright: reportDeprecated=false, reportExplicitAny=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportAny=false, reportUnusedImport=false
"""Central intent router for Inebotten message handling."""

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import re
from typing import Any, Dict, Optional

from cal_system.natural_language_parser import NaturalParseResult
from cal_system.temporal_resolver import OSLO, TemporalResolver
from core.intent_arbitration import arbitrate_candidates

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
from core.intent_payloads import (
    ENVELOPE_KEYS,
    PayloadValidationError,
    validate_intent_payload,
)
from core.message_context import RoutingContext, domain_scope_id
from core.nlu_metrics import NLUMetrics
from core.utterance import NormalizedUtterance, normalize_utterance
from core.utterance_semantics import UtteranceSemantics, analyze_utterance

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
    r"^(?:hva|kva|ka|what)\s+(?:kan|can)\s+(?:du|you)\s+"
    r"(?:gjøre|gjere|gjør|do)\s*\??$",
    re.IGNORECASE,
)
EXPLICIT_SHORTEN = re.compile(
    r"\b(?:forkort|shorten)\b.*\bhttps?://[^\s]+", re.IGNORECASE
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
_CALENDAR_FAMILY = r"møte|avtale|kalender|påminnelse|reminder|event"
_CALENDAR_ITEM_FAMILY = (
    r"møte|møtet|avtale|avtalen|arrangement|arrangementet|"
    r"meeting|event|eventet"
)
_CALENDAR_MUTATION_FAMILY = (
    rf"{_CALENDAR_FAMILY}|arrangement|meeting"
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
            BotIntent.CALENDAR_EDIT,
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
}


def _phrase_present(text: str, phrase: str) -> bool:
    return bool(
        re.search(rf"(?<!\w){re.escape(phrase.casefold())}(?!\w)", text.casefold())
    )


def _present_terms(text: str, terms) -> tuple[str, ...]:
    return tuple(term for term in terms if _phrase_present(text, term))

class IntentRouter:
    """Routes cleaned, authorized message text to one concrete bot intent."""

    def __init__(
        self,
        monitor,
        metrics: NLUMetrics | None = None,
        *,
        temporal_resolver: TemporalResolver | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.monitor = monitor
        self.metrics = metrics or NLUMetrics()
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

        if self._has_calendar_context(control) and has_any_keyword(
            control, ("hjelp", "help", "guide")
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
        if any(_phrase_present(control, term) for term in simple_help):
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
            result = IntentResult(
                BotIntent.PROFILE, 0.95, reason="profile_keyword"
            )
            candidates.append(
                self._candidate_from_result(
                    result,
                    tier=10,
                    order=40,
                    specificity=4,
                    action_terms=_present_terms(
                        control, ("spiller", "playing", "ser på", "watching")
                    ),
                    domain_terms=_present_terms(
                        control,
                        ("status", "online", "offline", "idle", "dnd", "invisible"),
                    ),
                )
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
                        ("slett", "slette", "delete", "glem"),
                    ),
                    domain_terms=_present_terms(
                        control,
                        (
                            "minne",
                            "minnet",
                            "memory",
                            "brukerminne",
                            "glem meg",
                        ),
                    ),
                )
            )
        return CollectorOutput(candidates=tuple(candidates))

    def _collect_calendar_reminder_candidates(
        self, context: CollectorContext
    ) -> CollectorOutput:
        control = context.utterance.control_text.strip()
        text = context.utterance.text
        candidates: list[IntentCandidate] = []
        errors: list[str] = []
        rejections: list[CandidateRejection] = []

        local_search_gate = re.match(
            r"^(?:søk|search)\s+(?:påminnelse|påminnelser|påminning|"
            r"påminningar|reminder|reminders|kalender|calendar|på nett|"
            r"(?:the )?web)\b",
            control,
            re.I,
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
                            control, ("søk", "search")
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
            r"^(?:søk|search)\s+(.+)$", control, re.I
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

        reminder_gate = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:"
                r"påminn(?:e)?\s+meg|minn(?:e)?\s+(?:meg|mæ)|husk\s+(?:å|at)|"
                r"hugs\s+(?:å|at)|ikke\s+glem\s+(?:å|at)|"
                r"ikkje\s+gløym\s+(?:å|at)|(?:don't|don’t)\s+forget\s+(?:to|that)|"
                r"remind\s+me|remember\s+to|"
                r"(?:endre|rediger|edit|slett|fjern|delete|remove|"
                r"ferdig|fullfør|fullført|done|complete|gjort)\s+"
                r"(?:the\s+)?(?:påminnelse|påminnelsen|påminning|"
                r"påminninga|reminder)|"
                r"(?:vis|list|show|søk|search)?\s*"
                r"(?:påminnelser|påminningar|reminders|gjøremål|todos|"
                r"huskeliste)|(?:påminnelse|påminning|reminder|gjøremål|todo)\b)",
                control,
                re.I,
            )
        )
        parsed_reminder = None
        if reminder_gate:
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

        explicit_reminder_list = re.fullmatch(
            r"(?:(?:vis|list|show)\s+)?(?:påminnelser|påminningar|"
            r"reminders|gjøremål|todos|huskeliste)\s*\??",
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
                        control, ("vis", "list", "show")
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
            if (
                parsed_reminder.get("action") == "add"
                and isinstance(parsed_reminder.get("text"), str)
                and re.fullmatch(
                    r"(?:det|that|dette|den|it)(?:\s+.*)?",
                    parsed_reminder["text"].strip(),
                    re.I,
                )
            ):
                topic = self._infer_recent_reminder_topic(
                    channel_id=context.channel_id,
                    user_id=context.user_id,
                )
                if topic:
                    parsed_reminder = dict(parsed_reminder)
                    parsed_reminder["text"] = topic[0].upper() + topic[1:]
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
                    "hugs",
                    "glem",
                    "gløym",
                    "forget",
                    "remind",
                    "remember",
                    "endre",
                    "rediger",
                    "edit",
                    "slett",
                    "fjern",
                    "delete",
                    "remove",
                    "ferdig",
                    "fullfør",
                    "fullført",
                    "done",
                    "complete",
                    "gjort",
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

        if control.isdigit() and self._has_active_reminders(
            context.domain_scope_id
        ):
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
            r"(?:ferdig|fullført|fullfør|done|complete|gjort)\s+(\d+)",
            control,
            re.I,
        )
        if active_complete and self._has_active_reminders(
            context.domain_scope_id
        ):
            number = int(active_complete.group(1))
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
                        ),
                    ),
                    domain_terms=(str(number),),
                )
            )

        auth_match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:(?:kalender|gcal)\s+"
            r"(?:(?:auth|login)(?:\s+(?P<auth_code>[4/a-z0-9_-]+))?|"
            r"(?:kode|code)(?:\s+(?P<label_code>[4/a-z0-9_-]+))?)|"
            r"kalenderkode(?:\s+(?P<compact_code>[4/a-z0-9_-]+))?)\s*\??",
            text.strip(),
            re.I,
        )
        if auth_match:
            auth_code = next(
                (
                    auth_match.group(name)
                    for name in ("auth_code", "label_code", "compact_code")
                    if auth_match.group(name)
                ),
                None,
            )
            if (
                isinstance(auth_code, str)
                and auth_code.casefold() in _RESERVED_CALENDAR_AUTH_CODES
            ):
                auth_match = None
        if auth_match:
            result = IntentResult(
                BotIntent.CALENDAR_AUTH,
                0.99,
                {"auth_code": auth_code},
                "calendar_auth_keyword",
            )
            candidates.append(
                self._candidate_from_result(
                    result,
                    tier=20,
                    order=100,
                    specificity=4,
                    action_terms=_present_terms(
                        control, ("auth", "kode", "code", "login")
                    )
                    or (("kalenderkode",) if _phrase_present(
                        control, "kalenderkode"
                    ) else ()),
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

        clear_match = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}(?:(?:slett|slette|delete|tøm|clear)\s+"
            r"(?:hele\s+|the\s+)?(?:kalenderen|kalender|calendar)|"
            r"(?:kalenderen|kalender|calendar)\s+(?:slett|fjern)\s+alt|"
            r"(?:kalenderen|kalender|calendar)\s+(?:tøm|clear))\s*\??",
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
                    else (target,)
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

        if self._has_calendar_context(control):
            list_terms = _present_terms(control, LIST_KEYWORDS)
            no_mutation = not calendar_actions and not clear_match
            if list_terms and no_mutation:
                candidates.append(
                    self._candidate_from_result(
                        IntentResult(
                            BotIntent.CALENDAR_LIST,
                            0.92,
                            {},
                            "calendar_list_keyword",
                        ),
                        tier=30,
                        order=118,
                        specificity=2,
                        action_terms=list_terms,
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

        birthday_edit = re.fullmatch(
            rf"{_POLITE_COMMAND_PREFIX}"
            r"(?P<verb>endre|rediger|oppdater|edit|update)\s+"
            r"(?P<domain>bursdag(?:en)?|birthday)"
            r"(?:\s+(?P<target>.+?\s+\d{1,2}\.\d{1,2}"
            r"(?:\.\d{2,4})?))?\s*\??",
            text.strip(),
            re.I,
        )
        if birthday_edit:
            candidates.append(
                self._candidate_from_result(
                    IntentResult(
                        BotIntent.CLARIFY,
                        0.95,
                        {},
                        "birthday_identity_required",
                    ),
                    tier=30,
                    order=120,
                    specificity=(
                        3 if birthday_edit.group("target") else 2
                    ),
                    action_terms=_present_terms(
                        control,
                        ("endre", "rediger", "oppdater", "edit", "update"),
                    ),
                    domain_terms=_present_terms(
                        control, ("bursdag", "bursdagen", "birthday")
                    ),
                )
            )

        calendar_create_frame = re.match(
            rf"^{_POLITE_COMMAND_PREFIX}(?:(?:lag|opprett|create|add)\s+)?"
            rf"(?:{_CALENDAR_ITEM_FAMILY})\b",
            control,
            re.I,
        ) or re.match(
            rf"^(?:ikke\s+glem|ikkje\s+gløym)\s+"
            rf"(?:{_CALENDAR_ITEM_FAMILY})\b",
            control,
            re.I,
        )
        task_create_frame = re.match(
            r"^(?:jeg\s+må|eg\s+må|i\s+need\s+to)\b",
            control,
            re.I,
        )
        calendar_parse_gate = bool(calendar_create_frame or task_create_frame)
        calendar_item = None
        if calendar_parse_gate:
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
            calendar_item = self._resolve_calendar_followup(
                text,
                calendar_item,
                channel_id=context.channel_id,
                user_id=context.user_id,
            )
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
                    "opprett",
                    "create",
                    "add",
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

        poll_domain = _present_terms(control, ("poll", "avstemning"))
        poll_list_alias = (
            r"(?:polls|avstemninger|active polls|vis poll|"
            r"vis avstemning|list poll|poll liste|poll list|"
            r"avstemning liste)"
        )
        poll_list_gate = bool(
            re.fullmatch(poll_list_alias, control, re.I)
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
                rf"^{_POLITE_COMMAND_PREFIX}(?:endre|rediger|edit|slett|"
                r"delete|fjern|remove|lukk|close|avslutt|steng)\s+"
                r"(?:poll|avstemning)\b",
                control,
                re.I,
            )
        )
        active_polls = (
            self._active_polls(
                context.domain_scope_id,
                context.reference_time,
            )
            if poll_list_gate or control.isdigit() or poll_domain
            else ()
        )
        single_poll_id = self._single_poll_id(active_polls)
        if poll_list_gate and active_polls:
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
                    r"(?:(?:lag|opprett|ny|create)\s+)?"
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
                            ("lag", "opprett", "create", "ny"),
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
                            ("lag", "opprett", "create", "ny"),
                        ),
                        domain_terms=poll_domain,
                    )
                )

        if control.isdigit() and single_poll_id is not None:
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
                        domain_terms=(control,),
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
                    ("endre", "rediger", "edit"),
                    BotIntent.POLL_EDIT,
                    "poll_edit",
                    "poll_edit_keyword",
                    170,
                ),
                (
                    ("slett", "delete", "fjern", "remove"),
                    BotIntent.POLL_DELETE,
                    "poll_delete",
                    "poll_delete_keyword",
                    180,
                ),
                (
                    ("lukk", "close", "avslutt", "steng"),
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
                    r"(?:poll|avstemning)\b",
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
                r"\b(?:hvor lenge|countdown|dager til|days until)\b",
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
                            ("hvor lenge", "countdown", "dager til", "days until"),
                        ),
                        domain_terms=(str(target),) if target else (),
                    )
                )

        watchlist_status_gate = bool(
            re.fullmatch(
                r"(?:(?:vis|list|show)\s+)?(?:(?:min|the)\s+)?"
                r"(?:watchlist|watchlista|watch\s+list)|"
                r"hva\s+har\s+vi\s+(?:på|i)\s+watchlist",
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
                r".+?\s+(?:på|i)\s+watchlist|"
                rf"{_POLITE_COMMAND_PREFIX}add\s+.+?\s+to\s+(?:the\s+)?watchlist|"
                r"(?:husk\s+å\s+se|hugs\s+å\s+sjå|remember\s+to\s+watch)"
                r"(?:\s+.*)?|"
                r"legg\s+til\s+(?:film|filmen|serie|serien)(?:\s+.*)?|"
                r".*(?:på|i)\s+watchlist|"
                r".*to\s+(?:the\s+)?watchlist)\s*\??",
                control,
                re.I,
            )
        )
        watchlist_remove_gate = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:fjern|fjerne|slett|slette|"
                r"remove|delete)\s+(?:film|filmen|serie|serien|movie|show|watchlist)\b",
                control,
                re.I,
            )
            or re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:fjern|fjerne|slett|slette|"
                r"remove|delete)\s+(?:nummer|number|nr\.?|no\.?|#)?\s*"
                r"\d+\s+(?:fra|from)\s+watchlist\b",
                control,
                re.I,
            )
        )
        watchlist_edit_gate = bool(
            re.match(
                rf"^{_POLITE_COMMAND_PREFIX}(?:endre|rediger|edit|change)\s+"
                r"(?:film|filmen|serie|serien|movie|show|watchlist)\b",
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
                        "hugs",
                        "remember",
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
                        "film",
                        "filmen",
                        "serie",
                        "serien",
                        "movie",
                        "show",
                        "husk å se",
                        "hugs å sjå",
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

        if has_any_keyword(control, WORD_OF_DAY_KEYWORDS):
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
                r"(?:liste\s+sitater|vis\s+sitater|alle\s+sitater|"
                r"list\s+quotes|show\s+quotes|all\s+quotes)",
                control,
                re.I,
            )
        )
        quote_domain = _present_terms(control, ("sitat", "quote"))
        quote_edit_gate = bool(
            re.fullmatch(
                r"(?:endre|rediger|edit)\s+(?:sitat|quote)\s+"
                r"\d+(?:\s+.+)?",
                control,
                re.I,
            )
        )
        quote_delete_gate = bool(re.fullmatch(
            r"(?:slett|fjern|delete|remove)\s+(?:sitat|quote)\s+(\d+)",
            control,
            re.I,
        ))
        quote_get_gate = bool(
            re.fullmatch(
                r"(?:sitat|quote|random\s+quote|show\s+quote|vis\s+sitat|"
                r"vis\s+quote|husk\s+hva(?:\s+.+)?|hva\s+sa(?:\s+.+)?|"
                r"what\s+did\s+.+?\s+say)\s*\??",
                control,
                re.I,
            )
        )
        quote_save_gate = bool(
            re.match(
                r"^(?:husk\s+dette|lagre\s+dette|dette\s+må\s+huskes|"
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
                                "edit",
                                "slett",
                                "fjern",
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

        if has_any_keyword(control, AURORA_KEYWORDS):
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
        if has_any_keyword(control, SCHOOL_HOLIDAYS_KEYWORDS):
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
                r"\b(?:pris|price|koster|kostar|bitcoin|ethereum|btc|eth|"
                r"krypto|crypto)\b",
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
                                "price",
                            ),
                        ),
                    )
                )

        horoscope_gate = bool(
            re.search(r"\b(?:horoskop|horoscope|stjernetegn)\b", control, re.I)
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
                            control, ("horoskop", "horoscope", "stjernetegn")
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
                r"(?:\b(?:regn ut|calculate|kalkuler|hva er)\b|"
                r"\d\s*[+*/^-]\s*\d)",
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
                            control, ("regn ut", "calculate", "kalkuler", "hva er")
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
                    "forkort"
                    if _phrase_present(control, "forkort")
                    else "shorten"
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

        if has_any_keyword(control, DAILY_DIGEST_KEYWORDS):
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

        search_gate = bool(
            not vague
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

        dashboard_gate = bool(
            not vague
            and re.search(
                r"\b(?:dashboard|dashbord|oversikt|vær|weather|hva skjer i)\b",
                control,
                re.I,
            )
        )
        conversation = getattr(self.monitor, "conversation", None)
        dashboard_parser = getattr(conversation, "should_show_dashboard", None)
        if dashboard_gate and callable(dashboard_parser):
            try:
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
                            0.7,
                            {"dashboard_reason": dashboard_reason},
                            "dashboard_intent",
                        ),
                        tier=80,
                        order=370,
                        specificity=1,
                        domain_terms=_present_terms(
                            control, ("dashboard", "dashbord", "oversikt", "vær", "weather")
                        ),
                    )
                )

        location_actions = _present_terms(
            control,
            (
                "bor",
                "bosted",
                "sted",
                "location",
                "flytt",
                "sett",
                "holder til",
                "live in",
                "from",
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
            r"(?:arrangementer|events|kommende|kommende arrangementer|planlagt|planlagte)",
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
        target = target.strip(" .")
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
        if lower in delete_commands or lower in confirmed_delete_commands:
            return IntentResult(
                BotIntent.MEMORY_DELETE,
                0.99,
                {"memory": {"action": "delete", "confirmed": lower in confirmed_delete_commands}},
                "memory_delete_keyword",
            )
        if any(phrase in lower for phrase in ("eksporter minnet mitt", "export my memory", "eksporter brukerminne")):
            return IntentResult(
                BotIntent.MEMORY_EXPORT,
                0.99,
                {"memory": {"action": "export"}},
                "memory_export_keyword",
            )
        if any(phrase in lower for phrase in ("vis minnet mitt", "mitt minne", "brukerminne", "hva husker du om meg")):
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
        lower = cleaned.lower()

        reminder_match = re.match(
            r"^(?:søk|search)\s+(?:påminnelse|påminnelser|reminder|reminders)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if reminder_match:
            query = reminder_match.group(1).strip()
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
            r"^(?:søk|search)\s+(?:kalender|calendar)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if calendar_match:
            query = calendar_match.group(1).strip()
            if query:
                return IntentResult(
                    BotIntent.CALENDAR_SEARCH,
                    0.98,
                    {"query": query},
                    "calendar_search_keyword",
                )

        web_match = re.match(
            r"^(?:søk\s+på\s+nett|search\s+(?:the\s+)?web)\s+(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if web_match:
            query = web_match.group(1).strip()
            if query:
                return IntentResult(
                    BotIntent.SEARCH,
                    0.96,
                    {"search": {"query": query, "type": "web"}},
                    "explicit_web_search_keyword",
                )

        bare_match = re.match(r"^(?:søk|search)\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if bare_match and not lower.startswith(("søk på nett", "search web", "search the web")):
            query = bare_match.group(1).strip()
            if query:
                return IntentResult(
                    BotIntent.SEARCH,
                    0.95,
                    {"search": {"query": query, "type": "web"}},
                    "bare_web_search_keyword",
                )

        return None

    def _has_active_reminders(self, scope_id: int | None) -> bool:
        reminders = getattr(self.monitor, "reminders", None)
        if not reminders or not hasattr(reminders, "get_active_reminders"):
            return False
        try:
            return bool(reminders.get_active_reminders(scope_id))
        except Exception:
            return False

    def _route_location_command(self, content: str) -> Optional[IntentResult]:
        """Detect when a user is setting their location."""
        content_lower = content.lower().strip(" .!?")
        
        # Phrases like "Jeg bor i Trondheim", "Min lokasjon er Oslo", "Sett lokasjon til Bergen"
        patterns = [
            r"(?:jeg bor i|min lokasjon er|sett (?:min )?lokasjon(?:en)? til|jeg er fra|jeg holder til i)\s+([a-zæøå\s]+)",
            r"(?:i'm from|i live in|my location is|set (?:my )?location to)\s+([a-z\s]+)"
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

    def _resolve_calendar_followup(
        self,
        content: str,
        parsed: Dict[str, Any],
        *,
        channel_id: Optional[int],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        """Replace vague follow-up titles like "det" with the recent offered reminder topic."""
        title = str(parsed.get("title", "")).strip()
        content_lower = content.lower()
        vague_title = re.fullmatch(r"(det|that|dette|den|it)(?:\s+.*)?", title.lower() or "") is not None
        reminder_followup = any(re.search(rf"\b{re.escape(phrase)}\b", content_lower) for phrase in ["minn meg", "påminn meg", "remind me"])

        if not (vague_title and reminder_followup):
            return parsed

        topic = self._infer_recent_reminder_topic(
            channel_id=channel_id,
            user_id=user_id,
        )
        if topic:
            parsed = dict(parsed)
            parsed["title"] = topic[0].upper() + topic[1:]
            parsed["type"] = "task"
        return parsed

    def _infer_recent_reminder_topic(
        self,
        *,
        channel_id: Optional[int],
        user_id: Optional[int],
    ) -> Optional[str]:
        conversation = getattr(self.monitor, "conversation", None)
        threads = getattr(conversation, "threads", None)
        if not threads or channel_id is None or user_id is None:
            return None

        recent_messages = list(threads.get(channel_id, [])[-6:])

        recent_messages.sort(key=lambda msg: msg.get("timestamp"), reverse=True)
        for msg in recent_messages:
            if not msg.get("is_bot") or msg.get("user_id") != user_id:
                continue
            topic = self._extract_reminder_offer_topic(str(msg.get("content", "")))
            if topic:
                return topic
        return None

    def _extract_reminder_offer_topic(self, text: str) -> Optional[str]:
        patterns = [
            r"påminnelse\s+om\s+å\s+([^?!.:\n]+)",
            r"minne\s+deg\s+på\s+å\s+([^?!.:\n]+)",
            r"reminder\s+to\s+([^?!.:\n]+)",
            r"remind\s+you\s+to\s+([^?!.:\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            topic = re.sub(r"\s+", " ", match.group(1)).strip(" -–—,")
            topic = re.sub(r"\s+(eller|or)\s+.*$", "", topic, flags=re.IGNORECASE).strip(" -–—,")
            if len(topic) >= 2:
                return topic
        return None

    def _is_status_command(self, content_lower: str) -> bool:
        return content_lower == "status" or has_any_keyword(content_lower, STATUS_KEYWORDS)

    def _is_profile_command(
        self,
        content_lower: str,
        raw_content: str | None = None,
    ) -> bool:
        if self._is_status_command(content_lower):
            return False
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
            rf"{_POLITE_COMMAND_PREFIX}(?:endre|rediger|edit)\s+"
            r"(?:poll|avstemning)(?:\s+(?:\d+|siste|last))?\s+"
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
        number_match = re.search(r'(?:poll|avstemning)\s+(\d+)', content_lower)
        if number_match:
            result["target"] = int(number_match.group(1))
            return result
        # If message contains poll keywords but no scoped number, don't fall back
        # to arbitrary numbers (prevents "slett poll etter 15 minutter" → target=15)
        if has_any_keyword(content_lower, ("poll", "avstemning")):
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
