"""Typed public contracts shared by intent-routing components."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BotIntent(Enum):
    HELP = "help"
    STATUS = "status"
    PROFILE = "profile"
    CALENDAR_HELP = "calendar_help"
    CALENDAR_LIST = "calendar_list"
    CALENDAR_SYNC = "calendar_sync"
    CALENDAR_DELETE = "calendar_delete"
    CALENDAR_COMPLETE = "calendar_complete"
    CALENDAR_EDIT = "calendar_edit"
    CALENDAR_FACT_CHECK = "calendar_fact_check"
    CALENDAR_SEARCH = "calendar_search"
    CALENDAR_CLEAR = "calendar_clear"
    CALENDAR_ITEM = "calendar_item"
    POLL_CREATE = "poll_create"
    POLL_VOTE = "poll_vote"
    POLL_EDIT = "poll_edit"
    POLL_DELETE = "poll_delete"
    POLL_CLOSE = "poll_close"
    POLL_LIST = "poll_list"
    COUNTDOWN = "countdown"
    WATCHLIST = "watchlist"
    WORD_OF_DAY = "word_of_day"
    QUOTE = "quote"
    QUOTE_LIST = "quote_list"
    QUOTE_EDIT = "quote_edit"
    QUOTE_DELETE = "quote_delete"
    AURORA = "aurora"
    SCHOOL_HOLIDAYS = "school_holidays"
    PRICE = "price"
    HOROSCOPE = "horoscope"
    COMPLIMENT = "compliment"
    CALCULATOR = "calculator"
    SHORTEN_URL = "shorten_url"
    DAILY_DIGEST = "daily_digest"
    SEARCH = "search"
    DASHBOARD = "dashboard"
    SET_LOCATION = "set_location"
    MEMORY_VIEW = "memory_view"
    MEMORY_EXPORT = "memory_export"
    MEMORY_DELETE = "memory_delete"
    BIRTHDAY_EDIT = "birthday_edit"
    REMINDER_EDIT = "reminder_edit"
    REMINDER_DELETE = "reminder_delete"
    REMINDER_SEARCH = "reminder_search"
    REMINDER_CREATE = "reminder_create"
    REMINDER_LIST = "reminder_list"
    REMINDER_COMPLETE = "reminder_complete"
    CALENDAR_AUTH = "calendar_auth"
    AI_CHAT = "ai_chat"
    CLARIFY = "clarify"
    BIRTHDAY_CREATE = "birthday_create"
    BIRTHDAY_LIST = "birthday_list"
    ACTION_CONFIRM = "action_confirm"
    ACTION_CANCEL = "action_cancel"
    ACTION_SELECT = "action_select"
    ACTION_CORRECT = "action_correct"


class IntentSource(str, Enum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"


class IntentRisk(str, Enum):
    READ_ONLY = "read_only"
    ADDITIVE = "additive"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class RejectionCode(str, Enum):
    NEGATED_ACTION = "negated_action"
    QUOTED_ONLY = "quoted_only"
    META = "meta"
    HYPOTHETICAL = "hypothetical"
    INFORMATION_QUESTION_MUTATION = "information_question_mutation"
    MISSING_ACTION_EVIDENCE = "missing_action_evidence"
    MISSING_DOMAIN_EVIDENCE = "missing_domain_evidence"
    MISSING_LIVE_EVIDENCE = "missing_live_evidence"
    INVALID_TEMPORAL = "invalid_temporal"
    PARSER_ERROR = "parser_error"
    UNSAFE_SEMANTIC = "unsafe_semantic"
    INVALID_CONTEXT = "invalid_context"
    CONFLICT = "conflict"
    OTHER = "other"


@dataclass(frozen=True)
class IntentResult:
    intent: BotIntent
    confidence: float
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: IntentSource = IntentSource.DETERMINISTIC
    risk: IntentRisk = IntentRisk.READ_ONLY
    requires_confirmation: bool = False


@dataclass(frozen=True)
class IntentCandidate:
    intent: BotIntent
    confidence: float
    priority: int
    order: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: IntentSource = IntentSource.DETERMINISTIC
    risk: IntentRisk = IntentRisk.READ_ONLY
    action_terms: tuple[str, ...] = ()
    domain_terms: tuple[str, ...] = ()
    specificity: int = 0
    requires_confirmation: bool = False

    def to_result(self) -> IntentResult:
        return IntentResult(
            self.intent,
            self.confidence,
            dict(self.payload),
            self.reason,
            self.source,
            self.risk,
            self.requires_confirmation,
        )


@dataclass(frozen=True)
class CandidateRejection:
    candidate: IntentCandidate
    code: RejectionCode


@dataclass(frozen=True)
class ArbitrationDecision:
    selected: IntentCandidate | None
    alternatives: tuple[IntentCandidate, ...] = ()
    rejected: tuple[CandidateRejection, ...] = ()
    blocked: bool = False
    reason: str = ""


@dataclass(frozen=True)
class RouteDiagnostics:
    parser_errors: tuple[str, ...] = ()
    rejection_counts: Mapping[RejectionCode, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutedIntent:
    result: IntentResult
    diagnostics: RouteDiagnostics = field(default_factory=RouteDiagnostics)
