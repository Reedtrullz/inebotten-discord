"""Pure risk-aware arbitration for deterministic and semantic candidates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
import re

from core.intent_models import (
    ArbitrationDecision,
    BotIntent,
    CandidateRejection,
    IntentCandidate,
    IntentRisk,
    IntentSource,
    RejectionCode,
)
from core.utterance import NormalizedUtterance
from core.utterance_semantics import (
    SpeechAct,
    UtteranceSemantics,
    evidence_is_quoted_only,
    is_negated_action,
)

_WRITE_RISKS = {
    IntentRisk.ADDITIVE,
    IntentRisk.MUTATING,
    IntentRisk.DESTRUCTIVE,
}
_HARD_BLOCK_CODES = {
    RejectionCode.NEGATED_ACTION,
    RejectionCode.QUOTED_ONLY,
    RejectionCode.META,
    RejectionCode.HYPOTHETICAL,
    RejectionCode.UNSAFE_SEMANTIC,
}
_WORD = re.compile(
    r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+", re.UNICODE
)


def _term_tokens(value: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(value.casefold()))


def _present(control_text: str, terms: tuple[str, ...]) -> bool:
    tokens = _term_tokens(control_text)

    def matches(window: tuple[str, ...], needle: tuple[str, ...]) -> bool:
        if window == needle:
            return True
        if len(window) != len(needle) or window[:-1] != needle[:-1]:
            return False
        final = window[-1]
        stem = needle[-1]
        return final.startswith(stem) and final[len(stem) :] in {
            "a",
            "en",
            "ene",
            "er",
            "et",
            "s",
        }

    for term in terms:
        needle = _term_tokens(term)
        if not needle:
            continue
        width = len(needle)
        if any(
            matches(tokens[index : index + width], needle)
            for index in range(0, len(tokens) - width + 1)
        ):
            return True
    return False


def _rejection(
    candidate: IntentCandidate, code: RejectionCode
) -> CandidateRejection:
    return CandidateRejection(candidate, code)


def _unsafe_code(
    utterance: NormalizedUtterance,
    semantics: UtteranceSemantics,
    candidate: IntentCandidate,
) -> RejectionCode | None:
    evidence = candidate.action_terms + candidate.domain_terms
    if evidence_is_quoted_only(utterance, evidence):
        return RejectionCode.QUOTED_ONLY
    live_evidence = tuple(
        term
        for term in evidence
        if _present(utterance.control_text, (term,))
    )
    if not live_evidence:
        if candidate.risk in _WRITE_RISKS:
            return RejectionCode.MISSING_LIVE_EVIDENCE
        return None
    if semantics.speech_act is SpeechAct.META:
        return RejectionCode.META
    if semantics.speech_act is SpeechAct.HYPOTHETICAL:
        return RejectionCode.HYPOTHETICAL

    allow_positive_forget = (
        candidate.risk is IntentRisk.ADDITIVE
        and candidate.intent
        in {BotIntent.CALENDAR_ITEM, BotIntent.REMINDER_CREATE}
    )
    if is_negated_action(
        utterance,
        live_evidence,
        allow_positive_forget=allow_positive_forget,
    ):
        return RejectionCode.NEGATED_ACTION
    if candidate.risk not in _WRITE_RISKS:
        return None
    if semantics.speech_act is SpeechAct.INFORMATION_REQUEST:
        return RejectionCode.INFORMATION_QUESTION_MUTATION
    if (
        not semantics.allows_mutation
        and (
            candidate.source is IntentSource.DETERMINISTIC
            or bool(candidate.action_terms)
        )
        and "negated_action" not in semantics.reasons
    ):
        return RejectionCode.UNSAFE_SEMANTIC
    if candidate.risk is IntentRisk.DESTRUCTIVE:
        if not candidate.action_terms or not _present(
            utterance.control_text, candidate.action_terms
        ):
            return RejectionCode.MISSING_ACTION_EVIDENCE
        if not candidate.domain_terms or not _present(
            utterance.control_text, candidate.domain_terms
        ):
            return RejectionCode.MISSING_DOMAIN_EVIDENCE
    return None


def _sort_key(candidate: IntentCandidate) -> tuple[int, int, int, float, str]:
    return (
        -candidate.specificity,
        candidate.priority,
        candidate.order,
        -candidate.confidence,
        candidate.intent.value,
    )


def _is_conflict(first: IntentCandidate, second: IntentCandidate) -> bool:
    return (
        first.intent is not second.intent
        and first.specificity == second.specificity
        and first.priority == second.priority == 35
        and abs(first.confidence - second.confidence) <= 0.05
        and frozenset(first.domain_terms) != frozenset(second.domain_terms)
    )


def arbitrate_candidates(
    utterance: NormalizedUtterance,
    semantics: UtteranceSemantics,
    candidates: Iterable[IntentCandidate],
) -> ArbitrationDecision:
    """Filter unsafe writes, deterministically rank, and select one candidate."""

    accepted: list[IntentCandidate] = []
    rejected: list[CandidateRejection] = []
    hard_blocked = False
    for candidate in candidates:
        code = _unsafe_code(utterance, semantics, candidate)
        if code is None:
            accepted.append(candidate)
            continue
        rejected.append(_rejection(candidate, code))
        hard_blocked = hard_blocked or code in _HARD_BLOCK_CODES

    if hard_blocked:
        return ArbitrationDecision(
            None,
            rejected=tuple(rejected),
            blocked=True,
            reason="unsafe_write",
        )

    ordered = sorted(accepted, key=_sort_key)
    if not ordered:
        return ArbitrationDecision(
            None, rejected=tuple(rejected), reason="no_candidate"
        )
    if len(ordered) > 1 and _is_conflict(ordered[0], ordered[1]):
        choices = [ordered[0].intent.value, ordered[1].intent.value]
        clarification = IntentCandidate(
            BotIntent.CLARIFY,
            min(ordered[0].confidence, ordered[1].confidence),
            ordered[0].priority,
            order=min(ordered[0].order, ordered[1].order),
            payload={"choices": choices},
            reason="candidate_conflict",
            source=IntentSource.DETERMINISTIC,
            risk=IntentRisk.READ_ONLY,
            specificity=ordered[0].specificity,
        )
        rejected.extend(
            _rejection(candidate, RejectionCode.CONFLICT)
            for candidate in ordered[:2]
        )
        return ArbitrationDecision(
            clarification,
            alternatives=tuple(ordered[:2]),
            rejected=tuple(rejected),
            reason="candidate_conflict",
        )

    selected = ordered[0]
    confirmation = (
        selected.intent is BotIntent.CALENDAR_AUTH
        or selected.risk is IntentRisk.DESTRUCTIVE
        or (
            selected.source is IntentSource.SEMANTIC
            and selected.risk in _WRITE_RISKS
        )
    )
    return ArbitrationDecision(
        replace(selected, requires_confirmation=confirmation),
        rejected=tuple(rejected),
        reason="selected",
    )


__all__ = ["arbitrate_candidates"]
