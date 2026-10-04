# Lagring og feiltilstand

Kalender, påminnelser, brukerminne og konsollens statistikk/sesjoner bruker et versjonert JSON-dokument:

```json
{"schema_version": 1, "document": {}}
```

Manglende fil er en ny lagring. Ugyldig JSON, feil datastruktur og ukjent skjema er en skrivebeskyttet feiltilstand. De opprinnelige bytene beholdes. Kommandoer som ikke blir lagret rapporterer feil, og manageren går tilbake til siste lagrede tilstand. Konsollens helsedata viser feiltilstanden; øktlagring med feil gir ingen innlogging.

Gyldige eldre dokumenter leses uten omskriving. Før første lagring i nytt format opprettes `<filnavn>.legacy-v0.bak` med de opprinnelige bytene og modus 0600. En eksisterende backup med annet innhold stopper migreringen. Det nye dokumentet skrives til en midlertidig fil, synkroniseres til disk og erstatter målet atomisk. Sikkerhetskopien er ikke en komplett backup av alle lagringer.

Et nyere skjema kan ikke nedgraderes gjennom vanlig lagring. En gammel binær uten dette formatet er heller ikke en trygg rollback: bruk kode som forstår formatet, eller gjenopprett en verifisert kompatibel sikkerhetskopi når tjenesten er stoppet. Ingen automatisk reparasjon eller gjenoppretting skjer ved feil. Etter en godkjent erstatning av filen lastes manageren på nytt eller tjenesten startes på nytt. Ikke slett en korrupt fil for å få en grønn helsetilstand.

Google-effekter og lokale commits er ikke én transaksjon. Oppretting og redigering starter med en lokal commit; en lokal feil etter en ekstern effekt krever kontroll av begge tilstandene. Varig synkroniseringskø og konfliktbehandling håndteres av I11. Samtidige mutasjoner serialiseres av lagringens eier. Testene bruker syntetiske data; ingen private lagringer ble migrert under utvikling.


Managerne bruker én privat kopi per mutasjon og gir kopier tilbake til lesere. Async-mutatorer køes per lagring. Synkrone mutatorer som møter en aktiv async-mutator avvises med `store_busy`; de blokkerer ikke hendelsesløkken. Interne nestede kall deler samme transaksjon, men en ny asyncio-task arver ikke tilgang til den private kopien. Filarbeidere mottar kopierte data, med høyst én mutasjonsarbeider per lagring. Kansellering venter på filarbeiderens resultat før transaksjonen slippes; en allerede lagret endring kan derfor være fullført selv om den opprinnelige tasken ble kansellert.

Før første mutasjon holdes en OS-lås på `<filnavn>.lock` gjennom eierens levetid. POSIX bruker `flock(LOCK_EX|LOCK_NB)`, Windows bruker `msvcrt.locking(LK_NBLCK)` på byte 0. En annen skriver avvises før mutasjon, også i samme prosess. Rene lesere kan åpne dokumentet. Låsfilen inneholder ingen applikasjonsdata og skal ikke slettes mens eiere kan være aktive; et nytt inode ville omgå låsen. Ved ny overtakelse lastes et dokument som ble endret siden konstruksjon på nytt. Eierens `close()` frigir låsen; prosessavslutning gjør det også. Låsen er rådgivende og støtter lokal disk, ikke en garanti for nettverksfilsystemer eller eldre skrivere som ignorerer adapteren.

`VersionedJsonStore.snapshot()` gir revisjon og kopi; `mutate(expected_revision, change)` avviser en gammel revisjon og publiserer først etter vellykket commit. Revisjonen lagres i dokumentkonvolutten. Eldre konvolutter uten revisjon leses som revisjon 0. Konsollens read/merge/commit ligger under samme trådlås. Kalenderens Google-link oppdateres gjennom en eid mutasjon; endring av en returnert kopi lagrer ingenting.

Testet krasjgrense: prosessavslutning før/etter atomisk replace etterlater et komplett gammelt eller nytt dokument og frigir OS-låsen. Filens innhold fsync-es før replace. Katalogen fsync-es ikke, så strømbrudd/diskmaskinvare gir ingen ekstra varighetsgaranti. En hardt avsluttet prosess kan etterlate en privat tempfil; den leses aldri som det autoritative dokumentet. Windows-adapteren har en egen CI-jobb, men lokal macOS-verifikasjon er ikke bevis for at den jobben har passert.
