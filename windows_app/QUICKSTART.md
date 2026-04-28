# Hurtigstart for Windows

## Bruk ferdig program

1. Last ned `Inebotten.exe` fra GitHub-utgivelsene.
2. Dobbeltklikk programmet.
3. Bekreft SmartScreen-varsel med `More info` -> `Run anyway` hvis det dukker opp.
4. Fyll inn Discord-token og eventuelt OpenRouter-nøkkel.
5. Trykk `Start Bot`.

## Bygg selv

```bat
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord
pip install -r requirements.txt
pip install pyinstaller
windows_app\setup.bat
windows_app\dist\Inebotten.exe
```

## AI-valg

- LM Studio: gratis og lokalt, men LM Studio må kjøre.
- OpenRouter: skybasert, enklere å drifte og med flere modeller.

Anbefalt norsk startmodell: `google/gemma-3-4b-it:free`.

## Vanlige problemer

| Problem | Løsning |
|---------|---------|
| SmartScreen stopper appen | Velg `More info` og `Run anyway` |
| Botten stopper raskt | Sjekk token, API-nøkkel og valgt AI-leverandør |
| Python finnes ikke | Installer Python 3.12+ med `Add Python to PATH` |
| Manglende moduler | Kjør `pip install -r requirements.txt` og bygg på nytt |

## Neste steg

Les [README.md](README.md) for full Windows-dokumentasjon og hoved-README-en i repoet for kommandoeksempler.
