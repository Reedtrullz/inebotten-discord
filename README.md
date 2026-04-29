# Inebotten Discord Bot

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/discord-selfbot-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord selfbot">
  <img src="https://img.shields.io/badge/AI-LM%20Studio%20%7C%20OpenRouter-green?style=for-the-badge&logo=openai&logoColor=white" alt="AI">
  <img src="https://img.shields.io/badge/plattform-macOS%20%7C%20Windows-lightgrey?style=for-the-badge&logo=apple&logoColor=white" alt="Plattform">
</p>

<p align="center">
  <a href="https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml">
    <img src="https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/lisens-MIT-yellow.svg" alt="MIT-lisens">
  </a>
  <a href="https://github.com/Reedtrullz/inebotten-discord/releases">
    <img src="https://img.shields.io/github/v/release/Reedtrullz/inebotten-discord" alt="Siste utgivelse">
  </a>
</p>

> En norsk Discord-selfbot for kalender, påminnelser, nyttefunksjoner og korte AI-samtaler.

Inebotten er laget for praktisk hverdagsbruk i Discord: skriv naturlig norsk, så prøver botten å forstå om du vil lagre noe i kalenderen, se status, lage avstemning, slå opp vær, eller bare chatte. Den nye intent-routeren gjør rutingen mer konservativ, slik at samtaler som "jeg skal bare høre hva du synes om RBK i morgen" ikke blir tolket som kalenderoppgaver.

## Hovedfunksjoner

| Område | Hva botten kan |
|--------|----------------|
| Samtale | AI-chat via LM Studio lokalt eller OpenRouter i skyen |
| Kalender | Hendelser, oppgaver, gjentakelser, fullføring, sletting og Google Calendar-synk |
| Intent-ruting | Sentral router som prioriterer eksplisitte kommandoer før naturlig språk og AI-chat |
| Norsk språk | Bokmål, nynorskvarianter, vanlige dialektformer og grunnleggende engelsk |
| Verktøy | Vær, kalkulator, valuta/temperatur, krypto, URL-forkorter og søk/dashboard |
| Sosialt | Avstemninger, sitater, dagens ord, komplimenter, horoskop og nordlysvarsel |
| Drift | Rate limiting, mention-gate, helsesjekk, Docker/VPS-oppsett og desktop-launchere |
| Web Console | Dashboard med bot-status, logger og innlogging via API-nøkkel |

## Hurtigstart

### Ferdig app

Last ned siste pakke fra [GitHub-utgivelser](https://github.com/Reedtrullz/inebotten-discord/releases):

- macOS: `Inebotten-macos.zip`
- Windows: `Inebotten.exe`

macOS kan vise en Gatekeeper-advarsel fordi appen ikke er notarized. Høyreklikk `Inebotten.app`, velg `Åpne`, og bekreft. Se [mac_app/README.md](mac_app/README.md) for detaljer.

### Kommandolinje

```bash
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord

python3 -m pip install -r requirements.txt
python3 setup.py
python3 scripts/run_both.py
```

På systemer med `externally-managed-environment` kan du bruke virtuelt miljø:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### Docker/VPS

```bash
docker compose up -d
```

For VPS med webhook-basert auto-oppdatering:

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

Se [docs/VPS_DEPLOYMENT.md](docs/VPS_DEPLOYMENT.md).

## Eksempler

### Kalender og oppgaver

```text
@inebotten møte med Ola i morgen kl 14
@inebotten husk "RBK - Bodø/Glimt" på søndag kl 18:00
@inebotten lunsj hver fredag kl 12:00
@inebotten møte 15. mai kl 10
@inebotten meeting tomorrow at 3pm
@inebotten kalender (Delt på tvers av alle kanaler og DMs!)
@inebotten ferdig 2
@inebotten slett alle tannlege
```

### Samtale

```text
@inebotten hei, hvordan går det?
@inebotten hva synes du om RBK i morgen?
@inebotten fortell en kort vits
```

### Andre kommandoer

```text
@inebotten hjelp
@inebotten bot status
@inebotten status dnd
@inebotten spiller CS2
@inebotten vær i Trondheim
@inebotten avstemning Pizza? Pepperoni, Margherita, Kebab
@inebotten polls
@inebotten stem 1
@inebotten slett poll
@inebotten nedtelling til 17. mai
@inebotten pris BTC
@inebotten 100 USD til NOK
@inebotten nordlys
@inebotten Jeg bor i Trondheim
@inebotten daglig oppsummering
```

## Hvordan botten forstår meldinger

`core/intent_router.py` gir én strukturert beslutning per prompt. Routeren bruker sentraliserte keywords (`core/intent_keywords.py`) og token-aware matching (`core/intent_utils.py`) med regex word boundaries for å unngå falske positive.

**Standard prioritet:**

1. Hjelp, status, profil og eksplisitte kalenderkommandoer.
2. Aktiv avstemning og stemmegivning.
3. Nedtelling, watchlist, sitat/moro og nytteverktøy.
4. Konservativ kalender-/oppgaveforståelse med tydelig dato, tid eller påminnelsessignal.
5. Søk/dashboard når meldingen faktisk ber om kontekst utenfra.
6. AI-chat som trygg fallback.

**Confidence-tresholds:**

Usikre intents faller tilbake til AI-chat i stedet for å gjette. Kalender-NLP krever f.eks. confidence ≥ 0.94 før dispatch.

**Structured actions:**

AI kan returnere handlinger som JSON (`{"action": "SAVE_EVENT", ...}`) eller eldre tag-format (`[SAVE_EVENT: ...]`). Begge valideres gjennom `nlp_parser.parse_event()` før kalenderen endres.

## Prosjektstruktur

```text
inebotten-discord/
├── ai/                    # AI-koblinger, prompt og personlighet
├── cal_system/            # Kalender, Google Calendar og norsk dato-parser
├── core/                  # Konfig, auth, rate limit, intent-router og meldingsmonitor
├── features/              # Funksjoner og handlere
├── memory/                # Samtalekontekst og brukerminne
├── web_console/           # Dashboard, login og loggvisning
├── docs/                  # Norsk dokumentasjon
├── scripts/               # Start-, test- og deploy-skript
├── tests/                 # Enhets- og rutingtester
├── mac_app/               # macOS-launcher
└── windows_app/           # Windows-launcher
```

## Dokumentasjon

| Dokument | Innhold |
|----------|---------|
| [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md) | Kort kommandooversikt |
| [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) | Komplett teknisk gjennomgang |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arkitektur, dataflyt og designvalg |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Utviklingsguide og testpraksis |
| [docs/SECURITY.md](docs/SECURITY.md) | Sikkerhetsmodell og hemmeligheter |
| [docs/GOOGLE_CALENDAR_SETUP.md](docs/GOOGLE_CALENDAR_SETUP.md) | Google Calendar-oppsett |
| [docs/OPENROUTER_SETUP.md](docs/OPENROUTER_SETUP.md) | OpenRouter-oppsett |
| [docs/LM_STUDIO_SETUP.md](docs/LM_STUDIO_SETUP.md) | LM Studio-oppsett |
| [docs/VPS_DEPLOYMENT.md](docs/VPS_DEPLOYMENT.md) | VPS, Docker og auto-oppdatering |
| [docs/RELEASE.md](docs/RELEASE.md) | Utgivelser og desktop-bygg |

## Utvikling og test

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest -q
```

Nyttige måltester:

```bash
python3 -m pytest tests/test_intent_router.py -q
python3 -m pytest tests/test_message_monitor_routing.py -q
python3 -m pytest tests/test_false_positives.py -q
python3 -m pytest tests/test_action_schema.py -q
python3 -m pytest tests/test_comprehensive.py -q
```

## Sikkerhet

Discord selfbots bryter med Discords vilkår. Bruk en dedikert testkonto, hold token og API-nøkler unna git, og bruk botten på egen risiko.

Launcher-konfigurasjon skal bare inneholde ikke-hemmelige preferanser. Hemmeligheter lagres via sikker lagring eller `.env` med stramme filrettigheter.

## Bidra

Les [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) før du sender endringer. For sikkerhetsfunn, følg [docs/SECURITY.md](docs/SECURITY.md) og ikke åpne offentlig issue.

## Lisens

MIT. Se [LICENSE](LICENSE).

<p align="center">
  <b>Språk:</b> norsk først &nbsp;|&nbsp;
  <b>AI:</b> LM Studio eller OpenRouter &nbsp;|&nbsp;
  <b>Status:</b> aktivt utviklet
</p>
