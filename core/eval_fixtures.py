"""Bounded in-memory state names for natural-language evaluation."""

from enum import Enum


class EvalFixture(str, Enum):
    EMPTY = "empty"
    ACTIVE_POLL = "active_poll"
    ACTIVE_REMINDER = "active_reminder"
    CALENDAR_TITLE_MEETING = "calendar_title_meeting"
    MENTIONED_USER_42 = "mentioned_user_42"
    MIXED_STATE = "mixed_state"
