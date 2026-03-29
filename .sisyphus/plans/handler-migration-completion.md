# Handler Migration Completion Plan

## Overview
Complete the Discord bot handler migration by wiring all 10 handlers and fixing test infrastructure.

## Tasks

### Task 1: Register 4 Missing Handlers
Add to `_register_handlers()` in message_monitor.py:
- aurora: AuroraHandler
- school_holidays: SchoolHolidaysHandler
- help: HelpHandler
- daily_digest: DailyDigestHandler

### Task 2: Wire 4 Handlers (hasattr pattern)
Update message_monitor.py at lines 330-420:
- aurora: use aurora_handler.handle_aurora
- school_holidays: use school_holidays_handler.handle_school_holidays
- daily_digest: use daily_digest_handler.handle_daily_digest
- help: use help_handler.handle_help

Pattern: `if hasattr(self, 'aurora_handler'): await self.aurora_handler.handle_aurora(message)`

### Task 3: Fix __init__.py Circular Import
The discord package gets shadowed by project's __init__.py. Solution: make __init__.py lazy-load or empty.

### Task 4: Verify Tests
Run: `cd tests && python3 -m pytest test_comprehensive.py -v`
Expected: 157/157 pass

### Task 5: Remove Fallback Code
After verification, remove old `_handle_*` methods from message_monitor.py:
- _handle_aurora_command
- _handle_school_holidays_command
- _handle_daily_digest
- _handle_help_command

### Task 6: Add Health Check
Add `get_handlers_status()` method to MessageMonitor that returns health of each handler.

### Task 7: Final Verification
- All tests pass
- Bot instantiates correctly
- All handlers registered

## Execution Order
1. Register handlers
2. Wire handlers
3. Fix __init__.py
4. Run tests
5. Remove fallbacks
6. Add health check
7. Final verification
