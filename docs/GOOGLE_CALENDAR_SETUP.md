# Google Calendar Oppsett

> Steg-for-steg guide for å koble Inebotten til Google Calendar

---

## 📋 Innholdsfortegnelse

1. [Oversikt](#oversikt)
2. [Forutsetninger](#forutsetninger)
3. [Steg 1: Google Cloud Console](#steg-1-google-cloud-console)
4. [Steg 2: OAuth-oppsett](#steg-2-oauth-oppsett)
5. [Steg 3: Autentisering](#steg-3-autentisering)
6. [Steg 4: Test](#steg-4-test)
7. [Dele Kalenderen](#dele-kalenderen)
8. [Feilsøking](#feilsøking)

---

## Oversikt

Med Google Calendar-integrasjon kan Inebotten:

- 📅 **Vise** kommende arrangementer fra Google Calendar
- 🔄 **Synkronisere** lokale arrangementer til Google Calendar
- 📌 **Se status** - 📅 for synkronisert, 📌 for kun lokalt
- ✏️ **Oppdatere** arrangementer begge veier

---

## Forutsetninger

- Google-konto
- Tilgang til [Google Cloud Console](https://console.cloud.google.com)
- Inebotten installert og kjørende

---

## Steg 1: Google Cloud Console

### 1.1 Opprett Prosjekt

1. Gå til [Google Cloud Console](https://console.cloud.google.com)
2. Klikk prosjekt-velgeren øverst:
   ```
   ┌─────────────────────────────┐
   │  🔽 Velg et prosjekt        │
   └─────────────────────────────┘
   ```
3. Klikk **"Nytt prosjekt"**
4. Gi prosjektet et navn, f.eks. `inebotten-calendar`
5. Klikk **"Opprett"**

### 1.2 Aktiver API

1. Gå til **"APIer og tjenester"** > **"Bibliotek"**
2. Søk etter **"Google Calendar API"**
3. Klikk på den og trykk **"Aktiver"**

   ```
   ┌────────────────────────────────────┐
   │  ✅ Google Calendar API            │
   │     Status: AKTIVERES              │
   └────────────────────────────────────┘
   ```

---

## Steg 2: OAuth-oppsett

### 2.1 Lag OAuth-bruker

1. Gå til **"APIer og tjenester"** > **"OAuth-brukere"**
2. Klikk **"+ OPPRETT BRUKER"**
3. Velg **"Eksternt"** (hvis du vil dele med venner)
   - Eller "Internt" for kun personlig bruk

   ```
   ┌─────────────────────────────────────┐
   │  Brukertype:                        │
   │  ○ Internt  ●Eksternt               │
   │                                     │
   │  [Fortsett]                         │
   └─────────────────────────────────────┘
   ```

4. Fyll ut app-informasjon:
   - **App-navn:** `Inebotten Calendar`
   - **Brukerstøtte-e-post:** (din e-post)
   - **App-logo:** (valgfritt)
   - **Domene:** (kan være tomt)
   - **Utviklerkontakt:** (din e-post)

5. Klikk **"Lagre og fortsett"**

### 2.2 Legg til Scopes

1. Klikk **"Legg til eller fjern scopes"**
2. Søk etter **"Calendar"**
3. Velg:
   - ✅ `.../auth/calendar` - "Se, rediger, dele og slette alle kalendere"
   - ✅ `.../auth/calendar.events` - "Se, redigere, slette kalenderarrangementer"

   ```
   ┌────────────────────────────────────────┐
   │  ✅ /auth/calendar                     │
   │  ✅ /auth/calendar.events              │
   │                                        │
   │  [Oppdater]                            │
   └────────────────────────────────────────┘
   ```

4. Klikk **"Oppdater"** og deretter **"Lagre og fortsett"**

### 2.3 Legg til Testbrukere

1. Under **"Testbrukere"**, klikk **"+ LEGG TIL BRUKERE"**
2. Legg til din e-postadresse
3. Klikk **"Lagre og fortsett"**

### 2.4 Opprett Credentials

1. Gå til **"APIer og tjenester"** > **"Credentials"**
2. Klikk **"+ OPPRETT CREDENTIALS"** > **"OAuth client ID"**
3. Velg **"Applikasjonstype: Desktop-app"**
4. Gi den et navn: `Inebotten Desktop`
5. Klikk **"Opprett"**
6. Klikk **"Last ned JSON"** i popup-vinduet

   ```
   ┌─────────────────────────────────────┐
   │  ✅ OAuth-client opprettet          │
   │                                     │
   │  [LAST NED JSON]                   │
   └─────────────────────────────────────┘
   ```

7. Lagre filen som `credentials.json` i riktig Hermes data-mappe:
   - Lokal kjøring: `~/.hermes/credentials.json`
   - Docker/VPS: `/opt/apps/inebotten-discord/data/credentials.json`

---

## Steg 3: Autentisering

Google-tokenet må lagres i den samme persistente data-mappen som botten bruker
ved restart. I Docker/VPS er `./data` montert som `/home/inebotten/.hermes` i
containeren, så host-stien er `/opt/apps/inebotten-discord/data`.

### 3.1 Start OAuth-flyt

```bash
# Alternativ A: via Discord
@inebotten kalender auth

# Alternativ B: via terminal fra prosjektmappen
python3 scripts/auth_gcal.py

# Alternativ C: via terminal på VPS/Docker-host
HERMES_HOME=/opt/apps/inebotten-discord/data python3 scripts/auth_gcal.py --no-browser
```

### 3.2 Godkjenn i Nettleser

1. Botten eller skriptet viser en Google OAuth-URL:
   ```
   ===========================================
   Åpne denne URLen i nettleseren:
   
   https://accounts.google.com/o/oauth2/auth?...
   
   Godkjenn tilgang og kopier redirect-URLen
   ===========================================
   ```

2. **Åpne URLen** i nettleseren
3. **Logg inn** med Google-kontoen som har kalenderen
4. **Godkjenn** tilgangen:
   ```
   ┌─────────────────────────────────────┐
   │  Inebotten Calendar ønsker å:       │
   │                                     │
   │  ✅ Se kalenderne dine              │
   │  ✅ Administrere kalenderne dine    │
   │                                     │
   │  [Tillat]                           │
   └─────────────────────────────────────┘
   ```

5. Du vil bli redirected til `localhost` (feilside er normalt!)
6. **Kopier koden** fra redirecten eller terminalflyten

### 3.3 Fullfør Autentisering

1. Hvis du bruker Discord-flyten, send koden tilbake:
   ```
   @inebotten kalender auth 4/0Ab...
   ```
   Hvis du bruker `scripts/auth_gcal.py`, limer du inn koden i terminalen.

2. Skriptet vil bekrefte:
   ```
   ✅ Autentisering vellykket!
   Token lagret i: ~/.hermes/google_token.json
   ```
   På VPS skal tilsvarende sti være:
   ```
   /opt/apps/inebotten-discord/data/google_token.json
   ```

---

## Steg 4: Test

### 4.1 Verifiser Oppsett

```bash
python3 scripts/auth_gcal.py --no-browser
```

På VPS:

```bash
cd /opt/apps/inebotten-discord
HERMES_HOME=/opt/apps/inebotten-discord/data python3 scripts/auth_gcal.py --no-browser
```

Hvis tokenet finnes og kan friskes opp, skriver skriptet at eksisterende token ble funnet eller oppdatert. Du kan også kjøre `@inebotten synk kalender` i Discord for å teste en faktisk sync.

### 4.2 Test i Discord

1. Start botten:
   ```bash
   python3 run_both.py
   ```

2. I Discord, skriv:
   ```
   @inebotten google calendar
   ```

3. Botten skal vise:
   ```
   📅 Kommende arrangementer:
   
   1. 📅 Møte med Ola - 25.03 kl 14:00
      └─ [Åpne i Google Calendar](link)
   ```

### 4.3 Test Synkronisering

1. Legg til et arrangement:
   ```
   @inebotten test-møte i morgen kl 10
   ```

2. Sync til Google:
   ```
   @inebotten sync til google
   ```

3. Sjekk i [Google Calendar](https://calendar.google.com)
   - Arrangementet skal vises der!

---

## Dele Kalenderen

### Med Venner

Hvis kalenderen skal deles med venner:

1. Gå til [Google Calendar](https://calendar.google.com)
2. Finn **"Mine kalendere"** på venstre side
3. Hold musen over din kalender → klikk **⋮** → **"Innstillinger og deling"**
4. Under **"Del med bestemte personer"**:
   - Klikk **"+ Legg til personer"**
   - Skriv inn vennens Gmail-adresse
   - Velg rettigheter:
     - **"Se alle eventdetaljer"** - kan se alt
     - **"Gjøre endringer på events"** - kan redigere
   - Klikk **"Send"**

   ```
   ┌─────────────────────────────────────┐
   │  Del med: venn@example.com          │
   │  Rettigheter: Se alle detaljer      │
   │                                     │
   │  [✉️ Send invitasjon]               │
   └─────────────────────────────────────┘
   ```

### Offentlig Tilgang

⚠️ **Advarsel:** Dette gjør kalenderen synlig for alle!

1. I kalender-innstillinger, under **"Tilgang tillatt for"**
2. Sjekk **"Gjør tilgjengelig for offentligheten"**
3. Velg **"Se kun ledig/opptatt (skjul detaljer)"** eller **"Se alle eventdetaljer"**

---

## Feilsøking

### Vanlige Problemer

| Problem | Årsak | Løsning |
|---------|-------|---------|
| "Uautorisert" | Token mangler, er utløpt, eller ligger i feil mappe | Kjør setup med riktig `HERMES_HOME` |
| "Invalid client" | Feil client_secret | Sjekk at riktig JSON er lastet ned |
| "Access denied" | Ikke testbruker | Legg til e-post i testbrukere |
| "Scope insufficient" | Manglende tillatelser | Sjekk at calendar-scopes er valgt |
| "localhost refused" | Normalt! | Kopier URLen likevel |
| Kalender vises ikke | Feil konto | Sjekk at du logget inn med riktig Google-konto |
| Må autorisere etter hver restart | Tokenet ble lagret utenfor persistent Docker-data | Legg `credentials.json` i `/opt/apps/inebotten-discord/data` og kjør auth med `HERMES_HOME=/opt/apps/inebotten-discord/data` |

### Nullstill Autentisering

```bash
# Slett token
rm ~/.hermes/google_token.json

# Kjør setup på nytt
python3 scripts/auth_gcal.py
```

På VPS:

```bash
rm /opt/apps/inebotten-discord/data/google_token.json
cd /opt/apps/inebotten-discord
HERMES_HOME=/opt/apps/inebotten-discord/data python3 scripts/auth_gcal.py --no-browser
```

### Sjekk Token

```python
python3 -c "
from google.oauth2.credentials import Credentials
creds = Credentials.from_authorized_user_file(
    '~/.hermes/google_token.json',
    ['https://www.googleapis.com/auth/calendar']
)
print(f'Valid: {creds.valid}')
print(f'Expired: {creds.expired}')
print(f'Scopes: {creds.scopes}')
"
```

### Debug Logging

Legg til i din kode:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Sikkerhetsnotater

- 🔐 **Token lagres lokalt** i `~/.hermes/google_token.json`
- 🔐 **OAuth-client lagres lokalt** i `~/.hermes/credentials.json`
- 🔐 **Docker/VPS-token lagres persistent** i `/opt/apps/inebotten-discord/data/google_token.json`
- 🔐 **Docker/VPS OAuth-client lagres persistent** i `/opt/apps/inebotten-discord/data/credentials.json`
- 🔐 **Ikke del token-filen** - gir full tilgang til kalenderen
- 🔐 **Bruk .gitignore** - token-filen skal aldri committes
- 🔐 **Regelmessig rotasjon** - slett og opprett nytt token årlig

---

<p align="center">
  <a href="DOCUMENTATION.md">📖 Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="QUICK_REFERENCE.md">📋 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
