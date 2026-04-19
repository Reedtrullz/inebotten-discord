# Inebotten Discord Bot

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/discord-selfbot-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord Selfbot">
  <img src="https://img.shields.io/badge/AI-LM%20Studio-green?style=for-the-badge&logo=openai&logoColor=white" alt="AI Powered">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey?style=for-the-badge&logo=apple&logoColor=white" alt="Platform">
</p>

<p align="center">
  <a href="https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml">
    <img src="https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  </a>
  <a href="https://github.com/Reedtrullz/inebotten-discord/releases">
    <img src="https://img.shields.io/github/v/release/Reedtrullz/inebotten-discord" alt="Latest Release">
  </a>
</p>

---

> **Din personlige norske Discord-kalenderbot med AI-personlighet**

Inebotten er en feature-rik Discord selfbot som kombinerer AI-drevne samtaler med praktiske verktøy som kalenderhåndtering, vær, avstemninger og mye mer.

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🤖 AI & Personlighet
- **AI-drevne samtaler** via LM Studio (gemma-3-4b)
- **Personlighetsystem** som husker deg
- **Naturlig språkforståelse** på norsk
- **Kontekstbevisst** - følger samtalen

</td>
<td width="50%">

### 📅 Kalender & Planlegging
- **Enhetlig kalender** for events og påminnelser
- **Google Calendar-sync** to-veis
- **Gjentagende events** (ukentlig, månedlig, årlig)
- **Norsk kalender** med helligdager og flaggdager

</td>
</tr>
<tr>
<td width="50%">

### 🛠️ Verktøy & Utilities
- **Vær fra MET.no** (norsk værtjeneste)
- **Avstemninger** i kanaler
- **Nedtellinger** til viktige datoer
- **Kryptopriser** (BTC, ETH, etc.)
- **Kalkulator** for raske utregninger

</td>
<td width="50%">

### 🎯 Moro & Underholdning
- **Dagens ord** - norske ord og uttrykk
- **Sitater** - inspirerende og morsomme
- **Komplimenter** - for å glede noen
- **Horoskop** - dagens stjernetegn
- **Nordlysvarsel** - for nordlysjegere

</td>
</tr>
</table>

---

## 🚀 Hurtigstart

### 📥 Last ned Pre-built Apps (Enkelst)

Last ned ferdige desktop-apper fra [Releases](https://github.com/Reedtrullz/inebotten-discord/releases):

- **macOS:** `Inebotten-macos.zip` - Pakk ut og åpne `Inebotten.app`
- **Windows:** `Inebotten.exe` - Dobbeltklikk for å kjøre

Se [RELEASE.md](RELEASE.md) for hvordan du lager nye releases.

### Bygg Lokalt

**macOS:**
```bash
cd mac_app
./build.sh
open dist/Inebotten.app
```

**Windows:**
```bash
cd windows_app
python build.py
dist\Inebotten.exe
```

Se [mac_app/README.md](mac_app/README.md) eller [windows_app/README.md](windows_app/README.md) for detaljert instruksjoner.

### Kommandolinje

#### Forutsetninger

- Python 3.10+
- Discord bruker-token ([hvordan finne](#-discord-token))
- LM Studio (valgfritt, for AI-funksjonalitet)

#### Installasjon

```bash
# 1. Klon repoet
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord

# 2. Installer avhengigheter
pip install -r requirements.txt

# 3. Konfigurer miljø
cp .env.example .env
# Rediger .env og legg til din Discord-token

# 4. Start botten
python3 run_both.py
```

---

## 📖 Dokumentasjon

| Dokument | Beskrivelse | For hvem |
|----------|-------------|----------|
| **[QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)** | Hurtigreferanse for alle kommandoer | Brukere |
| **[DOCUMENTATION.md](docs/DOCUMENTATION.md)** | Komplett teknisk dokumentasjon | Utviklere |
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Systemarkitektur og dataflyt | Utviklere |
| **[DEVELOPMENT.md](docs/DEVELOPMENT.md)** | Guide for å legge til nye features | Bidragsytere |
| **[GOOGLE_CALENDAR_SETUP.md](docs/GOOGLE_CALENDAR_SETUP.md)** | Oppsett av Google Calendar-sync | Brukere |
| **[RELEASE.md](RELEASE.md)** | Hvordan lage releases med pre-built apps | Utviklere |
| **[mac_app/README.md](mac_app/README.md)** | macOS app dokumentasjon | macOS-brukere |
| **[windows_app/README.md](windows_app/README.md)** | Windows app dokumentasjon | Windows-brukere |

---

## 💬 Eksempler på Bruk

### Kalender med naturlig språk

```
@inebotten møte med Ola i morgen kl 14
@inebotten husk å ringe mamma på lørdag
@inebotten RBK-kamp 12.04 kl 18:30 hver uke
@inebotten lunsj hver fredag kl 12
@inebotten regninger den 5. hver måned
@inebotten julebord 20 desember kl 18:00
@inebotten møte 15. mai kl 10:00
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

---

## 🏗️ Arkitektur

```
┌─────────────┐      ┌─────────────────┐      ┌──────────────┐
│  Discord    │──────▶  Message Monitor │──────▶   Handlers  │
│  (Brukere)  │      │  (Ruting)       │      │  (Kalender,  │
└─────────────┘      └────────┬────────┘      │   Vær, etc)  │
                              │               └──────────────┘
                              │                      │
                              ▼                      ▼
                    ┌─────────────────┐      ┌──────────────┐
                    │  Hermes Bridge  │──────▶  LM Studio   │
                    │  (HTTP Bridge)  │      │  (gemma-3-4b)│
                    └─────────────────┘      └──────────────┘
```

**Handler Architecture:** All 10 handlers extend `BaseHandler` for unified response handling, rate limiting, and logging.

Se [ARCHITECTURE.md](docs/ARCHITECTURE.md) for full detaljering.

---

## 🛡️ Sikkerhet

> ⚠️ **Viktig:** Discord selfbots er mot [Discord's Terms of Service](https://discord.com/terms). Bruk på egen risiko.

- **Bruk en dedikert konto** - aldri på hovedkontoen din
- **Hold token hemmelig** - aldri commit .env-filen
- **Konservative rate limits** - maks 5 meldinger/sekund
- **Kun svar ved mention** - botten responderer kun når @inebotten blir nevnt

Se [SECURITY.md](SECURITY.md) for mer informasjon.

---

## 🤝 Bidragsytere

Vi setter pris på alle bidrag! Se [CONTRIBUTING.md](CONTRIBUTING.md) for hvordan du kan hjelpe til.

---

## 📄 Lisens

Dette prosjektet er lisensiert under MIT License - se [LICENSE](LICENSE) for detaljer.

---

<p align="center">
  <b>Versjon:</b> 2.0 (April 2026) &nbsp;|&nbsp;
  <b>Modell:</b> gemma-3-4b &nbsp;|&nbsp;
  <b>Språk:</b> Norsk (bokmål/nynorsk)
</p>

<p align="center">
  Utviklet med ❤️ av <a href="https://github.com/Reedtrullz">reedtrullz</a>
</p>
