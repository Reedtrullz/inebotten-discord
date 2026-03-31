# THORNode Tilbaketrekkingsovervåking

> Automatisk varsling når din bonded RUNE kan trekkes tilbake fra en THORNode

---

## 📋 Innholdsfortegnelse

1. [Oversikt](#oversikt)
2. [Hvordan Det Fungerer](#hvordan-det-fungerer)
3. [Oppsett](#oppsett)
4. [Når Kan Du Trekke Tilbake?](#når-kan-du-trekke-tilbake)
5. [Varsler](#varsler)
6. [Kommandoer](#kommandoer)
7. [Sikkerhetsvarsler](#sikkerhetsvarsler)
8. [Feilsøking](#feilsøking)

---

## Oversikt

Denne funksjonen overvåker statusen til en THORNode du har bondet RUNE til, og sender deg et varsel på Discord så snart noden går inn i en tilstand der du kan trekke tilbake din bonded RUNE.

**Hva den gjør:**
- 🔄 Poller THORChain API hvert 5. minutt (konfigurerbart)
- 🟢 Varsler når noden blir `Standby` og du kan unbond'e
- 🔴 Varsler ved API-svikt (overvåkingen er blind)
- 🔴 Varsler hvis bond-provider-adressen din forsvinner fra noden
- 💬 Gir deg nøyaktig UNBOND-memo du trenger for å trekke tilbake

---

## Hvordan Det Fungerer

### Arkitektur

```
┌─────────────────────────────────────────────────────────┐
│  Inebotten (kjører via run_both.py)                     │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Bakgrunnssløyfe (_thornode_poll_loop)            │  │
│  │                                                   │  │
│  │  1. Poll thornode.ninerealms.com                  │  │
│  │     /thorchain/node/{node_address}                │  │
│  │                                                   │  │
│  │  2. Sjekk API-helse (consecutive failures)        │  │
│  │     → Varsle hvis ≥ 6 feil på rad                 │  │
│  │                                                   │  │
│  │  3. Sjekk bond-provider                           │  │
│  │     → Varsle hvis adressen din mangler            │  │
│  │                                                   │  │
│  │  4. Sjekk withdrawal eligibility:                 │  │
│  │     • status == "Standby"                         │  │
│  │     • signer_membership == null/empty             │  │
│  │     • jail == empty                               │  │
│  │     • din bond > 0                                │  │
│  │     → Varsle hvis alle betingelser er oppfylt     │  │
│  │                                                   │  │
│  │  5. Deduplikasjon:                                │  │
│  │     • 6 timers cooldown mellom varsler            │  │
│  │     • Varsle på nytt hvis bond-beløp endres       │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Discord-kanal (THORNODE_ALERT_CHANNEL_ID)        │  │
│  │                                                   │  │
│  │  🟢 THORNode Withdrawal Alert                     │  │
│  │  Node: thor1abc...xyz                             │  │
│  │  Status: Standby                                  │  │
│  │  Your Bond: 15,000 RUNE                           │  │
│  │  To withdraw: UNBOND:thor1abc...:1500000000000    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Node Status Flyt

```
  Bonded → Whitelisted → Standby ←→ Ready ←→ Active
                            │                      │
                            │  Kan unbond'e        │  Kan IKKE unbond'e
                            │                      │
                            ▼                      ▼
                       Unbond/Leave          Churn out → Standby
```

Noden må være i **Standby**-tilstand for at du skal kunne trekke tilbake bond. Active og Ready noder kan ikke unbond'e.

---

## Oppsett

### 1. Legg til konfigurasjon i `.env`

Åpne filen i `~/.hermes/discord/.env` og legg til:

```bash
# THORNode-overvåking
THORNODE_ADDRESS=thor19uyg2vvsja9cfpejdj0c6pm7exfk87envj5s5h
THORNODE_BOND_PROVIDER=thor12mpnw4stg9fw8yngs3rpzzc6zdprepev3e0346
THORNODE_ALERT_CHANNEL_ID=1234567890
THORNODE_POLL_INTERVAL=300
```

| Variabel | Beskrivelse | Påkrevd |
|----------|-------------|---------|
| `THORNODE_ADDRESS` | THORNode-adressen du har bondet til | ✅ Ja |
| `THORNODE_BOND_PROVIDER` | Din THOR-adresse som bidro med bond | ✅ Ja |
| `THORNODE_ALERT_CHANNEL_ID` | Discord kanal-ID for varsler | ❌ Nei (varsler går til konsoll) |
| `THORNODE_POLL_INTERVAL` | Poll-intervall i sekunder (min 60) | ❌ Nei (default: 300) |

### 2. Finn Discord Kanal-ID

1. Aktiver utviklermodus i Discord (Innstillinger → Avansert → Utviklermodus)
2. Høyreklikk på kanalen du vil ha varsler i
3. Velg "Kopier ID"

### 3. Start Botten

```bash
python3 run_both.py
```

Du skal se denne meldingen ved oppstart:

```
[BOT] THORNode monitor active for thor19uyg2vvs...
```

Hvis konfigurasjon mangler:

```
[BOT] THORNode monitor not configured (set THORNODE_ADDRESS and THORNODE_BOND_PROVIDER in .env)
```

---

## Når Kan Du Trekke Tilbake?

### Betingelser for Tilbaketrekking

Du kan trekke tilbake din bonded RUNE når **alle** disse betingelsene er oppfylt:

| Betingelse | Beskrivelse |
|------------|-------------|
| `status == "Standby"` | Noden er ikke aktiv validator |
| `signer_membership` er tom/null | Noden er ikke del av vault-migrering |
| `jail` er tom | Noden er ikke fengslet |
| Din bond > 0 | Du har fortsatt bond på noden |

### Vanlige Tilstander

| Tilstand | Kan trekke tilbake? | Beskrivelse |
|----------|---------------------|-------------|
| **Standby** | ✅ Ja | Venter på churn, kan unbond'e |
| **Ready** | ❌ Nei | Oppfyller krav, klar for churn-in |
| **Active** | ❌ Nei | Aktiv validator |
| **Disabled** | N/A | Har brukt LEAVE, kan ikke bli med igjen |
| **Whitelisted** | ❌ Nei | Bondet men keys ikke satt |

### Hvordan Trekke Tilbake

Når du mottar varselet, send en transaksjon med følgende memo:

```
UNBOND:<node_address>:<beløp_i_tor>
```

Eksempel:
```
UNBOND:thor19uyg2vvsja9cfpejdj0c6pm7exfk87envj5s5h:1500000000000
```

Her er `1500000000000` = 15,000 RUNE (1 RUNE = 100,000,000 tor).

Varslet inneholder den ferdige memo-en klar til kopiering.

---

## Varsler

### 🟢 Withdrawal Alert

Sendes når noden er klar for tilbaketrekking:

```
🟢 **THORNode Withdrawal Alert**

**Node:** `thor19uyg2vv...envj5s5h`
**Status:** Standby
**Your Bond:** 15,000 RUNE

✅ You can now withdraw your bonded RUNE!

**To withdraw, send this memo:**
```UNBOND:thor19uyg2vvsja9cfpejdj0c6pm7exfk87envj5s5h:1500000000000```

📊 [View on Runescan](https://runescan.io/node/thor19uyg2vvsja9cfpejdj0c6pm7exfk87envj5s5h)
```

### Deduplikasjon

For å unngå spam:
- **6 timers cooldown** mellom withdrawal-varsler
- Varsler på nytt hvis **bond-beløpet endres** (f.eks. etter delvis unbond)
- Varsler kun ved **status-overgang** (Active → Standby)

---

## Kommandoer

### Sjekk Status Manuelt

```
@inebotten thornode
@inebotten withdraw
@inebotten bond status
@inebotten rune withdrawal
```

Svar:

```
🟢 **THORNode Status**

**Node:** `thor19uyg2vv...envj5s5h`
**Status:** Active
**Your Bond:** 15,000 RUNE
**Withdrawal:** Node is 'Active' (must be 'Standby' to unbond)

⚡ Slash points: 0

_Last checked: 14:32:05_
```

---

## Sikkerhetsvarsler

### 🔴 API-svikt

Hvis begge THORNode API-endepunktene (ninerealms og thorswap) er utilgjengelige i 6 påfølgende poll-sykluser, mottar du et varsel:

```
🔴 **THORNode Monitor Alert — API Failure**

**Node:** `thor19uyg2vv...envj5s5h`
**Consecutive failures:** 6

⚠️ Cannot reach THORNode API. The monitor may be blind to withdrawal events.

**Endpoints tried:**
- `https://thornode.ninerealms.com`
- `https://thornode.thorswap.net`

Check your internet connection or try a different API endpoint.
```

Dette betyr at overvåkingen er blind — du kan gå glipp av en withdrawal-mulighet.

**Reset:** Varselet resettes automatisk ved første vellykket API-kall.

### 🔴 Bond Provider Mangler

Hvis din bond-provider-adresse ikke finnes i nodens provider-liste:

```
🔴 **THORNode Monitor Alert — Bond Provider Missing**

**Node:** `thor19uyg2vv...envj5s5h`
**Expected provider:** `thor12mpnw4s...ev3e0346`
**Providers found:** 1

⚠️ Your bond provider address is NOT on this node. This means:
- Your bond may have been removed or slashed
- The node address may be wrong
- Your provider address may be wrong

**Current providers on node:**
- `thor1other11...11111111`

📊 [View on Runescan](https://runescan.io/node/thor19uyg2vvsja9cfpejdj0c6pm7exfk87envj5s5h)
```

Dette er et **kritisk varsel** — det kan bety at bond-en din er blitt slashed eller fjernet.

---

## Feilsøking

| Problem | Årsak | Løsning |
|---------|-------|---------|
| "THORNode monitor not configured" | Mangler THORNODE_ADDRESS eller THORNODE_BOND_PROVIDER i .env | Legg til begge variablene |
| Ingen varsler kommer | THORNODE_ALERT_CHANNEL_ID er feil | Sjekk kanal-ID med utviklermodus |
| "Channel not found" | Botten har ikke tilgang til kanalen | Inviter botten til kanalen eller sjekk ID |
| API-feil i konsoll | THORNode API er nede | Vent — fallback til thorswap brukes automatisk |
| Varsler kommer for ofte | Cooldown ble reset | Sjekk at state-filen ikke er slettet |
| Bond vises som 0 | Feil bond-provider-adresse | Verifiser adressen i .env |

### State-fil

Overvåkingen lagrer tilstand i:

```
~/.hermes/discord/thornode_state.json
```

Denne filen inneholder:
- Siste varsel-status
- Siste bond-beløp
- Cooldown-tidspunkt

**Slett denne filen** for å resette alle varsler og starte på nytt.

### Loggmeldinger

Se etter disse i konsoll-output:

```
[THORNODE] Alert sent to channel          # Varsel sendt til Discord
[THORNODE] Poll loop error: ...           # Feil i poll-sløyfen
[THORNODE] API returned 429 from ...      # Rate limit fra API
[THORNODE] Connection error to ...        # Tilkoblingsfeil
[THORNODE] Withdrawal eligible but no alert channel configured  # Mangler kanal-ID
```

---

## API-endepunkter

| Endpoint | Bruk | Fallback |
|----------|------|----------|
| `https://thornode.ninerealms.com/thorchain/node/{address}` | Primær | `https://thornode.thorswap.net/thorchain/node/{address}` |

Begge endepunktene prøves sekvensielt. Hvis primær feiler, prøves fallback automatisk.

---

<p align="center">
  <a href="QUICK_REFERENCE.md">📋 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="DOCUMENTATION.md">📖 Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
