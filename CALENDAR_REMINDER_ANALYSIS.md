# Calendar Reminder System Analysis

**Date:** 2026-04-19  
**Status:** ISSUES FOUND ⚠️

---

## Executive Summary

The calendar reminder system is partially implemented but has **critical issues** that prevent it from working as expected. The system is designed to send reminders but is missing key functionality.

---

## Current Implementation

### Components

1. **`cal_system/reminder_checker.py`** - Background task that checks for upcoming events
2. **`cal_system/reminder_manager.py`** - Manages reminders separate from calendar items
3. **`cal_system/calendar_manager.py`** - Manages calendar items
4. **`features/calendar_handler.py`** - Handles calendar commands

### How It Works

1. **Reminder Checker** runs as a background asyncio task
2. **Checks every 60 seconds** for events within 30 minutes
3. **Sends 30-minute warning** to the channel where the event was created
4. **Sends morning digest** at 09:00 Oslo time with today's events
5. **Tracks sent reminders** in `reminder_log.json` to avoid duplicates

---

## Issues Found

### ❌ CRITICAL ISSUE #1: Missing "At the Time" Reminders

**Problem:** The system only sends 30-minute warnings, but does NOT send reminders when events actually happen.

**Current Behavior:**
```python
# reminder_checker.py line 139
if now <= item_date <= thirty_min:
    # Only sends reminder if event is within 30 minutes
```

**Expected Behavior:**
- Send 30-minute warning before event
- Send reminder when event happens (at the exact time)

**Impact:** Users don't get notified when events are happening, only 30 minutes before.

---

### ❌ CRITICAL ISSUE #2: No "Just Happened" Notifications

**Problem:** The system doesn't send notifications when events have just happened.

**Current Behavior:**
- No notification when event time passes
- No "event is happening now" message

**Expected Behavior:**
- Send notification when event starts
- Send "event is happening now" message

**Impact:** Users miss events entirely if they don't see the 30-minute warning.

---

### ⚠️ ISSUE #3: Time Zone Handling

**Problem:** The reminder checker uses Europe/Oslo timezone, but calendar items don't store timezone information.

**Current Code:**
```python
# reminder_checker.py line 123
now = datetime.now(ZoneInfo("Europe/Oslo"))
```

**Issue:** If user creates an event in a different timezone, the reminder timing will be wrong.

**Impact:** Reminders may be sent at the wrong time.

---

### ⚠️ ISSUE #4: No Reminder for Events Without Time

**Problem:** Events without a specific time (date-only) get reminders at midnight (00:00).

**Current Code:**
```python
# reminder_checker.py line 209
dt = datetime.strptime(date_str, "%d.%m.%Y").replace(
    hour=0, minute=0, second=0, microsecond=0, tzinfo=oslo_tz
)
```

**Issue:** Date-only events are treated as happening at 00:00, which may not be intended.

**Impact:** Users get midnight reminders for all-day events.

---

### ⚠️ ISSUE #5: Morning Digest Timing Window Too Narrow

**Problem:** Morning digest only triggers between 09:00 and 09:10.

**Current Code:**
```python
# reminder_checker.py line 175
if not (now.hour == 9 and now.minute < 10):
    return
```

**Issue:** If the bot restarts after 09:10, no digest is sent that day.

**Impact:** Users may miss their daily digest if the bot restarts.

---

### ⚠️ ISSUE #6: No "Event Starting Now" Reminder

**Problem:** There's no separate reminder type for "event is starting now".

**Current Reminder Types:**
- Only `30min` reminder type exists

**Expected Reminder Types:**
- `30min` - 30 minutes before
- `now` - At the exact time
- `passed` - Just after the event

**Impact:** Users don't get notified when events start.

---

## What Works Correctly ✅

1. **30-minute warnings** are sent correctly
2. **Morning digest** is sent at 09:00 Oslo time
3. **Channel routing** works (reminders sent to correct channel)
4. **Duplicate prevention** works (tracks sent reminders)
5. **User mentions** work (pings event creator)
6. **Recurring events** are handled correctly
7. **Calendar items** have channel_id set correctly

---

## Required Fixes

### Fix #1: Add "At the Time" Reminders

**File:** `cal_system/reminder_checker.py`

**Add new reminder check:**
```python
async def check_event_now(self):
    """Check for events happening NOW and send notifications"""
    now = datetime.now(ZoneInfo("Europe/Oslo"))
    
    if self.calendar:
        for guild_id, items_list in self.calendar.items.items():
            for item in items_list:
                if item.get("completed"):
                    continue
                
                try:
                    item_date = self._parse_item_datetime(item)
                except (ValueError, TypeError):
                    continue
                
                if item_date is None:
                    continue
                
                # Check if event is happening NOW (within 1 minute)
                one_minute_ago = now - timedelta(minutes=1)
                one_minute_ahead = now + timedelta(minutes=1)
                
                if one_minute_ago <= item_date <= one_minute_ahead:
                    if self._has_been_sent(item["id"], "now"):
                        continue
                    await self._send_item_reminder(item, "now", "nå")
```

**Add to main loop:**
```python
async def start(self):
    """Start the reminder checker background task"""
    self.running = True
    print("[REMIND] Reminder checker started")
    while self.running:
        try:
            await self.check_upcoming_30min()
            await self.check_event_now()  # NEW
            await self.check_morning_digest()
        except Exception as e:
            print(f"[REMIND] Error in checker loop: {e}")
        
        # Check every 60 seconds
        for _ in range(60):
            if not self.running:
                break
            await asyncio.sleep(1)
```

---

### Fix #2: Add "Just Passed" Notifications

**Add new reminder check:**
```python
async def check_event_passed(self):
    """Check for events that just happened (within last 5 minutes)"""
    now = datetime.now(ZoneInfo("Europe/Oslo"))
    five_minutes_ago = now - timedelta(minutes=5)
    
    if self.calendar:
        for guild_id, items_list in self.calendar.items.items():
            for item in items_list:
                if item.get("completed"):
                    continue
                
                try:
                    item_date = self._parse_item_datetime(item)
                except (ValueError, TypeError):
                    continue
                
                if item_date is None:
                    continue
                
                # Check if event just happened (within last 5 minutes)
                if five_minutes_ago <= item_date <= now:
                    if self._has_been_sent(item["id"], "passed"):
                        continue
                    await self._send_item_reminder(item, "passed", "akkurat nå")
```

---

### Fix #3: Improve Morning Digest Timing

**Change timing window:**
```python
async def check_morning_digest(self):
    """If it's past 09:00 and we haven't sent a morning digest yet per guild, send one"""
    oslo_tz = ZoneInfo("Europe/Oslo")
    now = datetime.now(oslo_tz)
    
    # Trigger between 09:00 and 10:00 (wider window)
    if not (9 <= now.hour < 10):
        return
    
    # Rest of the logic...
```

---

### Fix #4: Handle Date-Only Events Better

**Add default time for date-only events:**
```python
def _parse_item_datetime(self, item):
    """Parse date+time from a calendar item into a Europe/Oslo datetime"""
    oslo_tz = ZoneInfo("Europe/Oslo")
    date_str = item.get("date", "")
    time_str = item.get("time") or None
    
    if not date_str:
        return None
    
    dt = datetime.strptime(date_str, "%d.%m.%Y").replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=oslo_tz
    )
    
    if time_str:
        try:
            parts = time_str.split(":")
            dt = dt.replace(hour=int(parts[0]), minute=int(parts[1]))
        except (ValueError, IndexError):
            pass
    else:
        # For date-only events, use 09:00 as default time
        dt = dt.replace(hour=9, minute=0)
    
    return dt
```

---

### Fix #5: Update Reminder Messages

**Update reminder messages to be more descriptive:**

**30-minute warning:**
```python
message = (
    f"⏰ **Påminnelse: {item['title']}**\n\n"
    f"Det er {label} til!{time_str}\n\n"
    f"Klar? 😊"
)
```

**Event happening now:**
```python
message = (
    f"🔔 **Starter nå: {item['title']}**\n\n"
    f"Det er på tide!{time_str}\n\n"
    f"Lykke til! 🎉"
)
```

**Event just passed:**
```python
message = (
    f"✅ **Akkurat ferdig: {item['title']}**\n\n"
    f"Håper det gikk bra!{time_str}\n\n"
    f"Bra jobba! 👍"
)
```

---

## Testing Recommendations

### Manual Testing

1. **Test 30-minute warning:**
   - Create an event 25 minutes from now
   - Wait 5 minutes
   - Verify reminder is sent

2. **Test "at the time" reminder:**
   - Create an event 1 minute from now
   - Wait 1 minute
   - Verify "now" reminder is sent

3. **Test "just passed" reminder:**
   - Create an event 1 minute ago
   - Verify "passed" reminder is sent

4. **Test morning digest:**
   - Set system time to 09:05
   - Restart bot
   - Verify digest is sent

5. **Test date-only events:**
   - Create an event for today without time
   - Verify reminder is sent at 09:00

6. **Test recurring events:**
   - Create a weekly event
   - Verify reminders work for each occurrence

### Automated Testing

Add tests to `tests/test_calendar_reminders.py`:

```python
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from cal_system.reminder_checker import ReminderChecker

def test_30min_reminder():
    """Test 30-minute warning is sent"""
    # Create event 25 minutes from now
    # Run checker
    # Verify reminder sent

def test_now_reminder():
    """Test 'at the time' reminder is sent"""
    # Create event 1 minute from now
    # Run checker
    # Verify 'now' reminder sent

def test_passed_reminder():
    """Test 'just passed' reminder is sent"""
    # Create event 1 minute ago
    # Run checker
    # Verify 'passed' reminder sent

def test_morning_digest():
    """Test morning digest is sent at 09:00"""
    # Set time to 09:05
    # Run checker
    # Verify digest sent

def test_duplicate_prevention():
    """Test duplicate reminders are not sent"""
    # Send reminder once
    # Run checker again
    # Verify no duplicate
```

---

## Configuration Options

### Add to `.env.example`

```bash
# Reminder Settings
REMINDER_30MIN_ENABLED=true
REMINDER_NOW_ENABLED=true
REMINDER_PASSED_ENABLED=true
MORNING_DIGEST_ENABLED=true
MORNING_DIGEST_TIME=09:00
REMINDER_TIMEZONE=Europe/Oslo
```

---

## Monitoring

### Add Statistics Tracking

**Track in reminder checker:**
```python
self.stats = {
    "30min_sent": 0,
    "now_sent": 0,
    "passed_sent": 0,
    "digest_sent": 0,
    "errors": 0,
}
```

**Display in shutdown:**
```python
print(f"[REMIND] 30min reminders: {self.stats['30min_sent']}")
print(f"[REMIND] Now reminders: {self.stats['now_sent']}")
print(f"[REMIND] Passed reminders: {self.stats['passed_sent']}")
print(f"[REMIND] Morning digests: {self.stats['digest_sent']}")
```

---

## Success Criteria

After fixes, the reminder system should:

- ✅ Send 30-minute warnings before events
- ✅ Send "at the time" reminders when events start
- ✅ Send "just passed" notifications after events
- ✅ Send morning digest at 09:00
- ✅ Handle date-only events correctly
- ✅ Prevent duplicate reminders
- ✅ Send reminders to correct channel
- ✅ Mention event creator
- ✅ Handle recurring events
- ✅ Track statistics

---

## Priority

**HIGH PRIORITY:**
1. Add "at the time" reminders (Fix #1)
2. Add "just passed" notifications (Fix #2)

**MEDIUM PRIORITY:**
3. Improve morning digest timing (Fix #3)
4. Handle date-only events better (Fix #4)

**LOW PRIORITY:**
5. Update reminder messages (Fix #5)
6. Add configuration options
7. Add statistics tracking

---

## Conclusion

The calendar reminder system is **partially functional** but missing critical features. The 30-minute warnings work correctly, but the system lacks:

1. "At the time" reminders when events start
2. "Just passed" notifications after events
3. Better handling of edge cases

**Status:** ⚠️ NEEDS FIXES

**Recommendation:** Implement fixes #1 and #2 immediately to make the reminder system work as expected.

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-19
