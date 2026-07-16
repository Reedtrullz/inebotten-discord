"""Pure bounded parser for Discord profile status and activity commands."""

from __future__ import annotations

import re
from typing import Literal

from core.intent_payloads import ProfilePayload


_BOT_INVOCATION = re.compile(r"^\s*@inebotten\b\s*[,;:]?\s*", re.I)
_POLITE_PREFIX = re.compile(
    r"^(?:(?:kan|kunne|vil|can|could|would|will)\s+(?:du|you)|"
    r"vennligst|please)\s+",
    re.I,
)
_PROFILE_PATTERNS: tuple[
    tuple[re.Pattern[str], Literal["status", "playing", "watching"]], ...
] = (
    (
        re.compile(
            r"^status\s+(online|offline|idle|dnd|invisible)\s*[.!?]?$",
            re.I,
        ),
        "status",
    ),
    (re.compile(r"^(?:spiller|playing)\s+(.+?)\s*[.!]?$", re.I), "playing"),
    (
        re.compile(r"^(?:ser\s+på|watching)\s+(.+?)\s*[.!]?$", re.I),
        "watching",
    ),
    (
        re.compile(
            r"^(?:sett|sette|set)\s+(?:(?:min|my)\s+)?status(?:en)?"
            r"(?:\s+(?:til|to))?\s+"
            r"(online|offline|idle|dnd|invisible)\s*[.!?]?$",
            re.I,
        ),
        "status",
    ),
    (
        re.compile(
            r"^(?:sett|sette|set)\s+(?:aktivitet(?:en)?|activity)\s+"
            r"(?:til|to)\s+(?:å\s+)?(?:spille|spiller|playing)\s+"
            r"(.+?)\s*[.!?]?$",
            re.I,
        ),
        "playing",
    ),
    (
        re.compile(
            r"^(?:sett|sette|set)\s+(?:aktivitet(?:en)?|activity)\s+"
            r"(?:til|to)\s+(?:å\s+)?(?:se\s+på|ser\s+på|watching)\s+"
            r"(.+?)\s*[.!?]?$",
            re.I,
        ),
        "watching",
    ),
)


def parse_profile_command(message_content: str) -> ProfilePayload | None:
    """Return one canonical profile mutation for an exact command frame."""

    if not isinstance(message_content, str):
        return None
    cleaned = _BOT_INVOCATION.sub("", message_content, count=1).strip()
    cleaned = _POLITE_PREFIX.sub("", cleaned, count=1).strip()
    for pattern, action in _PROFILE_PATTERNS:
        match = pattern.fullmatch(cleaned)
        if match is None:
            continue
        value = match.group(1).strip()
        if not value or len(value) > 100:
            return None
        if action == "status":
            value = value.casefold()
        return {"action": action, "value": value}
    return None


__all__ = ["ProfilePayload", "parse_profile_command"]
