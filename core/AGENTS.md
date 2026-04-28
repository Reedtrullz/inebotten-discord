# core/ — Bot Kernel

Central orchestration, configuration, authentication, rate limiting, and message routing.

## STRUCTURE

```
core/
├── message_monitor.py      # MessageMonitor + SelfbotClient (~1024 lines)
├── intent_router.py        # Central intent routing with confidence thresholds
├── intent_keywords.py      # Keyword constants for all intents
├── intent_thresholds.py    # Confidence cutoffs per intent
├── intent_utils.py         # Token-aware keyword matching
├── config.py               # Config singleton (.env + defaults)
├── auth_handler.py         # Discord token/email auth validation
├── rate_limiter.py         # Per-user + global rate limiting
└── selfbot_runner.py       # Entry point: initializes all components
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Add a new intent/route | `intent_router.py` + `intent_keywords.py` |
| Change mention detection | `message_monitor.py` — `is_mention()` |
| Change startup flow | `selfbot_runner.py` + `message_monitor.py` `setup_hook()` |
| Change console monitor wiring | `message_monitor.py` — `start_console()` and `on_ready()` |
| Change auth method | `auth_handler.py` |
| Change rate limits | `rate_limiter.py` |
| Change config defaults | `config.py` |

## CONVENTIONS

- `MessageMonitor` is instantiated in `SelfbotClient.on_ready()` after Discord connects
- `SelfbotClient.start_console()` creates `ConsoleServer` early (before `on_ready`) and updates `.monitor` later
- `IntentRouter.route()` returns `IntentResult(intent, confidence, payload, reason)`
- Confidence thresholds in `intent_thresholds.py` — calendar requires ≥0.94

## ANTI-PATTERNS

- **Do not** call `await self.monitor.setup()` if the monitor object lacks a `setup()` method
- **Do not** add random parsing in `MessageMonitor` — route through `IntentRouter`
- `message_monitor.py` is ~1024 lines — resist adding more; extract to handlers
