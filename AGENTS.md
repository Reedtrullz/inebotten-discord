# Inebotten Discord Bot — Project Knowledge Base

**Generated:** 2026-04-28

## OVERVIEW

Norwegian Discord selfbot with AI chat, calendar, reminders, polls, weather, and utilities. Built in Python 3.12+ with discord.py-self, supporting both LM Studio (local) and OpenRouter (cloud) AI backends.

## STRUCTURE

```
.
├── ai/              # AI connectors, bridge server, response generation
├── cal_system/      # Calendar, Norwegian NLP date parser, GCal sync
├── core/            # Config, auth, rate limit, intent router, message monitor
├── features/        # Command handlers and domain managers
├── memory/          # User memory and conversation context
├── web_console/     # Dashboard, login, log viewer (port 8080)
├── scripts/         # Entry points, deployment, tests
├── tests/           # pytest suite (324+ tests)
├── docs/            # Norwegian documentation
├── mac_app/         # macOS launcher
└── windows_app/     # Windows launcher
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add a new command | `features/` | Manager + handler, register in `MessageMonitor` |
| Change routing logic | `core/intent_router.py` | Centralized keywords + confidence thresholds |
| Change calendar behavior | `cal_system/calendar_manager.py` | Unified event/task system |
| Change AI backend | `ai/connector_factory.py` | Switch between LM Studio and OpenRouter |
| Change web dashboard | `web_console/dashboard.py` | Pure Python HTML generation |
| Change auth | `core/auth_handler.py`, `web_console/server.py` | Token + cookie session |
| Change rate limits | `core/rate_limiter.py` | Per-user + global quotas |
| Add tests | `tests/test_*.py` | pytest with async support |

## CONVENTIONS

- **Language:** Norwegian (Bokmål/Nynorsk) for user-facing text, English for code
- **Async:** All I/O is async; use `asyncio` consistently
- **Manager/Handler split:** Managers hold pure domain logic (testable without Discord); handlers adapt for Discord
- **Intent routing:** All commands route through `core/intent_router.py` before dispatch
- **Storage:** JSON files in `~/.hermes/discord/data/`
- **Logging:** `utils/logger.py` with `setup_logger()`; `install_log_capture()` captures both logging and stdout to `LogBuffer`
- **Config:** `.env` file + `core/config.py` singleton

## ANTI-PATTERNS

- **Do not** add command parsing directly in `MessageMonitor` — use `IntentRouter`
- **Do not** call `setup()` on objects that lack it (caused crashes in `ConversationContext` and `BirthdayManager`)
- **Do not** hardcode Discord tokens or API keys
- **Do not** increase rate limits above defaults (5/sec, 10k/day)
- **Do not** respond to untagged messages (mention-gate enforced in `MessageMonitor.is_mention()`)

## COMMANDS

```bash
# Run
python3 scripts/run_both.py           # Bridge + selfbot
python3 core/selfbot_runner.py        # Selfbot only
python3 ai/hermes_bridge_server.py    # Bridge only

# Test
python3 -m pytest -q                   # All tests
python3 -m pytest tests/test_console_server.py -q

# Setup
python3 setup.py                       # Interactive first-run setup
```

## NOTES

- `MessageMonitor` is the central hub (~1024 lines). It routes mentions → intents → handlers or AI
- `ConsoleServer` starts in `SelfbotClient.setup_hook()` with `monitor=None`, then gets the real monitor after `on_ready()`
- Web console auth supports both `X-API-Key` header and cookie session via `/api/login`
- The bridge runs on port 3000 (localhost); the web console on port 8080
- GCal OAuth token stored in `~/.hermes/google_token.json`
