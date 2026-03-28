# Inebotten Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                     USER INTERFACE                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│  │   Discord    │  │  Google      │  │   LM Studio  │  │  MET.no      │                │
│  │   (Chat)     │  │  Calendar    │  │   (AI)       │  │  (Weather)   │                │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │
└─────────┼─────────────────┼─────────────────┼─────────────────┼────────────────────────┘
          │                 │                 │                 │
          │  HTTP/WebSocket │   HTTPS/OAuth   │   HTTP (local)  │    HTTPS               │
          │                 │                 │                 │                        │
┌─────────▼─────────────────▼─────────────────▼─────────────────▼────────────────────────┐
│                                    BOT LAYER                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │                        Message Monitor (message_monitor.py)                      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │   │
│  │  │   Mention   │  │   Command   │  │     AI      │  │  Calendar   │            │   │
│  │  │   Detector  │──►   Router    │──►  Fallback   │──►   Handler   │            │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘            │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                              │
│                    ┌────────────────────┼────────────────────┐                        │
│                    │                    │                    │                        │
│           ┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐              │
│           │  Natural Lang   │  │  Personality    │  │  Feature        │              │
│           │  Parser         │  │  System         │  │  Handlers       │              │
│           │                 │  │                 │  │                 │              │
│           │ calendar_parser │  │ user_memory     │  │ countdown       │              │
│           │ date_extractor  │  │ conversation    │  │ poll            │              │
│           │ recurrence      │  │ personality     │  │ watchlist       │              │
│           └─────────────────┘  └─────────────────┘  │ crypto          │              │
│                                                     │ horoscope       │              │
│                                                     │ calculator      │              │
│                                                     └─────────────────┘              │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼────────────────────────────────────────────────┐
│                                    DATA LAYER                                           │
│                                                                                         │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                    │
│   │  Calendar Store  │  │   User Memory    │  │   GCal Cache     │                    │
│   │  (JSON)          │  │   (JSON)         │  │   (OAuth)        │                    │
│   │                  │  │                  │  │                  │                    │
│   │ • Events         │  │ • Preferences    │  │ • Sync tokens    │                    │
│   │ • Reminders      │  │ • Interests      │  │ • Event IDs      │                    │
│   │ • Recurring      │  │ • Last topics    │  │                  │                    │
│   └──────────────────┘  └──────────────────┘  └──────────────────┘                    │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Component Interactions

### Message Flow

```
┌─────────┐     ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  User   │────►│   Discord   │────►│  Message Monitor │────►│  Command     │
│  Input  │     │   Gateway   │     │  (process_msg)  │     │  Detection   │
└─────────┘     └─────────────┘     └─────────────────┘     └──────┬───────┘
                                                                   │
                    ┌──────────────────────────────────────────────┼──────────────┐
                    │                                              │              │
              ┌─────▼──────┐  ┌──────────┐  ┌──────────┐    ┌─────▼──────┐  ┌──▼──────┐
              │   Intent   │  │ Natural  │  │ Calendar │    │   Other    │  │  Small  │
              │   Check    │  │ Language │  │ Command  │    │  Commands  │  │  Talk   │
              │            │  │ Parser   │  │          │    │            │  │         │
              └─────┬──────┘  └────┬─────┘  └────┬─────┘    └─────┬──────┘  └────┬────┘
                    │              │             │                │             │
                    └──────────────┴─────────────┴────────────────┘             │
                                   │                                            │
                         ┌─────────▼──────────┐                      ┌──────────▼──────────┐
                         │  Calendar Manager  │                      │  AI Response Flow   │
                         │  • Add/Edit/Delete │                      │  • Build context    │
                         │  • Complete        │                      │  • Get system prompt│
                         │  • Sync to GCal    │                      │  • Call bridge      │
                         └─────────┬──────────┘                      └──────────┬──────────┘
                                   │                                           │
                         ┌─────────▼──────────┐                      ┌──────────▼──────────┐
                         │   JSON Storage     │                      │  Hermes Bridge      │
                         │   (data/calendar.json)  │                      │  • Check LM Studio  │
                         └────────────────────┘                      │  • Generate response│
                                                                     └──────────┬──────────┘
                                                                                │
                                                                     ┌──────────▼──────────┐
                                                                     │  LM Studio (gemma)  │
                                                                     │  or Local Fallback  │
                                                                     └─────────────────────┘
```

## Data Models

### Calendar Item

```
┌─────────────────────────────────────────────────────────────┐
│                      Calendar Item                           │
├─────────────────────────────────────────────────────────────┤
│  id: UUID              │  Unique identifier                  │
│  type: str             │  "event" | "task"                   │
│  title: str            │  Display title                      │
│  description: str      │  Optional details                   │
│  date: str             │  "DD.MM.YYYY"                       │
│  time: str             │  "HH:MM" (optional)                 │
│  created_by: str       │  Discord user ID                    │
│  created_at: str       │  ISO timestamp                      │
│  completed: bool       │  Completion status                  │
│  completed_at: str     │  ISO timestamp (optional)           │
│  recurrence: str       │  null | "weekly" | "biweekly" | ... │
│  recurrence_day: str   │  "Monday" | "Tuesday" | ...         │
│  gcal_event_id: str    │  Google Calendar ID (optional)      │
│  gcal_link: str        │  Google Calendar URL (optional)     │
└─────────────────────────────────────────────────────────────┘
```

### User Memory

```
┌─────────────────────────────────────────────────────────────┐
│                      User Memory                             │
├─────────────────────────────────────────────────────────────┤
│  username: str         │  Discord display name               │
│  location: str         │  User's location                    │
│  interests: [str]      │  Extracted interests                │
│  last_topics: [str]    │  Recent conversation topics         │
│  conversation_count: int  Total interactions                 │
│  last_interaction: str │  ISO timestamp                      │
│  preferences: {        │                                      │
│    formality: str      │  "casual" | "formal"                │
│    humor_style: str    │  "friendly" | "sarcastic" | "dry"   │
│    use_dialect: bool   │  Use Norwegian dialect              │
│  }                     │                                      │
└─────────────────────────────────────────────────────────────┘
```

## Configuration Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Configuration                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐  │
│  │   Environment    │      │   Files          │      │   Runtime        │  │
│  │   Variables      │      │   (JSON/Pickle)  │      │   State          │  │
│  │                  │      │                  │      │                  │  │
│  │ HERMES_BRIDGE_   │      │ data/calendar.   │      │ Conversation     │  │
│  │   HOST/PORT      │──────│   json           │      │   threads        │  │
│  │                  │      │                  │      │                  │  │
│  │ DISCORD_TOKEN    │      │ user_memory.     │      │ Rate limiters    │  │
│  │                  │──────│   json           │      │                  │  │
│  │                  │      │                  │      │ Hermes session   │  │
│  │                  │      │ .gcal_token.     │      │                  │  │
│  │                  │──────│   pickle         │      │                  │  │
│  └──────────────────┘      └──────────────────┘      └──────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Dependencies

```
run_both.py
├── hermes_bridge_server.py
│   └── aiohttp (external)
│
└── selfbot_runner.py
    ├── message_monitor.py
    │   ├── hermes_connector.py
    │   ├── calendar_manager.py
    │   │   └── google_calendar_manager.py (optional)
    │   ├── natural_language_parser.py
    │   ├── user_memory.py
    │   ├── conversation_context.py
    │   ├── personality_config.py
    │   ├── conversational_responses.py
    │   ├── localization.py
    │   ├── weather_api.py
    │   ├── norwegian_calendar.py
    │   └── [feature managers...]
    │       ├── countdown_manager.py
    │       ├── poll_manager.py
    │       ├── watchlist_manager.py
    │       ├── crypto_manager.py
    │       ├── horoscope_manager.py
    │       ├── calculator_manager.py
    │       └── ...
    │
    ├── rate_limiter.py
    ├── response_generator.py
    └── personality.py
```

## Key Design Decisions

### 1. Unified Calendar
**Why:** Originally separate event_manager and reminder_manager caused duplication
**Solution:** Single calendar_manager handles both with type field

### 2. Natural Language Parser
**Why:** Rigid commands are user-unfriendly
**Solution:** Parse Norwegian text patterns into structured data

### 3. Bridge Architecture
**Why:** LM Studio runs on Windows, bot on WSL Linux
**Solution:** HTTP bridge enables cross-platform communication

### 4. Personality System
**Why:** AI responses were generic and robotic
**Solution:** Layer of user memory + conversation context + personality config

### 5. Graceful Degradation
**Why:** Bot should work even when AI is down
**Solution:** Local fallbacks for all AI-dependent features

## Performance Considerations

- **JSON Storage:** Good for <10k items, no database required
- **In-Memory Cache:** Conversation context expires after 30min
- **Rate Limiting:** Discord API limits respected (5/sec, 10k/day)
- **Lazy Loading:** GCal sync only when requested

## Security Notes

- Selfbot uses **user token** (against Discord ToS for production)
- GCal OAuth tokens stored locally with pickle
- No sensitive data logged (tokens redacted)
- Bridge runs on localhost only (no external exposure)
