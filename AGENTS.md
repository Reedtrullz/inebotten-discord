# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-29  
**Commit:** 682b960  
**Branch:** master

## OVERVIEW
Inebotten - Norwegian Discord selfbot with AI integration (LM Studio). Monitors DMs/Group DMs for @inebotten mentions, responds with AI or feature commands.

## STRUCTURE
```
.
├── run_both.py              # Main entry (Hermes Bridge + Selfbot)
├── core/                    # Bot infrastructure
│   ├── message_monitor.py   # Message routing (607 lines)
│   ├── rate_limiter.py      # Rate limiting
│   ├── config.py            # Configuration
│   ├── auth_handler.py      # Token authentication
│   └── selfbot_runner.py    # Main runner
├── features/                # Command handlers
│   ├── base_handler.py      # Base class for all handlers
│   ├── *_handler.py         # 10 handler classes
│   └── *_manager.py         # Feature managers
├── ai/                      # Hermes connector, personality, responses
├── cal_system/              # Norwegian calendar, Google Calendar sync
├── memory/                  # User memory, context, localization
├── tests/                   # 157 pytest tests
└── docs/                    # Documentation
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add feature | features/ | Extend BaseHandler, register in message_monitor.py |
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

- **Handler Pattern**: All handlers extend `BaseHandler` from `features/base_handler.py`
- **Unified Response**: Use `self.send_response()` from BaseHandler for all replies
- **Selfbot architecture**: Access DMs/Group DMs (slash commands impossible)
- **Norwegian-first localization**
- **Cascading if/elif message routing** (NOT keyword commands)

## BASEHANDLER UTILITIES

All handlers inherit from `BaseHandler`:

```python
class MyHandler(BaseHandler):
    async def handle_command(self, message):
        # Unified response (handles DM/Group/Guild)
        await self.send_response(message, "Response text")
        
        # Guild ID (works in DMs too)
        guild_id = self.get_guild_id(message)
        
        # Extract number from message
        num = self.extract_number(message.content)
        
        # Rate limit check
        can_send, reason = await self.check_rate_limit()
        
        # Logging
        self.log("Message processed")
```

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
- Handler architecture: 10 handlers extend BaseHandler
- pytest.ini: pythonpath=. required for tests
- MessageMonitor: Reduced from 1302 to 607 lines (53% smaller)
