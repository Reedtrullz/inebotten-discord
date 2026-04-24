# Inebotten for macOS

Dette er macOS-launcheren for Inebotten. Den gir et enkelt grafisk grensesnitt for å lagre innstillinger, velge AI-leverandør og starte eller stoppe botten uten terminal.

## Funksjoner

- Native macOS-app som kan åpnes med dobbeltklikk.
- Felt for Discord-token, OpenRouter-nøkkel, modell og leverandørvalg.
- Støtte for LM Studio lokalt og OpenRouter i skyen.
- Sanntidslogg fra bot-prosessen.
- Start/stopp-knapper for normal bruk.
- Hemmeligheter lagres ikke i `launcher_config.json`; bruk sikker lagring eller `.env`.

## Krav

- macOS 12 Monterey eller nyere.
- Python 3.10 eller nyere hvis du bygger selv.
- PyInstaller hvis du bygger `.app` lokalt.

## Bruk ferdig app

1. Last ned `Inebotten-macos.zip` fra [GitHub-utgivelser](https://github.com/Reedtrullz/inebotten-discord/releases).
2. Pakk ut zip-filen.
3. Høyreklikk `Inebotten.app` og velg `Åpne` hvis macOS viser Gatekeeper-varsel.
4. Fyll inn konfigurasjon og trykk `Start Bot`.

## Bygg fra kildekode

```bash
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller

cd mac_app
./build.sh
open dist/Inebotten.app
```

## Førstegangsoppsett

1. Velg AI-leverandør:
   - `lm_studio` for lokal modell.
   - `openrouter` for skybasert modell.
2. Legg inn Discord-token.
3. Legg inn OpenRouter API-nøkkel hvis du bruker OpenRouter.
4. Velg modell, for eksempel `google/gemma-3-4b-it:free`.
5. Lagre konfigurasjon og start botten.

## Discord-token

Bruk en dedikert testkonto. Token er hemmelig og må aldri legges i git.

1. Åpne Discord i nettleseren.
2. Trykk `Cmd+Option+I`.
3. Gå til `Application` -> `Local Storage` -> `https://discord.com`.
4. Finn `token` og kopier verdien.

## OpenRouter-nøkkel

1. Gå til [openrouter.ai/keys](https://openrouter.ai/keys).
2. Logg inn og opprett en ny nøkkel.
3. Kopier nøkkelen som starter med `sk-or-`.

## Feilsøking

### "Inebotten.app er skadet og kan ikke åpnes"

Dette er vanlig for usignerte apper.

```bash
xattr -cr dist/Inebotten.app
open dist/Inebotten.app
```

Du kan også høyreklikke appen og velge `Åpne`.

### Appen åpner ikke

- Sjekk at du bruker macOS 12 eller nyere.
- Bygg appen på nytt med `cd mac_app && ./build.sh`.
- Se etter feil i loggen.

### Botten stopper med en gang

- Sjekk Discord-token.
- Sjekk OpenRouter-nøkkel hvis OpenRouter er valgt.
- Start LM Studio hvis `lm_studio` er valgt.
- Les sanntidsloggen i appen.

## Filer

```text
~/.hermes/discord/.env                  # hemmeligheter og bot-konfigurasjon
~/.hermes/discord/launcher_config.json  # ikke-hemmelige GUI-valg
~/.hermes/discord/data/                 # kalender og lokal data
~/.hermes/discord/logs/inebotten.log    # logg
```

## Distribusjon

`build.sh` bruker PyInstaller og ad-hoc-signering for lokal distribusjon. Offentlige utgivelser bygges via GitHub Actions når en release-tag pushes.
