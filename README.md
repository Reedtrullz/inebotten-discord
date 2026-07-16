# Inebotten Discord Bot

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/discord-selfbot-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord selfbot">
  <img src="https://img.shields.io/badge/AI-LM%20Studio%20%7C%20OpenRouter-green?style=for-the-badge&logo=openai&logoColor=white" alt="AI">
  <img src="https://img.shields.io/badge/plattform-macOS%20%7C%20Windows-lightgrey?style=for-the-badge&logo=apple&logoColor=white" alt="Plattform">
</p>

<p align="center">
  <a href="https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml">
    <img src="https://github.com/Reedtrullz/inebotten-discord/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/lisens-MIT-yellow.svg" alt="MIT-lisens">
  </a>
  <a href="https://github.com/Reedtrullz/inebotten-discord/releases">
    <img src="https://img.shields.io/github/v/release/Reedtrullz/inebotten-discord" alt="Siste utgivelse">
  </a>
</p>

> En norsk Discord-selfbot for kalender, påminnelser, nyttefunksjoner og korte AI-samtaler.

Inebotten er laget for praktisk hverdagsbruk i Discord: skriv naturlig norsk, så prøver botten å forstå om du vil lagre noe i kalenderen, se status, lage avstemning, slå opp vær, eller bare chatte. Den nye intent-routeren gjør rutingen mer konservativ, slik at samtaler som "jeg skal bare høre hva du synes om RBK i morgen" ikke blir tolket som kalenderoppgaver.

## Hovedfunksjoner

| Område | Hva botten kan |
|--------|----------------|
| Samtale | AI-chat via LM Studio lokalt eller OpenRouter i skyen |
| Kalender | Hendelser, oppgaver, gjentakelser, fullføring, sletting og Google Calendar-synk |
| Intent-ruting | Typede kandidater, felles risikovurdering og konservativ AI-fallback |
| Språkdekning | Evaluert på bokmål, nynorsk, utvalgte dialektnære former og engelsk |
| Verktøy | Vær, kalkulator, valuta/temperatur, krypto, URL-forkorter og søk/dashboard |
| Sosialt | Avstemninger, sitater, dagens ord, komplimenter, horoskop og nordlysvarsel |
| Drift | Rate limiting, mention-gate, helsesjekk, Docker/VPS-oppsett og desktop-launchere |
| Web Console | Dashboard med bot-status, logger og innlogging via API-nøkkel |

## Hurtigstart

### Ferdig app

Last ned siste pakke fra [GitHub-utgivelser](https://github.com/Reedtrullz/inebotten-discord/releases):

- macOS: `Inebotten-macos.zip`
- Windows: `Inebotten.exe`

macOS kan vise en Gatekeeper-advarsel fordi appen ikke er notarized. Høyreklikk `Inebotten.app`, velg `Åpne`, og bekreft. Se [mac_app/README.md](mac_app/README.md) for detaljer.

### Kommandolinje

```bash
git clone https://github.com/Reedtrullz/inebotten-discord.git
cd inebotten-discord

python3 -m pip install -r requirements.txt
python3 setup.py
python3 scripts/run_both.py
```

På systemer med `externally-managed-environment` kan du bruke virtuelt miljø:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### Docker/VPS

For local development:

```bash
docker compose up -d
```

For deploying to the production VPS, use the Ansible playbook in `deploy/`:

```bash
ansible-playbook -i deploy/inventory/hosts.yml deploy/ansible-playbook.yml \
  --vault-password-file ~/.vault_pass.txt
```

See [deploy/README.md](deploy/README.md) for prerequisites, secrets layout,
and verification steps.

For VPS med webhook-basert auto-oppdatering (legacy):

```bash
cd /opt/inebotten-discord
sudo WEBHOOK_PORT=9000 ./scripts/deploy/install-autoupdate.sh
```

Se [docs/VPS_DEPLOYMENT.md](docs/VPS_DEPLOYMENT.md).

## Eksempler

### Kalender og påminnelser

```text
@inebotten Kan du legge inn et møte med Ola i morgen klokka 14?
@inebotten Kan du vise meg kalenderen?
@inebotten Kan du flytte møtet med Ola til fredag klokka 10?
@inebotten Kan du minne meg på å ringe legen om to timer?
@inebotten Kan du vise påminnelsene mine?
@inebotten Kan du markere påminnelse 1 som ferdig?
@inebotten Kan du slette møtet med Ola?
```

Sletting og andre destruktive handlinger blir vist for bekreftelse før de
utføres. Du kan svare naturlig med for eksempel «ja takk», «nei, avbryt» eller
en avgrenset rettelse som «i overmorgen klokka 15».

### Samtale

```text
@inebotten hei, hvordan går det?
@inebotten hva synes du om RBK i morgen?
@inebotten fortell en kort vits
```

### Flere naturlige forespørsler

```text
@inebotten Kan du lage en avstemning: Hva spiser vi? pizza, burger eller taco
@inebotten Kan du legge til bursdagen min 15. mai?
@inebotten Hvis du har tid kan du vise prisen på BTC?
@inebotten Kan du regne ut 2,5 + 1?
@inebotten Kan du fortelle meg hvor mange dager det er til jul?
@inebotten Kan du forkorte https://example.invalid?
@inebotten Kan du vise skoleferiene i Tromsø?
@inebotten Kan du sette aktiviteten til å spille CS2?
@inebotten Kan du vise hva du husker om meg?
```

## Hvordan botten forstår meldinger

Meldingen går gjennom én sikker handlingsflyt:

1. Mention-gate, normalisering og kontroll av sitater, negasjon, hypotetiske utsagn, avbrytelser og flere handlinger i samme ytring.
2. Rene funksjonsparsere lager typede kandidater. En felles arbiter velger én kandidat eller avviser/ber om presisering.
3. Eksplisitte, komplette ruter som policyen autoriserer kan utføres direkte, inkludert lesing, opprettelse og enkelte avgrensede endringer/fullføringer. Autentisering og destruktive handlinger, samt alle inferred/modelldrevne skriveforslag, legges i en kanal- og brukeravgrenset ventetilstand for bekreftelse.
4. Hvis den deterministiske ruteren ikke har nok bevis, kan modellen returnere ett strengt, inert forslag. Forslaget går gjennom samme skjema, risikovurdering og arbiter; modellen kan aldri kalle en manager eller skrive direkte.
5. Handleren mottar det validerte payloadet én gang og parser ikke originalteksten på nytt.

Et modellforslag må være én frittstående kompakt JSON-linje med nøyaktig disse toppnivåfeltene:

```json
{"action":"CALENDAR_CREATE","confidence":0.96,"slots":{"title":"Møte med Ola","date":"17.07.2026","time":"14:00"},"reply":"","clarification":null}
```

Eldre `SAVE_EVENT`-/tag-format støttes bare som `legacy compatibility` i én overgangsutgivelse. Det får ingen snarvei: innholdet konverteres til gjeldende skjema og må gjennom samme validering og bekreftelsesregler.

Språkdekningen måles av den versjonerte NLU-kontrakten. Den dekker bokmål, nynorsk, utvalgte dialektnære former og engelsk; den er ikke dokumentasjon på at alle dialekter eller vilkårlige kommandofrie formuleringer forstås.

## Prosjektstruktur

```text
inebotten-discord/
├── ai/                    # AI-koblinger, prompt og personlighet
├── cal_system/            # Kalender, Google Calendar og norsk dato-parser
├── core/                  # Konfig, auth, rate limit, intent-router og meldingsmonitor
├── features/              # Funksjoner og handlere
├── memory/                # Samtalekontekst og brukerminne
├── web_console/           # Dashboard, login og loggvisning
├── docs/                  # Norsk dokumentasjon
├── scripts/               # Start-, test- og deploy-skript
├── tests/                 # Enhets- og rutingtester
├── mac_app/               # macOS-launcher
└── windows_app/           # Windows-launcher
```

## Dokumentasjon

| Dokument | Innhold |
|----------|---------|
| [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md) | Verifisert eksempelbank for naturlige forespørsler |
| [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) | Komplett teknisk gjennomgang |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arkitektur, dataflyt og designvalg |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Utviklingsguide og testpraksis |
| [docs/SECURITY.md](docs/SECURITY.md) | Sikkerhetsmodell og hemmeligheter |
| [docs/GOOGLE_CALENDAR_SETUP.md](docs/GOOGLE_CALENDAR_SETUP.md) | Google Calendar-oppsett |
| [docs/OPENROUTER_SETUP.md](docs/OPENROUTER_SETUP.md) | OpenRouter-oppsett |
| [docs/LM_STUDIO_SETUP.md](docs/LM_STUDIO_SETUP.md) | LM Studio-oppsett |
| [docs/VPS_DEPLOYMENT.md](docs/VPS_DEPLOYMENT.md) | VPS, Docker og auto-oppdatering |
| [docs/RELEASE.md](docs/RELEASE.md) | Utgivelser og desktop-bygg |

## Utvikling og test

```bash
.venv312/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv312/bin/python -m pytest -q
```

Nyttige måltester:

```bash
.venv312/bin/python -m pytest tests/test_intent_router.py -q
.venv312/bin/python -m pytest tests/test_message_monitor_routing.py -q
.venv312/bin/python -m pytest tests/test_false_positives.py -q
.venv312/bin/python -m pytest tests/test_action_schema.py -q
.venv312/bin/python -m pytest tests/test_comprehensive.py -q
.venv312/bin/python scripts/evaluate_nlu.py \
  --corpus tests/fixtures/nlu_contract_v1.jsonl \
  --report .artifacts/nlu-contract.json
```

NLU-porten er deterministisk og bruker produksjonsparserne uten nettverk. Live LM Studio-, OpenRouter- og Discord-smoke er separate, manuelle bevis.

## Sikkerhet

Discord selfbots bryter med Discords vilkår. Bruk en dedikert testkonto, hold token og API-nøkler unna git, og bruk botten på egen risiko.

Launcher-konfigurasjon skal bare inneholde ikke-hemmelige preferanser. Hemmeligheter lagres via sikker lagring eller `.env` med stramme filrettigheter.

## Bidra

Les [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) før du sender endringer. For sikkerhetsfunn, følg [docs/SECURITY.md](docs/SECURITY.md) og ikke åpne offentlig issue.

## Lisens

MIT. Se [LICENSE](LICENSE).

<p align="center">
  <b>Språk:</b> norsk først &nbsp;|&nbsp;
  <b>AI:</b> LM Studio eller OpenRouter &nbsp;|&nbsp;
  <b>Status:</b> aktivt utviklet
</p>
