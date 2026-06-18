# tests/ — Test Suite

pytest-based test suite with async support, fixtures, and regression baselines.

## STRUCTURE

```
tests/
├── conftest.py                  # Fixtures, stubs, environment isolation
├── test_intent_router.py        # Intent routing correctness
├── test_message_monitor_routing.py  # End-to-end routing behavior
├── test_false_positives.py      # Negative-case intent tests
├── test_action_schema.py        # Structured action validation
├── test_calendar_edit.py        # Calendar CRUD and destructive-action regressions
├── test_reminder_crud.py        # Reminder CRUD and routing-order regressions
├── test_quote_crud.py           # Quote CRUD (12 tests)
├── test_watchlist_birthday_edit.py  # Watchlist + birthday edit regressions
├── test_poll_target.py          # Poll target extraction and ambiguity handling
├── test_comprehensive.py        # Broad regression suite (~2300 lines)
└── run_tests.py                 # Test runner entry point
```

## CONVENTIONS

- All new intents need positive + negative tests
- Calendar-like prompts must have regression tests
- `conftest.py` isolates `HOME` and stubs Discord client when unavailable
- Async tests use `pytest-asyncio` with `asyncio_mode = auto`
- Baseline: bruk repoets `.venv312/bin/python -m pytest -q`; ikke stol på gamle hardkodede testtall.

## COMMANDS

```bash
.venv312/bin/python -m pytest -q                              # All tests
.venv312/bin/python -m pytest tests/test_intent_router.py -q  # Routing only
.venv312/bin/python -m pytest tests/test_calendar_edit.py -q  # Calendar CRUD
```
