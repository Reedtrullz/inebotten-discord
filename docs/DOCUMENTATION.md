# Inebotten - Komplett Dokumentasjon

> Omfattende dokumentasjon for utviklere og avanserte brukere

---

## 📋 Innholdsfortegnelse

1. [Oversikt](#oversikt)
2. [Systemarkitektur](#systemarkitektur)
3. [Komponenter](#komponenter)
4. [Datastrøm](#datastrøm)
5. [Kalendersystem](#kalendersystem)
6. [Personlighetssystem](#personlighetssystem)
7. [Features](#features)
8. [Konfigurasjon](#konfigurasjon)
9. [Utvikling](#utvikling)
10. [Feilsøking](#feilsøking)

---

## Oversikt

**Inebotten** er en feature-rik norsk Discord selfbot som kombinerer AI-drevne samtaler med praktiske verktøy. Arkitekturen er modulær og designet for:

- **Pålitelighet** - Lokale fallbacks når AI er utilgjengelig
- **Skalerbarhet** - Enkel å utvide med nye features
- **Personalisering** - Husker brukere og tilpasser seg
- **Naturlig språk** - Ingen rigid kommando-struktur

### Teknisk Stack

| Komponent | Teknologi |
|-----------|-----------|
| Språk | Python 3.10+ |
| Discord API | discord.py |
| AI Backend | LM Studio (gemma-3-4b) |
| Bridge | aiohttp HTTP server |
| Lagring | JSON-filer |
| Vær API | MET.no (gratis, norsk) |
| Kalender | Google Calendar API |

---

## Systemarkitektur

### Høynivå Arkitektur

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                   BRUKERGRENSESNITT                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   Discord    │  │   Google     │  │   LM Studio  │  │    MET.no    │              │
│  │   (Chat)     │  │  Calendar    │  │    (AI)      │  │   (Vær)      │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
└─────────┼─────────────────┼─────────────────┼─────────────────┼──────────────────────┘
          │                 │                 │                 │
          ▼                 ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                      BOT LAG                                         │
│  ┌───────────────────────────────────────────────────────────────────────────────┐   │
│  │                         Message Monitor (message_monitor.py)                   │   │
│  │                         ─────────────────────────────────                      │   │
│  │  • Mention-deteksjon    • Kommandoruting    • AI-fallback                    │   │
│  └───────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                            │
│                    ┌────────────────────┼────────────────────┐                        │
│                    ▼                    ▼                    ▼                        │
│         ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐               │
│         │  Natural Lang   │  │  Personality    │  │  Feature        │               │
│         │  Parser         │  │  System         │  │  Handlers       │               │
│         └─────────────────┘  └─────────────────┘  └─────────────────┘               │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
┌─────────────────────────────────────────▼────────────────────────────────────────────┐
│                                      DATA LAG                                        │
│                                                                                      │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                  │
│   │  Calendar Store  │  │   User Memory    │  │   GCal Cache     │                  │
│   │  (JSON)          │  │   (JSON)         │  │   (OAuth)        │                  │
│   └──────────────────┘  └──────────────────┘  └──────────────────┘                  │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Meldingsflyt

```
┌─────────┐     ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Bruker │────▶│   Discord   │────▶│  Message Monitor │────▶│  Kommando-   │
│  Input  │     │   Gateway   │     │  (process_msg)  │     │  Deteksjon   │
└─────────┘     └─────────────┘     └─────────────────┘     └──────┬───────┘
                                                                   │
              ┌────────────────────────────────────────────────────┼──────────────┐
              │                                                    │              │
        ┌─────▼──────┐  ┌──────────┐  ┌──────────┐         ┌─────▼──────┐  ┌──▼──────┐
        │   Intent   │  │ Natural  │  │ Kalender │         │   Andre    │  │   AI    │
        │   Sjekk    │  │ Språk    │  │ Kommando │         │  Kommando  │  │  Chat   │
        └─────┬──────┘  └────┬─────┘  └────┬─────┘         └─────┬──────┘  └────┬────┘
              │              │             │                     │            │
              └──────────────┴─────────────┴─────────────────────┘            │
                              │                                              │
                    ┌─────────▼──────────┐                      ┌───────────▼──────────┐
                    │  Calendar Manager  │                      │   AI Response Flow   │
                    │  • Legg til/slett  │                      │   • Bygg kontekst    │
                    │  • Fullfør         │                      │   • Kall bridge      │
                    │  • Sync til GCal   │                      │   • Returner svar    │
                    └─────────┬──────────┘                      └───────────┬──────────┘
                              │                                            │
                    ┌─────────▼──────────┐                      ┌───────────▼──────────┐
                    │   JSON Lagring     │                      │   LM Studio (gemma)  │
                    │  (data/calendar.   │                      │   eller lokal fallback│
                    │       json)        │                      │                      │
                    └────────────────────┘                      └──────────────────────┘
```

---

## Komponenter

### 1. Entry Points

| Fil | Formål | Bruk |
|-----|--------|------|
| `run_both.py` | Starter bridge + selfbot samtidig | `python3 run_both.py` |
| `selfbot_runner.py` | Kun selfbot (bridge må kjøre) | `python3 selfbot_runner.py` |
| `hermes_bridge_server.py` | Kun bridge | `python3 hermes_bridge_server.py` |

### 2. Bridge Layer (`hermes_bridge_server.py`)

**Formål:** HTTP-bro mellom Discord-bot og LM Studio

**Endpoints:**

| Endpoint | Metode | Beskrivelse |
|----------|--------|-------------|
| `/api/chat` | GET | Hoved-AI-endpoint. Tar `data`-parameter med JSON-payload |
| `/health` | GET | Health check, returnerer status |

**Fallback-oppførsel:**
- Hvis LM Studio er utilgjengelig, brukes lokale responssjablonger
- Grunnleggende funksjonalitet opprettholdes uten AI

**System Prompt:**

```
Du er 'inebotten', ein vennleg Discord-kalenderbot.
I dag er det {weekday} {today}.
Du svarar ALLTID på norsk (nynorsk eller bokmål).
ALDRI svar på engelsk.
Du hjelper til med vêr, høgtider, kalender og generelle spørsmål.
Hald svara korte (under 300 ord) og vennlege.
Du pratar med {author_name}.
```

### 3. Message Monitor (`message_monitor.py`)

**Formål:** Kjernen i meldingshåndtering og kommando-ruting (~1200 linjer)

**Nøkkelmetoder:**

| Metode | Beskrivelse |
|--------|-------------|
| `is_mention()` | Detekterer @inebotten-mentions |
| `handle_message()` | Hovedprosesseringsrørledning |
| `_send_ai_response()` | AI-/samtalerespons |
| `handlers["calendar"]` | Kalenderkommandoer (via CalendarHandler) |

**Kommandoprioritet:**

1. Naturlig språk kalender-parser
2. Spesifikke kommandomatchere (nedtelling, avstemning, etc.)
3. AI-fallback for generell chat

### 4. Kalendersystem

#### 4.1 Unified Calendar Manager (`calendar_manager.py`)

**Erstatter:** Separate event_manager og reminder_manager

**Lagring:** `~/.hermes/discord/data/calendar.json`

**Features:**
- Events + påminnelser i ett system
- Gjentagende elementer (ukentlig, annenhver uke, månedlig, årlig)
- Fullføringssporing
- Google Calendar sync-støtte

**Datamodell:**

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

#### 4.2 Natural Language Parser (`natural_language_parser.py`)

**Formål:** Parse norsk tekst til kalender-elementer

**Støttede mønstre:**

| Input | Resultat |
|-------|----------|
| `@inebotten møte i morgen kl 14` | Event i morgen 14:00 |
| `@inebotten husk å ringe mamma på lørdag` | Påminnelse på lørdag |
| `@inebotten RBK-kamp 12.04 kl 18:30` | Spesifikk dato/tid |
| `@inebotten lunsj med Ola hver fredag kl 12` | Gjentagende ukentlig |
| `@inebotten test imårra kl 13:37` | Dialektstøtte (imårra) |
| `@inebotten møte 15. mai kl 10:00` | Månedsnavn (mai) |
| `@inebotten regninger den 5. hver måned` | "Den X" mønster med gjentagelse |
| `@inebotten bursdag 20 desember` | Månedsnavn uten punktum |

**Datoparsing:**
- Eksplisitt: `25.03.2026`, `25/03/2026`
- Relativt: `i dag`, `i morgen`/`imorgen`/`imårra`/`i morgon`, `i overmorgen`
- Ukedager: `på mandag`/`måndag`, `neste tirsdag` (Bokmål + Nynorsk)
- Månedsnavn: `15. mai`, `20 desember`, `1. januar` (norsk/engelsk)
- "Den X" mønster: `den 5.`, `den 15. mai` (daglig gjentagelse)
- Dialektstøtte: Nynorsk (`kvar veke`, `måndag`, `laurdag`, etc.)

**Gjentagelse:**
- Nøkkelord: `hver uke`, `hver måned`, `hvert år`, `annenhver uke`
- Dags-spesifikasjon: `hver mandag`, `hver lørdag kl 10`
- Månedlig med dato: `den 5. hver måned` (kombinert mønster)

#### 4.3 Google Calendar Integration (`google_calendar_manager.py`)

**Formål:** To-veis sync med Google Calendar

**OAuth Flyt:**
1. Bruker kjører `sync_calendar_to_gcal.py`
2. Åpner nettleser for Google OAuth
3. Godkjenner kalender-tilgang
4. Token lagres i `~/.gcal_token.pickle`

**Sync-oppførsel:**
- Oppretter events i GCal når lagt til via bot
- Lagrer GCal event-ID for fremtidige oppdateringer
- Viser 📅 indikator for synkroniserte elementer
- Viser 📌 for kun lokale elementer

### 5. Personlighetssystem

#### 5.1 User Memory (`user_memory.py`)

**Lagring:** `~/.hermes/discord/data/user_memory.json`

**Sporingsdata:**

| Felt | Beskrivelse |
|------|-------------|
| `username` | Discord visningsnavn |
| `location` | Brukerens lokasjon |
| `interests` | Automatisk ekstraherte interesser |
| `last_topics` | Nylige samtaleemner |
| `conversation_count` | Totalt antall interaksjoner |
| `last_interaction` | ISO-tidsstempel |
| `preferences` | {formality, humor_style, use_dialect} |

**Features:**
- Personlige hilsener ("Hei Rune! Lenge siden sist - 3 dager!")
- Dager-siden-sist-chat sporing
- Interesse-baserte samtalestartere

#### 5.2 Conversation Context (`conversation_context.py`)

**Formål:** Vedlikeholder samtaletråder og detekterer intensjon

**Intent-deteksjon:**

| Type | Eksempler |
|------|-----------|
| Small talk (ikke vis dashboard) | "Hei!", "Hvordan går det?", "Hva synes du om RBK?" |
| Dashboard-forespørsler | "Hva er været?", "Vis meg kalenderen", "Hva skjer i dag?" |

**Samtalehistorikk:**
- Lagrer siste 10 meldinger per kanal
- Utløper etter 30 minutter inaktivitet
- Gir kontekst til AI for koherente samtaler

#### 5.3 Personality Config (`personality_config.py`)

**Karakterprofil:**

| Egenskap | Beskrivelse |
|----------|-------------|
| Navn | Inebotten |
| Personlighet | Avslappet, humoristisk nordmann |
| Trekk | Bruker dialekt (imårra, serr), fotballmeninger (RBK) |
| Stil | Hjelpsom men ikke påtrengende, ikke robotaktig |

**DO:**
- Varier hilsener
- Referer til tidligere samtaler
- Bruk humor og personlighet
- Vis at du husker brukeren

**DON'T:**
- Start med vær med mindre spurt
- List opp kalender uten å bli spurt
- Vær robotaktig eller over-hjelpsom
- Bruk "Som en AI..." fraser

### 6. Andre Features

| Feature | Fil | Kommando |
|---------|-----|----------|
| **Avstemninger** | `poll_manager.py` | `@inebotten avstemning Tittel? Alt1, Alt2` |
| **Nedtellinger** | `countdown_manager.py` | `@inebotten nedtelling til [dato]` |
| **Watchlist** | `watchlist_manager.py` | `@inebotten watchlist add [symbol]` |
| **Krypto** | `crypto_manager.py` | `@inebotten pris BTC` |
| **Horoskop** | `horoscope_manager.py` | `@inebotten horoskop [stjernetegn]` |
| **Kalkulator** | `calculator_manager.py` | `@inebotten kalk 2+2*3` |
| **Sitater** | `quote_manager.py` | `@inebotten sitat` |
| **Dagens ord** | `word_of_day.py` | `@inebotten dagens ord` |
| **Komplimenter** | `compliments_manager.py` | `@inebotten kompliment` |
| **URL-forkorter** | `url_shortener.py` | `@inebotten shorten [url]` |
| **Nordlys** | `aurora_forecast.py` | `@inebotten nordlys` |

### 7. Utility-komponenter

| Fil | Formål |
|-----|--------|
| `weather_api.py` | MET.no API-integrasjon (norsk vær) |
| `norwegian_calendar.py` | Helligdager, flaggdager, navnedager |
| `localization.py` | Norske oversettelser og formatering |
| `rate_limiter.py` | Discord API rate limiting |
| `response_generator.py` | Fallback-responsgenerering |

---

## Datastrøm

### Legge til Kalender-event (Naturlig Språk)

```
Bruker: @inebotten møte med Ola i morgen kl 14

1. message_monitor detekterer mention
2. natural_language_parser.parse_event() ekstraherer:
   - title: "møte med Ola"
   - date: tomorrow (kalkulert)
   - time: "14:00"
3. calendar_manager.add_item() lagrer til JSON
4. Hvis GCal aktivert: google_calendar_manager.sync_to_gcal()
5. Bot svarer: "Lagt til: Møte med Ola - [dato] kl. 14:00"
```

### Small Talk Respons (AI)

```
Bruker: @inebotten Hei! Hvordan går det?

1. message_monitor detekterer mention
2. conversation_context.is_small_talk() = True
3. user_memory.update_last_interaction() registrerer emne
4. Bygg personlig system_prompt med brukerkontekst
5. hermes_connector.generate_response() sender til bridge
6. Bridge videresender til LM Studio (gemma-3-4b)
7. Bot svarer med AI-generert, personlighetsinfusert respons
```

### Kalendervisning

```
Bruker: @inebotten kalender

1. handlers["calendar"].handle_list() kalles
2. calendar_manager.get_upcoming() henter elementer
3. Formater med statusindikatorer (📅📌✓)
4. Vis Google Calendar sync-lenker hvis aktivert
5. Bot svarer med formatert liste + "ferdig [nummer]" hjelp
```

---

## Kalendersystem

### Kommandoer

```
@inebotten kalender                      # List alle kommende elementer
@inebotten kalender 7                    # List neste 7 dager
@inebotten møte [tittel] [dato] [tid]    # Legg til event
@inebotten husk [tittel] [dato]          # Legg til task/påminnelse
@inebotten ferdig [nummer]               # Marker element som fullført
@inebotten slett [nummer]                # Slett element
@inebotten sync                          # Sync til Google Calendar
```

### Naturlig Språk (Ingen Kommandostruktur)

```
@inebotten lunsj med teamet på fredag kl 12
@inebotten husk å betale regninga imårra
@inebotten tannlege neste tirsdag kl 09:00
@inebotten RBK-kamp 12.04 kl 18:30 hver uke
@inebotten bursdag til mamma 15.05 hvert år
```

### Utility-kommandoer

```
@inebotten vær                          # Nåværende vær
@inebotten været i Oslo                 # Vær for lokasjon
@inebotten avstemning Pizza eller burger?  # Lag avstemning
@inebotten stem 1                        # Stem på avstemning
@inebotten nedtelling til 17. mai       # Start nedtelling
@inebotten dagens ord                    # Norsk ord for dagen
@inebotten horoskop væren                # Dagens horoskop
@inebotten pris BTC                      # Kryptopris
@inebotten kalk (100 * 1.25) / 2         # Kalkulator
```

---

## Konfigurasjon

### Miljøvariabler

```bash
# Bridge-konfigurasjon
HERMES_BRIDGE_HOST=127.0.0.1
HERMES_BRIDGE_PORT=3000

# Discord Token (i .env-fil)
DISCORD_TOKEN=***

# Google Calendar (OAuth-credentials)
# Lagret i ~/.gcal_credentials.json etter første kjøring
```

### Filplasseringer

| Fil | Plassering | Formål |
|-----|------------|--------|
| Kalenderdata | `~/.hermes/discord/data/calendar.json` | Events & påminnelser |
| Brukerminne | `~/.hermes/discord/data/user_memory.json` | Brukerpreferanser |
| GCal Token | `~/.gcal_token.pickle` | Google OAuth token |
| GCal Credentials | `~/.gcal_credentials.json` | Google OAuth credentials |

---

## Utvikling

### Kjøre Tester

```bash
python3 tests/test_selfbot.py              # Basis-tester
python3 tests/test_selfbot_comprehensive.py # Full test-suite
python3 -m py_compile *.py                 # Syntaks-sjekk alle filer
```

### Legge til Nye Features

Se [DEVELOPMENT.md](DEVELOPMENT.md) for komplett guide.

Kortversjon:

1. Lag `feature_manager.py` med kommandoparsing
2. Legg til i `message_monitor.py` imports og initialisering
3. Legg til kommandomatcher i `process_message()`
4. Legg til handler-metode `_handle_feature_command()`
5. Oppdater denne dokumentasjonen

---

## Arkitekturstyrker

1. **Modulær Design** - Hver feature er selvstendig
2. **Graceful Degradation** - Fungerer uten AI (lokale fallbacks)
3. **Enhetlig Kalender** - Ett system for events + påminnelser
4. **Naturlig Språk** - Ingen rigid kommando-syntaks
5. **Google Integrasjon** - Syncer med ekte kalender
6. **Personlighetssystem** - Kontekstbevisst, personlig tilpasset

---

## Kjente Begrensninger

1. **Bridge System Prompt** - Broen ignorerer botens personlige system_prompt
2. **Selfbot Nature** - Krever user token (ikke bot token), mot Discord ToS for produksjon
3. **Ingen Persistent AI-minne** - AI husker ikke på tvers av omstarter (men user_memory.json gjør)
4. **Single Guild Fokus** - Noen features fungerer best med én Discord-server

---

## Fremtidige Forbedringer

- [ ] Fiks bridge til å bruke botens personlige system_prompt
- [ ] Mer norsk dialekt-støtte
- [ ] Bildegenererings-integrasjon
- [ ] Stemme-melding-støtte
- [ ] Flerspråklig støtte (Svensk, Dansk)
- [ ] Web dashboard for kalenderhåndtering

---

## Feilsøking

### Vanlige Problemer

| Problem | Årsak | Løsning |
|---------|-------|---------|
| Botten svarer ikke | Bridge eller selfbot ikke kjørende | Sjekk `run_both.py` output |
| AI svarer ikke | LM Studio ikke tilgjengelig | Start LM Studio på Windows |
| "Invalid token" | Token utløpt | Hent ny token fra Discord DevTools |
| GCal sync feiler | OAuth utløpt | Kjør sync-skript på nytt |
| "Fant ikke nummer" | Feil nummer i kalender | Bruk `@inebotten kalender` først |

### Debug Logging

Legg til i koden:
```python
print(f"[DEBUG] variable={value}")
```

### Sjekk Lagring

```bash
# Vis lagrede data
cat ~/.hermes/discord/data/calendar.json | python3 -m json.tool
```

---

<p align="center">
  <b>Versjon:</b> 2.0 (Mars 2026) &nbsp;|&nbsp;
  <b>Hovedspråk:</b> Norsk (Bokmål/Nynorsk) &nbsp;|&nbsp;
  <b>AI-modell:</b> gemma-3-4b via LM Studio &nbsp;|&nbsp;
  <b>Maintainer:</b> reedtrullz
</p>

<p align="center">
  <a href="QUICK_REFERENCE.md">📖 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="ARCHITECTURE.md">🏗️ Arkitektur</a> &nbsp;•&nbsp;
  <a href="DEVELOPMENT.md">💻 Utvikling</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
