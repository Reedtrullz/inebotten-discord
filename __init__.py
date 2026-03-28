"""
Inebotten Discord Bot

Usage:
    python3 run_both.py          # Start everything
    python3 selfbot_runner.py    # Bot only (bridge must run)
"""

__version__ = "2.0.0"
__author__ = "reedtrullz"

# Convenient imports
from core.message_monitor import MessageMonitor
from cal_system.calendar_manager import CalendarManager
from ai.hermes_connector import HermesConnector
