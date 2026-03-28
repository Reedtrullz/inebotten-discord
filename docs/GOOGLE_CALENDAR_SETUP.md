# Google Calendar Integration for Inebotten

Botten kan nå integrere med Google Calendar! Dette lar deg:
- Se kommende arrangementer fra Google Calendar
- Synkronisere lokale arrangementer til Google Calendar

## Kommandoer

| Kommando | Beskrivelse |
|----------|-------------|
| `@inebotten google calendar` | Vis kommende arrangementer fra Google Calendar |
| `@inebotten gcal` | Kortversjon av over |
| `@inebotten sync til google` | Sync alle lokale arrangementer til Google Calendar |

## Oppsett (Engangssak)

For å koble boten til Google Calendar må du sette opp OAuth:

### Steg 1: Google Cloud Console

1. Gå til https://console.cloud.google.com/apis/credentials
2. Opprett et nytt prosjekt (eller bruk eksisterende)
3. Klikk **"Enable APIs and Services"**
4. Søk etter og aktiver:
   - **Google Calendar API**
5. Gå til **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
6. Velg **Application type: Desktop app**
7. Klikk **Create**, deretter **Download JSON**

### Steg 2: Autentisering

Kjør setup-scriptet fra Hermes:

```bash
python ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --client-secret /path/to/client_secret.json
```

Deretter får du en URL å åpne i nettleseren:

```bash
python ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --auth-url
```

1. Åpne URLen i nettleseren
2. Logg inn med Google-kontoen som har kalenderen du vil dele
3. Godkjenn tilgangen
4. Kopier URLen du blir redirectet til (viser kanskje feilside, det er normalt)
5. Fullfør med:

```bash
python ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --auth-code "KLE_INN_URLEN_HER"
```

### Steg 3: Verifiser

```bash
python ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --check
```

Skal vise: `AUTHENTICATED`

## Passkeys

Du nevnte at du bruker passkey for Google. Dette skal funke fint med OAuth - du logger inn på vanlig måte i nettleseren under autentiseringssteget.

## Deling med venner

Hvis kalenderen skal deles med venner:
1. I Google Calendar, klikk på "My calendars" → din kalender → "Settings and sharing"
2. Under "Share with specific people", legg til vennenes Gmail-adresser
3. Velg passende rettigheter ("See all event details" eller "Make changes to events")

## Tester

Etter oppsett, test med:
```
@inebotten google calendar
```

Boten skal da vise kommende arrangementer fra din Google Calendar.
