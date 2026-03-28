# Inebotten Discord Bot

[![CI](https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml/badge.svg)](https://github.com/Reedtrullz/inebotten-discord/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Discord](https://img.shields.io/badge/discord-selfbot-5865F2?logo=discord)](https://discord.com)

> Din personlige norske Discord-kalenderbot med AI-personlighet

## Hva er Inebotten?

Inebotten er en feature-rik Discord selfbot som kombinerer:
- 🤖 **AI-drevne samtaler** (via LM Studio / gemma-3-4b)
- 📅 **Kalender med Google Calendar-sync**
- 🗣️ **Naturlig språkforståelse** (norsk)
- 🧠 **Personlighetsystem** som husker deg
- 🌤️ **Vær fra MET.no**
- 📊 **Avstemninger, nedtellinger, krypto, horoskop** ++

## Hurtigstart

```bash
# Start alt sammen
python3 run_both.py

# Eller separat:
python3 hermes_bridge_server.py  # Terminal 1
python3 selfbot_runner.py        # Terminal 2
```

## Dokumentasjon

| Dokument | Beskrivelse |
|----------|-------------|
| **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** | Hurtigreferanse for kommandoer |
| **[DOCUMENTATION.md](DOCUMENTATION.md)** | Full funksjonell dokumentasjon |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Systemarkitektur og dataflyt |
| **[DEVELOPMENT.md](DEVELOPMENT.md)** | Utviklerguide for nye features |
| **[GOOGLE_CALENDAR_SETUP.md](GOOGLE_CALENDAR_SETUP.md)** | Oppsett av Google Calendar-sync |

## Eksempler på bruk

### Kalender med naturlig språk

```
@inebotten møte med Ola i morgen kl 14
@inebotten husk å ringe mamma på lørdag
@inebotten RBK-kamp 12.04 kl 18:30 hver uke
@inebotten lunsj hver fredag kl 12
```

### Vanlig chatting

```
@inebotten Hei! Hvordan går det?
@inebotten Hva synes du om RBK?
@inebotten Fortell en vits
```

### Andre kommandoer

```
@inebotten vær                    # Værmelding
@inebotten avstemning Pizza?       # Lag avstemning
@inebotten nedtelling til 17. mai  # Nedtelling
@inebotten pris BTC                # Kryptopris
@inebotten horoskop væren          # Horoskop
```

## Arkitektur

```
Discord ──► Message Monitor ──┬──► Calendar Manager ──► JSON
                              ├──► AI Response ───────► LM Studio
                              ├──► User Memory ───────► JSON
                              └──► [Features...]
```

## Teknisk Stack

- **Språk:** Python 3.10+
- **AI:** gemma-3-4b via LM Studio
- **Discord:** discord.py (selfbot)
- **Bridge:** aiohttp (HTTP)
- **Lagring:** JSON-filer
- **Eksterne APIer:** MET.no (vær), Google Calendar

## Viktige Filer

| Fil | Linjer | Formål |
|-----|--------|--------|
| `message_monitor.py` | 1,240 | Hovedlogikk og ruting |
| `calendar_manager.py` | 435 | Enhetlig kalendersystem |
| `natural_language_parser.py` | 686 | Norsk språkforståelse |
| `hermes_bridge_server.py` | 353 | AI-bro til LM Studio |

## Status Ikoner

| Ikon | Betydning |
|------|-----------|
| 📅 | Synkronisert med Google Calendar |
| 📌 | Kun lokalt |
| ✓ | Fullført |
| 🔄 | Gjentagende |

## Utvikling

Se [DEVELOPMENT.md](DEVELOPMENT.md) for guide om å legge til nye features.

Hurtig sjekk:
```bash
# Syntaks-sjekk
python3 -m py_compile *.py

# Kjør tester
python3 test_selfbot.py
```

## Lisens

Privat bruk - utviklet av reedtrullz

---

**Versjon:** 2.0 (Mars 2026)  
**Modell:** gemma-3-4b  
**Språk:** Norsk (bokmål/nynorsk)
