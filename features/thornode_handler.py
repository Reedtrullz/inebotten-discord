#!/usr/bin/env python3
"""
THORNode Withdrawal Handler for Inebotten
Provides command interface for THORNode monitoring via @inebotten mentions.
"""

from features.base_handler import BaseHandler


class THORNodeHandler(BaseHandler):
    def __init__(self, monitor):
        super().__init__(monitor)
        self.thornode = monitor.thornode

    async def handle_thornode_status(self, message):
        can_send, reason = await self.check_rate_limit()
        if not can_send:
            return

        node_data = await self.thornode.fetch_node_status()
        eligibility = self.thornode.check_withdrawal_eligibility(node_data)
        msg = self.thornode.format_status_message(eligibility)
        await self.send_response(message, msg)
