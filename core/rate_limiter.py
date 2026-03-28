#!/usr/bin/env python3
"""
Rate Limiter for Discord Selfbot
Enforces Discord's rate limits to avoid account flags
"""

import time
import asyncio
from datetime import datetime, timedelta
from collections import deque

class RateLimiter:
    """
    Comprehensive rate limiting for Discord selfbot
    - Per-second burst limit (5 msgs/sec)
    - Daily quota limit (10,000 msgs/day)
    - Exponential backoff on failures
    """
    
    def __init__(self, max_per_second=5, daily_quota=10000):
        self.max_per_second = max_per_second
        self.daily_quota = daily_quota
        
        # Message tracking
        self.message_times = deque()
        self.daily_count = 0
        self.day_start = datetime.now().date()
        
        # Backoff state
        self.consecutive_failures = 0
        self.last_failure_time = None
        self.backoff_until = None
        
        # Statistics
        self.total_sent = 0
        self.total_dropped = 0
    
    def can_send(self):
        """
        Check if a message can be sent right now
        Returns: (bool, reason)
        """
        now = datetime.now()
        
        # Check if in backoff
        if self.backoff_until and now < self.backoff_until:
            wait_secs = (self.backoff_until - now).total_seconds()
            return False, f"in_backoff:{wait_secs:.1f}s"
        
        # Reset backoff if expired
        if self.backoff_until and now >= self.backoff_until:
            self.backoff_until = None
            self.consecutive_failures = 0
        
        # Check daily quota
        today = now.date()
        if today != self.day_start:
            # New day, reset counter
            self.day_start = today
            self.daily_count = 0
        
        if self.daily_count >= self.daily_quota:
            return False, "daily_quota_exceeded"
        
        # Check per-second rate
        cutoff = now - timedelta(seconds=1)
        while self.message_times and self.message_times[0] < cutoff:
            self.message_times.popleft()
        
        if len(self.message_times) >= self.max_per_second:
            oldest = self.message_times[0]
            wait_time = 1.0 - (now - oldest).total_seconds()
            return False, f"rate_limited:{wait_time:.2f}s"
        
        return True, "ok"
    
    async def wait_if_needed(self):
        """
        Wait until a message can be sent
        Returns: True if ready, False if cannot send (quota exceeded)
        """
        while True:
            can_send, reason = self.can_send()
            if can_send:
                return True
            
            if reason == "daily_quota_exceeded":
                return False
            
            if reason.startswith("in_backoff:"):
                wait_secs = float(reason.split(":")[1])
                await asyncio.sleep(min(wait_secs, 5))
            elif reason.startswith("rate_limited:"):
                wait_secs = float(reason.split(":")[1])
                await asyncio.sleep(max(0.1, wait_secs))
            else:
                await asyncio.sleep(0.5)
    
    def record_sent(self):
        """
        Record that a message was sent
        """
        now = datetime.now()
        self.message_times.append(now)
        
        today = now.date()
        if today != self.day_start:
            self.day_start = today
            self.daily_count = 0
        
        self.daily_count += 1
        self.total_sent += 1
        
        # Reset failure count on success
        if self.consecutive_failures > 0:
            self.consecutive_failures = 0
    
    def record_failure(self, is_rate_limit=False):
        """
        Record a failed send attempt
        """
        self.consecutive_failures += 1
        self.last_failure_time = datetime.now()
        
        if is_rate_limit or self.consecutive_failures >= 3:
            # Exponential backoff
            backoff_secs = min(2 ** self.consecutive_failures, 30)
            self.backoff_until = self.last_failure_time + timedelta(seconds=backoff_secs)
            print(f"[RATE_LIMIT] Backing off for {backoff_secs}s (failures: {self.consecutive_failures})")
    
    def record_dropped(self):
        """
        Record a message that was dropped (not sent due to limits)
        """
        self.total_dropped += 1
    
    def get_stats(self):
        """
        Get current rate limiting statistics
        """
        now = datetime.now()
        
        # Clean old messages from tracking
        cutoff = now - timedelta(seconds=1)
        while self.message_times and self.message_times[0] < cutoff:
            self.message_times.popleft()
        
        return {
            'sent_last_second': len(self.message_times),
            'sent_today': self.daily_count,
            'daily_quota': self.daily_quota,
            'quota_remaining': self.daily_quota - self.daily_count,
            'total_sent': self.total_sent,
            'total_dropped': self.total_dropped,
            'consecutive_failures': self.consecutive_failures,
            'in_backoff': self.backoff_until is not None and now < self.backoff_until,
            'backoff_remaining': max(0, (self.backoff_until - now).total_seconds()) if self.backoff_until else 0
        }
    
    def get_status_line(self):
        """
        Get a short status string for logging
        """
        stats = self.get_stats()
        return f"[RateLimit] Today: {stats['sent_today']}/{stats['daily_quota']} | Last sec: {stats['sent_last_second']}/{self.max_per_second}"

def create_rate_limiter(config):
    """
    Factory function to create RateLimiter from config
    """
    return RateLimiter(
        max_per_second=config.MAX_MSGS_PER_SECOND,
        daily_quota=config.DAILY_QUOTA
    )
