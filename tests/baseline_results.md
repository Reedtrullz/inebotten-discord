# Baseline for tester

Sist kjente lokale baseline:

```text
228 passed, 1 skipped
```

## Miljø

- Python 3.12 eller nyere.
- `discord.py-self` eller teststubb fra `tests/conftest.py`.
- `pytest` og `pytest-asyncio`.

## Kjente avvik

- Enkelte eldre integrasjonstester krever Discord-token eller ekstern LM Studio. De skal ikke blokkere vanlig enhetstestkjøring.
- Den avanserte dialekttesten kan hoppes over når lokal LM Studio ikke er tilgjengelig.

## Kommandoer

```bash
python3 -m pytest -q
python3 -m pytest tests/test_intent_router.py -q
python3 -m pytest tests/test_message_monitor_routing.py -q
```
