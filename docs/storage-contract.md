# Lagring og feiltilstand

Kalender, påminnelser, brukerminne og konsollens statistikk/sesjoner bruker et versjonert JSON-dokument:

```json
{"schema_version": 1, "document": {}}
```

Manglende fil er en ny lagring. Ugyldig JSON, feil datastruktur og ukjent skjema er en skrivebeskyttet feiltilstand. De opprinnelige bytene beholdes. Kommandoer som ikke blir lagret rapporterer feil, og manageren går tilbake til siste lagrede tilstand. Konsollens helsedata viser feiltilstanden; øktlagring med feil gir ingen innlogging.

Gyldige eldre dokumenter leses uten omskriving. Før første lagring i nytt format opprettes `<filnavn>.legacy-v0.bak` med de opprinnelige bytene og modus 0600. En eksisterende backup med annet innhold stopper migreringen. Det nye dokumentet skrives til en midlertidig fil, synkroniseres til disk og erstatter målet atomisk. Sikkerhetskopien er ikke en komplett backup av alle lagringer.

Et nyere skjema kan ikke nedgraderes gjennom vanlig lagring. En gammel binær uten dette formatet er heller ikke en trygg rollback: bruk kode som forstår formatet, eller gjenopprett en verifisert kompatibel sikkerhetskopi når tjenesten er stoppet. Ingen automatisk reparasjon eller gjenoppretting skjer ved feil. Etter en godkjent erstatning av filen lastes manageren på nytt eller tjenesten startes på nytt. Ikke slett en korrupt fil for å få en grønn helsetilstand.

Google-effekter og lokale commits er ikke én transaksjon. Oppretting og redigering starter med en lokal commit; en lokal feil etter en ekstern effekt krever kontroll av begge tilstandene. Varig synkroniseringskø og konfliktbehandling håndteres av I11. Serialisering av samtidige mutasjoner håndteres av I05. Testene bruker syntetiske data; ingen private lagringer ble migrert under utvikling.
