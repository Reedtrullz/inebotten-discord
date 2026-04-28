# cal_system/ — Calendar Engine

Unified calendar with Norwegian natural language parsing, recurring events, Google Calendar sync, and proactive reminders.

## STRUCTURE

```
cal_system/
├── calendar_manager.py           # Unified event/task CRUD
├── natural_language_parser.py    # Norwegian date/time NLP (~891 lines)
├── event_manager.py              # Legacy event logic (being merged into calendar_manager)
├── google_calendar_manager.py    # GCal OAuth + two-way sync
├── reminder_checker.py           # Background reminders + morning digest
├── norwegian_calendar.py         # Holidays, flag days, name days
└── *.py                          # Additional parsers and utilities
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Add new date patterns | `natural_language_parser.py` |
| Change calendar storage format | `calendar_manager.py` |
| Change GCal sync behavior | `google_calendar_manager.py` |
| Change reminder timing | `reminder_checker.py` |
| Change holiday data | `norwegian_calendar.py` |

## CONVENTIONS

- Date formats supported: `DD.MM.YYYY`, relative (`i morgen`, `imårra`), weekdays (`på mandag`), month names (`15. mai`)
- Recurrence: `hver uke`, `annenhver uke`, `hver måned`, `hvert år`
- All calendar items stored in `~/.hermes/discord/data/calendar.json`
- GCal events store `gcal_event_id` for two-way sync

## NOTES

- `natural_language_parser.py` is the largest file here (~891 lines). It handles Norwegian dialects, nynorsk, and flexible date patterns
- `event_manager.py` is legacy code being gradually merged into `calendar_manager.py`
- Reminder checker runs as a background task started in `SelfbotClient.on_ready()`
