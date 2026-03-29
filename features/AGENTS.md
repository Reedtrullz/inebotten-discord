# FEATURES MODULE

**Parent:** ./AGENTS.md

## OVERVIEW
30 Python files implementing bot commands. Modular handler architecture.

## STRUCTURE
```
features/
├── _base.py           # BaseCog class (unused - selfbot limitation)
├── _loader.py        # Cog loader (unused)
├── __init__.py        # Exports all handlers
├── *_handler.py      # 10 modular handler classes
└── *_manager.py      # 20 feature managers
```

## HANDLER CLASSES (10)

| Handler | File | Purpose |
|---------|------|---------|
| FunHandler | fun_handler.py | word_of_day, quote, horoscope, compliment |
| UtilityHandler | utility_handler.py | calculator, price, shorten |
| CountdownHandler | countdown_manager.py | Event countdowns |
| PollsHandler | polls_handler.py | Create polls, voting |
| CalendarHandler | calendar_handler.py | Calendar CRUD |
| WatchlistHandler | watchlist_manager.py | Watchlist management |
| AuroraHandler | aurora_forecast.py | Nordlys forecasts |
| SchoolHolidaysHandler | school_holidays.py | Norwegian school holidays |
| HelpHandler | help_handler.py | Help command |
| DailyDigestHandler | daily_digest_manager.py | Daily summaries |

## MANAGERS (20+)

- poll_manager.py, watchlist_manager.py, birthday_manager.py
- weather_api.py, crypto_manager.py, word_of_day.py
- quote_manager.py, horoscope_manager.py, compliments_manager.py
- calculator_manager.py, url_shortener.py, countdown_manager.py
- aurora_forecast.py, school_holidays.py, daily_digest_manager.py

## ADDING NEW FEATURE

1. Create `features/your_feature_manager.py` with logic
2. Create `features/your_handler.py` with Handler class:
```python
class YourHandler:
    def __init__(self, monitor):
        self.monitor = monitor
        self.your_manager = monitor.your_manager
    
    async def handle_your_command(self, message):
        # Use self.monitor.rate_limiter.record_sent()
        # Use self.monitor.response_count += 1
```
3. Register in `message_monitor.py` `_register_handlers()`:
```python
from features.your_handler import YourHandler
self.handlers["your_feature"] = YourHandler(self)
```
4. Wire in `handle_message()` with hasattr pattern

## CONVENTIONS

- Handler classes use `self.monitor` to access all state
- Always call `rate_limiter.record_sent()` after response
- Increment `response_count` after sending
- Use `message.reply()` for guild, `channel.send()` for DM/Group
- Import managers via `monitor.manager_name`

## TESTING

Run: `python3 -m pytest tests/test_comprehensive.py -v`
