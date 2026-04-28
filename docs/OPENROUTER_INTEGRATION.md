# OpenRouter-integrasjon

Dette dokumentet oppsummerer hvordan OpenRouter-støtten er bygget inn i Inebotten.

## Oversikt

Inebotten støtter to AI-leverandører:

- `lm_studio`: lokal modell via lokal HTTP-bro.
- `openrouter`: skybasert API med valgfri modell.

Valget styres av `AI_PROVIDER` i `.env` og håndteres av connector-laget.

## Berørte filer

| Fil | Rolle |
|-----|------|
| `ai/openrouter_connector.py` | Klient mot OpenRouter API |
| `ai/connector_factory.py` | Velger riktig AI-connector |
| `core/config.py` | Leser OpenRouter-innstillinger |
| `.env.example` | Viser nødvendige variabler |
| `docs/OPENROUTER_SETUP.md` | Brukeroppsett |
| `mac_app/launcher.py` og `windows_app/launcher.py` | GUI-valg for leverandør og modell |

## Dataflyt

```text
Discord-melding
  -> MessageMonitor
  -> IntentRouter
  -> AI-chat fallback
  -> connector_factory
  -> OpenRouterConnector
  -> OpenRouter API
  -> renset Discord-svar
```

Handlinger fra AI blir validert lokalt før kalenderen endres. OpenRouter får derfor ikke lov til å skrive direkte til lagring uten parser-sjekk.

**Supported action formats:**

```python
# JSON-format (anbefalt)
{"action": "SAVE_EVENT", "title": "Møte med Ola", "date": "01.05.2025", "time": "14:00"}
{"action": "SHOW_DASHBOARD"}

# Eldre tag-format (bakoverkompatibelt)
[SAVE_EVENT: Møte med Ola | 01.05.2025 | 14:00]
[SHOW_DASHBOARD]
```

**Routing context:**

Når AI kalles som fallback, injiseres routerens intent-beslutning i system prompt:

```
SYSTEMINTENT: ai_chat
Systemet har analysert meldingen og bestemt at brukeren vil: brukeren vil bare chatte
Hvis dette stemmer, fortsett med handlingen. Hvis ikke, svar naturlig.
```

Dette hjelper AI-modellen å forstå hvorfor den ble kalt og unngår å gjette feil.

## Miljøvariabler

```bash
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-din-nokkel
OPENROUTER_MODEL=google/gemma-3-4b-it:free
OPENROUTER_TEMPERATURE=0.7
OPENROUTER_MAX_TOKENS=200
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

## Test

```bash
python3 -m pytest tests/test_intent_router.py -q
python3 -m pytest tests/test_message_monitor_routing.py -q
python3 -m pytest -q
```

Manuell test:

```text
@inebotten hei, kan du svare kort på norsk?
@inebotten jeg skal bare høre hva du synes om RBK i morgen
@inebotten møte med Ola i morgen kl 14
```

Forventning:

- Vanlig chat skal gå til AI.
- RBK-spørsmålet skal ikke lagres som kalender.
- Møteprompten skal bli kalenderhendelse.

## Drift

- Hold token og API-nøkler utenfor Git.
- Sett lav `OPENROUTER_MAX_TOKENS` for Discord.
- Overvåk forbruk i OpenRouter.
- Bruk LM Studio når du vil teste uten kostnad eller ekstern avhengighet.
