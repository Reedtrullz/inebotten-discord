"""Lossless response cleaning for explicit model reasoning regions."""

from __future__ import annotations

import re


MAX_CLEANER_INPUT_BYTES = 65_536
_REASON_TAG = re.compile(
    r"<(?P<close>/)?(?P<name>think|thinking)\b[^>]*>",
    re.IGNORECASE,
)


class ResponseCleaningError(ValueError):
    """Bounded failure raised before strict action parsing."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def clean_thinking_response(text: str) -> str:
    """Remove only proven ``think``/``thinking`` regions, preserving order."""

    if not isinstance(text, str):
        raise ResponseCleaningError("invalid_response_type")
    try:
        input_size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise ResponseCleaningError("invalid_response_encoding") from None
    if input_size > MAX_CLEANER_INPUT_BYTES:
        raise ResponseCleaningError("response_too_large")
    if not text:
        return ""

    output: list[str] = []
    stack: list[str] = []
    cursor = 0
    for match in _REASON_TAG.finditer(text):
        name = match.group("name").casefold()
        closing = bool(match.group("close"))
        if not stack:
            if closing:
                continue
            output.append(text[cursor : match.start()])
            stack.append(name)
            cursor = match.end()
            continue
        if closing and stack[-1] == name:
            stack.pop()
            if not stack:
                cursor = match.end()
        elif not closing:
            stack.append(name)
    if not stack:
        output.append(text[cursor:])
    return "".join(output)


__all__ = [
    "MAX_CLEANER_INPUT_BYTES",
    "ResponseCleaningError",
    "clean_thinking_response",
]
