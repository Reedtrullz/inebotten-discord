# Deploy-profiler og kode-tilbakerulling

Repositoryet beskriver disse profilene. Dette er en kildeinventering, ikke en
bekreftelse på hvilken tjeneste som kjører på en bestemt maskin:

| Profil | Definisjon | Inngang / vedvarende data |
| --- | --- | --- |
| Lokal Python / launchd | `core/selfbot_runner.py`, prosjektets launchd-oppsett | Konsoll konfigurert lokalt; `HERMES_HOME` |
| `compose` | `docker-compose.yml` | Konsoll kun `127.0.0.1:8080`; `./data` som Hermes-rot |
| `compose-host-caddy` | `deploy/ansible-playbook.yml` | Konsoll kun `127.0.0.1:8081`; eksisterende host-proxy; samme datamappe |
| Eldre webhook / systemd | `scripts/deploy/` | Beholder installerte innganger; bruker samme deploy-kontrakt |
| macOS / Windows | `mac_app/`, `windows_app/` | Egen release- og launcher-kontrakt; ingen Docker-tilbakerulling |

Bundlet Caddy er en uttrykkelig opt-in Compose-profil. Deploy-verktøyet aktiverer
bare `inebotten`, og endrer ikke andre containere, proxyer eller brannmurregler.
En gammel container uten verifiserbare bildeetiketter, riktig Compose-eier og
riktig datamontasje krever en separat gjennomgang før overgang. Den fjernes ikke
som en innledende deploy-operasjon.

## Kontrakt

`python3 scripts/inebotten_deploy.py --image sha256:…` kontrollerer et eksisterende
bilde uten å aktivere det. `--build` bygger først et privat, midlertidig
`git archive` av en ren, fullstendig committet kilde. Ignorerte `.env`, data,
virtuelle miljøer og lokale eksportfiler følger ikke med. Python 3.12 eller nyere,
Docker og Compose **2.24.4 eller nyere** (`!override`) kreves. Se [Docker sin merge-kontrakt](https://docs.docker.com/reference/compose-file/merge/) og [HEALTHCHECK](https://docs.docker.com/reference/dockerfile/#healthcheck).

Bildeetikettene og `.deployment/deployment.json` binder full 40-tegns revisjon,
Docker **image ID** (`sha256:`), konfigurasjonsskjema 1 og lesbart dataskjema 0–3.
Image ID er en lokal innholdsdigest, ikke en registry distribution digest.
Skjema 0 betyr eldre dokumenter som fortsatt kan leses; ingen automatisert
migrering eller flytting av gamle delte/private scopes utføres av deploy-verktøyet.
Kalender og påminnelser skriver skjema 2 når nye forekomstdata lagres. Et tidligere
bilde som bare støtter skjema 1 kan da ikke startes som kode-tilbakerulling;
tjenesten beholdes stoppet og krever gjennomgått gjenoppretting.

Preflight avviser skitten kilde, mindre enn 30 GiB fri plass, opptatt port uten
verifisert eksisterende tjeneste, feil revisjon, utrygge filer/montasjer,
inkompatible dataskjemaer og manglende tidligere bildebevis. Bare de fem eide
lagrene inspiseres; innhold, tokenfiler, logger og OAuth-filer rapporteres ikke.
Konfigurasjonen roteres ikke. En lokal, midlertidig innholdsdigest oppdager endringer under deploy; ingen konfigurasjonsverdier eller digest skrives i rapporten. Den eksisterende `.env` må være en vanlig fil,
og data-roten må være forhåndsprovisjonert for UID 10001. Eksisterende private
filer får ikke rekursiv `chown`.

En første installasjon må velges med `--first-install`, uten tidligere container
eller eide datalagere. Opprett en ny tom datarot med passende eierskap eksplisitt;
bruk ikke dette valget til å omgå gjennomgang av et eksisterende datasett.

## Aktivering og kode-tilbakerulling

`--apply` er den uttrykkelige aktiveringen. Før containeren stoppes, beholdes det
forrige immutable bildet med en digestbundet `inebotten-rollback:`-tagg og en
privat manifestfil. Deretter stoppes den eide tjenesten, schema-kompatibilitet
kontrolleres igjen, og bare det nye bildet startes. Ingen bildepruning utføres.

En vellykket deploy krever både nøyaktig container-image ID og `/health` med
`status=healthy`, full forventet `revision` og aggregert `readiness=ready`.
Dette inkluderer de påkrevde delsystemene, ikke bare at HTTP-porten svarer.
Probe og oppstart har tidsfrister. Docker HEALTHCHECK bruker samme offentlige,
minimale kontrakt; autentiserte diagnosefelt og persondata eksponeres ikke.

Ved feil stoppes kandidaten før ny schema-kontroll. Hvis det gamle bildet fortsatt
kan lese dataene, startes det igjen og må bestå sin egen eksakte readiness-sjekk.
Deploy-kommandoen returnerer likevel feil og skriver `rolled_back`, ikke suksess.
Hvis data er korrupte/utrygge eller et nyere schema er skrevet, holdes kandidaten
stoppet med `rollback_blocked_data`. Begge kodebildene og eksisterende data
beholdes for gjennomgang. Endret konfigurasjon under løpet blokkerer aktivering eller rollback med en egen feilkode. Tjenestens tidligere konfigurasjon kan ikke rekonstrueres
fra et image; kompatibel, uendret konfigurasjon er en forutsetning for kode-rollback.

Kode-rollback endrer **ingen** lagringsbytes og er ikke en data-restore. Andre
skrivere må være stoppet under vedlikeholdet; deploy-låsen serialiserer bare
samarbeidende deploy-operatører. Data-restore og flerlagermigrering krever separat
quiescence, et konsistent I35-bundle, validering og eksplisitt destinasjonsgjennomgang
beskrevet i backup-dokumentasjonen. `--apply` er ikke godkjenning av data-restore.

## Før en faktisk deploy

Denne endringen er verifisert med disposable Git-repositorier, inert Docker-adapter,
fixture-store-checksummer, shell/YAML-kontroller og lokale tester. Den bekrefter
ikke live Docker, produksjonskonti eller en faktisk server-tilbakerulling.

Før et separat autorisert live-løp: bekreft aktuell tjeneste, backup-resultat,
ledig disk, alle containerporter, eksisterende rollback-image og uendret kompatibel
konfigurasjon/data. Inspiser SSH-innstillinger med `ssh -G Racknerd-Deploy`;
bruk deploy-brukeren og identitetssperrene `IdentitiesOnly=yes`, `IdentityAgent=none`.
Ikke aktiver root-SSH. En grønn lokal test erstatter ikke et vellykket, ferskt
backup-resultat eller etterfølgende revisjons- og synlig UI-verifikasjon.

Ansible og den eldre updateren stopper på kildefeil. Updateren bruker bare
fast-forward, aldri hard reset, og deler samme readiness/rollback-verktøy.
Webhook-installasjon, secret-rotasjon og tjenesteaktivering er egne operatørhandlinger.
