# Hurtigstart for macOS

## Bruk ferdig app

1. Last ned `Inebotten-macos.zip` fra GitHub-utgivelsene.
2. Pakk ut filen.
3. Høyreklikk `Inebotten.app` og velg `Åpne`.
4. Fyll inn Discord-token og eventuelt OpenRouter-nøkkel.
5. Trykk `Start Bot`.

## Bygg selv

```bash
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller
./mac_app/setup.sh
open mac_app/dist/Inebotten.app
```

## AI-valg

- LM Studio: gratis og lokalt, men krever at LM Studio kjører.
- OpenRouter: enklere drift og flere modeller, men krever API-nøkkel og internett.

Anbefalt startmodell for norsk: `google/gemma-3-4b-it:free`.

## Vanlige problemer

| Problem | Løsning |
|---------|---------|
| Gatekeeper blokkerer appen | Høyreklikk appen og velg `Åpne`, eller kjør `xattr -cr Inebotten.app` |
| Botten starter ikke | Sjekk Discord-token, AI-valg og loggen i appen |
| Manglende moduler | Kjør `python3 -m pip install -r requirements.txt` og bygg på nytt |

## Neste steg

Les [README.md](README.md) for full macOS-dokumentasjon og hoved-README-en i repoet for kommandoeksempler.
