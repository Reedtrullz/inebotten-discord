"""Task-local delivery receipts and the single Discord send admission path."""

from __future__ import annotations

import asyncio
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

import discord

from core.dispatch_result import (
    DeliveryState,
    MessageSendCancelled,
    MessageSendResult,
)


@dataclass(slots=True)
class SendReceipt:
    """Aggregate the delivery truth observed by one dispatch task."""

    result: MessageSendResult | None = None

    def observe(self, result: MessageSendResult) -> None:
        current = self.result
        if current is not None and current.state is DeliveryState.UNKNOWN:
            return
        if result.state is DeliveryState.UNKNOWN:
            self.result = result
        elif current is not None and {
            current.state,
            result.state,
        } == {
            DeliveryState.DELIVERED,
            DeliveryState.NOT_DELIVERED,
        }:
            self.result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "partial_send",
            )
        elif result.state is DeliveryState.DELIVERED:
            self.result = result
        elif current is None:
            self.result = result


_CURRENT_RECEIPT: ContextVar[SendReceipt | None] = ContextVar(
    "dispatch_send_receipt",
    default=None,
)


@contextmanager
def capture_send_receipt() -> Iterator[SendReceipt]:
    receipt = SendReceipt()
    token = _CURRENT_RECEIPT.set(receipt)
    try:
        yield receipt
    finally:
        _CURRENT_RECEIPT.reset(token)


def record_send_result(result: MessageSendResult) -> None:
    receipt = _CURRENT_RECEIPT.get()
    if receipt is not None:
        receipt.observe(result)


async def _settle_owned_send(
    owned_send: asyncio.Task[MessageSendResult],
) -> MessageSendResult:
    """Settle one shielded send and retain genuine outer cancellation.

    The caller owns ``owned_send``.  Cancellation of the caller is temporarily
    consumed only so that the already-started send can reach terminal local
    truth.  The terminal result is recorded exactly once before cancellation is
    re-raised as a result-carrying ``MessageSendCancelled``.
    """

    outer_cancelled = False
    while True:
        try:
            candidate = await asyncio.shield(owned_send)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            cancellation_requests = current.cancelling() if current else 0
            if cancellation_requests:
                outer_cancelled = True
                for _ in range(cancellation_requests):
                    current.uncancel()
                continue
            result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_cancelled",
            )
            break
        except Exception:
            result = MessageSendResult(
                DeliveryState.UNKNOWN,
                "send_task_exception",
            )
            break
        else:
            result = (
                candidate
                if isinstance(candidate, MessageSendResult)
                else MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "send_task_exception",
                )
            )
            break

    record_send_result(result)
    if outer_cancelled:
        raise MessageSendCancelled(result)
    return result


class DiscordSendCoordinator:
    """Serialize rate admission, Discord I/O, and attempt accounting."""

    def __init__(self, rate_limiter) -> None:
        self.rate_limiter = rate_limiter
        self._admission_lock = asyncio.Lock()

    @staticmethod
    def _record(rate_limiter, method: str, *args, **kwargs) -> None:
        callback = getattr(rate_limiter, method, None)
        if not callable(callback):
            return
        try:
            callback(*args, **kwargs)
        except Exception:
            # Accounting is telemetry.  It must not rewrite known send truth.
            return

    @staticmethod
    def _channel_adapter(message):
        channel = getattr(message, "channel", None)
        if channel is None:
            return None, "missing_channel", False

        channel_id = getattr(channel, "id", None)
        if (
            not isinstance(channel_id, int)
            or isinstance(channel_id, bool)
            or channel_id <= 0
        ):
            return None, "invalid_channel", False

        direct = isinstance(
            channel,
            (discord.DMChannel, discord.GroupChannel),
        )
        adapter = (
            getattr(channel, "send", None)
            if direct
            else getattr(message, "reply", None)
        )
        if not callable(adapter):
            return None, "missing_adapter", direct
        return adapter, None, direct

    async def send_result(self, message, text: str) -> MessageSendResult:
        if not isinstance(text, str) or not text:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "empty",
            )

        adapter, adapter_error, direct = self._channel_adapter(message)
        if adapter_error is not None:
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                adapter_error,
            )

        wait_if_needed = getattr(
            self.rate_limiter,
            "wait_if_needed",
            None,
        )
        if not callable(wait_if_needed):
            return MessageSendResult(
                DeliveryState.NOT_DELIVERED,
                "missing_adapter",
            )

        async with self._admission_lock:
            try:
                wait_result = wait_if_needed()
                if inspect.isawaitable(wait_result):
                    wait_result = await wait_result
            except asyncio.CancelledError:
                raise
            except Exception:
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "missing_adapter",
                )
            if not wait_result:
                self._record(self.rate_limiter, "record_dropped")
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "daily_quota",
                )

            async def attempt() -> None:
                kwargs = {
                    "allowed_mentions": discord.AllowedMentions.none(),
                    "suppress_embeds": True,
                }
                if direct:
                    await adapter(text, **kwargs)
                else:
                    await adapter(
                        text,
                        mention_author=False,
                        **kwargs,
                    )

            try:
                await asyncio.wait_for(attempt(), timeout=15.0)
            except discord.errors.Forbidden:
                self._record(self.rate_limiter, "record_failure")
                return MessageSendResult(
                    DeliveryState.NOT_DELIVERED,
                    "forbidden",
                )
            except discord.errors.HTTPException as exc:
                self._record(self.rate_limiter, "record_sent")
                self._record(
                    self.rate_limiter,
                    "record_failure",
                    is_rate_limit=(getattr(exc, "status", None) == 429),
                )
                return MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "http",
                )
            except TimeoutError:
                self._record(self.rate_limiter, "record_sent")
                self._record(self.rate_limiter, "record_failure")
                return MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "timeout",
                )
            except Exception:
                self._record(self.rate_limiter, "record_sent")
                self._record(self.rate_limiter, "record_failure")
                return MessageSendResult(
                    DeliveryState.UNKNOWN,
                    "transport",
                )

            self._record(self.rate_limiter, "record_sent")
            return MessageSendResult(DeliveryState.DELIVERED)
