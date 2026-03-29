#!/usr/bin/env python3
"""
Features package for Inebotten Discord selfbot.

This package contains handlers for all bot features.
"""

from features.base_handler import BaseHandler
from features.fun_handler import FunHandler
from features.utility_handler import UtilityHandler
from features.countdown_handler import CountdownHandler
from features.polls_handler import PollsHandler
from features.calendar_handler import CalendarHandler
from features.watchlist_handler import WatchlistHandler
from features.aurora_handler import AuroraHandler
from features.school_holidays_handler import SchoolHolidaysHandler
from features.help_handler import HelpHandler
from features.daily_digest_handler import DailyDigestHandler

__all__ = [
    "BaseHandler",
    "FunHandler",
    "UtilityHandler",
    "CountdownHandler",
    "PollsHandler",
    "CalendarHandler",
    "WatchlistHandler",
    "AuroraHandler",
    "SchoolHolidaysHandler",
    "HelpHandler",
    "DailyDigestHandler",
]
