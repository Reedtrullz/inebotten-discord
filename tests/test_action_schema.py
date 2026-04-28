#!/usr/bin/env python3
"""Regression tests for structured action schemas."""

# pyright: reportMissingImports=false, reportAttributeAccessIssue=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportPrivateUsage=false, reportAny=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ai.action_schema import NoAction, SaveEventAction, ShowDashboardAction
from core.message_monitor import MessageMonitor


class FakeCalendarHandler:
    def __init__(self):
        self.calls = []

    async def handle_calendar_item(self, message, parsed_event):
        self.calls.append((message, parsed_event))


class FakeMessage:
    def __init__(self, content="", guild_id=None, channel_id=123, author_id=7):
        self.content = content
        self.guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
        self.channel = SimpleNamespace(id=channel_id)
        self.author = SimpleNamespace(id=author_id)


class ActionSchemaTests(unittest.IsolatedAsyncioTestCase):
    def make_monitor(self):
        monitor = MessageMonitor.__new__(MessageMonitor)
        monitor.handlers = {}
        monitor.nlp_parser = SimpleNamespace(parse_event=lambda text: {"title": "Møte"})
        monitor.user_memory = SimpleNamespace(get_memory=AsyncMock(return_value={"location": "Oslo"}))
        monitor._generate_dashboard = AsyncMock(return_value="dashboard")
        monitor._send_response = AsyncMock()
        return monitor

    def test_save_event_defaults(self):
        action = SaveEventAction()
        self.assertEqual(action.action, "SAVE_EVENT")
        self.assertEqual(action.title, "")

    def test_save_event_with_values(self):
        action = SaveEventAction(title="Møte", date="01.05.2025", time="14:00")
        self.assertEqual(action.title, "Møte")
        self.assertEqual(action.date, "01.05.2025")

    def test_show_dashboard_action(self):
        action = ShowDashboardAction()
        self.assertEqual(action.action, "SHOW_DASHBOARD")

    def test_no_action(self):
        action = NoAction()
        self.assertEqual(action.action, "NONE")

    def test_save_event_to_json(self):
        action = SaveEventAction(title="Møte", date="01.05.2025", time="14:00")
        data = json.dumps(action.__dict__)
        parsed = json.loads(data)
        self.assertEqual(parsed["action"], "SAVE_EVENT")
        self.assertEqual(parsed["title"], "Møte")

    async def test_json_action_executes_save_event(self):
        monitor = self.make_monitor()
        handler = FakeCalendarHandler()
        monitor.handlers["calendar"] = handler
        message = FakeMessage("{\"action\": \"SAVE_EVENT\", \"title\": \"Møte\", \"date\": \"01.05.2025\", \"time\": \"14:00\"}")

        cleaned = await monitor._parse_and_execute_actions(message.content, message)

        self.assertEqual(cleaned, "")
        self.assertEqual(len(handler.calls), 1)
        _, parsed_event = handler.calls[0]
        self.assertEqual(parsed_event, {"title": "Møte"})

    async def test_old_format_still_parseable(self):
        monitor = self.make_monitor()
        handler = FakeCalendarHandler()
        monitor.handlers["calendar"] = handler
        message = FakeMessage("[SAVE_EVENT: Møte | 01.05.2025 | 14:00]")

        cleaned = await monitor._parse_and_execute_actions(message.content, message)

        self.assertEqual(cleaned, "")
        self.assertEqual(len(handler.calls), 1)

    async def test_malformed_json_ignored(self):
        monitor = self.make_monitor()
        message = FakeMessage("{not valid json}")

        cleaned = await monitor._parse_and_execute_actions(message.content, message)

        self.assertEqual(cleaned, "{not valid json}")
