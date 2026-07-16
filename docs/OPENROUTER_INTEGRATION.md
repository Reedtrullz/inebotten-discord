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

Handlinger fra AI blir validert lokalt og gjort om til typede kandidater. OpenRouter har ingen executor-, manager- eller lagringstilgang og kan derfor ikke skrive direkte.

**Supported action formats:**

```json
{"action":"CALENDAR_CREATE","confidence":0.96,"slots":{"title":"Møte med Ola","date":"17.07.2026","time":"14:00"},"reply":"","clarification":null}
```

Forslaget må være null eller én frittstående kompakt JSON-linje. Toppnivåfeltene er nøyaktig `action`, `confidence`, `slots`, `reply` og `clarification`; actions og slots kommer fra en lukket allowlist. Ekstra felt, duplikatnøkler, kodeblokker, prosa rundt JSON eller ukjente actions er inert/avvist.

`SAVE_EVENT`-JSON og eldre `[SAVE_EVENT: ...]`/`[SHOW_DASHBOARD]` støttes bare som `legacy compatibility` i én overgangsutgivelse. De konverteres til gjeldende skjema og får ingen snarvei rundt validering, risikoklassifisering eller bekreftelse.

**Routing context:**

Når AI kalles som fallback, injiseres routerens intent-beslutning i system prompt:

```
SYSTEMINTENT: ai_chat
Systemet har analysert meldingen og bestemt at brukeren vil: brukeren vil bare chatte
Hvis dette stemmer, fortsett med handlingen. Hvis ikke, svar naturlig.
```

Dette hjelper AI-modellen å forstå hvorfor den ble kalt og unngår å gjette feil. Et gyldig semantisk forslag går likevel tilbake til den samme lokale arbiteren som deterministiske kandidater. Destruktive handlinger og alle modellforeslåtte skriveruter går til en kanal- og brukeravgrenset bekreftelse.

## Personvern og samtalehistorikk

- Providerkontekst får bare en allowlist-projeksjon av brukerminnet: lokasjon, interesser, siste temaer og ufarlige stilpreferanser. Discord-ID og vilkårlige lagrede felt sendes ikke.
- AI-chat, eksplisitt søk og en enkel semantisk presisering kan bruke avgrenset historikk. Det siste gjør at et kort svar på modellens presisering beholder turkonteksten. Deterministiske presiseringer og lokale/private funksjonsruter utelates; autentiseringsflyter får redigert historikk.
- Hvis en AI-chat-fallback ender i en lokal semantisk handling, reklassifiseres den aktuelle turen til den endelige rutens historikkpolicy før senere providerkall.
- Kontekst tilpasses strukturelt; vilkårlig nested JSON kuttes ikke midt i et felt.

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
.venv312/bin/python -m pytest tests/test_intent_router.py -q
.venv312/bin/python -m pytest tests/test_message_monitor_routing.py -q
.venv312/bin/python -m pytest tests/test_chat_contract.py tests/test_context_integration.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
```

Disse testene bruker ikke OpenRouter-nettverket. Et live-provider-smoke med ekte nøkkel er et separat, manuelt bevis og er ikke implisitt bestått av testpakken.

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
