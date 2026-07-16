"""Bounded recognition for read-only calendar schedule concerns."""

from __future__ import annotations

import re

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
