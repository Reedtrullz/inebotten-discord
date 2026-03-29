# Discord Bot Cogs Refactor Plan

## TL;DR

> **Quick Summary**: Refactor the Inebotten Discord bot from a monolithic 1,320-line `message_monitor.py` into a modular Cogs architecture using Discord.py's built-in COG system. Maintain all 21 handlers, preserve the cascading pattern-matching approach, and ensure the bot works identically after refactoring.
> 
> **Deliverables**:
> - 9 modular Cogs (core, AI, calendar, polls, fun, info, utility, countdown, watchlist)
> - BaseCog infrastructure with shared state
> - Dynamic cog loader
> - Test suite with pre/post validation per wave
> - Full backward compatibility maintained
> 
> **Estimated Effort**: XL (massive refactor)
> **Parallel Execution**: NO - sequential waves required
> **Critical Path**: Wave 1 → Wave 2 → Wave 3 → Wave 4 → Wave 5 → Wave 6 → Wave 7

---

## Context

### Original Request
User wants to refactor the Discord bot to use Cogs architecture. Key constraints:
- Keep current pattern matching (cascading if/elif) - DO NOT change to keyword commands
- No opinion on message_monitor.py - just make it work
- Run tests BEFORE and AFTER each wave
- Bot must work exactly the same after refactoring

### Research Findings
1. **Slash Commands**: IMPOSSIBLE with selfbots - confirmed via GitHub discussion
2. **Discord.py Cogs**: Perfect fit - official COG system provides modularity
3. **SQLite**: NOT in scope - user didn't request database migration
4. **Current Architecture**: 21 handler methods in 1 file needs modularization

### Reference Analysis
- **File Analyzed**: `/home/reed/.hermes/discord/core/message_monitor.py` (1,320 lines)
- **Current Handlers**: 21 total (5 calendar, 14 feature, 1 help, 1 AI fallback)
- **Dependencies**: 25+ external modules from cal_system/, features/, memory/, ai/
- **Shared State**: rate_limiter, localization, conversation context, user memory

---

## Work Objectives

### Core Objective
Refactor the monolithic message flow into modular Cogs while preserving 100% of existing functionality and behavior.

### Concrete Deliverables
- [ ] 9 new Cogs files in features/ directory
- [ ] BaseCog class with shared utilities
- [ ] Dynamic cog loader with hot-reload support
- [ ] All 21 handlers migrated to appropriate Cogs
- [ ] Test suite with pre/post validation
- [ ] Bot functions identically to before refactor

### Definition of Done
- [ ] All existing commands respond identically
- [ ] Rate limiting works exactly the same
- [ ] AI fallback preserves current behavior
- [ ] Google Calendar sync still works
- [ ] User memory persistence unchanged

### Must Have
- Zero behavioral changes from user perspective
- All 21 handlers must work
- Pattern-matching approach preserved exactly
- Test coverage for each wave

### Must NOT Have
- No new features or functionality changes
- No changes to command matching logic
- No breaking changes to external APIs (MET.no, CoinGecko, etc.)
- No slash commands (impossible with selfbots anyway)

---

## Verification Strategy

### Test Infrastructure
- **Framework**: pytest with asyncio support
- **Test Location**: /tests directory
- **Pattern**: Tests run BEFORE wave (baseline) and AFTER wave (validation)

### QA Policy
Every wave MUST include:
1. Run existing tests (baseline)
2. Execute wave implementation
3. Run tests again (validation)
4. Manual Smoke Test: Send @mention commands and verify responses

### Test Coverage Per Wave
- Wave 1: Setup only (no code changes)
- Wave 2-6: Full pre/post test runs
- Wave 7: Comprehensive validation

---

## Execution Strategy

### Wave Structure

```
Wave 1: TEST INFRASTRUCTURE SETUP
├── T1: Assess current test coverage
├── T2: Create baseline test fixtures
├── T3: Run initial tests (establish baseline)
└── T4: Document baseline results

Wave 2: BASE ARCHITECTURE
├── T1: Create BaseCog foundation class
├── T2: Create features/_loader.py with setup functions
├── T3: Create features/__init__.py exports
├── T4: Run tests (MUST PASS: all original functionality)
└── T5: Manual smoke test

Wave 3: CORE COGS (routing + AI)  
├── T1: Migrate is_mention() to CoreCog
├── T2: Migrate _send_response() to AICog
├── T3: Migrate handle_message() routing logic
├── T4: Run tests (MUST PASS: same behavior)
└── T5: Manual smoke test

Wave 4: CALENDAR + POLLS
├── T1: Create CalendarCog (5 handlers)
├── T2: Create PollsCog (2 handlers)
├── T3: Run tests (MUST PASS: calendar + polls work)
└── T4: Manual smoke test

Wave 5: FUN + INFO
├── T1: Create FunCog (4 handlers: horoscope, compliment, word, quote)
├── T2: Create InfoCog (3 handlers: aurora, school holidays, daily digest)
├── T3: Run tests (MUST PASS: fun + info features work)
└── T4: Manual smoke test

Wave 6: UTILITY + MISC
├── T1: Create UtilityCog (3 handlers: calculator, shorten, price)
├── T2: Create CountdownCog (1 handler)
├── T3: Create WatchlistCog (1 handler)
├── T4: Run tests (MUST PASS: all utility features work)
└── T5: Manual smoke test

Wave 7: FINAL INTEGRATION + CLEANUP
├── T1: Remove migrated handlers from message_monitor.py
├── T2: Wire up Cogs to load at startup
├── T3: Run FULL test suite (ALL tests must pass)
├── T4: Manual smoke test - EVERY feature
├── T5: Clean up temporary code
└── T6: Document changes made
```

### Dependency Matrix

- **W1**: — — tests only
- **W2**: W1 — all following waves
- **W3**: W1, W2 — requires BaseCog
- **W4**: W1, W2, W3 — requires CoreCog + AICog
- **W5**: W1, W2, W3 — requires CoreCog
- **W6**: W1, W2, W3 — requires CoreCog  
- **W7**: ALL WAVES — final integration

---

## TODOs

> Implementation + Test = ONE Task. NEVER separate.
> EVERY task MUST have: Recommended Agent Profile + QA Scenarios
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**

---

## Wave 1: TEST INFRASTRUCTURE SETUP

- [ ] 1. Assess existing test coverage

  **What to do**:
  - Explore /tests directory structure
  - Run existing tests: `python -m pytest tests/ -v`
  - Note which features are tested vs untested
  - Identify any test infrastructure issues

  **Must NOT do**:
  - Make no code changes

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: Simple exploration task requiring no AI logic
  - **Skills**: []
  
  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (this is wave 1 - foundation)

  **References**:
  - tests/ directory
  - pyproject.toml or setup.py for test dependencies

  **Acceptance Criteria**:
  - [ ] Tests directory structure identified
  - [ ] Runnable tests list created
  - [ ] Baseline test results documented

- [ ] 2. Create baseline test fixtures for core features

  **What to do**:
  - Create minimal test fixtures for:
    - MessageMonitor pattern matching
    - Calendar NLP parsing
    - AI response fallback
    - Rate limiting
  - Tests should validate behavior, not implementation

  **Must NOT do**:
  - Test implementation details (internal state)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Writing tests requires understanding what to verify
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - depends on T1

  **References**:
  - tests/test_selfbot.py - existing test patterns
  - core/message_monitor.py - handler methods to test
  - cal_system/natural_language_parser.py - NLP tests

  **Acceptance Criteria**:
  - [ ] Test fixtures created in tests/fixtures/
  - [ ] Tests use actual handler methods, not mocks
  - [ ] Fixtures are runnable with pytest

- [ ] 3. Run baseline tests and document results

  **What to do**:
  - Run all existing tests
  - Capture output for comparison
  - Mark which tests pass/fail before refactor
  - Document expected behavior

  **Must NOT do**:
  - Fix test failures during baseline run (document only)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Running tests is straightforward
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - depends on T2

  **QA Scenarios**:
  - Run: `python -m pytest tests/ -v --tb=short`
  - Verify: Tests execute without setup errors
  - Document: Pass/fail counts per test file

  **Acceptance Criteria**:
  - [ ] Baseline results captured
  - [ ] These results are the "before" reference

- [ ] 4. Document baseline test results

  **What to do**:
  - Create test/baseline_results.md with:
    - Pass/fail counts
    - Known failing tests
    - Expected behaviors
  - This becomes the reference for "did we break anything?"

  **Must NOT do**:
  - Make code changes

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: Documentation task
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - completes wave 1

  **Acceptance Criteria**:
  - [ ] test/baseline_results.md created
  - [ ] Includes all test outcomes
  - [ ] Clear "before refactor" snapshot

---

## Wave 2: BASE ARCHITECTURE

- [ ] 1. Create BaseCog foundation class

  **What to do**:
  - Create features/_base.py
  - BaseCog class should include:
    - Constructor accepting bot instance
    - Access to shared state (rate_limiter, localization)
    - respond() helper for sending messages to DMs/group/guild
    - check_rate_limit() helper
  - Use pattern from research:
    ```python
    class BaseCog(commands.Cog):
        def __init__(self, bot):
            self.bot = bot
            self.rate_limiter = getattr(bot, 'rate_limiter', None)
            self.loc = bot.localization if hasattr(bot, 'localization') else None
    ```

  **Must NOT do**:
  - No handler logic here - just shared utilities by the COG system

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Creating base infrastructure that others depend on
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 start

  **References**:
  - Research: Discord.py official Cogs docs
  - core/message_monitor.py lines 12-101 (init pattern)
  - core/rate_limiter.py (rate limiting to access)

  **Acceptance Criteria**:
  - [ ] features/_base.py created
  - [ ] BaseCog inherits from commands.Cog
  - [ ] Has utilty methods used by all handlers

- [ ] 2. Create features/_loader.py with setup functions

  **What to do**:
  - Create features/_loader.py
  - Include setup() functions for each Cog:
    ```python
    async def setup(bot):
        await bot.add_cog(CoreCog(bot))
    ```
  - Include load_all_cogs() for startup
  - Use dynamic loading pattern from research

  **Must NOT do**:
  - No actual cog implementations yet

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Infrastructure code
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - depends on T1

  **References**:
  - research: cog registration patterns
  - Red-DiscordBot cog loading

  **Acceptance Criteria**:
  - [ ] _loader.py created
  - [ ] Has setup() for each planned cog
  - [ ] Has load_all_cogs() function

- [ ] 3. Create features/__init__.py exports

  **What to do**:
  - Create features/__init__.py
  - Export all cog classes
  - Export loader functions
  - Allow: `from features import CoreCog, CalendarCog`

  **Must NOT do**:
  - No actual implementations in __init__

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple file creation
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - depends on T2

  **Acceptance Criteria**:
  - [ ] __init__.py created with exports
  - [ ] Import pattern works: `from features import CalendarCog`

- [ ] 4. Run tests - baseline validation

  **What to do**:
  - Run the full test suite
  - Compare to baseline from Wave 1
  - All tests that passed before MUST pass now
  
  **CRITICAL**: This verifies we haven't broken anything by adding infrastructure

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Running tests is straightforward
  - **Skills**: []

  **QA Scenarios**:
  - Run: `python -m pytest tests/ -v`
  - Verify: Same pass/fail counts as Wave 1 T3
  - If NEW failures: INVESTIGATE AND FIX before proceeding

  **Acceptance Criteria**:
  - [ ] Test counts match or exceed baseline
  - [ ] No regressions introduced

- [ ] 5. Manual smoke test

  **What to do**:
  - Start the bot (or use test mode)
  - Send @inebotten "hjelp"
  - Verify response comes back
  - Test a couple other basic commands

  **Must NOT do**:
  - Full test suite - just spot check

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: Manual verification
  - **Skills**: []

  **QA Scenarios**:
  - Run bot, send test messages
  - Verify: Responses work

  **Acceptance Criteria**:
  - [ ] Bot still responds to mentions
  - [ ] Basic functionality preserved

---

## Wave 3: CORE COGS (routing + AI)

- [ ] 1. Migrate is_mention() to CoreCog

  **What to do**:
  - Create features/core_cog.py
  - Include is_mention() method from message_monitor.py lines 107-127
  - Include _get_channel_type() helper
  - Include instance state similar to MessageMonitor

  **Must NOT do**:
  - Movement of is_mention OLD code
  - This is THE SAME logic, just in a different file

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Core routing logic - critical to get right
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Wave 3 START**

  **References**:
  - core/message_monitor.py lines 107-127 (is_mention)
  - core/message_monitor.py lines 1,198-1,209 (_get_channel_type)

  **Acceptance Criteria**:
  - [ ] CoreCog created in features/core_cog.py
  - [ ] is_mention() returns same results as original

- [ ] 2. Migrate _send_response() to AICog

  **What to do**:
  - Create features/ai_cog.py
  - Migrate _send_response() from message_monitor.py lines 1,041-1,196
  - Preserve:
    - Dashboard vs AI response decision
    - Hermes connector calls
    - Conversation history management
    - User memory integration

  **Must NOT do**:
  - Change any response logic

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Complex integration - AI + memory + weather
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - depends on T1

  **References**:
  - core/message_monitor.py lines 1,041-1,196 (_send_response)
  - ai/hermes_connector.py (HermesConnector usage)
  - memory/user_memory.py (user memory)
  - ai/conversational_responses.py (dashboard generation)

  **Acceptance Criteria**:
  - [ ] AICog created in features/ai_cog.py
  - [ ] AI fallback behaves identically
  - [ ] Dashboard generation unchanged

- [ ] 3. Migrate handle_message() routing logic

  **What to do**:
  - Keep handle_message() in message_monitor.py BUT delegate to Cogs
  - New flow: handle_message() → determine handler → call appropriate Cog
  - This maintains backward compatibility during transition

  **Must NOT do**:
  - Changing the cascading if/elif pattern

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Message flow coordination
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential - depends on T1 + T2

  **References**:
  - core/message_monitor.py lines 129-366 (handle_message)
  - Designed to preserve pattern matching exactly

  **Acceptance Criteria**:
  - [ ] handle_message() uses Cogs for actual handling
  - [ ] Routing logic identical to before

- [ ] 4. Run tests - core validation

  **What to do**:
  - Run full test suite
  - Compare to Wave 1 baseline
  - All tests MUST PASS
  
  **CRITICAL**: This validates core routing + AI work

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Running tests
  - **Skills**: []

  **QA Scenarios**:
  - Run: `python -m pytest tests/ -v`
  - Verify: Pass rate maintained

  **Acceptance Criteria**:
  - [ ] All baseline tests pass
  - [ ] No regressions

- [ ] 5. Manual smoke test

  **What to do**:
  - Test @mention triggers AI response
  - Test "hjelp" command
  - Test a couple feature commands

  **Must NOT do**:
  - Only spot check

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: Manual verification
  - **Skills**: []

  **Acceptance Criteria**:
  - [ ] AI fallback works
  - [ ] Help works

---

## Wave 4: CALENDAR + POLLS

- [ ] 1. Create CalendarCog (5 handlers)

  **What to do**:
  - Create features/calendar_cog.py
  - Migrate handlers:
    - _handle_calendar_item (NLP parsing → create event)
    - _handle_delete_item
    - _handle_complete_item
    - _handle_edit_event
    - _handle_list_calendar
  - Uses CalendarManager, NaturalLanguageParser

  **Reference**: message_monitor.py lines 368-443, 445-488, 490-542, 544-582, 999-1,023

  **Acceptance Criteria**:
  - [ ] CalendarCog created
  - [ ] All 5 handlers behave identically
  - [ ] Calendar operations (create, delete, complete, list) work

- [ ] 2. Create PollsCog (2 handlers)

  **What to do**:
  - Create features/polls_cog.py
  - Migrate handlers:
    - _handle_poll_command (create poll)
    - _handle_vote (vote on poll)
  - Uses PollManager

  **Reference**: message_monitor.py lines 672-697, 699-736

  **Acceptance Criteria**:
  - [ ] PollsCog created
  - [ ] Create poll works
  - [ ] Voting works

- [ ] 3. Run tests - calendar + polls validation

  **What to do**:
  - Run test suite
  - Compare to Wave 1 baseline
  - Calendar tests + poll tests MUST pass

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Running tests
  - **Skills**: []

  **QA Scenarios**:
  - Run: `python -m pytest tests/ -v -k "calendar or poll"`
  - Verify: Pass

  **Acceptance Criteria**:
  - [ ] All calendar tests pass
  - [ ] All poll tests pass

- [ ] 4. Manual smoke test

  **What to do**:
  - Test: @inebotten møte i morgen kl 14 Testing
  - Test: @inebotten kalender
  - Test: @inebotten avstemning Yes or No?

  **Must NOT do**:
  - These exact commands should produce same results

  **Acceptance Criteria**:
  - [ ] Calendar creation works
  - [ ] Calendar listing works
  - [ ] Poll creation works

---

## Wave 5: FUN + INFO

- [ ] 1. Create FunCog (4 handlers)

  **What to do**:
  - Create features/fun_cog.py
  - Migrate handlers:
    - _handle_compliment_command
    - _handle_horoscope_command
    - _handle_word_of_day
    - _handle_quote_command (save/retrieve)
  - Uses ComplimentsManager, HoroscopeManager, WordOfTheDay, QuoteManager

  **Reference**: message_monitor.py lines 844-870, 872-890, 770-787, 789-822

  **Acceptance Criteria**:
  - [ ] FunCog created
  - [ ] All 4 handlers work identically

- [ ] 2. Create InfoCog (3 handlers)

  **What to do**:
  - Create features/info_cog.py
  - Migrate handlers:
    - _handle_aurora_command (nordlys)
    - _handle_school_holidays_command
    - _handle_daily_digest
  - Uses AuroraForecast, school_holidays (dynamic imports), DailyDigestManager

  **Reference**: message_monitor.py lines 584-614, 616-652, 932-950

  **Acceptance Criteria**:
  - [ ] InfoCog created
  - [ ] All 3 handlers work identically

- [ ] 3. Run tests - fun + info validation

  **What to do**:
  - Run tests
  - All fun + info features MUST pass

  **Acceptance Criteria**:
  - [ ] All related tests pass

- [ ] 4. Manual smoke test

  **What to do**:
  - Test: @inebotten kompliment @someuser
  - Test: @inebotten horoskop Væren
  - Test: @inebotten nordlys

  **Acceptance Criteria**:
  - [ ] All respond correctly

---

## Wave 6: UTILITY + MISC

- [ ] 1. Create UtilityCog (3 handlers)

  **What to do**:
  - Create features/utility_cog.py
  - Migrate handlers:
    - _handle_calculator_command (math + conversions)
    - _handle_shorten_command (URL shortening)
    - _handle_price_command (crypto/stock prices)
  - Uses CalculatorManager, URLShortener, CryptoManager

  **Reference**: message_monitor.py lines 892-910, 912-930, 824-842

  **Acceptance Criteria**:
  - [ ] UtilityCog created
  - [ ] Calculator, URL shortener, prices work

- [ ] 2. Create CountdownCog (1 handler)

  **What to do**:
  - Create features/countdown_cog.py
  - Migrate: _handle_countdown
  - Uses CountdownManager

  **Reference**: message_monitor.py lines 654-670

  **Acceptance Criteria**:
  - [ ] CountdownCog created
  - [ ] Countdowns work

- [ ] 3. Create WatchlistCog (1 handler)

  **What to do**:
  - Create features/watchlist_cog.py
  - Migrate: _handle_watchlist_command
  - Uses WatchlistManager

  **Reference**: message_monitor.py lines 738-768

  **Acceptance Criteria**:
  - [ ] WatchlistCog created
  - [ ] Watchlist works

- [ ] 4. Run tests - utility validation

  **What to do**:
  - Run tests for utility features
  - All MUST pass

  **Acceptance Criteria**:
  - [ ] Tests pass

- [ ] 5. Manual smoke test

  **What to do**:
  - Test: @inebotten 100 USD til NOK
  - Test: @inebotten shorten https://example.com
  - Test: @inebotten bitcoin pris
  - Test: @inebotten nedtelling til 17. mai

  **Acceptance Criteria**:
  - [ ] All utility features work

---

## Wave 7: FINAL INTEGRATION + CLEANUP

- [ ] 1. Remove migrated handlers from message_monitor.py

  **What to do**:
  - After all Cogs created, remove handler code from message_monitor.py
  - Keep ONLY the delegation logic (handle_message routes to Cogs)
  - File should now be MUCH smaller

  **Must NOT do**:
  - Removing the routing/delegation - that's still needed
  - Removing anything that isn't migrated to Cogs

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Final integration cleanup
  - **Skills**: []

  **References**:
  - Should have 21 handlers across 9 Cogs now

  **Acceptance Criteria**:
  - [ ] message_monitor.py reduced in size
  - [ ] All functionality moved to Cogs

- [ ] 2. Wire up Cogs to load at startup

  **What to do**:
  - Modify core/selfbot_runner.py to load Cogs on startup
  - Use the loader functions created in Wave 2
  - Verify: All Cogs load without errors

  **Reference**: run_both.py, selfbot_runner.py

  **Acceptance Criteria**:
  - [ ] Bot loads all Cogs on startup
  - [ ] No import errors

- [ ] 3. Run FULL test suite - COMPREHENSIVE validation

  **What to do**:
  - Run ALL tests
  - Every test that passed in baseline MUST pass
  - Full test suite results

  **CRITICAL**: This is the final validation

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Running tests
  - **Skills**: []

  **QA Scenarios**:
  - Run: `python -m pytest tests/ -v --tb=short`
  - Verify: 100% of baseline tests pass

  **Acceptance Criteria**:
  - [ ] All tests pass
  - [ ] No regressions

- [ ] 4. Manual smoke test - EVERY feature

  **What to do**:
  - Test EACH of the 21 handlers manually
  - Create test scenarios:
    - Calendar: create, list, delete, complete
    - Polls: create, vote
    - Fun: compliment, horoscope, word, quote
    - Info: aurora, school holidays, daily digest
    - Utility: calculator, shorten, price
    - Countdown: countdown queries
    - Watchlist: watchlist queries
    - AI: fallback response
    - Help: help command

  **Must NOT do**:
  - Skip any feature

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Comprehensive verification
  - **Skills**: []

  **QA Scenarios**:
  - Run the bot
  - Send test messages for EVERY feature
  - Verify responses match expected behavior

  **Acceptance Criteria**:
  - [ ] 21/21 features tested manually
  - [ ] 21/21 work correctly

- [ ] 5. Clean up temporary code

  **What to do**:
  - Remove any debug print statements added during dev
  - Clean up any temporary test files
  - Ensure code is production-ready

  **Acceptance Criteria**:
  - [ ] No debug output in normal operation
  - [ ] Clean codebase

- [ ] 6. Document changes made

  **What to do**:
  - Create docs/COG_REFACTOR.md explaining:
    - What changed
    - New file structure
    - How to add new features
    - Migration guide for future changes

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: Documentation
  - **Skills**: []

  **Acceptance Criteria**:
  - [ ] docs/COG_REFACTOR.md created
  - [ ] Clear explanation of new architecture

---

## Final Verification Wave

- [ ] F1. **All Tests Pass** — `quick`
  Run full test suite, verify 100% pass rate
  
- [ ] F2. **All 21 Handlers Work** — `unspecified-high`
  Manual verification of every handler
  
- [ ] F3. **Pattern Matching Preserved** — `quick`
  Verify the cascading if/elif approach still works exactly
  
- [ ] F4. **Zero Behavioral Changes** — `quick`
  Bot responds identically to before refactor

---

## Commit Strategy

- **Wave 1**: `test(infra): add test infrastructure baseline`
- **Wave 2**: `feat(base): add BaseCog and loader infrastructure`
- **Wave 3**: `feat(core): migrate core + ai to cogs`
- **Wave 4**: `feat(features): add calendar + polls cogs`
- **Wave 5**: `feat(features): add fun + info cogs`
- **Wave 6**: `feat(features): add utility + misc cogs`
- **Wave 7**: `refactor(integration): final cleanup and wiring`

---

## Success Criteria

### Verification Commands
```bash
python -m pytest tests/ -v --tb=short
# Expected: All tests pass

# Manual tests:
@inebotten hjelp
@inebotten kalender
@inebottennordlys
@inebotten bitcoin pris
# ... (all 21 features)
```

### Final Checklist
- [ ] All 9 Cogs created and functional
- [ ] All 21 handlers migrated to Cogs
- [ ] Pattern matching preserved exactly
- [ ] All tests pass
- [ ] Manual verification of every feature
- [ ] message_monitor.py simplified (still handles routing)
- [ ] Docs updated