# Inebotten - Systemarkitektur

> Dypdykk i systemets arkitektur, komponenter og dataflyt

---

## 📋 Innholdsfortegnelse

1. [Systemoversikt](#systemoversikt)
2. [Lagsarkitektur](#lagsarkitektur)
3. [Komponentinteraksjoner](#komponentinteraksjoner)
4. [Datamodeller](#datamodeller)
5. [Konfigurasjonsflyt](#konfigurasjonsflyt)
6. [Modulavhengigheter](#modulavhengigheter)
7. [Designbeslutninger](#designbeslutninger)
8. [Ytelseshensyn](#ytelseshensyn)
9. [Sikkerhetsnotater](#sikkerhetsnotater)

---

## Systemoversikt

Inebotten er bygget med en **lagdelt arkitektur** som skiller bekymringer og muliggjør:

- **Uavhengig utvikling** av funksjoner
- **Robust fallback** når eksterne tjenester feiler
- **Enkel testing** av isolerte komponenter
- **Skalerbarhet** for nye funksjoner

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   BRUKERGRENSESNITT                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│  │   Discord    │  │  Google      │  │   LM Studio  │  │  MET.no      │                │
│  │   (Chat)     │  │  Calendar    │  │   (AI)       │  │  (Weather)   │                │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │
└─────────┼─────────────────┼─────────────────┼─────────────────┼────────────────────────┘
          │                 │                 │                 │
          │  HTTP/WebSocket │   HTTPS/OAuth   │   HTTP (local)  │    HTTPS               │
          │                 │                 │                 │                        │
┌─────────▼─────────────────▼─────────────────▼─────────────────▼────────────────────────┐
│                                    BOT LAG                                            │
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
```

### Modulær handler-arkitektur

Boten bruker et modulært handler-mønster basert på **BaseHandler**-klassen:

```
Handler-arkitektur
├── BaseHandler (features/base_handler.py)
│   ├── send_response()     # enhetlige svar i DM, gruppe-DM og server
│   ├── get_guild_id()      # trygg guild-id også uten server
│   ├── extract_number()    # henter tall fra meldinger
│   ├── check_rate_limit()  # rate limiting
│   └── log()               # strukturert logging
│
└── Feature-handlere (alle arver BaseHandler)
    ├── FunHandler          # word_of_day, quote, horoscope, compliment
    ├── UtilityHandler      # calculator, price, shorten
    ├── CountdownHandler    # nedtellinger
    ├── PollsHandler        # avstemninger og stemmer
    ├── CalendarHandler     # kalender-CRUD
    ├── WatchlistHandler    # watchlist
    ├── AuroraHandler       # nordlysvarsel
    ├── SchoolHolidaysHandler  # norske skoleferier
    ├── HelpHandler         # hjelp
    └── DailyDigestHandler  # daglig oppsummering
```

**Fordeler:**
- **Gjenbruk:** Alle handlere deler verktøy via BaseHandler
- **Lik oppførsel:** Rate limiting og feilhåndtering ligger ett sted
- **Enklere testing:** BaseHandler kan mockes i isolerte handler-tester
- **Lik kontrakt:** Handlere følger samme grensesnitt

**Registrering:**
Handlere registreres i `MessageMonitor._register_handlers()` og brukes via `self.handlers`.

---

## Lagsarkitektur

### 1. Brukergrensesnitt-Lag

Dette laget håndterer all kommunikasjon med eksterne systemer.

| Komponent | Protokoll | Beskrivelse |
|-----------|-----------|-------------|
| Discord Gateway | WebSocket | Sanntids meldingsmottak |
| Google Calendar API | HTTPS + OAuth | To-veis kalendersynkronisering |
| LM Studio | HTTP (localhost) | AI-modell (gemma-3-4b) |
| MET.no API | HTTPS | Værdata (gratis, norsk) |
| Web Console | HTTP | Dashbord med status, logger og autentisering |

### 2. Bot-Lag

Kjernen av applikasjonen - all forretningslogikk.

#### 2.1 Message Monitor

**Rolle:** Sentral ruting og orkestrering

```python
class MessageMonitor:
    """
    Hovedansvar:
    - Detektere @mentions
    - Rute kommandoer til riktig handler
    - Koordinere mellom AI og lokale funksjoner
    - Håndtere rate limiting
    """
```

#### 2.2 Intent Router

**Rolle:** Én sentral beslutning per prompt før meldingen sendes til handler eller AI.

`core/intent_router.py` returnerer `IntentResult(intent, confidence, payload, reason)`. Routeren importerer nå keywords fra `core/intent_keywords.py` og bruker token-aware utilities fra `core/intent_utils.py`. Dette erstatter spredt keyword-ruting i `MessageMonitor` og gjør prioritetene lettere å teste.

**Intent-systemarkitektur:**

```
Intent-system
├── core/intent_keywords.py     # Sentraliserte keyword-constants
│   ├── HELP_KEYWORDS
│   ├── CALENDAR_KEYWORDS
│   ├── STATUS_KEYWORDS
│   └── ... (13 eksporterte tupler)
│
├── core/intent_thresholds.py   # Confidence-grenser per intent
│   └── CONFIDENCE_THRESHOLDS
│       ├── CALENDAR_ITEM: 0.94
│       ├── SEARCH: 0.80
│       ├── PRICE: 0.85
│       ├── HOROSCOPE: 0.85
│       └── COMPLIMENT: 0.80
│
├── core/intent_utils.py        # Token-aware matching
│   ├── has_keyword()           # Regex \b for hele ord
│   ├── has_any_keyword()
│   ├── has_all_keywords()
│   └── extract_keywords()
│
├── core/intent_router.py       # Rutinglogikk
│   └── route() → IntentResult
│
└── core/message_monitor.py     # Dispatch med confidence-sjekk
    └── _handle_intent()
```

**Standard prioritet:**

```
1. Eksplisitt hjelp, status, profil og kalender-CRUD
2. Aktiv avstemning og stemmegivning
3. Nedtelling, watchlist, sitat/moro og nytteverktøy
4. Konservativ kalender-/oppgaveparser
5. Søk eller dashboard når prompten ber om ekstern kontekst
6. AI-chat som fallback
```

**Confidence-tresholds:**

`message_monitor.py` sjekker `route.confidence` mot `CONFIDENCE_THRESHOLDS` før dispatch. Hvis confidence er for lav, faller boten tilbake til AI-chat i stedet for å utføre en usikker handling. Kalender-NLP krever tydelig kommandohensikt pluss dato, tid eller gjentakelsessignal. Bare "jeg skal", "jeg vil" eller "jeg bør" er ikke nok alene.

**Token-aware matching:**

`core/intent_utils.py` bruker regex word boundaries (`\b`) slik at "tale" ikke matcher inni "avtale". Dette eliminerer falske positive fra delstreng-treff.

**Structured Actions:**

`ai/action_schema.py` definerer dataclasses for AI-genererte handlinger:
- `SaveEventAction` — lagre kalenderhendelse
- `ShowDashboardAction` — vise dashboard
- `NoAction` — ingen handling

AI kan returnere handlinger som JSON (`{"action": "SAVE_EVENT", ...}`) eller eldre tag-format (`[SAVE_EVENT: ...]`). Begge parses og valideres gjennom `nlp_parser.parse_event()` før kalenderen endres.

#### 2.3 Natural Language Parser

**Rolle:** Transformere norsk tekst til strukturerte data

```
Input:  "møte med Ola i morgen kl 14"
Output: {
    "title": "møte med Ola",
    "date": "2026-03-29",
    "time": "14:00",
    "type": "event"
}
```

**Parsing Pipeline:**

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Rå tekst   │───▶│   Tokenize   │───▶│   Pattern    │───▶│   Build      │
│              │    │              │    │   Match      │    │   Object     │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

#### 2.3 Personality System

**Komponenter:**

```
Personality System
├── User Memory (JSON)
│   ├── Interesser (ekstrahert fra samtaler)
│   ├── Preferanser (formalitet, humor)
│   └── Historikk (siste emner, antall samtaler)
│
├── Conversation Context (In-memory)
│   ├── Siste 10 meldinger per kanal
│   ├── Intent-deteksjon (small talk vs handling)
│   └── 30-minutters utløp
│
└── Personality Config (Static)
    ├── Karaktertrekk (avslappet, humoristisk)
    ├── Dialett-bruk (imårra, serr)
    └── Interesse-områder (RBK, norsk kultur)
```

### 3. Data-Lag

All persistent lagring.

| Lagring | Format | Formål |
|---------|--------|--------|
| Kalender | JSON | Events, påminnelser, gjentagelser |
| Brukerminne | JSON | Brukerprofiler, preferanser |
| GCal Token | Pickle | OAuth2 tokens (kryptert) |
| Konfigurasjon | .env | Miljøvariabler |

---

## Komponentinteraksjoner

### Meldingsflyt - Komplett

```
┌─────────┐     ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Bruker │────▶│   Discord   │────▶│  Message Monitor │────▶│  Kommando-   │
│  Input  │     │   Gateway   │     │  (process_msg)  │     │  Deteksjon   │
└─────────┘     └─────────────┘     └─────────────────┘     └──────┬───────┘
                                                                   │
                    ┌────────────────────────────────────────────────┼──────────────┐
                    │                                                │              │
              ┌─────▼──────┐  ┌──────────┐  ┌──────────┐      ┌─────▼──────┐  ┌──▼──────┐
              │   Intent   │  │ Natural  │  │ Kalender │      │   Andre    │  │  Small  │
              │   Sjekk    │  │ Språk    │  │ Kommando │      │  Kommando  │  │  Talk   │
              │            │  │ Parser   │  │          │      │            │  │         │
              └─────┬──────┘  └────┬─────┘  └────┬─────┘      └─────┬──────┘  └────┬────┘
                    │              │             │                  │            │
                    └──────────────┴─────────────┴──────────────────┘            │
                                    │                                           │
                          ┌─────────▼──────────┐                      ┌──────────▼──────────┐
                          │  Calendar Manager  │                      │  AI Response Flow   │
                          │  • Legg til/slett  │                      │  • Bygg kontekst    │
                          │  • Fullfør         │                      │  • Hent system      │
                          │  • Sync til GCal   │                      │     prompt          │
                          └─────────┬──────────┘                      └──────────┬──────────┘
                                    │                                           │
                          ┌─────────▼──────────┐                      ┌──────────▼──────────┐
                          │   JSON Lagring     │                      │  Hermes Bridge      │
                          │  (data/calendar.   │                      │  • Sjekk LM Studio  │
                          │       json)        │                      │  • Generer respons  │
                          └────────────────────┘                      └──────────┬──────────┘
                                                                                 │
                                                                      ┌──────────▼──────────┐
                                                                      │  LM Studio (gemma)  │
                                                                      │  eller lokal fallback│
                                                                      └─────────────────────┘
```

### AI Response Flow - Detaljert

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AI Response Flow                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Mottatt mention                                                         │
│     │                                                                       │
│     ▼                                                                       │
│  2. Sjekk conversation_context.is_small_talk()                              │
│     │                                                                       │
│     ├─ JA: Bygg personlig prompt med user_memory                            │
│     │                                                                       │
│     └─ NEI: Bygg dashboard-kontekst (vær, kalender)                         │
│     │                                                                       │
│     ▼                                                                       │
│  3. hermes_connector.generate_response()                                    │
│     │                                                                       │
│     ├─ Bygg payload: {system_prompt, user_message, conversation_history}    │
│     │                                                                       │
│     ├─ POST til bridge: /api/chat                                           │
│     │                                                                       │
│     └─ Motta AI-respons eller fallback                                      │
│     │                                                                       │
│     ▼                                                                       │
│  4. Send til Discord                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Google Calendar Sync Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Google Calendar Sync Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Initial Auth (Engang)                                                      │
│  ═══════════════════════                                                    │
│  1. Bruker kjører sync_calendar_to_gcal.py                                  │
│     │                                                                       │
│     ├─ Åpner browser for Google OAuth2                                      │
│     │                                                                       │
│     ├─ Bruker godkjenner tilgang                                            │
│     │                                                                       │
│     └─ Token lagres: ~/.gcal_token.pickle                                   │
│                                                                             │
│  Sync Ved Ny Event                                                          │
│  ═══════════════════                                                        │
│  1. Bruker: "@inebotten møte i morgen kl 14"                                │
│     │                                                                       │
│     ├─ Event lagres lokalt                                                  │
│     │                                                                       │
│     ├─ GCal sync trigges (hvis autentisert)                                 │
│     │                                                                       │
│     ├─ POST til Google Calendar API                                         │
│     │                                                                       │
│     ├─ Motta gcal_event_id                                                  │
│     │                                                                       │
│     └─ Lagre gcal_event_id i local event                                    │
│     │                                                                       │
│     ├─ Vis 📅 i kalenderliste                                               │
│                                                                             │
│  Fullføring Sync                                                            │
│  ════════════════                                                           │
│  1. Bruker: "@inebotten ferdig 2"                                           │
│     │                                                                       │
│     ├─ Hvis recurring: beregn neste dato                                    │
│     │                                                                       │
│     ├─ Hvis gcal_event_id: oppdater i GCal                                  │
│     │                                                                       │
│     └─ Vis ✓ og eventuell neste dato                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Datamodeller

### Kalender-Element

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Calendar Item                                      │
├───────────────────────────────┬─────────────────────────────────────────────┤
│  Felt                         │  Beskrivelse                                │
├───────────────────────────────┼─────────────────────────────────────────────┤
│  id: UUID                     │  Unik identifikator                         │
│  type: str                    │  "event" | "task"                           │
│  title: str                   │  Visningstittel                             │
│  description: str             │  Valgfrie detaljer                          │
│  date: str                    │  "DD.MM.YYYY"                               │
│  time: str                    │  "HH:MM" (valgfri)                          │
│  created_by: str              │  Discord bruker-ID                          │
│  created_at: str              │  ISO tidsstempel                            │
│  completed: bool              │  Fullføringsstatus                          │
│  completed_at: str            │  ISO tidsstempel (valgfri)                  │
│  recurrence: str              │  null | "weekly" | "biweekly" | ...         │
│  recurrence_day: str          │  "Monday" | "Tuesday" | ...                 │
│  gcal_event_id: str           │  Google Calendar ID (valgfri)               │
│  gcal_link: str               │  Google Calendar URL (valgfri)              │
└───────────────────────────────┴─────────────────────────────────────────────┘
```

### Brukerminne

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            User Memory                                       │
├───────────────────────────────┬─────────────────────────────────────────────┤
│  Felt                         │  Beskrivelse                                │
├───────────────────────────────┼─────────────────────────────────────────────┤
│  username: str                │  Discord visningsnavn                       │
│  location: str                │  Brukerens faste lokasjon                   │
│  interests: [str]             │  Ekstraherte interesser                     │
│  last_topics: [str]           │  Nylige samtaleemner                        │
│  conversation_count: int      │  Totalt antall interaksjoner                │
│  last_interaction: str        │  ISO tidsstempel                            │
│  preferences: {               │                                              │
│    formality: str             │  "casual" | "formal"                        │
│    humor_style: str           │  "friendly" | "sarcastic" | "dry"           │
│    use_dialect: bool          │  Bruk norsk dialekt                         │
│  }                            │                                              │
└───────────────────────────────┴─────────────────────────────────────────────┘
```

### Conversation Context (In-Memory)

```python
{
    "channel_id": {
        "messages": [
            {"role": "user", "content": "...", "timestamp": "..."},
            {"role": "assistant", "content": "...", "timestamp": "..."},
            # ... siste 10
        ],
        "last_activity": "ISO timestamp",
        "detected_intent": "small_talk" | "dashboard" | "calendar"
    }
}
```

---

## Konfigurasjonsflyt

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Konfigurasjon                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐  │
│  │   Environment    │      │   Filer          │      │   Runtime        │  │
│  │   Variabler      │      │   (JSON/Pickle)  │      │   Tilstand       │  │
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

### Opplastingsrekkefølge

```
1. .env lastes (discord token, bridge config)
   │
   ▼
2. JSON-datafiler lastes (kalender, brukerminne)
   │
   ▼
3. GCal token lastes (hvis finnes)
   │
   ▼
4. Hermes bridge initialiseres
   │
   ▼
5. Discord client starter
   │
   ▼
6. Ready! Venter på meldinger
```

---

## Modulavhengigheter

```
run_both.py
├── hermes_bridge_server.py
│   └── aiohttp (ekstern)
│
└── selfbot_runner.py
    ├── message_monitor.py
    │   ├── hermes_connector.py
    │   ├── intent_router.py
    │   │   ├── intent_keywords.py
    │   │   ├── intent_thresholds.py
    │   │   └── intent_utils.py
    │   ├── calendar_manager.py
    │   │   └── google_calendar_manager.py (valgfri)
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

### Avhengighetsregler

1. **Message Monitor** kan ikke avhenge av funksjoner som avhenger av den
2. **Calendar Manager** er sentral - mange funksjoner kan lese, få skrive
3. **Bridge** må starte før selfbot
4. **User Memory** kan leses av alle, skrives av AI-flow

---

## Designbeslutninger

### 1. Unified Calendar

**Problem:** Separate event_manager og reminder_manager forårsaket duplisering og inkonsistens.

**Løsning:** Single calendar_manager med type-felt ("event" | "task").

**Fordeler:**
- Enhetlig datamodell
- Felles UI for begge typer
- Enklere synkronisering

### 2. Natural Language Parser

**Problem:** Rigid kommando-syntaks er bruker-uvennlig.

**Løsning:** Parse norsk tekst til strukturerte data.

**Parser-funksjoner:**
- **Relativt:** `i dag`, `i morgen`/`i morgon`, `imårra`, `på mandag`
- **Numerisk:** `25.03.2026`, `DD.MM`, `DD/MM/YYYY`
- **Månedsnavn:** `15. mai`, `20 desember` (norsk/engelsk)
- **"Den X" mønster:** `den 5.`, `den 15. mai`
- **Tid:** `kl 14`, `klokken 14:30`, `14:30`, tidsord (`i kveld`)
- **Gjentagelse:** `hver uke`/`kvar veke`, `den 5. hver måned`, `annenhver torsdag`
- **Nynorsk:** Full støtte for `kvar`, `måndag`, `laurdag`, `kvart år`, etc.

**Fordeler:**
- Intuitivt for norske brukere
- Ingen læringskurve
- Støtter dialekter
- Fleksible datomønstre (månedsnavn + "den X")

### 3. Bridge-arkitektur

**Problem:** LM Studio kjører på Windows, bot på WSL Linux.

**Løsning:** HTTP bridge muliggjør cross-platform kommunikasjon.

**Fordeler:**
- Hver komponent kan kjøre hvor som helst
- Enkel å erstatte AI-backend
- Localhost-only = sikkert

### 4. Personality System

**Problem:** AI-responser var generiske og robotaktige.

**Løsning:** Lag med user memory + conversation context + personality config.

**Fordeler:**
- Personlig tilpasset
- Husker tidligere samtaler
- Konsekvent karakter

### 5. Robust fallback

**Problem:** Bot bør fungere selv når AI er nede.

**Løsning:** Lokale fallbacks for alle AI-avhengige funksjoner.

**Fordeler:**
- Pålitelighet
- Lavere latency for enkle spørsmål
- Fungerer offline

---

## Ytelseshensyn

| Aspekt | Strategi | Begrunnelse |
|--------|----------|-------------|
| **JSON Lagring** | God for <10k elementer | Ingen database nødvendig, enkel backup |
| **In-Memory Cache** | Conversation context utløper etter 30min | Minimerer minnebruk, fjerner gamle data |
| **Rate Limiting** | Discord API limits (5/sek, 10k/dag) | Unngår banning |
| **Lazy Loading** | GCal sync kun ved behov | Rask oppstart, mindre nettverk |
| **Batch Operations** | Kalenderliste cache'et i 5 minutter | Reduserer fil-I/O |

### Ytelsesmål

| Metrikk | Mål | Status |
|---------|-----|--------|
| Oppstartstid | <5 sekunder | ✅ |
| Responstid (lokal) | <100ms | ✅ |
| Responstid (AI) | <2 sekunder | ✅ |
| Minnebruk | <200MB | ✅ |

---

## Sikkerhetsnotater

### Autentisering

| Tjeneste | Metode | Lagring |
|----------|--------|---------|
| Discord | User Token | .env-fil (gitignored) |
| Google Calendar | OAuth2 | ~/.gcal_token.pickle |
| Web Console | API-nøkkel + cookie-session | `.env` (`CONSOLE_API_KEY`) |

### Data-sikkerhet

- **Ingen sensitive data logges** - tokens redigeres fra logger
- **Bridge kun på localhost** - ingen ekstern eksponering
- **JSON-filer lokalt** - ingen skylagring av brukerdata
- **Rate limiting** - forhindrer misbruk

### Risikoer

| Risiko | Sannsynlighet | Konsekvens | Mitigering |
|--------|---------------|------------|------------|
| Discord ban | Middels | Konto mistet | Dedikert konto, konservative limits |
| Token lekkasje | Lav | Konto kompromittert | .env i .gitignore, secret scanning |
| GCal data tap | Lav | Kalenderdata tapt | Regelmessig backup av JSON |

---

<p align="center">
  <a href="DOCUMENTATION.md">📖 Komplett Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="QUICK_REFERENCE.md">📋 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="DEVELOPMENT.md">💻 Utvikling</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
