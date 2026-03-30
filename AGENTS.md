# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-29  
**Commit:** 682b960  
**Branch:** master

## OVERVIEW
Inebotten - Norwegian Discord selfbot with AI integration (LM Studio). Monitors DMs/Group DMs for @inebotten mentions, responds with AI or feature commands.

**🆕 UPDATED (March 2026):** Now optimized for Gemma 3 12B model with 82/100 Norwegian language score!

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
│   ├── hermes_connector.py  # LM Studio bridge (now with 12B support)
│   ├── personality.py       # Includes dialect handler
│   ├── system_prompt.txt    # Default prompt (4B models)
│   └── system_prompt_12b.txt # Optimized for Gemma 12B
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

## AI MODEL CONFIGURATION

### Supported Models

**🏆 Recommended: Gemma 3 12B Instruct**
- **Norsk score:** 82/100 (tested on 100 Norwegian sentences)
- **VRAM:** ~7-8GB (RTX 3080 compatible)
- **Response time:** 5-8 seconds
- **Setup:** Load in LM Studio, use `model_size="12b"`

**Alternative: Qwen 2.5 4B**
- **Norsk score:** ~70/100
- **VRAM:** ~3GB
- **Response time:** 2-3 seconds
- **Setup:** Use default `model_size="4b"`

### System Prompt Files

- `ai/system_prompt.txt` - Default (works with 4B models)
- `ai/system_prompt_12b.txt` - Optimized for Gemma 12B
  - Uses: "kjempe", "skikkelig", "supert", "altså", "vel", "jo", "da"
  - Short and explicit (531 chars)
  - Includes usage examples

### Dialect Support

The bot now handles Norwegian dialect expressions via `respond_to_dialect()` in `ai/personality.py`:
- "kjekt" → "Det var kjekt å høre! 😊"
- "tøft" → "Skikkelig tøft! 👍"
- "rått" → "Helt rått! 🎉"
- "skikkelig" → "Skikkelig bra! 👍"

### Temperature & Max Tokens

**For 12B models:**
- Temperature: 0.8 (higher creativity, stable)
- Max tokens: 200

**For 4B models:**
- Temperature: 0.7 (more conservative)
- Max tokens: 200

## TESTING

```bash
# Run all tests (157 tests)
python3 -m pytest tests/test_comprehensive.py -v

# Test Norwegian language capabilities
python3 test_100_norwegian.py

# Check test results
# All 157 tests must pass before committing!
```

## NOTES

- Root __init__.py removed (causes discord.py import shadowing)
- Handler architecture: 10 handlers extend BaseHandler
- pytest.ini: pythonpath=. required for tests
- MessageMonitor: Reduced from 1302 to 607 lines (53% smaller)
- **NEW:** Supports both 4B and 12B models with automatic prompt selection
