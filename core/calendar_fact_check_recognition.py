"""Bounded recognition for read-only calendar schedule concerns."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from cal_system.temporal_resolver import TemporalResolver
from core.calendar_fact_check_store import CalendarFactCheckInquiry, CalendarFactCheckPhase
from core.utterance import NormalizedUtterance
from core.utterance_semantics import SpeechAct, UtteranceSemantics


_UNCERTAINTY_PREFIX = (
    r"(?:jeg\s+er\s+ganske\s+sikker\s+på\s+at|"
    r"jeg\s+tror|eg\s+trur|i\s+think)"
)
_SCHEDULE_FIELD = (
    r"(?:(?:the\s+)?(?:time|date)|tidspunktet|tidspunkt|tiden|datoen|dato)"
)
_TARGET_CONNECTOR = r"(?:for|til|on)"
_CONCERN_SUFFIX = (
    r"(?:er\s+feil|er\s+galt|stemmer\s+ikke|ikke\s+stemmer|"
    r"kan\s+være\s+feil|is\s+wrong|does(?:n't|\s+not)\s+look\s+right|"
    r"might\s+be\s+wrong)"
)
_SCHEDULE_CONCERN = re.compile(
    rf"^(?:{_UNCERTAINTY_PREFIX}\s+)?{_SCHEDULE_FIELD}\s+"
    rf"{_TARGET_CONNECTOR}\s+(?P<target>.{{1,200}}?)\s+{_CONCERN_SUFFIX}$",
    re.IGNORECASE,
)
_SEARCH_CONTINUATION = re.compile(
    r"(?:sjekk|undersøk|undersøk det|kan du undersøke\??|"
    r"ja,? finn ut av det|look it up|check|search)", re.IGNORECASE
)
_CANCEL_CONTINUATION = re.compile(
    r"(?:avbryt|stopp|dropp det|cancel|never mind)", re.IGNORECASE
)
_ORDINALS = {
    "første": 1, "fyrste": 1, "first": 1,
    "andre": 2, "second": 2,
    "tredje": 3, "third": 3,
    "fjerde": 4, "fourth": 4,
    "femte": 5, "fifth": 5,
}
_DIRECT_TEMPORAL = re.compile(
    r"(?:(?:riktig(?:e)?\s+)?(?:dato|tidspunkt|tid)(?:en|et)?\s+er\s+|"
    r"sett\s+den\s+til\s+|change\s+it\s+to\s+)?"
    r"(?:"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?"
    r"(?:\s+(?:kl(?:okka|okken)?\.?|at)\s+[^\s]+(?:\s*(?:am|pm))?)?|"
    r"(?:kl(?:okka|okken)?\.?|at)\s+[^\s]+(?:\s*(?:am|pm))?|"
    r"\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)"
    r")",
    re.IGNORECASE,
)
_DATE_CUE = re.compile(r"\d{1,2}[./]\d{1,2}|\b(?:today|tomorrow|i dag|i morgen)\b", re.I)
_TIME_CUE = re.compile(r"\b(?:kl(?:okka|okken)?\.?|at)\b|\d{1,2}:\d{2}|\b\d{1,2}\s*(?:am|pm)\b", re.I)
_AMBIGUOUS_CUED_HOUR = re.compile(
    r"(?:kl(?:okka|okken)?\.?|at)\s+(?:[1-9]|1[0-2])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FactCheckContinuation:
    kind: Literal["select", "search", "cancel", "direct", "expired"]
    number: int | None = None
    changes: Mapping[str, str] | None = None
    clarification: str | None = None


def parse_fact_check_continuation(
    text: str,
    inquiry: CalendarFactCheckInquiry | None,
    *,
    expired: bool,
    temporal_resolver: TemporalResolver,
    reference_time: datetime,
) -> FactCheckContinuation | None:
    normalized = " ".join(text.strip().split())
    folded = normalized.casefold().strip(" .!?")
    recognized = bool(
        _SEARCH_CONTINUATION.fullmatch(folded)
        or _CANCEL_CONTINUATION.fullmatch(folded)
        or folded.isdecimal()
        or folded in _ORDINALS
        or _DIRECT_TEMPORAL.fullmatch(normalized)
    )
    if expired and recognized:
        return FactCheckContinuation("expired")
    if inquiry is None:
        return None
    if _CANCEL_CONTINUATION.fullmatch(folded):
        return FactCheckContinuation("cancel")
    if inquiry.phase is CalendarFactCheckPhase.CHOOSING_TARGET:
        number = int(folded) if folded.isdecimal() else _ORDINALS.get(folded)
        if number is not None:
            if 1 <= number <= len(inquiry.targets):
                return FactCheckContinuation("select", number=number)
            return FactCheckContinuation(
                "select",
                clarification="Det nummeret finnes ikke i valgene.",
            )
        return None
    if _SEARCH_CONTINUATION.fullmatch(folded):
        return FactCheckContinuation("search")
    if folded.isdecimal():
        return FactCheckContinuation(
            "direct",
            clarification="Oppgi et entydig klokkeslett, for eksempel `klokka 18`.",
        )
    if _DIRECT_TEMPORAL.fullmatch(normalized) is None:
        return None
    if _AMBIGUOUS_CUED_HOUR.fullmatch(normalized):
        return FactCheckContinuation(
            "direct",
            clarification="Oppgi om du mener morgen eller ettermiddag, eller bruk 24-timersformat.",
        )
    resolution = temporal_resolver.resolve(normalized, reference=reference_time)
    if resolution.errors:
        return FactCheckContinuation(
            "direct",
            clarification="Jeg kunne ikke tolke datoen eller klokkeslettet entydig.",
        )
    has_date = _DATE_CUE.search(normalized) is not None
    has_time = _TIME_CUE.search(normalized) is not None
    changes: dict[str, str] = {}
    if has_date and resolution.date is not None:
        changes["date"] = resolution.date
    if has_time and resolution.time is not None:
        changes["time"] = resolution.time
    if not changes:
        return None
    target = inquiry.targets[0]
    merged = temporal_resolver.validate_fields(
        changes.get("date", target.date),
        changes.get("time", target.time),
        reference=reference_time,
    )
    if merged.errors:
        return FactCheckContinuation(
            "direct",
            clarification="Datoen og klokkeslettet er ikke gyldige sammen.",
        )
    return FactCheckContinuation("direct", changes=changes)


def parse_schedule_concern(
    utterance: NormalizedUtterance,
    semantics: UtteranceSemantics,
) -> str | None:
    """Return one inert target for a complete supported concern statement."""

    if utterance.quoted_segments:
        return None
    match = _SCHEDULE_CONCERN.fullmatch(utterance.text)
    if match is None:
        return None
    semantic_statement = semantics.speech_act is SpeechAct.STATEMENT
    # ``stemmer`` is also a Norwegian vote verb in the shared action-term
    # table, so ``... ikke stemmer`` is conservatively labelled as a negated
    # directive. Accept only that exact fail-closed semantic shape after the
    # complete read-only concern grammar has matched.
    negated_vote_collision = semantics.reasons == (
        "imperative_action",
        "negated_action",
    )
    if not semantic_statement and not negated_vote_collision:
        return None
    target = match.group("target").strip()
    return target or None
