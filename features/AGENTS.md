# Funksjonsmodulen

Denne mappen inneholder botfunksjoner og handlers for Discord-kommandoer.

## Struktur

```text
features/
├── base_handler.py          # felles svar, guild-id, logging og rate limit
├── calendar_handler.py      # kalenderkommandoer
├── polls_handler.py         # avstemninger og stemmer
├── utility_handler.py       # kalkulator, krypto og URL
├── fun_handler.py           # sitater, dagens ord, horoskop og komplimenter
├── *_manager.py             # domenelogikk uten Discord-avhengighet
└── *_handler.py             # Discord-tilpasning rundt manager
```

## Viktig mønster

- Manager-filer skal kunne testes uten Discord.
- Handler-filer arver `BaseHandler`.
- Ruting skal gå via `core/intent_router.py` og `MessageMonitor`, ikke via tilfeldig parsing i nye handlers.
- Nye kalenderlignende prompts skal være konservative og dekkes av regresjonstester.

## Legge til ny funksjon

1. Lag en manager med ren domenelogikk.
2. Lag en handler hvis funksjonen trenger Discord-svar.
3. Registrer handleren i `MessageMonitor`.
4. Legg intent-regel i `IntentRouter` hvis prompten skal rutes direkte.
5. Legg tester for positivt treff og minst én falsk positiv.

## Tester

```bash
python3 -m pytest tests/test_intent_router.py -q
python3 -m pytest tests/test_message_monitor_routing.py -q
python3 -m pytest -q
```
