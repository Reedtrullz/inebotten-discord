"""Shared clock boundary for reminder scheduling and runtime checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
