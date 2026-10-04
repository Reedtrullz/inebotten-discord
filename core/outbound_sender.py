"""One bounded outbound path; a missing acknowledgement is never success."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field, replace
import inspect
import hashlib
import math
import time
from typing import Literal, Any

from core.rate_limiter import RateLimiter


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal['delivered', 'dropped', 'retryable', 'forbidden', 'unknown']
    message_id: str | None = None
    retry_after_s: float | None = None
    reason_code: str = 'unspecified'
    message: Any = field(default=None, repr=False, compare=False)


class _LegacyLimiter:
    """Serial adapter for existing non-reserving integrations/test doubles."""
    def __init__(self, limiter):
        self.limiter = limiter
        self.lock = asyncio.Lock()

    async def reserve(self, deadline):
        await self.lock.acquire()
        try:
            if not self.limiter.can_send()[0]:
                self.lock.release()
                return None
            wait = self.limiter.wait_if_needed()
            if inspect.isawaitable(wait):
                wait = await wait
            if not wait:
                self.lock.release()
                return None
            return True
        except BaseException:
            self.lock.release()
            raise

    def finish(self, token, *, delivered=False, unknown=False):
        if delivered:
            self.limiter.record_sent()
        self.lock.release()

    def release(self, token, *, attempted=False):
        self.lock.release()

    def record_dropped(self):
        if hasattr(self.limiter, 'record_dropped'):
            self.limiter.record_dropped()

    def record_failure(self, is_rate_limit=False, retry_after_s=None):
        self.limiter.record_failure(is_rate_limit=is_rate_limit)


class OutboundSender:
    def __init__(self, get_channel, limiter=None, *, send_channel_message=None, capacity=4096):
        self.get_channel = get_channel
        self.limiter = limiter if limiter is not None else RateLimiter(safe_interval=1)
        self._quota = self.limiter if isinstance(self.limiter, RateLimiter) else _LegacyLimiter(self.limiter)
        self.send_channel_message = send_channel_message
        self.capacity = capacity
        self._results = OrderedDict()
        self._inflight = {}
        self._closed = False

    async def send(self, channel_id: str, text: str, *, delivery_key: str | None = None,
                   deadline: float, _dispatch=None) -> DeliveryResult:
        if not math.isfinite(deadline) or deadline <= time.monotonic():
            return DeliveryResult('dropped', reason_code='deadline_expired')
        if self._closed:
            return DeliveryResult('dropped', reason_code='sender_closed')
        if not channel_id or not text:
            return DeliveryResult('dropped', reason_code='missing_destination_or_text')
        if delivery_key:
            if delivery_key in self._results:
                return replace(self._results[delivery_key], reason_code='cached_receipt')
            if delivery_key in self._inflight:
                try:
                    async with asyncio.timeout_at(deadline):
                        result = await asyncio.shield(self._inflight[delivery_key])
                    return replace(result, reason_code='cached_receipt')
                except TimeoutError:
                    return DeliveryResult('unknown', reason_code='duplicate_wait_deadline')
            if len(self._results) + len(self._inflight) >= self.capacity:
                # Unknown receipts are never evicted into a blind retry.
                removable = next((key for key, result in self._results.items() if result.status == 'delivered'), None)
                if removable is None:
                    return DeliveryResult('dropped', reason_code='receipt_capacity')
                del self._results[removable]
        future = asyncio.get_running_loop().create_future()
        if delivery_key:
            self._inflight[delivery_key] = future
        result = DeliveryResult('unknown', reason_code='interrupted')
        attempt_state = {'started': False}
        try:
            result = await self._attempt(channel_id, text, deadline, _dispatch, attempt_state)
            return result
        except asyncio.CancelledError as error:
            if not attempt_state['started']:
                result = DeliveryResult('dropped', reason_code='cancelled_before_send')
            error.delivery_result = result
            raise
        finally:
            if delivery_key:
                self._inflight.pop(delivery_key, None)
                # Definitively rejected requests can be retried later.
                if result.status in ('delivered', 'unknown'):
                    self._results[delivery_key] = replace(result, message=None)
                if not future.done():
                    future.set_result(result)

    async def _attempt(self, channel_id, text, deadline, dispatch, attempt_state):
        if dispatch is None:
            try:
                channel = self.get_channel(int(channel_id)) if self.get_channel else None
                if inspect.isawaitable(channel):
                    async with asyncio.timeout_at(deadline):
                        channel = await channel
                if channel is not None:
                    dispatch = channel.send
                elif self.send_channel_message:
                    dispatch = lambda content: self.send_channel_message(int(channel_id), content)
                else:
                    self._quota.record_dropped()
                    return DeliveryResult('dropped', reason_code='destination_unavailable')
            except (ValueError, TypeError):
                return DeliveryResult('dropped', reason_code='invalid_destination')
            except TimeoutError:
                return DeliveryResult('retryable', reason_code='lookup_timeout')
            except Exception:
                return DeliveryResult('retryable', reason_code='lookup_failed')
        for attempt in range(2):
            token = None
            started = False
            try:
                async with asyncio.timeout_at(deadline):
                    token = await self._quota.reserve(deadline)
                    if token is None:
                        self._quota.record_dropped()
                        return DeliveryResult('dropped', reason_code='quota_or_deadline')
                    started = True
                    attempt_state['started'] = True
                    message = await dispatch(text)
                message_id = getattr(message, 'id', None)
                if type(message_id) not in (str, int) or not str(message_id):
                    self._quota.finish(token, unknown=True)
                    token = None
                    return DeliveryResult('unknown', reason_code='missing_message_evidence')
                self._quota.finish(token, delivered=True)
                token = None
                return DeliveryResult('delivered', str(message_id), reason_code='remote_message', message=message)
            except asyncio.CancelledError:
                if token is not None:
                    if started:
                        self._quota.finish(token, unknown=True)
                    else:
                        self._quota.release(token, attempted=False)
                    token = None
                raise
            except TimeoutError:
                if token is not None:
                    self._quota.finish(token, unknown=started)
                    token = None
                if started:
                    return DeliveryResult('unknown', reason_code='send_timeout')
                return DeliveryResult('dropped', reason_code='reservation_deadline')
            except Exception as error:
                status = getattr(error, 'status', None)
                if status == 403 or error.__class__.__name__ == 'Forbidden':
                    self._quota.release(token, attempted=True)
                    token = None
                    self._quota.record_failure()
                    return DeliveryResult('forbidden', reason_code='remote_forbidden')
                if status == 429:
                    attempt_state['started'] = False
                    delay = _retry_after(error)
                    self._quota.release(token, attempted=True)
                    token = None
                    self._quota.record_failure(is_rate_limit=True, retry_after_s=delay)
                    if attempt == 0 and delay is not None and time.monotonic()+delay < deadline:
                        await asyncio.sleep(delay)
                        continue
                    return DeliveryResult('retryable', retry_after_s=delay, reason_code='remote_rate_limit')
                self._quota.finish(token, unknown=started)
                token = None
                self._quota.record_failure()
                return DeliveryResult('unknown' if started else 'retryable', reason_code='send_failed' if started else 'reservation_failed')
            finally:
                if token is not None:
                    self._quota.release(token, attempted=started)
        return DeliveryResult('retryable', reason_code='retry_budget')

    async def reply(self, message, text, *, deadline=None, mention_author=False):
        import discord
        if isinstance(message.channel, (discord.DMChannel, discord.GroupChannel)):
            dispatch = message.channel.send
        else:
            dispatch = lambda content: message.reply(content, mention_author=mention_author)
        content_key = hashlib.sha256(text.encode()).hexdigest() if text else 'empty'
        key = f'reply:{message.channel.id}:{message.id}:{content_key}' if getattr(message, 'id', None) is not None else None
        return await self.send(str(message.channel.id), text, delivery_key=key,
                               deadline=deadline or time.monotonic()+10, _dispatch=dispatch)

    def close(self):
        self._closed = True


def _retry_after(error):
    value = getattr(error, 'retry_after', None)
    if value is None:
        response = getattr(error, 'response', None)
        value = getattr(response, 'headers', {}).get('Retry-After') if response else None
    try:
        delay = float(value)
        return delay if math.isfinite(delay) and delay >= 0 else None
    except (ValueError, TypeError):
        return None


def monitor_sender(monitor):
    sender = getattr(monitor, 'outbound', None)
    if sender is None:
        sender = OutboundSender(getattr(monitor.client, 'get_channel', None), monitor.rate_limiter)
        monitor.outbound = sender
    return sender
