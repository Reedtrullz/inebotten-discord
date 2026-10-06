# Utgivelser

GitHub Actions har ett publiseringsansvar: `.github/workflows/release.yml` reagerer på `v*`-tagger, venter på hele CI-suiten, kontrakttestene og begge plattformbyggene, kontrollerer bevisene fra nøyaktig samme tag og oppretter deretter utgivelsen. CI- og bygg-workflowene kan kjøres uten publisering; bygg-workflowen kan også kjøres manuelt for å bygge en valgt gren, tagg eller commit.

## Automatisk utgivelse

Lag og push en semantisk versjonstag:

```bash
git tag -a v2.1.0 -m "Utgivelse v2.1.0"
git push origin v2.1.0
```

Release-workflowen sender den fullstendige taggreferansen til både den gjenbrukbare CI-workflowen og desktop-bygg-workflowen. Hvert jobbsett sjekker ut denne referansen. Desktop-byggeren bekrefter at checkoutens commit-SHA samsvarer med den valgte referansen og utleder appversjonen fra taggen. Publisering venter på hele CI-suiten, release-kontrakttestene, macOS-bygg og røyketest, Windows-bygg og røyketest, og kontroll av de to byggbevisene.

Utgivelsen inneholder per plattform en ZIP-fil, en JSON-manifestfil og en røyketestkvittering, samt `SHA256SUMS`. Manifestet binder sammen full commit-SHA, valgt ref, tagg, versjon, OS/arkitektur, hash av `requirements/desktop.lock`, artefakthash og røyketestkvittering. Publiseringsjobben kontrollerer disse verdiene mot checkouten før den oppretter utgivelsen.

Låsfilens SHA-256 beregnes med LF-linjeskift. Git kan bruke CRLF på Windows; denne forskjellen skal ikke endre identiteten til den samme låste avhengighetsgrafen. Alle andre byte inngår fortsatt i hashen. Den vanlige byggeworkflowen kontrollerer nå begge plattformenes artefakter med publiseringskontrakten på Linux, også når ingen utgivelse skal publiseres. Dermed oppdages forskjeller mellom byggeren og publiseringsjobben før en tagget utgivelse.

## Manuell, ikke-publiserende bygging

Velg **Build Desktop Apps → Run workflow** i GitHub Actions. Fyll eventuelt inn `ref` med grenen, taggen eller committen som skal bygges. Hvis feltet er tomt, brukes workflowens valgte ref. `version` er valgfritt; for en versjonstagg må verdien stemme med taggen, og for en gren eller commit er standardversjonen `2.0.0`. Uoverensstemmelse avvises. Denne kjøringen laster opp tidsbegrensede CI-bevis og oppretter ingen GitHub-utgivelse.

## Lokal macOS-bygging

Opprett et eget miljø og installer bare den hash-låste desktop-profilen fra PyPI. Python-distribusjonen må også ha en fungerende Tcl/Tk-runtime for GUI-launcheren; dette leveres ikke av desktop-låsefilen:

```bash
python3 -m venv .superpowers/desktop-env
.superpowers/desktop-env/bin/python -m pip install \
  --require-hashes --index-url https://pypi.org/simple \
  -r requirements/desktop.lock
.superpowers/desktop-env/bin/python scripts/build_desktop.py macos \
  --ref refs/heads/master \
  --output-dir .superpowers/receipts/release
```

Byggeren nekter å merke en checkout med en annen refs commit og avviser lokale kildeendringer. Den bruker én felles definisjon av versjon, appmetadata, pakkefiler og skjulte importer for begge plattformene. Før den skriver manifestet, starter den det frosne programmet med `--smoke-artifact`. Denne tidlige banen kontrollerer de pakkede filene, blokkerer nettverkstilgang og avslutter før Tk, konfigurasjonsmapper, private data eller tjenester lastes inn.

De eldre plattformkommandoene videresender til den samme byggeren:

```bash
mac_app/build.sh --ref refs/heads/master
python windows_app/build.py --ref refs/heads/master
```

Begge krever at den låste desktop-profilen allerede er installert i det aktive Python-miljøet. Kommandoene installerer eller oppgraderer ikke pakker.

Byggeren kontrollerer installerte pakkeversjoner mot alle aktive krav i
desktop-låsen, inkludert plattformmarkører. Manglende eller avvikende pakker
avvises. Dette erstatter ikke pip sin hashverifiserte installasjon; CI utfører
begge kontrollene. PyInstaller og modulinnsamling får bare et tillatt sett
miljøvariabler og egne midlertidige hjemme-/konfigurasjonsmapper, uten arvede
Discord-/provider-nøkler eller Python-importoverstyringer. Den avgrensede
røyketestens Python-nettverksvakt er ikke en OS-sandbox.

## Bevis og akseptgrenser

macOS-byggeren setter endelige Info.plist-verdier før den fornyer appens ad-hoc-signatur. Den kontrollerer hele signaturen med `codesign --verify --deep --strict`, pakker ZIP-filen og gjentar kontrollen etter native utpakking med `ditto`. Signaturfeil stopper byggingen før et utgivelsesmanifest kan opprettes. Denne lokale integritetskontrollen er ikke Developer ID-signering eller Apple-notarisering; en nedlastet ad-hoc-signert app kan fortsatt kreve uttrykkelig godkjenning i macOS.

Kontrollerte artefakter viser hvilken commit og plattform som ble bygget, at de påkrevde kilde- og datafilene finnes i pakken, at den frosne entrypointen kan kjøre den avgrensede røyketesten uten nettverk, og at artefakt og kvittering samsvarer med SHA-256-manifestet. Dette verifiserer ikke Discord-innlogging, eksterne tjenester, brukeroppsett, tilgjengelighet, kodesignering, notarization eller installasjon på en annen maskin. Windows-bygg og signering må bekreftes på Windows og med en faktisk sertifikatbasert signeringsjobb. Workflowen hevder ikke sertifisert signering; selv ad-hoc-signering er ikke et sertifisert distribusjonsstempel.

## Tidligere publiserings- og pakkeavvik

Før denne kontrakten publiserte både release-workflowen og desktop-bygg-workflowen. macOS Python-byggeren utelot `scripts/run_both.py` og `web_console`, mens macOS shell-byggeren og Windows-byggeren pakket scripts, men utelot `web_console`. Den felles kontrakten krever nå blant annet `scripts/run_both.py`, `ai`, `cal_system`, `core`, `features`, `memory`, `utils`, `web_console/templates`, `web_console/static`, AI-promptene og skolekalenderdataene; bygg og røyketest stopper hvis noe mangler.
