"""Token-aware keyword matching utilities for intent routing.

These helpers use regex word boundaries so matching is based on whole words,
not substrings. That prevents false positives like matching ``tale`` inside
``avtale``.
"""

import re
from collections.abc import Iterable


def has_keyword(content: str, keyword: str) -> bool:
    """Check whether ``content`` contains ``keyword`` as a whole word.

    Uses regex word boundaries to avoid substring matches.

    Examples:
        >>> has_keyword("hello world", "hello")
        True
        >>> has_keyword("helloworld", "hello")
        False
        >>> has_keyword("møte i morgen", "møte")
        True
        >>> has_keyword("avtale", "tale")
        False
    """

    return bool(re.search(rf"\b{re.escape(keyword)}\b", content, re.IGNORECASE))


def has_any_keyword(content: str, keywords: Iterable[str]) -> bool:
    """Check whether ``content`` contains any keyword as a whole word.

    Examples:
        >>> has_any_keyword("jeg har møte i morgen", ["avtale", "møte"])
        True
    """

    for keyword in keywords:
        if has_keyword(content, keyword):
            return True
    return False


def has_all_keywords(content: str, keywords: Iterable[str]) -> bool:
    """Check whether ``content`` contains all keywords as whole words.

    Examples:
        >>> has_all_keywords("møte i morgen", ["møte", "morgen"])
        True
    """

    for keyword in keywords:
        if not has_keyword(content, keyword):
            return False
    return True


def extract_keywords(content: str, keywords: Iterable[str]) -> list[str]:
    """Return the keywords found in ``content`` as whole words.

    Examples:
        >>> extract_keywords("møte i morgen", ["møte", "tale", "morgen"])
        ['møte', 'morgen']
    """

    found: list[str] = []
    for keyword in keywords:
        if has_keyword(content, keyword):
            found.append(keyword)
    return found
