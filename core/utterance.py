from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_QUOTED = re.compile(
    r'"([^"\n]*)"|“([^”\n]*)”|‘([^’\n]*)’|'
    r'«([^»\n]*)»|(?<!\w)\'([^\'\n]+)\'(?!\w)'
)
_MULTILINE_BLOCKQUOTE = re.compile(
    r"(?m)^ {0,3}>>>(?!>)[^\n]*(?:\n|$)"
)
_BLOCKQUOTE = re.compile(r"(?m)^ {0,3}>[^\n]*(?:\n|$)")
_MENTION = re.compile(r"<@!?\d+>")
_FENCE_OPEN = re.compile(
    r"(?m)^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})[^\n]*$"
)
_TOKEN = re.compile(
    r"\d{1,2}(?::\d{2})|\d{1,2}(?:[./]\d{1,2})(?:[./]\d{2,4})?"
    r"|[^\W\d_]+(?:['’][^\W\d_]+)?|\d+",
    re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class NormalizedUtterance:
    raw: str
    text: str
    folded: str
    control_text: str
    quoted_segments: tuple[str, ...]
    tokens: tuple[str, ...]


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _mask_span(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if not chars[index].isspace():
            chars[index] = " "


def _fenced_spans(value: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while opener := _FENCE_OPEN.search(value, cursor):
        marker = opener.group("marker")
        close = re.compile(
            rf"(?m)^ {{0,3}}{re.escape(marker[0])}"
            rf"{{{len(marker)},}}[ \t]*(?:\n|$)"
        ).search(value, opener.end())
        end = close.end() if close is not None else len(value)
        spans.append((opener.start(), end))
        cursor = end
        if close is None:
            break
    return tuple(spans)


def _overlaps(
    spans: tuple[tuple[int, int], ...],
    start: int,
    end: int,
) -> bool:
    return any(
        start < span_end and end > span_start
        for span_start, span_end in spans
    )


def _inline_code_spans(
    value: str,
    fenced: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(value):
        if value[index] != "`" or _overlaps(fenced, index, index + 1):
            index += 1
            continue
        end_run = index
        while end_run < len(value) and value[end_run] == "`":
            end_run += 1
        marker = value[index:end_run]
        close = value.find(marker, end_run)
        while close >= 0 and _overlaps(fenced, close, close + len(marker)):
            close = value.find(marker, close + len(marker))
        if close < 0:
            newline = value.find("\n", end_run)
            end = len(value) if newline < 0 else newline
            spans.append((index, end))
            index = end
            continue
        spans.append((index, close + len(marker)))
        index = close + len(marker)
    return tuple(spans)


def normalize_utterance(raw: str) -> NormalizedUtterance:
    if not isinstance(raw, str):
        raise TypeError("utterance must be str")
    normalized = unicodedata.normalize("NFKC", raw)
    text = _collapse(normalized)
    folded = text.casefold()
    control_chars = list(normalized)
    fenced = _fenced_spans(normalized)
    inline = _inline_code_spans(normalized, fenced)
    inert_code = fenced + inline
    for start, end in inert_code:
        _mask_span(control_chars, start, end)
    quoted: list[str] = []
    multiline_match = next(
        (
            match
            for match in _MULTILINE_BLOCKQUOTE.finditer(normalized)
            if not _overlaps(
                inert_code,
                match.start(),
                match.end(),
            )
        ),
        None,
    )
    multiline_blockquotes = (
        ((multiline_match.start(), len(normalized)),)
        if multiline_match is not None
        else ()
    )
    line_blockquotes = tuple(
        (match.start(), match.end())
        for match in _BLOCKQUOTE.finditer(normalized)
        if not _overlaps(
            inert_code + multiline_blockquotes,
            match.start(),
            match.end(),
        )
    )
    blockquotes = tuple(sorted(multiline_blockquotes + line_blockquotes))
    for start, end in blockquotes:
        quoted.append(_collapse(normalized[start:end].lstrip(" >")))
        _mask_span(control_chars, start, end)
    for match in _QUOTED.finditer(normalized):
        if _overlaps(inert_code + blockquotes, match.start(), match.end()):
            continue
        body = next(group for group in match.groups() if group is not None)
        quoted.append(_collapse(body))
        _mask_span(control_chars, match.start(), match.end())
    for match in _MENTION.finditer(normalized):
        _mask_span(control_chars, match.start(), match.end())
    control_text = _collapse("".join(control_chars)).casefold()
    return NormalizedUtterance(
        raw=raw,
        text=text,
        folded=folded,
        control_text=control_text,
        tokens=tuple(
            match.group(0) for match in _TOKEN.finditer(control_text)
        ),
        quoted_segments=tuple(quoted),
    )
