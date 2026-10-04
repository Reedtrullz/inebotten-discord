#!/usr/bin/env python3
"""Discord help from the same catalogue used by dispatch and reference views."""
from core.command_registry import command_help_pages
from features.base_handler import BaseHandler


class HelpHandler(BaseHandler):
    async def handle_help(self, message) -> None:
        for page in command_help_pages():
            result = await self.send_response(message, page)
            # Do not queue subsequent pages after an explicitly failed send.
            if result is None or getattr(result, 'status', None) in ('dropped', 'forbidden', 'unknown', 'retryable'):
                break
