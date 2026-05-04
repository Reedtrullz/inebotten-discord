# Sikkerhetspolicy

> Hvordan vi håndterer sikkerhet i Inebotten-prosjektet

---

## 📋 Innholdsfortegnelse

1. [Støttede Versjoner](#støttede-versjoner)
2. [Rapportere Sårbarheter](#rapportere-sårbarheter)
3. [Sikkerhetshensyn for Brukere](#sikkerhetshensyn-for-brukere)
4. [Beste praksis](#beste-praksis)
5. [Token-lekkasje](#token-lekkasje)
6. [Sikkerhetsfunksjoner](#sikkerhetsfunksjoner)

---

## Støttede Versjoner

| Versjon | Støttet | Status |
|---------|---------|--------|
| 2.x | ✅ | Aktiv utvikling |
| 1.x | ❌ | Ikke lenger støttet |

Vi gir sikkerhetsoppdateringer kun for den nyeste major-versjonen.

---

## Rapportere Sårbarheter

### ⚠️ Viktig

**Ikke rapporter sikkerhetsproblemer i offentlige issues!**

Dette gir angripere tid til å utnytte problemet før det er fikset.

### Hvordan rapportere

1. **Send e-post til:** [your-email@example.com]
2. **Emne:** `[SECURITY] Kort beskrivelse`
3. **Innhold:**
   - Beskrivelse av sårbarheten
   - Hvordan gjenskape (hvis mulig)
   - Potensiell innvirkning
   - Forslag til fiks (hvis du har)

### Hva som skjer

1. **0-48 timer** - Vi bekrefter mottak
2. **1 uke** - Vi vurderer alvorlighetsgrad
3. **2-4 uker** - Vi utvikler fiks (avhengig av kompleksitet)
4. **Før release** - Vi koordinerer offentliggjøring
5. **Etter release** - Du får kreditering (hvis ønsket)

---

## Sikkerhetshensyn for Brukere

### ⚠️ Vigtig Advarsel

**Discord selfbots er mot [Discord's Terms of Service](https://discord.com/terms).**

Bruk av denne programvaren kan resultere i:
- ❌ Konto-terminering
- ❌ IP-ban
- ❌ Tap av data

**Bruk på egen risiko.**

### Anbefalinger for Trygg Bruk

#### 1. Bruk Dedikert Konto

**Aldri** kjør selfbot på din hoved-Discord-konto!

```
❌ Galt: Din personlige konto
✅ Riktig: Separat konto kun for botten
```

#### 2. Hold Tokens Hemmelig

Tokens er som passord - aldri del dem!

```bash
# ✅ Riktig - i .env-fil
DISCORD_TOKEN=MTQ3ND...your_token

# ❌ Galt - i koden
discord_token = "MTQ3ND..."
```

#### 3. Konservative Rate Limits

Standardinnstillinger er konservative:

```env
# .env
MAX_MSGS_PER_SEC=5      # Maks 5 meldinger per sekund
DAILY_QUOTA=10000       # Maks 10 000 meldinger per dag
SAFE_INTERVAL=1         # Minst 1 sekund mellom meldinger
```

**Ikke øke disse!**

#### 4. Kun Svar Ved Mention

Botten er konfigurert til å kun behandle meldinger når @inebotten blir eksplisitt nevnt. Dette gjelder også DM og gruppe-DM. Untagged meldinger skal ikke logges, routes, lagres i minne, sendes til AI eller brukes i digest.

```python
# I message_monitor.py
def is_mention(self, message):
    """Check if message explicitly mentions the bot."""
    ...
```

Dette reduserer synlighet og risiko.

#### 5. Overvåk Logger

Se etter uvanlig aktivitet:

```bash
# Kjør med logging
tail -f ~/.hermes/discord/bot.log | grep -i "error\|warning\|rate"
```

#### 6. Hold Oppdatert

```bash
# Sjekk for oppdateringer daglig
git pull origin master

# Les changelog før oppdatering
git log --oneline -5
```

På VPS kan dette automatiseres med GitHub Actions + GHCR + Ansible (se [VPS_DEPLOYMENT.md](VPS_DEPLOYMENT.md)).

For legacy webhook-basert auto-update (kun for enkelt-app VPS, IKKE anbefalt for multi-app):
- Bruk en GitHub webhook secret.
- Ikke commit `/etc/inebotten-webhook.env`, `.env`, tokens eller `data/`.
- Ikke gjør manuelle kodeendringer i `/opt/inebotten-discord`; auto-update bruker `git reset --hard origin/master`.
- Sjekk `/var/log/inebotten-autoupdate.log` etter feil.
- Ikke eksponer webhook-port 9000 offentlig med mindre du bruker legacy-metoden.

---

## Beste praksis

### Fil-beskyttelse

```bash
# Disse skal ALDRI committes til git
.env                    # Discord token, API-nøkler
.env.local             # Lokale overrides
data/                  # All kjøredata, tokens, minne
data/tokens.json       # Bruker-tokens
data/user_memory.json  # Personlig data
data/calendar.json     # Personlig data
data/client_secret*.json  # Google credentials
*.log                  # Loggfiler

# API-nøkler (ALDRI commit)
OPENROUTER_API_KEY     # OpenRouter
TAVILY_API_KEY         # Tavily search
BROWSERBASE_API_KEY    # Browserbase
/etc/inebotten-webhook.env  # Webhook secret (legacy)
```

Alle disse er allerede i `.gitignore`.

### Miljø-variabler

```bash
# ✅ Riktig
export DISCORD_TOKEN="your-token"
python3 run_both.py

# ❌ Galt
discord_token="your-token" python3 run_both.py  # Vises i shell history
```

### Nettverk

- **Bridge kjører kun på localhost** (127.0.0.1:3000)
- **Ingen ekstern tilgang** til AI-endepunktet
- **Discord-token sendes kun til Discord's API**

### Produksjonsdeployment Sikkerhet

For multi-app VPS deployment:
- All public access går kun gjennom sentral Caddy proxy (bot.reidar.tech)
- Interne porter (3000, 8080) skal IKKE eksponeres offentlig
- Web console skal beskyttes med `CONSOLE_API_KEY` i `.env`
- Ikke bruk webhook-basert auto-update i produksjon (dette er legacy metode)
- Bruk foretrukket metode: GitHub Actions + GHCR + Ansible

---

## Token-lekkasje

### Hvis du ved et uhell committet en token:

#### Steg 1: Roter Token Umiddelbart

1. Gå til [Discord Developer Portal](https://discord.com/developers/applications)
2. Eller endre passord (hvis user token) - dette invaliderer token

#### Steg 2: Fjern Fra Git History

```bash
# Installer git-filter-repo (bedre enn filter-branch)
pip install git-filter-repo

# Fjern filen fra all historie
git filter-repo --path .env --invert-paths

# Force-push (ADVARSEL: dette endrer historie!)
git push origin --force --all
```

#### Steg 3: Sjekk for Lekkasje

```bash
# Sjekk om token finnes i historie
git log --all --full-history -- .env

# Søk etter token-mønster
git rev-list --all | xargs git grep -l "MTQ3N"
```

### Hvis token ble lekket offentlig:

1. **Roter token umiddelbart** (se over)
2. **Informer brukere** hvis de bruker samme token
3. **Overvåk konto** for uvanlig aktivitet
4. **Rapporter til oss** hvis det var sentral token

---

## Sikkerhetsfunksjoner

### Implementert

| Feature | Beskrivelse |
|---------|-------------|
| Rate Limiting | Maks 5 msg/sek, 10k/dag |
| Mention-only | Svarer kun ved @inebotten |
| Local-only Bridge | Kun localhost:3000 |
| Token Redaction | Tokens fjernes fra logger |
| JSON Storage | Ingen skylagring av data |
| OAuth for GCal | Ingen passord lagret |
| Console Auth | API-nøkkel + HttpOnly-cookie, SameSite=Strict |

### CI-sikkerhet

Vår CI sjekker automatisk:

- Hardkodede tokens (GitHub secret scanning)
- Sårbarheter i dependencies (Dependabot)
- `.env` filer i commits

---

## Kontakt

### Sikkerhetsproblemer

📧 **E-post:** [your-email@example.com]  
🔒 **PGP:** [hvis tilgjengelig]

### Andre spørsmål

- 💬 [GitHub Discussions](../../discussions)
- 🐛 [GitHub Issues](../../issues) (ikke for sikkerhet!)

---

<p align="center">
Sikkerhet er et felles ansvar. Takk for at du hjelper oss å holde Inebotten trygg!
</p>

<p align="center">
  <a href="README.md">⬅️ Tilbake til README</a>
</p>
