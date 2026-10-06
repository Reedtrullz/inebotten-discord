"""Conservative quotas reserved before an awaited Discord send."""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta
import math
import threading
import time
import uuid


class RateLimiter:
    def __init__(self, max_per_second=5, daily_quota=10000, safe_interval=0):
        if not 1 <= max_per_second <= 5 or not 1 <= daily_quota <= 10000:
            raise ValueError('Rate limits must remain within 5/sec and 10000/day')
        if not math.isfinite(safe_interval) or safe_interval < 0:
            raise ValueError('Invalid safe interval')
        self.max_per_second = max_per_second
        self.daily_quota = daily_quota
        self.safe_interval = safe_interval
        self.message_times = deque()
        self._attempts = deque()
        self._reservations = {}
        self._lock = threading.RLock()
        self.daily_count = 0
        self.day_start = datetime.now().date()
        self.consecutive_failures = 0
        self.last_failure_time = None
        self.backoff_until = None
        self._backoff_deadline = 0
        self.total_sent = 0
        self.total_dropped = 0
        self.total_unknown = 0

    def _refresh(self):
        today = datetime.now().date()
        if today != self.day_start:
            self.day_start = today
            self.daily_count = 0
        now = time.monotonic()
        while self._attempts and self._attempts[0][0] <= now - max(1, self.safe_interval):
            self._attempts.popleft()
        cutoff = datetime.now() - timedelta(seconds=1)
        while self.message_times and self.message_times[0] <= cutoff:
            self.message_times.popleft()
        return now

    def _check(self):
        now = self._refresh()
        if now < self._backoff_deadline:
            return False, f'in_backoff:{self._backoff_deadline-now:.3f}s', self._backoff_deadline-now
        if self.daily_count + len(self._reservations) >= self.daily_quota:
            return False, 'daily_quota_exceeded', None
        recent = [pair for pair in self._attempts if pair[0] > now - 1]
        if len(recent) >= self.max_per_second:
            wait = max(.001, recent[0][0] + 1 - now)
            return False, f'rate_limited:{wait:.3f}s', wait
        if self._attempts and now < self._attempts[-1][0] + self.safe_interval:
            wait = self._attempts[-1][0] + self.safe_interval - now
            return False, f'rate_limited:{wait:.3f}s', wait
        return True, 'ok', 0

    def can_send(self):
        with self._lock:
            allowed, reason, _ = self._check()
            return allowed, reason

    async def wait_if_needed(self):
        while True:
            with self._lock:
                allowed, _, delay = self._check()
            if allowed:
                return True
            if delay is None:
                return False
            await asyncio.sleep(min(max(.001, delay), 5))

    async def reserve(self, deadline: float):
        while time.monotonic() < deadline:
            with self._lock:
                allowed, _, delay = self._check()
                if allowed:
                    token = uuid.uuid4().hex
                    now = time.monotonic()
                    self._reservations[token] = now
                    self._attempts.append((now, token))
                    return token
                # A pending reservation may finish without consuming quota.
                if delay is None and self.daily_count >= self.daily_quota:
                    return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, max(.001, delay or .01)))
        return None

    def release(self, token, *, attempted=False):
        with self._lock:
            self._reservations.pop(token, None)
            if not attempted:
                self._attempts = deque(pair for pair in self._attempts if pair[1] != token)

    def finish(self, token, *, delivered=False, unknown=False):
        with self._lock:
            if token not in self._reservations:
                return
            self._refresh()
            self._reservations.pop(token)
            if delivered or unknown:
                self.daily_count += 1
            if delivered:
                self.total_sent += 1
                self.message_times.append(datetime.now())
                self.consecutive_failures = 0
            elif unknown:
                self.total_unknown += 1

    def record_sent(self):
        """Compatibility accounting; new sender paths use finish(reservation)."""
        with self._lock:
            self._refresh()
            self._attempts.append((time.monotonic(), None))
            self.message_times.append(datetime.now())
            self.daily_count += 1
            self.total_sent += 1
            self.consecutive_failures = 0

    def record_failure(self, is_rate_limit=False, retry_after_s=None):
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = datetime.now()
            if is_rate_limit or self.consecutive_failures >= 3:
                seconds = retry_after_s if retry_after_s is not None else min(2 ** self.consecutive_failures, 30)
                self._backoff_deadline = max(self._backoff_deadline, time.monotonic()+seconds)
                self.backoff_until = self.last_failure_time + timedelta(seconds=seconds)

    def record_dropped(self):
        with self._lock:
            self.total_dropped += 1

    def get_stats(self):
        with self._lock:
            now = self._refresh()
            remaining = max(0, self._backoff_deadline-now)
            return {'sent_last_second': len(self.message_times), 'sent_today': self.daily_count,
                    'daily_quota': self.daily_quota,
                    'quota_remaining': max(0, self.daily_quota-self.daily_count-len(self._reservations)),
                    'reserved': len(self._reservations), 'total_sent': self.total_sent,
                    'total_dropped': self.total_dropped, 'total_unknown': self.total_unknown,
                    'consecutive_failures': self.consecutive_failures,
                    'in_backoff': remaining > 0, 'backoff_remaining': remaining}

    def get_status_line(self):
        stats = self.get_stats()
        return f"[RateLimit] Today: {stats['sent_today']}/{self.daily_quota} | Last sec: {stats['sent_last_second']}/{self.max_per_second}"


def create_rate_limiter(config):
    interval = getattr(config, 'SAFE_INTERVAL', timedelta(seconds=1))
    return RateLimiter(max_per_second=config.MAX_MSGS_PER_SECOND, daily_quota=config.DAILY_QUOTA,
                       safe_interval=interval.total_seconds())
