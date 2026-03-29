# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-29
**Commit:** 22b13fb
**Branch:** master

## OVERVIEW
Inebotten - Norwegian Discord selfbot with AI integration (LM Studio). Monitors DMs/Group DMs for @inebotten mentions, responds with AI or feature commands.

## STRUCTURE
```
.
├── run_both.py              # Main entry (Hermes Bridge + Selfbot)
├── core/                    # Bot infrastructure (message_monitor, config, auth)
├── features/                # 30+ command handlers (polls, calendar, crypto, weather)
├── ai/                      # Hermes connector, personality, responses
├── cal_system/              # Norwegian calendar, Google Calendar sync
├── memory/                  # User memory, context, localization
├── tests/                   # 157 pytest tests
└── docs/                    # DEVELOPMENT.md, API docs
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add feature | features/ | Create *_handler.py, register in message_monitor.py |
| Fix AI response | ai/hermes_connector.py | LM Studio bridge |
| Calendar fix | cal_system/calendar_manager.py | NLP parsing, Google sync |
| Tests | tests/test_comprehensive.py | 157 tests, run via pytest |
| Config | .env | Token, rate limits |

## CONVENTIONS

- **Shebang**: `#!/usr/bin/env python3` on scripts
- **Imports**: Relative within packages (`from cal_system.calendar_manager import`)
- **Naming**: snake_case functions, PascalCase classes
- **Linting**: flake8, pylint (in requirements-dev.txt)
- **Tests**: pytest, test_*.py pattern

## ANTI-PATTERNS

- NEVER hardcode tokens (use .env)
- DO NOT change pattern-matching to keyword commands (cascading if/elif is required)
- NEVER separate implementation from tests
- DON'T use English for user-facing messages (Norwegian project)

## UNIQUE STYLES

- Cascading if/elif message routing (NOT keyword commands)
- Selfbot architecture (access DMs/Group DMs - slash commands impossible)
- Norwegian-first localization
- Handler pattern with fallback (not Discord.py Cogs)

## COMMANDS

```bash
# Run bot
python3 run_both.py

# Run tests
python3 -m pytest tests/test_comprehensive.py -v

# Lint
flake8 . --max-line-length=100

# Dev deps
pip install -r requirements-dev.txt
```

## NOTES

- Root __init__.py removed (causes discord.py import shadowing)
- Handler migration complete: 10 handler classes wired
- pytest.ini: pythonpath=. required for tests
