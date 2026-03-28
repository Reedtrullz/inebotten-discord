# Inebotten Discord Bot - Complete Documentation

## Overview

**Inebotten** is a feature-rich Norwegian Discord selfbot that combines AI-powered conversations with practical utilities like calendar management, weather, polls, and more. It uses a bridge architecture to connect to LM Studio (running locally or remotely) for AI responses while maintaining local functionality for reliability.

## Architecture

```
┌─────────────────┐     HTTP      ┌──────────────────┐     HTTP      ┌─────────────────┐
│   Discord       │◄─────────────►│  Hermes Bridge   │◄─────────────►│  LM Studio      │
│   Selfbot       │               │  Server          │               │  (gemma-3-4b)   │
│   (Python)      │               │  (Port 3000)     │               │  (Port 1234)    │
└─────────────────┘               └──────────────────┘               └─────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         Local Components (No AI Required)                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  • Calendar Manager (events + reminders unified)                                     │
│  • Google Calendar Sync                                                             │
│  • Natural Language Parser                                                          │
│  • User Memory & Personality System                                                 │
│  • Weather API (MET.no)                                                             │
│  • Norwegian Calendar (holidays, flag days)                                         │
│  • Polls, Countdowns, Watchlists, Crypto, etc.                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Entry Points

| File | Purpose | Usage |
|------|---------|-------|
| `run_both.py` | Starts bridge + selfbot together | `python3 run_both.py` |
| `selfbot_runner.py` | Selfbot only (bridge must run) | `python3 selfbot_runner.py` |
| `hermes_bridge_server.py` | Bridge only | `python3 hermes_bridge_server.py` |

### 2. Bridge Layer (`hermes_bridge_server.py`)

**Purpose:** HTTP bridge between Discord bot and LM Studio

**Endpoints:**
- `GET /api/chat?data={payload}` - Main AI endpoint
- `GET /health` - Health check

**Fallback Behavior:**
- If LM Studio unavailable, uses local response templates
- Maintains basic functionality without AI

**System Prompt (Current):**
```
Du er 'inebotten', ein vennleg Discord-kalenderbot.
I dag er det {weekday} {today}.
Du svarar ALLTID på norsk (nynorsk eller bokmål).
ALDRI svar på engelsk.
Du hjelper til med vêr, høgtider, kalender og generelle spørsmål.
Hald svara korte (under 300 ord) og vennlege.
Du pratar med {author_name}.
```

**Note:** The bridge currently uses a hardcoded prompt. The bot sends a personalized `system_prompt` but the bridge ignores it.

### 3. Message Monitor (`message_monitor.py`)

**Purpose:** Core message handling and command routing (1,240 lines)

**Key Methods:**
- `is_mention()` - Detects @inebotten mentions
- `process_message()` - Main processing pipeline
- `_send_response()` - AI/conversational responses
- `_handle_calendar_*()` - Calendar commands

**Command Priority:**
1. Natural language calendar parser
2. Specific command matchers (countdown, poll, etc.)
3. AI fallback for general chat

### 4. Calendar System

#### Unified Calendar Manager (`calendar_manager.py`)

**Replaces:** Separate event_manager and reminder_manager

**Storage:** `~/.hermes/discord/data/calendar.json`

**Features:**
- Events + reminders in one system
- Recurring items (weekly, biweekly, monthly, yearly)
- Completion tracking
- Google Calendar sync support

**Data Model:**
```json
{
  "guild_id": [
    {
      "id": "uuid",
      "type": "event",
      "title": "Rosenborg - Brann",
      "description": "...",
      "date": "25.04.2026",
      "time": "18:00",
      "created_by": "user_id",
      "created_at": "...",
      "completed": false,
      "recurrence": "weekly",
      "recurrence_day": "Saturday",
      "gcal_event_id": "...",
      "gcal_link": "..."
    }
  ]
}
```

#### Natural Language Parser (`natural_language_parser.py`)

**Purpose:** Parse Norwegian text into calendar items

**Supported Patterns:**
```
"@inebotten møte i morgen kl 14"           → Event tomorrow 14:00
"@inebotten husk å ringe mamma på lørdag"  → Task on Saturday
"@inebotten RBK-kamp 12.04 kl 18:30"       → Specific date/time
"@inebotten lunsj med Ola hver fredag kl 12" → Recurring weekly
"@inebotten test imårra kl 13:37"          → Dialect support (imårra)
```

**Date Parsing:**
- Explicit: `25.03.2026`, `25/03/2026`
- Relative: `i dag`, `i morgen`/`imorgen`/`imårra`, `i overmorgen`
- Weekdays: `på mandag`, `neste tirsdag`

**Recurrence:**
- Keywords: `hver uke`, `hver måned`, `hvert år`, `annenhver uke`
- Day specification: `hver mandag`, `hver lørdag kl 10`

#### Google Calendar Integration (`google_calendar_manager.py`)

**Purpose:** Two-way sync with Google Calendar

**OAuth Flow:**
1. User runs `sync_calendar_to_gcal.py`
2. Opens browser to Google OAuth
3. Grants calendar access
4. Token saved to `~/.gcal_token.pickle`

**Sync Behavior:**
- Creates events in GCal when added via bot
- Stores GCal event ID for future updates
- Shows 📅 indicator for synced items
- Shows 📌 for local-only items

**Status Indicators:**
- 📅 = Synced to Google Calendar
- 📌 = Local only
- ✓ = Completed

### 5. Personality System (New)

#### User Memory (`user_memory.py`)

**Storage:** `~/.hermes/discord/data/user_memory.json`

**Tracked Data:**
- Username, location
- Interests (auto-extracted)
- Last topics discussed
- Conversation count
- Preferences (formality, humor style, dialect usage)
- Last interaction timestamp

**Features:**
- Personalized greetings ("Hei Rune! Lenge siden sist - 3 dager!")
- Days-since-last-chat tracking
- Interest-based conversation starters

#### Conversation Context (`conversation_context.py`)

**Purpose:** Maintains conversation threads and detects intent

**Intent Detection:**
```python
# Small talk (don't show dashboard)
"Hei!", "Hvordan går det?", "Hva synes du om RBK?"

# Dashboard requests (show weather/calendar)
"Hva er været?", "Vis meg kalenderen", "Hva skjer i dag?"
```

**Conversation History:**
- Stores last 10 messages per channel
- Expires after 30 minutes of inactivity
- Provides context to AI for coherent conversations

#### Personality Config (`personality_config.py`)

**Character Profile:**
- Name: Inebotten
- Personality: Laid-back, humorous Norwegian
- Traits: Uses dialect (imårra, serr), football opinions (RBK)
- Style: Helpful but not pushy, not robotic

**DO:**
- Vary greetings
- Reference past conversations
- Use humor and personality
- Show you remember the user

**DON'T:**
- Start with weather unless asked
- List calendar without being asked
- Be robotic or overly helpful
- Use "As an AI..." phrases

### 6. Other Features

| Feature | Manager File | Commands |
|---------|--------------|----------|
| **Polls** | `poll_manager.py` | `@inebotten avstemning Tittel? Alternativ 1, Alternativ 2` |
| **Countdowns** | `countdown_manager.py` | `@inebotten nedtelling til [dato]` |
| **Watchlist** | `watchlist_manager.py` | `@inebotten watchlist add [symbol]` |
| **Crypto Prices** | `crypto_manager.py` | `@inebotten pris BTC` |
| **Horoscope** | `horoscope_manager.py` | `@inebotten horoskop [sign]` |
| **Calculator** | `calculator_manager.py` | `@inebotten kalk 2+2*3` |
| **Quotes** | `quote_manager.py` | `@inebotten sitat` |
| **Word of Day** | `word_of_day.py` | `@inebotten dagens ord` |
| **Compliments** | `compliments_manager.py` | `@inebotten kompliment` |
| **URL Shortener** | `url_shortener.py` | `@inebotten shorten [url]` |
| **Daily Digest** | `daily_digest_manager.py` | Auto-scheduled morning summary |

### 7. Utility Components

| File | Purpose |
|------|---------|
| `weather_api.py` | MET.no API integration (Norwegian weather) |
| `norwegian_calendar.py` | Holidays, flag days, name days |
| `localization.py` | Norwegian translations and formatting |
| `rate_limiter.py` | Discord API rate limiting |
| `response_generator.py` | Fallback response generation |

## Data Flow Examples

### Adding a Calendar Event (Natural Language)

```
User: @inebotten møte med Ola i morgen kl 14

1. message_monitor detects mention
2. natural_language_parser.parse_event() extracts:
   - title: "møte med Ola"
   - date: tomorrow (calculated)
   - time: "14:00"
3. calendar_manager.add_item() saves to JSON
4. If GCal enabled: google_calendar_manager.sync_to_gcal()
5. Bot replies: "Lagt til: Møte med Ola - [date] kl. 14:00"
```

### Small Talk Response (AI)

```
User: @inebotten Hei! Hvordan går det?

1. message_monitor detects mention
2. conversation_context.is_small_talk() = True
3. user_memory.update_last_interaction() records topic
4. Build personalized system_prompt with user context
5. hermes_connector.generate_response() sends to bridge
6. Bridge forwards to LM Studio (gemma-3-4b)
7. Bot replies with AI-generated, personality-infused response
```

### Calendar View

```
User: @inebotten kalender

1. message_monitor._handle_calendar_list() called
2. calendar_manager.get_upcoming() fetches items
3. Format with status indicators (📅📌✓)
4. Show Google Calendar sync links if enabled
5. Bot replies with formatted list + "ferdig [nummer]" help
```

### Completing an Item

```
User: @inebotten ferdig 2

1. message_monitor._handle_complete_item() extracts number
2. calendar_manager.complete_item() marks as complete
3. If recurring: calculates next occurrence
4. If GCal synced: updates event in Google Calendar
5. Bot replies: "✓ Fullført: [title]" (+ next date if recurring)
```

## Configuration

### Environment Variables

```bash
# Bridge Configuration
HERMES_BRIDGE_HOST=127.0.0.1
HERMES_BRIDGE_PORT=3000

# Discord Token (in .env file)
DISCORD_TOKEN=your_token_here

# Google Calendar (OAuth credentials)
# Stored in ~/.gcal_credentials.json after first run
```

### File Locations

| File | Location | Purpose |
|------|----------|---------|
| Calendar Data | `~/.hermes/discord/data/calendar.json` | Events & reminders |
| User Memory | `~/.hermes/discord/data/user_memory.json` | User preferences |
| GCal Token | `~/.gcal_token.pickle` | Google OAuth token |
| GCal Credentials | `~/.gcal_credentials.json` | Google OAuth credentials |

## Usage Examples

### Calendar Commands

```
@inebotten kalender                      # List all upcoming items
@inebotten kalender 7                    # List next 7 days
@inebotten møte [tittel] [dato] [tid]    # Add event
@inebotten husk [tittel] [dato]          # Add task/reminder
@inebotten ferdig [nummer]               # Mark item as complete
@inebotten slett [nummer]                # Delete item
@inebotten sync                          # Sync to Google Calendar
```

### Natural Language (No Command Structure)

```
@inebotten lunsj med teamet på fredag kl 12
@inebotten husk å betale regninga imårra
@inebotten tannlege neste tirsdag kl 09:00
@inebotten RBK-kamp 12.04 kl 18:30 hver uke
@inebotten bursdag til mamma 15.05 hvert år
```

### Utility Commands

```
@inebotten vær                          # Current weather
@inebotten været i Oslo                 # Weather for location
@inebotten avstemning Pizza eller burger?  # Create poll
@inebotten stem 1                        # Vote on poll
@inebotten nedtelling til 17. mai       # Start countdown
@inebotten dagens ord                    # Norwegian word of day
@inebotten horoskop væren                # Daily horoscope
@inebotten pris BTC                      # Crypto price
@inebotten kalk (100 * 1.25) / 2         # Calculator
```

## Architecture Strengths

1. **Modular Design:** Each feature is self-contained
2. **Graceful Degradation:** Works without AI (local fallbacks)
3. **Unified Calendar:** Single system for events + reminders
4. **Natural Language:** No rigid command syntax
5. **Google Integration:** Syncs with real calendar
6. **Personality System:** Context-aware, personalized responses

## Known Limitations

1. **Bridge System Prompt:** The bridge ignores the bot's personalized system_prompt
2. **Selfbot Nature:** Requires user token (not bot token), against Discord ToS for production
3. **No Persistent AI Memory:** AI doesn't remember across restarts (but user_memory.json does)
4. **Single Guild Focus:** Some features work best with one Discord server

## Future Enhancements

- Fix bridge to use bot's personalized system_prompt
- Add more Norwegian dialect support
- Image generation integration
- Voice message support
- Multi-language support (Swedish, Danish)
- Web dashboard for calendar management

## Development

### Running Tests

```bash
python3 test_selfbot.py              # Basic tests
python3 test_selfbot_comprehensive.py # Full test suite
python3 -m py_compile *.py           # Syntax check all files
```

### Adding New Features

1. Create `feature_manager.py` with command parsing
2. Add to `message_monitor.py` imports and initialization
3. Add command matcher in `process_message()`
4. Add handler method `_handle_feature_command()`
5. Update this documentation

---

**Version:** 2.0 (March 2026)  
**Primary Language:** Norwegian (Bokmål/Nynorsk)  
**AI Model:** gemma-3-4b via LM Studio  
**Maintainer:** reedtrullz
