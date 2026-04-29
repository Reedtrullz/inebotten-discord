# Inebotten - Hurtigreferanse

> En rask oversikt over alle kommandoer og funksjoner

---

## 🚀 Komme i Gang

Inebotten er mention-gated: hun ser og svarer bare på meldinger der hun er eksplisitt tagget, også i DM og gruppe-DM.

### Starte Botten

```bash
# 1. Kjør interaktivt oppsett (anbefalt)
python3 setup.py

# 2. Start botten
python3 run_both.py
```

### Web Console

Når botten kjører er dashbordet tilgjengelig på `http://localhost:8080` (eller det konfigurerte domenet på VPS).

1. Åpne URL i nettleser
2. Logg inn med API-nøkkelen (vises i oppstartsloggen som `Console API key: q9oAYGbb...`)
3. Dashboard viser bot-status, bridge, kalender, avstemninger og sanntidslogger

For API-tilgang: send `X-API-Key`-headeren med samme nøkkel.

---

## 📅 Kalenderkommandoer

### Opprette Kalender-element

> Du trenger ikke lære kommandoer - bare skriv som du snakker!

```
@inebotten møte med Ola i morgen kl 14
@inebotten husk "Viktig møte" på lørdag kl 10:00
@inebotten "RBK - Bodø/Glimt" — 12.04 kl 18:30
@inebotten lunsj hver fredag kl 12
@inebotten bursdag til mamma 15.05 hvert år
@inebotten tannlege neste tirsdag kl 09:00
@inebotten test imårra kl 13:37
@inebotten møte 15. mai kl 10:00
@inebotten regninger den 5. hver måned
@inebotten julebord 20 desember
```

### Se Liste

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten kalender` | Vis alle kommende hendelser (90 dager) | `@inebotten kalender` |
| `@inebotten søk [tittel]` | Søk etter hendelser | `@inebotten søk møte` |

### Redigere

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten endre [nummer] [felter]` | Endre hendelse | `@inebotten endre 1 tittel: Ny tittel dato: 15.05 kl 14` |

### Slette

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten slett [nummer]` | Slett hendelse etter nummer | `@inebotten slett 2` |
| `@inebotten slett [tittel]` | Slett første treff på delvis tittel | `@inebotten slett spaghetti` |
| `@inebotten slett alle [tittel]` | Slett ALLE treff | `@inebotten slett alle spaghetti` |
| `@inebotten slett alt` / `@inebotten fjern alt` | Slett alt (krever bekreftelse) | `@inebotten slett alt` |

### Fullføre

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten ferdig [nummer]` | Marker som fullført | `@inebotten ferdig 2` |
| `@inebotten ferdig [tittel]` | Fullfør første treff på delvis tittel | `@inebotten ferdig meldekort` |
| `@inebotten ferdig alle [tittel]` | Fullfør ALLE treff | `@inebotten ferdig alle meldekort` |

### Gjentagende Oppføringer

Gjentagende elementer (`hver uke`, `annenhver uke`, `hver måned`, `hvert år`) blir ikke slettet når du fullfører dem - de flyttes til neste dato. Bruk `slett` for å fjerne dem permanent.

### 🌍 Delt Kalender

Inebotten bruker nå **én felles kalender** for alle dine kanaler, grupper og DMs. Det betyr at en avtale du legger til i en DM vil være synlig når du skriver `@inebotten kalender` i en gruppechat, og omvendt.

### 💡 Tips for presisjon

Hvis du vil sikre at botten forstår nøyaktig hva som er tittelen på arrangementet ditt, sett det i hermetegn:
`@inebotten husk "Fisketur med gjengen" i morgen kl 08:00`

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

### Påminnelser (Automatisk)

Boten sender automatisk påminnelser når kalender-elementer nærmer seg:

- **30 minutter før:** Boten pinger deg i kanalen der elementet ble opprettet
- **Dagens Briefing kl 09:00:** Boten poster dagens plan, vær, markedsoppdatering og bursdager.

Du trenger ikke be om påminnelser - de skjer automatisk!

---

## 🔔 Påminnelser

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten påminnelse [tekst] om [tid]` | Opprett påminnelse | `@inebotten påminnelse Ring lege om 2 timer` |
| `@inebotten påminnelser` | Vis aktive påminnelser | `@inebotten påminnelser` |
| `@inebotten endre påminnelse [nummer] [felt]` | Endre påminnelse | `@inebotten endre påminnelse 1 om 1 time` |
| `@inebotten slett påminnelse [nummer]` | Slett påminnelse | `@inebotten slett påminnelse 1` |
| `@inebotten søk påminnelse [tekst]` | Søk etter påminnelse | `@inebotten søk påminnelse lege` |

## 🌦️ Vær

| Kommando | Beskrivelse |
|----------|-------------|
| `@inebotten vær` | Værmelding for din lokasjon |
| `@inebotten været i [sted]` | Vær for spesifikt sted |
| `@inebotten Jeg bor i [sted]` | Lagre din faste lokasjon (for brief/dashboard) |

**Eksempel:**
```
@inebotten Jeg bor i Trondheim
@inebotten vær
```

---

## 📊 Avstemninger

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten avstemning [tittel]? [alt1], [alt2]` | Lag avstemning | `@inebotten avstemning Pizza eller burger? Pepperoni, Margherita, Kebab` |
| `@inebotten stem [nummer]` | Stem på alternativ | `@inebotten stem 1` |
| `@inebotten polls` | Vis aktive avstemninger | `@inebotten polls` |
| `@inebotten endre poll [nummer]` | Endre avstemning | `@inebotten endre poll 1` |
| `@inebotten slett poll [nummer]` | Slett avstemning | `@inebotten slett poll 1` |
| `@inebotten lukk poll [nummer]` | Lukk avstemning | `@inebotten lukk poll 1` |

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

## 💬 Sitater

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten sitat` | Tilfeldig sitat | `@inebotten sitat` |
| `@inebotten sitater` | Vis alle sitater | `@inebotten sitater` |
| `@inebotten endre sitat [nummer] [felt]` | Endre sitat | `@inebotten endre sitat 1 tekst: Ny tekst forfatter: Ola` |
| `@inebotten slett sitat [nummer]` | Slett sitat | `@inebotten slett sitat 1` |

## 📺 Watchlist

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten watchlist` | Vis watchlist | `@inebotten watchlist` |
| `@inebotten watchlist [ticker]` | Legg til ticker | `@inebotten watchlist AAPL` |
| `@inebotten endre watchlist [nummer] [ticker]` | Endre ticker | `@inebotten endre watchlist 1 TSLA` |
| `@inebotten fjern watchlist [nummer]` | Fjern ticker | `@inebotten fjern watchlist 1` |

## 🎂 Bursdager

| Kommando | Beskrivelse | Eksempel |
|----------|-------------|----------|
| `@inebotten bursdag [navn] [dato]` | Legg til bursdag | `@inebotten bursdag Ola 15.05` |
| `@inebotten endre bursdag [navn] [dato]` | Endre bursdag | `@inebotten endre bursdag Ola 20.05` |
| `@inebotten bursdager` | Vis bursdager | `@inebotten bursdager` |

## 🌟 Annet

| Kommando | Beskrivelse |
|----------|-------------|
| `@inebotten dagens ord` | Norsk ord med definisjon |
| `@inebotten daglig oppsummering` | Omfattende briefing (Vær, marked, kalender) |
| `@inebotten kompliment` | Send et kompliment |
| `@inebotten shorten [url]` | Forkort en URL |
| `@inebotten nordlys` | Nordlysvarsel (Aurora) |

---

## 👤 Profilhåndtering

| Kommando | Eksempel | Beskrivelse |
|----------|----------|-------------|
| `@inebotten status` | `@inebotten status` | Bot-helse og driftstatus |
| `@inebotten status [s]` | `@inebotten status dnd` | online, idle, dnd, invisible |
| `@inebotten spiller [t]` | `@inebotten spiller CS2` | Endre aktivitet |
| `@inebotten ser på [t]` | `@inebotten ser på Netflix` | Endre aktivitet |

---

## 🩺 Drift

| Kommando | Eksempel | Beskrivelse |
|----------|----------|-------------|
| `@inebotten bot status` | `@inebotten bot status` | Vis uptime, AI-status, handlers og rate-limit |
| `@inebotten health` | `@inebotten health` | Kort helsesjekk for botten |

På VPS brukes systemd og Docker Compose:

```bash
sudo systemctl status inebotten-webhook.service --no-pager
sudo systemctl status inebotten-update.timer --no-pager
sudo tail -f /var/log/inebotten-autoupdate.log
sudo docker compose ps
```

Se [VPS_DEPLOYMENT.md](VPS_DEPLOYMENT.md) for auto-update-oppsett.

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
| Google Calendar Token | `~/.hermes/google_token.json` |
| Konfigurasjon | `.env` (i prosjektmappen) |

---

## 🔧 Feilsøking

| Problem | Løsning |
|---------|---------|
| Botten svarer ikke | Sjekk at `run_both.py` kjører uten feil |
| AI svarer ikke | Sjekk at LM Studio kjører på Windows |
| GCal sync feiler | Sjekk at token ikke er utløpt (`~/.hermes/google_token.json`) |
| "Fant ikke nummer" | Bruk `@inebotten kalender` først for å se numre |
| "Ugyldig token" | Hent ny token fra Discord (F12 > Application > Local Storage) |
| Påminnelser kommer ikke | Sjekk at `reminder_checker.py` logger ved oppstart (`[REMIND] Reminder checker started`) |
| Ingen morgen-digest | Opprett minst 1 arrangement for dagen via boten |

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
