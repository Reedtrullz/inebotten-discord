from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from collections.abc import Iterable

from core.utterance import NormalizedUtterance


class SpeechAct(str, Enum):
    DIRECTIVE = "directive"
    INFORMATION_REQUEST = "information_request"
    STATEMENT = "statement"
    HYPOTHETICAL = "hypothetical"
    META = "meta"
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"


@dataclass(frozen=True, slots=True)
class UtteranceSemantics:
    speech_act: SpeechAct
    reasons: tuple[str, ...]
    allows_mutation: bool


CONFIRMATIONS = frozenset({
    "ja", "yes", "jepp", "bekreft", "confirm", "ok", "okay",
})
REJECTIONS = frozenset({
    "nei", "no", "avbryt", "cancel", "stopp", "dropp det",
    "ikke gjør det", "ikkje gjer det",
})
HYPOTHETICAL_FRAMES = (
    "hva skjer hvis", "kva skjer om", "ka skjer hvis", "what happens if",
    "hvis jeg", "om jeg", "if i ", "hvis du", "om du", "if you ",
)
HYPOTHETICAL_PATTERNS = (
    re.compile(r"\b(?:jeg|eg)\s+vurderer\s+(?:kanskje\s+)?å\b"),
    re.compile(r"\b(?:jeg|eg)\s+tenker\s+på\s+å\b"),
    re.compile(r"\bi\s+am\s+considering\b"),
    re.compile(r"\bmaybe\s+i\s+should\b"),
)
META_FRAMES = (
    "jeg skrev", "eg skreiv", "i wrote", "eksempel", "example",
    "hva betyr", "kva tyder", "what does", "hvordan skriver",
)
POLITE_DIRECTIVES = (
    "kan du", "kunne du", "vil du", "vennligst", "vær så snill",
    "could you", "would you", "please",
)
QUESTION_STARTS = (
    "hva ", "kva ", "ka ", "hvordan ", "korleis ", "når ", "where ",
    "when ", "what ", "how ", "why ", "hvor ", "kor ",
)
INFORMATION_MUTATION_PATTERNS = (
    re.compile(r"^(?:hvorfor|kvifor|why)\b"),
    re.compile(
        r"^(?:kan\s+man|er\s+det\s+mulig\s+å|can\s+one|"
        r"is\s+it\s+possible\s+to)\b"
    ),
    re.compile(
        r"^(?:kan\s+du|kunne\s+du|could\s+you|would\s+you)\s+"
        r"(?:forklare|vise|fortelle|explain|show|tell)\b.*"
        r"\b(?:hvordan|korleis|how)\b"
    ),
)
PERMISSION_QUESTION_PATTERN = re.compile(
    r"^(?:kan\s+(?:jeg|eg|æ)|can\s+i|may\s+i|could\s+i)\b"
)
ACTION_TERMS = frozenset({
    "slett", "slette", "sletter", "slettar", "delete", "deleting",
    "fjern", "fjerne", "remove", "tøm", "tømme", "clear", "endre", "edit",
    "rediger", "flytt", "move", "opprett", "opprette", "create",
    "lag", "lage", "add", "legg",
    "husk", "glem", "gløym", "forget", "påminn", "minn", "stem", "vote",
    "lukk", "close", "fullfør", "complete", "synk", "sync", "forkort",
})
NEGATIONS = frozenset({
    "ikke", "ikkje", "aldri", "not", "never", "don't", "don’t",
    "can't", "can’t", "cannot", "won't", "won’t",
    "shouldn't", "shouldn’t",
})
POSITIVE_FORGET = ("ikke glem", "ikkje gløym", "don't forget", "don’t forget")


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    tokens = tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text.casefold()))
    return any(
        needle and any(True for _ in _token_starts(tokens, needle))
        for needle in (_term_tokens(phrase) for phrase in phrases)
    )


def _term_tokens(term: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", term.casefold()))


def _token_starts(tokens: tuple[str, ...], needle: tuple[str, ...]):
    width = len(needle)
    for index in range(0, len(tokens) - width + 1):
        if tokens[index:index + width] == needle:
            yield index


def is_negated_action(
    utterance: NormalizedUtterance,
    action_terms: Iterable[str],
    *,
    allow_positive_forget: bool = False,
) -> bool:
    tokens = utterance.tokens
    ignored_negations: set[int] = set()
    if allow_positive_forget:
        for phrase in POSITIVE_FORGET:
            needle = _term_tokens(phrase)
            for start in _token_starts(tokens, needle):
                ignored_negations.add(start)
    for term in action_terms:
        needle = _term_tokens(term)
        if not needle:
            continue
        for index in _token_starts(tokens, needle):
            left = max(0, index - 8)
            right = min(len(tokens), index + len(needle) + 4)
            negated_indices = {
                offset
                for offset in range(left, right)
                if tokens[offset] in NEGATIONS
            }
            if negated_indices - ignored_negations:
                return True
    return False


def evidence_is_quoted_only(
    utterance: NormalizedUtterance, terms: Iterable[str]
) -> bool:
    normalized = tuple(
        term.casefold().strip() for term in terms if term.strip()
    )
    present = tuple(
        term for term in normalized
        if _contains_phrase(utterance.folded, (term,))
    )
    if not present:
        return False
    return not _contains_phrase(utterance.control_text, present)


def analyze_utterance(utterance: NormalizedUtterance) -> UtteranceSemantics:
    text = utterance.control_text.strip()
    if text in CONFIRMATIONS:
        return UtteranceSemantics(
            SpeechAct.CONFIRMATION,
            ("exact_confirmation",),
            False,
        )
    if text in REJECTIONS:
        return UtteranceSemantics(
            SpeechAct.REJECTION,
            ("exact_rejection",),
            False,
        )
    if _contains_phrase(text, HYPOTHETICAL_FRAMES) or any(
        pattern.search(text) for pattern in HYPOTHETICAL_PATTERNS
    ):
        return UtteranceSemantics(
            SpeechAct.HYPOTHETICAL,
            ("hypothetical_frame",),
            False,
        )
    if _contains_phrase(text, META_FRAMES):
        return UtteranceSemantics(SpeechAct.META, ("meta_frame",), False)
    if any(
        pattern.search(text)
        for pattern in INFORMATION_MUTATION_PATTERNS
    ):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("information_question",),
            False,
        )
    if (
        PERMISSION_QUESTION_PATTERN.search(text)
        and _contains_phrase(text, ACTION_TERMS)
    ):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("permission_question",),
            False,
        )
    if _contains_phrase(text, POLITE_DIRECTIVES):
        negated = is_negated_action(utterance, ACTION_TERMS)
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("polite_directive",) + (("negated_action",) if negated else ()),
            not negated,
        )
    if text.startswith(QUESTION_STARTS) or (
        text.endswith("?") and not _contains_phrase(text, ACTION_TERMS)
    ):
        return UtteranceSemantics(
            SpeechAct.INFORMATION_REQUEST,
            ("information_question",),
            False,
        )
    if _contains_phrase(text, ACTION_TERMS):
        negated = is_negated_action(
            utterance,
            ACTION_TERMS,
            allow_positive_forget=True,
        )
        return UtteranceSemantics(
            SpeechAct.DIRECTIVE,
            ("imperative_action",) + (("negated_action",) if negated else ()),
            not negated,
        )
    return UtteranceSemantics(
        SpeechAct.STATEMENT,
        ("statement_fallback",),
        True,
    )
