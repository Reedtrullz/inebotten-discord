# Bidragsguide for Inebotten

> Takk for at du vurderer å bidra til Inebotten! 🎉

---

## 📋 Innholdsfortegnelse

1. [Hvordan Kan Jeg Bidra?](#hvordan-kan-jeg-bidra)
2. [Utviklingsoppsett](#utviklingsoppsett)
3. [Kode-stil](#kode-stil)
4. [Commit-meldinger](#commit-meldinger)
5. [Pull Request-prosess](#pull-request-prosess)
6. [Rapportere Bugs](#rapportere-bugs)
7. [Foreslå funksjoner](#foreslå-funksjoner)
8. [Sikkerhet](#sikkerhet)
9. [Kommunikasjon](#kommunikasjon)

---

## Hvordan Kan Jeg Bidra?

Det er mange måter å bidra på:

- 🐛 **Rapportere bugs** - Hjelper oss å forbedre
- 💡 **Foreslå funksjoner** - Del dine ideer
- 📝 **Forbedre dokumentasjon** - Gjør det klarere
- 🔧 **Fikse bugs** - Hopp på et [good first issue](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
- ✨ **Legge til funksjoner** - Utvid funksjonaliteten
- 🎨 **UI/UX forbedringer** - Gjør det penere

---

## Utviklingsoppsett

### 1. Fork og Klon

```bash
# Fork repoet på GitHub, deretter:
git clone https://github.com/DIN-BRUKER/inebotten-discord.git
cd inebotten-discord

# Legg til upstream remote
git remote add upstream https://github.com/Reedtrullz/inebotten-discord.git
```

### 2. Sett Opp Miljø

```bash
# Lag virtuelt miljø
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Installer avhengigheter
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Kopier miljøfil
cp .env.example .env
# Rediger .env med din Discord-token (test-konto!)
```

### 3. Verifiser Oppsett

```bash
# Syntaks-sjekk
python3 -m py_compile core/*.py features/*.py

# Kjør tester
python3 tests/test_selfbot.py

# Test at imports fungerer
python3 -c "from core import message_monitor; print('✅ OK')"
```

---

## Kode-stil

Vi følger [PEP 8](https://pep8.org/) med noen justeringer.

### Navngiving

| Type | Konvensjon | Eksempel |
|------|------------|----------|
| Klasser | PascalCase | `CalendarManager` |
| Funksjoner | snake_case | `parse_event` |
| Konstanter | UPPER_CASE | `MAX_ITEMS` |
| Private | _leading_underscore | `_load_data` |

### Type Hints

Bruk alltid type hints:

```python
def calculate_date(
    date_str: str,
    days: int = 1
) -> Optional[str]:
    """Beregn ny dato."""
    ...
```

### Dokumentasjon

```python
def complex_function(param1: str, param2: int) -> bool:
    """
    Kort beskrivelse av hva funksjonen gjør.
    
    Mer detaljert forklaring hvis nødvendig. Kan være
    flere linjer og forklare kompleks logikk.
    
    Args:
        param1: Beskrivelse av første parameter
        param2: Beskrivelse av andre parameter
    
    Returns:
        Beskrivelse av returverdi
    
    Raises:
        ValueError: Hvis param1 er ugyldig
    
    Example:
        >>> complex_function("test", 42)
        True
    """
```

### Norsk vs Engelsk

- **Kode:** Engelsk
- **Kommentarer:** Engelsk
- **Brukervendte meldinger:** Norsk

```python
# ✅ Godt
error_message = "Fant ikke noe med det nummeret."

# ❌ Dårlig
error_message = "Item not found with that number."
```

---

## Commit-meldinger

Skriv gode commit-meldinger:

```
Add user memory persistence

- Store user preferences in JSON
- Track conversation count
- Remember last interaction time
- Auto-expire old context after 30min

Fixes #123
```

### Struktur

```
<header>
<BLANK LINE>
<body>
<BLANK LINE>
<footer>
```

### Regler

1. **Header** (maks 50 tegn):
   - Bruk imperativ: "Add" ikke "Added"
   - Ikke slutt med punktum
   - Beskriv hva, ikke hvordan

2. **Body** (valgfritt):
   - Forklar hvorfor, ikke hva
   - Wrap ved 72 tegn
   - Bruk punktlister for flere endringer

3. **Footer** (valgfritt):
   - `Fixes #123`
   - `Relates to #456`
   - `Co-authored-by: Name <email>`

### Eksempler

```bash
# ✅ God
Add aurora forecast feature

Fetch aurora data from NOAA SWPC API
Støtt stedsbaserte spørringer (breddegrad/lengdegrad)
Add visualization with Kp-index scale
Cache results for 1 hour to reduce API calls

# ❌ Dårlig
added stuff

# ✅ God
Fix calendar sync for recurring events

Recurring events were not syncing because gcal_event_id
was not being stored after initial creation. Now we
store the ID and use it for subsequent updates.

Fixes #145

# ❌ Dårlig
fixed bug
```

---

## Pull Request-prosess

### 1. Før du starter

```bash
# Sjekk at master er oppdatert
git checkout master
git pull upstream master

# Lag feature-branch
git checkout -b feature/my-feature
```

### 2. Under utvikling

```bash
# Regelmessige commits
git add .
git commit -m "Add: beskrivelse"

# Push til din fork
git push origin feature/my-feature
```

### 3. Før PR

```bash
# Sjekk at koden er ren
flake8 features/my_feature.py

# Kjør tester
python3 tests/test_selfbot.py

# Sjekk syntaks
python3 -m py_compile features/my_feature.py

# Sjekk at du ikke har committet sensitive data
git diff --name-only  # Sjekk at .env ikke er med
```

### 4. Opprett PR

Gå til GitHub og opprett PR fra din fork til `Reedtrullz/inebotten-discord:master`.

**PR-malen skal fylles ut:**

```markdown
## Beskrivelse
Lagt til ny funksjon X som gjør Y.

## Endringstype
- [ ] Bug fix
- [x] Ny feature
- [ ] Breaking change
- [ ] Dokumentasjon

## Test
- [x] Testet lokalt
- [x] Lagt til enhetstester
- [ ] Testet i Discord

## Sjekkliste
- [x] Koden følger stilguiden
- [x] Jeg har gjennomgått koden selv
- [x] Dokumentasjon er oppdatert
- [ ] Tester passerer

## Sikkerhet
- [x] Ingen hardkodede tokens
- [x] Ingen passord i koden
```

### 5. Etter PR

- Svar på tilbakemeldinger raskt
- Gjør endringer i samme branch
- Force-push ikke etter review har startet

---

## Rapportere Bugs

Bruk [bug report template](../../issues/new?template=bug_report.md).

### God bug-rapport inneholder:

1. **Beskrivelse** - Hva skjedde?
2. **Reproduksjon** - Steg for å gjenskape
3. **Forventet** - Hva forventet du?
4. **Faktisk** - Hva skjedde faktisk?
5. **Miljø** - OS, Python-versjon, Discord.py-versjon
6. **Logger** - Relevante logglinjer

### Eksempel

```markdown
**Beskrivelse**
Botten krasjer når jeg prøver å legge til et gjentagende event.

**Reproduksjon**
1. Skriv: `@inebotten møte hver mandag kl 10`
2. Botten svarer ikke
3. Etter 10 sekunder krasjer run_both.py

**Forventet**
Event skal legges til med ukentlig gjentagelse.

**Faktisk**
Script krasjer med IndexError.

**Miljø**
- OS: Ubuntu 22.04
- Python: 3.10.6
- Discord.py: 2.3.0

**Logger**
```
[MONITOR] Matched: calendar command
[MONITOR] Error: list index out of range
Traceback (most recent call last):
  File "message_monitor.py", line 245, in process_message
    ...
IndexError: list index out of range
```
```

---

## Foreslå funksjoner

Bruk [malen for funksjonsønsker](../../issues/new?template=feature_request.md).

### Et godt funksjonsønske inneholder:

1. **Problem** - Hva er problemet du vil løse?
2. **Løsning** - Din foreslåtte løsning
3. **Alternativer** - Andre måter å løse det på
4. **Eksempel** - Hvordan ville det sett ut i bruk?

### Eksempel

```markdown
**Er funksjonsønsket relatert til et problem?**
Jeg glemmer alltid å sjekke været før jeg går ut.

**Beskriv løsningen**
Legg til "daglig værmelding" som sendes automatisk hver morgen.

**Alternativer**
- Manuell kommando: `@inebotten vær`
- Daglig oppsummering med vær inkludert

**Eksempel på bruk**
```
@inebotten aktiver daglig værmelding kl 07:00

# Hver morgen:
[Inebotten]: 🌤️ God morgen! I dag blir det 12°C og delvis skyet i Trondheim.
```
```

---

## Sikkerhet

**VIKTIG:** Aldri commit sensitive data!

### Sjekkliste før commit:

- [ ] Ingen Discord-tokens i koden
- [ ] Ingen passord eller API-nøkler
- [ ] Ingen `data/*.json` filer (brukerdata)
- [ ] Ingen `.env` fil
- [ ] Ingen Google client secrets

### Hvis du ved et uhell committet sensitiv data:

1. **Roter token umiddelbart** (endre passord/nullstill)
2. **Fjern fra git history**:
   ```bash
   git filter-branch --force --index-filter \
   'git rm --cached --ignore-unmatch FILENAME' HEAD
   git push origin --force --all
   ```
3. **Informer maintainer** hvis det var sentralt token

---

## Kommunikasjon

### Kanaler

- 💬 **GitHub Discussions** - Spørsmål, ideer, vis frem
- 🐛 **GitHub Issues** - Feil og funksjonsønsker
- 🔒 **Sikkerhet** - Sikkerhetsproblemer (ikke offentlig!)
  - Send e-post til: [your-email@example.com]

### Retningslinjer

- Vær respektfull og konstruktiv
- Aksepter at ikke alle ideer blir implementert
- Hjelp andre bidragsytere
- Spør hvis du er usikker

---

## Anerkjennelse

Bidragsytere vil bli lagt til i [README.md](../README.md) under en "Bidragsytere"-seksjon.

---

## Spørsmål?

- 📖 Les [dokumentasjonen](docs/DOCUMENTATION.md)
- 🏗️ Sjekk [arkitekturen](docs/ARCHITECTURE.md)
- 💬 Start en [diskusjon](../../discussions)

---

<p align="center">
Takk for at du bidrar! 🎉
</p>

<p align="center">
  <a href="docs/DOCUMENTATION.md">📖 Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="README.md">⬅️ Tilbake til README</a>
</p>
