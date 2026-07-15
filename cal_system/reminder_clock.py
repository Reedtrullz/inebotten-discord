"""Shared clock boundary for reminder scheduling and runtime checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


OSLO = ZoneInfo("Europe/Oslo")


class ReminderClock(Protocol):
    def now(self) -> datetime:
        raise NotImplementedError

    def epoch(self) -> float:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SystemReminderClock:
    timezone: ZoneInfo = OSLO

    def __post_init__(self) -> None:
        probe = datetime(2000, 1, 1, tzinfo=self.timezone)
        if probe.tzinfo is None or probe.utcoffset() is None:
            raise ValueError("naive_reminder_clock")

    def now(self) -> datetime:
        value = datetime.now(self.timezone)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive_reminder_clock")
        return value

    def epoch(self) -> float:
        return self.now().timestamp()


@dataclass(slots=True)
class MutableReminderClock:
    """Small deterministic clock used at reminder composition boundaries."""

    current: datetime

    def __post_init__(self) -> None:
        self._require_aware(self.current)

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive_reminder_clock")

    def now(self) -> datetime:
        self._require_aware(self.current)
        return self.current

    def epoch(self) -> float:
        return self.now().timestamp()

    def advance(self, delta: timedelta) -> None:
        if not isinstance(delta, timedelta):
            raise TypeError("reminder_clock_delta_must_be_timedelta")
        self.current += delta
        self._require_aware(self.current)
