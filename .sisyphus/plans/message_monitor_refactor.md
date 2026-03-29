# message_monitor.py Refactor Plan

## What Needs to Change

### Phase 1: Prepare Cogs to Receive Messages

The Cogs currently have the handler methods. They need to ALSO have entry point methods that message_monitor can call.

**Change Required:** Add wrapper methods to each Cog that message_monitor can invoke.

### Phase 2: Modify handle_message() to Delegate

In message_monitor.py's handle_message() method (lines 129-366), instead of:

```python
# CURRENT (inline):
await self._handle_word_of_day(message)
```

Change to:

```python
# NEW (delegate to Cog):
fun_cog = self.bot.get_cog('FunCog')
if fun_cog:
    await fun_cog.handle_word_of_day(message)
```

### Phase 3: Wire Cogs into Bot Startup

In run_both.py or selfbot_runner.py, load the Cogs after the client is created:

```python
# After client = SelfbotClient()
await client.load_extension('features.fun_cog')
await client.load_extension('features.core_cog')
# etc...
```

### Phase 4: Add Bot Reference

MessageMonitor needs access to the bot to call get_cog(). Add at initialization:

```python
self.bot = client  # Add this line
```

---

## Step-by-Step Implementation Plan

### Step 1: Add bot reference to MessageMonitor
**File:** `core/message_monitor.py`
**Line:** ~26 (in __init__)
**Change:** Add `self.bot = client`

### Step 2: Create Delegator Methods in Each Cog
**Files:** `features/{cog_name}.py`
**Change:** Each handler method stays the same, BUT wrap it with a public entry point.

Actually - NO WRAP NEEDED - just access via get_cog().

### Step 3: Modify handle_message() - Handler by Handler

Replace inline handler calls with Cog delegation:

**Pattern OLD:**
```python
if any(word in content_lower for word in ["dagens ord", "word of the day"]):
    await self._handle_word_of_day(message)
    return
```

**Pattern NEW:**
```python
if any(word in content_lower for word in ["dagens ord", "word of the day"]):
    fun_cog = self.bot.get_cog('FunCog')
    if fun_cog:
        await fun_cog.handle_word_of_day(message)
    else:
        await self._handle_word_of_day(message)  # Fallback to original
    return
```

This keeps fallback if Cogs fail to load.

### Step 4: Add Cog Loading to Startup
**File:** `core/selfbot_runner.py` or `run_both.py`
**Location:** After MessageMonitor initialization
**Change:** Add client.load_extension() calls

---

## Handlers to Migrate (21 Total)

| # | Handler | Target Cog | Priority |
|---|---------|------------|----------|
| 1 | _handle_calendar_item | CalendarCog | High |
| 2 | _handle_delete_item | CalendarCog | High |
| 3 | _handle_complete_item | CalendarCog | High |
| 4 | _handle_edit_event | CalendarCog | High |
| 5 | _handle_list_calendar | CalendarCog | High |
| 6 | _handle_poll_command | PollsCog | High |
| 7 | _handle_vote | PollsCog | High |
| 8 | _handle_countdown | CountdownCog | Medium |
| 9 | _handle_watchlist_command | WatchlistCog | Medium |
| 10 | _handle_word_of_day | FunCog | Medium |
| 11 | _handle_quote_command | FunCog | Medium |
| 12 | _handle_aurora_command | InfoCog | Medium |
| 13 | _handle_school_holidays_command | InfoCog | Medium |
| 14 | _handle_price_command | UtilityCog | Medium |
| 15 | _handle_horoscope_command | FunCog | Medium |
| 16 | _handle_compliment_command | FunCog | Medium |
| 17 | _handle_calculator_command | UtilityCog | Medium |
| 18 | _handle_shorten_command | UtilityCog | Medium |
| 19 | _handle_daily_digest | InfoCog | Medium |
| 20 | _handle_help_command | (keep in core) | Low |
| 21 | _send_response (AI) | AICog | High |

---

## Implementation Order

### Wave A: Core + AI (Most Critical)
1. Add `self.bot = client` to MessageMonitor.__init__
2. Wire CoreCog, AICog to load at startup
3. Test - bot should still work

### Wave B: Calendar + Polls (High Priority)
1. Create CalendarCog with all 5 handlers
2. Create PollsCog with 2 handlers  
3. Modify handle_message() to delegate these
4. Test - calendar and polls still work

### Wave C: Fun + Info (Medium Priority)
1. Create FunCog with 4 handlers
2. Create InfoCog with 3 handlers
3. Modify handle_message() to delegate these
4. Test - fun features still work

### Wave D: Utility + Misc
1. Create UtilityCog with 3 handlers
2. Create CountdownCog with 1 handler
3. Create WatchlistCog with 1 handler
4. Modify handle_message() to delegate these
5. Test - all utility features still work

### Wave E: Final Cleanup
1. Remove inline handler methods from message_monitor.py
2. Keep ONLY the handle_message() routing logic
3. File should shrink from 1320 to ~400 lines
4. Run full test suite - MUST PASS

---

## Testing Strategy

After each wave:
```bash
python3 tests/test_comprehensive.py
# Must show: Ran 157 tests ... OK
```

If tests fail - STOP and fix before proceeding.

---

## Success Criteria

- [ ] message_monitor.py reduced to routing logic only
- [ ] All 21 handlers in Cogs
- [ ] All 157 tests pass
- [ ] Bot responds identically to commands
- [ ] Cogs load at startup without error