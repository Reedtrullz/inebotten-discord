"""Typed, bounded contracts for untrusted conversational history."""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from itertools import islice
from typing import Literal, Protocol

from core.intent_models import BotIntent, IntentResult, IntentSource


class ChatContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str
    source_message_id: int | None = None


class HistoryPolicy(str, Enum):
    FULL = "full"
    REDACT_AUTH = "redact_auth"
    OMIT = "omit"


REDACTED_AUTH_TURN = "[sensitiv autentisering utelatt]"
_CURRENT_HISTORY_POLICY: ContextVar[HistoryPolicy] = ContextVar(
    "history_policy",
    default=HistoryPolicy.OMIT,
)
_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "auth_code",
        "oauth_code",
        "oauth_state",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "code",
        "state",
    }
)
_FAIL_CLOSED_HISTORY_REASONS = frozenset(
    {
        "credential_shaped_input_blocked",
        "pending_expired",
        "pending_stale",
    }
)
_PROVIDER_CONVERSATION_INTENTS = frozenset(
    {
        BotIntent.AI_CHAT,
        BotIntent.SEARCH,
    }
)


def _contains_sensitive_key(
    value: object,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> bool:
    if depth >= 12:
        return True
    if seen is None:
        seen = set()
    if isinstance(value, IntentResult):
        return (
            value.intent is BotIntent.CALENDAR_AUTH
            or value.reason in _FAIL_CLOSED_HISTORY_REASONS
            or _contains_sensitive_key(
                value.payload,
                depth=depth + 1,
                seen=seen,
            )
        )
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return True
        seen.add(identity)
        try:
            items = list(islice(value.items(), 51))
            if len(items) > 50:
                return True
            keys = {
                key.casefold()
                for key, _ in items
                if isinstance(key, str)
            }
            return bool(_SENSITIVE_PAYLOAD_KEYS & keys) or any(
                _contains_sensitive_key(
                    nested,
                    depth=depth + 1,
                    seen=seen,
                )
                for _, nested in items
            )
        except Exception:
            return True
        finally:
            seen.remove(identity)
    if isinstance(value, (list, tuple, set, frozenset)):
        identity = id(value)
        if identity in seen:
            return True
        seen.add(identity)
        try:
            if len(value) > 50:
                return True
            return any(
                _contains_sensitive_key(
                    item,
                    depth=depth + 1,
                    seen=seen,
                )
                for item in value
            )
        except Exception:
            return True
        finally:
            seen.remove(identity)
    return False


def history_policy_for_effective_routes(
    routes: Sequence[IntentResult] | None,
) -> HistoryPolicy:
    """Return a conservative policy for the exact effective route set."""

    if routes is None or not routes:
        return HistoryPolicy.REDACT_AUTH
    if any(not isinstance(route, IntentResult) for route in routes):
        return HistoryPolicy.REDACT_AUTH
    if any(
        route.intent is BotIntent.CALENDAR_AUTH
        or route.reason in _FAIL_CLOSED_HISTORY_REASONS
        or _contains_sensitive_key(route.payload)
        for route in routes
    ):
        return HistoryPolicy.REDACT_AUTH
    if all(
        (
            route.intent in _PROVIDER_CONVERSATION_INTENTS
            or (
                route.intent is BotIntent.CLARIFY
                and route.source is IntentSource.SEMANTIC
            )
        )
        for route in routes
    ):
        return HistoryPolicy.FULL
    return HistoryPolicy.OMIT


@contextmanager
def capture_history_policy(policy: HistoryPolicy) -> Iterator[None]:
    if not isinstance(policy, HistoryPolicy):
        raise ChatContractError("invalid_history_policy")
    token = _CURRENT_HISTORY_POLICY.set(policy)
    try:
        yield
    finally:
        _CURRENT_HISTORY_POLICY.reset(token)


def history_safe_content(content: str) -> str | None:
    if not isinstance(content, str):
        raise ChatContractError("invalid_history_content")
    policy = _CURRENT_HISTORY_POLICY.get()
    if policy is HistoryPolicy.FULL:
        return content
    if policy is HistoryPolicy.REDACT_AUTH:
        return REDACTED_AUTH_TURN
    return None


def sanitize_chat_turn_content(
    content: str,
    *,
    max_chars: int = 4_000,
) -> str:
    if not isinstance(content, str):
        raise ChatContractError("invalid_history_content")
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars < 1
    ):
        raise ChatContractError("invalid_history_limit")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(
        character
        for character in normalized
        if (
            character in {"\n", "\t"}
            or unicodedata.category(character) not in {"Cc", "Cf"}
        )
    )
    if len(cleaned) > max_chars:
        cleaned = cleaned[-max_chars:]
        newline = cleaned.find("\n")
        if newline > 0:
            cleaned = cleaned[newline + 1 :]
    return cleaned.strip()


def _validate_turn(turn: ChatTurn) -> ChatTurn:
    if not isinstance(turn.role, str) or turn.role not in {
        "user",
        "assistant",
    }:
        raise ChatContractError("invalid_history_role")
    source_id = turn.source_message_id
    if source_id is not None and (
        isinstance(source_id, bool) or not isinstance(source_id, int)
    ):
        raise ChatContractError("invalid_source_message_id")
    return ChatTurn(
        role=turn.role,
        content=sanitize_chat_turn_content(turn.content),
        source_message_id=source_id,
    )


def prepare_history(
    history: Sequence[ChatTurn],
    *,
    max_turns: int = 10,
    max_chars: int = 12_000,
) -> tuple[ChatTurn, ...]:
    if not isinstance(history, (list, tuple)):
        raise ChatContractError("invalid_history")
    for value, code in (
        (max_turns, "invalid_history_turn_limit"),
        (max_chars, "invalid_history_char_limit"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ChatContractError(code)

    selected: list[ChatTurn] = []
    remaining = max_chars
    for raw_turn in reversed(history[-max_turns:]):
        if not isinstance(raw_turn, ChatTurn):
            raise ChatContractError("invalid_history_turn")
        turn = _validate_turn(raw_turn)
        if not turn.content:
            continue
        content = turn.content
        if len(content) > remaining:
            content = sanitize_chat_turn_content(
                content,
                max_chars=remaining,
            )
        if not content:
            break
        selected.append(
            ChatTurn(turn.role, content, turn.source_message_id)
        )
        remaining -= len(content)
        if remaining <= 0:
            break
    selected.reverse()
    return tuple(selected)


def _json_safe(
    value: object,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> object:
    if seen is None:
        seen = set()
    if depth >= 6:
        return "[nested context omitted]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[non-finite number omitted]"
    if isinstance(value, str):
        return sanitize_chat_turn_content(value, max_chars=2_000)
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return "[cyclic context omitted]"
        seen.add(identity)
        result: dict[str, object] = {}
        for key, nested in islice(value.items(), 50):
            if not isinstance(key, str):
                continue
            result[key[:100]] = _json_safe(
                nested,
                depth=depth + 1,
                seen=seen,
            )
        seen.remove(identity)
        return result
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            return "[cyclic context omitted]"
        seen.add(identity)
        result = [
            _json_safe(item, depth=depth + 1, seen=seen)
            for item in islice(value, 50)
        ]
        seen.remove(identity)
        return result
    try:
        rendered = str(value)
    except Exception:
        rendered = f"[{type(value).__name__} omitted]"
    return sanitize_chat_turn_content(rendered, max_chars=500)


def _prune_json(
    value: object,
    *,
    string_limit: int,
    item_limit: int,
    depth: int = 0,
) -> object:
    if isinstance(value, str):
        return value[:string_limit]
    if isinstance(value, dict):
        if depth >= 6:
            return "[nested context omitted]"
        return {
            key: _prune_json(
                nested,
                string_limit=string_limit,
                item_limit=item_limit,
                depth=depth + 1,
            )
            for key, nested in islice(value.items(), item_limit)
        }
    if isinstance(value, list):
        if depth >= 6:
            return ["[nested context omitted]"]
        return [
            _prune_json(
                nested,
                string_limit=string_limit,
                item_limit=item_limit,
                depth=depth + 1,
            )
            for nested in value[:item_limit]
        ]
    return value


def build_context_prompt(
    data: Mapping[str, object],
    *,
    max_chars: int = 4_000,
) -> str:
    """Serialize detached untrusted context as valid, bounded JSON."""

    if not isinstance(data, Mapping):
        raise ChatContractError("invalid_context_data")
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars < 64
    ):
        raise ChatContractError("invalid_context_limit")
    safe = _json_safe(data)
    def serialize(candidate: object) -> str:
        return json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    serialized = serialize(safe)
    if len(serialized) <= max_chars:
        return serialized
    for string_limit, item_limit in (
        (1_000, 20),
        (500, 10),
        (200, 8),
        (100, 5),
        (40, 3),
        (20, 1),
    ):
        candidate = _prune_json(
            safe,
            string_limit=string_limit,
            item_limit=item_limit,
        )
        if isinstance(candidate, dict):
            candidate = {**candidate, "truncated": True}
        serialized = serialize(candidate)
        if len(serialized) <= max_chars:
            return serialized
    return serialize({"truncated": True})


def fit_context_prompt_in_wrapper(
    context_prompt: str,
    *,
    serialize_wrapper: Callable[[str], str],
    max_chars: int,
) -> str:
    """Fit context into a wrapper without corrupting nested JSON text.

    Provider metadata stores the already-serialized context document as a JSON
    string.  Cutting that string at an arbitrary character keeps the outer
    wrapper valid but can leave the nested document invalid.  Valid object
    context is therefore parsed and rebuilt through ``build_context_prompt``;
    legacy plain text retains the prior bounded-prefix behavior.
    """

    if not isinstance(context_prompt, str):
        raise ChatContractError("invalid_context_prompt")
    if not callable(serialize_wrapper):
        raise ChatContractError("invalid_context_wrapper")
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars < 64
    ):
        raise ChatContractError("invalid_context_limit")

    def fits(candidate: str) -> bool:
        rendered = serialize_wrapper(candidate)
        if not isinstance(rendered, str):
            raise ChatContractError("invalid_context_wrapper")
        return len(rendered) <= max_chars

    if fits(context_prompt):
        return context_prompt

    try:
        decoded = json.loads(context_prompt)
    except (json.JSONDecodeError, RecursionError):
        decoded = None
        was_json = False
    else:
        was_json = True

    if isinstance(decoded, Mapping):
        fallback = json.dumps(
            {"truncated": True},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if not fits(fallback):
            raise ChatContractError("context_wrapper_too_large")
        best = fallback
        low = 64
        high = min(len(context_prompt), max_chars)
        while low <= high:
            middle = (low + high) // 2
            candidate = build_context_prompt(decoded, max_chars=middle)
            if fits(candidate):
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        return best

    if was_json and isinstance(decoded, str):
        def encode_prefix(length: int) -> str:
            return json.dumps(
                decoded[:length],
                ensure_ascii=False,
                separators=(",", ":"),
            )

        best = encode_prefix(0)
        if not fits(best):
            raise ChatContractError("context_wrapper_too_large")
        low = 0
        high = len(decoded)
        while low <= high:
            middle = (low + high) // 2
            candidate = encode_prefix(middle)
            if fits(candidate):
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        return best

    if was_json:
        fallback = json.dumps(
            {"truncated": True},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if not fits(fallback):
            raise ChatContractError("context_wrapper_too_large")
        return fallback

    low = 0
    high = len(context_prompt)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(context_prompt[:middle]):
            low = middle
        else:
            high = middle - 1
    if not fits(context_prompt[:low]):
        raise ChatContractError("context_wrapper_too_large")
    return context_prompt[:low]


class AIConnector(Protocol):
    async def generate_response(
        self,
        message_content: str,
        author_name: str,
        channel_type: str,
        is_mention: bool = True,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context_prompt: str = "",
        history: Sequence[ChatTurn] = (),
    ) -> tuple[bool, str]:
        raise NotImplementedError


__all__ = [
    "AIConnector",
    "ChatContractError",
    "ChatTurn",
    "HistoryPolicy",
    "REDACTED_AUTH_TURN",
    "_SENSITIVE_PAYLOAD_KEYS",
    "build_context_prompt",
    "capture_history_policy",
    "fit_context_prompt_in_wrapper",
    "history_policy_for_effective_routes",
    "history_safe_content",
    "prepare_history",
    "sanitize_chat_turn_content",
]
