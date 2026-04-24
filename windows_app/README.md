# Inebotten for Windows

Dette er Windows-launcheren for Inebotten. Den gir et enkelt grafisk grensesnitt for konfigurasjon, AI-valg, start/stopp og sanntidslogg.

## Funksjoner

- Native Windows-program som kan startes med dobbeltklikk.
- Støtte for LM Studio lokalt og OpenRouter i skyen.
- Felter for Discord-token, API-nøkkel, modell og leverandør.
- Sanntidslogg fra botten.
- Konfigurasjon for ikke-hemmelige valg lagres i `launcher_config.json`.
- Hemmeligheter skal lagres i sikker lagring eller `.env`, ikke i plaintext GUI-konfig.

## Krav

- Windows 10 eller nyere, 64-bit.
- Python 3.10 eller nyere hvis du bygger selv.
- PyInstaller for lokalt bygg.

## Bruk ferdig program

1. Last ned `Inebotten.exe` fra [GitHub-utgivelser](https://github.com/Reedtrullz/inebotten-discord/releases).
2. Dobbeltklikk filen.
3. Hvis SmartScreen stopper deg, velg `More info` og deretter `Run anyway`.
4. Fyll inn konfigurasjon og trykk `Start Bot`.

## Bygg fra kildekode

```bat
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
pip install -r requirements.txt
pip install pyinstaller

cd windows_app
python build.py
dist\Inebotten.exe
```

Du kan også kjøre:

```bat
windows_app\setup.bat
```

## Førstegangsoppsett

1. Velg `lm_studio` eller `openrouter`.
2. Legg inn Discord-token for en dedikert testkonto.
3. Legg inn OpenRouter API-nøkkel hvis du bruker OpenRouter.
4. Velg modell, for eksempel `google/gemma-3-4b-it:free`.
5. Lagre og start botten.

## Discord-token

1. Åpne Discord i nettleseren.
2. Trykk `F12`.
3. Gå til `Application` -> `Local Storage` -> `https://discord.com`.
4. Finn `token` og kopier verdien.

## OpenRouter-nøkkel

1. Gå til [openrouter.ai/keys](https://openrouter.ai/keys).
2. Logg inn og opprett en ny nøkkel.
3. Kopier nøkkelen som starter med `sk-or-`.

## Feilsøking

| Problem | Løsning |
|---------|---------|
| SmartScreen-varsel | Velg `More info` og `Run anyway` |
| Programmet åpner ikke | Sjekk Windows-versjon, bygg på nytt og les loggen |
| Botten stopper | Sjekk Discord-token, OpenRouter-nøkkel og LM Studio-status |
| Python mangler | Installer Python 3.10+ og huk av `Add Python to PATH` |

## Filer

```text
C:\Users\<deg>\.hermes\discord\.env                  # hemmeligheter og bot-konfigurasjon
C:\Users\<deg>\.hermes\discord\launcher_config.json  # ikke-hemmelige GUI-valg
C:\Users\<deg>\.hermes\discord\data\                 # kalender og lokal data
C:\Users\<deg>\.hermes\discord\logs\inebotten.log    # logg
```

## Distribusjon

`build.py` bruker PyInstaller for å lage `dist\Inebotten.exe`. Offentlige utgivelser bygges via GitHub Actions når en release-tag pushes.
