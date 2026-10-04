"""Validated inference outcomes and a zero-queue admission gate."""

import asyncio
from dataclasses import dataclass
import math
import time
from typing import Awaitable, Callable, Literal


AIStatus = Literal[
    "success", "busy", "cancelled", "auth_error", "retryable", "unavailable"
]
AI_STATUSES = frozenset(
    {"success", "busy", "cancelled", "auth_error", "retryable", "unavailable"}
)
MAX_AI_TEXT_CHARS = 20_000
MAX_AI_PROMPT_CHARS = 50_000
MAX_AI_IN_FLIGHT = 2
MAX_RETRY_AFTER_S = 3_600.0


def parse_retry_after(value, *, default: float) -> float:
    """Normalize an untrusted Retry-After header to a finite bounded delay."""
    try:
        delay = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(delay):
        return default
    return min(max(delay, 0.0), MAX_RETRY_AFTER_S)


@dataclass(frozen=True, slots=True)
class AIResult:
    """One unambiguous provider outcome, safe to pass across app layers."""

    status: AIStatus
    text: str | None
    provider: str
    model: str | None = None
    fallback: bool = False
    retry_after_s: float | None = None

    def __post_init__(self):
        if not isinstance(self.status, str) or self.status not in AI_STATUSES:
            raise ValueError(f"Unsupported AI status: {self.status!r}")
        if not isinstance(self.provider, str) or not self.provider or len(self.provider) > 80:
            raise ValueError("AI result requires a bounded provider name")
        if self.model is not None and (
            not isinstance(self.model, str) or len(self.model) > 160
        ):
            raise ValueError("AI model name must be a bounded string or None")
        if not isinstance(self.fallback, bool):
            raise ValueError("AI fallback marker must be boolean")
        if self.status == "success":
            if not isinstance(self.text, str):
                raise ValueError("Successful AI results require text")
            if len(self.text) > MAX_AI_TEXT_CHARS:
                raise ValueError("AI response exceeds the configured size limit")
        elif self.text is not None:
            raise ValueError("Failed AI results cannot contain response text")
        if self.retry_after_s is not None:
            if (
                isinstance(self.retry_after_s, bool)
                or not isinstance(self.retry_after_s, (int, float))
                or not math.isfinite(self.retry_after_s)
                or self.retry_after_s < 0
                or self.retry_after_s > MAX_RETRY_AFTER_S
            ):
                raise ValueError("retry_after_s must be a bounded non-negative number")

    def legacy_tuple(self) -> tuple[bool, str]:
        """Adapt old callers without weakening the structured monitor contract."""
        if self.status == "success":
            return True, self.text or ""
        if self.status == "busy":
            delay = (
                f" (retry after {self.retry_after_s:g}s)"
                if self.retry_after_s is not None
                else ""
            )
            return False, f"Provider is busy{delay}"
        messages = {
            "cancelled": "Request cancelled",
            "auth_error": "Provider authentication failed",
            "retryable": "Provider request failed temporarily",
            "unavailable": "Provider is unavailable",
        }
        return False, messages[self.status]


class BoundedAdmission:
    """Reject excess inference immediately; there is no waiter queue."""

    def __init__(self, max_in_flight: int = MAX_AI_IN_FLIGHT):
        if isinstance(max_in_flight, bool) or not isinstance(max_in_flight, int):
            raise ValueError("max_in_flight must be a positive integer")
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be a positive integer")
        self.max_in_flight = max_in_flight
        self.in_flight = 0

    async def run(
        self,
        operation: Callable[[], Awaitable[AIResult]],
        *,
        deadline: float,
        provider: str,
        model: str | None,
    ) -> AIResult:
        if self.in_flight >= self.max_in_flight:
            return AIResult("busy", None, provider, model)

        remaining = deadline - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            return AIResult("cancelled", None, provider, model)

        self.in_flight += 1
        try:
            try:
                result = await asyncio.wait_for(operation(), timeout=remaining)
            except asyncio.TimeoutError:
                return AIResult("cancelled", None, provider, model)
            if not isinstance(result, AIResult):
                return AIResult("unavailable", None, provider, model)
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            return AIResult("unavailable", None, provider, model)
        finally:
            self.in_flight -= 1
