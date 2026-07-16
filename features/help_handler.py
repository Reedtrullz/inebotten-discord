#!/usr/bin/env python3
"""Discord renderer for the executable shared help catalog."""

from __future__ import annotations

from core.dispatch_result import (
    DeliveryState,
    DispatchCancelled,
    DispatchOutcome,
    MessageSendCancelled,
    MessageSendResult,
)
from core.help_registry import render_discord_help_chunks
from core.send_receipt import record_send_result
from features.base_handler import BaseHandler


def _partial_response_outcome() -> DispatchOutcome:
    aggregate = MessageSendResult(
        DeliveryState.UNKNOWN,
        "partial_send",
    )
    record_send_result(aggregate)
    return DispatchOutcome.failure(
        "partial_response_sent",
        retryable=False,
    ).with_delivery(aggregate)


def _first_failure(result: MessageSendResult) -> DispatchOutcome:
    if result.state is DeliveryState.NOT_DELIVERED:
        return DispatchOutcome.failure(
            "response_send_failed",
            retryable=True,
        ).with_delivery(result)
    return DispatchOutcome.failure(
        "response_delivery_unknown",
        retryable=False,
    ).with_delivery(result)


class HelpHandler(BaseHandler):
    """Send registry-rendered help without replaying delivered prefixes."""

    async def handle_help(self, message) -> DispatchOutcome:
        chunks = render_discord_help_chunks(self.loc.current_lang)
        delivered = 0
        for index, chunk in enumerate(chunks):
            try:
                result = await self.send_response_result(message, chunk)
            except MessageSendCancelled as exc:
                if delivered or exc.result.state is DeliveryState.DELIVERED:
                    if index < len(chunks) - 1:
                        outcome = _partial_response_outcome()
                    else:
                        outcome = DispatchOutcome.success().with_delivery(
                            exc.result
                        )
                else:
                    outcome = _first_failure(exc.result)
                raise DispatchCancelled(outcome) from None

            if result.state is DeliveryState.DELIVERED:
                delivered += 1
                continue
            if delivered:
                return _partial_response_outcome()
            return _first_failure(result)

        if not chunks:
            return DispatchOutcome.failure(
                "response_send_failed",
                retryable=False,
            )
        return DispatchOutcome.success().with_delivery(
            MessageSendResult(DeliveryState.DELIVERED)
        )
