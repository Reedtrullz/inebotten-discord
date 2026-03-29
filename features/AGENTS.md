# FEATURES MODULE

**Parent:** ./AGENTS.md

## OVERVIEW
30 Python files implementing bot commands. Modular handler architecture with BaseHandler base class.

## STRUCTURE
```
features/
├── base_handler.py          # Base class for all handlers (NEW)
├── __init__.py              # Exports all handlers
├── *_handler.py             # 10 modular handler classes
└── *_manager.py             # 20 feature managers
```

## HANDLER CLASSES (10)

All handlers extend `BaseHandler` from `features/base_handler.py`:

| Handler | File | Purpose | BaseHandler Methods Used |
|---------|------|---------|-------------------------|
| FunHandler | fun_handler.py | word_of_day, quote, horoscope, compliment | send_response, log |
| UtilityHandler | utility_handler.py | calculator, price, shorten | send_response, check_rate_limit |
| CountdownHandler | countdown_handler.py | Event countdowns | send_response |
| PollsHandler | polls_handler.py | Create polls, voting | send_response, get_guild_id |
| CalendarHandler | calendar_handler.py | Calendar CRUD | send_response, get_guild_id, extract_number |
| WatchlistHandler | watchlist_handler.py | Watchlist management | send_response |
| AuroraHandler | aurora_handler.py | Nordlys forecasts | send_response |
| SchoolHolidaysHandler | school_holidays.py | Norwegian school holidays | send_response |
| HelpHandler | help_handler.py | Help command | send_response |
| DailyDigestHandler | daily_digest_handler.py | Daily summaries | send_response, get_guild_id |

## BASEHANDLER REFERENCE

```python
class BaseHandler:
    def __init__(self, monitor):
        self.monitor = monitor           # Access to all bot state
        self.rate_limiter = monitor.rate_limiter
        self.loc = monitor.loc           # Localization
        self.client = monitor.client     # Discord client
    
    async def send_response(self, message, content, mention_author=False):
        """Unified response - handles DM/Group/Guild automatically"""
        # Also records rate_limiter stats
    
    def get_guild_id(self, message) -> int:
        """Get guild ID (or channel ID for DMs)"""
    
    def extract_number(self, content: str) -> Optional[int]:
        """Extract first number from message (removes mentions first)"""
    
    async def check_rate_limit(self) -> Tuple[bool, Optional[str]]:
        """Check if we can send"""
    
    async def wait_if_needed(self) -> bool:
        """Wait for rate limit if needed"""
    
    def get_channel_type(self, channel) -> str:
        """Returns: DM, GROUP_DM, GUILD_TEXT, UNKNOWN"""
    
    def log(self, message: str) -> None:
        """Log with handler name prefix"""
```

## MANAGERS (20+)

Feature managers contain business logic:

- poll_manager.py, watchlist_manager.py, birthday_manager.py
- weather_api.py, crypto_manager.py, word_of_day.py
- quote_manager.py, horoscope_manager.py, compliments_manager.py
- calculator_manager.py, url_shortener.py, countdown_manager.py
- aurora_forecast.py, school_holidays.py, daily_digest_manager.py

## ADDING NEW FEATURE

### Step 1: Create Manager (if needed)
```python
# features/my_feature_manager.py
class MyFeatureManager:
    def do_something(self):
        return "result"
```

### Step 2: Create Handler
```python
# features/my_handler.py
from features.base_handler import BaseHandler

class MyHandler(BaseHandler):
    def __init__(self, monitor):
        super().__init__(monitor)
        self.my_manager = MyFeatureManager()
    
    async def handle_my_command(self, message):
        result = self.my_manager.do_something()
        await self.send_response(message, result)
```

### Step 3: Register in MessageMonitor
```python
# core/message_monitor.py in _register_handlers()
from features.my_handler import MyHandler
self.handlers["my_feature"] = MyHandler(self)
```

### Step 4: Add Routing
```python
# core/message_monitor.py in handle_message()
if "my_keyword" in content_lower:
    await self.handlers["my_feature"].handle_my_command(message)
    return
```

## CONVENTIONS

- All handlers **MUST** extend `BaseHandler`
- Use `self.send_response()` for all replies (handles rate limiting)
- Never use `print()` - use `self.log()` instead
- Access managers via initialization, not directly from monitor
- Type hints recommended for all public methods

## TESTING

```bash
python3 -m pytest tests/test_comprehensive.py -v
```
