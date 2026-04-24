# Utgivelser

Denne guiden beskriver hvordan du lager en ny release med ferdige macOS- og Windows-bygg.

## Automatisk bygg

GitHub Actions bygger desktop-appene når du pusher en tag som starter med `v`.

Flyt:

1. Lag en tag, for eksempel `v2.1.0`.
2. Push taggen til GitHub.
3. GitHub Actions bygger macOS-app og Windows-program.
4. Workflowen oppretter GitHub-utgivelse.
5. Artefakter lastes opp til releasen.

## Lag release med skript

macOS/Linux:

```bash
./scripts/create-release.sh v2.1.0
```

Windows:

```cmd
scripts\create-release.bat v2.1.0
```

Skriptet sjekker arbeidskopien, viser siste commits, ber om bekreftelse og pusher taggen.

## Lag release manuelt

```bash
git status -sb
git tag -a v2.1.0 -m "Utgivelse v2.1.0"
git push origin v2.1.0
```

Følg byggingen på:

```text
https://github.com/Reedtrullz/inebotten-discord/actions
```

Ferdige filer ligger på:

```text
https://github.com/Reedtrullz/inebotten-discord/releases/tag/v2.1.0
```

## Versjonering

Bruk semantisk versjonering:

| Del | Bruk |
|-----|-----|
| `MAJOR` | Brudd i kompatibilitet |
| `MINOR` | Nye funksjoner |
| `PATCH` | Feilrettinger |

Eksempler:

- `v2.0.0`: større release.
- `v2.1.0`: nye funksjoner.
- `v2.1.1`: feilretting.
- `v2.2.0-beta.1`: forhåndsversjon.

## Lokal byggtest

macOS:

```bash
cd mac_app
./build.sh
```

Windows:

```cmd
cd windows_app
python build.py
```

## Før release

- Kjør `python3 -m pytest -q`.
- Test intent-routeren med relevante norske prompt-eksempler.
- Bygg minst én desktop-app lokalt hvis endringen berører launcher eller packaging.
- Sjekk at `.env`, token og API-nøkler ikke ligger i diffen.
- Oppdater dokumentasjon hvis brukerflyt eller kommandoer er endret.

## Feilsøking

| Problem | Løsning |
|---------|---------|
| Tag finnes allerede | Slett lokal og remote tag, og lag den på nytt |
| Bygg feiler | Les Actions-loggen og sjekk manglende avhengigheter |
| Utgivelsen mangler filer | Sjekk at workflowen fikk lov til å opprette utgivelser |
| macOS-app blokkeres | Se `mac_app/README.md` om Gatekeeper |

Slette og lage tag på nytt:

```bash
git tag -d v2.1.0
git push origin :refs/tags/v2.1.0
git tag -a v2.1.0 -m "Utgivelse v2.1.0"
git push origin v2.1.0
```
