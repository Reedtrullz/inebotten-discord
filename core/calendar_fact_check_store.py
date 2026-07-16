"""Memory-only, exact-conversation state for calendar fact-check inquiries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

from core.message_context import ConversationKey


class CalendarFactCheckPhase(str, Enum):
    CHOOSING_TARGET = "choosing_target"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class CalendarFactCheckTarget:
    stable_id: str
    revision: str
    title: str
    date: str
    time: str | None


@dataclass(frozen=True, slots=True)
class CalendarFactCheckInquiry:
    key: ConversationKey
    phase: CalendarFactCheckPhase
    targets: tuple[CalendarFactCheckTarget, ...]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CalendarFactCheckLookup:
    inquiry: CalendarFactCheckInquiry | None
    expired: bool = False


class CalendarFactCheckStore:
    """Own bounded non-executable inquiry state without persistence."""

    def __init__(
        self,
        *,
        now_provider: Callable[[], datetime],
        ttl: timedelta = timedelta(minutes=10),
        max_candidates: int = 5,
        max_inquiries: int = 1_000,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("invalid_ttl")
        if not 1 <= max_candidates <= 5:
            raise ValueError("invalid_candidate_limit")
        if not 1 <= max_inquiries <= 1_000:
            raise ValueError("invalid_inquiry_limit")
        self._now_provider = now_provider
        self._ttl = ttl
        self._max_candidates = max_candidates
        self._max_inquiries = max_inquiries
        self._inquiries: dict[ConversationKey, CalendarFactCheckInquiry] = {}

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive_clock")
        return value

    def _purge_expired(self, now: datetime, *, except_key=None) -> None:
        expired = tuple(
            key
            for key, inquiry in self._inquiries.items()
            if key != except_key and now >= inquiry.expires_at
        )
        for key in expired:
            self._inquiries.pop(key, None)

    def begin(
        self,
        key: ConversationKey,
        targets: tuple[CalendarFactCheckTarget, ...],
    ) -> CalendarFactCheckInquiry:
        if not isinstance(targets, tuple) or not 1 <= len(targets) <= self._max_candidates:
            raise ValueError("invalid_candidate_count")
        if any(not isinstance(target, CalendarFactCheckTarget) for target in targets):
            raise ValueError("invalid_candidate")
        if len({target.stable_id for target in targets}) != len(targets):
            raise ValueError("duplicate_candidate")
        now = self._now()
        self._purge_expired(now)
        if key not in self._inquiries and len(self._inquiries) >= self._max_inquiries:
            evicted = min(
                self._inquiries.values(),
                key=lambda inquiry: (
                    inquiry.expires_at,
                    inquiry.created_at,
                    -1 if inquiry.key.guild_id is None else inquiry.key.guild_id,
                    inquiry.key.channel_id,
                    inquiry.key.user_id,
                ),
            )
            self._inquiries.pop(evicted.key, None)
        inquiry = CalendarFactCheckInquiry(
            key=key,
            phase=(
                CalendarFactCheckPhase.READY
                if len(targets) == 1
                else CalendarFactCheckPhase.CHOOSING_TARGET
            ),
            targets=targets,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._inquiries[key] = inquiry
        return inquiry

    def lookup(self, key: ConversationKey) -> CalendarFactCheckLookup:
        now = self._now()
        inquiry = self._inquiries.get(key)
        if inquiry is not None and now >= inquiry.expires_at:
            self._inquiries.pop(key, None)
            self._purge_expired(now)
            return CalendarFactCheckLookup(None, expired=True)
        self._purge_expired(now, except_key=key)
        return CalendarFactCheckLookup(inquiry)

    def select(self, key: ConversationKey, number: int) -> CalendarFactCheckInquiry:
        lookup = self.lookup(key)
        inquiry = lookup.inquiry
        if inquiry is None:
            raise ValueError("inquiry_not_found")
        if inquiry.phase is not CalendarFactCheckPhase.CHOOSING_TARGET:
            raise ValueError("wrong_phase")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(inquiry.targets):
            raise ValueError("invalid_selection")
        selected = replace(
            inquiry,
            phase=CalendarFactCheckPhase.READY,
            targets=(inquiry.targets[number - 1],),
        )
        self._inquiries[key] = selected
        return selected

    def cancel(self, key: ConversationKey) -> bool:
        self._now()
        return self._inquiries.pop(key, None) is not None
