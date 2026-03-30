# Inebotten - Hurtigreferanse

> En rask oversikt over alle kommandoer og funksjoner

---

## 🚀 Komme i Gang

### Starte Botten

```bash
# Alt sammen (anbefalt)
python3 run_both.py

# Eller separat:
python3 hermes_bridge_server.py  # Terminal 1 - AI-bridge
python3 selfbot_runner.py        # Terminal 2 - Discord-bot
```

---

## 📅 Kalenderkommandoer

### Grunnleggende

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten kalender` | Vis alle kommende hendelser | `@inebotten kalender` |
| `@inebotten kalender [dager]` | Vis neste N dager | `@inebotten kalender 7` |
| `@inebotten ferdig [nummer]` | Marker som fullført | `@inebotten ferdig 2` |
| `@inebotten slett [nummer]` | Slett hendelse | `@inebotten slett 3` |
| `@inebotten sync` | Synkroniser med Google Calendar | `@inebotten sync` |

### Naturlig Språk

> Du trenger ikke lære kommandoer - bare skriv som du snakker!

```
@inebotten møte med Ola i morgen kl 14
@inebotten husk å ringe mamma på lørdag
@inebotten RBK-kamp 12.04 kl 18:30
@inebotten lunsj hver fredag kl 12
@inebotten bursdag til mamma 15.05 hvert år
@inebotten tannlege neste tirsdag kl 09:00
@inebotten test imårra kl 13:37
@inebotten møte 15. mai kl 10:00
@inebotten regninger den 5. hver måned
@inebotten julebord 20 desember
```

### Nøkkelord for Datoer

| Nøkkelord | Betydning | Eksempel |
|-----------|-----------|----------|
| `i dag`, `idag` | I dag | `@inebotten møte i dag kl 14` |
| `i morgen`, `imorgen`, `imårra` | I morgen | `@inebotten test imårra` |
| `i overmorgen` | I overmorgen | `@inebotten avtale i overmorgen` |
| `på mandag` | Neste mandag | `@inebotten møte på mandag kl 10` |
| `neste tirsdag` | Neste tirsdag | `@inebotten tannlege neste tirsdag` |
| `den 25.03` | 25. mars | `@inebotten frist den 25.03` |
| `15. mai` | 15. mai (månedsnavn) | `@inebotten møte 15. mai kl 14` |
| `den 5.` | Den 5. (daglig) | `@inebotten regninger den 5. hver måned` |
| `20 desember` | 20. desember | `@inebotten julebord 20 desember` |

### Statusikoner

| Ikon | Betydning |
|------|-----------|
| 📅 | Synkronisert med Google Calendar |
| 📌 | Kun lokalt |
| ✓ | Fullført |
| 🔄 | Gjentagende |

---

## 🌦️ Vær

| Kommando | Beskrivelse |
|----------|-------------|
| `@inebotten vær` | Værmelding for din lokasjon |
| `@inebotten været i [sted]` | Vær for spesifikt sted |

**Eksempel:**
```
@inebotten været i Trondheim
```

---

## 📊 Avstemninger

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten avstemning [tittel]? [alt1], [alt2]` | Lag avstemning | `@inebotten avstemning Pizza eller burger? Pepperoni, Margherita, Kebab` |
| `@inebotten stem [nummer]` | Stem på alternativ | `@inebotten stem 1` |
| `@inebotten resultat` | Se resultater | `@inebotten resultat` |

---

## ⏱️ Nedtellinger

| Kommando | Eksempel |
|----------|----------|
| `@inebotten nedtelling til [dato]` | `@inebotten nedtelling til 17. mai` |
| `@inebotten nedtelling til [hendelse]` | `@inebotten nedtelling til julaften` |

---

## 💰 Krypto

| Kommando | Eksempel |
|----------|----------|
| `@inebotten pris [symbol]` | `@inebotten pris BTC` |

Støttede symboler: BTC, ETH, SOL, ADA, XRP, DOGE, m.fl.

---

## 🧮 Kalkulator

| Kommando | Eksempel |
|----------|----------|
| `@inebotten kalk [uttrykk]` | `@inebotten kalk (100 * 1.25) / 2` |

---

## 🔮 Horoskop

| Kommando | Eksempel |
|----------|----------|
| `@inebotten horoskop [stjernetegn]` | `@inebotten horoskop væren` |

Stjernetegn: væren, tyren, tvillingene, kreften, løven, jomfruen, vekten, skorpionen, skytten, steinbukken, vannmannen, fiskene

---

## 🌟 Annet

| Kommando | Beskrivelse |
|----------|-------------|
| `@inebotten sitat` | Tilfeldig inspirerende sitat |
| `@inebotten dagens ord` | Norsk ord med definisjon |
| `@inebotten kompliment` | Send et kompliment |
| `@inebotten shorten [url]` | Forkort en URL |

---

## 💬 Chatting

> Bare nev @inebotten og snakk naturlig!

```
@inebotten Hei! Hvordan går det?
@inebotten Hva synes du om RBK?
@inebotten Fortell en vits
@inebotten Hva er meningen med livet?
```

---

## 📁 Filplasseringer

| Data | Plassering |
|------|------------|
| Kalender | `~/.hermes/discord/data/calendar.json` |
| Brukerminne | `~/.hermes/discord/data/user_memory.json` |
| Google Calendar Token | `~/.gcal_token.pickle` |
| Konfigurasjon | `.env` (i prosjektmappen) |

---

## 🔧 Feilsøking

| Problem | Løsning |
|---------|---------|
| Botten svarer ikke | Sjekk at `run_both.py` kjører uten feil |
| AI svarer ikke | Sjekk at LM Studio kjører på Windows |
| GCal sync feiler | Kjør `python3 sync_calendar_to_gcal.py` |
| "Fant ikke nummer" | Bruk `@inebotten kalender` først for å se numre |
| "Ugyldig token" | Hent ny token fra Discord (F12 > Application > Local Storage) |

---

## 🆘 Få Hjelp

- 📖 [Full dokumentasjon](DOCUMENTATION.md)
- 🏗️ [Arkitektur](ARCHITECTURE.md)
- 🐛 [Rapporter bug](../../issues/new?template=bug_report.md)
- 💡 [Foreslå feature](../../issues/new?template=feature_request.md)

---

<p align="center">
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
